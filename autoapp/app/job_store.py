"""
Creating, changing and deleting jobs.

A job is saved whole: the editor sends the job with all its steps and their
parameters, in the order the steps should run. Saving works out what changed,
applies it, and records it in the audit log.

Rules:
  - A step keeps its identity when it is changed or moved, so the operations it
    has already recorded stay linked to it. A step left out of a save is deleted.
  - A parameter with a blank value is not stored; the step type's default applies.
  - A job that has run history cannot be deleted, only disabled, so its history
    keeps its link.
"""
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Union

from sqlalchemy.orm import Session, object_session

from app.models import Audit, Job, JobRun, JobStep, JobStepParameter, StepType, Variable, utcnow
from app.schemas import JobDetail, JobSave, JobStepOut, JobStepSave, VariableOut
from app import outside_store, reaction_store, workflow_store
from engine import return_codes, step_tree
from engine.handlers import HANDLER_REGISTRY
from engine.handlers.flow import BRANCH_NAMES, BRANCHES, structure_problems, top_level_problems

# A variable is written ${Name} in a value, so its name is kept to what that can hold unambiguously
VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def name_from_title(title: Optional[str], position: Union[int, str]) -> str:
    """
    A StepName made from a step's title, as the editor makes it: spaces become underscores and
    anything else a name cannot hold is dropped. "Check files (EU)" gives Check_files_EU.
    A title that leaves nothing usable gives Step<position>.
    """
    name = re.sub(r"[^A-Za-z0-9_]", "", re.sub(r"\s+", "_", (title or "").strip()))
    name = name.strip("_")[:64]
    if not name:
        return f"Step{position}"
    return name if name[0].isalpha() else ("Step_" + name)[:64]


class JobStoreError(Exception):
    """A save or delete that cannot be done. status is the HTTP status to answer with."""
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def inherited_variables(db: Session, job: Job) -> list:
    """What a job's tags give it, secrets masked, marking those its own variables override."""
    from app import tag_store
    view = tag_store.variables_view(db, tag_store.paths_on(job), [v.VarName for v in job.variables])
    return view["variables"]


def _describe_steps(nodes: List[step_tree.Node]) -> List[JobStepOut]:
    return [
        JobStepOut(
            id=node.step.id,
            order=node.step.StepOrder,
            number=node.number,
            title=node.step.Title,
            name=node.step.StepName,
            active=bool(node.step.IsActive),
            on_failure=node.step.OnFailure or "FAIL_JOB",
            step_type=node.step.step_type.HandlerClass,
            step_type_name=node.step.step_type.TypeName,
            parameters={p.ParamName: p.ParamValue for p in node.step.parameters},
            children=_describe_steps(node.children),
        )
        for node in nodes
    ]


def describe_job(job: Job) -> JobDetail:
    from app import tag_store
    db = object_session(job)
    return JobDetail(
        job_key=job.JobKey,
        job_type=job.JobType or "STEPS",
        description=job.Description,
        active=bool(job.IsActive),
        success_return_codes=job.SuccessReturnCodes,
        created=job.CreatedDateTime,
        created_by=job.CreatedBy,
        modified=job.ModifiedDateTime,
        modified_by=job.ModifiedBy,
        steps=_describe_steps(step_tree.build(job.steps)),
        variables=describe_variables(job.variables),
        tags=tag_store.paths_on(job),
        inherited_variables=inherited_variables(db, job) if db is not None else [],
        items=workflow_store.describe_items(job) if job.JobType == "WORKFLOW" else [],
        succeeds_when=job.SucceedsWhen, return_code_from=job.ReturnCodeFrom,
        used_in=workflow_store.workflows_using(db, job) if db is not None else [],
        reactions=reaction_store.describe(job.reactions),
    )


def _stored(parameters: dict) -> dict:
    """The parameters worth storing: those with a value."""
    return {name: value for name, value in parameters.items() if value is not None and str(value).strip() != ""}


def _audit(db: Session, job: Optional[Job], action: str, who: str, details: dict) -> None:
    db.add(Audit(MasterObject_id=job.MasterObject_id if job else None, Action=action,
                 PerformedBy=who, Details=json.dumps(details)))


def _name(title: Optional[str], position: int) -> str:
    return f"step {position} ('{title}')" if title else f"step {position}"


def describe_variables(variables) -> List[VariableOut]:
    """Variables as the page sees them, in name order. A secret's value never leaves the server."""
    return [VariableOut(name=v.VarName, value=None if v.IsSecret else v.VarValue, secret=bool(v.IsSecret),
                        description=v.Description)
            for v in sorted(variables, key=lambda v: (v.VarName.lower(), v.VarName))]


def apply_variables(job, submitted: list, creating: bool, model=Variable) -> List[str]:
    """
    Makes the variables of a job (or of any other object that can hold variables) match the
    list submitted. Returns what changed, naming variables but never values. model: the kind
    of row they are kept in (WorkflowItemVariable for a use of a job in a workflow).
    """
    names = [v.name.strip() for v in submitted]
    for name in names:
        if not VARIABLE_NAME_PATTERN.match(name):
            raise JobStoreError(
                f"Invalid variable name '{name}': use letters, digits and underscores, starting with a letter or underscore.")
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise JobStoreError(f"The variable '{repeated[0]}' is listed more than once.")

    have = {v.VarName: v for v in job.variables}
    added, changed, removed = [], [], []
    for wanted in submitted:
        name = wanted.name.strip()
        description = (wanted.description or "").strip() or None
        blank = wanted.value is None or wanted.value == ""
        variable = have.get(name)
        if variable is None:
            job.variables.append(model(VarName=name, VarValue=wanted.value or "", IsSecret=wanted.secret,
                                          Description=description))
            added.append(name)
            continue
        # A secret is never sent back to the page, so a blank value for one that exists means "leave it"
        keep_value = blank and bool(variable.IsSecret) and wanted.secret
        new_value = variable.VarValue if keep_value else (wanted.value or "")
        if (new_value, wanted.secret, description) != (variable.VarValue, bool(variable.IsSecret), variable.Description):
            variable.VarValue, variable.IsSecret, variable.Description = new_value, wanted.secret, description
            changed.append(name)
    for name, variable in have.items():
        if name not in names:
            job.variables.remove(variable)
            removed.append(name)

    if creating:
        return []
    changes = []
    for verb, which in (("Added", added), ("Changed", changed), ("Removed", removed)):
        if which:
            changes.append(f"{verb} variable{'' if len(which) == 1 else 's'} {', '.join(sorted(which))}.")
    return changes


@dataclass
class _Entry:
    """One submitted step, where it sits, and (once applied) the JobStep it is saved as."""
    submitted: JobStepSave
    parent: Optional["_Entry"]
    position: int                   # among the steps of the same block
    number: str                     # 3.1; a Then, ElseIf or Else has its If's
    children: List["_Entry"] = field(default_factory=list)
    step: Optional[JobStep] = None

    @property
    def code(self) -> str:
        return self.submitted.step_type

    @property
    def label(self) -> str:
        """How the audit log names it: step 3.1 ('Copy'), or step 3's Else."""
        if self.code in BRANCHES:
            return f"step {self.number}'s {BRANCH_NAMES[self.code].split(' ')[1]}"
        return _name(self.submitted.title, self.number)


def _flatten(steps: List[JobStepSave], parent: Optional[_Entry] = None, prefix: str = "",
             counter: Optional[List[int]] = None) -> List[_Entry]:
    """Every submitted step, each block before the steps inside it, numbered as the job log numbers them."""
    counter = counter if counter is not None else [0]
    entries = []
    for position, submitted in enumerate(steps, start=1):
        if submitted.step_type in BRANCHES:         # keeps its If's number and count
            entry = _Entry(submitted, parent, position, parent.number if parent else "")
            below = _flatten(submitted.children, entry, prefix, counter)
        else:
            counter[0] += 1
            number = f"{prefix}.{counter[0]}" if prefix else str(counter[0])
            entry = _Entry(submitted, parent, position, number)
            below = _flatten(submitted.children, entry, number, [0])
        if parent:
            parent.children.append(entry)
        entries += [entry] + below
    return entries


def _check_submitted(entries: List[_Entry], step_types: dict) -> None:
    """Refuses a save whose steps are of unknown types, or are not held as their types allow."""
    for entry in entries:
        if entry.code not in step_types:
            raise JobStoreError(f"{_capital(entry.label)}: there is no step type '{entry.code}'.")
    for problem in top_level_problems([e.code for e in entries if e.parent is None]):
        raise JobStoreError(problem)
    for entry in entries:
        handler = HANDLER_REGISTRY.get(entry.code)
        problems = structure_problems(entry.code, [c.code for c in entry.children], bool(handler and handler.BLOCK))
        if problems:
            raise JobStoreError(f"{_capital(entry.label)} {problems[0]}")
        if entry.submitted.on_failure not in JobStep.ON_FAILURE:
            raise JobStoreError(f"{_capital(entry.label)}: On failure must be one of {', '.join(JobStep.ON_FAILURE)}, "
                                f"not '{entry.submitted.on_failure}'.")
        name = (entry.submitted.name or "").strip() or None
        if name is not None and not JobStep.NAME_PATTERN.match(name):
            raise JobStoreError(f"{_capital(entry.label)}: '{name}' cannot be a step name. Use letters, digits and "
                                f"underscores, starting with a letter.")


def _capital(text: str) -> str:
    return text[0].upper() + text[1:]


def _step_name(entry: _Entry, saved: Optional[JobStep] = None) -> Optional[str]:
    """
    The StepName to save: as given; else the one it has, as other steps may use it; else one
    made from the title. A Then, ElseIf or Else has none.
    """
    if entry.code in BRANCHES:
        return None
    given = (entry.submitted.name or "").strip()
    return given or (saved.StepName if saved else None) or name_from_title(
        entry.submitted.title, entry.number.replace(".", "_"))


def _apply_parameters(step: JobStep, wanted: dict) -> bool:
    """Makes a step's stored parameters match wanted. Returns whether anything changed."""
    have = {p.ParamName: p for p in step.parameters}
    if {n: p.ParamValue for n, p in have.items()} == wanted:
        return False
    for name, parameter in have.items():
        if name not in wanted:
            step.parameters.remove(parameter)
        else:
            parameter.ParamValue = wanted[name]
    for name, value in wanted.items():
        if name not in have:
            step.parameters.append(JobStepParameter(ParamName=name, ParamValue=value))
    return True


def _update_step(step: JobStep, entry: _Entry, step_types: dict) -> List[str]:
    """Changes a saved step to match what was submitted. Returns what changed, in words."""
    submitted, parent = entry.submitted, entry.parent.step if entry.parent else None
    name = _step_name(entry, step)
    wanted = {"title": (submitted.title, step.Title), "name": (name, step.StepName),
              "on failure": (submitted.on_failure, step.OnFailure)}
    what = [field_name for field_name, (new, old) in wanted.items() if (new or "") != (old or "")]
    if not step.StepName and not (submitted.name or "").strip() and "name" in what:
        what.remove("name")             # a step saved before names existed is given one, unasked: not a change
    step.Title, step.StepName, step.OnFailure = submitted.title, name, submitted.on_failure
    if submitted.active != bool(step.IsActive):
        what.append("enabled" if submitted.active else "disabled")
        step.IsActive = submitted.active
    if step.step_type.HandlerClass != submitted.step_type:
        what.append("step type")
        # The relationship, not just the id, so a preview (which never commits) sees the new type
        step.step_type = step_types[submitted.step_type]
    if _apply_parameters(step, _stored(submitted.parameters)):
        what.append("parameters")
    if step.parent is not parent:
        what.append("moved into " + (parent_label(entry.parent) if entry.parent else "the top level"))
        step.parent = parent
    step.StepOrder = entry.position
    return what


def parent_label(entry: _Entry) -> str:
    """The block a step was moved into, for the audit log: step 3, or step 3's Else."""
    return entry.label.split(" (")[0] if entry.code not in BRANCHES else entry.label


def _apply_steps(job: Job, entries: List[_Entry], step_types: dict, creating: bool) -> List[str]:
    """Makes the job's steps match those submitted, keeping each saved step's identity."""
    current = {step.id: step for step in job.steps}
    submitted_ids = [e.submitted.id for e in entries if e.submitted.id is not None]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise JobStoreError("The same step was submitted twice.")
    for step_id in submitted_ids:
        if step_id not in current:
            raise JobStoreError(f"Step id {step_id} does not belong to job '{job.JobKey}'.")
    old_order = [s.id for s in step_tree.in_order(current.values()) if s.id in submitted_ids]

    changes = []
    for entry in entries:               # each block before the steps inside it, so its JobStep exists first
        submitted = entry.submitted
        if submitted.id is None:
            entry.step = JobStep(job_id=job.MasterObject_id, StepType_id=step_types[submitted.step_type].id,
                                 StepOrder=entry.position, Title=submitted.title, StepName=_step_name(entry),
                                 IsActive=submitted.active, OnFailure=submitted.on_failure,
                                 parent=entry.parent.step if entry.parent else None)
            entry.step.parameters = [JobStepParameter(ParamName=n, ParamValue=v)
                                     for n, v in _stored(submitted.parameters).items()]
            job.steps.append(entry.step)
            if not creating and not (entry.parent and entry.parent.submitted.id is None):
                changes.append(f"Added {entry.label}.")
            continue
        entry.step = current[submitted.id]
        what = _update_step(entry.step, entry, step_types)
        if what:
            changes.append(f"Changed {entry.label}: {', '.join(what)}.")

    removed = {step_id for step_id in current if step_id not in submitted_ids}
    for step_id in removed:
        step = current[step_id]
        if step.ParentStep_id not in removed:   # the steps inside a removed block go with it, unmentioned
            changes.append(_removed(step))
        job.steps.remove(step)

    if not creating and old_order != submitted_ids:
        changes.append("Reordered the steps.")
    return changes


def _removed(step: JobStep) -> str:
    code = step.step_type.HandlerClass
    if code in BRANCHES and step.parent is not None:
        return f"Removed {BRANCH_NAMES[code]} from step '{step.parent.Title or step.parent.StepName}'."
    return f"Removed step '{step.Title}'." if step.Title else "Removed a step."


def save_job(db: Session, payload: JobSave, existing_key: Optional[str], who: str) -> tuple:
    """
    Creates the job (existing_key is None) or changes the job with that key, and
    records the change. Returns (job, changes), where changes says in words what
    the save did. Raises JobStoreError if it cannot be done.
    """
    job, changes = apply_job(db, payload, existing_key, who)
    if changes:
        _audit(db, job, "JOB_CREATED" if existing_key is None else "JOB_UPDATED", who,
               {"job_key": job.JobKey, "changes": changes})
    db.commit()
    db.refresh(job)
    return job, changes


def apply_job(db: Session, payload: JobSave, existing_key: Optional[str], who: str) -> tuple:
    """
    Makes the changes a save would make, in the current transaction, without
    committing or recording them. save_job commits them; a preview looks at the
    result and rolls it back.
    """
    creating = existing_key is None
    if creating:
        job = None
    else:
        job = db.query(Job).filter(Job.JobKey == existing_key).first()
        if not job:
            raise JobStoreError(f"No job with JobKey '{existing_key}' exists.", status=404)

    new_key = payload.job_key.strip()
    if (creating or new_key != job.JobKey) and db.query(Job.MasterObject_id).filter(Job.JobKey == new_key).first():
        raise JobStoreError(f"A job with JobKey '{new_key}' already exists.", status=409)

    job_type = _check_type(payload, job)
    success_codes = _success_codes(payload)
    step_types = {t.HandlerClass: t for t in db.query(StepType)}
    entries = _flatten(payload.steps)
    _check_submitted(entries, step_types)

    changes: List[str] = []
    try:
        if creating:
            job = Job(JobKey=new_key, JobType=job_type, Description=payload.description, IsActive=payload.active,
                      SuccessReturnCodes=success_codes, CreatedBy=who)
            db.add(job)
            db.flush()
            changes.append(f"Created {'workflow' if job_type == 'WORKFLOW' else 'job'} '{new_key}'.")
        else:
            if new_key != job.JobKey:
                changes.append(f"Renamed from '{job.JobKey}' to '{new_key}'.")
                job.JobKey = new_key
            if (payload.description or "") != (job.Description or ""):
                changes.append("Changed the description.")
                job.Description = payload.description
            if payload.active != bool(job.IsActive):
                changes.append("Enabled the job." if payload.active else "Disabled the job.")
                job.IsActive = payload.active
            if success_codes != job.SuccessReturnCodes:
                changes.append(f"Success return codes are now {success_codes or '0'}.")
                job.SuccessReturnCodes = success_codes
    except ValueError as e:                 # the JobKey is not a usable name
        raise JobStoreError(str(e))

    if job_type == "WORKFLOW":
        try:
            renamed = {} if creating else workflow_store.renames(job, payload.items)
            changes += workflow_store.apply_items(db, job, payload.items, creating, renamed)
            changes += workflow_store.apply_completion(job, payload.succeeds_when, payload.return_code_from,
                                                       creating, renamed)
        except workflow_store.WorkflowError as e:
            raise JobStoreError(str(e))
    else:
        changes += _apply_steps(job, entries, step_types, creating)

    if payload.reactions is not None:
        try:
            reaction_store.check(db, "The job", payload.reactions, job)
        except reaction_store.ReactionError as e:
            raise JobStoreError(str(e))
        if reaction_store.apply(db, job.reactions, payload.reactions, {"Job_MasterObject_id": job.MasterObject_id}) \
                and not creating:
            changes.append("Changed the Reactions.")

    if payload.variables is not None:
        changes += apply_variables(job, payload.variables, creating)

    if payload.tags is not None:
        from app import tag_store
        tag_changes = tag_store.apply_tags(db, job, payload.tags)
        if not creating:
            changes += tag_changes

    if changes and not creating:
        job.ModifiedDateTime = utcnow()
        job.ModifiedBy = who
    db.flush()
    return job, changes


def _check_type(payload: JobSave, job: Optional[Job]) -> str:
    """The job's type: as submitted for a new job; a saved job's type never changes."""
    job_type = (payload.job_type or "STEPS").strip().upper()
    if job_type not in Job.TYPES:
        raise JobStoreError(f"'{payload.job_type}' is not a type of job. A job is STEPS or WORKFLOW.")
    if job is not None and job_type != (job.JobType or "STEPS"):
        raise JobStoreError(f"'{job.JobKey}' is a {'workflow' if job.JobType == 'WORKFLOW' else 'job made of steps'}, "
                            f"and a job's type cannot be changed. Make a new one instead.")
    if job_type == "WORKFLOW" and payload.steps:
        raise JobStoreError("A workflow is made of jobs, not steps. Put the steps in a job and add that job to the workflow.")
    if job_type == "STEPS" and payload.items:
        raise JobStoreError("Only a workflow is made of other jobs. Create a workflow to run jobs together.")
    return job_type


def _success_codes(payload: JobSave) -> Optional[str]:
    problem = return_codes.problem(payload.success_return_codes) if (payload.success_return_codes or "").strip() else None
    if problem:
        raise JobStoreError(f"Success return codes: {problem}")
    return return_codes.normal(payload.success_return_codes)


def delete_job(db: Session, job_key: str, who: str) -> None:
    """Deletes a job that has never run and that no workflow uses. Raises JobStoreError otherwise."""
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    if not job:
        raise JobStoreError(f"No job with JobKey '{job_key}' exists.", status=404)
    using = workflow_store.workflows_using(db, job)
    if using:
        raise JobStoreError(f"Job '{job_key}' is used by the workflow{'s' if len(using) > 1 else ''} "
                            f"{', '.join(repr(k) for k in using)}, so it cannot be deleted. Take it out of "
                            f"{'them' if len(using) > 1 else 'it'} first.", status=409)
    waiting = outside_store.waiting_for_workflow(db, job) if job.JobType == "WORKFLOW" else []
    if waiting:
        raise JobStoreError(f"Workflow '{job_key}' cannot be deleted: {', '.join(waiting)} "
                            f"wait{'s' if len(waiting) == 1 else ''} for it or for a job in it. Change what they wait for first.",
                            status=409)
    starters = reaction_store.started_by(db, job)
    if starters:
        raise JobStoreError(f"Workflow '{job_key}' is started by Reactions of {', '.join(starters)}, so it cannot be "
                            f"deleted. Change those Reactions first.", status=409)
    runs = db.query(JobRun).filter((JobRun.Job_MasterObject_id == job.MasterObject_id) | (JobRun.JobKey == job_key)).count()
    if runs:
        raise JobStoreError(
            f"Job '{job_key}' has run {runs} time{'' if runs == 1 else 's'}, so it cannot be deleted. "
            f"Disable it instead: its history then keeps its link to the job.", status=409)

    _audit(db, None, "JOB_DELETED", who, {"job_key": job_key, "changes": [f"Deleted job '{job_key}'."]})
    db.delete(job)
    db.commit()

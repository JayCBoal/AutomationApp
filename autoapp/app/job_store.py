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
from typing import List, Optional

from sqlalchemy.orm import Session, object_session

from app.models import Audit, Job, JobRun, JobStep, JobStepParameter, StepType, Variable, utcnow
from app.schemas import JobDetail, JobSave, JobStepOut, VariableOut

# A variable is written ${Name} in a value, so its name is kept to what that can hold unambiguously
VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def describe_job(job: Job) -> JobDetail:
    from app import tag_store
    db = object_session(job)
    return JobDetail(
        job_key=job.JobKey,
        description=job.Description,
        active=bool(job.IsActive),
        created=job.CreatedDateTime,
        created_by=job.CreatedBy,
        modified=job.ModifiedDateTime,
        modified_by=job.ModifiedBy,
        steps=[
            JobStepOut(
                id=step.id,
                order=step.StepOrder,
                title=step.Title,
                active=bool(step.IsActive),
                step_type=step.step_type.HandlerClass,
                step_type_name=step.step_type.TypeName,
                parameters={p.ParamName: p.ParamValue for p in step.parameters},
            )
            for step in sorted(job.steps, key=lambda s: (s.StepOrder, s.id))
        ],
        variables=[
            # A secret's value never leaves the server
            VariableOut(name=v.VarName, value=None if v.IsSecret else v.VarValue, secret=bool(v.IsSecret),
                        description=v.Description)
            for v in sorted(job.variables, key=lambda v: (v.VarName.lower(), v.VarName))
        ],
        tags=tag_store.paths_on(job),
        inherited_variables=inherited_variables(db, job) if db is not None else [],
    )


def _stored(parameters: dict) -> dict:
    """The parameters worth storing: those with a value."""
    return {name: value for name, value in parameters.items() if value is not None and str(value).strip() != ""}


def _audit(db: Session, job: Optional[Job], action: str, who: str, details: dict) -> None:
    db.add(Audit(MasterObject_id=job.MasterObject_id if job else None, Action=action,
                 PerformedBy=who, Details=json.dumps(details)))


def _name(title: Optional[str], position: int) -> str:
    return f"step {position} ('{title}')" if title else f"step {position}"


def apply_variables(job, submitted: list, creating: bool) -> List[str]:
    """
    Makes the variables of a job (or of any other object that can hold variables) match the
    list submitted. Returns what changed, naming variables but never values.
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
            job.variables.append(Variable(VarName=name, VarValue=wanted.value or "", IsSecret=wanted.secret,
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

    step_types = {t.HandlerClass: t for t in db.query(StepType)}
    for position, step in enumerate(payload.steps, start=1):
        if step.step_type not in step_types:
            name = _name(step.title, position)
            raise JobStoreError(f"{name[0].upper()}{name[1:]}: there is no step type '{step.step_type}'.")

    changes: List[str] = []
    try:
        if creating:
            job = Job(JobKey=new_key, Description=payload.description, IsActive=payload.active, CreatedBy=who)
            db.add(job)
            db.flush()
            changes.append(f"Created job '{new_key}'.")
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
    except ValueError as e:                 # the JobKey is not a usable name
        raise JobStoreError(str(e))

    current = {step.id: step for step in job.steps}
    submitted_ids = [step.id for step in payload.steps if step.id is not None]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise JobStoreError("The same step was submitted twice.")
    for step_id in submitted_ids:
        if step_id not in current:
            raise JobStoreError(f"Step id {step_id} does not belong to job '{job.JobKey}'.")

    old_order = [s.id for s in sorted(current.values(), key=lambda s: (s.StepOrder, s.id)) if s.id in submitted_ids]

    for position, submitted in enumerate(payload.steps, start=1):
        wanted = _stored(submitted.parameters)
        if submitted.id is None:
            step = JobStep(job_id=job.MasterObject_id, StepType_id=step_types[submitted.step_type].id,
                           StepOrder=position, Title=submitted.title, IsActive=submitted.active)
            step.parameters = [JobStepParameter(ParamName=n, ParamValue=v) for n, v in wanted.items()]
            job.steps.append(step)
            if not creating:
                changes.append(f"Added {_name(submitted.title, position)}.")
            continue

        step = current[submitted.id]
        what = []
        if (submitted.title or "") != (step.Title or ""):
            what.append("title")
            step.Title = submitted.title
        if submitted.active != bool(step.IsActive):
            what.append("enabled" if submitted.active else "disabled")
            step.IsActive = submitted.active
        if step.step_type.HandlerClass != submitted.step_type:
            what.append("step type")
            step.StepType_id = step_types[submitted.step_type].id
        have = {p.ParamName: p for p in step.parameters}
        if {n: p.ParamValue for n, p in have.items()} != wanted:
            what.append("parameters")
            for name, parameter in have.items():
                if name not in wanted:
                    step.parameters.remove(parameter)
                else:
                    parameter.ParamValue = wanted[name]
            for name, value in wanted.items():
                if name not in have:
                    step.parameters.append(JobStepParameter(ParamName=name, ParamValue=value))
        step.StepOrder = position
        if what:
            changes.append(f"Changed {_name(submitted.title, position)}: {', '.join(what)}.")

    for step_id, step in current.items():
        if step_id not in submitted_ids:
            changes.append(f"Removed step '{step.Title}'." if step.Title else "Removed a step.")
            job.steps.remove(step)

    if not creating and old_order != submitted_ids:
        changes.append("Reordered the steps.")

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


def delete_job(db: Session, job_key: str, who: str) -> None:
    """Deletes a job that has never run. Raises JobStoreError for one with run history."""
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    if not job:
        raise JobStoreError(f"No job with JobKey '{job_key}' exists.", status=404)
    runs = db.query(JobRun).filter((JobRun.Job_MasterObject_id == job.MasterObject_id) | (JobRun.JobKey == job_key)).count()
    if runs:
        raise JobStoreError(
            f"Job '{job_key}' has run {runs} time{'' if runs == 1 else 's'}, so it cannot be deleted. "
            f"Disable it instead: its history then keeps its link to the job.", status=409)

    _audit(db, None, "JOB_DELETED", who, {"job_key": job_key, "changes": [f"Deleted job '{job_key}'."]})
    db.delete(job)
    db.commit()

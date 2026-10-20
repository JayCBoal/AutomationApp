"""
Prerequisites on something outside a job's workflow (docs/WORKFLOWS_PHASE5.md): saving, checking
and describing them. workflow_store calls this for each item it saves.

Rules:
  - A prerequisite's Kind is JOB (a job of the same workflow, as before), OTHER_JOB (a job used in
    another workflow, or the whole workflow), ENDPOINT (files) or TIME (a condition on %{Now...}).
  - Something outside gets a name for conditions (MONTH_END.Extract, INBOUND_ORDERS), made from
    what it is if not given. It is unique among the job's own prerequisites and never the name of a
    job in the workflow, or Now.
  - Patience (D16, D99): wait the system's default time, with no limit, up to some minutes, or until a
    time; the minutes count from when the job's other prerequisites held, from the first of them, from
    a chosen one, or from the start of the run. An optional prerequisite needs a limit (D101).
  - The other workflow's job is followed by identity (the use's id), so renaming it elsewhere changes
    nothing here. A use that others wait for cannot be deleted (decision 8).
  - No loops of prerequisites between workflows either (D104): the message names the path.
"""
import re
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models import Endpoint, Job, WorkflowItem, WorkflowPrerequisite
from app.schemas import NeededByOut, PrerequisiteOut, PrerequisiteSave
from app.workflow_errors import WorkflowError
from engine import conditions, return_codes, workflow_conditions

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
WAIT_DEFAULTS = dict(wait_mode="DEFAULT", wait_minutes=None, wait_until=None, wait_from="OTHERS",
                     wait_from_target=None, required=True)


def is_outside(p) -> bool:
    return p.kind != "JOB"


def inside(prerequisites) -> list:
    """The prerequisites that are jobs of the workflow itself."""
    return [p for p in prerequisites if p.kind == "JOB"]


def outside_names(prerequisites) -> Dict[str, str]:
    """The names of the outside targets among prerequisites, as {name: kind}."""
    return {p.target: p.kind for p in prerequisites if is_outside(p)}


# ---------- Names ----------

def _clean(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text.strip())


def default_name(p: PrerequisiteSave) -> str:
    """The name made from what the prerequisite waits for."""
    if p.kind == "OTHER_JOB":
        return _clean(f"{p.workflow}.{p.job}" if (p.job or "").strip() else p.workflow or "Workflow")
    if p.kind == "ENDPOINT":
        return _clean(p.endpoint or "Files")
    return "Time"


def with_names(prerequisites: List[PrerequisiteSave], item_names: List[str]) -> List[PrerequisiteSave]:
    """The prerequisites with each outside one named: a name given is kept; otherwise one is made, numbered if it clashes."""
    taken = {p.target.strip() for p in prerequisites if is_outside(p) and p.target.strip()} | set(item_names) | {"Now"}
    result = []
    for p in prerequisites:
        if is_outside(p) and not p.target.strip():
            base = name = default_name(p)
            number = 2
            while name in taken:
                name, number = f"{base}{number}", number + 1
            taken.add(name)
            p = p.model_copy(update={"target": name})
        result.append(p)
    return result


# ---------- Normal form ----------

def normal(p: PrerequisiteSave, custom: bool) -> PrerequisiteSave:
    """The prerequisite with what does not apply to its kind put back to its defaults, so two are equal when they mean the same."""
    text = lambda value: (value or "").strip() or None          # noqa: E731
    keep = dict(kind=p.kind, target=p.target.strip(), required=p.required if is_outside(p) else True)
    if p.kind == "JOB":
        return PrerequisiteSave(test=p.test, return_codes=return_codes.normal(p.return_codes) if p.test == "RC" else None,
                                **{k: v for k, v in keep.items()})
    wait = dict(wait_mode=p.wait_mode, wait_minutes=p.wait_minutes if p.wait_mode == "MINUTES" else None,
                wait_until=text(p.wait_until) if p.wait_mode == "UNTIL" else None, wait_from=p.wait_from,
                wait_from_target=text(p.wait_from_target) if p.wait_from == "CHOSEN" else None)
    if p.kind == "OTHER_JOB":
        test = "RULE" if custom else p.test
        return PrerequisiteSave(test=test, return_codes=return_codes.normal(p.return_codes) if test == "RC" else None,
                                workflow=text(p.workflow), job=text(p.job), look_back_hours=p.look_back_hours,
                                only_after_start=p.only_after_start, **keep, **wait)
    if p.kind == "ENDPOINT":
        return PrerequisiteSave(endpoint=text(p.endpoint), file_pattern=text(p.file_pattern),
                                min_age_seconds=p.min_age_seconds, **keep, **wait)
    return PrerequisiteSave(time_condition=text(p.time_condition), **keep, **wait)


def signature(p) -> tuple:
    """Everything a prerequisite means, for telling whether a save changed it. Works on a normal PrerequisiteSave or an Out."""
    return (p.kind, p.target, p.test, p.return_codes, p.workflow, p.job, p.look_back_hours, bool(p.only_after_start),
            p.endpoint, p.file_pattern, p.min_age_seconds, p.time_condition, p.wait_mode, p.wait_minutes, p.wait_until,
            p.wait_from, p.wait_from_target, bool(p.required))


# ---------- Checking what was submitted ----------

def check(db: Session, workflow: Job, item_name: str, prerequisites: List[PrerequisiteSave], item_names: List[str],
          custom: bool) -> None:
    """Raises WorkflowError for the first thing wrong with the item's outside prerequisites."""
    seen: Set[str] = set()
    outside = [p for p in prerequisites if is_outside(p)]
    for p in outside:
        where = f"'{item_name}' waits for '{p.target}'"
        if p.kind not in WorkflowPrerequisite.KINDS:
            raise WorkflowError(f"'{item_name}': a prerequisite's kind must be JOB, OTHER_JOB, ENDPOINT or TIME, not '{p.kind}'.")
        _check_name(item_name, p.target, seen, item_names)
        {"OTHER_JOB": _check_other_job, "ENDPOINT": _check_files, "TIME": _check_time}[p.kind](db, workflow, where, p, custom)
        _check_patience(where, p, [q.target for q in prerequisites if q is not p])


def _check_name(item_name: str, name: str, seen: Set[str], item_names: List[str]) -> None:
    if not NAME_PATTERN.match(name):
        raise WorkflowError(f"'{item_name}': '{name}' cannot be the name of something it waits for. Use letters, digits, "
                            f"'_', '-' and '.', starting with a letter or digit.")
    if name in seen:
        raise WorkflowError(f"'{item_name}' waits for two things both named '{name}'. Give one of them another name.")
    if name in item_names or name == "Now":
        raise WorkflowError(f"'{item_name}': the name '{name}' is already used by a job in the workflow"
                            f"{' (and Now is the time)' if name == 'Now' else ''}. Give what it waits for another name.")
    seen.add(name)


def _check_other_job(db: Session, workflow: Job, where: str, p: PrerequisiteSave, custom: bool) -> None:
    other = _other_workflow(db, where, p.workflow)
    if other.MasterObject_id == workflow.MasterObject_id:
        raise WorkflowError(f"{where}, a job of this same workflow. For that, add an ordinary prerequisite on the job itself.")
    if (p.job or "").strip() and _other_use(other, p.job.strip()) is None:
        raise WorkflowError(f"{where}: the workflow '{other.JobKey}' has no job named '{p.job.strip()}'.")
    if not custom and p.test not in WorkflowPrerequisite.TESTS:
        raise WorkflowError(f"{where} with the test '{p.test}'. The test must be SUCCESS, FAILED, ENDED or RC.")
    if not custom and p.test == "RC" and return_codes.problem(p.return_codes):
        raise WorkflowError(f"{where} to give return codes: {return_codes.problem(p.return_codes)}")


def _other_workflow(db: Session, where: str, key: Optional[str]) -> Job:
    other = db.query(Job).filter(Job.JobKey == (key or "").strip()).first() if (key or "").strip() else None
    if other is None:
        raise WorkflowError(f"{where}, in the workflow '{key or ''}', which does not exist.")
    if other.JobType != "WORKFLOW":
        raise WorkflowError(f"{where}: '{other.JobKey}' is a job, not a workflow. Name the workflow that uses it, and the job in it.")
    return other


def _other_use(other: Job, name: str) -> Optional[WorkflowItem]:
    return next((i for i in other.items if i.ItemName == name), None)


def _check_files(db: Session, workflow: Job, where: str, p: PrerequisiteSave, custom: bool) -> None:
    if not (p.endpoint or "").strip() or db.query(Endpoint).filter(Endpoint.Name == p.endpoint.strip()).first() is None:
        raise WorkflowError(f"{where}, files at the endpoint '{p.endpoint or ''}', which is not registered.")


def _check_time(db: Session, workflow: Job, where: str, p: PrerequisiteSave, custom: bool) -> None:
    condition = (p.time_condition or "").strip()
    if not condition:
        raise WorkflowError(f"{where}, a time, but the time condition is empty. Write it as "
                            f"%{{Now.Time}} BETWEEN '06:00' AND '18:00'.")
    problems, _ = workflow_conditions.check(condition, [])
    if problems:
        raise WorkflowError(f"{where}: its time condition: {problems[0]}")
    if not any(ref.startswith("%{Now.") for ref in conditions.references(condition)):
        raise WorkflowError(f"{where}: its time condition does not look at the time. Use %{{Now.Time}}, "
                            f"%{{Now.Date}} or %{{Now.Weekday}}.")


def _check_patience(where: str, p: PrerequisiteSave, others: List[str]) -> None:
    if p.wait_mode not in WorkflowPrerequisite.WAIT_MODES:
        raise WorkflowError(f"{where}: how long to wait must be DEFAULT, NONE, MINUTES or UNTIL, not '{p.wait_mode}'.")
    if p.wait_mode == "MINUTES" and not (p.wait_minutes and p.wait_minutes >= 1):
        raise WorkflowError(f"{where}: give the number of minutes to wait, at least 1.")
    if p.wait_mode == "UNTIL" and not CLOCK.match((p.wait_until or "").strip()):
        raise WorkflowError(f"{where}: give the time to wait until, as 02:00 (24 hours).")
    if p.wait_from not in WorkflowPrerequisite.WAIT_FROM:
        raise WorkflowError(f"{where}: the wait must count from OTHERS, FIRST, CHOSEN or RUN_START, not '{p.wait_from}'.")
    if p.wait_from == "CHOSEN" and (p.wait_from_target or "").strip() not in others:
        raise WorkflowError(f"{where}: the wait counts from '{p.wait_from_target or ''}', which is not another "
                            f"prerequisite of the same job.")
    if not p.required and p.wait_mode == "NONE":
        raise WorkflowError(f"{where} as optional, with no limit. An optional prerequisite is given up after its limit, "
                            f"so it needs one: choose how long to wait, or make it required.")


# ---------- Loops between workflows (D104) ----------

def _whole(key: str) -> str:
    return f"{key} (whole workflow)"


def _waits_for_graph(db: Session, workflow: Job, names: List[str], submitted_items) -> Dict[str, List[str]]:
    """Every wait in the database, with this workflow's as submitted: 'WORKFLOW: job' waits for 'OTHER: job'."""
    graph: Dict[str, List[str]] = {}
    for other in db.query(Job).filter(Job.JobType == "WORKFLOW", Job.MasterObject_id != workflow.MasterObject_id):
        graph[_whole(other.JobKey)] = [f"{other.JobKey}: {i.ItemName}" for i in other.items]
        for item in other.items:
            graph[f"{other.JobKey}: {item.ItemName}"] = [_target_node(other.JobKey, p) for p in item.prerequisites
                                                         if p.Kind != "ENDPOINT" and p.Kind != "TIME"]
    graph[_whole(workflow.JobKey)] = [f"{workflow.JobKey}: {n}" for n in names]
    for name, item in zip(names, submitted_items):
        graph[f"{workflow.JobKey}: {name}"] = [_submitted_node(workflow.JobKey, p) for p in item.prerequisites
                                               if p.kind in ("JOB", "OTHER_JOB")]
    return graph


def _target_node(key: str, p: WorkflowPrerequisite) -> str:
    if p.Kind == "JOB":
        return f"{key}: {p.target.ItemName}"
    if p.target is not None:
        return f"{p.target.workflow.JobKey}: {p.target.ItemName}"
    return _whole(p.target_workflow.JobKey)


def _submitted_node(key: str, p: PrerequisiteSave) -> str:
    if p.kind == "JOB":
        return f"{key}: {p.target}"
    return f"{p.workflow}: {p.job}" if (p.job or "").strip() else _whole(p.workflow or "")


def check_no_loops_between_workflows(db: Session, workflow: Job, names: List[str], submitted_items) -> None:
    """Refuses prerequisites that, through other workflows, come back to a job waiting for itself."""
    if not any(p.kind == "OTHER_JOB" for item in submitted_items for p in item.prerequisites):
        return
    from app.workflow_store import find_loop
    loop = find_loop(_waits_for_graph(db, workflow, names, submitted_items))
    if loop:
        chain = ", which waits for ".join(f"'{n}'" for n in loop)
        raise WorkflowError(f"The prerequisites go round in a loop between workflows: {chain}. None of them could ever "
                            f"start. To run jobs again, a Rerun from… Reaction will repeat them, up to a limit.")


# ---------- Saving ----------

def wanted(prerequisites: List[PrerequisiteSave], custom: bool) -> List[PrerequisiteSave]:
    return [normal(p, custom) for p in prerequisites]


def build_row(db: Session, p: PrerequisiteSave, by_name: Dict[str, WorkflowItem]) -> WorkflowPrerequisite:
    """The row for a normal prerequisite. WaitFromPrerequisite_id is set by link_wait_from once the rows have ids."""
    if p.kind == "JOB":
        return WorkflowPrerequisite(Kind="JOB", target=by_name[p.target], Test=p.test, ReturnCodes=p.return_codes)
    row = WorkflowPrerequisite(Kind=p.kind, TargetName=p.target, Required=p.required, WaitMode=p.wait_mode,
                               WaitMinutes=p.wait_minutes, WaitUntil=p.wait_until, WaitFrom=p.wait_from)
    if p.kind == "OTHER_JOB":
        row.Test, row.ReturnCodes = p.test, p.return_codes
        row.LookBackHours, row.OnlyAfterStart = p.look_back_hours, p.only_after_start
    elif p.kind == "ENDPOINT":
        row.FilePattern, row.MinAgeSeconds = p.file_pattern, p.min_age_seconds
    else:
        row.TimeCondition = p.time_condition
    return row


def point_at_target(db: Session, row: WorkflowPrerequisite, p: PrerequisiteSave) -> None:
    """Sets what an outside row waits for: the job or workflow elsewhere, or the endpoint."""
    with db.no_autoflush:
        if p.kind == "OTHER_JOB":
            other = db.query(Job).filter(Job.JobKey == p.workflow).one()
            use = _other_use(other, p.job) if p.job else None
            row.target, row.target_workflow = use, (None if use else other)
        elif p.kind == "ENDPOINT":
            row.endpoint = db.query(Endpoint).filter(Endpoint.Name == p.endpoint).one()


def link_wait_from(rows: List[WorkflowPrerequisite], normals: List[PrerequisiteSave]) -> None:
    """Points each prerequisite that counts its wait from a chosen one at that one's row (call after the rows have ids)."""
    by_name = {(r.TargetName if r.Kind != "JOB" else r.target.ItemName): r for r in rows}
    for row, p in zip(rows, normals):
        if p.wait_from == "CHOSEN" and p.wait_from_target in by_name:
            row.WaitFromPrerequisite_id = by_name[p.wait_from_target].id


# ---------- Describing ----------

def describe(row: WorkflowPrerequisite, names_by_id: Dict[int, str]) -> PrerequisiteOut:
    """A stored prerequisite as the API gives it. names_by_id: the names of the item's prerequisites, by row id."""
    chosen = names_by_id.get(row.WaitFromPrerequisite_id) if row.WaitFrom == "CHOSEN" else None
    if row.Kind == "JOB":
        return PrerequisiteOut(kind="JOB", target=row.target.ItemName, test=row.Test, return_codes=row.ReturnCodes)
    out = PrerequisiteOut(kind=row.Kind, target=row.TargetName or "", test=row.Test, return_codes=row.ReturnCodes,
                          look_back_hours=row.LookBackHours, only_after_start=bool(row.OnlyAfterStart),
                          file_pattern=row.FilePattern, min_age_seconds=row.MinAgeSeconds,
                          time_condition=row.TimeCondition, wait_mode=row.WaitMode, wait_minutes=row.WaitMinutes,
                          wait_until=row.WaitUntil, wait_from=row.WaitFrom, wait_from_target=chosen,
                          required=bool(row.Required))
    if row.Kind == "OTHER_JOB":
        out.workflow = row.target.workflow.JobKey if row.target else row.target_workflow.JobKey
        out.job = row.target.ItemName if row.target else None
    elif row.Kind == "ENDPOINT" and row.endpoint is not None:
        out.endpoint = row.endpoint.Name
    return out


def describe_all(prerequisites) -> List[PrerequisiteOut]:
    names = {p.id: (p.target.ItemName if p.Kind == "JOB" and p.target else p.TargetName) for p in prerequisites}
    return [describe(p, names) for p in prerequisites if p.Kind != "JOB" or p.target is not None]


# ---------- Who waits ----------

def _waiters_of_use(item: WorkflowItem) -> List[WorkflowPrerequisite]:
    return [p for p in item.waiters if p.Kind == "OTHER_JOB" and p.item.Workflow_MasterObject_id != item.Workflow_MasterObject_id]


def needed_by(item: WorkflowItem) -> List[NeededByOut]:
    """The jobs in other workflows that wait for this use, in order."""
    found = {(p.item.workflow.JobKey, p.item.ItemName) for p in _waiters_of_use(item)}
    return [NeededByOut(workflow=workflow, job=job) for workflow, job in sorted(found)]


def _words(pairs) -> List[str]:
    return sorted({f"'{job}' in '{workflow}'" for workflow, job in pairs})


def waiting_for_use(item: WorkflowItem) -> List[str]:
    """The jobs in other workflows that wait for this use, as "'Load' in 'DOWNSTREAM'", in order."""
    return _words((p.item.workflow.JobKey, p.item.ItemName) for p in _waiters_of_use(item))


def waiting_for_workflow(db: Session, workflow: Job) -> List[str]:
    """The jobs that wait for the workflow as a whole, and for any job in it, in order."""
    pairs = [(p.item.workflow.JobKey, p.item.ItemName) for p in workflow.waiters if p.Kind == "OTHER_JOB"]
    for item in workflow.items:
        pairs += [(p.item.workflow.JobKey, p.item.ItemName) for p in _waiters_of_use(item)]
    return _words(pairs)


def waiting_for_endpoint(db: Session, endpoint: Endpoint) -> List[str]:
    """The workflows that wait for files at the endpoint, by key, in order."""
    rows = db.query(WorkflowPrerequisite).filter(WorkflowPrerequisite.Endpoint_MasterObject_id == endpoint.MasterObject_id)
    return sorted({p.item.workflow.JobKey for p in rows})

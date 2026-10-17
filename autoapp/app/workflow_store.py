"""
What a workflow is made of: the jobs it uses (its items) and the prerequisites between
them. A workflow is a Job of type WORKFLOW (docs/WORKFLOWS.md); job_store saves what all
jobs share and calls apply_items for a workflow's items.

Rules:
  - Items are saved whole, in outline order. An item keeps its identity (its id) when it is
    changed, so later run records stay linked to it; one left out of a save is deleted.
  - Each item has a name unique within its workflow, made from its job's key if not given.
  - A prerequisite names another item of the same workflow. There are no loops: a job never
    ends up waiting, directly or not, for itself. A workflow never uses itself, directly or
    through another workflow.
"""
import re
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models import Job, WorkflowItem, WorkflowPrerequisite
from app.schemas import PrerequisiteOut, WorkflowItemOut, WorkflowItemSave
from engine import return_codes

TEST_WORDS = {"SUCCESS": "succeeded", "FAILED": "failed", "ENDED": "ended", "RC": "gave return codes"}


class WorkflowError(Exception):
    """A workflow that cannot be saved as submitted; the message says why, for the person saving it."""


def default_item_name(job_key: str) -> str:
    """An item's name made from its job's key: dots and anything else a name cannot hold become underscores."""
    name = re.sub(r"[^A-Za-z0-9_-]", "_", job_key)
    return name if name[:1].isalnum() else f"J{name}"


def describe_items(job: Job) -> List[WorkflowItemOut]:
    return [
        WorkflowItemOut(
            id=item.id, name=item.ItemName, job_key=item.job.JobKey, job_type=item.job.JobType, join=item.JoinRule,
            prerequisites=[PrerequisiteOut(target=p.target.ItemName, test=p.Test, return_codes=p.ReturnCodes)
                           for p in item.prerequisites if p.target is not None])
        for item in job.items
    ]


def describe_prerequisite(target: str, test: str, codes: Optional[str]) -> str:
    """In words, as the audit log and the outline say it: "Extract succeeded", "Load gave return codes 0-4"."""
    return f"{target} {TEST_WORDS.get(test, test.lower())}" + (f" {codes}" if test == "RC" else "")


# ---------- Checking what was submitted ----------

def _names(submitted: List[WorkflowItemSave]) -> List[str]:
    """Each item's name: as given, or made from its job key."""
    return [(s.name or "").strip() or default_item_name(s.job_key.strip()) for s in submitted]


def _check_names(names: List[str]) -> None:
    seen: Set[str] = set()
    for name in names:
        if not WorkflowItem.NAME_PATTERN.match(name):
            raise WorkflowError(f"'{name}' cannot be the name of a job in a workflow. Use letters, digits, '_' and '-', "
                                f"starting with a letter or digit.")
        if name in seen:
            raise WorkflowError(f"Two jobs in the workflow are both named '{name}'. Give one of them another name.")
        seen.add(name)


def _check_prerequisites(names: List[str], submitted: List[WorkflowItemSave]) -> None:
    for name, item in zip(names, submitted):
        if item.join not in WorkflowItem.JOIN_RULES:
            raise WorkflowError(f"'{name}': its join must be ALL or ANY, not '{item.join}'.")
        for p in item.prerequisites:
            if p.target not in names:
                raise WorkflowError(f"'{name}' waits for '{p.target}', which is not a job in this workflow.")
            if p.target == name:
                raise WorkflowError(f"'{name}' cannot wait for itself.")
            if p.test not in WorkflowPrerequisite.TESTS:
                raise WorkflowError(f"'{name}' waits for '{p.target}' with the test '{p.test}'. "
                                    f"The test must be SUCCESS, FAILED, ENDED or RC.")
            if p.test == "RC" and return_codes.problem(p.return_codes):
                raise WorkflowError(f"'{name}' waits for return codes of '{p.target}': {return_codes.problem(p.return_codes)}")


def find_loop(waits_for: Dict[str, List[str]]) -> Optional[List[str]]:
    """A chain of names that comes back to its start (a waits for b, which waits for a), or None."""
    state: Dict[str, str] = {}

    def visit(name: str, path: List[str]) -> Optional[List[str]]:
        state[name] = "visiting"
        for target in waits_for.get(name, []):
            if state.get(target) == "visiting":
                return path[path.index(target):] + [target] if target in path else [name, target]
            if target not in state:
                found = visit(target, path + [target])
                if found:
                    return found
        state[name] = "done"
        return None

    for start in waits_for:
        if start not in state:
            found = visit(start, [start])
            if found:
                return found
    return None


def _check_no_loops(names: List[str], submitted: List[WorkflowItemSave]) -> None:
    loop = find_loop({name: [p.target for p in item.prerequisites] for name, item in zip(names, submitted)})
    if loop:
        chain = ", which waits for ".join(f"'{n}'" for n in loop)
        raise WorkflowError(f"The prerequisites go round in a loop: {chain}. A job cannot end up waiting for itself.")


def _jobs_used(db: Session, submitted: List[WorkflowItemSave], names: List[str]) -> Dict[str, Job]:
    jobs = {}
    for name, item in zip(names, submitted):
        key = item.job_key.strip()
        job = db.query(Job).filter(Job.JobKey == key).first()
        if not job:
            raise WorkflowError(f"'{name}' runs the job '{key}', which does not exist.")
        jobs[name] = job
    return jobs


def _uses(db: Session, workflow: Job, target_id: int, seen: Set[int]) -> bool:
    """Whether the workflow uses the job target_id, directly or through workflows it uses."""
    for item in workflow.items:
        if item.Job_MasterObject_id == target_id:
            return True
        inner = item.job
        if inner.JobType == "WORKFLOW" and inner.MasterObject_id not in seen:
            seen.add(inner.MasterObject_id)
            if _uses(db, inner, target_id, seen):
                return True
    return False


def _check_not_itself(db: Session, workflow: Job, jobs: Dict[str, Job]) -> None:
    for name, job in jobs.items():
        if job.MasterObject_id == workflow.MasterObject_id:
            raise WorkflowError(f"'{name}' runs this workflow itself. A workflow cannot use itself.")
        if job.JobType == "WORKFLOW" and _uses(db, job, workflow.MasterObject_id, {job.MasterObject_id}):
            raise WorkflowError(f"'{name}' runs the workflow '{job.JobKey}', which uses this one. "
                                f"A workflow cannot use itself, even through another.")


# ---------- Saving ----------

def apply_items(db: Session, workflow: Job, submitted: List[WorkflowItemSave], creating: bool) -> List[str]:
    """Makes the workflow's items and prerequisites match those submitted. Returns what changed, in words."""
    names = _names(submitted)
    _check_names(names)
    _check_prerequisites(names, submitted)
    _check_no_loops(names, submitted)
    jobs = _jobs_used(db, submitted, names)
    _check_not_itself(db, workflow, jobs)

    current = {item.id: item for item in workflow.items}
    for s in submitted:
        if s.id is not None and s.id not in current:
            raise WorkflowError(f"Item id {s.id} does not belong to workflow '{workflow.JobKey}'.")
    submitted_ids = [s.id for s in submitted if s.id is not None]
    old_order = [item.id for item in sorted(current.values(), key=lambda i: i.ItemOrder) if item.id in submitted_ids]
    changes: List[str] = []
    kept = _apply_item_rows(workflow, submitted, names, jobs, current, creating, changes)
    _remove_left_out(workflow, current, kept, changes)
    db.flush()                          # every item has its id before prerequisites point at it
    by_name = {item.ItemName: item for item in workflow.items}
    for name, s in zip(names, submitted):
        if _apply_prerequisites(by_name[name], s, by_name) and not creating and s.id is not None:
            changes.append(f"Changed what '{name}' waits for.")
    if not creating and old_order != submitted_ids:
        changes.append("Reordered the jobs.")
    return changes


def _apply_item_rows(workflow, submitted, names, jobs, current, creating, changes) -> Set[int]:
    kept: Set[int] = set()
    for position, (name, s) in enumerate(zip(names, submitted), start=1):
        job = jobs[name]
        if s.id is None:
            workflow.items.append(WorkflowItem(ItemName=name, job=job, JoinRule=s.join, ItemOrder=position))
            if not creating:
                changes.append(f"Added '{name}' (job '{job.JobKey}').")
            continue
        item = current[s.id]
        kept.add(item.id)
        what = []
        if item.ItemName != name:
            what.append(f"renamed from '{item.ItemName}'")
        if item.Job_MasterObject_id != job.MasterObject_id:
            what.append(f"now runs '{job.JobKey}'")
        if item.JoinRule != s.join:
            what.append(f"starts when {'any' if s.join == 'ANY' else 'all'} of its prerequisites hold")
        item.ItemName, item.job, item.JoinRule, item.ItemOrder = name, job, s.join, position
        if what:
            changes.append(f"Changed '{name}': {', '.join(what)}.")
    return kept


def _remove_left_out(workflow: Job, current: dict, kept: Set[int], changes: List[str]) -> None:
    for item_id, item in current.items():
        if item_id not in kept:
            changes.append(f"Removed '{item.ItemName}'.")
            workflow.items.remove(item)


def _apply_prerequisites(item: WorkflowItem, submitted: WorkflowItemSave, by_name: Dict[str, WorkflowItem]) -> bool:
    """Makes the item's prerequisites match those submitted. Returns whether they changed."""
    wanted = [(p.target, p.test, return_codes.normal(p.return_codes) if p.test == "RC" else None)
              for p in submitted.prerequisites]
    have = [(p.target.ItemName if p.target else None, p.Test, p.ReturnCodes) for p in item.prerequisites]
    if wanted == have:
        return False
    item.prerequisites.clear()
    for target, test, codes in wanted:
        item.prerequisites.append(WorkflowPrerequisite(target=by_name[target], Test=test, ReturnCodes=codes))
    return True


# ---------- Checking before a run, and who uses what ----------

def workflow_problems(db: Session, workflow: Job, seen: Optional[Set[int]] = None) -> List[str]:
    """Everything that would stop the workflow from running, in plain words. Runs nothing."""
    from app.routers.jobs import job_problems
    seen = (seen or set()) | {workflow.MasterObject_id}
    problems = []
    if not workflow.IsActive:
        problems.append(f"Workflow '{workflow.JobKey}' is disabled.")
    if not workflow.items:
        problems.append(f"Workflow '{workflow.JobKey}' has no jobs in it yet. Add the jobs it should run.")
    checked: Dict[int, List[str]] = {}
    for item in workflow.items:
        job = item.job
        if job.MasterObject_id in seen:
            continue
        if job.MasterObject_id not in checked:
            checked[job.MasterObject_id] = (workflow_problems(db, job, seen) if job.JobType == "WORKFLOW"
                                            else job_problems(db, job))
        for problem in checked[job.MasterObject_id][:1]:     # the first is enough to say it would not run
            problems.append(f"'{item.ItemName}' would not run: {problem}")
    return problems


def workflows_using(db: Session, job: Job) -> List[str]:
    """The keys of the workflows that use the job, in name order."""
    rows = (db.query(Job.JobKey).join(WorkflowItem, WorkflowItem.Workflow_MasterObject_id == Job.MasterObject_id)
            .filter(WorkflowItem.Job_MasterObject_id == job.MasterObject_id).distinct())
    return sorted(key for (key,) in rows)

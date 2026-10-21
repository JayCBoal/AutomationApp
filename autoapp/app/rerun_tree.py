"""
What Rerun would do to a workflow run (docs/WORKFLOWS_PHASE7.md, step 3): which run to reopen, which items
go on from where they stopped or start again, and what stops it. The rules for each item are engine/reopen.py's,
the same the workflow runner follows, so the plan is what the run will do.

A run is chosen as a whole, or by one failed job or frame inside it. Either way the run that is reopened is the
one at the top: it is the runner of the whole tree, and the frames between it and the item chosen are
reopened in turn.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Job, JobRun, WorkflowRunItem
from engine import reopen
from engine.control_file import ControlRecord
from engine.runner import find_earlier_attempt


@dataclass
class Pick:
    """One item the reopened run will run again."""
    path: str
    job_key: str
    action: str
    attempt: int
    child: Optional[JobRun]
    record: Optional[ControlRecord] = None
    problem: Optional[str] = None

    def goes_on(self) -> bool:
        return self.action in (reopen.PICK_UP, reopen.ROUTE)


@dataclass
class TreePlan:
    top: JobRun
    scope: Optional[str] = None
    refusal: Optional[str] = None
    picks: List[Pick] = field(default_factory=list)
    resume_problem: Optional[str] = None


def top_and_scope(db: Session, run: JobRun) -> Tuple[JobRun, Optional[str], Optional[str]]:
    """The run at the top of the tree this run is in, the path of the item chosen (None for the whole run), and a refusal."""
    if run.ParentRun_id is None:
        return run, None, None
    top = run
    while top.ParentRun_id is not None:
        top = db.get(JobRun, top.ParentRun_id)
    row = (db.query(WorkflowRunItem).filter(WorkflowRunItem.WorkflowRun_id == run.ParentRun_id,
                                            WorkflowRunItem.Path == run.WorkflowPath).first())
    if row is None or row.ChildRun_id != run.id:
        return top, run.WorkflowPath, f"This is not the latest attempt of '{run.WorkflowPath}'; run that one again instead."
    return top, run.WorkflowPath, None


def make_tree_plan(db: Session, run: JobRun) -> TreePlan:
    top, scope, refusal = top_and_scope(db, run)
    plan = TreePlan(top, scope, refusal or _refusal(db, top, scope))
    if plan.refusal:
        return plan
    plan.picks = walk(db, top, reopen.RESUME, scope)
    plan.resume_problem = _resume_problem(db, plan)
    return plan


def _refusal(db: Session, top: JobRun, scope: Optional[str]) -> Optional[str]:
    """Why this run cannot be run again at all, or None."""
    if top.Status == "RUNNING":
        return f"'{top.JobKey}' is still running. Kill it first if it should be run again."
    later = (db.query(JobRun.Attempt).filter(JobRun.JobKey == top.JobKey, JobRun.SchedulerInstanceID == top.SchedulerInstanceID,
                                            JobRun.Attempt > top.Attempt).first())
    if later:
        return f"This is attempt {top.Attempt}; attempt {later[0]} has run since. Run that one again instead."
    if top.Status != "FAILED":
        return f"'{top.JobKey}' succeeded, so there is nothing to pick up. Run it again from the Run Job page."
    return _item_refusal(db, top, scope) if scope else None


def _item_refusal(db: Session, top: JobRun, scope: str) -> Optional[str]:
    row = _find_item(db, top, scope)
    if row is not None and row.Status == "FAILED":
        return None
    return f"'{scope}' did not fail, so there is nothing to run again."


def _find_item(db: Session, top: JobRun, path: str) -> Optional[WorkflowRunItem]:
    from engine import outside
    return (db.query(WorkflowRunItem).filter(WorkflowRunItem.Path == path,
                                             WorkflowRunItem.WorkflowRun_id.in_(outside.run_tree_ids(db, top.id))).first())


def walk(db: Session, run: JobRun, kind: str, scope: Optional[str]) -> List[Pick]:
    """The items of the run, and of the frames inside it that go on, which reopening it runs again."""
    picks: List[Pick] = []
    rows = (db.query(WorkflowRunItem).filter(WorkflowRunItem.WorkflowRun_id == run.id)
            .order_by(WorkflowRunItem.ItemOrder, WorkflowRunItem.id))
    for row in rows:
        child = db.get(JobRun, row.ChildRun_id) if row.ChildRun_id else None
        action = reopen.action_for(row.Status, child is not None, row.Path, kind, scope)
        if action == reopen.UNTOUCHED:
            continue
        pick = Pick(row.Path, row.JobKey, action, row.Attempt, child)
        picks.append(pick)
        if pick.goes_on() and child is not None:
            _look_inside(db, pick, kind, scope, picks)
    return picks


def _look_inside(db: Session, pick: Pick, kind: str, scope: Optional[str], picks: List[Pick]) -> None:
    """A frame is read through to its own items; a job is read for the record of how far it got."""
    child = pick.child
    if child.JobType == "WORKFLOW":
        missing = missing_items(db, child)
        pick.problem = _missing_words(child, missing) if missing else None
        picks += walk(db, child, kind, scope if pick.action == reopen.ROUTE else None)
    else:
        pick.record, pick.problem = find_earlier_attempt(db, child.RunID)


def missing_items(db: Session, run: JobRun) -> List[str]:
    """The items the run has that its workflow no longer has: it was edited since."""
    job = db.query(Job).filter(Job.JobKey == run.JobKey).first()
    names = {item.ItemName for item in job.items} if job is not None else set()
    rows = db.query(WorkflowRunItem).filter(WorkflowRunItem.WorkflowRun_id == run.id)
    return [row.ItemName for row in rows if row.ItemName not in names]


def _missing_words(run: JobRun, missing: List[str]) -> str:
    names = ", ".join(f"'{name}'" for name in missing)
    return (f"Workflow '{run.JobKey}' has been changed since this run: {names} "
            f"{'is' if len(missing) == 1 else 'are'} no longer in it. Restart the run from the beginning.")


def _resume_problem(db: Session, plan: TreePlan) -> Optional[str]:
    """Why Resume cannot be done, in words; Restart can be."""
    problems = _missing_at_top(db, plan) + [f"'{p.path}': {p.problem}" for p in plan.picks if p.problem]
    if problems:
        return " ".join(problems)
    if not plan.picks:
        return f"Nothing in '{plan.top.JobKey}' failed or was left unrun, so there is nothing to pick up."
    return None


def _missing_at_top(db: Session, plan: TreePlan) -> List[str]:
    missing = missing_items(db, plan.top)
    return [_missing_words(plan.top, missing)] if missing else []

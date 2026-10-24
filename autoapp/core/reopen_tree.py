"""
What Rerun would do to a workflow run (docs/WORKFLOWS_PHASE7.md, step 3): which run to reopen, which items
go on from where they stopped or start again, and what stops it. The rules for each item are engine/reopen.py's,
the same the workflow runner follows, so the plan is what the run will do. It lives in the engine because a
Reaction asks it too (automatic_problem): the one rule for "can this run be picked up".

A run is chosen as a whole, or by one failed job or frame inside it. Either way the run that is reopened is the
one at the top: it is the runner of the whole tree, and the frames between it and the item chosen are
reopened in turn.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from core.models import Job, JobRun, WorkflowItem, WorkflowPrerequisite, WorkflowRunItem
from core import reopen
from core.control_file import ControlRecord
from core.earlier_attempt import automatic_resume_problem, find_earlier_attempt


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
    status: str = ""

    def goes_on(self) -> bool:
        return self.action in (reopen.PICK_UP, reopen.ROUTE)


@dataclass
class TreePlan:
    top: JobRun
    scope: Optional[str] = None
    refusal: Optional[str] = None
    picks: List[Pick] = field(default_factory=list)
    resume_problem: Optional[str] = None
    items: Optional[Dict[str, str]] = None      # Advanced: what to do with each item named, by path
    choices: List["ItemState"] = field(default_factory=list)    # Advanced: every item of the run, for the dialog


@dataclass
class ItemState:
    """One item of the run as it ended, and what Advanced may do with it."""
    path: str
    job_key: str
    status: str
    is_workflow: bool
    depth: int
    can_resume: bool
    resume_problem: Optional[str] = None
    waits: List[str] = field(default_factory=list)     # what it waits for, by name: jobs of its workflow, and things outside it
    custom_rule: bool = False                          # it starts by a Custom rule, which Ignore a prerequisite cannot take apart


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


def make_advanced_plan(db: Session, run: JobRun, items: Optional[Dict[str, str]] = None) -> TreePlan:
    """
    What Advanced may do with the run at the top of this one: any run that has ended, Succeeded or not. With items,
    the items it would run again; without, only the list of items to choose from.
    """
    top, scope, refusal = top_and_scope(db, run)
    plan = TreePlan(top, scope, refusal or _refusal(db, top, None, advanced=True), items=items)
    if plan.refusal:
        return plan
    plan.choices = list_items(db, top)
    if items:
        plan.picks = walk(db, top, reopen.RESUME, None, items)
        plan.resume_problem = _items_problem(db, plan)
    return plan


def _refusal(db: Session, top: JobRun, scope: Optional[str], advanced: bool = False) -> Optional[str]:
    """Why this run cannot be run again at all, or None."""
    if top.Status == "RUNNING":
        return f"'{top.JobKey}' is still running. Kill it first if it should be run again."
    later = (db.query(JobRun.Attempt).filter(JobRun.JobKey == top.JobKey, JobRun.SchedulerInstanceID == top.SchedulerInstanceID,
                                            JobRun.Attempt > top.Attempt).first())
    if later:
        return f"This is attempt {top.Attempt}; attempt {later[0]} has run since. Run that one again instead."
    if top.Status != "FAILED" and not (advanced and top.Status == "SUCCESS"):
        return f"'{top.JobKey}' succeeded, so there is nothing to pick up. Run it again from the Run Job page."
    return _item_refusal(db, top, scope) if scope else None


def _item_refusal(db: Session, top: JobRun, scope: str) -> Optional[str]:
    row = _find_item(db, top, scope)
    if row is not None and row.Status == "FAILED":
        return None
    return f"'{scope}' did not fail, so there is nothing to run again."


def _find_item(db: Session, top: JobRun, path: str) -> Optional[WorkflowRunItem]:
    from core import outside
    return (db.query(WorkflowRunItem).filter(WorkflowRunItem.Path == path,
                                             WorkflowRunItem.WorkflowRun_id.in_(outside.run_tree_ids(db, top.id))).first())


def walk(db: Session, run: JobRun, kind: str, scope: Optional[str], items: Optional[Dict[str, str]] = None) -> List[Pick]:
    """The items of the run, and of the frames inside it that go on, which reopening it runs again."""
    picks: List[Pick] = []
    rows = (db.query(WorkflowRunItem).filter(WorkflowRunItem.WorkflowRun_id == run.id)
            .order_by(WorkflowRunItem.ItemOrder, WorkflowRunItem.id))
    for row in rows:
        child = db.get(JobRun, row.ChildRun_id) if row.ChildRun_id else None
        action = reopen.action_for(row.Status, child is not None, row.Path, kind, scope, items)
        if action == reopen.UNTOUCHED:
            continue
        pick = Pick(row.Path, row.JobKey, action, row.Attempt, child, status=row.Status)
        picks.append(pick)
        if pick.goes_on() and child is not None:
            _look_inside(db, pick, kind, scope, picks, items)
    return picks


def _look_inside(db: Session, pick: Pick, kind: str, scope: Optional[str], picks: List[Pick],
                 items: Optional[Dict[str, str]] = None) -> None:
    """A frame is read through to its own items; a job is read for the record of how far it got."""
    child = pick.child
    if child.JobType == "WORKFLOW":
        missing = missing_items(db, child)
        pick.problem = _missing_words(child, missing) if missing else None
        on_the_way = pick.action == reopen.ROUTE
        picks += walk(db, child, kind if on_the_way else reopen.RESUME, scope if on_the_way else None,
                      items if on_the_way else None)
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


def automatic_problem(db: Session, run: JobRun) -> Optional[str]:
    """
    Why a Reaction may not Resume this workflow run, in words, or None when it may. The run is reopened as
    the operator's Resume would (walk), and one refusal refuses all of it: the workflow was edited, nothing
    failed or was left unrun, or a failed job or a job in a failed frame has no usable record or has a step
    whose effect is not known (automatic_resume_problem, as for a job on its own).
    """
    problems = [_missing_words(run, missing_items(db, run))] if missing_items(db, run) else []
    picks = walk(db, run, reopen.RESUME, None)
    for pick in picks:
        if pick.problem:
            problems.append(f"'{pick.path}': {pick.problem}")
        elif pick.status == "FAILED" and pick.child is None:
            problems.append(f"'{pick.path}': the job left no record of its run, so there is nothing to pick up.")
        elif pick.goes_on() and pick.child is not None and pick.child.JobType != "WORKFLOW":
            why = automatic_resume_problem(pick.record, None)
            if why:
                problems.append(f"'{pick.path}': {why}")
    if not problems and not picks:
        problems.append(f"Nothing in '{run.JobKey}' failed or was left unrun, so there is nothing to pick up.")
    return " ".join(problems) or None


def list_items(db: Session, run: JobRun, depth: int = 0) -> List[ItemState]:
    """Every item of the run, and of the embedded workflows inside it, in order, with whether it could be resumed."""
    found: List[ItemState] = []
    rows = (db.query(WorkflowRunItem).filter(WorkflowRunItem.WorkflowRun_id == run.id)
            .order_by(WorkflowRunItem.ItemOrder, WorkflowRunItem.id))
    for row in rows:
        child = db.get(JobRun, row.ChildRun_id) if row.ChildRun_id else None
        is_workflow = child is not None and child.JobType == "WORKFLOW"
        can, why = _can_be_resumed(db, row, child)
        waits, custom = _waits_of(db, row)
        found.append(ItemState(row.Path, row.JobKey, row.Status, is_workflow, depth, can, why, waits, custom))
        if is_workflow:
            found += list_items(db, child, depth + 1)
    return found


def _waits_of(db: Session, row: WorkflowRunItem) -> Tuple[List[str], bool]:
    """The names of what the item waits for, as the workflow has it now, and whether a Custom rule decides when it starts."""
    item = db.get(WorkflowItem, row.Item_id) if row.Item_id else None
    if item is None:
        return [], False
    names = [(p.target.ItemName if p.Kind == "JOB" and p.target else p.TargetName or "") for p in item.prerequisites]
    return [name for name in names if name], item.JoinRule == "CUSTOM"


def _can_be_resumed(db: Session, row: WorkflowRunItem, child: Optional[JobRun]) -> Tuple[bool, Optional[str]]:
    """Only a failed item with a run of its own can be picked up; a job also needs the record of how far it got."""
    if row.Status != "FAILED":
        return False, "It did not fail, so it can only be run again from the beginning."
    if child is None:
        return False, "It left no record of its run, so it can only be run again from the beginning."
    if child.JobType == "WORKFLOW":
        return True, None
    record, problem = find_earlier_attempt(db, child.RunID)
    return record is not None, problem


def _items_problem(db: Session, plan: TreePlan) -> Optional[str]:
    """Why the items named cannot be run, in words: the workflow was edited, an item is not in the run, or one cannot be picked up."""
    known = {item.path: item for item in plan.choices}
    problems = [f"'{path}' is not an item of this run." for path in plan.items if path not in known]
    problems += [f"'{path}': {known[path].resume_problem}" for path, what in plan.items.items()
                 if what == reopen.RESUME and path in known and not known[path].can_resume]
    problems += [f"'{path}': {why}" for path, what in plan.items.items() if path in known
                 for why in [_pass_over_problem(what, known[path].status)] if why]
    problems += _missing_at_top(db, plan) + [f"'{p.path}': {p.problem}" for p in plan.picks if p.problem]
    return " ".join(problems) or None


def _pass_over_problem(action: str, status: str) -> Optional[str]:
    """Why an item cannot be bypassed or left unrun, in words: only one that ended, and not to the status it has already."""
    if action not in reopen.PASS_OVER:
        return None
    if status in ("PENDING", "WAITING", "RUNNING"):
        return "it has not ended, so it cannot be bypassed or left unrun."
    if status == "DISABLED":
        return "it is disabled, which already stops it running."
    if action == reopen.BYPASS and status in ("SUCCESS", "BYPASSED"):
        return "it already counts as succeeded."
    if action == reopen.DONT_RUN and status == "SKIPPED":
        return "it is already left unrun (Skipped)."
    return None


def downstream(db: Session, run: JobRun, chosen: List[str]) -> List[str]:
    """
    The paths of everything that waits, directly or not, for the items chosen, in the workflow each is in and in
    every workflow around it: the items themselves are not included.
    """
    found: List[str] = []
    for path in chosen:
        while path:
            for later in _later_items(db, run, path):
                if later not in found and later not in chosen:
                    found.append(later)
            path = path.rsplit("/", 1)[0] if "/" in path else ""
    return found


def _later_items(db: Session, top: JobRun, path: str) -> List[str]:
    """What waits for the item at path, in the same workflow, by the prerequisites on other jobs of that workflow."""
    from core import outside
    row = (db.query(WorkflowRunItem).filter(WorkflowRunItem.Path == path,
                                            WorkflowRunItem.WorkflowRun_id.in_(outside.run_tree_ids(db, top.id))).first())
    if row is None or row.Item_id is None:
        return []
    prefix = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
    reached, queue = [], [row.Item_id]
    while queue:
        item_id = queue.pop()
        waiting = (db.query(WorkflowPrerequisite.Item_id).filter(WorkflowPrerequisite.TargetItem_id == item_id,
                                                                 WorkflowPrerequisite.Kind == "JOB").all())
        for (waiter,) in waiting:
            if waiter not in reached:
                reached.append(waiter)
                queue.append(waiter)
    names = [name for (name,) in db.query(WorkflowItem.ItemName).filter(WorkflowItem.id.in_(reached))] if reached else []
    return [prefix + name for name in names]

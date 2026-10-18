"""
Reactions as the API reads and saves them (docs/WORKFLOWS_PHASE3.md): on a job, and on one use
of a job in a workflow, whose list then replaces the job's. job_store and workflow_store call
this; the engine carries them out (engine/reactions.py).

Rules, checked on saving:
  - What happens next (NEXT) holds decisions; Also (ALSO) holds side effects. Each entry has
    at least one action, at most one Count as, and at most one of Rerun, Rerun from… and Kill
    the workflow.
  - The When is SUCCESS, FAILED, ENDED or RC with return codes.
  - Rerun from…, Skip…, Skip the rest of the branch and Kill the workflow name other jobs, or a
    workflow around the job, so only a use in a workflow offers them.
  - Rerun from… names a job this one waits for, directly or not; Skip… another job in the
    workflow. A rerun runs at most 1 to 100 times, after a wait of 0 to 86400 seconds.
  - Start a workflow names a workflow, which must not be the one the Reaction is in, nor use it.
"""
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models import Job, Reaction, ReactionAction, WorkflowItem
from app.schemas import ReactionActionIO, ReactionIO
from engine import return_codes
from engine.reactions import LIMITED, ONLY_IN_WORKFLOWS, SIDE_EFFECTS, WORDS

MAX_TIMES, MAX_WAIT = 100, 86400
DECISIONS = tuple(ReactionAction.DECISIONS)


class ReactionError(Exception):
    """Reactions that cannot be saved as submitted; the message says why, for the person saving them."""


def describe(reactions: List[Reaction]) -> List[ReactionIO]:
    return [ReactionIO(section=r.Section, when=r.WhenTest, return_codes=r.WhenReturnCodes,
                       actions=[ReactionActionIO(action=a.Action, max_times=a.MaxTimes, wait_seconds=a.WaitSeconds,
                                                 target=a.target_item.ItemName if a.target_item else None,
                                                 workflow=a.target_job.JobKey if a.target_job else None)
                                for a in r.actions])
            for r in sorted(reactions, key=lambda r: (r.Section != "NEXT", r.ReactionOrder))]


# ---------- Checking ----------

def check(db: Session, label: str, submitted: List[ReactionIO], home: Job, upstream: Optional[Set[str]] = None,
          names: Optional[List[str]] = None, own_name: Optional[str] = None) -> None:
    """
    Refuses Reactions that break a rule. label names whose they are ("'Load'", "The job").
    home: the job they belong to, or the workflow a use is in. In a workflow, upstream holds the
    names of the jobs this one waits for, directly or not, and names every job in it.
    """
    in_workflow = names is not None
    for number, entry in enumerate(submitted, start=1):
        where = f"{label}, Reaction {number}"
        _check_entry(where, entry)
        for act in entry.actions:
            _check_action(db, where, entry, act, home, in_workflow, upstream or set(), names or [], own_name)


def _check_entry(where: str, entry: ReactionIO) -> None:
    if entry.section not in Reaction.SECTIONS:
        raise ReactionError(f"{where}: its section must be NEXT (What happens next) or ALSO, not '{entry.section}'.")
    if entry.when not in Reaction.TESTS:
        raise ReactionError(f"{where}: its When must be SUCCESS, FAILED, ENDED or RC, not '{entry.when}'.")
    if entry.when == "RC" and return_codes.problem(entry.return_codes):
        raise ReactionError(f"{where}: {return_codes.problem(entry.return_codes)}")
    if not entry.actions:
        raise ReactionError(f"{where} does nothing. Choose what it does, or remove it.")
    actions = [a.action for a in entry.actions]
    if sum(a.startswith("COUNT_AS") for a in actions) > 1:
        raise ReactionError(f"{where} counts the job as succeeded and as failed. Keep one.")
    if sum(a in ("RERUN", "RERUN_FROM", "KILL_WORKFLOW") for a in actions) > 1:
        raise ReactionError(f"{where} both reruns and kills, or reruns twice. Keep one of Rerun, Rerun from… "
                            "and Kill the workflow.")


def _check_action(db, where, entry, act: ReactionActionIO, home, in_workflow, upstream, names, own_name) -> None:
    if act.action not in DECISIONS + SIDE_EFFECTS:
        raise ReactionError(f"{where}: '{act.action}' is not an action AutoApp knows.")
    words = WORDS[act.action].capitalize()
    if entry.section == "NEXT" and act.action in SIDE_EFFECTS:
        raise ReactionError(f"{where}: {words} changes nothing in the run, so it belongs under Also.")
    if entry.section == "ALSO" and act.action not in SIDE_EFFECTS:
        raise ReactionError(f"{where}: {words} decides what happens next, so it belongs under What happens next.")
    if act.action in ONLY_IN_WORKFLOWS and not in_workflow:
        raise ReactionError(f"{where}: {words} needs a workflow around the job, so only a use of it in a workflow "
                            "offers it. Add it there.")
    if act.action in LIMITED:
        _check_limits(where, act)
    if act.action == "RERUN_FROM" and act.target not in upstream:
        raise ReactionError(f"{where}: Rerun from '{act.target or ''}' must name a job {own_name and repr(own_name)} "
                            "waits for, directly or not.")
    if act.action == "SKIP" and (act.target not in names or act.target == own_name):
        raise ReactionError(f"{where}: Skip must name another job in this workflow, not '{act.target or ''}'.")
    if act.action == "START_WORKFLOW":
        _check_start(db, where, act, home)


def _check_limits(where: str, act: ReactionActionIO) -> None:
    if not 1 <= (act.max_times or 0) <= MAX_TIMES:
        raise ReactionError(f"{where}: a rerun runs at most 1 to {MAX_TIMES} times. Say how many.")
    if not 0 <= (act.wait_seconds or 0) <= MAX_WAIT:
        raise ReactionError(f"{where}: the wait before a rerun is 0 to {MAX_WAIT} seconds.")


def _check_start(db: Session, where: str, act: ReactionActionIO, home: Job) -> None:
    from app.workflow_store import uses
    target = db.query(Job).filter(Job.JobKey == (act.workflow or "").strip()).first()
    if target is None or target.JobType != "WORKFLOW":
        raise ReactionError(f"{where}: Start a workflow must name a workflow, and '{act.workflow or ''}' is not one.")
    if target.MasterObject_id == home.MasterObject_id or uses(target, home.MasterObject_id):
        raise ReactionError(f"{where}: starting '{target.JobKey}' would start this again, and again. "
                            "Choose a workflow that does not use it.")


# ---------- Saving ----------

def apply(db: Session, reactions: List[Reaction], submitted: List[ReactionIO], owner: dict,
          items: Optional[Dict[str, object]] = None) -> bool:
    """Makes the list match what was submitted. owner: {"Job_MasterObject_id": ...} or {"Item_id": ...}. Returns whether it changed."""
    if describe(reactions) == sorted((_normal(e) for e in submitted), key=lambda e: e.section != "NEXT"):
        return False
    reactions.clear()
    order = {"NEXT": 0, "ALSO": 0}
    for entry in submitted:
        order[entry.section] += 1
        reaction = Reaction(Section=entry.section, ReactionOrder=order[entry.section], WhenTest=entry.when,
                            WhenReturnCodes=return_codes.normal(entry.return_codes) if entry.when == "RC" else None,
                            **owner)
        for position, act in enumerate(entry.actions, start=1):
            reaction.actions.append(_action(db, act, position, items or {}))
        reactions.append(reaction)
    return True


def _action(db: Session, act: ReactionActionIO, position: int, items: Dict[str, object]) -> ReactionAction:
    limited = act.action in LIMITED
    target = db.query(Job).filter(Job.JobKey == act.workflow.strip()).first() if act.workflow else None
    return ReactionAction(ActionOrder=position, Action=act.action, MaxTimes=act.max_times if limited else None,
                          WaitSeconds=(act.wait_seconds or 0) if limited else None,
                          target_item=items.get(act.target) if act.action in ("RERUN_FROM", "SKIP") else None,
                          target_job=target if act.action == "START_WORKFLOW" else None)


def _normal(entry: ReactionIO) -> ReactionIO:
    """An entry as it would be saved, so an unchanged list is recognised."""
    actions = [ReactionActionIO(action=a.action, max_times=a.max_times if a.action in LIMITED else None,
                                wait_seconds=(a.wait_seconds or 0) if a.action in LIMITED else None,
                                target=a.target if a.action in ("RERUN_FROM", "SKIP") else None,
                                workflow=a.workflow.strip() if a.action == "START_WORKFLOW" and a.workflow else None)
               for a in entry.actions]
    return ReactionIO(section=entry.section, when=entry.when,
                      return_codes=return_codes.normal(entry.return_codes) if entry.when == "RC" else None,
                      actions=actions)


def started_by(db: Session, workflow: Job) -> List[str]:
    """Whose Reactions start the workflow, in words: "'FINANCE_DAILY'" or "'Load' in 'FINANCE_DAILY'"."""
    found = []
    for action in db.query(ReactionAction).filter(ReactionAction.TargetJob_MasterObject_id == workflow.MasterObject_id):
        reaction = action.reaction
        if reaction.Job_MasterObject_id:
            found.append(repr(db.get(Job, reaction.Job_MasterObject_id).JobKey))
        else:
            item = db.get(WorkflowItem, reaction.Item_id)
            found.append(f"'{item.ItemName}' in '{item.workflow.JobKey}'")
    return sorted(set(found))

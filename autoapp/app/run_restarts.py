"""
The record of a run being run again, and the list the run and log pages show (docs/WORKFLOWS_PHASE7.md, step 5-2).

An operator's Resume or Restart is written by the API when it is requested: one RunRestarts row and one Audit Log
row (JOB_RESUMED or JOB_RESTARTED) for each request. A Reaction's rerun is not copied: the list merges the
Reaction events in when it is read, so nothing here depends on the runner or on telemetry.
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import Audit, Job, JobRun, ReactionEvent, RunRestart

RESUME, RESTART = "RESUME", "RESTART"
BY_OPERATOR, BY_REACTION = "web interface", "a Reaction"


class RestartOut(BaseModel):
    """One time a run was run again, by an operator or by a Reaction, in the order they happened."""
    number: int = Field(..., description="1 for the first time the run was run again, 2 for the second")
    time: datetime
    kind: str = Field(..., description="RESUME or RESTART")
    by: str = Field(..., description="web interface, or a Reaction")
    words: str = Field(..., description="Resumed from attempt 1, or Restarted from the beginning")
    from_attempt: Optional[int] = Field(None, description="The attempt it went on from")
    scope: str = Field("", description="The item chosen, by path; empty for the whole run")
    items: List[str] = Field([], description="The items touched, each with what it got, in words")
    decisions: List[str] = Field([], description="What was chosen for steps that may have changed something")
    values_refreshed: bool = False
    edits: List[str] = Field([], description="Values changed, by name, with the old and new value; never a secret")
    message: Optional[str] = Field(None, description="For a Reaction: what it said")


# ---------- Writing ----------

def record(db: Session, job_key: str, run_id: str, kind: str, number: int, scope: str, details: Dict[str, Any],
           changes: List[str]) -> None:
    """Writes the run's restart row and its Audit Log row, in one commit."""
    db.add(RunRestart(RunID=run_id, Number=number, Kind=kind, Scope=scope, PerformedBy=BY_OPERATOR,
                      Details=json.dumps(details)))
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    db.add(Audit(MasterObject_id=job.MasterObject_id if job else None,
                 Action="JOB_RESUMED" if kind == RESUME else "JOB_RESTARTED",
                 PerformedBy=BY_OPERATOR, Details=json.dumps({"changes": changes})))
    db.commit()


def next_number(db: Session, run_id: str) -> int:
    """For a workflow run, which is reopened and keeps its ID: 1 for the first time, 2 for the second."""
    return db.query(RunRestart).filter(RunRestart.RunID == run_id).count() + 1


def details_for(plan, kind: str, decisions: Dict[str, str], refreshed: bool, edits: List[str]) -> Dict[str, Any]:
    """What the request did, for the row: the plan's items, the choices on unknown steps, the values."""
    if kind == RESUME:
        items = [f"{item.path} {item.what}" for item in plan.items] if plan.items else []
    else:
        items = [plan.scope or plan.job_key] if plan.scope else []
    return {"from_attempt": plan.attempt, "items": items, "decisions": _decision_words(plan, decisions),
            "values_refreshed": refreshed, "edits": edits}


def _decision_words(plan, chosen: Dict[str, str]) -> List[str]:
    """"Step 4 'Load' of 'Post': run again, as chosen." for each step of unknown effect the operator decided."""
    steps = plan.steps_to_decide or ([plan.step_to_decide] if plan.step_to_decide else [])
    words = {"run_again": "run again", "count_done": "counted as done"}
    found = []
    for step in steps:
        choice = chosen.get(step.path) if step.path is not None else chosen.get("")
        if choice in words:
            where = f" of '{step.path}'" if step.path else ""
            found.append(f"Step {step.step} '{step.title}'{where}: {words[choice]}, as chosen.")
    return found


def headline(plan, job_key: str, kind: str, details: Dict[str, Any]) -> str:
    """The Audit Log's words: "Resumed 'WF' from attempt 1: 'Load' and 'Reconcile' run again; ..." """
    what = f"'{plan.scope}' in '{job_key}'" if plan.scope else f"'{job_key}'"
    if kind == RESTART:
        return f"Restarted {what} from the beginning (it was attempt {plan.attempt})."
    touched = [item.path for item in plan.items]
    parts = [f"{_names(touched)} run again" if len(touched) > 1 else f"{_names(touched)} runs again"] if touched else []
    parts += [d.rstrip(".").replace(": ", " ", 1) for d in details["decisions"]]
    return f"Resumed {what} from attempt {plan.attempt}" + (": " + "; ".join(parts) + "." if parts else ".")


def _names(paths: List[str]) -> str:
    quoted = [f"'{p}'" for p in paths]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " and " + quoted[-1]


# ---------- Reading ----------

def restarts_for(db: Session, run: JobRun) -> List[RestartOut]:
    """
    Every time the run was run again, operator's and Reaction's, by time. A job on its own is a new run each
    attempt, so its list is that of the whole chain (every run of the same instance); a job inside a workflow has
    none of its own: its workflow's run carries them.
    """
    if run.ParentRun_id is not None:
        return []
    chain = _chain(db, run)
    rows = db.query(RunRestart).filter(RunRestart.RunID.in_([r.RunID for r in chain])).all()
    found = [_from_row(r) for r in rows] + _from_reactions(db, run, chain)
    found.sort(key=lambda r: r.time)
    return [r.model_copy(update={"number": position}) for position, r in enumerate(found, start=1)]


def _chain(db: Session, run: JobRun) -> List[JobRun]:
    if run.JobType == "WORKFLOW":
        return [run]
    return (db.query(JobRun).filter(JobRun.JobKey == run.JobKey, JobRun.SchedulerInstanceID == run.SchedulerInstanceID,
                                    JobRun.ParentRun_id.is_(None)).order_by(JobRun.Attempt).all())


def _from_row(row: RunRestart) -> RestartOut:
    details = json.loads(row.Details or "{}")
    return RestartOut(number=row.Number, time=row.ChosenDateTime, kind=row.Kind, by=row.PerformedBy,
                      words=_words(row.Kind, details.get("from_attempt")), from_attempt=details.get("from_attempt"),
                      scope=row.Scope or "", items=details.get("items", []), decisions=details.get("decisions", []),
                      values_refreshed=bool(details.get("values_refreshed")), edits=details.get("edits", []))


def _from_reactions(db: Session, run: JobRun, chain: List[JobRun]) -> List[RestartOut]:
    """The Reaction events that ran an item or the job again, as list entries."""
    if run.JobType == "WORKFLOW":
        # a workflow's items' events name it; its own Reaction's name only the run itself
        condition = or_(ReactionEvent.WorkflowRun_id == run.id,
                        and_(ReactionEvent.JobRun_id == run.id, ReactionEvent.WorkflowRun_id.is_(None)))
    else:
        condition = ReactionEvent.JobRun_id.in_([r.id for r in chain])
    events = (db.query(ReactionEvent).filter(condition, ReactionEvent.Action.in_(("RERUN", "RERUN_FROM")),
                                             ReactionEvent.Result == "TOOK_EFFECT").order_by(ReactionEvent.id))
    attempts = {r.id: r.Attempt for r in chain}
    found = []
    for event in events:
        kind = RESUME if "from where it failed" in (event.Message or "") else RESTART
        from_attempt = attempts.get(event.JobRun_id) if run.JobType != "WORKFLOW" else None
        found.append(RestartOut(number=0, time=event.EventDateTime, kind=kind, by=BY_REACTION,
                                words=_words(kind, from_attempt), from_attempt=from_attempt,
                                scope=event.WorkflowPath or "", message=event.Message))
    return found


def _words(kind: str, from_attempt: Optional[int]) -> str:
    if kind == RESUME:
        return f"Resumed from attempt {from_attempt}" if from_attempt else "Resumed from where it failed"
    return "Restarted from the beginning"


def summary_for(db: Session, run: JobRun) -> Tuple[int, Optional[str]]:
    """
    For Job History: how many times the run was run again, and in words how, "Resumed by you, then restarted by a
    Reaction". A reopened workflow run counts its list; a job's attempt counts the attempts before it, and says
    how only for a job on its own (inside a workflow the workflow's run carries the list).
    """
    if run.ParentRun_id is not None:
        return max((run.Attempt or 1) - 1, 0), None
    if run.JobType != "WORKFLOW" and (run.Attempt or 1) <= 1:
        return 0, None
    listed = restarts_for(db, run)
    count = len(listed) if run.JobType == "WORKFLOW" else (run.Attempt or 1) - 1
    return count, _in_words(listed[:count])


def _in_words(listed: List[RestartOut]) -> Optional[str]:
    parts = [f"{'resumed' if r.kind == RESUME else 'restarted'} by {'you' if r.by == BY_OPERATOR else r.by}" for r in listed]
    return (", then ".join(parts)).capitalize() if parts else None

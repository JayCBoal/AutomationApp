"""
The clock lines of the run view and Explain (docs/WORKFLOWS_PHASE8.md, proposal 10): for a run still going, each timed
entry that has not fired yet, with the time it works out to, how that was worked out, and how long is left.

    Not ended by: due by 03:00 (in 42 minutes); the next 03:00 after the run started at 01:10

What already fired is not here: it is in the run's Reactions list, with what it did. Nothing is judged or changed here;
the runners' clocks do that (core/workflow_clock.py, engine/job_clock.py). This only works the same times out again.
"""
from datetime import datetime
from typing import List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from core.models import Job, JobRun, ReactionEvent, WorkflowItem, WorkflowRunItem
from core import clock_rules, outside
from core.clock_rules import HISTORY, NOT_ENDED_BY, NOT_STARTED_BY, RUNS_LONGER_THAN
from core.prerequisites import FINAL
from core.reactions import Rule, read_rules
from core.workflow_clock import durations_of, local

NOT_STARTED = ("PENDING", "WAITING")
LABELS = {NOT_STARTED_BY: "Not started by", NOT_ENDED_BY: "Not ended by", RUNS_LONGER_THAN: "Runs longer than"}


def fired_entries(db: Session, run: JobRun) -> Set[Tuple[Optional[str], int]]:
    """(item path, action id) of every timed action that took effect in the run; the path is None for the run's own."""
    events = db.query(ReactionEvent).filter(
        ReactionEvent.Result == "TOOK_EFFECT",
        (ReactionEvent.WorkflowRun_id == run.id) | (ReactionEvent.JobRun_id == run.id))
    return {(e.WorkflowPath or None, e.ReactionAction_id) for e in events}


def run_lines(db: Session, run: JobRun, fired: Set) -> List[str]:
    """The timed entries of the job or workflow itself, while it runs."""
    job = db.get(Job, run.Job_MasterObject_id) if run.Status == "RUNNING" and run.Job_MasterObject_id else None
    if job is None:
        return []
    started = local(run.StartedDateTime)
    return _lines(db, read_rules(job), job, None, fired, run_started=started, attempt_started=started, ready=None,
                  applies=lambda rule: rule.test != NOT_STARTED_BY)


def item_lines(db: Session, run: JobRun, row: WorkflowRunItem, fired: Set) -> List[str]:
    """The timed entries of one job of a workflow run, while it waits or runs."""
    item = db.get(WorkflowItem, row.Item_id) if row.Item_id and row.Status not in FINAL else None
    if item is None or run.Status != "RUNNING":
        return []
    attempt = local(row.StartedDateTime) if row.Status == "RUNNING" else None
    return _lines(db, read_rules(item.job, item), item.job, row.Path, fired, run_started=local(run.StartedDateTime),
                  attempt_started=attempt, ready=local(row.ReadyDateTime), applies=lambda rule: _applies(rule, row.Status))


def _applies(rule: Rule, status: str) -> bool:
    if rule.test == NOT_STARTED_BY:
        return status in NOT_STARTED
    return rule.test != RUNS_LONGER_THAN or status == "RUNNING"


def _lines(db: Session, rules: List[Rule], job: Job, path: Optional[str], fired: Set, run_started: datetime,
           attempt_started: Optional[datetime], ready: Optional[datetime], applies) -> List[str]:
    now = outside.now()
    lines = []
    for rule in rules:
        if rule.time is None or not applies(rule) or any((path, a.id) in fired for a in rule.actions):
            continue
        limit = _history_limit(db, job, rule) if rule.time.kind == HISTORY else None
        deadline = clock_rules.deadline_for(rule.time, run_started, attempt_started, ready, limit)
        lines.append(_line(rule, deadline, now))
    return lines


def _history_limit(db: Session, job: Job, rule: Rule):
    found = clock_rules.history_limit(durations_of(db, job.MasterObject_id, rule.time.run_count), rule.time.percent,
                                      rule.time.run_count)
    return found.limit


def _line(rule: Rule, deadline: clock_rules.Deadline, now: datetime) -> str:
    label = LABELS[rule.test]
    if deadline.due is None:
        return f"{label}: {deadline.how}"
    return f"{label}: {clock_rules.due_in_words(deadline.due, now)}; {deadline.how}"

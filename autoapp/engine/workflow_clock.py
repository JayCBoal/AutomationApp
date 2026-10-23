"""
The workflow runner's clock (docs/WORKFLOWS_PHASE8.md, step 3): time-based Reactions on the jobs of a workflow and on
the workflow itself. The runner calls this once a pass; the rules for working a deadline out and judging it are in
engine/clock_rules.py.

  - An entry fires once: once per workflow run for "not started by" and "not ended by", once per attempt for "runs
    longer than". What fired is a ReactionEvent row, so a reopened run knows (proposal 9).
  - An entry only ever has side effects (Mark as late, Start a workflow, Notify). It never changes how a job ends.
  - A job that was still waiting for another job of the workflow when its time passed says so (D183).
  - Everything is judged in the server's local time, as time-window prerequisites are.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from app.models import JobRun, ReactionEvent, RunRestart, utcnow
from engine import clock_rules, job_log, outside
from engine.clock_rules import HISTORY, NOT_STARTED_BY, RUNS_LONGER_THAN, Deadline
from engine.prerequisites import FINAL
from engine.reactions import Act, Rule, start_workflow

NOT_STARTED = ("PENDING", "WAITING")
SIDE_EFFECTS = ("MARK_AS_LATE", "START_WORKFLOW", "NOTIFY")


def local(moment: Optional[datetime]) -> Optional[datetime]:
    """A stored time (UTC) as the server's local clock shows it."""
    if moment is None:
        return None
    return moment.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def durations_of(db, job_id: int, count: Optional[int]) -> List[float]:
    """Seconds from start to end of a job's successful runs, newest first. Counted-as, resumed and killed runs are left out."""
    runs = db.query(JobRun).filter(
        JobRun.Job_MasterObject_id == job_id, JobRun.Status == "SUCCESS",
        JobRun.StatusBeforeOverride.is_(None), JobRun.StartedDateTime.isnot(None), JobRun.EndedDateTime.isnot(None),
        JobRun.RunID.notin_(db.query(RunRestart.RunID))
    ).order_by(JobRun.StartedDateTime.desc()).limit(count or clock_rules.DEFAULT_HISTORY_RUNS)
    return [(run.EndedDateTime - run.StartedDateTime).total_seconds() for run in runs]


@dataclass
class Watch:
    """One timed entry, on one job of the workflow (planned) or on the workflow itself (planned is None)."""
    rule: Rule
    planned: Optional[object] = None

    @property
    def path(self) -> str:
        return self.planned.row.Path if self.planned else ""

    @property
    def label(self) -> str:
        return f"'{self.planned.name}'" if self.planned else "The workflow"


class ClockWatcher:
    def __init__(self, runner):
        self.runner = runner
        self.watches: List[Watch] = []
        self.done: Set[Tuple] = set()               # entries not looked at again: fired, or no longer applicable
        self.limits: Dict[Tuple, Deadline] = {}     # "runs longer than" deadlines, worked out as each attempt started
        self.reopened_at: Optional[datetime] = None
        self.attempt_started: Optional[datetime] = None

    # --- The runner's calls ---

    def begin(self) -> None:
        """Once, after the run is planned: finds the timed entries and, for a reopened run, what already fired."""
        self.attempt_started = outside.now()
        self.watches = [Watch(rule, planned) for planned in self.runner.items for rule in planned.rules if rule.time]
        if self.runner.own is not None:
            self.watches += [Watch(rule) for rule in self.runner.own.rules if rule.time]
        if self.runner.options.reopen:
            self.reopened_at = self.attempt_started
            self._remember_fired()
        for watch in self.watches:
            if watch.planned is None and watch.rule.test == RUNS_LONGER_THAN:
                self._arm_longer(watch, self.runner.workflow, self.attempt_started)

    def item_started(self, planned) -> None:
        """A job of the workflow has just started an attempt: its "runs longer than" limits are worked out now."""
        for watch in self.watches:
            if watch.planned is planned and watch.rule.test == RUNS_LONGER_THAN:
                self._arm_longer(watch, planned.job, local(planned.row.StartedDateTime))

    def watch(self) -> None:
        """Once a pass: fires what is due. A workflow being killed fires nothing: Reactions no longer apply."""
        if self.runner.killing:
            return
        now = outside.now()
        for watch in self.watches:
            if self._key(watch) not in self.done and self._applies(watch):
                self._look(watch, now)

    def carry_late(self, planned, child: Optional[JobRun]) -> None:
        """A job that ended was marked late while running: its run record says so too."""
        row = planned.row
        if child is not None and row.LateDateTime is not None and child.LateDateTime is None:
            child.LateDateTime, child.LateReason, child.LateCause = row.LateDateTime, row.LateReason, row.LateCause

    # --- What to look at ---

    def _key(self, watch: Watch) -> Tuple:
        attempt = watch.planned.row.Attempt if watch.planned and watch.rule.test == RUNS_LONGER_THAN else 0
        return (watch.path, watch.rule.id, attempt)

    def _applies(self, watch: Watch) -> bool:
        """Whether the entry still means anything: "not started by" until it starts, "longer than" while it runs."""
        if watch.planned is None:
            return watch.rule.test != NOT_STARTED_BY
        status = watch.planned.row.Status
        if status in FINAL:
            return False
        if watch.rule.test == NOT_STARTED_BY and status not in NOT_STARTED:
            self.done.add(self._key(watch))
            return False
        return watch.rule.test != RUNS_LONGER_THAN or status == "RUNNING"

    def _remember_fired(self) -> None:
        """Entries a reopened run already fired are not fired again (proposal 9)."""
        by_action = {a.id: w for w in self.watches if w.rule.test != RUNS_LONGER_THAN for a in w.rule.actions}
        events = self.runner.db.query(ReactionEvent).filter(
            ReactionEvent.ReactionAction_id.in_(list(by_action)), ReactionEvent.Result == "TOOK_EFFECT",
            (ReactionEvent.WorkflowRun_id == self.runner.record.id) | (ReactionEvent.JobRun_id == self.runner.record.id))
        for event in events:
            watch = by_action[event.ReactionAction_id]
            if event.WorkflowPath == (watch.path or None) or watch.planned is None:
                self.done.add(self._key(watch))

    # --- Working deadlines out and judging them ---

    def _arm_longer(self, watch: Watch, job, attempt_started: datetime) -> None:
        rule = watch.rule.time
        limit = None
        if rule.kind == HISTORY:
            found = clock_rules.history_limit(self._durations(job, rule.run_count), rule.percent, rule.run_count)
            limit = found.limit
            job_log.summary(f"{watch.label}: {found.log_line}")
        self.limits[self._key(watch)] = clock_rules.deadline_for(rule, self._run_started(), attempt_started, limit=limit)

    def _durations(self, job, count: Optional[int]) -> List[float]:
        return durations_of(self.runner.db, job.MasterObject_id, count)

    def _run_started(self) -> datetime:
        return local(self.runner.record.StartedDateTime)

    def _deadline(self, watch: Watch) -> Optional[Deadline]:
        if watch.rule.test == RUNS_LONGER_THAN:
            return self.limits.get(self._key(watch))
        ready = local(watch.planned.row.ReadyDateTime) if watch.planned else None
        return clock_rules.deadline_for(watch.rule.time, self._run_started(), ready=ready)

    def _look(self, watch: Watch, now: datetime) -> None:
        deadline = self._deadline(watch)
        if deadline is None:
            return
        started = watch.planned is None or watch.planned.row.Status not in NOT_STARTED
        verdict = clock_rules.judge(deadline, watch.rule.test, now, started, False, reopened_at=self.reopened_at)
        if verdict.settled:
            self.done.add(self._key(watch))
            job_log.summary(f"{watch.label}: {verdict.why}.")
        elif verdict.fires:
            self.done.add(self._key(watch))
            self._fire(watch, deadline)

    # --- Firing ---

    def _fire(self, watch: Watch, deadline: Deadline) -> None:
        reason = self._reason(watch, deadline)
        cause, cause_late = self._cause(watch) if watch.planned and watch.planned.row.Status in NOT_STARTED else (None, False)
        told = reason + (f": {cause}" if cause else "")
        for act in watch.rule.actions:
            if act.action == "MARK_AS_LATE":
                self._mark_late(watch, reason, cause, told)
            elif act.action == "START_WORKFLOW":
                self._start_workflow(watch, act, told)
            elif act.action == "NOTIFY":
                self._notify(watch, act, told, cause_late)
            else:
                self._event(watch, act, "NOT_FIRED", f"{told}. {act.words().capitalize()} was not carried out: "
                                                     f"a time can only mark as late, notify or start a workflow.")

    def _reason(self, watch: Watch, deadline: Deadline) -> str:
        if watch.rule.test == RUNS_LONGER_THAN:
            started = local(watch.planned.row.StartedDateTime) if watch.planned else self.attempt_started
            return f"{watch.label} has run longer than {clock_rules.length_words(deadline.due - started)}"
        words = "started" if watch.rule.test == NOT_STARTED_BY else "ended"
        return f"{watch.label} had not {words} by {clock_rules.shown(deadline.due)}"

    def _cause(self, watch: Watch) -> Tuple[Optional[str], bool]:
        """What a job that has not started was waiting for in this workflow, and whether a job it waited for was late (D183)."""
        waiting, late = [], False
        for target, _test, _codes in watch.planned.prerequisites:
            row = self.runner.by_name[target].row
            late = late or row.LateDateTime is not None
            if row.Status not in FINAL:
                since = f"has been running since {clock_rules.shown(local(row.StartedDateTime))}" if row.Status == "RUNNING" \
                    else "has not started"
                waiting.append(f"'{target}', which {since}")
        return ("waiting for " + "; ".join(waiting) if waiting else None), late

    def _mark_late(self, watch: Watch, reason: str, cause: Optional[str], told: str) -> None:
        """Sets the flag on the item and on its run, keeping the first reason: a run can be late for several."""
        for holder in self._holders(watch):
            if holder.LateDateTime is None:
                holder.LateDateTime, holder.LateReason, holder.LateCause = utcnow(), reason, cause
        self._event(watch, self._first(watch, "MARK_AS_LATE"), "TOOK_EFFECT", f"{told}. Marked as late.")

    def _start_workflow(self, watch: Watch, act: Act, told: str) -> None:
        o = self.runner.options
        instance = start_workflow(act.target_job, o.spool_dir, o.api_url, o.working_root, o.log_level)
        self._event(watch, act, "TOOK_EFFECT", f"{told}. Started workflow '{act.target_job}', instance {instance}.")

    def _notify(self, watch: Watch, act: Act, told: str, cause_late: bool) -> None:
        """Notify arrives with the alert outbox (step 5); until then a Notify is recorded as not carried out."""
        self._event(watch, act, "NOT_FIRED", f"{told}. Notify '{act.alert_name}' was not carried out: alerts are not built yet.")

    def _first(self, watch: Watch, action: str) -> Act:
        return next(a for a in watch.rule.actions if a.action == action)

    def _holders(self, watch: Watch) -> list:
        """What carries the late flag: the item's row and its run record, or the workflow's own run record."""
        if watch.planned is None:
            return [self.runner.record]
        child = self._child(watch.planned)
        return [watch.planned.row] + ([child] if child else [])

    def _child(self, planned) -> Optional[JobRun]:
        if not planned.run_id:
            return None
        return self.runner.db.query(JobRun).filter(JobRun.RunID == planned.run_id).first()

    def _event(self, watch: Watch, act: Act, result: str, message: str) -> None:
        record = self.runner.record
        if watch.planned is None:
            event = ReactionEvent(JobRun_id=record.id, ReactionAction_id=act.id, Action=act.action, Result=result, Message=message)
        else:
            child = self._child(watch.planned)
            event = ReactionEvent(JobRun_id=child.id if child else None, WorkflowRun_id=record.id, WorkflowPath=watch.path,
                                  ReactionAction_id=act.id, Action=act.action, Result=result, Message=message)
        self.runner.db.add(event)
        (job_log.warning if act.action == "MARK_AS_LATE" else job_log.summary)(message)

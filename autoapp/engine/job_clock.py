"""
The job runner's clock (docs/WORKFLOWS_PHASE8.md, step 4): time-based Reactions on a job run on its own.

A small thread watches while the job's steps run. Only "has not ended by" and "runs longer than" apply to a job
on its own (D180); both count from the job's own start. The rules for working a deadline out and judging it are in
core/clock_rules.py; the workflow runner has its own watcher (core/workflow_clock.py).

  - The thread only fires side effects (Mark as late, Start a workflow, Notify). It never decides anything about
    the run, so nothing it does can change how the job ends.
  - It never touches the database: a job runner on an agent host does not write it. What it did leaves through
    the telemetry client as REACTION records, like every other record, and may arrive late.
  - The thread's work is a comparison once a second and, when something fires, one short record. If it fails, the
    job carries on: the failure goes to the job log and the clock stops.
"""
import os
import threading
from datetime import datetime, timedelta
from typing import List, Optional

from core import clock_rules, job_log, outside
from core.clock_rules import HISTORY, NOT_ENDED_BY, RUNS_LONGER_THAN, Deadline, TimeRule
from core.reactions import Act, Rule, start_workflow

POLL_SECONDS = float(os.getenv("AUTOAPP_JOB_CLOCK_POLL_SECONDS", "1"))
APPLIES = (NOT_ENDED_BY, RUNS_LONGER_THAN)
CLOCK_KINDS = (clock_rules.CLOCK, clock_rules.AFTER_START, clock_rules.LENGTH, HISTORY)


class Entry:
    """One timed entry: its rule, the deadline worked out at the start, and whether it has fired."""
    def __init__(self, rule: Rule, deadline: Deadline, began: datetime):
        self.rule, self.deadline, self.began, self.fired = rule, deadline, began, False


class JobClock:
    def __init__(self, rules: List[Rule], telemetry, durations, options: dict, job_name: str):
        """
        durations(count) gives the seconds from start to end of the job's successful runs, newest first, read
        from Job History before the job starts (the thread itself reads no database).
        """
        self.rules = [r for r in rules if r.time and r.time.test in APPLIES]
        self.telemetry, self.durations, self.options, self.job_name = telemetry, durations, options, job_name
        self.entries: List[Entry] = []
        self.late = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def wanted(self) -> bool:
        return bool(self.rules)

    # --- The runner's calls ---

    def start(self) -> None:
        """Works the deadlines out, once, as the job starts, and starts watching. Never raises."""
        if not self.rules:
            return
        try:
            begun = outside.now()
            self.entries = [Entry(rule, self._deadline(rule, begun), begun) for rule in self.rules]
            for entry in self.entries:
                job_log.debug(f"Time-based Reaction '{entry.rule.when_words()}': {self._how(entry)}")
        except Exception as problem:
            job_log.warning(f"The job's time-based Reactions could not be set up and are not watched: {problem}")
            return
        self._thread = threading.Thread(target=self._watch, name="job-clock", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Called before the run's end is recorded, so no record of the clock can follow it."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    # --- Working deadlines out ---

    def _deadline(self, rule: Rule, begun: datetime) -> Deadline:
        time_rule: TimeRule = rule.time
        if time_rule.kind not in CLOCK_KINDS:
            return Deadline(None, f"{clock_rules.kind_words(time_rule.kind)} does not apply to a job run on its own.")
        limit = None
        if time_rule.kind == HISTORY:
            found = clock_rules.history_limit(self.durations(time_rule.run_count), time_rule.percent, time_rule.run_count)
            limit = found.limit
            job_log.summary(f"'{self.job_name}': {found.log_line}")
        return clock_rules.deadline_for(time_rule, begun, begun, limit=limit)

    def _how(self, entry: Entry) -> str:
        due = entry.deadline.due
        return (f"due {clock_rules.day_words(due, outside.now())}; " if due else "not judged; ") + entry.deadline.how

    # --- Watching ---

    def _watch(self) -> None:
        try:
            while not self._stop.wait(POLL_SECONDS):
                now = outside.now()
                for entry in self.entries:
                    if not entry.fired:
                        self._look(entry, now)
                if all(e.fired or e.deadline.due is None for e in self.entries):
                    return
        except Exception as problem:
            job_log.warning(f"The job's clock stopped: {problem}")

    def _look(self, entry: Entry, now: datetime) -> None:
        verdict = clock_rules.judge(entry.deadline, entry.rule.test, now, started=True, ended=False)
        if verdict.fires and not self._stop.is_set():
            entry.fired = True
            self._fire(entry)

    def _fire(self, entry: Entry) -> None:
        due, rule = entry.deadline.due, entry.rule
        if rule.test == RUNS_LONGER_THAN:
            reason = f"'{self.job_name}' has run longer than {clock_rules.length_words(due - entry.began)}"
        else:
            reason = f"'{self.job_name}' had not ended by {clock_rules.shown(due)}"
        for act in rule.actions:
            if act.action == "MARK_AS_LATE":
                self._record(act, "TOOK_EFFECT", f"{reason}. Marked as late.", late_reason=reason)
            elif act.action == "START_WORKFLOW":
                instance = start_workflow(act.target_job, **self.options)
                self._record(act, "TOOK_EFFECT", f"{reason}. Started workflow '{act.target_job}', instance {instance}.")
            elif act.action == "NOTIFY":
                self._record(act, "TOOK_EFFECT", f"{reason}. Alert '{act.alert_name}' queued.")
            else:
                self._record(act, "NOT_FIRED", f"{reason}. {act.words().capitalize()} was not carried out: "
                                               f"a time can only mark as late, notify or start a workflow.")

    def _record(self, act: Act, result: str, message: str, late_reason: Optional[str] = None) -> None:
        (job_log.warning if act.action == "MARK_AS_LATE" else job_log.summary)(message)
        self.telemetry.record_reaction(act.action, result, message, act.id, late_reason=late_reason)
        self.telemetry.deliver()        # so a long step does not hold the news back

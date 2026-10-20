"""
A job's prerequisites outside its workflow, as one run sees them (docs/WORKFLOWS_PHASE5.md): what
each waits for, whether it holds now, and how long its patience lasts (D16, D99, D100, D101).

The workflow runner builds one Outside for each such prerequisite when it plans the run, and,
every pass, asks a waiting job's to look (reading the database or the disk, never the operations
log) and to judge their patience. The job's own state is then worked out from all its
prerequisites, inside or out, by engine.workflow_runner.readiness().
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from engine import conditions, outside, workflow_conditions
from engine.prerequisites import HOLDS, SKIPPED_OPTIONAL, TIMED_OUT, WAIT, prerequisite_state


@dataclass
class Context:
    """The run this pass is for: when it started, and what time it is now (UTC for the database, local for the clock)."""
    db: Session
    run_started: datetime               # UTC
    utc_now: datetime
    local_now: datetime
    ts_now: float                       # time.time()
    default_hours: int                  # the Default wait for outside prerequisites setting


@dataclass
class Outside:
    """One prerequisite on a job or workflow elsewhere, files, or the time."""
    id: int
    name: str                           # what conditions call it: MONTH_END.Extract, INBOUND_ORDERS
    kind: str                           # OTHER_JOB, ENDPOINT or TIME
    required: bool = True
    test: str = "SUCCESS"
    codes: Optional[str] = None
    target_item_id: Optional[int] = None
    target_workflow_id: Optional[int] = None
    look_back_hours: Optional[int] = None
    only_after_start: bool = False
    pattern: Optional[str] = None       # the files, with their folder
    min_age: Optional[int] = None
    time_condition: Optional[str] = None
    wait_mode: str = "DEFAULT"
    wait_minutes: Optional[int] = None
    wait_until: Optional[str] = None
    wait_from: str = "OTHERS"
    wait_from_id: Optional[int] = None
    # What it stands at: WAIT, HOLDS, TIMED_OUT or SKIPPED (an optional one that ran out of patience)
    state: str = WAIT
    holding: bool = False               # whether it holds right now, before patience is looked at
    values: Dict[str, Any] = field(default_factory=dict)
    words: str = ""
    run_id: Optional[str] = None        # the run of the other workflow that was used
    seen: Optional[str] = None          # how it stood when last looked at: a job's status, or SUCCESS / WAITING
    deadline: Optional[float] = None    # time.time() when its patience ends, once that is known
    unlimited: bool = False
    check: Any = None                   # the WorkflowPrerequisiteCheck row kept for this attempt

    def blank_values(self) -> Dict[str, Any]:
        """Every value it offers to conditions, unknown."""
        if self.kind == "ENDPOINT":
            return workflow_conditions.endpoint_values(self.name, None, None)
        if self.kind == "OTHER_JOB":
            return workflow_conditions.item_values(self.name, "PENDING", None, None, None, None, None, None)
        return {}

    def forget(self) -> None:
        """A new attempt of the job starts waiting afresh."""
        self.state, self.holding, self.deadline, self.check, self.run_id, self.seen = WAIT, False, None, None, None, None
        self.values, self.words = self.blank_values(), ""

    @property
    def label(self) -> str:
        return self.name

    # --- Looking ---

    def look(self, ctx: Context) -> None:
        """Reads what it waits for, setting holding, values, words and run_id."""
        {"OTHER_JOB": self._look_at_job, "ENDPOINT": self._look_at_files, "TIME": self._look_at_time}[self.kind](ctx)

    def _look_at_job(self, ctx: Context) -> None:
        after = ctx.run_started if self.only_after_start else None
        if self.target_item_id is not None:
            found = outside.find_job(ctx.db, self.target_item_id, self.look_back_hours, after, ctx.utc_now)
        else:
            found = outside.find_workflow(ctx.db, self.target_workflow_id, self.look_back_hours, after, ctx.utc_now)
        self.holding, self.values, self.run_id, self.seen = False, self.blank_values(), None, None
        if found is None:
            self.words = f"No run of '{self.name}' counts yet."
            return
        self.run_id, self.seen = found.run_id, found.status
        self.values = workflow_conditions.item_values(self.name, found.status, found.code, found.reason,
                                                      found.file_count, found.size, found.started, found.ended)
        self.holding = prerequisite_state(self.test, self.codes, found.status, found.code) == HOLDS
        self.words = f"'{self.name}' {_outcome(found)}, in run {found.run_id}."

    def _look_at_files(self, ctx: Context) -> None:
        seen = outside.look_at_files(self.pattern, self.min_age, ctx.ts_now)
        self.holding = seen.holds()
        self.seen = "SUCCESS" if self.holding else "WAITING"
        self.values = (workflow_conditions.endpoint_values(self.name, seen.count, seen.size) if self.holding
                       else self.blank_values())
        self.words = seen.words(self.pattern, self.min_age)

    def _look_at_time(self, ctx: Context) -> None:
        values = outside.now_values(ctx.local_now)
        try:
            self.holding = conditions.decide(self.time_condition, values) is True
        except ValueError:
            self.holding = False
        self.seen = "SUCCESS" if self.holding else "WAITING"
        self.words = f"{self.time_condition} is {'true' if self.holding else 'false'} at {values['%{Now.Time}']}."

    # --- Patience ---

    def judge(self, ctx: Context, held: Dict[int, float], others: List[int], run_start_ts: float) -> str:
        """
        Where it stands now: HOLDS, WAIT, or, once its patience has run out and it does not hold, TIMED_OUT (required)
        or SKIPPED (optional). Once it has timed out or been skipped it stays so for this attempt.
        held: when each prerequisite of the job first held (by id); others: the ids of the job's other prerequisites.
        """
        if self.state in (TIMED_OUT, SKIPPED_OPTIONAL):
            return self.state
        if self.holding:
            self.state = HOLDS
            return HOLDS
        self.deadline = self.patience_ends(ctx, held, others, run_start_ts)
        if self.deadline is not None and ctx.ts_now >= self.deadline:
            self.state = TIMED_OUT if self.required else SKIPPED_OPTIONAL
        else:
            self.state = WAIT
        return self.state

    def patience_ends(self, ctx: Context, held: Dict[int, float], others: List[int], run_start_ts: float) -> Optional[float]:
        """time.time() when it stops waiting, or None if it has no limit or the limit has not started counting."""
        self.unlimited = False
        if self.wait_mode == "NONE":
            self.unlimited = True
            return None
        if self.wait_mode == "UNTIL":
            return outside.clock_time_after(_local_from_ts(run_start_ts), self.wait_until).timestamp()
        start = clock_start(self.wait_from, self.wait_from_id, held, others, run_start_ts)
        if start is None:
            return None
        minutes = self.wait_minutes if self.wait_mode == "MINUTES" else ctx.default_hours * 60
        return start + (minutes or 0) * 60

    def limit_words(self, ctx_default_hours: int) -> str:
        """In words, as the waiting message says it: "until 03:00", "for up to 30 minutes", "with no limit"."""
        if self.wait_mode == "NONE":
            return "with no limit"
        if self.deadline is not None:
            return "until " + datetime.fromtimestamp(self.deadline).strftime("%H:%M")
        if self.wait_mode == "UNTIL":
            return f"until {self.wait_until}"
        minutes = self.wait_minutes if self.wait_mode == "MINUTES" else ctx_default_hours * 60
        return f"for up to {_duration(minutes or 0)}"


def clock_start(wait_from: str, chosen: Optional[int], held: Dict[int, float], others: List[int],
                run_start_ts: float) -> Optional[float]:
    """
    When "up to N minutes" starts counting (D99): after the job's other prerequisites have all held (OTHERS), after
    the first of them (FIRST), after the chosen one (CHOSEN), or from the start of the run (RUN_START).
    None while that has not happened yet. A job with no other prerequisite counts from the start of the run.
    """
    if wait_from == "RUN_START" or (wait_from in ("OTHERS", "FIRST") and not others):
        return run_start_ts
    if wait_from == "CHOSEN":
        return held.get(chosen) if chosen in others else run_start_ts
    times = [held[i] for i in others if i in held]
    if wait_from == "FIRST":
        return min(times) if times else None
    return max(times) if len(times) == len(others) else None


def _local_from_ts(ts: float) -> datetime:
    return datetime.fromtimestamp(ts)


def _duration(minutes: int) -> str:
    if minutes % 60 == 0 and minutes >= 60:
        hours = minutes // 60
        return f"{hours} hour{'' if hours == 1 else 's'}"
    return f"{minutes} minute{'' if minutes == 1 else 's'}"


def _outcome(found: "outside.Target") -> str:
    if found.status in ("SUCCESS", "BYPASSED"):
        return "succeeded"
    return {"FAILED": "failed", "NOT_RUN": "did not run", "DISABLED": "is disabled", "SKIPPED": "was skipped"}.get(
        found.status, "has not ended")

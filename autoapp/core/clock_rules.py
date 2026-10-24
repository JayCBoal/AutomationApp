"""
The clock rules of time-based Reactions (docs/WORKFLOWS_PHASE8.md, proposals 1 to 4, 9 and 10).

Pure: no database, no clock of its own. Every function is given the moment it should use, so a test can
make one up. Times are plain local datetimes (server local time, as time-window prerequisites use).

Three steps, which the runners call:
  - work out a deadline once, from a rule and the times it counts from (`deadline_for`);
  - for "longer than usual", work the limit out from Job History when the item starts (`history_limit`);
  - judge a deadline at a given moment (`judge`).

The rules never decide anything about a run. They only say "due at" and "fires now", so a late or missed
judgement cannot change how a run ends.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Sequence

NOT_STARTED_BY, NOT_ENDED_BY, RUNS_LONGER_THAN = "NOT_STARTED_BY", "NOT_ENDED_BY", "RUNS_LONGER_THAN"
CLOCK, AFTER_START, AFTER_READY, LENGTH, HISTORY = "CLOCK", "AFTER_START", "AFTER_READY", "LENGTH", "HISTORY"

# Which ways of giving a time each When accepts
KINDS_FOR = {
    NOT_STARTED_BY: (CLOCK, AFTER_START, AFTER_READY),
    NOT_ENDED_BY: (CLOCK, AFTER_START, AFTER_READY),
    RUNS_LONGER_THAN: (LENGTH, HISTORY),
}
MIN_HISTORY_RUNS = 3
DEFAULT_HISTORY_RUNS = 10


@dataclass
class TimeRule:
    """The time part of a Reaction entry, as the runners read it when the run starts."""
    test: str                                   # NOT_STARTED_BY, NOT_ENDED_BY or RUNS_LONGER_THAN
    kind: str                                   # CLOCK, AFTER_START, AFTER_READY, LENGTH or HISTORY
    clock_time: Optional[str] = None            # "03:00", for CLOCK
    minutes: Optional[int] = None               # for AFTER_START, AFTER_READY and LENGTH
    percent: Optional[int] = None               # for HISTORY: how far over the average
    run_count: Optional[int] = None             # for HISTORY: how many earlier runs to average


@dataclass
class Deadline:
    """When an entry is due, and how that was worked out. `due` is empty when it cannot be judged (yet)."""
    due: Optional[datetime]
    how: str


@dataclass
class Verdict:
    """What judging a deadline at one moment found. `fires` is the only thing a runner acts on."""
    fires: bool
    why: str
    settled: bool = False       # judged for good without firing: the runner stops looking at this entry


def problem_with(rule: TimeRule) -> Optional[str]:
    """Why a rule cannot be used, in plain words, or None when it is complete."""
    if rule.test not in KINDS_FOR:
        return f"'{rule.test}' is not a time-based When."
    if rule.kind not in KINDS_FOR[rule.test]:
        return f"{when_words(rule.test)} cannot be given as {kind_words(rule.kind)}."
    if rule.kind == CLOCK and _parse_clock(rule.clock_time) is None:
        return "Give the time of day as hours and minutes, like 03:00."
    if rule.kind in (AFTER_START, AFTER_READY, LENGTH) and not (rule.minutes and rule.minutes > 0):
        return "Give a number of minutes greater than zero."
    if rule.kind == HISTORY and not (rule.percent is not None and rule.percent >= 0):
        return "Give how many percent over the average counts as too long (0 or more)."
    if rule.kind == HISTORY and rule.run_count is not None and rule.run_count < MIN_HISTORY_RUNS:
        return f"Average at least {MIN_HISTORY_RUNS} earlier runs."
    return None


def when_words(test: str) -> str:
    return {NOT_STARTED_BY: "'Has not started by'", NOT_ENDED_BY: "'Has not ended by'",
            RUNS_LONGER_THAN: "'Runs longer than'"}.get(test, test)


def kind_words(kind: str) -> str:
    return {CLOCK: "a time of day", AFTER_START: "minutes after the start", AFTER_READY: "minutes after being ready",
            LENGTH: "a length", HISTORY: "a percentage over its history"}.get(kind, kind)


def _parse_clock(text: Optional[str]) -> Optional[tuple]:
    """('03:00') -> (3, 0); None for anything that is not a time of day."""
    try:
        hours, minutes = (text or "").split(":")
        hours, minutes = int(hours), int(minutes)
    except ValueError:
        return None
    return (hours, minutes) if 0 <= hours <= 23 and 0 <= minutes <= 59 else None


def next_clock_time(clock_time: str, after: datetime) -> datetime:
    """The next occurrence of a time of day strictly after a moment (D178): 03:00 after 23:00 is tomorrow."""
    hours, minutes = _parse_clock(clock_time)
    same_day = after.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    return same_day if same_day > after else same_day + timedelta(days=1)


def deadline_for(rule: TimeRule, run_started: Optional[datetime], attempt_started: Optional[datetime] = None,
                 ready: Optional[datetime] = None, limit: Optional[timedelta] = None) -> Deadline:
    """
    Work out when a rule is due.
      run_started      when the run started: the workflow's start for a job in a workflow, else the job's own.
      attempt_started  when this attempt of the job started (RUNS_LONGER_THAN counts from here; a rerun restarts it).
      ready            when the job's own prerequisites were met (AFTER_READY).
      limit            for HISTORY, the limit `history_limit` worked out when the item started.
    """
    wrong = problem_with(rule)
    if wrong:
        return Deadline(None, wrong)
    if rule.kind == CLOCK:
        return _from_run_start(rule, run_started, lambda start: next_clock_time(rule.clock_time, start),
                               f"the next {rule.clock_time} after")
    if rule.kind == AFTER_START:
        return _from_run_start(rule, run_started, lambda start: start + timedelta(minutes=rule.minutes),
                               f"{rule.minutes} minutes after")
    if rule.kind == AFTER_READY:
        return _after_ready(rule, ready)
    return _from_attempt(rule, attempt_started, limit)


def _from_run_start(rule: TimeRule, run_started: Optional[datetime], work_out, words: str) -> Deadline:
    if run_started is None:
        return Deadline(None, "The run has not started, so there is no time to count from.")
    return Deadline(work_out(run_started), f"{words} the run started at {shown(run_started)}")


def _after_ready(rule: TimeRule, ready: Optional[datetime]) -> Deadline:
    if ready is None:
        return Deadline(None, "Not ready yet: the time counts from when its prerequisites are met.")
    return Deadline(ready + timedelta(minutes=rule.minutes),
                    f"{rule.minutes} minutes after its prerequisites were met at {shown(ready)}")


def _from_attempt(rule: TimeRule, attempt_started: Optional[datetime], limit: Optional[timedelta]) -> Deadline:
    if attempt_started is None:
        return Deadline(None, "This attempt has not started, so there is no length to count.")
    if rule.kind == LENGTH:
        limit, words = timedelta(minutes=rule.minutes), f"{length_words(timedelta(minutes=rule.minutes))} after"
    elif limit is None:
        return Deadline(None, "'Longer than usual' was not judged: there was not enough history to work a limit out.")
    else:
        words = f"the history limit of {length_words(limit)} after"
    return Deadline(attempt_started + limit, f"{words} this attempt started at {shown(attempt_started)}")


@dataclass
class HistoryLimit:
    """The limit "longer than usual" works out to, or None with the reason it could not be."""
    limit: Optional[timedelta]
    log_line: str


def history_limit(durations: Sequence[float], percent: int, run_count: Optional[int] = None) -> HistoryLimit:
    """
    The limit for "N% over the average of the last K runs" (D182). `durations` are the seconds from start to end
    of the job's successful runs, newest first; killed, failed and reopened runs are left out by the caller.
    Needs at least 3 runs; with fewer there is no limit and the log line says why.
    """
    wanted = run_count or DEFAULT_HISTORY_RUNS
    used: List[float] = list(durations[:wanted])
    if len(used) < MIN_HISTORY_RUNS:
        return HistoryLimit(None, f"only {_runs(len(used))}; 'longer than usual' not judged")
    average = sum(used) / len(used)
    limit = timedelta(seconds=round(average * (100 + percent) / 100))
    return HistoryLimit(limit, f"limit {length_words(limit)}: {percent}% over the "
                               f"{length_words(timedelta(seconds=round(average)))} average of the last {len(used)} runs")


def _runs(count: int) -> str:
    return f"{count} earlier run" + ("" if count == 1 else "s")


def judge(deadline: Deadline, test: str, now: datetime, started: bool, ended: bool, already_fired: bool = False,
          reopened_at: Optional[datetime] = None) -> Verdict:
    """
    Does an entry fire at `now`? Once only (proposal 9). NOT_STARTED_BY fires if the item has not started by
    the deadline; NOT_ENDED_BY and RUNS_LONGER_THAN if it has not ended. A reopened run does not fire a deadline
    that passed while the run was ended.
    """
    if already_fired:
        return Verdict(False, "Already fired for this run.")
    if deadline.due is None:
        return Verdict(False, deadline.how)
    if now < deadline.due:
        return Verdict(False, f"Due at {shown(deadline.due)}, not yet.")
    if reopened_at is not None and deadline.due <= reopened_at:
        return Verdict(False, f"deadline {shown(deadline.due)} passed before the run was reopened; not judged", settled=True)
    if test == NOT_STARTED_BY:
        return Verdict(not started, "It had started in time." if started else
                       f"It had not started by {shown(deadline.due)}.")
    return Verdict(not ended, "It had ended in time." if ended else f"It had not ended by {shown(deadline.due)}.")


def shown(moment: datetime) -> str:
    """A moment as the logs show it: 03:00, or with the date when it is not today's concern."""
    return moment.strftime("%H:%M" if moment.second == 0 else "%H:%M:%S")


def length_words(length: timedelta) -> str:
    """90 minutes -> '1h30m'; 48 minutes -> '48m'; 30 seconds -> '30s'."""
    seconds = int(length.total_seconds())
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m" if not secs else f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def day_words(due: datetime, reference: datetime) -> str:
    """'03:00 tomorrow': what a deadline works out to for a run starting at `reference`, for the editor (proposal 3)."""
    days = (due.date() - reference.date()).days
    day = {0: "today", 1: "tomorrow"}.get(days, f"on {due.strftime('%Y-%m-%d')}")
    return f"{shown(due)} {day}"


def due_in_words(due: datetime, now: datetime) -> str:
    """'due by 03:00 (in 42 minutes)', or '(7 minutes ago)' once passed, for the run view (proposal 10)."""
    minutes = int(abs((due - now).total_seconds()) // 60)
    span = "less than a minute" if minutes == 0 else (f"{minutes} minute" + ("" if minutes == 1 else "s"))
    return f"due by {shown(due)} (in {span})" if due >= now else f"due by {shown(due)} ({span} ago)"

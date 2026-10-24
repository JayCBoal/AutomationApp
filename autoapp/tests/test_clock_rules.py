"""
The clock rules of time-based Reactions (core/clock_rules.py), with a made-up clock:
deadlines from a time of day or a length, "longer than usual" from history, and judging at a moment.
"""
from datetime import datetime, timedelta

from core.clock_rules import (
    AFTER_READY, AFTER_START, CLOCK, HISTORY, LENGTH, NOT_ENDED_BY, NOT_STARTED_BY, RUNS_LONGER_THAN,
    Deadline, TimeRule, day_words, deadline_for, due_in_words, history_limit, judge, length_words,
    next_clock_time, problem_with,
)


def at(day, hour, minute=0, second=0):
    return datetime(2026, 10, day, hour, minute, second)


# ---- a time of day: the next occurrence after the run started (D178)

def test_a_run_starting_at_23_00_is_due_at_03_00_tomorrow():
    assert next_clock_time("03:00", at(23, 23, 0)) == at(24, 3, 0)


def test_a_run_starting_at_01_00_is_due_at_03_00_today():
    assert next_clock_time("03:00", at(24, 1, 0)) == at(24, 3, 0)


def test_a_run_starting_exactly_at_the_time_is_due_tomorrow():
    assert next_clock_time("03:00", at(24, 3, 0)) == at(25, 3, 0)


def test_a_clock_deadline_counts_from_the_run_start_and_says_so():
    rule = TimeRule(NOT_ENDED_BY, CLOCK, clock_time="03:00")
    deadline = deadline_for(rule, run_started=at(23, 23, 0))
    assert deadline.due == at(24, 3, 0)
    assert "next 03:00" in deadline.how and "23:00" in deadline.how


def test_the_editor_wording_for_the_next_run():
    assert day_words(at(24, 3, 0), at(23, 23, 0)) == "03:00 tomorrow"
    assert day_words(at(24, 3, 0), at(24, 1, 0)) == "03:00 today"


# ---- lengths and relative times

def test_after_start_counts_from_the_run_start():
    rule = TimeRule(NOT_STARTED_BY, AFTER_START, minutes=120)
    assert deadline_for(rule, run_started=at(23, 22, 0)).due == at(24, 0, 0)


def test_after_ready_waits_for_the_prerequisites_then_counts_from_then():
    rule = TimeRule(NOT_STARTED_BY, AFTER_READY, minutes=30)
    assert deadline_for(rule, run_started=at(23, 22, 0)).due is None
    assert deadline_for(rule, run_started=at(23, 22, 0), ready=at(23, 23, 15)).due == at(23, 23, 45)


def test_a_fixed_length_counts_from_this_attempt_not_the_run():
    rule = TimeRule(RUNS_LONGER_THAN, LENGTH, minutes=90)
    deadline = deadline_for(rule, run_started=at(23, 20, 0), attempt_started=at(23, 22, 0))
    assert deadline.due == at(23, 23, 30)


def test_no_start_means_no_deadline_and_a_reason():
    rule = TimeRule(RUNS_LONGER_THAN, LENGTH, minutes=90)
    assert deadline_for(rule, run_started=at(23, 20, 0)).due is None


# ---- longer than usual (D182)

def test_the_limit_is_a_percentage_over_the_average_and_the_log_line_shows_it():
    result = history_limit([48 * 60] * 10, percent=50, run_count=10)
    assert result.limit == timedelta(minutes=72)
    assert result.log_line == "limit 1h12m: 50% over the 48m average of the last 10 runs"


def test_only_the_newest_runs_asked_for_are_averaged():
    durations = [600, 600, 600, 6000, 6000]
    assert history_limit(durations, percent=0, run_count=3).limit == timedelta(minutes=10)


def test_fewer_than_three_runs_is_not_judged_and_the_log_says_so():
    result = history_limit([600], percent=50)
    assert result.limit is None
    assert result.log_line == "only 1 earlier run; 'longer than usual' not judged"
    assert history_limit([], percent=50).log_line.startswith("only 0 earlier runs")


def test_exactly_three_runs_is_enough():
    assert history_limit([60, 120, 180], percent=100).limit == timedelta(minutes=4)


def test_a_history_rule_with_no_limit_cannot_be_judged():
    rule = TimeRule(RUNS_LONGER_THAN, HISTORY, percent=50)
    deadline = deadline_for(rule, run_started=at(23, 22), attempt_started=at(23, 22), limit=None)
    assert deadline.due is None and "not enough history" in deadline.how
    limit = timedelta(minutes=72)
    assert deadline_for(rule, run_started=at(23, 22), attempt_started=at(23, 22), limit=limit).due == at(23, 23, 12)


# ---- judging at a moment

def test_not_ended_by_fires_once_the_deadline_passes_while_running():
    deadline = Deadline(at(24, 3, 0), "x")
    assert not judge(deadline, NOT_ENDED_BY, at(24, 2, 59), started=True, ended=False).fires
    assert judge(deadline, NOT_ENDED_BY, at(24, 3, 0), started=True, ended=False).fires


def test_not_ended_by_does_not_fire_for_a_run_that_ended_in_time():
    assert not judge(Deadline(at(24, 3, 0), "x"), NOT_ENDED_BY, at(24, 4, 0), started=True, ended=True).fires


def test_not_started_by_fires_only_when_the_item_has_not_started():
    deadline = Deadline(at(24, 3, 0), "x")
    assert judge(deadline, NOT_STARTED_BY, at(24, 3, 1), started=False, ended=False).fires
    assert not judge(deadline, NOT_STARTED_BY, at(24, 3, 1), started=True, ended=False).fires


def test_an_entry_fires_once_only():
    verdict = judge(Deadline(at(24, 3, 0), "x"), RUNS_LONGER_THAN, at(24, 4, 0), True, False, already_fired=True)
    assert not verdict.fires


def test_a_deadline_with_no_time_never_fires_and_gives_its_reason():
    verdict = judge(Deadline(None, "Not ready yet."), NOT_STARTED_BY, at(24, 4, 0), False, False)
    assert not verdict.fires and verdict.why == "Not ready yet."


def test_a_reopened_run_does_not_fire_a_deadline_that_passed_while_it_was_ended():
    deadline = Deadline(at(24, 3, 0), "x")
    verdict = judge(deadline, NOT_ENDED_BY, at(24, 6, 0), True, False, reopened_at=at(24, 5, 0))
    assert not verdict.fires
    assert verdict.why == "deadline 03:00 passed before the run was reopened; not judged"
    later = Deadline(at(24, 5, 30), "x")
    assert judge(later, NOT_ENDED_BY, at(24, 6, 0), True, False, reopened_at=at(24, 5, 0)).fires


# ---- checking a rule, and words

def test_a_rule_must_be_complete_and_use_a_way_its_when_accepts():
    assert problem_with(TimeRule(NOT_ENDED_BY, CLOCK, clock_time="03:00")) is None
    assert "time of day" in problem_with(TimeRule(NOT_ENDED_BY, CLOCK, clock_time="25:00"))
    assert "cannot be given" in problem_with(TimeRule(RUNS_LONGER_THAN, CLOCK, clock_time="03:00"))
    assert "minutes" in problem_with(TimeRule(NOT_STARTED_BY, AFTER_START))
    assert problem_with(TimeRule(RUNS_LONGER_THAN, HISTORY, percent=50, run_count=2)) is not None
    assert problem_with(TimeRule(RUNS_LONGER_THAN, HISTORY, percent=50)) is None


def test_lengths_and_due_times_in_plain_words():
    assert length_words(timedelta(minutes=90)) == "1h30m"
    assert length_words(timedelta(hours=2)) == "2h"
    assert length_words(timedelta(minutes=48)) == "48m"
    assert length_words(timedelta(seconds=30)) == "30s"
    assert due_in_words(at(24, 3, 0), at(24, 2, 18)) == "due by 03:00 (in 42 minutes)"
    assert due_in_words(at(24, 3, 0), at(24, 3, 7)) == "due by 03:00 (7 minutes ago)"

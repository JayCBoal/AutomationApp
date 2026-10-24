"""
Workflows Phase 5, step 2: what a job waits for outside its workflow, and how patient it is
(docs/WORKFLOWS_PHASE5.md). The helpers that need no database are tried on their own; the rest
runs workflows the way a scheduler would, with engine.runner as a separate process.
"""
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from core.models import (Job, JobRun, WorkflowItem, WorkflowPrerequisite, WorkflowPrerequisiteCheck, WorkflowRunItem,
                        utcnow)
from core import conditions, outside, workflow_conditions
from engine import outside_state
from core.prerequisites import HOLDS, NEVER, SKIPPED_OPTIONAL, TIMED_OUT, WAIT
from engine.workflow_runner import Planned, readiness
from test_workflow_runner import flow, results, run_flow, sim, start, states     # noqa: F401  (fixtures)

ALWAYS = "%{Now.Date} > '2000-01-01'"
NEVER_OPEN = "%{Now.Date} < '2000-01-01'"


# ---------- Without a database ----------

def test_a_window_that_spans_midnight_is_translated_to_plain_comparisons():
    assert conditions.expand_windows("%{Now.Time} IN WINDOW '18:00' TO '06:00'") == \
        "(%{Now.Time} >= '18:00' OR %{Now.Time} <= '06:00')"
    assert conditions.expand_windows("%{Now.Time} in window '06:00' to '18:00' AND 1 = 1") == \
        "(%{Now.Time} >= '06:00' AND %{Now.Time} <= '18:00') AND 1 = 1"


@pytest.mark.parametrize("clock, holds", [("23:30", True), ("03:00", True), ("12:00", False), ("18:00", True), ("06:00", True)])
def test_a_window_across_midnight_is_open_at_night(clock, holds):
    values = {"%{Now.Time}": clock}
    assert conditions.decide("%{Now.Time} IN WINDOW '18:00' TO '06:00'", values) is holds


def test_the_time_is_a_value_conditions_can_read():
    moment = datetime(2026, 10, 19, 14, 5)           # a Monday
    assert outside.now_values(moment) == {"%{Now.Time}": "14:05", "%{Now.Date}": "2026-10-19", "%{Now.Weekday}": "Monday"}
    assert conditions.decide("%{Now.Weekday} = 'Monday' AND %{Now.Time} BETWEEN '06:00' AND '18:00'",
                             outside.now_values(moment)) is True


def test_an_outside_name_may_hold_dots_and_a_condition_can_still_name_its_output():
    outside_names = {"MONTH_END.Extract": "OTHER_JOB", "INBOUND": "ENDPOINT"}
    assert workflow_conditions.split_ref("%{MONTH_END.Extract.Status}", list(outside_names)) == ("MONTH_END.Extract", "Status")
    assert workflow_conditions.split_ref("%{Load.Status}", list(outside_names)) == ("Load", "Status")
    rule = "%{MONTH_END.Extract.Succeeded} AND %{INBOUND.FileCount} > 2 AND %{Load.Ended} AND %{Now.Time} > '06:00'"
    assert workflow_conditions.named_jobs(rule, list(outside_names)) == ["Load"]
    problems, _ = workflow_conditions.check(rule, ["Load"], outside=outside_names)
    assert problems == []


def test_a_condition_on_outside_names_says_what_is_wrong_with_them():
    names = {"INBOUND": "ENDPOINT", "Window": "TIME", "UP.Extract": "OTHER_JOB"}
    for rule, words in [("%{INBOUND.Status} = 1", "files at an endpoint have FileCount and Bytes"),
                        ("%{Window.Anything} = 1", "a time has no values to read"),
                        ("%{UP.Extract.Bogus} = 1", "a job has no output 'Bogus'"),
                        ("%{Now.Hour} = 1", "the time has Time, Date, Weekday")]:
        problems, _ = workflow_conditions.check(rule, [], outside=names)
        assert words in problems[0], (rule, problems)


def planned(join="ALL", inside=(), outside_states=(), required=()):
    """A job of a run with the states of its prerequisites given: inside as statuses of other jobs, outside as states."""
    from core.models import WorkflowRunItem as Row
    by_name = {}
    for name, status in inside:
        by_name[name] = Planned(name, name, "ALL", [], Row(Status=status, ReturnCode=0 if status == "SUCCESS" else None))
    items = [outside_state.Outside(id=i + 1, name=f"O{i}", kind="TIME", state=state)
             for i, state in enumerate(outside_states)]
    job = Planned("Job", "JOB", join, [(name, "SUCCESS", None) for name, _ in inside], Row(Status="PENDING"), outside=items)
    return job, by_name


@pytest.mark.parametrize("join, inside, states, answer", [
    ("ALL", [("A", "SUCCESS")], [HOLDS], HOLDS),
    ("ALL", [("A", "RUNNING")], [HOLDS], WAIT),
    ("ALL", [("A", "SUCCESS")], [WAIT], WAIT),
    ("ALL", [("A", "FAILED")], [WAIT], NEVER),
    ("ALL", [("A", "SUCCESS")], [TIMED_OUT], TIMED_OUT),
    ("ALL", [("A", "SUCCESS")], [SKIPPED_OPTIONAL], HOLDS),                 # an optional one that gave up is dropped
    ("ALL", [], [SKIPPED_OPTIONAL], HOLDS),                                 # nothing left: the job starts
    ("ALL", [], [SKIPPED_OPTIONAL, WAIT], WAIT),
    ("ANY", [("A", "FAILED")], [HOLDS], HOLDS),
    ("ANY", [("A", "FAILED")], [TIMED_OUT], TIMED_OUT),
    ("ANY", [("A", "FAILED")], [WAIT], WAIT),
    ("ANY", [("A", "FAILED")], [SKIPPED_OPTIONAL], NEVER),
    ("ANY", [], [SKIPPED_OPTIONAL], HOLDS),
])
def test_a_job_starts_when_its_inside_and_outside_prerequisites_say_so(join, inside, states, answer):
    job, by_name = planned(join, inside, states)
    assert readiness(job, by_name) == answer


def context(seconds=0.0, default_hours=24):
    return outside_state.Context(None, utcnow(), utcnow(), datetime.now(), 1_000_000.0 + seconds, default_hours)


def a_wait(**fields):
    return outside_state.Outside(id=1, name="INBOUND", kind="ENDPOINT", **fields)


def test_up_to_n_minutes_counts_from_when_the_others_have_held_by_default():
    o, ctx = a_wait(wait_mode="MINUTES", wait_minutes=30), context(10_000)
    assert o.patience_ends(ctx, held={}, others=[2, 3], run_start_ts=1_000_000.0) is None          # not started counting
    assert o.patience_ends(ctx, held={2: 1_000_100.0}, others=[2, 3], run_start_ts=1_000_000.0) is None
    assert o.patience_ends(ctx, held={2: 1_000_100.0, 3: 1_000_500.0}, others=[2, 3], run_start_ts=1_000_000.0) == 1_000_500.0 + 1800


def test_the_other_places_a_wait_can_count_from():
    ctx, held, others = context(), {2: 1_000_100.0, 3: 1_000_500.0}, [2, 3]
    for wait_from, chosen, start in [("FIRST", None, 1_000_100.0), ("CHOSEN", 3, 1_000_500.0), ("RUN_START", None, 1_000_000.0)]:
        o = a_wait(wait_mode="MINUTES", wait_minutes=1, wait_from=wait_from, wait_from_id=chosen)
        assert o.patience_ends(ctx, held, others, 1_000_000.0) == start + 60, wait_from


def test_a_job_with_no_other_prerequisite_waits_from_the_start_of_the_run():
    o = a_wait(wait_mode="MINUTES", wait_minutes=5)
    assert o.patience_ends(context(), {}, [], 1_000_000.0) == 1_000_000.0 + 300


def test_the_default_wait_is_the_system_setting_and_no_limit_never_ends():
    assert a_wait().patience_ends(context(default_hours=2), {}, [], 1_000_000.0) == 1_000_000.0 + 7200
    unlimited = a_wait(wait_mode="NONE")
    assert unlimited.patience_ends(context(), {}, [], 1_000_000.0) is None and unlimited.unlimited


def test_until_a_time_is_the_next_time_the_clock_reads_it_after_the_run_started():
    start = datetime(2026, 10, 19, 22, 0).timestamp()
    o = a_wait(wait_mode="UNTIL", wait_until="02:00")
    assert datetime.fromtimestamp(o.patience_ends(context(), {}, [], start)) == datetime(2026, 10, 20, 2, 0)
    early = datetime(2026, 10, 19, 1, 0).timestamp()
    assert datetime.fromtimestamp(o.patience_ends(context(), {}, [], early)) == datetime(2026, 10, 19, 2, 0)


def test_what_does_not_hold_times_out_when_required_and_is_dropped_when_optional():
    for required, state in [(True, TIMED_OUT), (False, SKIPPED_OPTIONAL)]:
        o = a_wait(wait_mode="MINUTES", wait_minutes=1, required=required)
        assert o.judge(context(0), {}, [], 1_000_000.0) == WAIT
        assert o.judge(context(61), {}, [], 1_000_000.0) == state
        assert o.judge(context(62), {}, [], 1_000_000.0) == state                    # and it stays so
    o = a_wait(wait_mode="MINUTES", wait_minutes=1)
    o.holding = True
    assert o.judge(context(61), {}, [], 1_000_000.0) == HOLDS                         # holding on time beats patience


def test_the_limit_is_said_in_words():
    assert a_wait(wait_mode="NONE").limit_words(24) == "with no limit"
    assert a_wait(wait_mode="MINUTES", wait_minutes=30).limit_words(24) == "for up to 30 minutes"
    assert a_wait(wait_mode="MINUTES", wait_minutes=120).limit_words(24) == "for up to 2 hours"
    assert a_wait().limit_words(24) == "for up to 24 hours"
    assert a_wait(wait_mode="UNTIL", wait_until="03:00").limit_words(24) == "until 03:00"


def test_files_count_only_when_every_one_is_old_enough(tmp_path):
    old, young = tmp_path / "a.csv", tmp_path / "b.csv"
    old.write_text("x" * 10)
    young.write_text("y" * 5)
    os.utime(old, (time.time() - 600, time.time() - 600))
    pattern = str(tmp_path / "*.csv")
    seen = outside.look_at_files(pattern, 60)
    assert (seen.count, seen.size, seen.holds(), [os.path.basename(p) for p in seen.waiting_for]) == (2, 15, False, ["b.csv"])
    assert outside.look_at_files(pattern, 60, time.time() + 120).holds()
    assert outside.look_at_files(pattern, None).holds()
    assert not outside.look_at_files(str(tmp_path / "*.txt"), None).holds()          # no file at all is not a hold


# ---------- Which run of another workflow counts ----------

def an_ended_run(db, workflow, item, status, hours_ago=0.0, run_status="SUCCESS", running=False):
    started = utcnow() - timedelta(hours=hours_ago + 0.1)
    run = JobRun(RunID=f"run-{workflow.JobKey}-{db.query(JobRun).count()}", JobKey=workflow.JobKey,
                 Job_MasterObject_id=workflow.MasterObject_id, SchedulerInstanceID="I", JobType="WORKFLOW",
                 Status="RUNNING" if running else run_status, StartedDateTime=started,
                 EndedDateTime=None if running else utcnow() - timedelta(hours=hours_ago))
    db.add(run)
    db.flush()
    db.add(WorkflowRunItem(WorkflowRun_id=run.id, Item_id=item.id, Path=item.ItemName, ItemName=item.ItemName,
                           JobKey=item.job.JobKey, Status=status, ReturnCode=0 if status == "SUCCESS" else 1,
                           StartedDateTime=started, EndedDateTime=None if status in ("PENDING", "RUNNING") else run.EndedDateTime))
    db.commit()
    return run


@pytest.fixture
def upstream(seed, db, sim, flow):                                                         # noqa: F811
    workflow = flow("UP", [("Extract", sim("EXT"))])
    return workflow, workflow.items[0]


def test_the_run_executing_now_counts_before_a_completed_one(db, upstream):
    workflow, item = upstream
    an_ended_run(db, workflow, item, "SUCCESS", hours_ago=1)
    running = an_ended_run(db, workflow, item, "RUNNING", running=True)
    found = outside.find_job(db, item.id, None, None, utcnow())
    assert (found.run_id, found.status, found.run_running) == (running.RunID, "RUNNING", True)


def test_with_no_run_going_the_most_recent_completed_one_counts(db, upstream):
    workflow, item = upstream
    an_ended_run(db, workflow, item, "SUCCESS", hours_ago=5)
    latest = an_ended_run(db, workflow, item, "FAILED", hours_ago=1)
    found = outside.find_job(db, item.id, None, None, utcnow())
    assert (found.run_id, found.status) == (latest.RunID, "FAILED")
    assert outside.find_job(db, item.id + 999, None, None, utcnow()) is None


def test_a_run_that_ended_too_long_ago_does_not_count_when_a_limit_says_so(db, upstream):
    workflow, item = upstream
    an_ended_run(db, workflow, item, "SUCCESS", hours_ago=30)
    assert outside.find_job(db, item.id, None, None, utcnow()).status == "SUCCESS"
    assert outside.find_job(db, item.id, 24, None, utcnow()) is None
    recent = an_ended_run(db, workflow, item, "SUCCESS", hours_ago=2)
    assert outside.find_job(db, item.id, 24, None, utcnow()).run_id == recent.RunID


def test_only_a_run_started_after_this_one_counts_when_a_limit_says_so(db, upstream):
    workflow, item = upstream
    an_ended_run(db, workflow, item, "SUCCESS", hours_ago=3)
    mine = utcnow() - timedelta(hours=1)
    assert outside.find_job(db, item.id, None, mine, utcnow()) is None
    later = an_ended_run(db, workflow, item, "SUCCESS", hours_ago=0.2)
    assert outside.find_job(db, item.id, None, mine, utcnow()).run_id == later.RunID


def test_a_whole_workflow_counts_by_its_final_status(db, upstream):
    workflow, item = upstream
    an_ended_run(db, workflow, item, "SUCCESS", hours_ago=2, run_status="FAILED")
    found = outside.find_workflow(db, workflow.MasterObject_id, None, None, utcnow())
    assert found.status == "FAILED"


# ---------- Running with them ----------

def _utc_mtime(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(tzinfo=None)


def wait_for(seed, workflow, name, **columns):
    item = next(i for i in workflow.items if i.ItemName == name)
    seed._add(WorkflowPrerequisite(Item_id=item.id, **columns))
    return item


def checks(db, run):
    db.expire_all()
    return {c.TargetName: c for c in db.query(WorkflowPrerequisiteCheck).filter(WorkflowPrerequisiteCheck.WorkflowRun_id == run.id)}


def test_a_job_waits_for_a_time_window_that_is_open(sim, flow, run_flow, seed):
    workflow = flow("TIMED", [("Report", sim("R"))])
    wait_for(seed, workflow, "Report", Kind="TIME", TargetName="Window", TimeCondition=ALWAYS)
    code, run, items, log = run_flow("TIMED")
    assert code == 0, log
    assert items["Report"].Status == "SUCCESS"
    assert checks(seed.db, run)["Window"].Result == "HOLDS"


def test_a_job_that_gives_up_waiting_does_not_run_and_says_why(sim, flow, run_flow, seed):
    workflow = flow("SHUT", [("Report", sim("R")), ("Tidy", sim("T"), [("Report", "ENDED")])])
    wait_for(seed, workflow, "Report", Kind="TIME", TargetName="Window", TimeCondition=NEVER_OPEN,
             WaitMode="MINUTES", WaitMinutes=0)
    code, run, items, log = run_flow("SHUT")
    assert states(items)["Report"] == ("NOT_RUN", "TIMED_OUT", None)
    assert states(items)["Tidy"][0] == "SUCCESS"                                   # it waits for Report to end, and it did
    assert "'Report' will not run: it waited for 'Window' until " in log
    assert "and %{Now.Date} < '2000-01-01' is false at " in log
    assert checks(seed.db, run)["Window"].Result == "TIMED_OUT"


def test_a_job_can_fail_instead_when_it_cannot_start(sim, flow, run_flow, seed):
    workflow = flow("FAILS", [("Report", sim("R"))])
    item = wait_for(seed, workflow, "Report", Kind="TIME", TargetName="Window", TimeCondition=NEVER_OPEN,
                    WaitMode="MINUTES", WaitMinutes=0)
    item.OnUnmet = "FAIL"
    code, run, items, log = run_flow("FAILS")
    assert code == 1
    assert states(items)["Report"] == ("FAILED", "TIMED_OUT", None)
    assert run.Status == "FAILED"


def test_an_optional_prerequisite_is_dropped_after_its_limit_and_the_job_goes_on(sim, flow, run_flow, seed):
    workflow = flow("OPTIONAL", [("Prep", sim("P")), ("Report", sim("R"), ["Prep"])])
    wait_for(seed, workflow, "Report", Kind="TIME", TargetName="Window", TimeCondition=NEVER_OPEN,
             WaitMode="MINUTES", WaitMinutes=0, Required=False)
    code, run, items, log = run_flow("OPTIONAL")
    assert code == 0, log
    assert items["Report"].Status == "SUCCESS"
    assert checks(seed.db, run)["Window"].Result == "SKIPPED"
    assert "went on without it" in log


def test_a_job_waits_for_files_to_be_old_enough(sim, flow, run_flow, seed, tmp_path):
    inbound = tmp_path / "inbound"
    inbound.mkdir()
    (inbound / "orders.csv").write_text("a,b\n")
    endpoint = seed.endpoint("INBOUND", inbound, "*.csv")
    workflow = flow("FILES", [("Load", sim("L"))])
    wait_for(seed, workflow, "Load", Kind="ENDPOINT", TargetName="INBOUND", Endpoint_MasterObject_id=endpoint.MasterObject_id,
             MinAgeSeconds=2, WaitMode="NONE")
    code, run, items, log = run_flow("FILES")
    assert code == 0, log
    started = items["Load"].child_run.StartedDateTime
    written = _utc_mtime(inbound / "orders.csv")
    assert (started - written).total_seconds() >= 2
    assert "'Load' waits for 'INBOUND', with no limit." in log
    assert checks(seed.db, run)["INBOUND"].Result == "HOLDS"


def test_a_job_waits_until_the_files_arrive(sim, flow, run_flow, seed, tmp_path):
    inbound = tmp_path / "inbound"
    inbound.mkdir()
    endpoint = seed.endpoint("INBOUND", inbound, "*.csv")
    workflow = flow("ARRIVE", [("Load", sim("L"))])
    wait_for(seed, workflow, "Load", Kind="ENDPOINT", TargetName="INBOUND", Endpoint_MasterObject_id=endpoint.MasterObject_id,
             WaitMode="NONE")
    threading.Timer(2.0, lambda: (inbound / "late.csv").write_text("x")).start()
    code, run, items, log = run_flow("ARRIVE")
    assert code == 0, log
    assert items["Load"].child_run.StartedDateTime >= _utc_mtime(inbound / "late.csv") - timedelta(seconds=1)


def test_a_custom_rule_reads_the_files_it_waited_for(sim, flow, run_flow, seed, tmp_path):
    inbound = tmp_path / "inbound"
    inbound.mkdir()
    for name in ("a.csv", "b.csv"):
        (inbound / name).write_text("x")
    endpoint = seed.endpoint("INBOUND", inbound, "*.csv")
    workflow = flow("RULE", [("Load", sim("L"))])
    item = wait_for(seed, workflow, "Load", Kind="ENDPOINT", TargetName="INBOUND",
                    Endpoint_MasterObject_id=endpoint.MasterObject_id, WaitMode="MINUTES", WaitMinutes=0)
    item.JoinRule, item.StartRule = "CUSTOM", "%{INBOUND.FileCount} >= 2"
    code, run, items, log = run_flow("RULE")
    assert items["Load"].Status == "SUCCESS", log


def test_a_job_starts_once_another_workflows_job_has_succeeded(sim, flow, run_flow, seed):
    up = flow("UP", [("Extract", sim("EXT"))])
    down = flow("DOWN", [("Load", sim("LOAD"))])
    extract = up.items[0]
    wait_for(seed, down, "Load", Kind="OTHER_JOB", TargetName="UP.Extract", TargetItem_id=extract.id, WaitMode="MINUTES",
             WaitMinutes=0)
    _, up_run, _, _ = run_flow("UP")
    code, run, items, log = run_flow("DOWN")
    assert code == 0, log
    assert items["Load"].Status == "SUCCESS"
    check = checks(seed.db, run)["UP.Extract"]
    assert (check.Result, check.UsedRunID) == ("HOLDS", up_run.RunID)


def test_a_job_does_not_start_on_another_workflows_failure_it_waits_for_its_limit(sim, flow, run_flow, seed):
    up = flow("UPF", [("Extract", sim("EXTF", fail=True))])
    down = flow("DOWNF", [("Load", sim("LOADF"))])
    wait_for(seed, down, "Load", Kind="OTHER_JOB", TargetName="UPF.Extract", TargetItem_id=up.items[0].id, WaitMode="MINUTES",
             WaitMinutes=0)
    run_flow("UPF")
    code, run, items, log = run_flow("DOWNF")
    assert states(items)["Load"] == ("NOT_RUN", "TIMED_OUT", None)
    assert "'UPF.Extract' failed" in log


def test_a_job_can_wait_for_a_whole_workflow(sim, flow, run_flow, seed):
    up = flow("UPW", [("Extract", sim("EXTW"))])
    down = flow("DOWNW", [("Load", sim("LOADW"))])
    wait_for(seed, down, "Load", Kind="OTHER_JOB", TargetName="UPW", TargetJob_MasterObject_id=up.MasterObject_id,
             WaitMode="MINUTES", WaitMinutes=0)
    run_flow("UPW")
    code, run, items, log = run_flow("DOWNW")
    assert code == 0 and items["Load"].Status == "SUCCESS", log


# ---------- Seeing what was waited for ----------

def test_a_run_says_what_each_outside_prerequisite_found(sim, flow, run_flow, seed, client):
    up = flow("UPA", [("Extract", sim("EXTA"))])
    down = flow("DOWNA", [("Load", sim("LOADA"))])
    wait_for(seed, down, "Load", Kind="OTHER_JOB", TargetName="UPA.Extract", TargetItem_id=up.items[0].id,
             WaitMode="MINUTES", WaitMinutes=0)
    _, up_run, _, _ = run_flow("UPA")
    _, run, _, _ = run_flow("DOWNA")
    (found,) = client.get(f"/api/v1/runs/{run.RunID}").json()["outside_waits"]
    assert (found["path"], found["kind"], found["target"], found["result"], found["used_run_id"], found["attempt"]) == (
        "Load", "OTHER_JOB", "UPA.Extract", "HOLDS", up_run.RunID, 1)
    assert "'UPA.Extract' succeeded" in found["message"]


def test_a_run_still_waiting_says_what_for_and_until_when(sim, flow, seed, db, db_url, tmp_path, client):
    inbound = tmp_path / "inbound"
    inbound.mkdir()
    endpoint = seed.endpoint("INBOUND", inbound, "*.csv")
    workflow = flow("WAITING", [("Load", sim("LW"))])
    wait_for(seed, workflow, "Load", Kind="ENDPOINT", TargetName="INBOUND",
             Endpoint_MasterObject_id=endpoint.MasterObject_id, WaitMode="MINUTES", WaitMinutes=60)
    db.commit()
    process = start(db_url, tmp_path, "WAITING")
    try:
        said = None
        for _ in range(100):
            time.sleep(0.2)
            db.expire_all()
            run = db.query(JobRun).filter(JobRun.JobKey == "WAITING").first()
            if run is not None:
                items = client.get(f"/api/v1/runs/{run.RunID}").json()["items"]
                said = items and items[0]["waiting_for"]
                if said:
                    break
        assert said and "Waiting for 'INBOUND', until " in said and "No files match" in said, said
        (inbound / "now.csv").write_text("x")
        process.communicate(timeout=60)
    finally:
        process.kill()
    assert process.returncode == 0

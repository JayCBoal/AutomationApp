"""
Time-based Reactions in a workflow (docs/WORKFLOWS_PHASE8.md, step 3). The workflow runner runs with
a clock that goes 600 times faster than real time, so "30 minutes" passes in three seconds. The clock rules
themselves are tested in test_clock_rules.py.
"""
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from core.models import JobRun, Reaction, ReactionAction, ReactionEvent, utcnow
from conftest import AUTOAPP_DIR, subprocess_env
from test_workflow_reopen import fix
from test_workflow_runner import flow, results, sim  # noqa: F401 (fixtures)

SPEED = 600


@pytest.fixture
def run_clocked(db, db_url, tmp_path):
    """Runs a workflow to the end with the fast clock (tests/fast_runner.py). Returns (exit code, its run, items, log)."""
    def _run(key, *extra, hours_later=0):
        db.commit()
        env = {**subprocess_env(db_url), "AUTOAPP_WORKFLOW_POLL_SECONDS": "0.1", "AUTOAPP_TEST_CLOCK_SPEED": str(SPEED),
               "AUTOAPP_TEST_CLOCK_SHIFT_MINUTES": str(hours_later * 60)}
        done = subprocess.run([sys.executable, str(Path(__file__).with_name("fast_runner.py")), "--job-key", key,
                               "--instance-id", "CLOCK_1", "--spool-dir", str(tmp_path / "spool"),
                               "--working-root", str(tmp_path / "work"), *extra],
                              cwd=AUTOAPP_DIR, env=env, capture_output=True, text=True, timeout=120)
        assert done.returncode in (0, 1), done.stdout + done.stderr
        db.expire_all()
        return (done.returncode, *results(db, key))
    return _run


def timed(db, owner, test, kind, *actions, minutes=None, percent=None, runs=None, clock=None, order=1):
    """A time Reaction on a job (an ALSO entry); actions: ("MARK_AS_LATE", {})."""
    reaction = Reaction(Job_MasterObject_id=owner.MasterObject_id, Section="ALSO", ReactionOrder=order, WhenTest=test,
                        WhenTimeKind=kind, WhenMinutes=minutes, WhenPercent=percent, WhenRunCount=runs, WhenClockTime=clock)
    for position, (action, settings) in enumerate(actions, start=1):
        reaction.actions.append(ReactionAction(ActionOrder=position, Action=action, **settings))
    db.add(reaction)
    db.commit()
    return reaction


def events(db):
    return [(e.Action, e.Result) for e in db.query(ReactionEvent).order_by(ReactionEvent.id)]


def test_a_job_that_runs_longer_than_its_limit_is_marked_late_and_still_succeeds(sim, flow, run_clocked, db):
    slow = sim("SLOW", wait=6)
    timed(db, slow, "RUNS_LONGER_THAN", "LENGTH", ("MARK_AS_LATE", {}), minutes=30)
    flow("LONG", [("Slow", slow)])

    code, run, items, log = run_clocked("LONG")

    assert code == 0, log
    row = items["Slow"]
    assert row.Status == "SUCCESS"
    assert row.LateDateTime is not None and "has run longer than 30m" in row.LateReason
    assert row.child_run.LateDateTime is not None
    assert events(db) == [("MARK_AS_LATE", "TOOK_EFFECT")]
    event = db.query(ReactionEvent).one()       # its run's record had not arrived yet, so it belongs to the item
    assert (event.WorkflowRun_id, event.WorkflowPath) == (run.id, "Slow")


def test_a_job_that_finishes_in_time_is_not_marked(sim, flow, run_clocked, db):
    quick = sim("QUICK")
    timed(db, quick, "RUNS_LONGER_THAN", "LENGTH", ("MARK_AS_LATE", {}), minutes=6000)
    flow("INTIME", [("Quick", quick)])

    code, run, items, log = run_clocked("INTIME")

    assert code == 0 and items["Quick"].LateDateTime is None
    assert events(db) == []


def test_a_job_not_started_by_its_time_is_late_and_the_flag_names_what_it_waited_for(sim, flow, run_clocked, db):
    slow, after = sim("UPSTREAM", wait=8), sim("AFTER")
    timed(db, slow, "NOT_ENDED_BY", "AFTER_START", ("MARK_AS_LATE", {}), minutes=20)
    timed(db, after, "NOT_STARTED_BY", "AFTER_START", ("MARK_AS_LATE", {}), minutes=30)
    flow("DELAYED", [("Upstream", slow), ("After", after, ["Upstream"])])

    code, run, items, log = run_clocked("DELAYED")

    assert code == 0, log
    late = items["After"]
    assert "'After' had not started by" in late.LateReason
    assert late.LateCause.startswith("waiting for 'Upstream', which has been running since")
    assert late.Status == "SUCCESS"        # it ran in the end: late is a record, not a status
    assert items["Upstream"].LateDateTime is not None
    notstarted = [e for e in db.query(ReactionEvent) if e.WorkflowPath == "After"]
    assert len(notstarted) == 1 and notstarted[0].JobRun_id is None and notstarted[0].WorkflowRun_id == run.id


def test_longer_than_usual_is_worked_out_from_history_and_written_to_the_log(sim, flow, run_clocked, db):
    slow = sim("USUAL", wait=6)
    for _ in range(3):
        db.add(JobRun(RunID=os.urandom(16).hex()[:32], JobKey="USUAL", Job_MasterObject_id=slow.MasterObject_id,
                      SchedulerInstanceID="H", Status="SUCCESS", StartedDateTime=utcnow() - timedelta(hours=2),
                      EndedDateTime=utcnow() - timedelta(hours=2) + timedelta(minutes=10)))
    timed(db, slow, "RUNS_LONGER_THAN", "HISTORY", ("MARK_AS_LATE", {}), percent=50)
    flow("USUALLY", [("Usual", slow)])

    code, run, items, log = run_clocked("USUALLY")

    assert "limit 15m: 50% over the 10m average of the last 3 runs" in log
    assert items["Usual"].LateDateTime is not None


def test_too_little_history_means_it_is_not_judged_and_the_log_says_so(sim, flow, run_clocked, db):
    slow = sim("FEW", wait=3)
    timed(db, slow, "RUNS_LONGER_THAN", "HISTORY", ("MARK_AS_LATE", {}), percent=50)
    flow("FEWRUNS", [("Few", slow)])

    code, run, items, log = run_clocked("FEWRUNS")

    assert "only 0 earlier runs; 'longer than usual' not judged" in log
    assert items["Few"].LateDateTime is None and events(db) == []


def test_a_workflow_that_has_not_ended_by_its_time_is_marked_late(sim, flow, run_clocked, db):
    workflow = flow("WHOLE", [("Slow", sim("WHOLESLOW", wait=6))])
    timed(db, workflow, "NOT_ENDED_BY", "AFTER_START", ("MARK_AS_LATE", {}), minutes=20)

    code, run, items, log = run_clocked("WHOLE")

    assert code == 0, log
    assert run.LateDateTime is not None and run.LateReason.startswith("The workflow had not ended by")
    assert items["Slow"].LateDateTime is None
    assert db.query(ReactionEvent).one().JobRun_id == run.id


def test_a_reopened_run_does_not_fire_again_nor_judge_a_deadline_that_passed_while_it_was_over(sim, flow, run_clocked, db):
    upstream, after = sim("REOPENUP", wait=6, fail=True), sim("REOPENAFTER")
    timed(db, upstream, "NOT_ENDED_BY", "AFTER_START", ("MARK_AS_LATE", {}), minutes=20)
    timed(db, after, "NOT_STARTED_BY", "AFTER_START", ("MARK_AS_LATE", {}), minutes=90)
    flow("REOPENED", [("Up", upstream), ("After", after, ["Up"])])
    _, first, items, _ = run_clocked("REOPENED")
    assert (items["Up"].Status, items["After"].Status) == ("FAILED", "NOT_RUN")
    fix(db, "REOPENUP")

    code, run, items, log = run_clocked("REOPENED", "--run-id", first.RunID, "--attempt", str(first.Attempt), "--reopen", "resume",
                                        hours_later=4)

    assert (items["Up"].Status, items["After"].Status) == ("SUCCESS", "SUCCESS"), log
    assert db.query(ReactionEvent).filter(ReactionEvent.Action == "MARK_AS_LATE").count() == 1
    assert "'Up': deadline" not in log          # it fired before, so it is not looked at again
    assert "'After': deadline" in log and "passed before the run was reopened; not judged." in log
    assert items["After"].LateDateTime is None

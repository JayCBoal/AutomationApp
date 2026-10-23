"""
Time-based Reactions on a job run on its own (docs/WORKFLOWS_PHASE8.md, step 4). The job runner runs with a clock
600 times faster than real time (tests/fast_runner.py). What the clock does leaves as REACTION records in the spool.
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from app.models import JobRun
from conftest import AUTOAPP_DIR, subprocess_env
from engine.telemetry_client import LocalSpoolTelemetryClient
from test_telemetry_ingest import ROUTE
from test_workflow_clock import SPEED, timed
from test_workflow_runner import sim  # noqa: F401 (fixture)


@pytest.fixture
def run_alone(db, db_url, tmp_path, spool_records):
    """Runs a job on its own with the fast clock. Returns (exit code, the spool's records, seconds it took)."""
    def _run(key):
        db.commit()
        env = {**subprocess_env(db_url), "AUTOAPP_JOB_CLOCK_POLL_SECONDS": "0.1", "AUTOAPP_TEST_CLOCK_SPEED": str(SPEED),
               "AUTOAPP_TEST_CLOCK_SHIFT_MINUTES": "0"}
        began = time.time()
        done = subprocess.run([sys.executable, str(Path(__file__).with_name("fast_runner.py")), "--job-key", key,
                               "--instance-id", "ALONE_1", "--spool-dir", str(tmp_path / "spool"),
                               "--working-root", str(tmp_path / "work")],
                              cwd=AUTOAPP_DIR, env=env, capture_output=True, text=True, timeout=120)
        assert done.returncode in (0, 1), done.stdout + done.stderr
        return done.returncode, spool_records(tmp_path / "spool"), time.time() - began, done.stdout
    return _run


def reactions(records):
    return [r for r in records if r["Record"] == "REACTION"]


def test_a_job_on_its_own_that_runs_longer_than_its_limit_is_marked_late_and_still_succeeds(sim, run_alone, db):
    slow = sim("ALONESLOW", wait=6)
    timed(db, slow, "RUNS_LONGER_THAN", "LENGTH", ("MARK_AS_LATE", {}), minutes=30)

    code, records, _, log = run_alone("ALONESLOW")

    assert code == 0, log
    (fired,) = reactions(records)
    assert fired["Action"] == "MARK_AS_LATE" and fired["Result"] == "TOOK_EFFECT"
    assert fired["LateReason"] == "'ALONESLOW' has run longer than 30m"
    assert [r["Record"] for r in records][-1] == "RUN_END" and records[-1]["Status"] == "SUCCESS"
    assert "has run longer than 30m" in log


def test_a_job_that_ends_in_time_fires_nothing(sim, run_alone, db):
    quick = sim("ALONEQUICK")
    timed(db, quick, "RUNS_LONGER_THAN", "LENGTH", ("MARK_AS_LATE", {}), minutes=6000)
    timed(db, quick, "NOT_ENDED_BY", "AFTER_START", ("MARK_AS_LATE", {}), minutes=6000, order=2)

    code, records, took, log = run_alone("ALONEQUICK")

    assert code == 0 and reactions(records) == []
    assert took < 20, "the clock must not hold the job back when it ends"


def test_not_ended_by_counts_from_the_jobs_own_start_and_fires_once(sim, run_alone, db):
    slow = sim("ALONEEND", wait=6)
    timed(db, slow, "NOT_ENDED_BY", "AFTER_START", ("MARK_AS_LATE", {}), minutes=20)

    code, records, _, log = run_alone("ALONEEND")

    (fired,) = reactions(records)
    assert fired["LateReason"].startswith("'ALONEEND' had not ended by")


def test_a_time_that_does_not_apply_to_a_job_on_its_own_is_not_judged(sim, run_alone, db):
    slow = sim("ALONEREADY", wait=3)
    timed(db, slow, "NOT_ENDED_BY", "AFTER_READY", ("MARK_AS_LATE", {}), minutes=1)

    code, records, _, log = run_alone("ALONEREADY")

    assert code == 0 and reactions(records) == []


def test_the_late_flag_arrives_with_the_spool_and_keeps_the_first_reason(sim, client, db, tmp_path, spool_records):
    job = sim("ALONEFLAG")
    db.commit()
    spool = tmp_path / "flag"
    with LocalSpoolTelemetryClient(spool_dir=str(spool), instance_id="F1") as telemetry:
        telemetry.start_run("ALONEFLAG")
        telemetry.record_reaction("MARK_AS_LATE", "TOOK_EFFECT", "first. Marked as late.", late_reason="first")
        telemetry.record_reaction("MARK_AS_LATE", "TOOK_EFFECT", "second. Marked as late.", late_reason="second")
        telemetry.end_run("SUCCESS")

    assert client.post(ROUTE, json={"records": spool_records(spool)}).status_code == 201

    db.commit()
    run = db.query(JobRun).filter(JobRun.JobKey == "ALONEFLAG").one()
    assert run.LateDateTime is not None and run.LateReason == "first"


def test_two_threads_writing_one_spool_file_keep_every_record_whole(tmp_path):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T1") as telemetry:
        telemetry.start_run("THREADS")

        def write(name):
            for number in range(200):
                telemetry.record_reaction("MARK_AS_LATE", "TOOK_EFFECT", f"{name} {number}")

        threads = [threading.Thread(target=write, args=(name,)) for name in ("a", "b")]
        [t.start() for t in threads]
        [t.join() for t in threads]
        telemetry.end_run("SUCCESS")

    lines = [json.loads(line) for path in tmp_path.glob("*.jsonl") for line in path.read_text().splitlines()]
    assert len(lines) == 402 and sorted(r["Seq"] for r in lines) == list(range(1, 403))

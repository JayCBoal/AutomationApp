"""
Getting telemetry from the runner's machine into AutoApp.

These use a real API server in its own process (the live_api fixture), a real
runner process, and the real delivery command.
"""
import subprocess
import sys

import pytest

from app.models import JobRun, Operation
from conftest import AUTOAPP_DIR, subprocess_env


def names(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


@pytest.fixture
def job(seed, endpoints):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    return job


@pytest.fixture
def deliver(db, db_url, tmp_path):
    """Runs the delivery command as a separate process."""
    def _deliver(*args):
        result = subprocess.run(
            [sys.executable, "-m", "engine.spool_delivery", "--spool-dir", str(tmp_path / "spool"), *args],
            cwd=AUTOAPP_DIR, env=subprocess_env(db_url), capture_output=True, text=True,
        )
        db.commit()
        return result
    return _deliver


def test_runner_delivers_its_telemetry_through_the_api(db, job, run_runner, live_api, tmp_path):
    result = run_runner(job.JobKey, "88421", "--api-url", live_api)

    assert result.returncode == 0, result.stderr
    db.commit()
    run = db.query(JobRun).one()
    assert (run.JobKey, run.SchedulerInstanceID, run.Status) == ("DEV-LOAD", "88421", "SUCCESS")
    assert [(op.StepOrder, op.OpType, op.SourceFilename) for op in run.operations] == [
        (1, "COPY", "Legal_Batch_1.csv"), (1, "COPY", "Legal_Batch_2.csv"),
        (2, "MOVE", "Legal_Batch_1.csv"), (2, "MOVE", "Legal_Batch_2.csv"),
    ]
    # the spool file is kept, but set aside so it is not sent again
    spool = tmp_path / "spool"
    assert [n for n in names(spool) if n != "delivered"] == []
    assert len(names(spool / "delivered")) == 1


def test_runner_posts_after_each_step_and_sends_each_record_once(db, job, tmp_path, monkeypatch):
    """
    So a run can be watched while it is going. The runner is called in-process here,
    with the network call replaced by one that notes what would have been sent.
    """
    from engine.runner import run_job
    posts = []
    monkeypatch.setattr("engine.telemetry_client.post_records",
                        lambda api_url, records, timeout=None: posts.append(
                            [r["Record"] for r in records if r["Record"] != "LOG"]))
    db.commit()

    exit_code = run_job(db, "DEV-LOAD", "88421", str(tmp_path / "spool"),
                        working_root=str(tmp_path / "work"), api_url="http://autoapp.example")

    assert exit_code == 0
    assert posts == [
        ["RUN_START"],                              # as it starts, so the run shows as running at once
        ["OPERATION", "OPERATION"],                 # after step 1
        ["OPERATION", "OPERATION"],                 # after step 2
        ["RUN_END"],                                # when the run ends
    ]


def test_job_still_succeeds_when_the_api_is_unreachable(db, job, run_runner, unused_api_url, tmp_path):
    result = run_runner(job.JobKey, "88421", "--api-url", unused_api_url)

    assert result.returncode == 0, result.stderr
    assert names(tmp_path / "app_inbox") == ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]
    db.commit()
    assert db.query(JobRun).count() == 0
    [spool_file] = names(tmp_path / "spool")           # waiting for the delivery command
    assert spool_file.endswith(".jsonl")


def test_delivery_command_sends_what_was_left_behind(db, job, run_runner, unused_api_url, live_api, deliver, tmp_path):
    run_runner(job.JobKey, "88421", "--api-url", unused_api_url)

    result = deliver("--api-url", live_api)

    assert result.returncode == 0, result.stderr
    assert "Delivered 1 spool file(s)." in result.stdout
    assert db.query(JobRun).one().Status == "SUCCESS"
    assert db.query(Operation).count() == 4
    assert names(tmp_path / "spool") == ["delivered"]


def test_delivery_command_without_an_api_address_loads_the_database_directly(db, job, run_runner, deliver, tmp_path):
    run_runner(job.JobKey, "88421")

    result = deliver()

    assert result.returncode == 0, result.stderr
    assert db.query(JobRun).one().Status == "SUCCESS"
    assert db.query(Operation).count() == 4
    assert names(tmp_path / "spool") == ["delivered"]


def test_running_the_delivery_command_again_sends_nothing(db, job, run_runner, deliver):
    run_runner(job.JobKey, "88421")
    deliver()

    result = deliver()

    assert result.returncode == 0
    assert "Delivered 0 spool file(s)." in result.stdout
    assert db.query(Operation).count() == 4


def test_delivery_command_reports_failure_and_keeps_the_files_when_the_api_is_unreachable(
        db, job, run_runner, deliver, unused_api_url, tmp_path):
    run_runner(job.JobKey, "88421")

    result = deliver("--api-url", unused_api_url)

    assert result.returncode == 1
    assert "NOT delivered" in result.stderr
    assert len(names(tmp_path / "spool")) == 1
    assert db.query(JobRun).count() == 0


def test_a_bad_spool_file_is_reported_and_does_not_block_the_others(db, job, run_runner, deliver, tmp_path):
    run_runner(job.JobKey, "88421")
    (tmp_path / "spool" / "run_bad.jsonl").write_text('{"Record": "OPERATION", "RunID": "x", "Seq": 1}\n')

    result = deliver()

    assert result.returncode == 1
    assert "run_bad.jsonl" in result.stderr
    assert db.query(JobRun).one().Status == "SUCCESS"            # the good file was loaded
    assert [n for n in names(tmp_path / "spool") if n != "delivered"] == ["run_bad.jsonl"]


def test_a_spool_file_still_being_written_is_left_alone(db, deliver, tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "run_in_progress.jsonl.tmp").write_text('{"Record": "RUN_START"}\n')

    result = deliver()

    assert result.returncode == 0
    assert names(spool) == ["run_in_progress.jsonl.tmp"]

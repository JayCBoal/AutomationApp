"""
Runner: launched as a separate process, the way a scheduler would launch it,
against a throwaway database. Checks the exit code, the files and the spool.

Layout used by these tests, all inside pytest's temp folder:
    app_outbox/              an application's folder, registered as Endpoint LEGAL_EXTRACTS
    app_inbox/               another application's folder, registered as Endpoint BILLING_INBOX
    work/<JobKey>/           the job's working folder
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

AUTOAPP_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def run_runner(db, db_url, tmp_path):
    def _run(job_key, instance_id="RUN_001"):
        db.commit()
        return subprocess.run(
            [sys.executable, "-m", "engine.runner",
             "--job-key", job_key,
             "--instance-id", instance_id,
             "--spool-dir", str(tmp_path / "spool"),
             "--working-root", str(tmp_path / "work")],
            cwd=AUTOAPP_DIR,
            env={**os.environ, "DATABASE_URL": db_url},
            capture_output=True, text=True,
        )
    return _run


@pytest.fixture
def outbox(tmp_path):
    folder = tmp_path / "app_outbox"
    folder.mkdir()
    (folder / "Legal_Batch_1.csv").write_text("id\n1")
    (folder / "Legal_Batch_2.csv").write_text("id\n2")
    (folder / "other.txt").write_text("not part of the feed")
    return folder


@pytest.fixture
def endpoints(seed, outbox, tmp_path):
    source = seed.endpoint("LEGAL_EXTRACTS", outbox, "Legal_Batch_*.csv", application=seed.application("LEGAL_APP"))
    dest = seed.endpoint("BILLING_INBOX", tmp_path / "app_inbox", "*.csv", application=seed.application("BILLING_APP"))
    return source, dest


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def test_job_moves_files_from_one_endpoint_to_another_through_the_working_folder(
        seed, run_runner, endpoints, outbox, tmp_path, spool_records):
    source, dest = endpoints
    job = seed.job("DEV-LOAD")
    # Seeded out of order on purpose: steps must run by StepOrder.
    seed.step(job, 3, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Archive", Source="incoming/*.csv", Dest="archive/${SYS:INSTANCE_ID}")

    result = run_runner(job.JobKey, instance_id="RUN_001")

    work = tmp_path / "work" / "DEV-LOAD"
    batch = ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]
    assert result.returncode == 0, result.stderr
    assert names(outbox) == batch + ["other.txt"]            # collected by copy; source untouched
    assert names(work / "archive" / "RUN_001") == batch
    assert names(work / "incoming") == []                    # moved on by the last step
    assert names(tmp_path / "app_inbox") == batch

    records = spool_records(tmp_path / "spool")
    assert [r["Action"] for r in records if r.get("IsAudit")] == ["JOB_STARTED", "JOB_COMPLETED"]
    operations = [r for r in records if not r.get("IsAudit")]
    assert [r["Status"] for r in operations] == ["SUCCESS", "SUCCESS", "SUCCESS"]
    assert [(r["SourceEndpointID"], r["DestEndpointID"]) for r in operations] == [
        (source.id, None),      # Collect: from a registered endpoint into the working folder
        (None, None),           # Archive: a hop inside the working folder
        (None, dest.id),        # Deliver: out of the working folder to a registered endpoint
    ]


def test_raw_path_outside_the_working_folder_fails_the_job(seed, run_runner, outbox, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, Source=str(outbox / "*.csv"), Dest="incoming")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert "outside the job's working folder" in result.stderr
    assert "SourceEndpoint" in result.stderr
    assert not (tmp_path / "work" / "DEV-LOAD" / "incoming").exists()
    assert spool_records(tmp_path / "spool")[-1]["Action"] == "JOB_FAILED"


def test_unresolved_placeholder_fails_the_job_before_touching_files(seed, run_runner, endpoints, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="${NoSuchFolder}/out")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert "${NoSuchFolder}" in result.stderr
    assert names(tmp_path / "work" / "DEV-LOAD") == []
    assert spool_records(tmp_path / "spool")[-1]["Action"] == "JOB_FAILED"


def test_failing_step_stops_the_job(seed, run_runner, endpoints, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="missing", CreateFolder="False")
    seed.step(job, 2, SourceEndpoint="LEGAL_EXTRACTS", DestEndpoint="BILLING_INBOX")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert not (tmp_path / "app_inbox").exists()
    assert spool_records(tmp_path / "spool")[-1]["Action"] == "JOB_FAILED"


def test_unknown_step_type_fails_the_job(seed, run_runner):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, code="SQL_EXEC", Query="SELECT 1")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert "SQL_EXEC" in result.stderr


def test_only_the_job_whose_key_is_passed_runs(seed, run_runner, endpoints, tmp_path):
    for key in ("DEV-LOAD-A", "DEV-LOAD-B"):
        seed.step(seed.job(key), 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")

    result = run_runner("DEV-LOAD-B")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "work" / "DEV-LOAD-B" / "incoming").exists()
    assert not (tmp_path / "work" / "DEV-LOAD-A").exists()


def test_unknown_job_fails(seed, run_runner):
    seed.job("DEV-LOAD")

    result = run_runner("NO_SUCH_JOB")

    assert result.returncode == 1
    assert "NO_SUCH_JOB" in result.stderr


def test_job_with_no_steps_fails(seed, run_runner):
    job = seed.job("DEV-LOAD")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert "no active steps" in result.stderr

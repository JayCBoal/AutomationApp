"""
Runner: launched as a separate process, the way a scheduler would launch it,
against a throwaway database. Checks the exit code, the files and the spool.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

AUTOAPP_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def run_runner(db, db_url, tmp_path):
    def _run(job_id, instance_id="RUN_001"):
        db.commit()
        return subprocess.run(
            [sys.executable, "-m", "engine.runner",
             "--job-id", str(job_id),
             "--instance-id", instance_id,
             "--spool-dir", str(tmp_path / "spool")],
            cwd=AUTOAPP_DIR,
            env={**os.environ, "DATABASE_URL": db_url},
            capture_output=True, text=True,
        )
    return _run


@pytest.fixture
def inbound(tmp_path):
    folder = tmp_path / "inbound"
    folder.mkdir()
    (folder / "Legal_Batch_1.csv").write_text("id\n1")
    (folder / "Legal_Batch_2.csv").write_text("id\n2")
    return folder


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def test_job_runs_its_steps_in_order(seed, run_runner, inbound, tmp_path, spool_records):
    archive, outbound = tmp_path / "archive", tmp_path / "outbound"
    proc = seed.process(Inbound=str(inbound), Archive=str(archive), Outbound=str(outbound))
    job = seed.job(proc, Pattern="Legal_Batch_*.csv")
    # Seeded out of order on purpose: the move must still run after the copy.
    seed.step(job, 2, title="Deliver", Source="${Inbound}/${Pattern}", Dest="${Outbound}", Move="True")
    seed.step(job, 1, title="Archive", Source="${Inbound}/${Pattern}", Dest="${Archive}/${SYS:INSTANCE_ID}")

    result = run_runner(job.MasterObject_id, instance_id="RUN_001")

    assert result.returncode == 0, result.stderr
    assert names(archive / "RUN_001") == ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]
    assert names(outbound) == ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]
    assert names(inbound) == []

    records = spool_records(tmp_path / "spool")
    assert [r["Action"] for r in records if r.get("IsAudit")] == ["JOB_STARTED", "JOB_COMPLETED"]
    assert [r["Status"] for r in records if not r.get("IsAudit")] == ["SUCCESS", "SUCCESS"]


def test_unresolved_placeholder_fails_the_job_before_touching_files(seed, run_runner, inbound, tmp_path, spool_records):
    proc = seed.process(Inbound=str(inbound))
    job = seed.job(proc)
    seed.step(job, 1, Source="${Inbound}/*.csv", Dest="${NoSuchFolder}/out")

    result = run_runner(job.MasterObject_id)

    assert result.returncode == 1
    assert "${NoSuchFolder}" in result.stderr
    assert names(inbound) == ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]
    assert names(tmp_path) == ["autoapp_test.db", "inbound", "spool"]
    assert spool_records(tmp_path / "spool")[-1]["Action"] == "JOB_FAILED"


def test_failing_step_stops_the_job(seed, run_runner, inbound, tmp_path, spool_records):
    proc = seed.process(Inbound=str(inbound), Outbound=str(tmp_path / "outbound"))
    job = seed.job(proc)
    seed.step(job, 1, Source="${Inbound}/*.csv", Dest=str(tmp_path / "missing"), CreateFolder="False")
    seed.step(job, 2, Source="${Inbound}/*.csv", Dest="${Outbound}")

    result = run_runner(job.MasterObject_id)

    assert result.returncode == 1
    assert not (tmp_path / "outbound").exists()
    assert spool_records(tmp_path / "spool")[-1]["Action"] == "JOB_FAILED"


def test_unknown_step_type_fails_the_job(seed, run_runner, inbound, tmp_path):
    job = seed.job(seed.process())
    seed.step(job, 1, code="SQL_EXEC", Query="SELECT 1")

    result = run_runner(job.MasterObject_id)

    assert result.returncode == 1
    assert "SQL_EXEC" in result.stderr


def test_unknown_job_fails(seed, run_runner):
    seed.job(seed.process())

    result = run_runner(9999)

    assert result.returncode == 1
    assert "9999" in result.stderr


def test_job_with_no_steps_fails(seed, run_runner):
    job = seed.job(seed.process())

    result = run_runner(job.MasterObject_id)

    assert result.returncode == 1
    assert "no active steps" in result.stderr

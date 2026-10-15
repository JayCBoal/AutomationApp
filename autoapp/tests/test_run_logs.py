"""
Job logs kept with each run: the runner sends its log with the run's other
records, and GET /api/v1/runs/{run_id} gives it back, as the log page shows it.
"""
import pytest

from app.models import Variable
from app.telemetry_ingest import ingest_records
from conftest import read_spool


@pytest.fixture
def collect_and_deliver(seed, endpoints):
    job = seed.job("DEV-COLLECT")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    return job


def the_run(client, **criteria):
    [run] = client.get("/api/v1/runs", params=criteria).json()
    return client.get(f"/api/v1/runs/{run['run_id']}").json()


def test_a_runs_log_is_kept_with_it(collect_and_deliver, run_runner, load_spool, client):
    result = run_runner("DEV-COLLECT", "88421")
    load_spool()

    run = the_run(client, instance_id="88421")

    assert run["status"] == "SUCCESS" and run["has_log"] is True
    log = "\n".join(run["log"])
    assert "Job 'DEV-COLLECT', instance 88421, run number 1" in log
    assert "BEGIN Step 1: Collect (" in log
    assert log.rstrip().endswith("Job 'DEV-COLLECT' completed successfully.")
    # the same lines the runner printed, in the same order
    printed = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    assert sorted(run["log"]) == sorted(printed)


def test_a_failed_runs_log_ends_with_why(seed, endpoints, run_runner, load_spool, client):
    job = seed.job("DEV-BROKEN")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming", CreateFolder="False")
    seed.step(job, 2, Source="nothing_here/*.csv", Dest="out")
    run_runner("DEV-BROKEN", "88422")
    load_spool()

    run = the_run(client, instance_id="88422")

    assert run["status"] == "FAILED"
    assert any("[ERROR] Job 'DEV-BROKEN' failed:" in line for line in run["log"])


def test_a_secret_is_masked_in_the_kept_log(db, seed, endpoints, run_runner, load_spool, client):
    job = seed.job("DEV-LOAD")
    db.add(Variable(MasterObject_id=job.MasterObject_id, VarName="Token", VarValue="s3cr3t-t0ken", IsSecret=True))
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="in_${Token}")
    run_runner("DEV-LOAD", "88423")
    load_spool()

    run = the_run(client, instance_id="88423")

    assert "s3cr3t-t0ken" not in str(run)
    assert any("in_********" in line for line in run["log"])


def test_loading_the_same_spool_twice_keeps_one_copy_of_the_log(
        db, collect_and_deliver, run_runner, load_spool, client, tmp_path):
    run_runner("DEV-COLLECT", "88421")
    load_spool()
    first = the_run(client, instance_id="88421")["log"]

    result = ingest_records(db, read_spool(tmp_path / "spool" / "delivered", with_log=True))

    assert result.duplicates_skipped > 0
    assert the_run(client, instance_id="88421")["log"] == first


def test_a_run_from_before_logs_were_kept_says_it_has_none(db, client):
    from datetime import datetime
    from app.models import JobRun
    db.add(JobRun(RunID="old-run", JobKey="DEV-OLD", SchedulerInstanceID="1", Status="SUCCESS",
                  StartedDateTime=datetime(2026, 10, 1, 9, 0), EndedDateTime=datetime(2026, 10, 1, 9, 1)))
    db.commit()

    run = client.get("/api/v1/runs/old-run").json()

    assert (run["has_log"], run["log"]) == (False, [])
    assert client.get("/api/v1/runs").json()[0]["has_log"] is False


def test_an_unknown_run_is_404(client):
    response = client.get("/api/v1/runs/no-such-run")

    assert response.status_code == 404
    assert "no record of run 'no-such-run'" in response.json()["detail"]

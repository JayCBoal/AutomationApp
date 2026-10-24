"""
Job logs kept with each run: the runner writes its log to a file on its host
(<log root>/<host>/<date>/<RunID>.log), the run's record says where, and
GET /api/v1/runs/{run_id} reads it from there, as the log page shows it.
Old logs are removed after the Settings page's "Keep job logs for".
"""
import socket
from datetime import datetime, timedelta

import pytest

from app.log_agent import remove_old_logs
from core.models import JobRun, SettingValue, Variable, utcnow
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

    result = ingest_records(db, read_spool(tmp_path / "spool" / "delivered"))

    assert result.duplicates_skipped > 0
    assert the_run(client, instance_id="88421")["log"] == first


def test_a_run_from_before_logs_were_kept_says_it_has_none(db, client):
    from datetime import datetime
    from core.models import JobRun
    db.add(JobRun(RunID="old-run", JobKey="DEV-OLD", SchedulerInstanceID="1", Status="SUCCESS",
                  StartedDateTime=datetime(2026, 10, 1, 9, 0), EndedDateTime=datetime(2026, 10, 1, 9, 1)))
    db.commit()

    run = client.get("/api/v1/runs/old-run").json()

    assert (run["has_log"], run["log"]) == (False, [])
    assert client.get("/api/v1/runs").json()[0]["has_log"] is False


def test_the_log_is_a_file_on_the_host_that_ran_the_job(collect_and_deliver, run_runner, load_spool, db, log_root):
    run_runner("DEV-COLLECT", "88421")
    load_spool()
    run = db.query(JobRun).one()
    day = run.StartedDateTime.strftime("%Y-%m-%d")
    assert (run.Host, run.LogFile) == (socket.gethostname(), f"{day}/{run.RunID}.log")
    path = log_root / run.Host / run.LogFile
    assert "Job 'DEV-COLLECT' completed successfully." in path.read_text()


def old_run(db, log_root, run_id="old", days_ago=40, host="agent-1"):
    """A run that ended days_ago, with its log file on its host."""
    ended = utcnow() - timedelta(days=days_ago)
    log_file = f"{ended:%Y-%m-%d}/{run_id}.log"
    (log_root / host / log_file).parent.mkdir(parents=True, exist_ok=True)
    (log_root / host / log_file).write_text("line 1\nline 2\n")
    db.add(JobRun(RunID=run_id, JobKey="DEV-OLD", SchedulerInstanceID=run_id, Status="SUCCESS", Host=host,
                  LogFile=log_file, StartedDateTime=ended, EndedDateTime=ended))
    db.commit()
    return log_root / host / log_file


def test_a_log_is_read_from_its_host_through_the_agent(db, client, log_root):
    old_run(db, log_root, days_ago=1)
    run = client.get("/api/v1/runs/old").json()
    assert (run["has_log"], run["log"], run["log_note"]) == (True, ["line 1", "line 2"], None)


def test_logs_older_than_the_setting_are_removed_and_the_run_says_when(db, client, log_root):
    old = old_run(db, log_root, "old", days_ago=40)
    recent = old_run(db, log_root, "recent", days_ago=3)

    assert remove_old_logs(db) == 1                 # the default keeps 30 days

    assert not old.exists() and not old.parent.exists() and recent.exists()
    run = client.get("/api/v1/runs/old").json()
    assert (run["has_log"], run["log"]) == (False, [])
    assert run["log_note"].startswith("This run's log was removed on ")
    assert remove_old_logs(db) == 0                 # each once


def test_the_setting_can_keep_logs_longer_or_forever(db, log_root):
    old = old_run(db, log_root, days_ago=400)
    db.add(SettingValue(SettingKey="LogRetentionDays", SettingValue="FOREVER"))
    db.commit()
    assert remove_old_logs(db) == 0 and old.exists()


def test_a_log_missing_from_its_host_is_said_so(db, client, log_root):
    old_run(db, log_root, days_ago=1).unlink()
    run = client.get("/api/v1/runs/old").json()
    assert run["log"] == []
    assert run["log_note"] == "Host 'agent-1' has no log file for this run (it was looking for " + \
        db.query(JobRun).one().LogFile + ")."


def test_a_record_cannot_point_the_agent_outside_its_hosts_folder(db, client, log_root):
    (log_root / "secret.txt").parent.mkdir(parents=True, exist_ok=True)
    (log_root / "secret.txt").write_text("not a log")
    db.add(JobRun(RunID="sly", JobKey="X", SchedulerInstanceID="1", Status="SUCCESS", Host="agent-1",
                  LogFile="../secret.txt", StartedDateTime=datetime(2026, 10, 1)))
    db.commit()
    assert client.get("/api/v1/runs/sly").json()["log"] == []


def test_an_old_runners_log_records_still_load_but_are_not_kept(db, client):
    records = [
        {"Record": "RUN_START", "RunID": "r1", "Seq": 1, "JobKey": "X", "InstanceID": "1",
         "StartedAtUtc": "2026-10-01T09:00:00Z"},
        {"Record": "LOG", "RunID": "r1", "Seq": 2, "Lines": ["hello"]},
        {"Record": "RUN_END", "RunID": "r1", "Seq": 3, "Status": "SUCCESS", "EndedAtUtc": "2026-10-01T09:01:00Z"},
    ]
    ingest_records(db, records)
    run = client.get("/api/v1/runs/r1").json()
    assert (run["status"], run["has_log"], run["log"]) == ("SUCCESS", False, [])


def test_an_unknown_run_is_404(client):
    response = client.get("/api/v1/runs/no-such-run")

    assert response.status_code == 404
    assert "no record of run 'no-such-run'" in response.json()["detail"]


MIGRATION = __import__("pathlib").Path(__file__).resolve().parents[2] / "SQL" / "migrate_log_files.py"
OLD_LOG_SCHEMA = """
CREATE TABLE JobRuns (id INTEGER PRIMARY KEY, RunID VARCHAR(36), Host VARCHAR(255), StartedDateTime DATETIME);
CREATE TABLE JobRunLogs (id INTEGER PRIMARY KEY, JobRun_id INTEGER, Seq INTEGER, LogText TEXT);
INSERT INTO JobRuns VALUES (1, 'r1', 'penguin', '2026-10-15 09:00:00.000000'), (2, 'r2', NULL, '2026-10-16 10:00:00'),
                           (3, 'r3', 'penguin', '2026-10-16 11:00:00');
INSERT INTO JobRunLogs VALUES (1, 1, 2, 'line 3'), (2, 1, 1, 'line 1\nline 2'), (3, 2, 1, 'only line');
"""


def test_the_migration_moves_each_log_to_a_file_and_drops_the_table(tmp_path, log_root):
    import os, sqlite3, subprocess, sys
    database = tmp_path / "old.db"
    connection = sqlite3.connect(database)
    connection.executescript(OLD_LOG_SCHEMA)
    connection.commit()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    outputs = [subprocess.run([sys.executable, str(MIGRATION)], env=env, check=True, capture_output=True, text=True).stdout
               for _ in range(2)]
    assert "Wrote 2 run log(s)" in outputs[0] and "Dropped the JobRunLogs table." in outputs[0]
    assert "There was no JobRunLogs table to move." in outputs[1]

    rows = connection.execute("SELECT RunID, LogFile FROM JobRuns ORDER BY id").fetchall()
    assert rows == [("r1", "2026-10-15/r1.log"), ("r2", "2026-10-16/r2.log"), ("r3", None)]
    assert (log_root / "penguin" / "2026-10-15" / "r1.log").read_text() == "line 1\nline 2\nline 3\n"
    assert (log_root / "unknown" / "2026-10-16" / "r2.log").read_text() == "only line\n"
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "JobRunLogs" not in tables

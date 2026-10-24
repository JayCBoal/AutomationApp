"""
What a run knows about the scheduler that started it: the environment it was
started in (where schedulers put a job's own variables), the business date a
scheduler such as Control-M gives, and the registered Scheduler itself.
"""
import subprocess
import sys
from datetime import date

import pytest

from core.models import JobRun, SettingValue
from conftest import AUTOAPP_DIR, subprocess_env
from engine.scope_engine import ScopeResolutionEngine
from engine import settings


@pytest.fixture
def engine_for(db, tmp_path):
    def _engine(job, environment=None, business_date=None):
        db.flush()
        engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="I1",
                                       global_config={"WORKING_ROOT": str(tmp_path / "work")},
                                       environment=environment, business_date=business_date)
        engine.build_context()
        return engine
    return _engine


# --- Environment variables ---------------------------------------------------------------------

def test_env_names_an_environment_variable(seed, engine_for):
    engine = engine_for(seed.job("DEV-LOAD"), environment={"BATCH_ID": "B42"})

    assert engine.interpolate("in/${ENV:BATCH_ID}") == "in/B42"


def test_a_plain_name_falls_back_to_the_environment(seed, engine_for):
    engine = engine_for(seed.job("DEV-LOAD"), environment={"Region": "EU"})

    assert engine.interpolate("${Region}") == "EU"


def test_the_environment_has_the_lowest_priority(seed, engine_for):
    job = seed.job("DEV-LOAD", Region="US")

    assert engine_for(job, environment={"Region": "EU"}).interpolate("${Region}") == "US"


def test_a_missing_environment_variable_says_so(seed, engine_for):
    engine = engine_for(seed.job("DEV-LOAD"), environment={})

    with pytest.raises(ValueError) as error:
        engine.interpolate("in/${ENV:BATCH_ID}")
    assert "No environment variable BATCH_ID was set for this run" in str(error.value)


def test_without_an_environment_env_is_left_for_the_run(seed, engine_for):
    """On the server, checking or previewing a job: what a scheduler will set cannot be known there."""
    engine = engine_for(seed.job("DEV-LOAD"), environment=None)

    assert engine.interpolate("in/${ENV:BATCH_ID}") == "in/${ENV:BATCH_ID}"
    with pytest.raises(ValueError, match="Unresolved placeholder"):
        engine.interpolate("in/${Typo}")            # a plain name found nowhere is still an error


def test_the_pre_run_check_accepts_env_placeholders(seed, client, db, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, Source="in/${ENV:BATCH_ID}/*.csv", Dest="out")
    db.commit()

    assert client.get("/api/v1/jobs/DEV-LOAD/check").json()["valid"] is True


def test_a_precedence_saved_before_env_existed_keeps_its_order(db, seed):
    db.add(SettingValue(SettingKey="VariablePrecedence", SettingValue="SYS,ENTITY,APP,ENDPOINT,JOB,TAG"))
    db.flush()

    assert settings.current(db, "VariablePrecedence") == [
        "ENV", "SYS", "ENTITY", "APP", "ENDPOINT", "JOB", "TAG", "WORKFLOW", "USE"]


# --- Business date -----------------------------------------------------------------------------

def test_business_date_shows_the_date_the_scheduler_gave(seed, engine_for):
    engine = engine_for(seed.job("DEV-LOAD"), business_date=date(2026, 9, 30))

    assert engine.interpolate("Batch_${BUSINESS_DATE:yyyyMMdd}.csv") == "Batch_20260930.csv"
    assert engine.interpolate("${BUSINESS_DATE:yyyy-MM-dd HH:mm}") == "2026-09-30 00:00"


def test_without_a_business_date_it_is_the_runs_own_date(seed, engine_for):
    engine = engine_for(seed.job("DEV-LOAD"))

    assert engine.interpolate("${BUSINESS_DATE:yyyyMMdd}") == engine.interpolate("${DATE:yyyyMMdd}")


def test_a_business_date_mask_is_checked_like_a_date_mask(seed, engine_for):
    engine = engine_for(seed.job("DEV-LOAD"))

    with pytest.raises(ValueError, match="BUSINESS_DATE:yyyyMMdd"):
        engine.interpolate("${BUSINESS_DATE:}")


# --- Through the runner ------------------------------------------------------------------------

def runner(db, db_url, tmp_path, *args, environment=None):
    db.commit()
    return subprocess.run(
        [sys.executable, "-m", "engine.runner", "--spool-dir", str(tmp_path / "spool"),
         "--working-root", str(tmp_path / "work"), *args],
        cwd=AUTOAPP_DIR, env={**subprocess_env(db_url), **(environment or {})}, capture_output=True, text=True)


def test_the_runner_uses_the_environment_and_the_business_date(db, db_url, seed, endpoints, tmp_path, load_spool):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="in_${ENV:BATCH_ID}_${BUSINESS_DATE:yyyyMMdd}")

    result = runner(db, db_url, tmp_path, "--job-key", "DEV-LOAD", "--instance-id", "CTM1",
                    "--business-date", "20260930", "--scheduler", "CTM_PROD", environment={"BATCH_ID": "B42"})

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "work" / "DEV-LOAD" / "in_B42_20260930").is_dir()
    assert "business date 2026-09-30" in result.stdout
    load_spool()
    run = db.query(JobRun).one()
    assert (run.BusinessDate, run.SchedulerName) == (date(2026, 9, 30), "CTM_PROD")


def test_a_business_date_that_is_not_a_date_is_refused(db, db_url, seed, tmp_path):
    seed.job("DEV-LOAD")

    result = runner(db, db_url, tmp_path, "--job-key", "DEV-LOAD", "--instance-id", "X", "--business-date", "30/09/2026")

    assert result.returncode == 2
    assert "'30/09/2026' is not a date: use YYYY-MM-DD or YYYYMMDD" in result.stderr


def test_job_history_shows_the_business_date(db, db_url, seed, endpoints, tmp_path, load_spool, client):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="in")
    runner(db, db_url, tmp_path, "--job-key", "DEV-LOAD", "--instance-id", "CTM1", "--business-date", "2026-09-30")
    load_spool()

    [run] = client.get("/api/v1/runs").json()

    assert run["business_date"] == "2026-09-30"


# --- Schedulers --------------------------------------------------------------------------------

def test_a_scheduler_is_registered_found_and_changed(client):
    created = client.post("/api/v1/schedulers", json={
        "name": "RMJ_PROD", "technology": "runmyjobs", "api_url": "https://rmj.example/api",
        "variables": [{"name": "ApiToken", "value": "t0k3n", "secret": True}]})
    assert created.status_code == 201, created.text
    assert created.json()["technology"] == "RUNMYJOBS"

    scheduler = client.get("/api/v1/schedulers/RMJ_PROD").json()
    assert (scheduler["technology"], scheduler["api_url"], scheduler["runs"]) == ("RUNMYJOBS", "https://rmj.example/api", 0)
    assert scheduler["variables"] == [{"name": "ApiToken", "value": None, "secret": True, "description": None}]

    changed = client.put("/api/v1/schedulers/RMJ_PROD", json={"technology": "CONTROL_M"}).json()
    assert changed["changes"] == ["Changed the technology to CONTROL_M."]
    assert [s["name"] for s in client.get("/api/v1/schedulers", params={"technology": "control"}).json()] == ["RMJ_PROD"]


def test_a_scheduler_technology_must_be_one_of_the_list(client):
    response = client.post("/api/v1/schedulers", json={"name": "X", "technology": "Autosys"})

    assert response.status_code == 422
    assert "must be one of RUNMYJOBS, ACTIVEBATCH, CONTROL_M, TIDAL, CRON, STANDIN, OTHER" in response.json()["detail"]
    client.post("/api/v1/schedulers", json={"name": "Y"})
    assert client.put("/api/v1/schedulers/Y", json={"technology": "Autosys"}).status_code == 422


def test_a_scheduler_counts_the_runs_it_started(db, db_url, seed, endpoints, tmp_path, load_spool, client):
    client.post("/api/v1/schedulers", json={"name": "CTM_PROD", "technology": "CONTROL_M"})
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="in")
    runner(db, db_url, tmp_path, "--job-key", "DEV-LOAD", "--instance-id", "CTM1", "--scheduler", "CTM_PROD")
    load_spool()

    assert client.get("/api/v1/schedulers/CTM_PROD").json()["runs"] == 1
    assert [e["value"] for e in client.get("/api/v1/lookups").json()["schedulers"]] == ["CTM_PROD"]

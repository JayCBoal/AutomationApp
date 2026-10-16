"""
The Stand-in Scheduler (demo/scheduler_standin) and RunMyFiles' connector for it:
a real stand-in server beside a real RunMyFiles server (live_api), each in its own
process, talking to each other only as a WLA and RunMyFiles would.
"""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app.models import Scheduler, Variable
from conftest import AUTOAPP_DIR, subprocess_env

STANDIN_DIR = Path(AUTOAPP_DIR).parent / "demo" / "scheduler_standin"
TOKEN = "test-token"


def call(method, url, body=None, token=None):
    """A request; refusals come back as (status, body) too."""
    request = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode()
            return response.status, json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null")


@pytest.fixture
def standin(live_api, db_url, tmp_path):
    """The stand-in, on a free port, with its own database, running RunMyFiles jobs against live_api. Yields its address."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = {**subprocess_env(db_url), "AUTOAPP_WORKING_ROOT": str(tmp_path / "work"),
           "AUTOAPP_SPOOL_DIR": str(tmp_path / "spool"),
           "STANDIN_DATABASE_URL": f"sqlite:///{tmp_path / 'standin.db'}", "STANDIN_TOKEN": TOKEN,
           "STANDIN_NAME": "STANDIN", "STANDIN_AUTOAPP_URL": live_api, "STANDIN_AUTOAPP_DIR": str(AUTOAPP_DIR)}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "standin.app:app", "--host", "127.0.0.1",
                               "--port", str(port), "--log-level", "warning"], cwd=STANDIN_DIR, env=env)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/api/config", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        yield url
    finally:
        server.terminate()
        server.wait()


@pytest.fixture
def registered(db, standin):
    """The stand-in registered in RunMyFiles, with the token its API wants."""
    scheduler = Scheduler(Name="STANDIN", Technology="STANDIN", ApiUrl=standin)
    db.add(scheduler)
    db.flush()
    db.add(Variable(MasterObject_id=scheduler.MasterObject_id, VarName="ApiToken", VarValue=TOKEN, IsSecret=True))
    db.commit()
    return scheduler


@pytest.fixture
def wla_job(standin):
    status, job = call("POST", f"{standin}/api/jobs", {
        "name": "BILLING_EXPORT", "autoapp_job_key": "DEV-REGIONAL", "business_date": True,
        "parameters": [{"name": "Region", "value": "EU"}, {"name": "ExportPassword", "value": "hunter2", "secret": True}],
    }, token=TOKEN)
    assert status == 201, job
    return job


@pytest.fixture
def regional(seed, endpoints, db):
    """A RunMyFiles job that needs the scheduler's Region parameter."""
    job = seed.job("DEV-REGIONAL")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="in_${Region}_${BUSINESS_DATE:yyyyMMdd}")
    seed.step(job, 2, Source="in_${Region}_${BUSINESS_DATE:yyyyMMdd}/*.csv", Dest="pw_${ENV:ExportPassword}")
    db.commit()
    return job


# --- The stand-in's own API --------------------------------------------------------------------

def test_the_standins_api_wants_its_token(standin):
    assert call("GET", f"{standin}/api/jobs")[0] == 401
    assert call("GET", f"{standin}/api/jobs", token="wrong")[0] == 401
    assert call("GET", f"{standin}/api/jobs", token=TOKEN) == (200, [])


def test_the_standin_never_gives_out_a_secret(standin, wla_job):
    status, job = call("GET", f"{standin}/api/jobs/BILLING_EXPORT", token=TOKEN)

    assert status == 200
    assert {p["name"]: (p["value"], p["secret"]) for p in job["parameters"]} == {
        "ExportPassword": (None, True), "Region": ("EU", False)}
    assert "hunter2" not in json.dumps(job)


# --- RunMyFiles reading it ------------------------------------------------------------------------

def test_autoapp_reads_a_wla_jobs_parameters_through_the_connector(live_api, registered, wla_job):
    status, job = call("GET", f"{live_api}/api/v1/schedulers/STANDIN/jobs/BILLING_EXPORT")

    assert status == 200, job
    assert job["parameters"] == [{"name": "ExportPassword", "value": None, "secret": True},
                                 {"name": "Region", "value": "EU", "secret": False}]


def test_the_connector_says_what_went_wrong(live_api, db, registered, wla_job):
    status, answer = call("GET", f"{live_api}/api/v1/schedulers/STANDIN/jobs/NO_SUCH_JOB")
    assert (status, answer["detail"]) == (502, "Scheduler 'STANDIN' has no job 'NO_SUCH_JOB'.")

    db.query(Variable).filter(Variable.VarName == "ApiToken").one().VarValue = "wrong"
    db.commit()
    status, answer = call("GET", f"{live_api}/api/v1/schedulers/STANDIN/jobs/BILLING_EXPORT")
    assert status == 502 and "refused RunMyFiles' credential" in answer["detail"]

    assert call("GET", f"{live_api}/api/v1/schedulers/NOPE/jobs/X")[0] == 404


def test_a_technology_without_a_connector_says_so(live_api, db):
    db.add(Scheduler(Name="TIDAL_PROD", Technology="TIDAL", ApiUrl="https://tidal.example"))
    db.commit()

    status, answer = call("GET", f"{live_api}/api/v1/schedulers/TIDAL_PROD/jobs/X")

    assert status == 502
    assert "RunMyFiles cannot read TIDAL schedulers yet. It can read: RUNMYJOBS, STANDIN." in answer["detail"]


def test_the_pre_run_check_uses_the_wla_jobs_parameters(live_api, registered, wla_job, regional):
    plain = call("GET", f"{live_api}/api/v1/jobs/DEV-REGIONAL/check")[1]
    with_wla = call("GET", f"{live_api}/api/v1/jobs/DEV-REGIONAL/check?scheduler=STANDIN&wla_job=BILLING_EXPORT")[1]

    assert plain["valid"] is False and any("${Region}" in p for p in plain["problems"])
    assert with_wla["valid"] is True, with_wla["problems"]


def test_a_check_that_cannot_reach_the_scheduler_warns_and_carries_on(live_api, registered, regional):
    status, check = call("GET", f"{live_api}/api/v1/jobs/DEV-REGIONAL/check?scheduler=STANDIN&wla_job=NOT_THERE")

    assert status == 200
    assert "could not be read" in check["warnings"][0] and "has no job 'NOT_THERE'" in check["warnings"][0]


# --- The stand-in running RunMyFiles jobs ---------------------------------------------------------

def submit_and_wait(standin, name="BILLING_EXPORT"):
    status, run = call("POST", f"{standin}/api/jobs/{name}/submit", token=TOKEN)
    assert status == 202, run
    for _ in range(150):
        run = call("GET", f"{standin}/api/runs/{run['id']}", token=TOKEN)[1]
        if run["status"] != "RUNNING":
            return run
        time.sleep(0.2)
    raise AssertionError(f"the run did not end: {run}")


def test_the_standin_runs_an_autoapp_job_with_its_parameters(live_api, registered, wla_job, regional, tmp_path):
    run = submit_and_wait(standin=registered.ApiUrl)

    assert (run["status"], run["exit_code"]) == ("SUCCESS", 0), run["output"]
    assert run["instance_id"] == "SIS-1"
    today = time.strftime("%Y%m%d")
    assert (tmp_path / "work" / "DEV-REGIONAL" / f"in_EU_{today}").is_dir()
    assert f"--instance-id SIS-1 --scheduler STANDIN" in run["command"] and "--business-date" in run["command"]
    # RunMyFiles has the run, from the stand-in, with its business date
    [recorded] = call("GET", f"{live_api}/api/v1/runs?instance_id=SIS-1")[1]
    assert (recorded["scheduler"], recorded["business_date"]) == ("STANDIN", time.strftime("%Y-%m-%d"))


def test_the_wlas_secret_parameter_is_masked_in_both_logs(live_api, registered, wla_job, regional, tmp_path):
    run = submit_and_wait(standin=registered.ApiUrl)

    assert (tmp_path / "work" / "DEV-REGIONAL" / "pw_hunter2").is_dir()      # the real value was used
    assert "hunter2" not in run["output"] and "pw_********" in run["output"]
    [recorded] = call("GET", f"{live_api}/api/v1/runs?instance_id=SIS-1")[1]
    log = call("GET", f"{live_api}/api/v1/runs/{recorded['run_id']}")[1]["log"]
    assert "hunter2" not in "\n".join(log)


def test_a_job_with_no_autoapp_job_cannot_be_submitted(standin):
    call("POST", f"{standin}/api/jobs", {"name": "LONELY"}, token=TOKEN)

    status, answer = call("POST", f"{standin}/api/jobs/LONELY/submit", token=TOKEN)

    assert status == 422 and "has no RunMyFiles job yet" in answer["detail"]


# --- In the browser ----------------------------------------------------------------------------

def test_the_editor_shows_the_wla_jobs_parameters(page, registered, wla_job, regional):
    page.goto("/ui/job.html?key=DEV-REGIONAL&scheduler=STANDIN&wla_job=BILLING_EXPORT&embed=1")
    page.locator("#wla-parameters table").wait_for()

    rows = {r.locator("td").nth(0).inner_text(): r.locator("td").nth(1).inner_text()
            for r in page.locator("#wla-parameters tbody tr").all()}
    assert rows == {"ExportPassword": "********", "Region": "EU"}
    page.get_by_text("Ready to run").wait_for()                              # the check used them


def test_the_standins_page_opens_autoapps_editor_and_learns_a_new_jobs_key(browser, registered, seed, db):
    standin = registered.ApiUrl
    call("POST", f"{standin}/api/jobs", {"name": "NEW_ONE", "parameters": [{"name": "Region", "value": "EU"}]}, token=TOKEN)
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    page = context.new_page()
    page.goto(f"{standin}/ui/?job=NEW_ONE")
    page.locator("#edit-in-autoapp").wait_for()

    page.locator("#edit-in-autoapp").click()
    frame = page.frame_locator("#autoapp-frame")
    frame.locator("#job-key").wait_for()
    assert frame.locator("#job-key").input_value() == "NEW_ONE"
    frame.locator("#submit-button").click()

    page.wait_for_function("() => document.querySelector('#autoapp-job-key').value === 'NEW_ONE'", timeout=15000)
    page.locator("#notice", has_text="Saved job 'NEW_ONE'").wait_for()      # the stand-in has stored it
    assert call("GET", f"{standin}/api/jobs/NEW_ONE", token=TOKEN)[1]["autoapp_job_key"] == "NEW_ONE"
    context.close()


def test_the_standin_shows_what_autoapp_says_about_its_job(browser, registered, wla_job, regional):
    standin = registered.ApiUrl
    status, answer = call("GET", f"{standin}/api/jobs/BILLING_EXPORT/autoapp", token=TOKEN)
    assert status == 200 and answer["error"] is None
    assert (answer["summary"]["job_key"], answer["summary"]["ready"]) == ("DEV-REGIONAL", True)   # with its parameters
    submit_and_wait(standin)

    context = browser.new_context(viewport={"width": 1400, "height": 900})
    page = context.new_page()
    page.goto(f"{standin}/ui/?job=BILLING_EXPORT")
    page.locator("#autoapp-steps li").first.wait_for()

    assert page.locator("#autoapp-ready").inner_text() == "Ready to run"
    assert page.locator("#autoapp-steps li").count() == 2
    page.locator("#autoapp-run-log").wait_for()
    page.locator("#autoapp-run-log").click()
    page.frame_locator("#autoapp-frame").locator("#job-log").wait_for()
    context.close()

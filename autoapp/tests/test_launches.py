"""
Running a job from the web interface: POST /api/v1/launches starts the real
runner as a separate process, which records its run through the API as it goes.
These go through a real server (live_api), as the page does.
"""
import json
import time
import urllib.error
import urllib.request

import pytest


class Answer:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return json.loads(self.body)

    @property
    def text(self):
        return self.body


def call(method, url, body=None):
    """A request to the live server; refusals come back as answers, not exceptions."""
    request = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return Answer(response.status, response.read().decode())
    except urllib.error.HTTPError as e:
        return Answer(e.code, e.read().decode())


def get(url):
    return call("GET", url)


def post(url, json=None):
    return call("POST", url, json)


@pytest.fixture
def collect(seed, endpoints, db):
    job = seed.job("DEV-COLLECT")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    db.commit()
    return job


def follow(api, launch, timeout=30):
    """Waits for the launch to finish and its run to be recorded as ended. Returns (launch, run)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        launch = get(f"{api}/api/v1/launches/{launch['launch_id']}").json()
        run = get(f"{api}/api/v1/runs/{launch['run_id']}").json() if launch["recorded"] else None
        if launch["state"] == "FINISHED" and (run is None or run["status"] != "RUNNING"):
            return launch, run
        time.sleep(0.3)
    raise AssertionError(f"the launch did not finish: {launch}")


def test_a_launched_job_runs_and_is_recorded_with_its_log(live_api, collect, tmp_path):
    response = post(f"{live_api}/api/v1/launches", json={"job_key": "DEV-COLLECT", "instance_id": "UI-T1"})
    assert response.status_code == 202, response.text
    launch = response.json()
    assert launch["state"] == "RUNNING"
    assert launch["command"] == "python3 -m engine.runner --job-key DEV-COLLECT --instance-id UI-T1 --log-level DETAIL"

    launch, run = follow(live_api, launch)

    assert launch["exit_code"] == 0
    assert (run["status"], run["instance_id"], run["scheduler"], run["operations"]) == ("SUCCESS", "UI-T1", "RunMyFiles UI", 2)
    assert any("Job 'DEV-COLLECT' completed successfully." in line for line in run["log"])
    assert (tmp_path / "work" / "DEV-COLLECT" / "incoming" / "Legal_Batch_1.csv").exists()


def test_a_launch_without_an_instance_id_is_given_one(live_api, collect):
    launch = post(f"{live_api}/api/v1/launches", json={"job_key": "DEV-COLLECT"}).json()

    assert launch["instance_id"].startswith("UI-")
    follow(live_api, launch)


def test_a_failing_job_is_recorded_as_failed(live_api, seed, db):
    job = seed.job("DEV-BROKEN")
    seed.step(job, 1, Source="nowhere/*.csv", Dest="out")
    db.commit()

    launch, run = follow(live_api, post(f"{live_api}/api/v1/launches", json={"job_key": "DEV-BROKEN"}).json())

    assert launch["exit_code"] == 1
    assert run["status"] == "FAILED" and "No files matched" in run["error"]


def test_the_log_level_is_passed_to_the_runner(live_api, collect):
    launch = post(f"{live_api}/api/v1/launches",
                           json={"job_key": "DEV-COLLECT", "log_level": "summary"}).json()

    _, run = follow(live_api, launch)

    assert "--log-level SUMMARY" in launch["command"]
    assert not any("BEGIN Step" in line for line in run["log"])     # DETAIL, so not in a SUMMARY log
    assert any("END Step 1: Collect" in line for line in run["log"])


def test_a_launch_is_refused_for_an_unknown_job_a_bad_level_or_a_used_instance_id(live_api, collect):
    def launch(**body):
        return post(f"{live_api}/api/v1/launches", json=body)

    assert launch(job_key="NO-SUCH-JOB").status_code == 404
    assert launch(job_key="DEV-COLLECT", log_level="LOUD").status_code == 422
    follow(live_api, launch(job_key="DEV-COLLECT", instance_id="UI-SAME").json())
    response = launch(job_key="DEV-COLLECT", instance_id="UI-SAME")
    assert response.status_code == 409
    assert "already run as instance 'UI-SAME'" in response.json()["detail"]


def test_an_unknown_launch_is_404(live_api):
    assert get(f"{live_api}/api/v1/launches/nope").status_code == 404


def test_a_launch_can_give_a_business_date(live_api, seed, endpoints, db):
    job = seed.job("DEV-DATED")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="in_${BUSINESS_DATE:yyyyMMdd}")
    db.commit()

    launch = post(f"{live_api}/api/v1/launches", json={"job_key": "DEV-DATED", "business_date": "2026-09-30"}).json()
    launch, run = follow(live_api, launch)

    assert "--business-date 2026-09-30" in launch["command"]
    assert (run["status"], run["business_date"]) == ("SUCCESS", "2026-09-30")

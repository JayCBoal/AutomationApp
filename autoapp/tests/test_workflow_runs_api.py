"""
Workflow runs through the API, as the pages see them (docs/WORKFLOWS_PHASE1.md, steps 3 and 4):
a workflow started like any job (POST /api/v1/launches), its run with its jobs, Job History's
workflow columns and filters, and Cancel. These go through a real server (live_api).
"""
import time

import pytest

from app.models import Job, WorkflowItem, WorkflowPrerequisite
from test_launches import follow, get, post


@pytest.fixture
def workflow(seed, db):
    """FLOW: First (waits 'wait' seconds), then Second after it."""
    def _make(wait=0):
        jobs = []
        for key, seconds in (("FIRST", wait), ("SECOND", 0)):
            job = seed.job(key)
            seed.step(job, 1, "SIMULATE", title="Pretend", WaitSeconds=str(seconds))
            jobs.append(job)
        flow = seed._add(Job(JobKey="FLOW", JobType="WORKFLOW"))
        first = seed._add(WorkflowItem(workflow=flow, ItemName="First", job=jobs[0], ItemOrder=1))
        second = seed._add(WorkflowItem(workflow=flow, ItemName="Second", job=jobs[1], ItemOrder=2))
        seed._add(WorkflowPrerequisite(item=second, target=first, Test="SUCCESS"))
        db.commit()
    return _make


def launch(api):
    response = post(f"{api}/api/v1/launches", json={"job_key": "FLOW", "instance_id": "UI-W1"})
    assert response.status_code == 202, response.text
    return response.json()


def test_a_workflow_starts_like_a_job_and_its_run_lists_its_jobs(live_api, workflow):
    workflow()
    started, run = follow(live_api, launch(live_api), timeout=90)

    assert started["exit_code"] == 0, run
    assert (run["job_type"], run["status"], run["return_code"]) == ("WORKFLOW", "SUCCESS", 0)
    assert [(i["name"], i["status"], i["attempt"]) for i in run["items"]] == [("First", "SUCCESS", 1), ("Second", "SUCCESS", 1)]
    assert any("Workflow 'FLOW' completed successfully." in line for line in run["log"])

    first = get(f"{live_api}/api/v1/runs/{run['items'][0]['run_id']}").json()
    assert (first["job_key"], first["parent_run_id"], first["workflow_path"], first["scheduler"]) == (
        "FIRST", run["run_id"], "First", "AutoApp workflow")


def test_job_history_shows_a_workflow_run_and_the_runs_inside_it(live_api, workflow):
    workflow()
    _, run = follow(live_api, launch(live_api), timeout=90)
    inside = get(f"{live_api}/api/v1/runs?within={run['run_id']}").json()
    assert sorted((r["job_key"], r["job_type"], r["parent_run_id"]) for r in inside) == [
        ("FIRST", "STEPS", run["run_id"]), ("FLOW", "WORKFLOW", None), ("SECOND", "STEPS", run["run_id"])]
    assert [r["job_key"] for r in get(f"{live_api}/api/v1/runs?job_type=WORKFLOW").json()] == ["FLOW"]


def test_job_history_as_a_tree_lists_the_runs_inside_a_workflow_run_under_it(live_api, workflow):
    """docs/WORKFLOWS_PHASE2.md, step 5: with tree=true, a run whose workflow run is listed too is left out."""
    workflow()
    _, run = follow(live_api, launch(live_api), timeout=90)
    top = get(f"{live_api}/api/v1/runs?tree=true").json()
    assert [(r["job_key"], r["child_count"]) for r in top] == [("FLOW", 2)]
    inside = get(f"{live_api}/api/v1/runs?parent={run['run_id']}").json()
    assert sorted(r["job_key"] for r in inside) == ["FIRST", "SECOND"]
    assert all(r["child_count"] == 0 for r in inside)

    # Found by the search when its workflow run is not: a row of its own, saying which run it was in
    found = get(f"{live_api}/api/v1/runs?tree=true&job_key=FIRST").json()
    assert [(r["job_key"], r["parent_run_id"]) for r in found] == [("FIRST", run["run_id"])]
    # Within a run: that run alone at the top, the runs inside it under it
    assert [r["job_key"] for r in get(f"{live_api}/api/v1/runs?tree=true&within={run['run_id']}").json()] == ["FLOW"]
    # Without tree, as before: every run is a row
    assert len(get(f"{live_api}/api/v1/runs").json()) == 3
    assert get(f"{live_api}/api/v1/runs?parent=NO-SUCH-RUN").status_code == 404


def test_a_cancelled_workflow_starts_nothing_more(live_api, workflow):
    workflow(wait=4)
    started = launch(live_api)
    deadline = time.time() + 60
    while time.time() < deadline:
        run = get(f"{live_api}/api/v1/runs/{started['run_id']}").json() if get(
            f"{live_api}/api/v1/launches/{started['launch_id']}").json()["recorded"] else None
        if run and run["items"] and run["items"][0]["status"] == "RUNNING":
            break
        time.sleep(0.3)

    answer = post(f"{live_api}/api/v1/runs/{started['run_id']}/cancel")
    assert answer.status_code == 200 and answer.json()["cancel_requested"]

    _, run = follow(live_api, started, timeout=90)
    assert (run["status"], run["reason"]) == ("FAILED", "CANCELLED")
    assert [(i["name"], i["status"], i["reason"]) for i in run["items"]] == [
        ("First", "SUCCESS", None), ("Second", "NOT_RUN", "CANCELLED")]
    again = post(f"{live_api}/api/v1/runs/{started['run_id']}/cancel")
    assert again.status_code == 409 and "has already ended (FAILED)" in again.json()["detail"]
    job_run = post(f"{live_api}/api/v1/runs/{run['items'][0]['run_id']}/cancel")
    assert job_run.status_code == 422 and "Only a workflow run can be cancelled" in job_run.json()["detail"]

"""
Reactions, Disable here and Kill over HTTP (docs/WORKFLOWS_PHASE3.md, step 3): a job's own
Reactions and a use's override, saved with the job through /api/v1/jobs and checked as they
are saved; a run's details; Kill on a job, a workflow and a job in a workflow run.
"""
import json
import time

import pytest

from app.models import Audit, Job, WorkflowItem
from test_launches import follow, get, post

ROUTE = "/api/v1/jobs"


@pytest.fixture
def sims(seed, db):
    """Jobs of one Simulate step: LOAD, CHECK, FIX; SLOW waits 30 seconds."""
    for key, wait in (("LOAD", 0), ("CHECK", 0), ("FIX", 0), ("SLOW", 30)):
        seed.step(seed.job(key), 1, "SIMULATE", title="Pretend", WaitSeconds=str(wait))
    db.commit()


def act(action, **settings):
    return {"action": action, **settings}


def reaction(when, *actions, section="NEXT", codes=None):
    return {"section": section, "when": when, "return_codes": codes, "actions": list(actions)}


def steps_job(key, reactions):
    return {"job_key": key, "steps": [{"step_type": "SIMULATE", "title": "Pretend", "parameters": {}}],
            "reactions": reactions}


def use(job_key, name, after=(), **more):
    return {"job_key": job_key, "name": name, "prerequisites": [{"target": t, "test": "SUCCESS"} for t in after], **more}


def a_workflow(key, items):
    return {"job_key": key, "job_type": "WORKFLOW", "items": items}


# ---------- A job's own Reactions ----------

def test_a_jobs_reactions_are_saved_in_order_and_read_back(client, db):
    reactions = [reaction("RC", act("RERUN", max_times=2, wait_seconds=30), codes="8"),
                 reaction("FAILED", act("COUNT_AS_SUCCEEDED")),
                 reaction("ENDED", act("START_WORKFLOW", workflow="ALERT"), section="ALSO")]
    assert client.post(ROUTE, json=a_workflow("ALERT", [])).status_code == 201
    response = client.post(ROUTE, json=steps_job("FLAKY", reactions))
    assert response.status_code == 201, response.text

    saved = client.get(f"{ROUTE}/FLAKY").json()["reactions"]
    assert [(r["section"], r["when"], r["return_codes"], [a["action"] for a in r["actions"]]) for r in saved] == [
        ("NEXT", "RC", "8", ["RERUN"]), ("NEXT", "FAILED", None, ["COUNT_AS_SUCCEEDED"]),
        ("ALSO", "ENDED", None, ["START_WORKFLOW"])]
    assert (saved[0]["actions"][0]["max_times"], saved[0]["actions"][0]["wait_seconds"]) == (2, 30)
    assert saved[2]["actions"][0]["workflow"] == "ALERT"

    # Saved again unchanged, nothing is recorded; changed, the audit says so
    client.put(f"{ROUTE}/FLAKY", json=steps_job("FLAKY", reactions))
    client.put(f"{ROUTE}/FLAKY", json=steps_job("FLAKY", reactions[1:]))
    changes = [c for a in db.query(Audit).order_by(Audit.id) for c in json.loads(a.Details)["changes"]
               if "Reactions" in c]
    assert changes == ["Changed the Reactions."]


def test_leaving_reactions_out_keeps_them(client):
    client.post(ROUTE, json=steps_job("KEEP", [reaction("FAILED", act("COUNT_AS_SUCCEEDED"))]))
    payload = steps_job("KEEP", [])
    del payload["reactions"]
    client.put(f"{ROUTE}/KEEP", json=payload)
    assert len(client.get(f"{ROUTE}/KEEP").json()["reactions"]) == 1


@pytest.mark.parametrize("reactions, message", [
    ([reaction("FAILED", act("SKIP_BRANCH"))],
     "Skip the rest of the branch needs a workflow around the job, so only a use of it in a workflow offers it."),
    ([reaction("FAILED", act("START_WORKFLOW", workflow="ALERT"))], "belongs under Also"),
    ([reaction("FAILED", act("COUNT_AS_FAILED"), section="ALSO")], "belongs under What happens next"),
    ([reaction("FAILED", act("RERUN", max_times=0))], "a rerun runs at most 1 to 100 times"),
    ([reaction("FAILED")], "does nothing"),
    ([reaction("RC", act("COUNT_AS_SUCCEEDED"), codes="x")], "Reaction 1"),
    ([reaction("ENDED", act("START_WORKFLOW", workflow="NOPE"), section="ALSO")], "'NOPE' is not one"),
    ([reaction("FAILED", act("COUNT_AS_SUCCEEDED"), act("COUNT_AS_FAILED"))], "Keep one"),
])
def test_reactions_that_break_a_rule_are_refused_saying_why(client, reactions, message):
    client.post(ROUTE, json=a_workflow("ALERT", []))
    response = client.post(ROUTE, json=steps_job("BAD", reactions))
    assert response.status_code == 422 and message in response.json()["detail"], response.text


def test_a_workflow_cannot_start_itself_or_one_that_uses_it(client, sims):
    client.post(ROUTE, json=a_workflow("INNER", [use("LOAD", "Load")]))
    client.post(ROUTE, json=a_workflow("OUTER", [use("INNER", "Inner")]))
    load_id = client.get(f"{ROUTE}/INNER").json()["items"][0]["id"]
    response = client.put(f"{ROUTE}/INNER", json={**a_workflow("INNER", [{**use("LOAD", "Load"), "id": load_id}]),
                                                  "reactions": [reaction("ENDED", act("START_WORKFLOW", workflow="OUTER"),
                                                                         section="ALSO")]})
    assert response.status_code == 422 and "would start this again" in response.json()["detail"]


def test_a_workflow_started_by_reactions_cannot_be_deleted(client, sims):
    client.post(ROUTE, json=a_workflow("ALERT", [use("FIX", "Fix")]))
    client.post(ROUTE, json=steps_job("NOISY", [reaction("FAILED", act("START_WORKFLOW", workflow="ALERT"), section="ALSO")]))
    response = client.delete(f"{ROUTE}/ALERT")
    assert response.status_code == 409 and "started by Reactions of 'NOISY'" in response.json()["detail"]


# ---------- A use's override, and Disable here ----------

def test_a_use_overrides_its_jobs_reactions_and_can_be_disabled_here(client, db, sims):
    client.put(f"{ROUTE}/CHECK", json=steps_job("CHECK", [reaction("FAILED", act("COUNT_AS_SUCCEEDED"))]))
    items = [use("LOAD", "Load"), use("FIX", "Fix", disabled_here="PASS_THROUGH"),
             use("CHECK", "Check", after=["Load"], reactions_overridden=True,
                 reactions=[reaction("FAILED", act("RERUN_FROM", target="Load", max_times=1), act("SKIP", target="Fix"))])]
    response = client.post(ROUTE, json=a_workflow("NIGHTLY", items))
    assert response.status_code == 201, response.text

    saved = {i["name"]: i for i in client.get(f"{ROUTE}/NIGHTLY").json()["items"]}
    assert saved["Fix"]["disabled_here"] == "PASS_THROUGH" and saved["Load"]["disabled_here"] is None
    check = saved["Check"]
    assert check["reactions_overridden"] is True
    assert [(a["action"], a["target"]) for a in check["reactions"][0]["actions"]] == [("RERUN_FROM", "Load"), ("SKIP", "Fix")]
    assert [a["action"] for a in check["job_reactions"][0]["actions"]] == ["COUNT_AS_SUCCEEDED"]
    assert saved["Load"]["reactions_overridden"] is False and saved["Load"]["reactions"] == []


def test_a_use_that_stops_overriding_drops_its_own_reactions(client, sims):
    own = [reaction("FAILED", act("SKIP_BRANCH"))]
    client.post(ROUTE, json=a_workflow("W", [use("LOAD", "Load", reactions_overridden=True, reactions=own)]))
    saved = client.get(f"{ROUTE}/W").json()["items"][0]
    client.put(f"{ROUTE}/W", json=a_workflow("W", [{**use("LOAD", "Load"), "id": saved["id"]}]))
    again = client.get(f"{ROUTE}/W").json()["items"][0]
    assert (again["reactions_overridden"], again["reactions"]) == (False, [])


@pytest.mark.parametrize("bad_use, message", [
    (use("CHECK", "Check", after=["Load"], reactions_overridden=True,
         reactions=[reaction("FAILED", act("RERUN_FROM", target="Fix", max_times=1))]),
     "Rerun from 'Fix' must name a job 'Check' waits for"),
    (use("CHECK", "Check", reactions_overridden=True, reactions=[reaction("FAILED", act("SKIP", target="Check"))]),
     "Skip must name another job in this workflow"),
    (use("CHECK", "Check", disabled_here="MAYBE"), "Disable here must be STOP or PASS_THROUGH"),
])
def test_a_uses_reactions_and_disable_here_are_checked(client, sims, bad_use, message):
    response = client.post(ROUTE, json=a_workflow("W", [use("LOAD", "Load"), use("FIX", "Fix"), bad_use]))
    assert response.status_code == 422 and message in response.json()["detail"], response.text


# ---------- Kill, through a real server ----------

def wait_until(api, run_id, test, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        answer = get(f"{api}/api/v1/runs/{run_id}")
        if answer.status_code == 200 and test(answer.json()):
            return answer.json()
        time.sleep(0.3)
    raise AssertionError("Gave up waiting")


def launch(api, job_key, instance):
    response = post(f"{api}/api/v1/launches", json={"job_key": job_key, "instance_id": instance})
    assert response.status_code == 202, response.text
    return response.json()


def test_kill_ends_a_running_job_killed(live_api, sims):
    started = launch(live_api, "SLOW", "K-1")
    wait_until(live_api, started["run_id"], lambda run: run["status"] == "RUNNING")
    assert post(f"{live_api}/api/v1/runs/{started['run_id']}/kill").status_code == 200

    _, run = follow(live_api, started, timeout=60)
    assert (run["status"], run["reason"], run["return_code"]) == ("FAILED", "KILLED", None)
    again = post(f"{live_api}/api/v1/runs/{started['run_id']}/kill")
    assert again.status_code == 409 and "nothing to kill" in again.json()["detail"]


def test_kill_and_cancel_on_a_workflow_and_kill_on_one_of_its_jobs(live_api, seed, db, sims):
    for key in ("BOTH", "ONE"):
        flow = seed._add(Job(JobKey=key, JobType="WORKFLOW"))
        seed._add(WorkflowItem(workflow=flow, ItemName="Slow", job=db.query(Job).filter_by(JobKey="SLOW").one(),
                               ItemOrder=1))
    db.commit()

    started = launch(live_api, "BOTH", "K-2")
    wait_until(live_api, started["run_id"], lambda run: run["items"] and run["items"][0]["status"] == "RUNNING")
    answer = post(f"{live_api}/api/v1/runs/{started['run_id']}/kill")
    assert answer.status_code == 200 and answer.json()["kill_requested"]
    _, run = follow(live_api, started, timeout=60)
    assert (run["status"], run["reason"]) == ("FAILED", "KILLED")
    assert (run["items"][0]["status"], run["items"][0]["reason"]) == ("FAILED", "KILLED")

    started = launch(live_api, "ONE", "K-3")
    wait_until(live_api, started["run_id"], lambda run: run["items"] and run["items"][0]["status"] == "RUNNING")
    assert post(f"{live_api}/api/v1/runs/{started['run_id']}/items/Slow/kill").status_code == 200
    _, run = follow(live_api, started, timeout=60)
    assert (run["items"][0]["status"], run["items"][0]["reason"]) == ("FAILED", "KILLED")
    assert (run["status"], run["reason"]) == ("FAILED", "JOB_FAILED")       # a killed job is a failure like any other

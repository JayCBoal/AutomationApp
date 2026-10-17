"""
Saving workflows over HTTP (docs/WORKFLOWS_PHASE1.md, step 2): a workflow is a job of type
WORKFLOW, saved through /api/v1/jobs with its items and their prerequisites.
"""
import json

import pytest

from app.models import Audit, Job, WorkflowItem

ROUTE = "/api/v1/jobs"


@pytest.fixture(autouse=True)
def working_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))


@pytest.fixture
def jobs(seed, db):
    """Three jobs made of steps, for workflows to use; each would run."""
    for key in ("EXTRACT.US", "EXTRACT_EU", "LOAD"):
        seed.step(seed.job(key), 1, Source="incoming/*.csv", Dest="outgoing")
    db.commit()


def item(job_key, name=None, join="ALL", after=(), **more):
    """after: (target, test) or (target, test, codes) tuples, or plain target names (succeeded)."""
    prerequisites = []
    for p in after:
        p = (p, "SUCCESS") if isinstance(p, str) else p
        prerequisites.append({"target": p[0], "test": p[1], **({"return_codes": p[2]} if len(p) > 2 else {})})
    return {"job_key": job_key, **({"name": name} if name else {}), "join": join, "prerequisites": prerequisites, **more}


def workflow(key="MONTH_END", items=None, **fields):
    return {"job_key": key, "job_type": "WORKFLOW", "description": "Month end", **fields,
            "items": items if items is not None else [
                item("EXTRACT.US", "Extract_US"), item("EXTRACT_EU", "Extract_EU"),
                item("LOAD", join="ANY", after=["Extract_US", ("Extract_EU", "RC", "0,4")])]}


def save(client, payload, key=None):
    return client.put(f"{ROUTE}/{key}", json=payload) if key else client.post(ROUTE, json=payload)


def as_submitted(saved):
    return {"job_key": saved["job_key"], "job_type": saved["job_type"], "description": saved["description"],
            "items": [{"id": i["id"], "name": i["name"], "job_key": i["job_key"], "join": i["join"],
                       "prerequisites": i["prerequisites"]} for i in saved["items"]]}


# ---------- Creating and reading ----------

def test_a_workflow_is_created_with_its_jobs_and_what_each_waits_for(client, jobs):
    response = save(client, workflow())
    assert response.status_code == 201, response.text
    saved = response.json()["job"]
    assert saved["job_type"] == "WORKFLOW" and saved["steps"] == []
    assert [(i["name"], i["job_key"], i["join"]) for i in saved["items"]] == [
        ("Extract_US", "EXTRACT.US", "ALL"), ("Extract_EU", "EXTRACT_EU", "ALL"), ("LOAD", "LOAD", "ANY")]
    assert saved["items"][2]["prerequisites"] == [
        {"target": "Extract_US", "test": "SUCCESS", "return_codes": None},
        {"target": "Extract_EU", "test": "RC", "return_codes": "0, 4"}]
    assert client.get(f"{ROUTE}/MONTH_END").json()["items"] == saved["items"]


def test_a_name_left_out_is_made_from_the_job_key(client, jobs):
    saved = save(client, workflow(items=[item("EXTRACT.US")])).json()["job"]
    assert saved["items"][0]["name"] == "EXTRACT_US"


def test_the_jobs_search_lists_workflows_with_their_type_and_size(client, jobs):
    save(client, workflow())
    rows = client.get(ROUTE, params={"job_type": "WORKFLOW"}).json()
    assert [(r["job_key"], r["job_type"], r["item_count"]) for r in rows] == [("MONTH_END", "WORKFLOW", 3)]
    assert {r["job_type"] for r in client.get(ROUTE, params={"job_type": "STEPS"}).json()} == {"STEPS"}


def test_a_workflow_whose_jobs_would_run_is_ready(client, jobs, db):
    result = save(client, workflow()).json()
    assert result["valid"], result["problems"]


def test_a_workflow_says_which_of_its_jobs_would_not_run(client, jobs, db):
    db.query(Job).filter(Job.JobKey == "LOAD").one().IsActive = False
    db.commit()
    result = save(client, workflow()).json()
    assert not result["valid"]
    assert result["problems"] == ["'LOAD' would not run: Job 'LOAD' is disabled."]


def test_an_empty_workflow_is_saved_but_will_not_run(client, jobs):
    result = save(client, workflow(items=[])).json()
    assert result["problems"] == ["Workflow 'MONTH_END' has no jobs in it yet. Add the jobs it should run."]


# ---------- What is refused, and why ----------

@pytest.mark.parametrize("items, message", [
    ([item("LOAD", "Same"), item("EXTRACT_EU", "Same")],
     "Two jobs in the workflow are both named 'Same'. Give one of them another name."),
    ([item("LOAD", "Bad name")], "'Bad name' cannot be the name of a job in a workflow."),
    ([item("LOAD", after=["Missing"])], "'LOAD' waits for 'Missing', which is not a job in this workflow."),
    ([item("LOAD", after=["LOAD"])], "'LOAD' cannot wait for itself."),
    ([item("LOAD", after=[("X", "MAYBE")]), item("EXTRACT_EU", "X")], "The test must be SUCCESS, FAILED, ENDED or RC."),
    ([item("LOAD", after=[("X", "RC", "4-0")]), item("EXTRACT_EU", "X")], "The range '4-0' in '4-0' runs backwards."),
    ([item("LOAD", join="SOME")], "'LOAD': its join must be ALL or ANY, not 'SOME'."),
    ([item("NOPE")], "'NOPE' runs the job 'NOPE', which does not exist."),
    ([item("LOAD", "A", after=["C"]), item("EXTRACT_EU", "B", after=["A"]), item("EXTRACT.US", "C", after=["B"])],
     "The prerequisites go round in a loop: 'A', which waits for 'C', which waits for 'B', which waits for 'A'."),
])
def test_a_workflow_that_cannot_work_is_refused_saying_why(client, jobs, items, message):
    response = save(client, workflow(items=items))
    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_a_workflow_cannot_use_itself_even_through_another(client, jobs):
    assert save(client, workflow("INNER", items=[item("LOAD")])).status_code == 201
    assert save(client, workflow("OUTER", items=[item("INNER")])).status_code == 201
    inner = client.get(f"{ROUTE}/INNER").json()
    response = save(client, {**as_submitted(inner), "items": as_submitted(inner)["items"] + [item("OUTER")]}, "INNER")
    assert response.status_code == 422
    assert "'OUTER' runs the workflow 'OUTER', which uses this one." in response.json()["detail"]
    response = save(client, workflow("SELF", items=[]))
    response = save(client, {**workflow("SELF", items=[item("SELF")])}, "SELF")
    assert "'SELF' runs this workflow itself." in response.json()["detail"]


def test_a_type_cannot_be_changed_or_mixed(client, jobs):
    assert "a job's type cannot be changed" in save(client, {"job_key": "LOAD", "job_type": "WORKFLOW"}, "LOAD").json()["detail"]
    mixed = workflow(steps=[{"title": "x", "step_type": "COPY_FILES"}])
    assert "A workflow is made of jobs, not steps." in save(client, mixed).json()["detail"]
    steps_with_items = {"job_key": "PLAIN", "items": [item("LOAD")]}
    assert "Only a workflow is made of other jobs." in save(client, steps_with_items).json()["detail"]


def test_a_job_used_by_a_workflow_cannot_be_deleted(client, jobs):
    save(client, workflow())
    response = client.delete(f"{ROUTE}/LOAD")
    assert response.status_code == 409
    assert response.json()["detail"] == ("Job 'LOAD' is used by the workflow 'MONTH_END', so it cannot be deleted. "
                                         "Take it out of it first.")


# ---------- Changing ----------

def test_changes_keep_each_items_identity_and_are_audited_in_words(client, jobs, db):
    saved = save(client, workflow()).json()["job"]
    payload = as_submitted(saved)
    first, second, load = payload["items"]
    second["name"] = "Extract_Europe"
    load["prerequisites"] = [{"target": "Extract_Europe", "test": "ENDED"}]
    load["join"] = "ALL"
    payload["items"] = [second, first, load]

    result = save(client, payload, "MONTH_END").json()

    assert [i["id"] for i in result["job"]["items"]] == [second["id"], first["id"], load["id"]]
    assert result["changes"] == [
        "Changed 'Extract_Europe': renamed from 'Extract_EU'.",
        "Changed 'LOAD': starts when all of its prerequisites hold.",
        "Changed what 'LOAD' waits for.",
        "Reordered the jobs."]
    db.commit()
    audit = db.query(Audit).filter(Audit.Action == "JOB_UPDATED").one()
    assert json.loads(audit.Details)["changes"] == result["changes"]


def test_a_job_left_out_is_removed_from_the_workflow(client, jobs, db):
    payload = as_submitted(save(client, workflow()).json()["job"])
    payload["items"] = payload["items"][:2]
    result = save(client, payload, "MONTH_END").json()
    assert result["changes"] == ["Removed 'LOAD'."]
    db.commit()
    assert db.query(WorkflowItem).count() == 2


# ---------- Success return codes ----------

def test_success_return_codes_are_saved_tidily_and_checked(client, jobs):
    result = save(client, {"job_key": "SIM", "success_return_codes": "0,4 ,8-10"}).json()
    assert result["job"]["success_return_codes"] == "0, 4, 8-10"
    response = save(client, {"job_key": "SIM2", "success_return_codes": "zero"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Success return codes: 'zero' in 'zero' is not a return code")

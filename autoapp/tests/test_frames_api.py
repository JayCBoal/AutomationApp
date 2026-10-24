"""
Workflows Phase 6, the store: a workflow holding jobs and workflows of its own (frames), saved in one Save
through /api/v1/jobs, with the checks run over the whole tree.
"""
import pytest

from core.models import Job, JobRun, WorkflowItem
from test_workflows_api import ROUTE, item, jobs, save, workflow, working_root      # noqa: F401  (fixtures)


def steps(title="Run"):
    return [{"title": title, "step_type": "COPY_FILES", "parameters": {"Source": "incoming/*.csv", "Dest": "outgoing"}}]


def job_in(name, **more):
    """An item that runs a job embedded in its workflow."""
    return {"name": name, "embedded": {"job_type": "STEPS", "steps": steps(name)}, **more}


def frame(name, items, **more):
    """An item that runs a workflow embedded in its workflow."""
    return {"name": name, "embedded": {"job_type": "WORKFLOW", "items": items}, **more}


def tree(**more):
    return {"job_key": "TOP", "job_type": "WORKFLOW", "items": [
        item("LOAD", "FX"),
        frame("Extract", [job_in("US"), job_in("EU")]),
        frame("Transform", [job_in("Enrich", prerequisites=[
            {"kind": "OTHER_JOB", "workflow": "TOP", "job": "FX"}])], prerequisites=[{"target": "Extract"}])], **more}


def keys(db):
    db.expire_all()
    return sorted(k for (k,) in db.query(Job.JobKey).filter(Job.JobKey.like("TOP%")))


def created(client, db, payload=None):
    response = save(client, payload or tree())
    assert response.status_code == 201, response.text
    return response.json()["job"]


# ---------- Saving a tree ----------

def test_a_workflow_is_saved_with_the_jobs_and_workflows_embedded_in_it(client, db, jobs):
    top = created(client, db)

    assert keys(db) == ["TOP", "TOP.Extract", "TOP.Extract.EU", "TOP.Extract.US", "TOP.Transform", "TOP.Transform.Enrich"]
    extract = next(i for i in top["items"] if i["name"] == "Extract")
    assert (extract["embedded"], extract["job_type"], extract["job_key"]) == (True, "WORKFLOW", "TOP.Extract")
    assert [i["name"] for i in extract["contents"]["items"]] == ["US", "EU"]
    assert extract["contents"]["owner"] == "TOP"
    assert next(i for i in top["items"] if i["name"] == "FX")["embedded"] is False


def test_embedded_jobs_are_hidden_from_the_lists_but_can_be_read(client, db, jobs):
    created(client, db)

    listed = [j["job_key"] for j in client.get(ROUTE).json()]

    assert "TOP" in listed and not [k for k in listed if k.startswith("TOP.")]
    assert client.get(f"{ROUTE}/TOP.Extract.US").json()["owner"] == "TOP.Extract"


def test_a_job_inside_a_frame_can_wait_for_a_job_outside_it_and_for_one_in_another_frame(client, db, jobs):
    payload = tree()
    payload["items"][2]["embedded"]["items"].append(job_in("Report", prerequisites=[
        {"kind": "OTHER_JOB", "workflow": "TOP.Extract", "job": "US"}]))

    top = created(client, db, payload)

    transform = next(i for i in top["items"] if i["name"] == "Transform")["contents"]["items"]
    enrich, report = transform
    assert [(p["kind"], p["workflow"], p["job"]) for p in enrich["prerequisites"]] == [("OTHER_JOB", "TOP", "FX")]
    assert [(p["kind"], p["workflow"], p["job"]) for p in report["prerequisites"]] == [("OTHER_JOB", "TOP.Extract", "US")]


def test_the_frame_as_a_whole_waits_like_any_item(client, db, jobs):
    top = created(client, db)

    transform = next(i for i in top["items"] if i["name"] == "Transform")

    assert [(p["kind"], p["target"], p["test"]) for p in transform["prerequisites"]] == [("JOB", "Extract", "SUCCESS")]


def test_one_save_covers_the_whole_tree_and_a_failed_check_anywhere_saves_nothing(client, db, jobs):
    payload = tree()
    payload["items"][1]["embedded"]["items"].append(job_in("Bad", prerequisites=[{"target": "Nowhere"}]))

    response = save(client, payload)

    assert response.status_code == 422 and "'Nowhere'" in response.json()["detail"]
    assert keys(db) == []


def test_changing_an_embedded_job_through_its_workflow_is_one_save(client, db, jobs):
    top = created(client, db)
    changed = {"job_key": "TOP", "job_type": "WORKFLOW", "items": [
        {"id": i["id"], "name": i["name"], "job_key": i["job_key"], "prerequisites": i["prerequisites"]}
        for i in top["items"]]}
    changed["items"][1] = {"id": top["items"][1]["id"], "name": "Extract", "prerequisites": [],
                           "embedded": {"job_type": "WORKFLOW", "description": "month end extract", "items": [
                               {"id": top["items"][1]["contents"]["items"][0]["id"], "name": "US",
                                "embedded": {"job_type": "STEPS", "steps": steps("US again")}}]}}

    response = client.put(f"{ROUTE}/TOP", json=changed)

    assert response.status_code == 200, response.text
    assert client.get(f"{ROUTE}/TOP.Extract").json()["description"] == "month end extract"
    assert client.get(f"{ROUTE}/TOP.Extract.US").json()["steps"][0]["title"] == "US again"
    assert client.get(f"{ROUTE}/TOP.Extract.EU").status_code == 404          # left out: gone


# ---------- Keys ----------

def test_an_embedded_key_follows_renames_of_the_item_and_of_its_owners_until_the_job_has_run(client, db, jobs):
    top = created(client, db)
    renamed = {"job_key": "TOP2", "job_type": "WORKFLOW", "items": [
        {"id": i["id"], "name": "Pull" if i["name"] == "Extract" else i["name"], "job_key": i["job_key"],
         "prerequisites": i["prerequisites"]} for i in top["items"]]}
    renamed["items"][2]["prerequisites"] = [{"target": "Pull"}]

    response = client.put(f"{ROUTE}/TOP", json=renamed)

    assert response.status_code == 200, response.text
    db.expire_all()
    assert sorted(k for (k,) in db.query(Job.JobKey).filter(Job.JobKey.like("TOP2%"))) == [
        "TOP2", "TOP2.Pull", "TOP2.Pull.EU", "TOP2.Pull.US", "TOP2.Transform", "TOP2.Transform.Enrich"]


def test_an_embedded_key_is_frozen_once_the_job_has_run(client, db, jobs):
    top = created(client, db)
    us = db.query(Job).filter(Job.JobKey == "TOP.Extract.US").one()
    db.add(JobRun(RunID="r1", JobKey="TOP.Extract.US", Job_MasterObject_id=us.MasterObject_id,
                  SchedulerInstanceID="r1", Status="SUCCESS"))
    db.commit()
    renamed = {"job_key": "TOP", "job_type": "WORKFLOW", "items": [
        {"id": i["id"], "name": "Pull" if i["name"] == "Extract" else i["name"], "job_key": i["job_key"],
         "prerequisites": i["prerequisites"]} for i in top["items"]]}
    renamed["items"][2]["prerequisites"] = [{"target": "Pull"}]

    assert client.put(f"{ROUTE}/TOP", json=renamed).status_code == 200

    db.expire_all()
    assert "TOP.Pull.US" not in keys(db) and "TOP.Extract.US" in keys(db)       # it has run: its folder holds files
    assert "TOP.Pull.EU" in keys(db)                                              # it has not: it follows


def test_a_key_too_long_for_the_limit_is_refused_naming_the_item(client, db, jobs):
    response = save(client, {"job_key": "T" * 300, "job_type": "WORKFLOW", "items": [job_in("N" * 60)]})

    assert response.status_code == 422 and "'" + "N" * 60 + "'" in response.json()["detail"] and "320" in response.json()["detail"]


# ---------- Belonging to the workflow ----------

def test_taking_an_embedded_item_out_deletes_its_job_and_everything_in_it(client, db, jobs):
    top = created(client, db)
    kept = [{"id": i["id"], "name": i["name"], "job_key": i["job_key"], "prerequisites": []}
            for i in top["items"] if i["name"] == "LOAD"]

    assert client.put(f"{ROUTE}/TOP", json={"job_key": "TOP", "job_type": "WORKFLOW", "items": kept}).status_code == 200

    assert keys(db) == ["TOP"]


def test_deleting_the_workflow_deletes_what_is_embedded_in_it(client, db, jobs):
    created(client, db)

    assert client.delete(f"{ROUTE}/TOP").status_code == 204

    assert keys(db) == []
    assert db.query(WorkflowItem).count() == 0


def test_an_embedded_job_of_steps_can_be_edited_on_its_own_page_but_not_renamed_or_deleted(client, db, jobs):
    created(client, db)

    edited = client.put(f"{ROUTE}/TOP.Extract.US", json={"job_key": "TOP.Extract.US", "description": "US extract", "steps": steps("Again")})
    renamed = client.put(f"{ROUTE}/TOP.Extract.US", json={"job_key": "ELSEWHERE", "steps": steps()})
    deleted = client.delete(f"{ROUTE}/TOP.Extract.US")

    assert edited.status_code == 200 and edited.json()["job"]["description"] == "US extract"
    assert renamed.status_code == 409 and "rename its item in that workflow" in renamed.json()["detail"]
    assert deleted.status_code == 409 and "embedded in the workflow 'TOP.Extract'" in deleted.json()["detail"]


def test_a_workflow_embedded_in_another_is_changed_only_from_the_workflow_it_is_in(client, db, jobs):
    created(client, db)

    changed = client.put(f"{ROUTE}/TOP.Extract", json={"job_key": "TOP.Extract", "job_type": "WORKFLOW", "items": []})

    assert changed.status_code == 409 and "Change it from that workflow's page" in changed.json()["detail"]


def test_another_workflow_cannot_use_an_embedded_job(client, db, jobs):
    created(client, db)

    response = save(client, workflow("OTHER", [item("TOP.Extract.US", "Borrowed")]))

    assert response.status_code == 422 and "embedded in the workflow" in response.json()["detail"]


def test_a_frame_cannot_be_taken_out_while_a_workflow_elsewhere_waits_for_a_job_in_it(client, db, jobs):
    top = created(client, db)
    other = workflow("OTHER", [item("LOAD", "Late", after=[{"kind": "OTHER_JOB", "workflow": "TOP.Extract", "job": "US"}])])
    assert save(client, other).status_code == 201
    kept = [{"id": i["id"], "name": i["name"], "job_key": i["job_key"], "prerequisites": []}
            for i in top["items"] if i["name"] == "LOAD"]

    response = client.put(f"{ROUTE}/TOP", json={"job_key": "TOP", "job_type": "WORKFLOW", "items": kept})

    assert response.status_code == 422 and "'Late' in 'OTHER'" in response.json()["detail"]
    assert "TOP.Extract.US" in keys(db)


# ---------- Loops through frames ----------

def test_a_job_cannot_wait_for_something_that_waits_for_the_frame_it_is_in(client, db, jobs):
    payload = tree()
    payload["items"][0]["prerequisites"] = [{"target": "Transform"}]         # FX waits for Transform, whose Enrich waits for FX

    response = save(client, payload)

    assert response.status_code == 422 and "loop" in response.json()["detail"]
    assert keys(db) == []


# ---------- Conditions reach inside a frame by a path ----------

def test_a_condition_can_name_a_job_inside_a_frame_by_its_path(client, db, jobs):
    payload = tree()
    payload["items"].append(item("LOAD", "Report", join="CUSTOM", rule="%{Transform.Enrich.Status} = 'SUCCESS'"))

    top = created(client, db, payload)

    report = next(i for i in top["items"] if i["name"] == "Report")
    assert report["rule"] == "%{Transform.Enrich.Status} = 'SUCCESS'"
    assert [p["target"] for p in report["prerequisites"]] == ["Transform"]         # it waits for the frame to end


def test_a_path_to_a_job_that_is_not_in_the_frame_says_so(client, db, jobs):
    payload = tree()
    payload["items"].append(item("LOAD", "Report", join="CUSTOM", rule="%{Transform.Nothing.Status} = 'SUCCESS'"))

    response = save(client, payload)

    assert response.status_code == 422 and "nothing inside 'Transform' is named 'Nothing'" in response.json()["detail"]


# ---------- Embedded and shared, both ways ----------

def test_an_embedded_copy_of_a_shared_job_has_its_steps_and_variables_and_later_changes_do_not_reach_it(client, db, jobs, seed):
    seed.set_vars(db.query(Job).filter(Job.JobKey == "LOAD").one(), Region="EU")
    db.query(Job).filter(Job.JobKey == "LOAD").one().variables[0].IsSecret = True
    db.commit()
    assert save(client, workflow("USER", [item("LOAD", "Load")])).status_code == 201

    response = client.post(f"{ROUTE}/USER/items/Load/embedded-copy")

    assert response.status_code == 200, response.text
    load = response.json()["job"]["items"][0]
    assert (load["embedded"], load["job_key"]) == (True, "USER.Load")
    assert load["contents"]["steps"][0]["parameters"]["Source"] == "incoming/*.csv"
    assert [(v["name"], v["secret"], v["value"]) for v in load["contents"]["variables"]] == [("Region", True, None)]
    db.expire_all()
    assert db.query(Job).filter(Job.JobKey == "USER.Load").one().variables[0].VarValue == "EU"      # the value came across
    original = client.get(f"{ROUTE}/LOAD").json()
    assert original["owner"] is None and original["used_in"] == []                                    # the original is untouched


def test_an_embedded_copy_of_a_shared_workflow_keeps_what_is_inside_pointing_at_the_copy(client, db, jobs):
    assert save(client, workflow("SHARED", [item("LOAD", "A"), item("LOAD", "B", after=["A"])])).status_code == 201
    assert save(client, workflow("USER", [item("SHARED", "Part")])).status_code == 201

    response = client.post(f"{ROUTE}/USER/items/Part/embedded-copy")

    assert response.status_code == 200, response.text
    part = response.json()["job"]["items"][0]["contents"]
    assert [i["name"] for i in part["items"]] == ["A", "B"]
    assert part["items"][1]["prerequisites"][0]["target"] == "A"
    assert client.get(f"{ROUTE}/SHARED").json()["used_in"] == []        # the item runs the copy now; the original is untouched


def test_making_an_embedded_job_shared_keeps_it_in_its_item_and_lists_it(client, db, jobs):
    created(client, db)

    response = client.post(f"{ROUTE}/TOP.Extract/make-shared", json={"job_key": "EXTRACT_ALL"})

    assert response.status_code == 200, response.text
    db.expire_all()
    assert "EXTRACT_ALL" in [j["job_key"] for j in client.get(ROUTE).json()]
    assert client.get(f"{ROUTE}/EXTRACT_ALL").json()["owner"] is None
    assert "EXTRACT_ALL.US" in keys(db) or db.query(Job).filter(Job.JobKey == "EXTRACT_ALL.US").count() == 1
    top = client.get(f"{ROUTE}/TOP").json()
    extract = next(i for i in top["items"] if i["name"] == "Extract")
    assert (extract["embedded"], extract["job_key"]) == (False, "EXTRACT_ALL")


def test_making_a_job_shared_under_a_key_that_is_taken_is_refused(client, db, jobs):
    created(client, db)

    response = client.post(f"{ROUTE}/TOP.Extract.US/make-shared", json={"job_key": "LOAD"})

    assert response.status_code == 409 and "'LOAD' already exists" in response.json()["detail"]

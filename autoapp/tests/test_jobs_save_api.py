"""Creating, changing and deleting jobs over HTTP: POST, PUT and DELETE on /api/v1/jobs."""
import json

import pytest

from app.models import Audit, Job, JobRun, JobStep, JobStepParameter, Operation

ROUTE = "/api/v1/jobs"


@pytest.fixture(autouse=True)
def working_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))


def step(title, **parameters):
    return {"title": title, "step_type": "COPY_FILES", "parameters": parameters}


def new_job(key="DEV-LOAD", **fields):
    return {
        "job_key": key, "description": "Collects and delivers",
        "steps": [step("Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming"),
                  step("Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")],
        **fields,
    }


@pytest.fixture
def created(client, db, endpoints):
    """A job created through the API, as returned by it."""
    db.commit()
    response = client.post(ROUTE, json=new_job())
    assert response.status_code == 201, response.text
    return response.json()["job"]


def as_submitted(job):
    """A job as the API returned it, in the shape it is sent back to save."""
    return {
        "job_key": job["job_key"], "description": job["description"], "active": job["active"],
        "steps": [{"id": s["id"], "title": s["title"], "active": s["active"], "step_type": s["step_type"],
                   "parameters": dict(s["parameters"])} for s in job["steps"]],
    }


def audits(db):
    db.commit()
    return [(a.Action, a.PerformedBy, json.loads(a.Details)) for a in db.query(Audit).order_by(Audit.id)]


# --- Creating ---------------------------------------------------------------------------------

def test_a_job_is_created_with_its_steps_in_the_order_given(client, db, endpoints):
    db.commit()

    response = client.post(ROUTE, json=new_job())

    assert response.status_code == 201
    result = response.json()
    assert (result["valid"], result["problems"]) == (True, [])
    job = result["job"]
    assert (job["job_key"], job["description"], job["active"], job["created_by"]) == (
        "DEV-LOAD", "Collects and delivers", True, "web interface")
    assert [(s["order"], s["title"], s["active"]) for s in job["steps"]] == [(1, "Collect", True), (2, "Deliver", True)]
    assert job["steps"][1]["parameters"] == {"Source": "incoming/*.csv", "DestEndpoint": "BILLING_INBOX", "Move": "True"}
    assert client.get(f"{ROUTE}/DEV-LOAD").json() == job              # and it is really stored


def test_a_created_job_runs(client, db, endpoints, run_runner, tmp_path):
    db.commit()
    client.post(ROUTE, json=new_job())

    result = run_runner("DEV-LOAD")

    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in (tmp_path / "app_inbox").iterdir()) == ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]


def test_blank_parameter_values_are_not_stored(client, db, endpoints):
    db.commit()
    job = new_job()
    job["steps"][0]["parameters"].update({"Move": "", "LogLevel": None, "Checksum": "   "})

    saved = client.post(ROUTE, json=job).json()["job"]

    assert saved["steps"][0]["parameters"] == {"SourceEndpoint": "LEGAL_EXTRACTS", "Dest": "incoming"}


def test_a_job_with_problems_is_still_saved_and_the_problems_are_returned(client, db, endpoints):
    db.commit()
    job = new_job()
    job["steps"][1]["parameters"]["DestEndpoint"] = "NO_SUCH_ENDPOINT"

    response = client.post(ROUTE, json=job)

    assert response.status_code == 201
    result = response.json()
    assert result["valid"] is False
    assert len(result["problems"]) == 1 and "NO_SUCH_ENDPOINT" in result["problems"][0]
    assert client.get(f"{ROUTE}/DEV-LOAD").status_code == 200


def test_a_job_can_be_created_with_no_steps_or_disabled(client):
    response = client.post(ROUTE, json={"job_key": "DEV-EMPTY", "active": False})

    job = response.json()["job"]
    assert response.status_code == 201
    assert (job["active"], job["steps"], job["description"]) == (False, [], None)


def test_a_key_that_is_already_taken_is_refused(client, created):
    response = client.post(ROUTE, json=new_job())

    assert response.status_code == 409
    assert response.json()["detail"] == "A job with JobKey 'DEV-LOAD' already exists."


@pytest.mark.parametrize("key", ["", "has space", "slash/inside", "-starts-with-dash", "../escape"])
def test_a_key_that_cannot_name_a_folder_is_refused(client, db, key):
    response = client.post(ROUTE, json={"job_key": key})

    assert response.status_code == 422
    assert db.query(Job).count() == 0


def test_an_unknown_step_type_is_refused_and_nothing_is_saved(client, db):
    job = new_job()
    job["steps"][1]["step_type"] = "NO_SUCH_TYPE"

    response = client.post(ROUTE, json=job)

    assert response.status_code == 422
    assert response.json()["detail"] == "Step 2 ('Deliver'): there is no step type 'NO_SUCH_TYPE'."
    assert db.query(Job).count() == 0 and db.query(JobStep).count() == 0


# --- Changing ---------------------------------------------------------------------------------

def test_saving_a_job_unchanged_changes_nothing(client, db, created):
    response = client.put(f"{ROUTE}/DEV-LOAD", json=as_submitted(created))

    assert response.status_code == 200
    result = response.json()
    assert result["changes"] == []
    assert result["job"] == created                       # including "modified": still never modified
    assert [a[0] for a in audits(db)] == ["JOB_CREATED"]


def test_job_fields_are_changed(client, db, created):
    submitted = as_submitted(created)
    submitted.update(description="A new description", active=False)

    result = client.put(f"{ROUTE}/DEV-LOAD", json=submitted).json()

    job = result["job"]
    assert (job["description"], job["active"]) == ("A new description", False)
    assert (job["modified"] is not None, job["modified_by"]) == (True, "web interface")
    assert result["changes"] == ["Changed the description.", "Disabled the job."]
    assert result["problems"] == ["Job 'DEV-LOAD' is disabled."]


def test_a_steps_title_parameters_and_enabled_flag_are_changed_in_place(client, db, created):
    submitted = as_submitted(created)
    deliver = submitted["steps"][1]
    deliver.update(title="Deliver to billing", active=False)
    deliver["parameters"].update({"Move": "", "Checksum": "True", "Source": "incoming/*.txt"})

    result = client.put(f"{ROUTE}/DEV-LOAD", json=submitted).json()

    saved = result["job"]["steps"][1]
    assert saved["id"] == created["steps"][1]["id"]            # the same step, changed
    assert (saved["title"], saved["active"]) == ("Deliver to billing", False)
    assert saved["parameters"] == {"Source": "incoming/*.txt", "DestEndpoint": "BILLING_INBOX", "Checksum": "True"}
    assert result["changes"] == ["Changed step 2 ('Deliver to billing'): title, disabled, parameters."]
    assert result["job"]["steps"][0] == created["steps"][0]    # the other step is untouched


def test_a_location_can_be_switched_between_endpoint_and_path(client, db, created):
    submitted = as_submitted(created)
    submitted["steps"][0]["parameters"] = {"Source": "staged/*.csv", "Dest": "incoming"}

    saved = client.put(f"{ROUTE}/DEV-LOAD", json=submitted).json()["job"]

    assert saved["steps"][0]["parameters"] == {"Source": "staged/*.csv", "Dest": "incoming"}
    assert db.query(JobStepParameter).filter(JobStepParameter.ParamName == "SourceEndpoint").count() == 0


def test_steps_are_added_removed_and_reordered_in_one_save(client, db, created):
    collect, deliver = as_submitted(created)["steps"]
    archive = step("Archive", Source="incoming/*.csv", Dest="archive")
    submitted = {**as_submitted(created), "steps": [deliver, archive]}        # collect removed, archive added

    result = client.put(f"{ROUTE}/DEV-LOAD", json=submitted).json()

    steps = result["job"]["steps"]
    assert [(s["order"], s["title"]) for s in steps] == [(1, "Deliver"), (2, "Archive")]
    assert steps[0]["id"] == deliver["id"] and steps[1]["id"] not in (collect["id"], deliver["id"])
    assert result["changes"] == ["Added step 2 ('Archive').", "Removed step 'Collect'."]
    assert db.query(JobStep).count() == 2
    assert db.query(JobStepParameter).filter(JobStepParameter.ParamName == "SourceEndpoint").count() == 0


def test_reordering_alone_is_recorded_and_keeps_each_steps_identity(client, db, created):
    collect, deliver = as_submitted(created)["steps"]

    result = client.put(f"{ROUTE}/DEV-LOAD", json={**as_submitted(created), "steps": [deliver, collect]}).json()

    assert [(s["order"], s["id"]) for s in result["job"]["steps"]] == [(1, deliver["id"]), (2, collect["id"])]
    assert result["changes"] == ["Reordered the steps."]


def test_a_changed_step_keeps_the_operations_it_recorded(client, db, created, run_runner, load_spool):
    """Operations point at the step that made them. Editing the step must not break that."""
    run_runner("DEV-LOAD")
    load_spool()
    step_id = created["steps"][0]["id"]
    assert db.query(Operation).filter(Operation.JobStep_id == step_id).count() == 2

    submitted = as_submitted(created)
    submitted["steps"][0]["title"] = "Collect extracts"
    client.put(f"{ROUTE}/DEV-LOAD", json={**submitted, "steps": list(reversed(submitted["steps"]))})

    db.commit()
    assert db.query(Operation).filter(Operation.JobStep_id == step_id).count() == 2


def test_removing_a_step_keeps_its_operations_without_the_link(client, db, created, run_runner, load_spool):
    run_runner("DEV-LOAD")
    load_spool()
    submitted = as_submitted(created)

    client.put(f"{ROUTE}/DEV-LOAD", json={**submitted, "steps": submitted["steps"][1:]})

    db.commit()
    assert db.query(Operation).count() == 4                                   # history is kept
    assert db.query(Operation).filter(Operation.JobStep_id.is_(None)).count() == 2
    assert {op.StepOrder for op in db.query(Operation).filter(Operation.JobStep_id.is_(None))} == {1}


def test_a_job_is_renamed_by_sending_a_new_key(client, db, created, run_runner, load_spool):
    run_runner("DEV-LOAD", "88421")
    load_spool()

    response = client.put(f"{ROUTE}/DEV-LOAD", json={**as_submitted(created), "job_key": "DEV-LOAD-RENAMED"})

    assert response.status_code == 200
    assert response.json()["changes"] == ["Renamed from 'DEV-LOAD' to 'DEV-LOAD-RENAMED'."]
    assert client.get(f"{ROUTE}/DEV-LOAD").status_code == 404
    assert client.get(f"{ROUTE}/DEV-LOAD-RENAMED").json()["steps"] == created["steps"]
    db.commit()
    run = db.query(JobRun).one()                     # the run keeps the name it ran under, and its link to the job
    assert run.JobKey == "DEV-LOAD"
    assert run.job.JobKey == "DEV-LOAD-RENAMED"


def test_renaming_to_a_key_that_is_taken_is_refused(client, db, created):
    client.post(ROUTE, json={"job_key": "DEV-OTHER"})

    response = client.put(f"{ROUTE}/DEV-LOAD", json={**as_submitted(created), "job_key": "DEV-OTHER"})

    assert response.status_code == 409
    assert client.get(f"{ROUTE}/DEV-LOAD").json() == created


def test_renaming_to_an_unusable_key_is_refused_and_nothing_changes(client, db, created):
    submitted = {**as_submitted(created), "job_key": "has space", "description": "changed too"}

    response = client.put(f"{ROUTE}/DEV-LOAD", json=submitted)

    assert response.status_code == 422
    assert "Invalid JobKey 'has space'" in response.json()["detail"]
    assert client.get(f"{ROUTE}/DEV-LOAD").json() == created


def test_a_step_belonging_to_another_job_is_refused(client, db, created):
    other = client.post(ROUTE, json=new_job("DEV-OTHER")).json()["job"]
    submitted = as_submitted(created)
    submitted["steps"][0]["id"] = other["steps"][0]["id"]

    response = client.put(f"{ROUTE}/DEV-LOAD", json=submitted)

    assert response.status_code == 422
    assert "does not belong to job 'DEV-LOAD'" in response.json()["detail"]
    assert client.get(f"{ROUTE}/DEV-LOAD").json() == created
    assert client.get(f"{ROUTE}/DEV-OTHER").json() == other


def test_the_same_step_twice_is_refused(client, created):
    submitted = as_submitted(created)
    submitted["steps"].append(dict(submitted["steps"][0]))

    assert client.put(f"{ROUTE}/DEV-LOAD", json=submitted).status_code == 422


def test_saving_an_unknown_job_is_404(client):
    assert client.put(f"{ROUTE}/NO_SUCH_JOB", json=new_job("NO_SUCH_JOB")).status_code == 404


# --- Deleting ---------------------------------------------------------------------------------

def test_a_job_that_has_never_run_is_deleted_with_its_steps(client, db, created):
    response = client.delete(f"{ROUTE}/DEV-LOAD")

    assert response.status_code == 204
    assert client.get(f"{ROUTE}/DEV-LOAD").status_code == 404
    db.commit()
    assert (db.query(Job).count(), db.query(JobStep).count(), db.query(JobStepParameter).count()) == (0, 0, 0)


def test_a_job_with_run_history_is_not_deleted(client, db, created, run_runner, load_spool):
    run_runner("DEV-LOAD")
    load_spool()

    response = client.delete(f"{ROUTE}/DEV-LOAD")

    assert response.status_code == 409
    assert response.json()["detail"].startswith("Job 'DEV-LOAD' has run 1 time, so it cannot be deleted. Disable it instead")
    assert client.get(f"{ROUTE}/DEV-LOAD").json() == created


def test_deleting_an_unknown_job_is_404(client):
    assert client.delete(f"{ROUTE}/NO_SUCH_JOB").status_code == 404


# --- The audit log ----------------------------------------------------------------------------

def test_every_change_is_recorded_with_what_was_done(client, db, created):
    submitted = as_submitted(created)
    submitted["description"] = "Edited"
    client.put(f"{ROUTE}/DEV-LOAD", json=submitted)
    client.put(f"{ROUTE}/DEV-LOAD", json=submitted)                 # no change: nothing to record
    client.delete(f"{ROUTE}/DEV-LOAD")

    assert audits(db) == [
        ("JOB_CREATED", "web interface", {"job_key": "DEV-LOAD", "changes": ["Created job 'DEV-LOAD'."]}),
        ("JOB_UPDATED", "web interface", {"job_key": "DEV-LOAD", "changes": ["Changed the description."]}),
        ("JOB_DELETED", "web interface", {"job_key": "DEV-LOAD", "changes": ["Deleted job 'DEV-LOAD'."]}),
    ]


def test_a_refused_save_records_nothing(client, db, created):
    client.put(f"{ROUTE}/DEV-LOAD", json={**as_submitted(created), "job_key": "has space"})
    client.post(ROUTE, json=new_job())                              # key taken

    assert [a[0] for a in audits(db)] == ["JOB_CREATED"]

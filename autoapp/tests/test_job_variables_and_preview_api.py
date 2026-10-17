"""
A job's variables, and previewing a job without saving it:
the variables part of /api/v1/jobs, and POST /api/v1/jobs/preview.
"""
import json

import pytest

from app.models import Audit, Job, Variable

ROUTE = "/api/v1/jobs"


@pytest.fixture(autouse=True)
def working_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))


def job_with(variables=None, steps=None, key="DEV-LOAD", **fields):
    body = {"job_key": key, "steps": steps if steps is not None else [
        {"title": "Collect", "step_type": "COPY_FILES", "parameters": {"SourceEndpoint": "LEGAL_EXTRACTS", "Dest": "incoming"}}],
        **fields}
    if variables is not None:
        body["variables"] = variables
    return body


def var(name, value="", secret=False, description=None):
    return {"name": name, "value": value, "secret": secret, "description": description}


@pytest.fixture
def created(client, db, endpoints):
    db.commit()
    response = client.post(ROUTE, json=job_with([var("Folder", "staging", description="Where files wait"),
                                                 var("ApiToken", "s3cr3t-t0ken", secret=True)]))
    assert response.status_code == 201, response.text
    return response.json()["job"]


def resubmit(job, **changes):
    return {"job_key": job["job_key"], "description": job["description"], "active": job["active"],
            "steps": [{"id": s["id"], "title": s["title"], "active": s["active"], "step_type": s["step_type"],
                       "parameters": dict(s["parameters"])} for s in job["steps"]],
            "variables": [dict(v) for v in job["variables"]], **changes}


# --- Variables --------------------------------------------------------------------------------

def test_a_jobs_variables_are_saved_and_returned_in_name_order(client, created):
    assert created["variables"] == [
        {"name": "ApiToken", "value": None, "secret": True, "description": None},          # a secret is never sent back
        {"name": "Folder", "value": "staging", "secret": False, "description": "Where files wait"},
    ]
    assert client.get(f"{ROUTE}/DEV-LOAD").json()["variables"] == created["variables"]


def test_a_secret_value_is_stored_but_never_returned(client, db, created):
    assert db.query(Variable).filter(Variable.VarName == "ApiToken").one().VarValue == "s3cr3t-t0ken"
    assert "s3cr3t-t0ken" not in client.get(f"{ROUTE}/DEV-LOAD").text
    assert "s3cr3t-t0ken" not in json.dumps(created)


def test_resubmitting_a_job_as_it_was_returned_keeps_its_secret(client, db, created):
    """The page never has the secret's value, so sending it back blank must mean "leave it"."""
    result = client.put(f"{ROUTE}/DEV-LOAD", json=resubmit(created)).json()

    assert result["changes"] == []
    assert db.query(Variable).filter(Variable.VarName == "ApiToken").one().VarValue == "s3cr3t-t0ken"


def test_a_secret_is_replaced_by_sending_a_new_value(client, db, created):
    submitted = resubmit(created)
    submitted["variables"][0]["value"] = "n3w-t0ken"

    result = client.put(f"{ROUTE}/DEV-LOAD", json=submitted).json()

    assert result["changes"] == ["Changed variable ApiToken."]
    db.commit()
    assert db.query(Variable).filter(Variable.VarName == "ApiToken").one().VarValue == "n3w-t0ken"


def test_variables_are_added_changed_and_removed_in_one_save(client, db, created):
    submitted = resubmit(created)
    submitted["variables"] = [var("Folder", "holding", description="Where files wait"), var("Pattern", "*.csv")]

    result = client.put(f"{ROUTE}/DEV-LOAD", json=submitted).json()

    assert result["job"]["variables"] == [
        {"name": "Folder", "value": "holding", "secret": False, "description": "Where files wait"},
        {"name": "Pattern", "value": "*.csv", "secret": False, "description": None},
    ]
    assert result["changes"] == ["Added variable Pattern.", "Changed variable Folder.", "Removed variable ApiToken."]


def test_the_audit_log_names_the_variables_changed_but_never_their_values(client, db, created):
    submitted = resubmit(created)
    submitted["variables"][0]["value"] = "an0ther-s3cret"
    submitted["variables"][1]["value"] = "holding"
    client.put(f"{ROUTE}/DEV-LOAD", json=submitted)

    db.commit()
    recorded = " ".join(a.Details for a in db.query(Audit))
    assert "Changed variables ApiToken, Folder." in recorded
    assert "an0ther-s3cret" not in recorded and "s3cr3t-t0ken" not in recorded and "holding" not in recorded


def test_leaving_variables_out_of_a_save_keeps_them(client, created):
    submitted = resubmit(created, description="Edited")
    del submitted["variables"]

    result = client.put(f"{ROUTE}/DEV-LOAD", json=submitted).json()

    assert result["changes"] == ["Changed the description."]
    assert [v["name"] for v in result["job"]["variables"]] == ["ApiToken", "Folder"]


def test_a_variable_set_on_the_job_is_used_when_the_job_runs(client, db, endpoints, run_runner, tmp_path):
    db.commit()
    steps = [{"title": "Collect", "step_type": "COPY_FILES",
              "parameters": {"SourceEndpoint": "LEGAL_EXTRACTS", "Dest": "${Folder}/in"}}]
    client.post(ROUTE, json=job_with([var("Folder", "staging")], steps))

    assert run_runner("DEV-LOAD").returncode == 0
    assert sorted(p.name for p in (tmp_path / "work" / "DEV-LOAD" / "staging" / "in").iterdir()) == [
        "Legal_Batch_1.csv", "Legal_Batch_2.csv"]


@pytest.mark.parametrize("name", ["", "has space", "1starts_with_digit", "dotted.name", "SYS:THING", "dash-ed"])
def test_a_variable_name_that_could_not_be_written_as_a_placeholder_is_refused(client, db, endpoints, name):
    db.commit()

    response = client.post(ROUTE, json=job_with([var(name, "x")]))

    assert response.status_code == 422
    assert "Invalid variable name" in response.json()["detail"]
    assert db.query(Job).count() == 0


def test_the_same_variable_twice_is_refused(client, db, endpoints):
    db.commit()

    response = client.post(ROUTE, json=job_with([var("Folder", "a"), var("Folder", "b")]))

    assert response.status_code == 422
    assert response.json()["detail"] == "The variable 'Folder' is listed more than once."


def test_variable_names_that_differ_only_by_case_are_two_variables(client, db, endpoints):
    db.commit()

    job = client.post(ROUTE, json=job_with([var("folder", "lower"), var("Folder", "upper")])).json()["job"]

    assert {v["name"]: v["value"] for v in job["variables"]} == {"folder": "lower", "Folder": "upper"}


# --- Preview ----------------------------------------------------------------------------------

def preview(client, body, existing_key=None):
    response = client.post(f"{ROUTE}/preview", json=body, params={"existing_key": existing_key} if existing_key else {})
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_shows_what_each_parameter_resolves_to(client, db, endpoints, outbox, tmp_path):
    db.commit()
    steps = [
        {"title": "Collect", "step_type": "COPY_FILES", "parameters": {"SourceEndpoint": "LEGAL_EXTRACTS", "Dest": "${Folder}/in"}},
        {"title": "Deliver", "step_type": "COPY_FILES",
         "parameters": {"Source": "${Folder}/in/*.csv", "DestEndpoint": "BILLING_INBOX", "Move": "True",
                        "RenameMask": "${FILE:STEM}_${Tag}${FILE:EXT}"}},
    ]

    result = preview(client, job_with([var("Folder", "staging"), var("Tag", "v2")], steps))

    work = tmp_path / "work" / "DEV-LOAD"
    collect, deliver = result["steps"]
    assert (result["valid"], result["problems"]) == (True, [])
    assert collect["Source"] == {"resolved": f"{outbox}/Legal_Batch_*.csv", "error": None, "warnings": []}      # the endpoint's folder and pattern
    assert collect["Dest"] == {"resolved": str(work / "staging" / "in"), "error": None, "warnings": []}         # relative to the working folder
    assert deliver["Source"]["resolved"] == str(work / "staging" / "in" / "*.csv")
    assert deliver["Dest"]["resolved"] == str(tmp_path / "app_inbox")
    assert deliver["RenameMask"]["resolved"] == "${FILE:STEM}_v2${FILE:EXT}"                    # per-file parts still to come
    assert deliver["Move"] == {"resolved": "True", "error": None, "warnings": []}


def test_preview_reports_each_fields_own_problem_and_carries_on(client, db, endpoints):
    db.commit()
    steps = [{"title": "Collect", "step_type": "COPY_FILES", "parameters": {
        "SourceEndpoint": "NO_SUCH_ENDPOINT", "Dest": "${Missing}/in", "RenameMask": "${FILE:BASENAME}",
        "Move": "${DATE:YYYY}", "Checksum": "True"}}]

    result = preview(client, job_with([], steps))

    [fields] = result["steps"]
    assert result["valid"] is False and len(result["problems"]) == 1
    assert "NO_SUCH_ENDPOINT" in fields["Source"]["error"] and fields["Source"]["resolved"] is None
    assert "${Missing}" in fields["Dest"]["error"]
    assert "${FILE:BASENAME} is not a file placeholder" in fields["RenameMask"]["error"]
    assert "'Y' in the date mask 'YYYY' is not understood" in fields["Move"]["error"]
    assert fields["Checksum"] == {"resolved": "True", "error": None, "warnings": []}             # the sound field is unaffected


def test_preview_of_a_path_outside_the_working_folder_says_so(client, db, endpoints):
    db.commit()
    steps = [{"title": "Collect", "step_type": "COPY_FILES", "parameters": {"Source": "/etc/*.conf", "Dest": "in"}}]

    fields = preview(client, job_with([], steps))["steps"][0]

    assert "outside the job's working folder" in fields["Source"]["error"]


def test_preview_saves_nothing(client, db, created):
    before = client.get(f"{ROUTE}/DEV-LOAD").json()
    submitted = resubmit(created, description="Not saved", job_key="DEV-RENAMED-IN-PREVIEW")
    submitted["variables"].append(var("Extra", "x"))
    submitted["steps"].append({"title": "Extra", "step_type": "COPY_FILES", "parameters": {"Source": "a", "Dest": "b"}})

    preview(client, submitted, existing_key="DEV-LOAD")

    assert client.get(f"{ROUTE}/DEV-LOAD").json() == before
    assert client.get(f"{ROUTE}/DEV-RENAMED-IN-PREVIEW").status_code == 404
    db.commit()
    assert [a.Action for a in db.query(Audit)] == ["JOB_CREATED"]


def test_preview_of_a_job_not_yet_saved_or_even_named(client, db, endpoints, tmp_path):
    db.commit()

    unnamed = preview(client, job_with([var("Folder", "staging")], key=""))
    named = preview(client, job_with([var("Folder", "staging")], key="DEV-NEW"))

    assert unnamed["steps"][0]["Dest"]["resolved"] == str(tmp_path / "work" / "UNNAMED-JOB" / "incoming")
    assert named["steps"][0]["Dest"]["resolved"] == str(tmp_path / "work" / "DEV-NEW" / "incoming")
    assert db.query(Job).count() == 0


def test_preview_uses_the_variables_as_edited_not_as_saved(client, db, created, tmp_path):
    submitted = resubmit(created)
    submitted["steps"][0]["parameters"]["Dest"] = "${Folder}/in"
    submitted["variables"][1]["value"] = "edited"

    fields = preview(client, submitted, existing_key="DEV-LOAD")["steps"][0]

    assert fields["Dest"]["resolved"] == str(tmp_path / "work" / "DEV-LOAD" / "edited" / "in")


def test_preview_never_shows_a_secrets_value(client, db, created, tmp_path):
    submitted = resubmit(created)
    submitted["steps"][0]["parameters"]["Dest"] = "in_${ApiToken}"

    result = preview(client, submitted, existing_key="DEV-LOAD")

    assert "s3cr3t-t0ken" not in json.dumps(result)
    assert result["steps"][0]["Dest"]["resolved"] == str(tmp_path / "work" / "DEV-LOAD" / "in_********")


def test_preview_lists_what_would_stop_the_job_running(client, db, created):
    submitted = resubmit(created, active=False)
    submitted["steps"][0]["parameters"]["SourceEndpoint"] = "NO_SUCH_ENDPOINT"

    result = preview(client, submitted, existing_key="DEV-LOAD")

    assert result["valid"] is False
    assert result["problems"][0] == "Job 'DEV-LOAD' is disabled."
    assert "NO_SUCH_ENDPOINT" in result["problems"][1]


def test_preview_of_something_that_could_not_be_saved_says_why(client, db, created):
    client.post(ROUTE, json={"job_key": "DEV-OTHER"})

    renamed = client.post(f"{ROUTE}/preview", json=resubmit(created, job_key="DEV-OTHER"), params={"existing_key": "DEV-LOAD"})
    bad_variable = client.post(f"{ROUTE}/preview", json=resubmit(created, variables=[var("bad name")]),
                               params={"existing_key": "DEV-LOAD"})

    assert (renamed.status_code, renamed.json()["detail"]) == (409, "A job with JobKey 'DEV-OTHER' already exists.")
    assert bad_variable.status_code == 422 and "Invalid variable name 'bad name'" in bad_variable.json()["detail"]

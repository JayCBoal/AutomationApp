"""
The step catalog: what parameters a step type takes, checking a step against
that, and publishing it for the job editor.
"""
import json

import pytest

from app.catalog import sync_catalog
from app.models import JobStepParameter, StepDefinition, StepType
from engine.handlers import HANDLERS
from engine.handlers.file_handler import FileOpHandler
from engine.step_catalog import (
    BOOLEAN, CHOICE, DEST, INTEGER, LOCATION, SOURCE, Param, check_parameters, normalize_parameters
)

# A made-up step type that uses every kind of parameter
PARAMS = (
    Param("Source", LOCATION, location_role=SOURCE, required=True),
    Param("Dest", LOCATION, location_role=DEST),
    Param("Query", required=True),
    Param("Commit", BOOLEAN, default="False"),
    Param("Retries", INTEGER, default="3"),
    Param("Mode", CHOICE, choices=("FAST", "SAFE")),
)
GOOD = {"SourceEndpoint": "LEGAL_EXTRACTS", "Query": "SELECT 1"}


# --- Checking a step as stored in the job --------------------------------------------------------

def test_a_step_with_only_what_is_required_has_no_problems():
    assert check_parameters(PARAMS, GOOD) == []


def test_a_location_can_be_given_as_a_path_or_as_an_endpoint():
    assert check_parameters(PARAMS, {"Source": "incoming/*.csv", "Query": "x"}) == []
    assert check_parameters(PARAMS, {"SourceEndpoint": "LEGAL_EXTRACTS", "Query": "x"}) == []


def test_a_location_given_both_ways_is_a_problem():
    problems = check_parameters(PARAMS, {**GOOD, "Source": "incoming/*.csv"})

    assert problems == ["Set either 'Source' or 'SourceEndpoint', not both."]


def test_a_missing_required_location_says_both_ways_to_give_it():
    [problem] = check_parameters(PARAMS, {"Query": "x"})

    assert problem.startswith("'Source' is required: set 'Source'") and "'SourceEndpoint'" in problem


def test_a_missing_optional_location_is_fine():
    assert check_parameters(PARAMS, GOOD) == []         # Dest is not required


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_required_parameter_left_blank_is_missing(blank):
    assert check_parameters(PARAMS, {"SourceEndpoint": "E", "Query": blank}) == ["'Query' is required."]


def test_an_unknown_parameter_is_a_problem_and_lists_what_is_accepted():
    [problem] = check_parameters(PARAMS, {**GOOD, "Sorce": "typo"})

    assert problem.startswith("Unknown parameter 'Sorce'.")
    assert "Source, Dest, Query, Commit, Retries, Mode, SourceEndpoint, DestEndpoint" in problem


def test_parameter_names_are_case_sensitive():
    assert check_parameters(PARAMS, {**GOOD, "commit": "True"})[0].startswith("Unknown parameter 'commit'.")


@pytest.mark.parametrize("name, value, message", [
    ("Commit", "maybe", "'Commit' must be True or False, not 'maybe'."),
    ("Retries", "three", "'Retries' must be a whole number, not 'three'."),
    ("Retries", "2.5", "'Retries' must be a whole number, not '2.5'."),
    ("Mode", "QUICK", "'Mode' must be one of FAST, SAFE, not 'QUICK'."),
])
def test_a_value_of_the_wrong_type_is_a_problem(name, value, message):
    assert check_parameters(PARAMS, {**GOOD, name: value}) == [message]


def test_a_value_with_a_placeholder_is_not_type_checked_until_it_is_resolved():
    assert check_parameters(PARAMS, {**GOOD, "Commit": "${CommitFlag}", "Retries": "${N}"}) == []


def test_every_problem_is_reported_not_just_the_first():
    problems = check_parameters(PARAMS, {"Commit": "maybe", "Extra": "x"})

    assert len(problems) == 4          # unknown 'Extra', Source missing, Query missing, Commit not a boolean


# --- Converting resolved values for the handler -----------------------------------------------

def test_values_are_converted_and_defaults_filled_in():
    values = normalize_parameters(PARAMS, {"Source": "/in/*.csv", "Query": "SELECT 1", "Commit": "yes", "Mode": "safe"})

    assert values == {"Source": "/in/*.csv", "Query": "SELECT 1", "Commit": True, "Retries": 3, "Mode": "SAFE"}


@pytest.mark.parametrize("text, expected", [("True", True), ("true", True), ("YES", True), ("1", True), ("y", True),
                                            ("False", False), ("no", False), ("0", False), (True, True), (False, False)])
def test_booleans_can_be_written_several_ways(text, expected):
    assert normalize_parameters(PARAMS, {"Source": "s", "Query": "q", "Commit": text})["Commit"] is expected


def test_an_optional_parameter_with_no_default_is_left_out_when_not_set():
    values = normalize_parameters(PARAMS, {"Source": "s", "Query": "q"})

    assert "Mode" not in values and "Dest" not in values


def test_a_placeholder_that_resolved_to_the_wrong_type_is_refused():
    with pytest.raises(ValueError, match="'Commit' must be True or False, not 'sometimes'"):
        normalize_parameters(PARAMS, {"Source": "s", "Query": "q", "Commit": "sometimes"})


def test_converting_twice_changes_nothing():
    once = normalize_parameters(PARAMS, {"Source": "s", "Query": "q", "Commit": "yes", "Retries": "5"})

    assert normalize_parameters(PARAMS, once) == once


# --- A job is checked as a whole before any step runs -----------------------------------------

def names(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_a_mistake_in_a_later_step_stops_the_job_before_the_first_step_runs(seed, endpoints, run_runner, tmp_path):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Mvoe="True")

    result = run_runner("DEV-LOAD")

    assert result.returncode == 1
    assert "Step 2 ('Deliver'): Unknown parameter 'Mvoe'." in result.stderr
    assert "BEGIN Step 1" not in result.stdout
    assert names(tmp_path / "work" / "DEV-LOAD") == []          # step 1 collected nothing


def test_problems_in_several_steps_are_all_reported_at_once(seed, endpoints, run_runner, spool_records, tmp_path):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="NO_SUCH_ENDPOINT", Dest="incoming")
    seed.step(job, 2, title="Archive", Source="incoming/*.csv", Dest="archive", Move="perhaps")
    seed.step(job, 3, title="Deliver", Source="incoming/*.csv")
    seed.step(job, 4, title="Odd one", code="SQL_EXEC", Query="SELECT 1")

    result = run_runner("DEV-LOAD")

    assert result.returncode == 1
    assert "4 problems were found before the job started:" in result.stderr
    assert "- Step 1 ('Collect'): 'SourceEndpoint' refers to Endpoint 'NO_SUCH_ENDPOINT'" in result.stderr
    assert "- Step 2 ('Archive'): 'Move' must be True or False, not 'perhaps'." in result.stderr
    assert "- Step 3 ('Deliver'): 'Dest' is required" in result.stderr
    assert "- Step 4 ('Odd one'): Unknown step type: SQL_EXEC" in result.stderr
    assert "4 problems" in spool_records(tmp_path / "spool")[-1]["Error"]      # and it is on the run record


def test_a_placeholder_that_resolves_to_the_wrong_type_stops_the_job(seed, endpoints, run_runner):
    job = seed.job("DEV-LOAD", MoveFlag="sometimes")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming", Move="${MoveFlag}")

    result = run_runner("DEV-LOAD")

    assert result.returncode == 1
    assert "Step 1 ('Collect'): 'Move' must be True or False, not 'sometimes'." in result.stderr


def test_a_disabled_step_is_not_checked(seed, endpoints, run_runner):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Half written", Nonsense="x").IsActive = False

    assert run_runner("DEV-LOAD").returncode == 0


# --- Publishing the catalog -------------------------------------------------------------------

def test_sync_writes_each_step_type_and_its_parameters_in_order(db):
    counts = sync_catalog(db)

    assert sorted(t.HandlerClass for t in db.query(StepType)) == sorted(h.CODE for h in HANDLERS)
    step_type = db.query(StepType).filter_by(HandlerClass="COPY_FILES").one()
    assert (step_type.HandlerClass, step_type.TypeName, step_type.Description) == (
        "COPY_FILES", "Copy Files", FileOpHandler.DESCRIPTION)
    assert [(d.DisplayOrder, d.ParamName) for d in step_type.definitions] == [
        (1, "Source"), (2, "Dest"), (3, "RenameMask"), (4, "Move"), (5, "CreateFolder"), (6, "Checksum"),
        (7, "AllowNoFiles"), (8, "LogLevel"),
    ]
    assert counts == {"step_types": len(HANDLERS), "parameters": db.query(StepDefinition).count()}

    by_name = {d.ParamName: d for d in step_type.definitions}
    assert (by_name["Source"].DataType, by_name["Source"].LocationRole, by_name["Source"].IsRequired) == (
        "LOCATION", "SOURCE", True)
    assert (by_name["Dest"].DataType, by_name["Dest"].LocationRole) == ("LOCATION", "DEST")
    assert (by_name["Move"].DataType, by_name["Move"].DefaultValue, by_name["Move"].IsRequired) == (
        "BOOLEAN", "False", False)
    assert by_name["CreateFolder"].DefaultValue == "True"
    assert json.loads(by_name["LogLevel"].AllowedValues) == ["DEBUG", "DETAIL", "SUMMARY", "SILENT"]
    assert by_name["Move"].AllowedValues is None and by_name["Move"].LocationRole is None


def test_sync_can_be_repeated_without_adding_anything(db):
    sync_catalog(db)
    ids = sorted(d.id for d in db.query(StepDefinition))

    sync_catalog(db)

    assert db.query(StepType).count() == len(HANDLERS)
    assert sorted(d.id for d in db.query(StepDefinition)) == ids


def test_sync_corrects_what_has_drifted_and_removes_what_no_handler_declares(db):
    sync_catalog(db)
    step_type = db.query(StepType).filter_by(HandlerClass="COPY_FILES").one()
    step_type.TypeName = "Renamed by hand"
    move = db.query(StepDefinition).filter_by(StepType_id=step_type.id, ParamName="Move").one()
    move.DefaultValue = "True"
    db.add(StepDefinition(StepType_id=step_type.id, ParamName="RenamePattern", DisplayOrder=99))
    db.commit()

    sync_catalog(db)

    db.expire_all()
    assert db.get(StepType, step_type.id).TypeName == "Copy Files"
    assert db.get(StepDefinition, move.id).DefaultValue == "False"
    assert db.query(StepDefinition).filter(StepDefinition.ParamName == "RenamePattern").count() == 0


def test_sync_adopts_a_step_type_row_that_already_exists_and_keeps_the_steps_that_use_it(db, seed):
    """A seed script or an older version may have created the row; jobs already point at it."""
    job = seed.job("DEV-LOAD")
    step = seed.step(job, 1, Source="a", Dest="b")
    type_id = step.StepType_id

    sync_catalog(db)

    assert db.query(StepType).filter_by(HandlerClass="COPY_FILES").one().id == type_id
    assert db.get(StepType, type_id).TypeName == "Copy Files"


def test_sync_leaves_a_step_type_with_no_handler_alone(db):
    db.add(StepType(TypeName="Send Email", HandlerClass="SEND_EMAIL", Description="Planned"))
    db.commit()

    sync_catalog(db)

    by_code = {t.HandlerClass: t for t in db.query(StepType)}
    assert set(by_code) == {h.CODE for h in HANDLERS} | {"SEND_EMAIL"}
    assert (by_code["SEND_EMAIL"].TypeName, by_code["SEND_EMAIL"].Description) == ("Send Email", "Planned")


# --- The catalog and the job check, over the API ----------------------------------------------

def test_the_server_publishes_the_catalog_when_it_starts(client):
    """Nothing was seeded: starting the server is what filled the catalog tables."""
    response = client.get("/api/v1/step-types")

    assert response.status_code == 200
    by_code = {t["code"]: t for t in response.json()}
    assert set(by_code) == {h.CODE for h in HANDLERS}
    copy_files = by_code["COPY_FILES"]
    assert (copy_files["code"], copy_files["name"], copy_files["active"], copy_files["has_handler"]) == (
        "COPY_FILES", "Copy Files", True, True)
    assert [p["name"] for p in copy_files["parameters"]] == [
        "Source", "Dest", "RenameMask", "Move", "CreateFolder", "Checksum", "AllowNoFiles", "LogLevel"]


def test_catalog_describes_each_parameter_for_a_form(client):
    parameters = {p["name"]: p for p in client.get("/api/v1/step-types/COPY_FILES").json()["parameters"]}

    assert parameters["Source"] == {
        "name": "Source", "data_type": "LOCATION", "required": True, "default": None,
        "description": "The files to take. A pattern such as *.csv matches several.", "display_order": 1,
        "location_role": "SOURCE", "endpoint_parameter": "SourceEndpoint", "allowed_values": None,
    }
    assert (parameters["Dest"]["location_role"], parameters["Dest"]["endpoint_parameter"]) == ("DEST", "DestEndpoint")
    assert (parameters["Move"]["data_type"], parameters["Move"]["default"], parameters["Move"]["required"]) == (
        "BOOLEAN", "False", False)
    assert parameters["Move"]["endpoint_parameter"] is None
    assert parameters["LogLevel"]["allowed_values"] == ["DEBUG", "DETAIL", "SUMMARY", "SILENT"]


def test_a_step_type_with_no_handler_is_listed_as_such(client, db):
    db.add(StepType(TypeName="Send Email", HandlerClass="SEND_EMAIL"))
    db.commit()

    by_code = {t["code"]: t for t in client.get("/api/v1/step-types").json()}

    assert (by_code["SEND_EMAIL"]["has_handler"], by_code["SEND_EMAIL"]["parameters"]) == (False, [])
    assert by_code["COPY_FILES"]["has_handler"] is True


def test_unknown_step_type_is_404(client):
    response = client.get("/api/v1/step-types/NO_SUCH_TYPE")

    assert response.status_code == 404
    assert "NO_SUCH_TYPE" in response.json()["detail"]


@pytest.fixture
def working_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))


def test_checking_a_sound_job_finds_no_problems_and_touches_nothing(client, db, seed, endpoints, working_root, tmp_path):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    db.commit()

    response = client.get("/api/v1/jobs/DEV-LOAD/check")

    assert response.status_code == 200
    assert response.json() == {"job_key": "DEV-LOAD", "valid": True, "problems": [], "warnings": []}
    assert not (tmp_path / "work").exists()                      # checking is not running


def test_checking_a_job_reports_every_problem_the_runner_would(client, db, seed, endpoints, working_root):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="${NoSuchVariable}/in")
    seed.step(job, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Mvoe="True")
    db.commit()

    result = client.get("/api/v1/jobs/DEV-LOAD/check").json()

    assert result["valid"] is False
    assert len(result["problems"]) == 2
    assert "Step 1 ('Collect')" in result["problems"][0] and "${NoSuchVariable}" in result["problems"][0]
    assert result["problems"][1].startswith("Step 2 ('Deliver'): Unknown parameter 'Mvoe'.")


def test_checking_a_disabled_job_or_one_with_no_steps_says_so(client, db, seed, working_root):
    seed.job("DEV-EMPTY")
    seed.job("DEV-OFF").IsActive = False
    db.commit()

    assert client.get("/api/v1/jobs/DEV-EMPTY/check").json()["problems"] == ["Job 'DEV-EMPTY' has no active steps."]
    assert client.get("/api/v1/jobs/DEV-OFF/check").json()["problems"][0] == "Job 'DEV-OFF' is disabled."


def test_checking_an_unknown_job_is_404(client):
    assert client.get("/api/v1/jobs/NO_SUCH_JOB/check").status_code == 404

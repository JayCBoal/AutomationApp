"""
Flow control (docs/FLOW_CONTROL.md): If, ElseIf and Else; For Each File; While; step
outputs read as %{StepName.Output}; and what On failure does.

Jobs are run as a scheduler would run them, as a separate process (run_runner), with
the layout of test_runner.py: LEGAL_EXTRACTS holds Legal_Batch_1.csv and Legal_Batch_2.csv.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.models import JobStep, Operation
from conftest import read_logs
from engine import conditions

MIGRATION = Path(__file__).resolve().parents[2] / "SQL" / "migrate_flow_control.py"


def names(folder):
    return sorted(p.name for p in Path(folder).iterdir())


def job_log(spool_records, tmp_path) -> str:
    return read_logs(tmp_path / "logs")


def if_job(seed, condition, elseif=None):
    """A job whose step 1 is an If copying the batch into 'then', 'elseif' or 'else'."""
    job = seed.job("FLOW", Mode="A")
    choice = seed.step(job, 1, "IF", title="Which way", name="Which_way", Condition=condition)
    then = seed.step(job, 1, "THEN", parent=choice)
    seed.step(job, 1, parent=then, SourceEndpoint="LEGAL_EXTRACTS", Dest="then")
    position = 2
    if elseif:
        other = seed.step(job, position, "ELSEIF", parent=choice, Condition=elseif)
        other_then = seed.step(job, 1, "THEN", parent=other)
        seed.step(job, 1, parent=other_then, SourceEndpoint="LEGAL_EXTRACTS", Dest="elseif")
        position += 1
    otherwise = seed.step(job, position, "ELSE", parent=choice)
    seed.step(job, 1, parent=otherwise, SourceEndpoint="LEGAL_EXTRACTS", Dest="else")
    return job


# ---------- If, ElseIf, Else ----------

def test_an_if_runs_its_then_when_the_condition_holds(seed, run_runner, endpoints, tmp_path, spool_records):
    if_job(seed, "${Mode} = 'A'")
    result = run_runner("FLOW")
    assert result.returncode == 0, result.stderr
    assert names(tmp_path / "work" / "FLOW") == ["then"]
    assert "took the Then branch" in job_log(spool_records, tmp_path)


def test_an_if_runs_its_else_when_no_condition_holds(seed, run_runner, endpoints, tmp_path):
    if_job(seed, "${Mode} = 'B'", elseif="${Mode} = 'C'")
    assert run_runner("FLOW").returncode == 0
    assert names(tmp_path / "work" / "FLOW") == ["else"]


def test_the_first_elseif_that_holds_is_taken(seed, run_runner, endpoints, tmp_path, spool_records):
    if_job(seed, "${Mode} = 'B'", elseif="${Mode} = 'A'")
    assert run_runner("FLOW").returncode == 0
    assert names(tmp_path / "work" / "FLOW") == ["elseif"]
    records = spool_records(tmp_path / "spool")
    assert {r["StepNumber"] for r in records if r["Record"] == "OPERATION"} == {"1.2"}


# ---------- For Each File ----------

def test_for_each_file_runs_its_steps_once_per_file(seed, run_runner, endpoints, tmp_path, spool_records):
    source, _ = endpoints
    job = seed.job("EACH")
    loop = seed.step(job, 1, "FOR_EACH_FILE", title="Each file", name="Each", SourceEndpoint="LEGAL_EXTRACTS")
    seed.step(job, 1, parent=loop, title="Copy one", Source="%{File.FullName}", Dest="per_file/%{File.BaseName}")

    result = run_runner("EACH")
    assert result.returncode == 0, result.stderr
    per_file = tmp_path / "work" / "EACH" / "per_file"
    assert names(per_file) == ["Legal_Batch_1", "Legal_Batch_2"]
    assert names(per_file / "Legal_Batch_2") == ["Legal_Batch_2.csv"]

    operations = [r for r in spool_records(tmp_path / "spool") if r["Record"] == "OPERATION"]
    # Each pass is recorded as such, and the file is still traced to the endpoint the loop reads from
    assert [(r["StepOrder"], r["StepNumber"], r["Iteration"], r["SourceEndpointID"]) for r in operations] == [
        (1, "1.1", "1", source.id), (1, "1.1", "2", source.id)]
    log = job_log(spool_records, tmp_path)
    assert "Step 1.1: Copy one (COPY_FILES) [File 2 of 2: Legal_Batch_2.csv]" in log
    assert "went through 2 files" in log


def test_operations_keep_their_step_number_and_pass(seed, run_runner, endpoints, load_spool, db):
    job = seed.job("EACH")
    loop = seed.step(job, 1, "FOR_EACH_FILE", SourceEndpoint="LEGAL_EXTRACTS", ItemName="Batch")
    seed.step(job, 1, parent=loop, Source="%{Batch.FullName}", Dest="out")
    assert run_runner("EACH").returncode == 0
    load_spool()
    assert sorted((o.StepNumber, o.Iteration) for o in db.query(Operation)) == [("1.1", "1"), ("1.1", "2")]


def test_a_loop_with_no_files_does_nothing_and_succeeds(seed, run_runner, endpoints, tmp_path):
    job = seed.job("EACH")
    loop = seed.step(job, 1, "FOR_EACH_FILE", Source="nothing_here/*.csv")
    seed.step(job, 1, parent=loop, Source="%{File.FullName}", Dest="out")
    assert run_runner("EACH").returncode == 0


# ---------- Outputs and On failure ----------

def test_a_failed_step_set_to_continue_can_be_tested_by_a_later_if(seed, run_runner, endpoints, tmp_path):
    job = seed.job("CHECKED")
    seed.step(job, 1, "CHECK_FILES", title="Enough files", name="Check", on_failure="CONTINUE",
              SourceEndpoint="LEGAL_EXTRACTS", MinCount="5")
    choice = seed.step(job, 2, "IF", Condition="%{Check.Status} = 'FAILED' AND %{Check.FileCount} = 2")
    then = seed.step(job, 1, "THEN", parent=choice)
    seed.step(job, 1, parent=then, SourceEndpoint="LEGAL_EXTRACTS", Dest="flagged")
    seed.step(job, 2, "ELSE", parent=choice)

    result = run_runner("CHECKED")
    assert result.returncode == 0, result.stderr
    assert names(tmp_path / "work" / "CHECKED" / "flagged") == ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]


def test_a_failed_step_set_to_end_with_success_stops_the_job_successfully(
        seed, run_runner, endpoints, tmp_path, spool_records):
    job = seed.job("ENDS")
    seed.step(job, 1, "CHECK_FILES", on_failure="END_SUCCESS", SourceEndpoint="LEGAL_EXTRACTS", MinCount="5")
    seed.step(job, 2, SourceEndpoint="LEGAL_EXTRACTS", Dest="never")

    result = run_runner("ENDS")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "work" / "ENDS" / "never").exists()
    records = spool_records(tmp_path / "spool")
    assert records[-1]["Status"] == "SUCCESS"
    assert "the job ends here with success" in job_log(spool_records, tmp_path)


def test_a_failure_inside_a_loop_fails_the_job_by_default(seed, run_runner, endpoints, tmp_path, spool_records):
    job = seed.job("EACH")
    loop = seed.step(job, 1, "FOR_EACH_FILE", SourceEndpoint="LEGAL_EXTRACTS")
    seed.step(job, 1, "CHECK_FILES", parent=loop, Source="%{File.FullName}", MinCount="2")
    result = run_runner("EACH")
    assert result.returncode == 1
    assert spool_records(tmp_path / "spool")[-1]["Error"].startswith("The files did not pass the check.")


# ---------- While ----------

def test_while_repeats_until_its_condition_no_longer_holds(seed, run_runner, endpoints, tmp_path):
    job = seed.job("LOOPS")
    loop = seed.step(job, 1, "WHILE", name="Loop", Condition="%{Loop.Passes} < 3", MaxIterations="10")
    seed.step(job, 1, parent=loop, SourceEndpoint="LEGAL_EXTRACTS", Dest="pass_%{Loop.Passes}")
    result = run_runner("LOOPS")
    assert result.returncode == 0, result.stderr
    assert names(tmp_path / "work" / "LOOPS") == ["pass_1", "pass_2", "pass_3"]


def test_a_while_that_goes_past_its_limit_fails(seed, run_runner, endpoints, tmp_path, spool_records):
    job = seed.job("FOREVER")
    loop = seed.step(job, 1, "WHILE", Condition="1 = 1", MaxIterations="2")
    seed.step(job, 1, parent=loop, SourceEndpoint="LEGAL_EXTRACTS", Dest="again")
    assert run_runner("FOREVER").returncode == 1
    assert "MaxIterations" in spool_records(tmp_path / "spool")[-1]["Error"]


# ---------- The pre-run check ----------

def check(client, key):
    response = client.get(f"/api/v1/jobs/{key}/check")
    assert response.status_code == 200, response.text
    return response.json()["problems"]


def test_the_check_names_what_a_run_value_gets_wrong(seed, client, db, endpoints):
    job = seed.job("BAD")
    seed.step(job, 1, "CHECK_FILES", name="Check", SourceEndpoint="LEGAL_EXTRACTS")
    loop = seed.step(job, 2, "FOR_EACH_FILE", title="Each", SourceEndpoint="LEGAL_EXTRACTS")
    seed.step(job, 1, parent=loop, title="Copy", Source="%{File}", Dest="out/%{Nobody.Status}")
    seed.step(job, 3, title="After", Source="in", Dest="%{Check.Colour}")
    db.commit()
    problems = check(client, "BAD")
    assert any(p.startswith("Step 2.1 ('Copy'): %{File} is a file, not a value") for p in problems), problems
    assert any("%{Nobody.Status}: no step is named Nobody" in p for p in problems), problems
    assert any(p.startswith("Step 3 ('After'): %{Check.Colour}: the step Check has no output 'Colour'")
               for p in problems), problems


def test_the_check_finds_a_condition_that_is_not_valid_even_in_a_branch_that_rarely_runs(seed, client, db, endpoints):
    job = seed.job("BAD")
    choice = seed.step(job, 1, "IF", title="Late?", Condition="1 = 1")
    then = seed.step(job, 1, "THEN", parent=choice)
    inner = seed.step(job, 1, "IF", parent=then, title="Inner", Condition="%{File.Name} = = 'x'")
    seed.step(job, 1, "THEN", parent=inner)
    db.commit()
    problems = check(client, "BAD")
    assert any(p.startswith("Step 1.1 ('Inner'): ") and "not valid" in p for p in problems), problems
    # %{File...} outside any loop is named too
    assert any("no For Each File loop around this step calls its file File" in p for p in problems), problems


def test_the_check_refuses_an_if_without_its_then(seed, client, db):
    job = seed.job("BAD")
    seed.step(job, 1, "IF", title="Lonely", Condition="1 = 1")
    db.commit()
    assert any("must start with one Then" in p for p in check(client, "BAD"))


# ---------- Saving and reading a job with blocks ----------

def nested_job(**changes):
    job = {
        "job_key": "NESTED", "steps": [
            {"title": "Check files", "step_type": "CHECK_FILES", "on_failure": "CONTINUE",
             "parameters": {"Source": "in/*.csv"}},
            {"title": "Any?", "step_type": "IF", "parameters": {"Condition": "%{Check_files.FileCount} > 0"},
             "children": [
                 {"step_type": "THEN", "children": [
                     {"title": "Copy them", "step_type": "COPY_FILES", "parameters": {"Source": "in/*.csv", "Dest": "out"}}]},
                 {"step_type": "ELSE"},
             ]},
        ]}
    job.update(changes)
    return job


def test_a_job_with_blocks_is_saved_and_read_back_as_a_tree(client):
    response = client.post("/api/v1/jobs", json=nested_job())
    assert response.status_code == 201, response.text
    steps = client.get("/api/v1/jobs/NESTED").json()["steps"]
    assert [(s["number"], s["name"], s["on_failure"]) for s in steps] == [
        ("1", "Check_files", "CONTINUE"), ("2", "Any", "FAIL_JOB")]
    then, otherwise = steps[1]["children"]
    assert (then["step_type"], then["number"], then["name"]) == ("THEN", "2", None)
    assert [(s["number"], s["title"]) for s in then["children"]] == [("2.1", "Copy them")]
    assert otherwise["step_type"] == "ELSE"


def test_moving_a_step_out_of_a_block_keeps_it_and_says_so(client):
    client.post("/api/v1/jobs", json=nested_job())
    saved = client.get("/api/v1/jobs/NESTED").json()["steps"]
    copy = saved[1]["children"][0]["children"][0]
    steps = [
        {**saved[0], "children": []},
        {**saved[1], "children": [{**saved[1]["children"][0], "children": []}, saved[1]["children"][1]]},
        copy,
    ]
    response = client.put("/api/v1/jobs/NESTED", json=nested_job(steps=steps))
    assert response.status_code == 200, response.text
    assert "Changed step 3 ('Copy them'): moved into the top level." in response.json()["changes"]
    assert [s["id"] for s in response.json()["job"]["steps"]][-1] == copy["id"]


def test_removing_a_block_removes_the_steps_inside_it(client, db):
    client.post("/api/v1/jobs", json=nested_job())
    saved = client.get("/api/v1/jobs/NESTED").json()["steps"]
    response = client.put("/api/v1/jobs/NESTED", json=nested_job(steps=[saved[0]]))
    assert response.status_code == 200, response.text
    # One line for the If; its Then, Else and the step inside go with it unmentioned
    assert response.json()["changes"] == ["Removed step 'Any?'."]
    db.commit()
    assert db.query(JobStep).count() == 1


def test_a_named_step_keeps_its_name_when_its_title_changes(client):
    client.post("/api/v1/jobs", json=nested_job())
    saved = client.get("/api/v1/jobs/NESTED").json()["steps"]
    steps = [{**saved[0], "title": "Look for files", "name": None}, saved[1]]
    job = client.put("/api/v1/jobs/NESTED", json=nested_job(steps=steps)).json()["job"]
    assert job["steps"][0]["name"] == "Check_files"


@pytest.mark.parametrize("change, message", [
    ({"children": [{"step_type": "ELSE"}]}, "must start with one Then"),
    ({"name": "2 fast"}, "'2 fast' cannot be a step name"),
    ({"on_failure": "SHRUG"}, "On failure must be one of FAIL_JOB, CONTINUE, END_SUCCESS"),
])
def test_a_job_that_cannot_be_saved_is_refused_with_a_reason(client, change, message):
    job = nested_job()
    job["steps"][1].update(change)
    response = client.post("/api/v1/jobs", json=job)
    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_an_ordinary_step_cannot_hold_steps(client):
    job = nested_job()
    job["steps"][0]["children"] = [{"step_type": "COPY_FILES", "parameters": {}}]
    response = client.post("/api/v1/jobs", json=job)
    assert response.status_code == 422
    assert "only If, For Each File and While can hold steps" in response.json()["detail"]


def test_the_preview_points_out_a_comparison_of_a_number_with_text(client):
    job = nested_job()
    job["steps"][1]["parameters"]["Condition"] = "%{Check_files.FileCount} > '0'"
    preview = client.post("/api/v1/jobs/preview", json=job).json()
    condition = preview["steps"][1]["Condition"]
    assert condition["warnings"] and "compares a number with text" in condition["warnings"][0]
    assert any("compares a number with text" in w for w in preview["warnings"])


def test_the_preview_checks_a_saved_step_as_the_type_it_is_changed_to(client):
    client.post("/api/v1/jobs", json=nested_job())
    saved = client.get("/api/v1/jobs/NESTED").json()["steps"]
    first = {**saved[0], "step_type": "WHILE", "parameters": {"Condition": "1 = 0", "MaxIterations": "3"}}
    preview = client.post("/api/v1/jobs/preview?existing_key=NESTED", json=nested_job(steps=[first, saved[1]])).json()
    # Before, the step was still checked as a Check Files step, which has no Condition
    assert not any("Unknown parameter" in p for p in preview["problems"]), preview["problems"]


def test_the_catalog_says_which_step_types_hold_steps_and_what_they_give(client):
    catalog = {t["code"]: t for t in client.get("/api/v1/step-types").json()}
    assert (catalog["IF"]["block"], catalog["IF"]["hidden"]) == (True, False)
    assert (catalog["THEN"]["block"], catalog["THEN"]["hidden"]) == (True, True)
    assert {o["name"] for o in catalog["CHECK_FILES"]["outputs"]} >= {"Status", "ReturnCode", "FileCount"}


# ---------- Conditions ----------

VALUES = {"%{File.Name}": "it's.csv", "%{File.Size}": 2048, "${Limit}": "1000", "%{Gone.ErrorMessage}": None}


@pytest.mark.parametrize("condition, expected", [
    ("%{File.Size} > ${Limit}", True),                     # a variable's number is compared as a number
    ("'%{File.Name}' = 'it''s.csv'", True),                # a quote in a value cannot end the text
    ("%{File.Name} LIKE '%.CSV'", True),                   # LIKE ignores case
    ("%{File.Name} = 'IT''S.CSV'", False),                 # = does not
    ("%{Gone.ErrorMessage} IS NULL", True),
    ("%{File.Size} BETWEEN 1 AND 100", False),
    ("lower(\"ABC\") = 'abc'", True),                      # double quotes are text too
])
def test_conditions(condition, expected):
    assert conditions.evaluate(condition, VALUES.get)[0] is expected


@pytest.mark.parametrize("condition, message", [
    ("%{File.Name} = SUCCESS", "'SUCCESS' is not a value. Put text in quotes"),
    ("%{File.Size} >", "stops before it is complete"),
    ("1 = 1; DELETE FROM x", "not valid near ';'"),
    ("(SELECT count(*) FROM sqlite_master) = 0", "can only compute values"),
    ("nosuch(1) = 1", "There is no function called nosuch"),
])
def test_a_condition_that_cannot_be_worked_out_says_why(condition, message):
    with pytest.raises(ValueError, match=message.replace("(", r"\(")):
        conditions.evaluate(condition, VALUES.get)


def test_a_value_cannot_change_what_a_condition_means():
    values = {"%{File.Name}": "x' OR '1'='1"}
    assert conditions.evaluate("%{File.Name} = 'y'", values.get)[0] is False
    assert conditions.evaluate("'%{File.Name}' = 'y'", values.get)[0] is False


# ---------- Bringing an older database up to date ----------

def test_the_migration_adds_the_columns_and_names_the_steps(tmp_path):
    database = tmp_path / "old.db"
    import sqlite3
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE JobSteps (id INTEGER PRIMARY KEY, Job_MasterObject_id INTEGER, StepType_id INTEGER,
                               StepOrder INTEGER, StepTitle VARCHAR(150), IsActive BOOLEAN);
        CREATE TABLE Operations (id INTEGER PRIMARY KEY, StepOrder INTEGER);
        INSERT INTO JobSteps VALUES (1, 1, 1, 1, 'Copy invoices (EU)', 1), (2, 1, 1, 2, NULL, 1);
    """)
    connection.commit()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    for _ in range(2):          # a second run finds nothing to do
        subprocess.run([sys.executable, str(MIGRATION)], env=env, check=True, capture_output=True)
    rows = connection.execute("SELECT StepName, OnFailure, ParentStep_id FROM JobSteps ORDER BY id").fetchall()
    assert rows == [("Copy_invoices_EU", "FAIL_JOB", None), ("Step2", "FAIL_JOB", None)]
    columns = {row[1] for row in connection.execute("PRAGMA table_info(Operations)")}
    assert {"StepNumber", "Iteration"} <= columns

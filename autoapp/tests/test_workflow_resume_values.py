"""
The values of a workflow's Resume (docs/WORKFLOWS_PHASE7.md, step 4b-1): the workflow's variables, and each use's, are
kept on the run; a Resume uses them as they were, reads them again (Refresh) or takes the operator's edits, and the jobs
that run again read what the workflow now holds. The job here fails while the workflow's variable Fail is True.
"""
import json

import pytest

from core.models import JobRun, Variable, WorkflowItem, WorkflowItemVariable
from engine import workflow_vars
from test_workflow_reopen import reopen          # noqa: F401  (fixture)
from test_workflow_runner import flow, results, run_flow, sim, start    # noqa: F401  (fixtures)


@pytest.fixture
def valued(seed, flow, run_flow, db):
    """Load fails because ${Fail} is True; Extract before it and Report after it succeed."""
    load = seed.job("LOAD")
    seed.step(load, 1, "SIMULATE", title="Load", Fail="${Fail}", Messages="Region ${Region}")
    extract, report = seed.job("EXTRACT"), seed.job("REPORT")
    seed.step(extract, 1, "SIMULATE", title="Extract", Fail="False")
    seed.step(report, 1, "SIMULATE", title="Report", Fail="False")
    workflow = flow("WF", [("Extract", extract), ("Load", load, ["Extract"]), ("Report", report, ["Load"])])
    seed.set_vars(workflow, Fail="True", Region="EU")
    return run_flow("WF")


def change_workflow_variable(db, name, value):
    db.query(Variable).filter(Variable.VarName == name,
                              Variable.MasterObject_id == db.query(JobRun).first().Job_MasterObject_id).one().VarValue = value
    db.commit()


def edits(**workflow):
    return json.dumps({"levels": {"": {"workflow": workflow}}})


def kept(db, run):
    db.refresh(run)
    return json.loads(run.WorkflowVariables)


def test_a_resume_with_no_choice_uses_the_workflows_values_as_they_were(valued, reopen, db):
    _, first, _, _ = valued
    change_workflow_variable(db, "Fail", "False")

    done = reopen(first, "resume")

    run, items, log = results(db, "WF")
    assert items["Load"].Status == "FAILED" and run.Status == "FAILED", done.stdout + done.stderr
    assert kept(db, run)["workflow"]["Fail"] == {"value": "True"}


def test_a_refresh_reads_the_workflows_variables_again_and_the_log_says_which_changed(valued, reopen, db):
    _, first, _, _ = valued
    change_workflow_variable(db, "Fail", "False")

    done = reopen(first, "resume", "--refresh-values")

    run, items, log = results(db, "WF")
    assert (run.Status, items["Load"].Status, items["Report"].Status) == ("SUCCESS", "SUCCESS", "SUCCESS"), done.stdout + done.stderr
    assert "Refreshed workflow variable Fail: it was 'True', it is now 'False'." in log
    assert kept(db, run)["workflow"]["Fail"] == {"value": "False"}


def test_an_edit_replaces_one_workflow_value_and_the_resumed_job_reads_it(valued, reopen, db):
    _, first, _, _ = valued

    done = reopen(first, "resume", "--edit-values", edits(Fail="False"))

    run, items, log = results(db, "WF")
    assert (run.Status, items["Load"].Status) == ("SUCCESS", "SUCCESS"), done.stdout + done.stderr
    assert "Edited workflow variable Fail: it was 'True', the operator set 'False'." in log
    assert kept(db, run)["workflow"]["Region"] == {"value": "EU"}           # the others stay


def test_an_edit_reaches_the_job_even_though_it_stored_the_value_it_used(valued, reopen, db, tmp_path):
    _, first, _, _ = valued
    reopen(first, "resume", "--edit-values", edits(Fail="False", Region="US"))

    job_logs = " ".join(path.read_text() for path in (tmp_path / "logs").rglob("*.log"))

    assert "Region US" in job_logs
    assert "Fail is read again: the workflow's value for it was changed." in job_logs


def test_a_restart_gets_no_values_choice(valued, reopen, db):
    _, first, _, _ = valued
    change_workflow_variable(db, "Fail", "False")

    reopen(first, "restart", "--edit-values", edits(Fail="True"))

    run, items, _ = results(db, "WF")
    assert items["Load"].Status == "FAILED"                  # the edit was not applied; nothing but a Resume takes one
    assert kept(db, run)["workflow"]["Fail"] == {"value": "True"}


def test_a_secret_is_never_edited(db):
    now = {"workflow": {"Fail": {"value": "True"}, "Key": {"secret": True}}, "uses": {}}

    said = workflow_vars.apply_choices(now, None, {"workflow": {"Key": "x", "Nope": "y"}})

    assert now["workflow"]["Key"] == {"secret": True}
    assert len(said) == 2 and all(line.startswith("Not edited") for line in said)


def test_the_names_a_job_must_read_again_come_from_every_level_at_or_above_it():
    choices = {"levels": {"": {"workflow": {"A": "1"}, "uses": {"Frame": {"U": "2"}}},
                          "Frame": {"workflow": {"B": "3"}, "uses": {"Job": {"C": "4"}}},
                          "Other": {"workflow": {"D": "5"}}}}

    assert workflow_vars.dropped_names(choices, "Frame", "Job") == ["A", "B", "C"]
    assert workflow_vars.dropped_names(choices, None, "Frame") == ["A", "U"]

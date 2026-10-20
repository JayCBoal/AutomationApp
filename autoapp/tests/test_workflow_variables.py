"""
Workflow variables (docs/WORKFLOWS_PHASE4.md, decisions 19 to 21): a workflow's variables, and its
tags', reach the jobs it runs, fixed as the run starts; a use can override one for itself; the
Variable precedence setting orders them. Each job here is a Simulate step whose return code is
${Code}, so the code it ends with says which value it got.
"""
import json
import time

import pytest

from app.models import JobRun, SettingValue, Variable, WorkflowItem, WorkflowItemVariable
from engine import settings
from test_workflow_runner import flow, results, run_flow, sim, start, states  # noqa: F401 (fixtures)

ROUTE = "/api/v1/jobs"
SUCCESS = "0-99"


@pytest.fixture
def coded(seed):
    """A job that ends with return code ${Code}, a success whatever it is: coded('A', Code='5')."""
    def _make(key, wait=0, **variables):
        job = seed.job(key, **variables)
        job.SuccessReturnCodes = SUCCESS
        seed.step(job, 1, "SIMULATE", title=f"Simulate {key}", ReturnCode="${Code}", Fail="False",
                  WaitSeconds=str(wait))
        return job
    return _make


def use_variable(db, workflow, name, var, value, secret=False):
    item = db.query(WorkflowItem).filter(WorkflowItem.Workflow_MasterObject_id == workflow.MasterObject_id,
                                         WorkflowItem.ItemName == name).one()
    db.add(WorkflowItemVariable(Item_id=item.id, VarName=var, VarValue=value, IsSecret=secret))


def codes(items):
    return {name: i.ReturnCode for name, i in items.items()}


# ---------- What reaches a job, and what wins ----------

def test_a_workflows_variable_reaches_its_jobs(coded, flow, run_flow, seed, db):
    workflow = flow("WF_VARS", [("A", coded("A")), ("B", coded("B"), ["A"])])
    seed.set_vars(workflow, Code="3")

    code, run, items, log = run_flow("WF_VARS")

    assert code == 0, log
    assert codes(items) == {"A": 3, "B": 3}
    assert "Variables for its jobs: Code." in log


def test_the_jobs_own_beats_the_workflows_and_a_use_beats_both(coded, flow, run_flow, seed, db):
    job = coded("OWN", Code="5")
    workflow = flow("WF_ORDER", [("Plain", job), ("Overridden", job)])
    seed.set_vars(workflow, Code="3")
    use_variable(db, workflow, "Overridden", "Code", "7")

    code, run, items, log = run_flow("WF_ORDER")

    assert codes(items) == {"Plain": 5, "Overridden": 7}, log


def test_the_workflows_tags_feed_its_jobs_below_its_own_and_above_the_jobs_tags(coded, flow, run_flow, seed, db):
    test, prod, other = seed.tag("TEST", Code="11"), seed.tag("PROD", Code="22"), seed.tag("OTHER", Region="EU")
    tagged = coded("TAGGED")
    seed.attach(prod, tagged)
    workflow = flow("WF_TAGS", [("Tagged", tagged)])
    seed.attach(test, workflow)
    run_code, _, items, log = run_flow("WF_TAGS")
    assert codes(items) == {"Tagged": 11}, log           # the workflow's tag beats the job's

    seed.set_vars(workflow, Code="4")
    _, _, items, log = run_flow("WF_TAGS")
    assert codes(items) == {"Tagged": 4}, log            # the workflow's own beats its tags


def test_the_precedence_setting_can_put_the_jobs_tags_above_the_workflow(coded, flow, run_flow, seed, db):
    prod = seed.tag("PROD", Code="22")
    tagged = coded("TAGGED")
    seed.attach(prod, tagged)
    workflow = flow("WF_SWAP", [("Tagged", tagged)])
    seed.set_vars(workflow, Code="4")
    db.add(SettingValue(SettingKey="VariablePrecedence", SettingValue="ENV,SYS,ENTITY,APP,ENDPOINT,WORKFLOW,TAG,JOB,USE"))

    _, _, items, log = run_flow("WF_SWAP")

    assert codes(items) == {"Tagged": 22}, log


def test_a_variable_the_workflows_tags_disagree_about_fails_the_job_that_uses_it(coded, flow, run_flow, seed, db):
    first, second = seed.tag("FIRST", Code="1"), seed.tag("SECOND", Code="2")
    workflow = flow("WF_CLASH", [("A", coded("A"))])
    seed.attach(first, workflow)
    seed.attach(second, workflow)

    _, _, items, log = run_flow("WF_CLASH")

    assert items["A"].Status == "FAILED", log
    assert "Give it a value on workflow 'WF_CLASH', or on this use of the job." in log


def test_a_job_run_on_its_own_gets_nothing_from_workflows_that_use_it(coded, flow, seed, db, run_runner, load_spool):
    job = coded("ALONE", Code="5")
    workflow = flow("WF_UNUSED", [("Alone", job)])
    seed.set_vars(workflow, Code="3")
    db.commit()
    run_runner("ALONE")
    load_spool()
    run = db.query(JobRun).filter(JobRun.JobKey == "ALONE").one()
    assert run.ReturnCode == 5


# ---------- Fixed as the run starts, secrets never kept ----------

def test_values_are_fixed_when_the_run_starts(coded, flow, seed, db, db_url, tmp_path):
    workflow = flow("WF_FIXED", [("Slow", coded("SLOW", wait=2)), ("Later", coded("LATER"), ["Slow"])])
    seed.set_vars(workflow, Code="3")
    db.commit()
    process = start(db_url, tmp_path, "WF_FIXED")
    time.sleep(1)
    db.query(Variable).filter(Variable.MasterObject_id == workflow.MasterObject_id).one().VarValue = "9"
    db.commit()
    output, _ = process.communicate(timeout=120)

    _, items, log = results(db, "WF_FIXED")
    assert codes(items) == {"Slow": 3, "Later": 3}, output


def test_a_secret_reaches_the_job_but_its_value_is_never_kept_on_the_run(coded, flow, run_flow, seed, db):
    workflow = flow("WF_SECRET", [("A", coded("A")), ("B", coded("B"))])
    db.add(Variable(MasterObject_id=workflow.MasterObject_id, VarName="Code", VarValue="6", IsSecret=True))
    use_variable(db, workflow, "B", "Code", "8", secret=True)

    _, run, items, log = run_flow("WF_SECRET")

    assert codes(items) == {"A": 6, "B": 8}, log
    kept = json.loads(run.WorkflowVariables)
    assert kept == {"workflow": {"Code": {"secret": True}}, "uses": {"A": {}, "B": {"Code": {"secret": True}}}}


def test_a_workflows_value_is_filled_in_as_the_run_starts(coded, flow, run_flow, seed, db):
    workflow = flow("WF_FILLED", [("A", coded("A"))])
    seed.set_vars(workflow, Code="${Base}", Base="4", Folder="out/${UnknownHere}")

    _, run, items, log = run_flow("WF_FILLED")

    assert codes(items) == {"A": 4}, log
    kept = json.loads(run.WorkflowVariables)["workflow"]
    assert kept["Code"] == {"value": "4"}
    assert kept["Folder"] == {"value": "out/${UnknownHere}"}     # left for the job to fill in


# ---------- The check before a run ----------

def test_the_check_sees_what_the_workflow_and_the_use_give(client, coded, flow, seed, db):
    workflow = flow("WF_CHECK", [("Given", coded("NEEDS_CODE")), ("Missing", coded("ALSO_NEEDS"))])
    db.commit()
    warnings = client.get(f"{ROUTE}/WF_CHECK/check").json()["warnings"]
    assert any(w.startswith("'Given' would fail:") and "${Code}" in w for w in warnings)

    use_variable(db, workflow, "Given", "Code", "1")
    db.commit()
    warnings = client.get(f"{ROUTE}/WF_CHECK/check").json()["warnings"]
    assert not any(w.startswith("'Given'") for w in warnings), warnings
    assert any(w.startswith("'Missing' would fail:") for w in warnings)

    seed.set_vars(workflow, Code="2")
    db.commit()
    assert client.get(f"{ROUTE}/WF_CHECK/check").json()["warnings"] == []
    assert not client.get(f"{ROUTE}/NEEDS_CODE/check").json()["valid"]     # on its own, it has no Code


# ---------- Saving a use's variables ----------

def test_a_uses_variables_are_saved_and_a_secret_is_never_sent_back(client, coded, flow, db):
    flow("WF_SAVE", [("A", coded("A"))])
    db.commit()
    saved = client.get(f"{ROUTE}/WF_SAVE").json()
    payload = {"job_key": "WF_SAVE", "job_type": "WORKFLOW", "description": None,
               "items": [{"id": i["id"], "name": i["name"], "job_key": i["job_key"], "join": i["join"],
                          "prerequisites": i["prerequisites"],
                          "variables": [{"name": "Code", "value": "7"},
                                        {"name": "Token", "value": "s3cret", "secret": True}]}
                         for i in saved["items"]]}
    result = client.put(f"{ROUTE}/WF_SAVE", json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["changes"] == ["Changed 'A': added its variables Code, Token."]
    variables = result.json()["job"]["items"][0]["variables"]
    assert variables == [{"name": "Code", "value": "7", "secret": False, "description": None},
                         {"name": "Token", "value": None, "secret": True, "description": None}]

    # A blank secret keeps its value; leaving variables out leaves them alone
    payload["items"][0]["variables"] = [{"name": "Code", "value": "8"}, {"name": "Token", "value": "", "secret": True}]
    assert client.put(f"{ROUTE}/WF_SAVE", json=payload).json()["changes"] == ["Changed 'A': changed its variable Code."]
    del payload["items"][0]["variables"]
    assert client.put(f"{ROUTE}/WF_SAVE", json=payload).json()["changes"] == []
    db.expire_all()
    kept = {v.VarName: v.VarValue for v in db.query(WorkflowItemVariable)}
    assert kept == {"Code": "8", "Token": "s3cret"}


def test_a_bad_variable_name_on_a_use_is_refused_naming_the_use(client, coded, flow, db):
    flow("WF_BAD", [("A", coded("A"))])
    db.commit()
    saved = client.get(f"{ROUTE}/WF_BAD").json()
    item = saved["items"][0]
    payload = {"job_key": "WF_BAD", "job_type": "WORKFLOW",
               "items": [{"id": item["id"], "name": "A", "job_key": "A", "variables": [{"name": "no good", "value": "1"}]}]}
    result = client.put(f"{ROUTE}/WF_BAD", json=payload)
    assert result.status_code == 400 or result.status_code == 422, result.text
    assert "'A': Invalid variable name 'no good'" in result.text


# ---------- The setting ----------

def test_an_order_saved_before_gets_the_new_levels_in_their_places(db):
    db.add(SettingValue(SettingKey="VariablePrecedence", SettingValue="ENV,SYS,ENTITY,APP,ENDPOINT,TAG,JOB"))
    db.flush()
    assert settings.current(db, "VariablePrecedence") == settings.current(None, "VariablePrecedence") == [
        "ENV", "SYS", "ENTITY", "APP", "ENDPOINT", "TAG", "WORKFLOW", "JOB", "USE"]


# ---------- Checking a job as a workflow runs it ----------

def test_a_job_is_checked_as_its_workflow_runs_it_or_on_its_own(client, coded, flow, seed, db):
    workflow = flow("WF_CTX", [("Needs", coded("NEEDS_CODE"))])
    seed.set_vars(workflow, Code="2")
    db.commit()
    own = client.get(f"{ROUTE}/NEEDS_CODE/check").json()
    assert not own["valid"] and "checked_as" not in own        # left out, as for every existing caller
    in_flow = client.get(f"{ROUTE}/NEEDS_CODE/check", params={"workflow": "WF_CTX", "use": "Needs"}).json()
    assert in_flow["valid"], in_flow
    assert in_flow["checked_as"] == "workflow 'WF_CTX', as 'Needs'"


def test_a_use_that_is_not_there_or_runs_another_job_is_refused(client, coded, flow, seed, db):
    flow("WF_CTX2", [("Needs", coded("NEEDS_CODE"))])
    coded("OTHER")
    db.commit()
    missing = client.get(f"{ROUTE}/NEEDS_CODE/check", params={"workflow": "WF_CTX2", "use": "Nope"})
    assert missing.status_code == 404 and "has no use 'Nope' of job 'NEEDS_CODE'" in missing.text
    wrong_job = client.get(f"{ROUTE}/OTHER/check", params={"workflow": "WF_CTX2", "use": "Needs"})
    assert wrong_job.status_code == 404
    half = client.get(f"{ROUTE}/NEEDS_CODE/check", params={"workflow": "WF_CTX2"})
    assert half.status_code == 422


def test_the_preview_resolves_a_job_as_its_workflow_runs_it(client, coded, flow, seed, db):
    workflow = flow("WF_CTX3", [("Needs", coded("NEEDS_CODE"))])
    seed.set_vars(workflow, Code="2")
    use_variable(db, workflow, "Needs", "Code", "9")
    db.commit()
    saved = client.get(f"{ROUTE}/NEEDS_CODE").json()
    payload = {"job_key": "NEEDS_CODE", "description": None, "active": True, "success_return_codes": SUCCESS,
               "steps": [{"id": s["id"], "title": s["title"], "name": s["name"], "step_type": s["step_type"],
                          "parameters": s["parameters"]} for s in saved["steps"]]}
    alone = client.post(f"{ROUTE}/preview", params={"existing_key": "NEEDS_CODE"}, json=payload).json()
    assert not alone["valid"]
    together = client.post(f"{ROUTE}/preview", params={"existing_key": "NEEDS_CODE", "workflow": "WF_CTX3", "use": "Needs"},
                           json=payload).json()
    assert together["valid"], together
    assert together["checked_as"] == "workflow 'WF_CTX3', as 'Needs'"
    assert together["steps"][0]["ReturnCode"]["resolved"] == "9"            # the use's value beats the workflow's

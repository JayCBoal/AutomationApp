"""
Conditions in workflows (docs/WORKFLOWS_PHASE4.md): three answers and Explain's parts; the outputs
of a job in a workflow; Custom rules and completion rules, saved through /api/v1/jobs and carried
out by the workflow runner; a job reporting the files it delivered with its end.
"""
import json

import pytest

from core.models import ConditionCheck, Job, Variable, WorkflowItem, WorkflowPrerequisite
from engine import conditions, workflow_conditions
from engine.telemetry_client import LocalSpoolTelemetryClient
from test_workflow_runner import flow, results, run_flow, sim, start, states  # noqa: F401 (fixtures)

ROUTE = "/api/v1/jobs"


def custom(db, workflow_key, name, rule):
    """Gives the job named name in the workflow a Custom rule; the jobs it names become its prerequisites."""
    workflow = db.query(Job).filter(Job.JobKey == workflow_key).one()
    items = {i.ItemName: i for i in workflow.items}
    item = items[name]
    item.JoinRule, item.StartRule = "CUSTOM", rule
    item.prerequisites.clear()
    for target in workflow_conditions.named_jobs(rule):
        item.prerequisites.append(WorkflowPrerequisite(target=items[target], Test="RULE"))
    db.commit()


def checks(db):
    return [(c.Path, c.Kind, c.Result) for c in db.query(ConditionCheck).order_by(ConditionCheck.id)]


# ---------- Three answers, and Explain's parts ----------

def test_a_condition_has_three_answers_with_unknown_values():
    rule = "(%{A.Succeeded} AND %{B.Succeeded}) OR %{C.Succeeded}"
    unknown = {"%{A.Succeeded}": None, "%{B.Succeeded}": None, "%{C.Succeeded}": None}
    assert conditions.decide(rule, unknown) is None
    assert conditions.decide(rule, {**unknown, "%{C.Succeeded}": 1}) is True       # TRUE OR unknown
    assert conditions.decide(rule, {**unknown, "%{C.Succeeded}": 0}) is None
    assert conditions.decide(rule, {**unknown, "%{A.Succeeded}": 0, "%{C.Succeeded}": 0}) is False   # FALSE AND unknown


def test_null_tests_are_found_so_a_rule_using_them_waits_for_all_its_jobs():
    assert conditions.uses_null_tests("%{A.Reason} IS NULL")
    assert conditions.uses_null_tests("coalesce(%{A.FileCount}, 0) > 0")
    assert not conditions.uses_null_tests("%{A.Succeeded} OR %{B.Status} = 'IS'")     # text in quotes is not a word


def test_explain_breaks_a_condition_into_its_parts_each_with_its_answer():
    values = {"%{A.FileCount}": 3, "%{B.Succeeded}": 0, "%{C.Succeeded}": None}
    tree = conditions.explain("%{A.FileCount} BETWEEN 1 AND 5 AND (%{B.Succeeded} OR %{C.Succeeded})", values)
    assert (tree["join"], tree["result"]) == ("AND", None)
    first, second = tree["parts"]
    assert (first["text"], first["result"]) == ("%{A.FileCount} BETWEEN 1 AND 5", True)     # BETWEEN keeps its AND
    assert (second["text"], second["join"], second["result"]) == ("%{B.Succeeded} OR %{C.Succeeded}", "OR", None)
    assert [p["result"] for p in second["parts"]] == [False, None]


# ---------- The outputs of a job in a workflow ----------

def test_every_output_is_unknown_until_the_job_ends_and_bypassed_counts_as_succeeded():
    assert set(workflow_conditions.item_values("A", "RUNNING", None, None, None, None, None, None).values()) == {None}
    bypassed = workflow_conditions.item_values("A", "BYPASSED", None, "DISABLED_PASS_THROUGH", None, None, None, None)
    assert (bypassed["%{A.Succeeded}"], bypassed["%{A.Bypassed}"], bypassed["%{A.ReturnCode}"]) == (1, 1, 0)
    not_run = workflow_conditions.item_values("A", "NOT_RUN", None, "CANCELLED", None, None, None, None)
    assert (not_run["%{A.Ended}"], not_run["%{A.NotRun}"], not_run["%{A.Succeeded}"]) == (1, 1, 0)


def test_a_workflow_condition_is_checked_against_its_jobs_and_their_outputs():
    problems, warnings = workflow_conditions.check(
        "%{Load.Succeeded} AND %{Nope.Status} = 'X' OR %{Load.Colour} = 1 OR %{Load.FileCount} > '3'", ["Load"])
    assert problems == ["%{Nope.Status}: no job in this workflow is named Nope.",
                        "%{Load.Colour}: a job has no output 'Colour'. It has " + ", ".join(workflow_conditions.OUTPUTS) + "."]
    assert warnings and "compares a number with text" in warnings[0]


def test_renaming_carries_into_a_condition_and_two_names_can_swap():
    assert workflow_conditions.rename("%{A.Succeeded} OR %{B.Failed} OR %{AB.Ended}", {"A": "B", "B": "A"}) \
        == "%{B.Succeeded} OR %{A.Failed} OR %{AB.Ended}"


# ---------- A job reports what it delivered ----------

def test_a_job_reports_the_files_it_delivered_with_its_end_counting_each_destination_once(tmp_path):
    client = LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T1")
    client.start_run("JOB")
    client.log_operation("COPY", "SUCCESS", dest_path="/out", dest_filename="a.csv", dest_size=10)
    client.log_operation("ZIP", "SUCCESS", dest_path="/out", dest_filename="all.zip", dest_size=7)
    client.log_operation("ZIP", "SUCCESS", dest_path="/out", dest_filename="all.zip", dest_size=7)   # a second file into it
    client.log_operation("COPY", "FAILED", dest_path="/out", dest_filename="b.csv", dest_size=5)
    client.log_operation("CHECK", "SUCCESS", source_path="/in", source_filename="c.csv", source_size=99)
    client.end_run("SUCCESS", return_code=0)
    client.close()
    end = [json.loads(line) for line in open(client.completed_file_path)][-1]
    assert (end["Record"], end["FileCount"], end["Bytes"]) == ("RUN_END", 2, 17)


# ---------- Custom rules, run ----------

def test_a_custom_rule_starts_its_job_as_soon_as_it_is_true(sim, flow, run_flow, db):
    flow("EARLY", [("Slow", sim("SLOW", wait=4)), ("Other", sim("OTHER", wait=4)), ("Quick", sim("QUICK")),
                   ("Publish", sim("PUBLISH"))])
    custom(db, "EARLY", "Publish", "(%{Slow.Succeeded} AND %{Other.Succeeded}) OR %{Quick.Succeeded}")

    code, run, items, log = run_flow("EARLY")

    assert code == 0, log
    assert items["Publish"].Status == "SUCCESS"
    assert items["Publish"].child_run.StartedDateTime < items["Slow"].child_run.EndedDateTime
    assert checks(db) == [("Publish", "START_RULE", "TRUE")]
    assert "Custom rule of 'Publish': (%{Slow.Succeeded} AND %{Other.Succeeded}) OR %{Quick.Succeeded} is true" in log


def test_a_custom_rule_that_is_false_makes_its_job_not_run_and_explain_has_its_values(sim, flow, run_flow, db):
    flow("FALSE_RULE", [("Load", sim("LOAD", code=4, success="0,4")), ("Report", sim("REPORT"))])
    custom(db, "FALSE_RULE", "Report", "%{Load.ReturnCode} = 0")

    code, run, items, log = run_flow("FALSE_RULE")

    assert states(items)["Report"] == ("NOT_RUN", "PREREQUISITES_NOT_MET", None)
    assert "'Report' will not run: its Custom rule is false: %{Load.ReturnCode} = 0." in log
    check = db.query(ConditionCheck).one()
    assert (check.Result, json.loads(check.ValuesJson)) == ("FALSE", {"%{Load.ReturnCode}": 4})


def test_a_custom_rule_naming_no_job_tests_variables_when_the_workflow_starts(sim, flow, run_flow, db):
    flow("REGIONAL", [("EU_only", sim("EU_ONLY")), ("US_only", sim("US_ONLY"))])
    workflow = db.query(Job).filter(Job.JobKey == "REGIONAL").one()
    db.add(Variable(MasterObject_id=workflow.MasterObject_id, VarName="Region", VarValue="EU"))
    custom(db, "REGIONAL", "EU_only", "${Region} = 'EU'")
    custom(db, "REGIONAL", "US_only", "${Region} = 'US'")

    code, run, items, log = run_flow("REGIONAL")

    assert code == 0, log
    assert (items["EU_only"].Status, items["US_only"].Status) == ("SUCCESS", "NOT_RUN")


def test_a_rule_using_is_null_waits_until_all_its_jobs_have_ended(sim, flow, run_flow, db):
    flow("NULLS", [("Slow", sim("SLOW", wait=3)), ("Quick", sim("QUICK")), ("After", sim("AFTER"))])
    custom(db, "NULLS", "After", "%{Quick.Succeeded} OR %{Slow.Reason} IS NULL")

    code, run, items, log = run_flow("NULLS")

    assert items["After"].Status == "SUCCESS"
    assert items["After"].child_run.StartedDateTime >= items["Slow"].child_run.EndedDateTime


# ---------- Completion rules, run ----------

def test_succeeds_when_decides_the_workflow_and_the_return_code_can_come_from_a_job(sim, flow, run_flow, db):
    flow("RULED", [("Load", sim("LOAD", fail=True)), ("Check", sim("CHECK", code=4, success="0,4"))])
    workflow = db.query(Job).filter(Job.JobKey == "RULED").one()
    workflow.SucceedsWhen, workflow.ReturnCodeFrom = "%{Check.Succeeded}", "Check"
    db.commit()

    code, run, items, log = run_flow("RULED")

    assert code == 0, log                       # Load's failure went unhandled, but Succeeds when holds
    assert (run.Status, run.Reason, run.ReturnCode) == ("SUCCESS", None, 4)
    assert checks(db) == [(None, "SUCCEEDS_WHEN", "TRUE")]


def test_a_workflow_whose_succeeds_when_is_false_fails_saying_so(sim, flow, run_flow, db):
    flow("STRICT", [("Load", sim("LOAD"))])
    workflow = db.query(Job).filter(Job.JobKey == "STRICT").one()
    workflow.SucceedsWhen = "%{Load.FileCount} > 0"
    db.commit()

    code, run, items, log = run_flow("STRICT")

    assert code == 1
    assert (run.Status, run.Reason, run.ReturnCode) == ("FAILED", "SUCCEEDS_WHEN", 1)
    assert run.ErrorMessage == "Succeeds when does not hold: %{Load.FileCount} > 0"
    assert (items["Load"].child_run.FileCount, run.FileCount) == (0, 0)


# ---------- Saving, through the API ----------

def use(job_key, name, after=(), **more):
    return {"job_key": job_key, "name": name, "prerequisites": [{"target": t, "test": "SUCCESS"} for t in after], **more}


@pytest.fixture
def sims(seed, db):
    for key in ("LOAD", "CHECK", "REPORT"):
        seed.step(seed.job(key), 1, "SIMULATE", title="Pretend")
    db.commit()


def test_a_custom_rule_is_saved_and_the_jobs_it_names_become_its_prerequisites(client, sims, db):
    rule = "%{Load.Succeeded} OR %{Check.ReturnCode} IN (0, 4)"
    payload = {"job_key": "WF", "job_type": "WORKFLOW", "items": [
        use("LOAD", "Load"), use("CHECK", "Check"),
        use("REPORT", "Report", after=["Load"], join="CUSTOM", rule=rule)]}
    response = client.post(ROUTE, json=payload)
    assert response.status_code == 201, response.text
    report = response.json()["job"]["items"][2]
    assert (report["join"], report["rule"]) == ("CUSTOM", rule)
    assert [(p["target"], p["test"], p["return_codes"]) for p in report["prerequisites"]] == [
        ("Load", "RULE", None), ("Check", "RULE", None)]


@pytest.mark.parametrize("rule, message", [
    ("", "'Report' starts by a Custom rule, but the rule is empty."),
    ("%{Nope.Succeeded}", "'Report': its Custom rule: %{Nope.Status}"),
    ("%{Report.Succeeded}", "'Report': its Custom rule names 'Report' itself."),
    ("%{Load.Succeeded} AND", "'Report': its Custom rule: The condition stops before it is complete."),
])
def test_a_custom_rule_with_a_problem_is_refused_saying_why(client, sims, rule, message):
    payload = {"job_key": "WF", "job_type": "WORKFLOW", "items": [
        use("LOAD", "Load"), use("REPORT", "Report", join="CUSTOM", rule=rule)]}
    response = client.post(ROUTE, json=payload)
    assert response.status_code == 422
    assert message.split(":")[0] in response.json()["detail"]
    if "Nope" not in rule:
        assert message in response.json()["detail"]


def test_renaming_a_job_renames_it_in_custom_rules_and_completion_rules(client, sims, db):
    payload = {"job_key": "WF", "job_type": "WORKFLOW", "succeeds_when": "%{Load.Succeeded}", "return_code_from": "Load",
               "items": [use("LOAD", "Load"), use("REPORT", "Report", join="CUSTOM", rule="%{Load.Succeeded}")]}
    saved = client.post(ROUTE, json=payload).json()["job"]
    items = saved["items"]
    payload["items"] = [{**use("LOAD", "Extract"), "id": items[0]["id"]},
                        {**use("REPORT", "Report", join="CUSTOM", rule="%{Load.Succeeded}"), "id": items[1]["id"]}]
    response = client.put(f"{ROUTE}/WF", json=payload)
    assert response.status_code == 200, response.text
    job = response.json()["job"]
    assert job["items"][1]["rule"] == "%{Extract.Succeeded}"
    assert (job["succeeds_when"], job["return_code_from"]) == ("%{Extract.Succeeded}", "Extract")


def test_completion_rules_are_checked_against_the_workflows_jobs(client, sims):
    payload = {"job_key": "WF", "job_type": "WORKFLOW", "items": [use("LOAD", "Load")], "succeeds_when": "%{Gone.Succeeded}"}
    assert "Succeeds when: %{Gone.Succeeded}: no job in this workflow is named Gone." in client.post(ROUTE, json=payload).json()["detail"]
    payload = {"job_key": "WF", "job_type": "WORKFLOW", "items": [use("LOAD", "Load")], "return_code_from": "Gone"}
    assert "comes from 'Gone', which is not a job in this workflow" in client.post(ROUTE, json=payload).json()["detail"]


def test_the_condition_box_checks_as_you_type_and_lists_the_outputs(client):
    response = client.post("/api/v1/conditions/check", json={"condition": "%{Load.Succeeded} AND %{X.Failed}",
                                                             "names": ["Load"]})
    assert response.json() == {"problems": ["%{X.Failed}: no job in this workflow is named X."], "warnings": [],
                               "named": ["Load", "X"]}
    outputs = client.get("/api/v1/conditions/outputs").json()
    assert [o["name"] for o in outputs][:3] == ["Succeeded", "Failed", "Ended"]


def test_a_missing_variable_in_a_rule_stops_the_workflow_before_it_runs(client, sims):
    payload = {"job_key": "WF", "job_type": "WORKFLOW",
               "items": [use("LOAD", "Load", join="CUSTOM", rule="${Region} = 'EU'")]}
    result = client.post(ROUTE, json=payload).json()
    assert not result["valid"]
    assert any("'Load': its Custom rule" in p and "Region" in p for p in result["problems"])

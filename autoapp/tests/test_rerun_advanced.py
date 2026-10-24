"""
Advanced rerun of a workflow run (docs/WORKFLOWS_PHASE7.md, step 6a): an action for each item named, the shortcuts that
fill the list in, a run that Succeeded reopened, and the values a restarted job may be given. The engine is driven the
way the API starts it (--reopen advanced --reopen-items); the API tests go through the plan and the request.
"""
import json
from urllib.parse import urlencode

import pytest

from core.models import Audit, RunRestart, WorkflowItem, WorkflowPrerequisite
from test_launches import follow, get, post     # noqa: F401
from test_workflow_reopen import fix, framed, reopen, run_workflow, two_stage    # noqa: F401  (fixtures)
from test_frames_engine import tree     # noqa: F401  (fixture)
from test_workflow_runner import flow, results, run_flow, sim, start    # noqa: F401  (fixtures)


def advanced(reopen, run, items, *extra):
    return reopen(run, "advanced", "--reopen-items", json.dumps(items), *extra)


def attempts(items):
    return {name: (item.Status, item.Attempt) for name, item in items.items()}


# ---------- The engine: an action for each item ----------

def test_only_the_items_named_run_again_and_the_rest_stays_as_it_ended(sim, flow, run_flow, reopen, db):
    two_stage(sim, flow)
    _, first, _, _ = run_flow("WF")
    fix(db, "LOAD")

    done = advanced(reopen, first, {"Load": "restart"})

    run, items, log = results(db, "WF")
    assert run.id == first.id, done.stdout + done.stderr + log
    assert attempts(items) == {"Extract": ("SUCCESS", 1), "Load": ("SUCCESS", 2), "Report": ("NOT_RUN", 0)}


def test_a_job_that_succeeded_can_be_started_again_and_what_follows_it_goes_on(sim, flow, run_flow, reopen, db):
    two_stage(sim, flow)
    _, first, _, _ = run_flow("WF")
    fix(db, "LOAD")

    advanced(reopen, first, {"Extract": "restart", "Load": "resume", "Report": "restart"})

    run, items, log = results(db, "WF")
    assert attempts(items) == {"Extract": ("SUCCESS", 2), "Load": ("SUCCESS", 2), "Report": ("SUCCESS", 1)}, log
    assert run.Status == "SUCCESS"


def test_a_run_that_succeeded_is_reopened_and_one_job_runs_again(sim, flow, run_flow, reopen, db):
    flow("WF", [("Extract", sim("EXTRACT")), ("Load", sim("LOAD"), ["Extract"])])
    _, first, before, _ = run_flow("WF")
    assert first.Status == "SUCCESS"

    advanced(reopen, first, {"Load": "restart"})

    run, items, log = results(db, "WF")
    assert (run.id, run.Status) == (first.id, "SUCCESS"), log
    assert attempts(items) == {"Extract": ("SUCCESS", 1), "Load": ("SUCCESS", 2)}


def test_an_item_inside_an_embedded_workflow_runs_again_through_the_workflow_that_holds_it(sim, tree, run_flow, reopen, db):
    framed(sim, tree, db)
    _, first, before, _ = run_flow("TOP")
    frame_run = before["Frame"].ChildRun_id
    fix(db, "PULL")

    advanced(reopen, first, {"Frame/Pull": "resume"})

    _, items, log = results(db, "TOP")
    inner_run, inner, _ = results(db, "TOP.Frame")
    assert items["Frame"].ChildRun_id == frame_run                      # the workflow on the way is reopened, not copied
    assert attempts(inner) == {"Pull": ("SUCCESS", 2), "Push": ("NOT_RUN", 0)}, log
    assert items["Prep"].Attempt == 1 and items["Done"].Status == "NOT_RUN"


def test_an_embedded_workflow_named_for_a_restart_runs_again_as_a_new_run(sim, tree, run_flow, reopen, db):
    framed(sim, tree, db)
    _, first, before, _ = run_flow("TOP")
    frame_run = before["Frame"].ChildRun_id
    fix(db, "PULL")

    advanced(reopen, first, {"Frame": "restart", "Done": "restart"})

    _, items, log = results(db, "TOP")
    assert items["Frame"].ChildRun_id != frame_run and items["Frame"].Status == "SUCCESS", log
    assert items["Done"].Status == "SUCCESS" and items["Prep"].Attempt == 1


# ---------- The engine: values for a restart ----------

@pytest.fixture
def valued(seed, flow, run_flow, db):
    load, extract, report = seed.job("LOAD"), seed.job("EXTRACT"), seed.job("REPORT")
    seed.step(load, 1, "SIMULATE", title="Load", Fail="${Fail}", Messages="Region ${Region}")
    seed.step(extract, 1, "SIMULATE", title="Extract", Fail="False")
    seed.step(report, 1, "SIMULATE", title="Report", Fail="False")
    workflow = flow("WF", [("Extract", extract), ("Load", load, ["Extract"]), ("Report", report, ["Load"])])
    seed.set_vars(workflow, Fail="True", Region="EU")
    return run_flow("WF")


def test_a_restarted_job_pins_only_the_value_typed_and_reads_the_rest_fresh(valued, reopen, db, tmp_path):
    _, first, _, _ = valued

    done = advanced(reopen, first, {"Load": "restart"}, "--edit-values", json.dumps({"levels": {}, "jobs": {"Load": {"Fail": "False"}}}))

    run, items, log = results(db, "WF")
    assert items["Load"].Status == "SUCCESS", done.stdout + done.stderr + log
    job_logs = " ".join(path.read_text() for path in (tmp_path / "logs").rglob("*.log"))
    assert "Region EU" in job_logs                      # not typed, so read as the workflow holds it


def test_a_restarted_job_without_a_typed_value_reads_everything_fresh(valued, reopen, db):
    _, first, _, _ = valued

    advanced(reopen, first, {"Load": "restart"})

    _, items, _ = results(db, "WF")
    assert items["Load"].Status == "FAILED" and items["Load"].Attempt == 2        # the workflow still says Fail is True


# ---------- The API ----------

@pytest.fixture
def failed(seed, flow, live_api, db):
    """Extract succeeds; Load fails while the workflow's Fail is True; Report waits for Load."""
    load, extract, report = seed.job("LOAD"), seed.job("EXTRACT"), seed.job("REPORT")
    seed.step(load, 1, "SIMULATE", title="Load", Fail="${Fail}", Messages="Region ${Region}")
    seed.step(extract, 1, "SIMULATE", title="Extract", Fail="False")
    seed.step(report, 1, "SIMULATE", title="Report", Fail="False")
    workflow = flow("WF", [("Extract", extract), ("Load", load, ["Extract"]), ("Report", report, ["Load"])])
    seed.set_vars(workflow, Fail="True", Region="EU")
    db.commit()
    return run_workflow(live_api, "WF", "UI-A1")


def plan_of(api, run, **query):
    pairs = [("advanced", "true")] + [(k, item) for k, v in query.items() for item in (v if isinstance(v, list) else [v])]
    return get(f"{api}/api/v1/runs/{run['run_id']}/rerun-plan?{urlencode(pairs)}").json()


def rerun(api, run, **body):
    return post(f"{api}/api/v1/runs/{run['run_id']}/rerun", json={"kind": "advanced", **body})


def test_the_plan_lists_every_item_and_says_which_can_be_picked_up(failed, live_api):
    plan = plan_of(live_api, failed)

    assert plan["advanced"] and plan["refusal"] is None
    by_path = {c["path"]: c for c in plan["choices"]}
    assert [c["path"] for c in plan["choices"]] == ["Extract", "Load", "Report"]
    assert (by_path["Load"]["can_resume"], by_path["Extract"]["can_resume"], by_path["Report"]["can_resume"]) == (True, False, False)
    assert "can only be run again from the beginning" in by_path["Extract"]["resume_problem"]


def test_from_a_chosen_job_names_it_and_everything_that_waits_for_it(failed, live_api):
    plan = plan_of(live_api, failed, shortcut="from", chosen=["Load"])

    assert plan["named_items"] == {"Load": "resume", "Report": "restart"}
    assert plan["items_problem"] is None
    assert [(i["path"], i["what"]) for i in plan["items"]] == [("Load", "goes on from attempt 1"), ("Report", "runs again from the beginning")]


def test_only_a_chosen_job_names_just_that_job_and_a_succeeded_one_is_restarted(failed, live_api):
    plan = plan_of(live_api, failed, shortcut="only", chosen=["Extract", "Load"], chosen_as="resume")

    assert plan["named_items"] == {"Extract": "restart", "Load": "resume"}


def test_from_a_chosen_job_can_restart_the_failed_ones_too(failed, live_api):
    plan = plan_of(live_api, failed, shortcut="from", chosen=["Extract"], chosen_as="restart")

    assert plan["named_items"] == {"Extract": "restart", "Load": "restart", "Report": "restart"}


def test_from_a_chosen_job_runs_it_and_what_follows_and_records_it(failed, live_api, db):
    response = rerun(live_api, failed, shortcut="from", chosen=["Load"], level_edits={"": {"workflow": {"Fail": "False"}}})
    assert response.status_code == 202, response.text
    _, run = follow(live_api, response.json())

    assert run["status"] == "SUCCESS"
    assert {i["name"]: i["status"] for i in run["items"]} == {"Extract": "SUCCESS", "Load": "SUCCESS", "Report": "SUCCESS"}
    row = db.query(RunRestart).one()
    assert row.Kind == "ADVANCED" and "Load" in row.Details
    assert db.query(Audit).filter(Audit.Action == "JOB_RERUN_ADVANCED").count() == 1


def test_a_succeeded_run_is_offered_to_advanced_and_refused_by_the_plain_buttons(failed, live_api):
    ok = rerun(live_api, failed, shortcut="from", chosen=["Load"], level_edits={"": {"workflow": {"Fail": "False"}}})
    follow(live_api, ok.json())

    plan = plan_of(live_api, failed)
    plain = post(f"{live_api}/api/v1/runs/{failed['run_id']}/rerun", json={"kind": "resume"})

    assert plan["refusal"] is None and len(plan["choices"]) == 3
    assert plain.status_code == 409 and "succeeded" in plain.text


def test_a_restart_that_types_one_value_is_recorded_by_name_for_that_job(failed, live_api, db):
    response = rerun(live_api, failed, items={"Load": "restart"}, job_edits={"Load": {"Fail": "False"}})
    assert response.status_code == 202, response.text
    _, run = follow(live_api, response.json())

    assert {i["name"]: i["status"] for i in run["items"]}["Load"] == "SUCCESS"
    rows = db.query(Audit).filter(Audit.Action == "JOB_RESTARTED_WITH_EDITS").all()
    assert len(rows) == 1 and "Restarted 'LOAD' with Fail set to 'False'" in json.loads(rows[0].Details)["changes"][0]


def test_nothing_is_recorded_for_a_request_that_is_refused(failed, live_api, db):
    nothing = rerun(live_api, failed, items={})
    unknown = rerun(live_api, failed, items={"Nope": "restart"})
    succeeded = rerun(live_api, failed, items={"Extract": "resume"})
    both = rerun(live_api, failed, items={"Extract": "restart"}, shortcut="sideways", chosen=["Load"])

    assert nothing.status_code == 422 and "at least one item" in nothing.text
    assert unknown.status_code == 409 and "'Nope' is not an item of this run" in unknown.text
    assert succeeded.status_code == 409 and "can only be run again from the beginning" in succeeded.text
    assert both.status_code == 422 and "Choose 'from'" in both.text
    assert db.query(RunRestart).count() == 0 and db.query(Audit).filter(Audit.Action == "JOB_RERUN_ADVANCED").count() == 0


def test_a_workflow_edited_since_the_run_is_refused(failed, live_api, db):
    item = db.query(WorkflowItem).filter(WorkflowItem.ItemName == "Report").one()
    db.query(WorkflowPrerequisite).filter(WorkflowPrerequisite.Item_id == item.id).delete()
    db.delete(item)
    db.commit()

    refused = rerun(live_api, failed, items={"Load": "restart"})

    assert refused.status_code == 409 and "has been changed since this run" in refused.text


def test_a_cancelled_run_is_reopened_by_resume_and_by_advanced(failed, live_api, db):
    from core.models import JobRun, WorkflowRunItem
    run = db.query(JobRun).filter(JobRun.RunID == failed["run_id"]).one()
    run.Reason = "CANCELLED"
    db.query(WorkflowRunItem).filter(WorkflowRunItem.ItemName == "Report").one().Reason = "CANCELLED"
    db.commit()

    plain = get(f"{live_api}/api/v1/runs/{failed['run_id']}/rerun-plan").json()
    plan = plan_of(live_api, failed, shortcut="from", chosen=["Load"])

    assert plain["refusal"] is None and plain["can_resume"]
    assert plan["refusal"] is None and plan["named_items"] == {"Load": "resume", "Report": "restart"}

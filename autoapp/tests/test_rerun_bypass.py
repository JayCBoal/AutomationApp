"""
Bypass and Don't run in an Advanced rerun (docs/WORKFLOWS_PHASE7.md, step 6b): the operator moves past an item
without running it. Bypass ends it Bypassed (it counts as succeeded, so what waits for it goes on); Don't run ends it
Skipped (so what waits for its success does not run). The engine is driven the way the API starts it; the API tests go
through the plan and the request.
"""
import json

from app.models import RunRestart
from test_launches import follow, get, post     # noqa: F401
from test_rerun_advanced import advanced, attempts, failed, plan_of, rerun    # noqa: F401  (fixtures)
from test_workflow_reopen import framed, reopen, run_workflow, two_stage    # noqa: F401  (fixtures)
from test_frames_engine import tree     # noqa: F401  (fixture)
from test_workflow_runner import flow, results, run_flow, sim, start    # noqa: F401  (fixtures)


# ---------- The engine ----------

def test_a_bypassed_job_counts_as_succeeded_and_what_waits_for_it_goes_on(sim, flow, run_flow, reopen, db):
    two_stage(sim, flow)
    _, first, _, _ = run_flow("WF")

    done = advanced(reopen, first, {"Load": "bypass", "Report": "restart"})

    run, items, log = results(db, "WF")
    assert items["Load"].Status == "BYPASSED" and items["Load"].Reason == "MARKED_DONE", done.stdout + done.stderr + log
    assert items["Load"].StatusBeforeOverride == "FAILED" and items["Load"].Attempt == 1      # it did not run again
    assert (items["Report"].Status, run.Status) == ("SUCCESS", "SUCCESS")
    assert "bypassed by the operator" in log


def test_a_job_left_unrun_ends_skipped_and_what_waits_for_its_success_does_not_run(sim, flow, run_flow, reopen, db):
    two_stage(sim, flow)
    _, first, _, _ = run_flow("WF")

    done = advanced(reopen, first, {"Load": "dont_run", "Report": "restart"})

    run, items, log = results(db, "WF")
    assert items["Load"].Status == "SKIPPED" and items["Load"].Attempt == 1, done.stdout + done.stderr + log
    assert (items["Report"].Status, items["Report"].Reason) == ("NOT_RUN", "PREREQUISITES_NOT_MET")
    assert run.Status == "SUCCESS"                       # Skipped and Not run do not count against it (D29)


def test_what_waits_for_a_skipped_job_to_end_runs_anyway(sim, flow, run_flow, reopen, db):
    flow("WF", [("Extract", sim("EXTRACT")), ("Load", sim("LOAD", fail=True), ["Extract"]),
                ("Report", sim("REPORT"), [("Load", "ENDED")])])
    _, first, _, _ = run_flow("WF")

    advanced(reopen, first, {"Load": "dont_run", "Report": "restart"})

    _, items, log = results(db, "WF")
    assert (items["Load"].Status, items["Report"].Status) == ("SKIPPED", "SUCCESS"), log


def test_a_job_that_did_not_run_can_be_bypassed_too(sim, flow, run_flow, reopen, db):
    two_stage(sim, flow)
    _, first, before, _ = run_flow("WF")
    assert before["Report"].Status == "NOT_RUN"

    advanced(reopen, first, {"Report": "bypass"})

    _, items, _ = results(db, "WF")
    assert (items["Report"].Status, items["Report"].StatusBeforeOverride) == ("BYPASSED", "NOT_RUN")
    assert items["Load"].Status == "FAILED"                  # nothing else changed


def test_a_failed_embedded_workflow_can_be_bypassed_and_what_follows_it_runs(sim, tree, run_flow, reopen, db):
    framed(sim, tree, db)
    _, first, before, _ = run_flow("TOP")
    frame_run = before["Frame"].ChildRun_id

    advanced(reopen, first, {"Frame": "bypass", "Done": "restart"})

    run, items, log = results(db, "TOP")
    assert (items["Frame"].Status, items["Done"].Status, run.Status) == ("BYPASSED", "SUCCESS", "SUCCESS"), log
    assert items["Frame"].ChildRun_id == frame_run           # the frame itself was not opened


def test_a_job_inside_an_embedded_workflow_is_bypassed_through_the_workflow_that_holds_it(sim, tree, run_flow, reopen, db):
    framed(sim, tree, db)
    _, first, before, _ = run_flow("TOP")
    frame_run = before["Frame"].ChildRun_id

    advanced(reopen, first, {"Frame/Pull": "bypass", "Frame/Push": "restart", "Done": "restart"})

    _, items, log = results(db, "TOP")
    inner_run, inner, _ = results(db, "TOP.Frame")
    assert items["Frame"].ChildRun_id == frame_run
    assert (inner["Pull"].Status, inner["Push"].Status) == ("BYPASSED", "SUCCESS"), log
    assert (inner_run.Status, items["Done"].Status) == ("SUCCESS", "SUCCESS")


# ---------- The API ----------

def test_the_plan_words_a_bypass_and_a_dont_run(failed, live_api):
    plan = plan_of(live_api, failed, shortcut="only", chosen="Load", chosen_as="bypass")
    other = plan_of(live_api, failed, shortcut="only", chosen="Load", chosen_as="dont_run")

    assert plan["named_items"] == {"Load": "bypass"} and plan["items_problem"] is None
    assert plan["items"][0]["what"].startswith("is bypassed")
    assert other["items"][0]["what"].startswith("is not run")


def test_from_a_job_bypassed_lets_what_follows_run_and_records_it(failed, live_api, db):
    plan = plan_of(live_api, failed, shortcut="from", chosen="Load", chosen_as="bypass")
    assert plan["named_items"] == {"Load": "bypass", "Report": "restart"}

    response = rerun(live_api, failed, shortcut="from", chosen=["Load"], chosen_as="bypass")
    assert response.status_code == 202, response.text
    _, run = follow(live_api, response.json())

    assert {i["name"]: i["status"] for i in run["items"]} == {"Extract": "SUCCESS", "Load": "BYPASSED", "Report": "SUCCESS"}
    details = json.loads(db.query(RunRestart).one().Details)
    assert "Bypassed 'Load'." in details["items"]


def test_from_a_job_not_run_leaves_what_follows_unrun(failed, live_api):
    response = rerun(live_api, failed, shortcut="from", chosen=["Load"], chosen_as="dont_run")
    _, run = follow(live_api, response.json())

    assert {i["name"]: i["status"] for i in run["items"]} == {"Extract": "SUCCESS", "Load": "SKIPPED", "Report": "NOT_RUN"}


def test_an_item_that_succeeded_cannot_be_bypassed_and_nothing_is_recorded(failed, live_api, db):
    refused = rerun(live_api, failed, items={"Extract": "bypass"})
    same = rerun(live_api, failed, items={"Load": "bypass", "Report": "dont_run", "Extract": "dont_run"})
    unknown = rerun(live_api, failed, items={"Load": "skip"})

    assert refused.status_code == 409 and "'Extract'" in refused.text and "already counts as succeeded" in refused.text
    assert same.status_code == 202                      # a succeeded job may be left unrun; a not-run one too
    assert unknown.status_code in (409, 422)
    assert db.query(RunRestart).count() == 1


# ---------- Items that did not run wait their turn ----------

def test_bypassing_one_job_item_by_item_also_runs_what_did_not_run_because_of_it(failed, live_api):
    plan = plan_of(live_api, failed, items=json.dumps({"Load": "bypass"}))

    assert plan["named_items"] == {"Load": "bypass", "Report": "restart"}, plan
    assert {i["path"]: i["what"] for i in plan["items"]}["Report"].startswith("runs again")


def test_leave_not_run_keeps_the_item_as_it_is(failed, live_api):
    plan = plan_of(live_api, failed, items=json.dumps({"Load": "bypass", "Report": "leave"}))

    assert plan["named_items"] == {"Load": "bypass"} and plan["items_problem"] is None


def test_only_the_jobs_chosen_leaves_what_did_not_run_alone(failed, live_api):
    plan = plan_of(live_api, failed, shortcut="only", chosen="Load", chosen_as="restart")

    assert plan["named_items"] == {"Load": "restart"}


def test_choosing_only_leave_is_not_a_choice_to_run_anything(failed, live_api):
    plan = plan_of(live_api, failed, items=json.dumps({"Report": "leave"}))

    assert plan["named_items"] == {} and plan["items_problem"]


def test_a_not_run_item_is_started_through_the_request_too(failed, live_api, db):
    response = rerun(live_api, failed, items={"Load": "bypass"})
    assert response.status_code == 202, response.text

    _, run = follow(live_api, response.json())

    assert run["status"] == "SUCCESS"      # Report ran, and Load counted as succeeded

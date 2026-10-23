"""
Ignore a prerequisite and Reset counts in an Advanced rerun (docs/WORKFLOWS_PHASE7.md, step 6c). An ignored wait
holds for the one reopening and is back in force at the next; reset retry counts stay reset for later reopenings.
The engine is driven the way the API starts it (--ignore-waits, --reset-counts); the API tests go through the request.
"""
import json

from app.models import ReactionEvent, RunRestart, WorkflowItem, WorkflowPrerequisiteCheck
from test_launches import follow, get, post     # noqa: F401
from test_outside_engine import NEVER_OPEN, wait_for     # noqa: F401
from test_rerun_advanced import advanced, attempts, plan_of, rerun    # noqa: F401  (fixtures)
from test_workflow_reactions import react
from test_frames_engine import tree     # noqa: F401  (fixture)
from test_workflow_reopen import framed, reopen, run_workflow    # noqa: F401  (fixtures)
from test_workflow_runner import flow, results, run_flow, sim, start    # noqa: F401  (fixtures)


def blocked(sim, flow):
    """A fails; B fails; Load waits for both."""
    flow("WF", [("A", sim("A", fail=True)), ("B", sim("B", fail=True)), ("Load", sim("LOAD"), ["A", "B"])])


def ignoring(waits):
    return ["--ignore-waits", json.dumps(waits)]


# ---------- The engine: Ignore a prerequisite ----------

def test_a_job_whose_wait_is_ignored_starts_though_what_it_waited_for_failed(sim, flow, run_flow, reopen, db):
    flow("WF", [("Extract", sim("EXTRACT", fail=True)), ("Load", sim("LOAD"), ["Extract"])])
    _, first, before, _ = run_flow("WF")
    assert before["Load"].Status == "NOT_RUN"

    done = advanced(reopen, first, {"Load": "restart"}, *ignoring({"Load": ["Extract"]}))

    _, items, log = results(db, "WF")
    assert (items["Extract"].Status, items["Extract"].Attempt) == ("FAILED", 1), done.stdout + done.stderr + log
    assert items["Load"].Status == "SUCCESS"
    assert "'Load' will not wait for 'Extract'" in log


def test_the_wait_is_back_in_force_the_next_time(sim, flow, run_flow, reopen, db):
    flow("WF", [("Extract", sim("EXTRACT", fail=True)), ("Load", sim("LOAD"), ["Extract"])])
    _, first, _, _ = run_flow("WF")
    advanced(reopen, first, {"Load": "restart"}, *ignoring({"Load": ["Extract"]}))

    advanced(reopen, first, {"Load": "restart"})

    _, items, _ = results(db, "WF")
    assert (items["Load"].Status, items["Load"].Reason) == ("NOT_RUN", "PREREQUISITES_NOT_MET")


def test_only_the_wait_named_is_released(sim, flow, run_flow, reopen, db):
    blocked(sim, flow)
    _, first, _, _ = run_flow("WF")

    advanced(reopen, first, {"Load": "restart"}, *ignoring({"Load": ["A"]}))
    _, items, _ = results(db, "WF")
    assert items["Load"].Status == "NOT_RUN"                # it still waits for B

    advanced(reopen, first, {"Load": "restart"}, *ignoring({"Load": ["A", "B"]}))
    _, items, _ = results(db, "WF")
    assert items["Load"].Status == "SUCCESS"


def test_a_wait_outside_the_job_can_be_ignored_and_the_check_says_so(sim, flow, run_flow, reopen, db, seed):
    workflow = flow("WF", [("Report", sim("R"))])
    wait_for(seed, workflow, "Report", Kind="TIME", TargetName="Window", TimeCondition=NEVER_OPEN,
             WaitMode="MINUTES", WaitMinutes=0)
    _, first, before, _ = run_flow("WF")
    assert before["Report"].Status == "NOT_RUN"

    advanced(reopen, first, {"Report": "restart"}, *ignoring({"Report": ["Window"]}))

    run, items, log = results(db, "WF")
    results_of = [c.Result for c in db.query(WorkflowPrerequisiteCheck).filter(WorkflowPrerequisiteCheck.WorkflowRun_id == run.id)]
    assert items["Report"].Status == "SUCCESS", log
    assert "RELEASED" in results_of


def test_a_job_inside_an_embedded_workflow_has_its_wait_ignored_through_the_workflow_that_holds_it(sim, tree, run_flow, reopen, db):
    framed(sim, tree, db)
    _, first, before, _ = run_flow("TOP")
    frame_run = before["Frame"].ChildRun_id

    advanced(reopen, first, {"Frame/Push": "restart"}, *ignoring({"Frame/Push": ["Pull"]}))

    _, items, log = results(db, "TOP")
    inner_run, inner, _ = results(db, "TOP.Frame")
    assert items["Frame"].ChildRun_id == frame_run
    assert (inner["Pull"].Status, inner["Push"].Status) == ("FAILED", "SUCCESS"), log


# ---------- The engine: Reset counts ----------

def test_a_reset_gives_a_reaction_its_allowance_again(sim, flow, run_flow, reopen, db):
    load = sim("LOAD", fail=True)
    flow("WF", [("Load", load)])
    react(db, load, "FAILED", ("RERUN", {"MaxTimes": 1}))
    _, first, _, _ = run_flow("WF")

    advanced(reopen, first, {"Load": "restart"}, "--reset-counts")

    _, items, log = results(db, "WF")
    assert items["Load"].Attempt == 4, log               # the restart, and the Reaction's one go again


def test_without_a_reset_the_allowance_stays_used(sim, flow, run_flow, reopen, db):
    load = sim("LOAD", fail=True)
    flow("WF", [("Load", load)])
    react(db, load, "FAILED", ("RERUN", {"MaxTimes": 1}))
    _, first, _, _ = run_flow("WF")

    advanced(reopen, first, {"Load": "restart"})

    _, items, _ = results(db, "WF")
    assert items["Load"].Attempt == 3


def test_a_reset_made_at_an_earlier_restart_is_still_honoured_when_the_run_is_reopened_again(sim, flow, run_flow, reopen, db):
    load = sim("LOAD", fail=True)
    flow("WF", [("Load", load)])
    react(db, load, "FAILED", ("RERUN", {"MaxTimes": 1}))
    _, first, _, _ = run_flow("WF")
    db.add(RunRestart(RunID=first.RunID, Number=1, Kind="ADVANCED", Details=json.dumps({"counts_reset": True})))
    db.commit()

    advanced(reopen, first, {"Load": "restart"})

    _, items, log = results(db, "WF")
    assert items["Load"].Attempt == 4, log
    assert db.query(ReactionEvent).filter(ReactionEvent.Result == "LIMIT_REACHED").count() >= 1


# ---------- The API ----------

def blocked_run(sim, flow, live_api):
    flow("WF", [("A", sim("A", fail=True)), ("Load", sim("LOAD"), ["A"])])
    return run_workflow(live_api, "WF", "UI-WAIT")


def test_ignoring_a_wait_through_the_api_runs_the_job_and_records_it(sim, flow, live_api, db):
    first = blocked_run(sim, flow, live_api)
    plan = plan_of(live_api, first, shortcut="only", chosen="Load", chosen_as="restart")
    assert {c["path"]: c["waits"] for c in plan["choices"]}["Load"] == ["A"]

    response = rerun(live_api, first, shortcut="only", chosen=["Load"], chosen_as="restart", ignore={"Load": ["A"]})
    assert response.status_code == 202, response.text
    _, run = follow(live_api, response.json())

    assert {i["name"]: i["status"] for i in run["items"]} == {"A": "FAILED", "Load": "SUCCESS"}
    row = db.query(RunRestart).one()
    assert json.loads(row.Details)["ignored"] == [{"item": "Load", "prerequisite": "A"}]
    latest = run["restarts"][-1]
    assert latest["ignored"] == [{"item": "Load", "prerequisite": "A"}]
    assert latest["released"] == ["Ignored the wait of 'A' for 'Load'."]


def test_an_ignore_that_makes_no_sense_is_refused_and_nothing_is_recorded(sim, flow, live_api, db):
    first = blocked_run(sim, flow, live_api)

    no_such_wait = rerun(live_api, first, items={"Load": "restart"}, ignore={"Load": ["Zed"]})
    not_run_again = rerun(live_api, first, items={"A": "restart", "Load": "leave"}, ignore={"Load": ["A"]})
    passed_over = rerun(live_api, first, items={"Load": "bypass"}, ignore={"Load": ["A"]})
    unknown_item = rerun(live_api, first, items={"Load": "restart"}, ignore={"Nope": ["A"]})

    assert no_such_wait.status_code == 409 and "does not wait for 'Zed'" in no_such_wait.text
    assert not_run_again.status_code == 409 and "not run again" in not_run_again.text
    assert passed_over.status_code == 409 and "not run again" in passed_over.text
    assert unknown_item.status_code == 409 and "not an item of this run" in unknown_item.text
    assert db.query(RunRestart).count() == 0


def test_a_job_that_starts_by_a_custom_rule_cannot_have_one_wait_ignored(sim, flow, live_api, db):
    first = blocked_run(sim, flow, live_api)
    item = db.query(WorkflowItem).filter(WorkflowItem.ItemName == "Load").one()
    item.JoinRule, item.StartRule = "CUSTOM", "%{A.Succeeded}"
    db.commit()

    plan = plan_of(live_api, first)
    refused = rerun(live_api, first, items={"Load": "restart"}, ignore={"Load": ["A"]})

    assert {c["path"]: c["custom_rule"] for c in plan["choices"]}["Load"] is True
    assert refused.status_code == 409 and "Custom rule" in refused.text


def test_reset_counts_through_the_api_lasts_for_the_next_restart_too(sim, flow, live_api, db):
    load = sim("LOAD", fail=True)
    flow("WF", [("Load", load)])
    react(db, load, "FAILED", ("RERUN", {"MaxTimes": 1}))
    first = run_workflow(live_api, "WF", "UI-RESET")
    assert first["items"][0]["attempt"] == 2

    reset = rerun(live_api, first, items={"Load": "restart"}, reset_counts=True)
    _, run = follow(live_api, reset.json())
    assert run["items"][0]["attempt"] == 4                               # the restart, then the Reaction's one go again
    assert json.loads(db.query(RunRestart).one().Details)["counts_reset"] is True
    assert [r["released"] for r in run["restarts"] if r["kind"] == "ADVANCED"] == [["Reset the retry counts."]]

    again = rerun(live_api, first, items={"Load": "restart"})
    _, run = follow(live_api, again.json())
    assert run["items"][0]["attempt"] == 5                               # the allowance was used up after the reset

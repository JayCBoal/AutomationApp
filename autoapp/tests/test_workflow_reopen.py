"""
Reopening a workflow run that has ended (docs/WORKFLOWS_PHASE7.md, step 3): Resume goes on from the items that
failed or did not run, Restart runs every item again, and a frame or a job inside can be run again on its own.
The runs here are made of Simulate jobs; fixing a job is changing its Fail parameter between the runs.
"""
import json
import subprocess
import sys

import pytest

from app.models import Job, JobStep, JobStepParameter, ReactionEvent, WorkflowItem, WorkflowPrerequisite, WorkflowRunItem
from conftest import AUTOAPP_DIR, subprocess_env
from test_frames_engine import tree     # noqa: F401  (fixture)
from test_workflow_runner import flow, results, run_flow, sim, start    # noqa: F401  (fixtures)


def fix(db, job_key):
    """Mends a Simulate job: its step no longer fails."""
    steps = db.query(JobStep.id).join(Job, Job.MasterObject_id == JobStep.job_id).filter(Job.JobKey == job_key)
    for parameter in db.query(JobStepParameter).filter(JobStepParameter.ParamName == "Fail",
                                                       JobStepParameter.job_step_id.in_(steps)):
        parameter.ParamValue = "False"
    db.commit()


@pytest.fixture
def reopen(db, db_url, tmp_path):
    """Reopens a run the way the API does: the workflow runner again, on the same run ID. Returns the finished process."""
    def _reopen(run, kind, *extra):
        db.commit()
        env = {**subprocess_env(db_url), "AUTOAPP_WORKFLOW_POLL_SECONDS": "0.2"}
        done = subprocess.run(
            [sys.executable, "-m", "engine.runner", "--job-key", run.JobKey, "--instance-id", run.SchedulerInstanceID,
             "--spool-dir", str(tmp_path / "spool"), "--working-root", str(tmp_path / "work"), "--run-id", run.RunID,
             "--attempt", str(run.Attempt), "--reopen", kind, *extra],
            cwd=AUTOAPP_DIR, env=env, capture_output=True, text=True, timeout=120)
        db.expire_all()
        return done
    return _reopen


def two_stage(sim, flow):
    """Extract succeeds; Load fails; Report waits for Load."""
    flow("WF", [("Extract", sim("EXTRACT")), ("Load", sim("LOAD", fail=True), ["Extract"]),
                ("Report", sim("REPORT"), ["Load"])])


def test_a_resume_runs_what_failed_and_what_did_not_run_and_leaves_what_succeeded(sim, flow, run_flow, reopen, db):
    two_stage(sim, flow)
    _, first, before, _ = run_flow("WF")
    assert (first.Status, before["Report"].Status) == ("FAILED", "NOT_RUN")
    extract_run, started = before["Extract"].ChildRun_id, first.StartedDateTime
    fix(db, "LOAD")

    done = reopen(first, "resume")

    run, items, log = results(db, "WF")
    assert done.returncode == 0, done.stdout + done.stderr
    assert run.id == first.id and run.RunID == first.RunID                  # the same run, not a copy
    assert (run.Status, run.Reason, run.StartedDateTime) == ("SUCCESS", None, started)
    assert items["Extract"].ChildRun_id == extract_run and items["Extract"].Attempt == 1     # not run again
    assert (items["Load"].Status, items["Load"].Attempt) == ("SUCCESS", 2)
    assert (items["Report"].Status, items["Report"].Attempt) == ("SUCCESS", 1)
    assert "picked up again (resume)" in log
    assert "'Load' will go on from attempt 1." in log


def test_a_resumed_job_picks_up_its_own_record(sim, flow, run_flow, reopen, db):
    two_stage(sim, flow)
    _, first, items, _ = run_flow("WF")
    failed = items["Load"].child_run
    fix(db, "LOAD")

    reopen(first, "resume")

    _, after, _ = results(db, "WF")
    resumed = after["Load"].child_run
    assert resumed.RunID != failed.RunID and resumed.Attempt == 2
    assert resumed.SchedulerInstanceID.endswith(".2")
    log = open_log(resumed)
    assert "Resumed from attempt 1: no step had finished; step 1 runs again." in log


def open_log(run):
    from app.log_agent import run_log
    return "\n".join(run_log(run))


def test_a_restart_runs_every_item_again(sim, flow, run_flow, reopen, db):
    two_stage(sim, flow)
    _, first, before, _ = run_flow("WF")
    extract_run = before["Extract"].ChildRun_id
    fix(db, "LOAD")

    done = reopen(first, "restart")

    run, items, log = results(db, "WF")
    assert done.returncode == 0, done.stdout + done.stderr
    assert run.RunID == first.RunID and run.Status == "SUCCESS"
    assert {n: (i.Status, i.Attempt) for n, i in items.items()} == {
        "Extract": ("SUCCESS", 2), "Load": ("SUCCESS", 2), "Report": ("SUCCESS", 1)}
    assert items["Extract"].ChildRun_id != extract_run
    assert "'Extract' will run again from the beginning." in log


def test_a_resume_that_fails_again_leaves_the_run_failed_with_the_new_reason(sim, flow, run_flow, reopen, db):
    two_stage(sim, flow)
    _, first, _, _ = run_flow("WF")

    done = reopen(first, "resume")

    run, items, _ = results(db, "WF")
    assert done.returncode == 1
    assert (run.Status, run.Reason) == ("FAILED", "JOB_FAILED")
    assert items["Load"].Attempt == 2 and run.EndedDateTime is not None


def test_the_variables_of_the_first_attempt_are_kept(sim, flow, run_flow, reopen, db):
    two_stage(sim, flow)
    _, first, _, _ = run_flow("WF")
    kept = json.loads(first.WorkflowVariables)
    assert "conditions" in kept
    fix(db, "LOAD")

    reopen(first, "resume")

    run, _, _ = results(db, "WF")
    assert json.loads(run.WorkflowVariables) == kept


# ---------- A frame, and a job inside one ----------

def framed(sim, tree, db):
    """Top: Prep, then a Frame with Pull and Push (Push waits for Pull), then Done."""
    top, made = tree("TOP", {"Prep": sim("PREP"), "Frame": {"Pull": sim("PULL", fail=True), "Push": sim("PUSH")},
                             "Done": sim("DONE")})
    pull, push = made["Frame"].job.items
    P = WorkflowPrerequisite
    db.add(P(item=push, target=pull, Test="SUCCESS"))
    db.add(P(item=made["Frame"], target=made["Prep"], Test="SUCCESS"))
    db.add(P(item=made["Done"], target=made["Frame"], Test="SUCCESS"))
    db.commit()


def test_a_resume_at_the_top_reopens_a_failed_frame_and_goes_on_inside_it(sim, tree, run_flow, reopen, db):
    framed(sim, tree, db)
    _, first, before, _ = run_flow("TOP")
    frame_run = before["Frame"].child_run
    assert (before["Frame"].Status, before["Done"].Status) == ("FAILED", "NOT_RUN")
    fix(db, "PULL")

    done = reopen(first, "resume")

    run, items, log = results(db, "TOP")
    inner_run, inner, _ = results(db, "TOP.Frame")
    assert done.returncode == 0, done.stdout + done.stderr + log
    assert items["Frame"].ChildRun_id == frame_run.id                       # the frame's own run, reopened
    assert inner_run.id == frame_run.id and inner_run.Status == "SUCCESS"
    assert {n: (i.Status, i.Attempt) for n, i in inner.items()} == {"Pull": ("SUCCESS", 2), "Push": ("SUCCESS", 1)}
    assert (items["Prep"].Attempt, items["Frame"].Attempt, items["Done"].Status) == (1, 2, "SUCCESS")
    assert run.Status == "SUCCESS"


def test_a_failed_job_inside_a_frame_can_be_run_again_on_its_own(sim, tree, run_flow, reopen, db):
    framed(sim, tree, db)
    _, first, before, _ = run_flow("TOP")
    fix(db, "PULL")

    done = reopen(first, "resume", "--reopen-scope", "Frame/Pull")

    run, items, log = results(db, "TOP")
    inner_run, inner, _ = results(db, "TOP.Frame")
    assert done.returncode == 0 or items["Done"].Status == "NOT_RUN", done.stdout + done.stderr + log
    assert inner["Pull"].Status == "SUCCESS" and inner["Pull"].Attempt == 2
    assert inner["Push"].Status == "NOT_RUN"                # the rest of the tree is not reset (proposal 8)
    assert items["Done"].Status == "NOT_RUN"
    assert items["Prep"].Attempt == 1


def test_a_restart_chosen_on_one_frame_runs_that_frame_again_and_nothing_else(sim, tree, run_flow, reopen, db):
    framed(sim, tree, db)
    _, first, before, _ = run_flow("TOP")
    frame_run = before["Frame"].ChildRun_id
    fix(db, "PULL")

    reopen(first, "restart", "--reopen-scope", "Frame")

    _, items, _ = results(db, "TOP")
    assert (items["Frame"].Status, items["Frame"].Attempt) == ("SUCCESS", 2)
    assert items["Frame"].ChildRun_id != frame_run        # a restart is a new run of the frame
    assert items["Prep"].Attempt == 1 and items["Done"].Status == "NOT_RUN"


# ---------- Reactions ----------

def test_a_reopened_run_remembers_how_often_a_reaction_has_rerun(sim, flow, run_flow, reopen, db, seed):
    from test_workflow_reactions import react
    load = sim("LOAD", fail=True)
    flow("WF", [("Load", load)])
    react(db, load, "FAILED", ("RERUN", {"MaxTimes": 1}))
    _, first, items, log = run_flow("WF")
    assert items["Load"].Attempt == 2                       # it reran once, its limit, and failed again

    reopen(first, "resume")

    run, after, log = results(db, "WF")
    assert after["Load"].Attempt == 3                       # a manual attempt only: the Reaction did not rerun it again
    assert db.query(ReactionEvent).filter(ReactionEvent.WorkflowRun_id == run.id,
                                          ReactionEvent.Result == "LIMIT_REACHED").count() >= 2


# ---------- The API ----------

from test_launches import follow, get, post     # noqa: E402


def run_workflow(api, key, instance):
    launch = post(f"{api}/api/v1/launches", json={"job_key": key, "instance_id": instance}).json()
    return follow(api, launch)[1]


def test_the_plan_for_a_failed_workflow_names_what_resume_would_do(sim, flow, live_api):
    two_stage(sim, flow)
    run = run_workflow(live_api, "WF", "UI-W1")
    assert run["status"] == "FAILED"

    plan = get(f"{live_api}/api/v1/runs/{run['run_id']}/rerun-plan").json()

    assert (plan["can_restart"], plan["can_resume"], plan["reopens_run_id"]) == (True, True, run["run_id"])
    assert [(i["path"], i["what"]) for i in plan["items"]] == [
        ("Load", "goes on from attempt 1"), ("Report", "runs again from the beginning")]
    assert plan["steps_to_decide"] == []


def test_resume_through_the_api_reopens_the_same_run(sim, flow, live_api, db):
    two_stage(sim, flow)
    first = run_workflow(live_api, "WF", "UI-W2")
    fix(db, "LOAD")

    response = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "resume"})
    assert response.status_code == 202, response.text
    assert response.json()["run_id"] == first["run_id"]
    _, run = follow(live_api, response.json())

    assert (run["run_id"], run["status"], run["instance_id"]) == (first["run_id"], "SUCCESS", "UI-W2")
    again = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "resume"})
    assert again.status_code == 409 and "succeeded" in again.text


def test_a_job_inside_a_workflow_is_rerun_through_the_run_at_the_top(sim, tree, live_api, db):
    framed(sim, tree, db)
    top = run_workflow(live_api, "TOP", "UI-W3")
    _, inner, _ = results(db, "TOP.Frame")
    pull_run = inner["Pull"].child_run

    plan = get(f"{live_api}/api/v1/runs/{pull_run.RunID}/rerun-plan").json()

    assert (plan["scope"], plan["reopens_run_id"], plan["can_resume"]) == ("Frame/Pull", top["run_id"], True)
    assert [i["path"] for i in plan["items"]] == ["Frame", "Frame/Pull"]
    assert plan["items"][0]["what"] == "is opened again, to run the item chosen"


def test_a_job_that_did_not_fail_cannot_be_chosen(sim, tree, live_api, db):
    framed(sim, tree, db)
    run_workflow(live_api, "TOP", "UI-W4")
    prep = db.query(WorkflowRunItem).filter(WorkflowRunItem.Path == "Prep").one().child_run

    plan = get(f"{live_api}/api/v1/runs/{prep.RunID}/rerun-plan").json()

    assert (plan["can_restart"], plan["can_resume"]) == (False, False) and "did not fail" in plan["refusal"]


def test_a_workflow_changed_since_the_run_can_only_be_restarted(sim, flow, live_api, db):
    two_stage(sim, flow)
    run = run_workflow(live_api, "WF", "UI-W5")
    db.query(WorkflowItem).filter(WorkflowItem.ItemName == "Report").delete()
    db.commit()

    plan = get(f"{live_api}/api/v1/runs/{run['run_id']}/rerun-plan").json()

    assert plan["can_restart"] and not plan["can_resume"]
    assert "'Report' is no longer in it" in plan["resume_problem"]
    refused = post(f"{live_api}/api/v1/runs/{run['run_id']}/rerun", json={"kind": "resume"})
    assert refused.status_code == 409


def test_a_failed_step_of_unknown_effect_must_be_decided_for_its_job(sim, flow, live_api, db, tmp_path):
    from test_reruns import make_unknown
    two_stage(sim, flow)
    run = run_workflow(live_api, "WF", "UI-W6")
    load_run = db.query(WorkflowRunItem).filter(WorkflowRunItem.Path == "Load").one().child_run.RunID
    make_unknown(tmp_path, load_run)

    plan = get(f"{live_api}/api/v1/runs/{run['run_id']}/rerun-plan").json()
    assert [s["path"] for s in plan["steps_to_decide"]] == ["Load"]

    refused = post(f"{live_api}/api/v1/runs/{run['run_id']}/rerun", json={"kind": "resume"})
    assert refused.status_code == 422 and "of 'Load'" in refused.text
    fix(db, "LOAD")
    chosen = post(f"{live_api}/api/v1/runs/{run['run_id']}/rerun",
                  json={"kind": "resume", "decisions": {"Load": "count_done"}})
    _, after = follow(live_api, chosen.json())
    assert after["status"] == "SUCCESS"

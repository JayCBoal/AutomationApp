"""
Carrying out Reactions, Disable here and Kill (docs/WORKFLOWS_PHASE3.md, step 2): in a workflow,
by the workflow runner, and for a job run on its own, by the job runner. Judging which entry
holds is tested in test_reactions.py.
"""
import os
import signal
import subprocess
import sys
import time

from core.models import Job, JobRun, Reaction, ReactionAction, ReactionEvent, WorkflowRunItem, utcnow
from conftest import AUTOAPP_DIR, subprocess_env
from test_workflow_runner import flow, results, run_flow, sim, start, states  # noqa: F401 (fixtures)


def react(db, owner, test, *actions, section="NEXT", codes=None, order=1):
    """A Reaction on a job (owner a Job) or a use (owner a WorkflowItem); actions: ("RERUN", {"MaxTimes": 2})."""
    owned = {"Item_id": owner.id} if hasattr(owner, "ItemName") else {"Job_MasterObject_id": owner.MasterObject_id}
    reaction = Reaction(Section=section, ReactionOrder=order, WhenTest=test, WhenReturnCodes=codes, **owned)
    for position, (action, settings) in enumerate(actions, start=1):
        reaction.actions.append(ReactionAction(ActionOrder=position, Action=action, **settings))
    db.add(reaction)
    db.commit()
    return reaction


def item(workflow, name):
    return next(i for i in workflow.items if i.ItemName == name)


def events(db, result=None):
    query = db.query(ReactionEvent).order_by(ReactionEvent.id)
    return [(e.Action, e.Result) for e in query if result is None or e.Result == result]


def wait_for(db, condition, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        db.commit()
        db.expire_all()
        found = condition()
        if found:
            return found
        time.sleep(0.2)
    raise AssertionError("Gave up waiting")


# ---------- In a workflow ----------

def test_count_as_succeeded_lets_what_needs_success_run_and_shows_both(sim, flow, run_flow, db):
    load = sim("LOAD", code=4)
    react(db, load, "RC", ("COUNT_AS_SUCCEEDED", {}), codes="4")
    flow("COUNTED", [("Load", load), ("Report", sim("REPORT"), ["Load"])])

    code, run, items, log = run_flow("COUNTED")

    assert code == 0, log
    assert states(items) == {"Load": ("SUCCESS", "RETURN_CODE", 4), "Report": ("SUCCESS", None, 0)}
    assert items["Load"].StatusBeforeOverride == "FAILED"
    assert (items["Load"].child_run.Status, items["Load"].child_run.StatusBeforeOverride) == ("SUCCESS", "FAILED")
    assert events(db) == [("COUNT_AS_SUCCEEDED", "TOOK_EFFECT")]
    assert "'Load': its return code is 4, so, as its Reactions say: count as succeeded." in log


def test_rerun_this_job_at_most_n_times_then_the_next_reaction_applies(sim, flow, run_flow, db):
    flaky = sim("FLAKY", code=8)
    react(db, flaky, "RC", ("RERUN", {"MaxTimes": 2}), codes="8", order=1)
    react(db, flaky, "FAILED", ("COUNT_AS_SUCCEEDED", {}), order=2)
    flow("RETRY", [("Flaky", flaky)])

    code, run, items, log = run_flow("RETRY")

    assert code == 0, log
    assert (items["Flaky"].Status, items["Flaky"].Attempt) == ("SUCCESS", 3)
    attempts = db.query(JobRun).filter(JobRun.JobKey == "FLAKY").order_by(JobRun.id).all()
    assert [(r.Attempt, r.ParentRun_id) for r in attempts] == [(1, run.id), (2, run.id), (3, run.id)]
    assert events(db) == [("RERUN", "TOOK_EFFECT"), ("RERUN", "TOOK_EFFECT"), ("RERUN", "LIMIT_REACHED"),
                          ("COUNT_AS_SUCCEEDED", "TOOK_EFFECT")]
    assert "Rerunning Flaky (rerun 2 of at most 2)." in log


def test_rerun_from_runs_the_chosen_job_and_those_between_again_and_no_others(sim, flow, run_flow, db):
    workflow = flow("LOOP", [("Extract", sim("EXTRACT")), ("Side", sim("SIDE"), ["Extract"]),
                             ("Stage", sim("STAGE"), ["Extract"]), ("Check", sim("CHECK", fail=True), ["Stage"])])
    react(db, item(workflow, "Check"), "FAILED", ("RERUN_FROM", {"MaxTimes": 1, "TargetItem_id": item(workflow, "Extract").id}))
    item(workflow, "Check").ReactionsOverridden = True
    db.commit()

    code, run, items, log = run_flow("LOOP")

    assert code == 1, log
    assert {name: i.Attempt for name, i in items.items()} == {"Extract": 2, "Side": 1, "Stage": 2, "Check": 2}
    assert "Rerunning Extract, Stage, Check (rerun 1 of at most 1)." in log


def test_skip_and_skip_the_rest_of_the_branch(sim, flow, run_flow, db):
    """The branch is what waits for Check, except its failure path (Fix, and Notify after it), which still runs."""
    workflow = flow("SKIPS", [("Check", sim("CHECK", fail=True)), ("Publish", sim("PUBLISH"), ["Check"]),
                              ("Announce", sim("ANNOUNCE"), [("Publish", "ENDED")]),
                              ("Fix", sim("FIX"), [("Check", "FAILED")]), ("Notify", sim("NOTIFY"), [("Fix", "ENDED")]),
                              ("Tidy", sim("TIDY", wait=2))])
    check = item(workflow, "Check")
    check.ReactionsOverridden = True
    react(db, check, "FAILED", ("SKIP_BRANCH", {}), ("SKIP", {"TargetItem_id": item(workflow, "Tidy").id}))

    code, run, items, log = run_flow("SKIPS")

    assert code == 0, log                       # Check's failure was handled: Fix ran
    assert {name: i.Status for name, i in items.items()} == {
        "Check": "FAILED", "Publish": "SKIPPED", "Announce": "SKIPPED", "Fix": "SUCCESS", "Notify": "SUCCESS",
        "Tidy": "SUCCESS"}
    # Tidy had already started by the time Check ended, so Skip found nothing not yet started there
    assert "Skipped (the rest of the branch after 'Check'): Publish, Announce." in log
    assert "Skipped (skipped by 'Check'): nothing not yet started." in log


def test_kill_the_workflow_kills_what_runs_and_cancels_the_rest(sim, flow, run_flow, db):
    workflow = flow("KILLER", [("Bad", sim("BAD", fail=True, wait=1)), ("Slow", sim("SLOW", wait=30)),
                               ("After", sim("AFTER"), ["Slow"])])
    bad = item(workflow, "Bad")
    bad.ReactionsOverridden = True
    react(db, bad, "FAILED", ("KILL_WORKFLOW", {}))

    code, run, items, log = run_flow("KILLER")

    assert code == 1
    assert (run.Status, run.Reason) == ("FAILED", "KILLED")
    assert states(items) == {"Bad": ("FAILED", "ERROR", 1), "Slow": ("FAILED", "KILLED", None),
                             "After": ("NOT_RUN", "CANCELLED", None)}
    assert "'Bad' killed the workflow, as its Reactions say" in run.ErrorMessage


def test_kill_and_cancel_asked_for_on_a_running_workflow(sim, flow, db, db_url, tmp_path):
    flow("LONG_KILL", [("Slow", sim("A", wait=30)), ("After", sim("B"), ["Slow"])])
    process = start(db_url, tmp_path, "LONG_KILL")
    wait_for(db, lambda: db.query(WorkflowRunItem).filter(WorkflowRunItem.ItemName == "Slow",
                                                          WorkflowRunItem.Status == "RUNNING").first())
    run = db.query(JobRun).filter(JobRun.JobKey == "LONG_KILL").one()
    run.KillRequestedDateTime = utcnow()
    db.commit()
    process.communicate(timeout=60)

    run, items, log = results(db, "LONG_KILL")
    assert (run.Status, run.Reason) == ("FAILED", "KILLED")
    assert states(items) == {"Slow": ("FAILED", "KILLED", None), "After": ("NOT_RUN", "CANCELLED", None)}
    assert "Kill and Cancel asked for" in log


def test_a_killed_jobs_reactions_do_not_apply(sim, flow, db, db_url, tmp_path):
    slow = sim("SLOW_RERUN", wait=30)
    react(db, slow, "FAILED", ("RERUN", {"MaxTimes": 3}))
    flow("KILL_NO_RERUN", [("Slow", slow)])
    process = start(db_url, tmp_path, "KILL_NO_RERUN")
    row = wait_for(db, lambda: db.query(WorkflowRunItem).filter(WorkflowRunItem.ItemName == "Slow",
                                                                WorkflowRunItem.ProcessID.isnot(None)).first())
    os.kill(row.ProcessID, signal.SIGTERM)                                    # Kill on the job alone
    process.communicate(timeout=60)

    run, items, log = results(db, "KILL_NO_RERUN")
    assert (items["Slow"].Status, items["Slow"].Reason, items["Slow"].Attempt) == ("FAILED", "KILLED", 1)
    assert events(db) == []


def test_disable_here_stops_or_passes_through(sim, flow, run_flow, db):
    workflow = flow("DISABLED_HERE", [("Pass", sim("PASS", fail=True)), ("AfterPass", sim("AP"), ["Pass"]),
                                      ("Stop", sim("STOP")), ("AfterStop", sim("AS"), ["Stop"])])
    item(workflow, "Pass").DisabledHere = "PASS_THROUGH"
    item(workflow, "Stop").DisabledHere = "STOP"
    db.commit()

    code, run, items, log = run_flow("DISABLED_HERE")

    assert states(items) == {"Pass": ("BYPASSED", "DISABLED_PASS_THROUGH", None), "AfterPass": ("SUCCESS", None, 0),
                             "Stop": ("DISABLED", None, None), "AfterStop": ("NOT_RUN", "PREREQUISITES_NOT_MET", None)}
    assert items["Pass"].ChildRun_id is None                    # never ran
    assert "'Pass' is disabled here to pass through" in log


def test_a_use_that_overrides_with_no_reactions_has_none(sim, flow, run_flow, db):
    load = sim("LOAD_OVERRIDE", fail=True)
    react(db, load, "FAILED", ("COUNT_AS_SUCCEEDED", {}))
    workflow = flow("OVERRIDDEN", [("Load", load)])
    item(workflow, "Load").ReactionsOverridden = True
    db.commit()

    code, run, items, log = run_flow("OVERRIDDEN")
    assert items["Load"].Status == "FAILED" and events(db) == []


def test_start_a_workflow_starts_it_as_a_run_of_its_own(sim, flow, run_flow, db):
    flow("ALERT", [("Tell", sim("TELL"))])
    done = sim("DONE")
    flow("MAIN", [("Done", done)])
    alert_id = db.query(Job).filter_by(JobKey="ALERT").one().MasterObject_id
    react(db, done, "ENDED", ("START_WORKFLOW", {"TargetJob_MasterObject_id": alert_id}), section="ALSO")

    code, run, items, log = run_flow("MAIN")

    assert code == 0, log
    alert = wait_for(db, lambda: db.query(JobRun).filter(JobRun.JobKey == "ALERT", JobRun.EndedDateTime.isnot(None)).first())
    assert (alert.Status, alert.SchedulerName, alert.ParentRun_id) == ("SUCCESS", "AutoApp reaction", None)
    assert "Started workflow 'ALERT', instance REACTION-" in log


# ---------- A job on its own ----------

def test_on_its_own_a_job_counts_as_and_reruns_by_its_own_reactions(sim, run_runner, load_spool, db):
    odd = sim("ODD_ALONE", code=8)
    react(db, odd, "RC", ("RERUN", {"MaxTimes": 1}), codes="8", order=1)
    react(db, odd, "FAILED", ("COUNT_AS_SUCCEEDED", {}), order=2)

    result = run_runner("ODD_ALONE")
    assert result.returncode == 0, result.stdout + result.stderr
    load_spool()
    runs = db.query(JobRun).filter(JobRun.JobKey == "ODD_ALONE").order_by(JobRun.id).all()
    assert [(r.Attempt, r.Status, r.StatusBeforeOverride, r.SchedulerInstanceID) for r in runs] == [
        (1, "FAILED", None, "RUN_001"), (2, "SUCCESS", "FAILED", "RUN_001")]
    assert events(db) == [("RERUN", "TOOK_EFFECT"), ("RERUN", "LIMIT_REACHED"), ("COUNT_AS_SUCCEEDED", "TOOK_EFFECT")]


def test_a_job_on_its_own_ends_killed_when_told_to_stop(sim, db, db_url, tmp_path, load_spool):
    job = sim("KILL_ME", wait=30)
    react(db, job, "FAILED", ("RERUN", {"MaxTimes": 3}))
    db.commit()
    process = subprocess.Popen([sys.executable, "-m", "engine.runner", "--job-key", "KILL_ME", "--instance-id", "K1",
                                "--spool-dir", str(tmp_path / "spool"), "--working-root", str(tmp_path / "work")],
                               cwd=AUTOAPP_DIR, env=subprocess_env(db_url), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    time.sleep(2)
    process.send_signal(signal.SIGTERM)
    output, _ = process.communicate(timeout=30)

    assert process.returncode == 1, output
    load_spool()
    run = db.query(JobRun).filter(JobRun.JobKey == "KILL_ME").one()                  # and no rerun
    assert (run.Status, run.Reason, run.ReturnCode, run.ProcessID) == ("FAILED", "KILLED", None, process.pid)


def test_a_workflows_own_reactions_rerun_it_and_count_it(sim, flow, run_flow, db):
    """A workflow is a job: its own Reactions apply to its run, when it runs on its own."""
    workflow = flow("OWN", [("Bad", sim("BAD_OWN", fail=True))])
    react(db, workflow, "FAILED", ("RERUN", {"MaxTimes": 1}), order=1)
    react(db, workflow, "FAILED", ("COUNT_AS_SUCCEEDED", {}), order=2)

    code, run, items, log = run_flow("OWN")

    assert code == 0
    runs = db.query(JobRun).filter(JobRun.JobKey == "OWN").order_by(JobRun.id).all()
    assert [(r.Attempt, r.Status, r.StatusBeforeOverride, r.Reason) for r in runs] == [
        (1, "FAILED", None, "JOB_FAILED"), (2, "SUCCESS", "FAILED", "JOB_FAILED")]
    assert events(db) == [("RERUN", "TOOK_EFFECT"), ("RERUN", "LIMIT_REACHED"), ("COUNT_AS_SUCCEEDED", "TOOK_EFFECT")]

"""
Workflows Phase 6, the engine: a workflow embedded in another runs as a frame (a run of its own),
and a job inside it can wait for a job elsewhere in the same tree. The trees here are built straight
in the database; the saving of them is tried in test_frames_api.py.
"""
import pytest

from app.models import Job, JobRun, WorkflowItem, WorkflowPrerequisite, WorkflowRunItem, utcnow
from test_workflow_runner import results, run_flow, sim, start      # noqa: F401  (fixtures)


@pytest.fixture
def tree(seed, db):
    """Builds a top workflow and the workflows embedded in it: tree("TOP", {"FX": job, "Frame": {"Inner": job}})."""
    def _build(key, entries, owner=None):
        workflow = seed._add(Job(JobKey=key, JobType="WORKFLOW", Owner_MasterObject_id=owner.MasterObject_id if owner else None))
        made = {}
        for position, (name, what) in enumerate(entries.items(), start=1):
            job = what if isinstance(what, Job) else _build(f"{key}.{name}", what, workflow)[0]
            made[name] = seed._add(WorkflowItem(workflow=workflow, ItemName=name, job=job, ItemOrder=position))
        return workflow, made
    return _build


def waits_in_tree(item, target, test="SUCCESS"):
    """The item waits for a job elsewhere in its tree (the kind a frame's job uses to reach outside its frame)."""
    return WorkflowPrerequisite(item=item, Kind="OTHER_JOB", target=target, Test=test, ReturnCodes=None,
                                TargetName=f"{target.workflow.JobKey}.{target.ItemName}")


def an_earlier_run_of(db, workflow, item, status):
    """A finished earlier run of the tree, in which the item ended as given: the answer a wait must not use."""
    run = JobRun(RunID="old-run", JobKey=workflow.JobKey, Job_MasterObject_id=workflow.MasterObject_id, JobType="WORKFLOW",
                 SchedulerInstanceID="OLD", Status="SUCCESS", StartedDateTime=utcnow(), EndedDateTime=utcnow())
    db.add(run)
    db.flush()
    db.add(WorkflowRunItem(WorkflowRun_id=run.id, Item_id=item.id, Path=item.ItemName, ItemName=item.ItemName,
                           JobKey=item.job.JobKey, Status=status, ReturnCode=0, EndedDateTime=utcnow()))


def test_a_job_in_a_frame_waits_for_this_runs_answer_and_not_an_earlier_ones(sim, tree, run_flow, db):
    top, made = tree("TOP", {"FX": sim("FX", wait=2), "Frame": {"Inner": sim("INNER")}})
    inner = made["Frame"].job.items[0]
    db.add(waits_in_tree(inner, made["FX"]))
    an_earlier_run_of(db, top, made["FX"], "SUCCESS")        # yesterday's FX succeeded; today's has yet to

    code, run, items, log = run_flow("TOP")

    assert code == 0, log
    frame_run, frame_items, _ = results(db, "TOP.Frame")
    assert frame_run.ParentRun_id == run.id and frame_run.WorkflowPath == "Frame"
    assert frame_items["Inner"].StartedDateTime >= items["FX"].EndedDateTime       # it waited for today's FX
    assert frame_items["Inner"].Status == "SUCCESS"


def test_a_job_in_a_frame_does_not_run_when_this_runs_answer_is_a_failure_whatever_the_last_run_said(sim, tree, run_flow, db):
    top, made = tree("TOP", {"FX": sim("FX", fail=True), "Frame": {"Inner": sim("INNER")}})
    db.add(waits_in_tree(made["Frame"].job.items[0], made["FX"]))
    an_earlier_run_of(db, top, made["FX"], "SUCCESS")

    code, run, items, log = run_flow("TOP")

    frame_run, frame_items, frame_log = results(db, "TOP.Frame")
    assert (frame_items["Inner"].Status, frame_items["Inner"].Reason) == ("NOT_RUN", "PREREQUISITES_NOT_MET")
    assert "it waits for 'TOP.FX' in this run" in frame_log
    assert items["Frame"].Status == "SUCCESS" and items["FX"].Status == "FAILED"


# ---------- Variables reach what is inside a frame (D91) ----------

from test_workflow_variables import codes, coded, use_variable      # noqa: E402,F401  (fixtures)


def test_a_workflows_variable_reaches_the_jobs_inside_its_frames(coded, tree, run_flow, seed, db):
    top, made = tree("TOP", {"Top_job": coded("T"), "Frame": {"Inner": coded("I"), "Deep": {"Deepest": coded("D")}}})
    seed.set_vars(top, Code="3")

    code, run, items, log = run_flow("TOP")

    assert code == 0, log
    assert items["Top_job"].ReturnCode == 3
    _, frame_items, _ = results(db, "TOP.Frame")
    _, deep_items, _ = results(db, "TOP.Frame.Deep")
    assert frame_items["Inner"].ReturnCode == 3 and deep_items["Deepest"].ReturnCode == 3


def test_the_nearest_workflow_wins_and_a_jobs_own_still_beats_them_all(coded, tree, run_flow, seed, db):
    top, made = tree("TOP", {"Frame": {"Inner": coded("I"), "Own": coded("O", Code="5")}})
    seed.set_vars(top, Code="3")
    seed.set_vars(made["Frame"].job, Code="4")

    code, run, items, log = run_flow("TOP")

    _, frame_items, _ = results(db, "TOP.Frame")
    assert codes(frame_items) == {"Inner": 4, "Own": 5}, log


def test_a_use_can_override_a_variable_for_the_job_in_a_frame(coded, tree, run_flow, seed, db):
    top, made = tree("TOP", {"Frame": {"Inner": coded("I"), "Other": coded("O")}})
    seed.set_vars(top, Code="3")
    use_variable(db, made["Frame"].job, "Other", "Code", "9")

    run_flow("TOP")

    _, frame_items, _ = results(db, "TOP.Frame")
    assert codes(frame_items) == {"Inner": 3, "Other": 9}


# ---------- A whole tree, saved as the editor saves it and run ----------

def test_a_saved_tree_runs_its_frames_in_order_and_a_condition_reads_inside_a_frame_by_path(client, sim, run_flow, db):
    sim("FX", wait=1), sim("LATER")
    sim_steps = lambda: [{"title": "Sim", "step_type": "SIMULATE", "parameters": {"ReturnCode": "0", "Fail": "False", "WaitSeconds": "0"}}]
    job = lambda name, **more: {"name": name, "embedded": {"job_type": "STEPS", "steps": sim_steps()}, **more}
    db.commit()
    payload = {"job_key": "MONTH_END", "job_type": "WORKFLOW", "items": [
        {"name": "FX", "job_key": "FX"},
        {"name": "Extract", "embedded": {"job_type": "WORKFLOW", "items": [job("US"), job("EU")]}},
        {"name": "Transform", "prerequisites": [{"target": "Extract"}], "embedded": {"job_type": "WORKFLOW", "items": [
            job("Enrich", prerequisites=[{"kind": "OTHER_JOB", "workflow": "MONTH_END", "job": "FX"}]),
            job("Other")]}},
        {"name": "Report", "job_key": "LATER", "join": "CUSTOM", "rule": "%{Transform.Enrich.Status} = 'SUCCESS'"}]}
    assert client.post("/api/v1/jobs", json=payload).status_code == 201

    code, run, items, log = run_flow("MONTH_END")

    assert code == 0, log
    assert {n: i.Status for n, i in items.items()} == {"FX": "SUCCESS", "Extract": "SUCCESS", "Transform": "SUCCESS", "Report": "SUCCESS"}
    _, extract, _ = results(db, "MONTH_END.Extract")
    _, transform, _ = results(db, "MONTH_END.Transform")
    assert transform["Enrich"].StartedDateTime >= items["FX"].EndedDateTime
    assert items["Transform"].StartedDateTime >= items["Extract"].EndedDateTime
    assert items["Report"].StartedDateTime >= transform["Enrich"].EndedDateTime
    assert transform["Enrich"].Path == "Transform/Enrich" and extract["US"].Path == "Extract/US"


def test_the_run_api_gives_what_is_inside_each_frame_to_any_depth(client, sim, run_flow, db):
    job = lambda name, **more: {"name": name, "embedded": {"job_type": "STEPS", "steps": [
        {"title": "Sim", "step_type": "SIMULATE", "parameters": {"ReturnCode": "0", "Fail": "False", "WaitSeconds": "0"}}]}, **more}
    payload = {"job_key": "NEST", "job_type": "WORKFLOW", "items": [
        {"name": "Outer", "embedded": {"job_type": "WORKFLOW", "items": [
            job("Leaf"), {"name": "Inner", "embedded": {"job_type": "WORKFLOW", "items": [job("Deep")]}}]}}]}
    assert client.post("/api/v1/jobs", json=payload).status_code == 201
    code, run, items, log = run_flow("NEST")

    detail = client.get(f"/api/v1/runs/{run.RunID}").json()

    outer = detail["items"][0]
    assert (outer["name"], outer["status"], outer["frame_run_id"] is not None) == ("Outer", "SUCCESS", True)
    assert [i["name"] for i in outer["inside"]] == ["Leaf", "Inner"]
    assert [(i["name"], i["status"], i["path"]) for i in outer["inside"][1]["inside"]] == [("Deep", "SUCCESS", "Outer/Inner/Deep")]
    assert outer["inside"][0]["inside"] == []


# ---------- A frame behaves as an item: Disable here, failure, Kill ----------

from test_workflow_reactions import events, react, wait_for      # noqa: E402,F401
from test_workflow_runner import states                            # noqa: E402,F401


def test_a_frame_disabled_here_stops_or_passes_through_as_one_item(sim, tree, run_flow, db):
    top, made = tree("DIS", {"Stopped": {"A": sim("A")}, "AfterStopped": sim("AS"), "Passed": {"B": sim("B", fail=True)},
                             "AfterPassed": sim("AP")})
    made["Stopped"].DisabledHere, made["Passed"].DisabledHere = "STOP", "PASS_THROUGH"
    db.add_all([WorkflowPrerequisite(item=made["AfterStopped"], target=made["Stopped"], Test="SUCCESS", Kind="JOB"),
                WorkflowPrerequisite(item=made["AfterPassed"], target=made["Passed"], Test="SUCCESS", Kind="JOB")])
    db.commit()

    code, run, items, log = run_flow("DIS")

    assert states(items) == {"Stopped": ("DISABLED", None, None), "AfterStopped": ("NOT_RUN", "PREREQUISITES_NOT_MET", None),
                             "Passed": ("BYPASSED", "DISABLED_PASS_THROUGH", None), "AfterPassed": ("SUCCESS", None, 0)}
    assert db.query(JobRun).filter(JobRun.JobKey.in_(["DIS.Stopped", "DIS.Passed"])).count() == 0     # the frames never ran


def test_a_frame_whose_job_failed_ends_failed_and_what_waits_for_its_failure_still_runs(sim, tree, run_flow, db):
    top, made = tree("FAILING", {"Frame": {"Bad": sim("BAD", fail=True), "After": sim("AFTER")}, "Alert": sim("ALERT")})
    bad = made["Frame"].job.items[0]
    db.add_all([WorkflowPrerequisite(item=made["Frame"].job.items[1], target=bad, Test="SUCCESS", Kind="JOB"),
                WorkflowPrerequisite(item=made["Alert"], target=made["Frame"], Test="FAILED", Kind="JOB")])
    db.commit()

    code, run, items, log = run_flow("FAILING")

    frame_run, frame_items, _ = results(db, "FAILING.Frame")
    assert (frame_run.Status, frame_run.Reason) == ("FAILED", "JOB_FAILED")
    assert states(items) == {"Frame": ("FAILED", "JOB_FAILED", 1), "Alert": ("SUCCESS", None, 0)}
    assert code == 0                                           # the frame's failure was handled: Alert ran
    assert frame_items["After"].Status == "NOT_RUN"


def test_kill_the_workflow_inside_a_frame_kills_that_frame_and_nothing_outside_it(sim, tree, run_flow, db):
    top, made = tree("SCOPED", {"Outside": sim("OUT", wait=3), "Frame": {"Bad": sim("BAD", fail=True, wait=1), "Slow": sim("SLOW", wait=30)}})
    bad = made["Frame"].job.items[0]
    bad.ReactionsOverridden = True
    react(db, bad, "FAILED", ("KILL_WORKFLOW", {}))

    code, run, items, log = run_flow("SCOPED")

    frame_run, frame_items, _ = results(db, "SCOPED.Frame")
    assert (frame_run.Status, frame_run.Reason) == ("FAILED", "KILLED")
    assert states(frame_items) == {"Bad": ("FAILED", "ERROR", 1), "Slow": ("FAILED", "KILLED", None)}
    assert items["Outside"].Status == "SUCCESS"              # the top run's other job was not killed
    assert (items["Frame"].Status, items["Frame"].Reason) == ("FAILED", "KILLED")
    assert (run.Status, run.Reason) == ("FAILED", "JOB_FAILED") and "Kill" not in (run.ErrorMessage or "")


def test_kill_and_cancel_asked_for_on_the_top_run_reach_the_jobs_inside_its_frames(sim, tree, db, db_url, tmp_path):
    tree("KILL_TREE", {"Frame": {"Slow": sim("SLOW_IN", wait=30), "After": sim("AFTER_IN")}})
    frame_item = db.query(WorkflowItem).filter(WorkflowItem.ItemName == "Frame").one()
    db.add(WorkflowPrerequisite(item=frame_item.job.items[1], target=frame_item.job.items[0], Test="SUCCESS", Kind="JOB"))
    db.commit()
    process = start(db_url, tmp_path, "KILL_TREE")
    wait_for(db, lambda: db.query(WorkflowRunItem).filter(WorkflowRunItem.ItemName == "Slow", WorkflowRunItem.Status == "RUNNING").first())
    run = db.query(JobRun).filter(JobRun.JobKey == "KILL_TREE").one()
    run.KillRequestedDateTime = utcnow()
    db.commit()
    process.communicate(timeout=60)

    run, items, log = results(db, "KILL_TREE")
    frame_run, frame_items, _ = results(db, "KILL_TREE.Frame")
    assert (run.Status, run.Reason) == ("FAILED", "KILLED")
    assert (frame_run.Status, frame_run.Reason) == ("FAILED", "KILLED")
    assert states(frame_items) == {"Slow": ("FAILED", "KILLED", None), "After": ("NOT_RUN", "CANCELLED", None)}


# ---------- Depth ----------

def test_a_tree_ten_levels_deep_with_dozens_of_frames_runs_in_reasonable_time(sim, tree, run_flow, db):
    """The load a deep, wide tree puts on the machine (a runner process for every frame): it must start and end promptly."""
    import time as clock
    leaf = sim("LEAF")

    def level(depth):
        inside = {"Leaf": leaf, "Side_a": {"Only": leaf}, "Side_b": {"Only": leaf}}
        if depth < 10:
            inside["Deeper"] = level(depth + 1)
        return inside

    tree("DEEP_TREE", {"Start": leaf, "Level": level(1)})
    frames = db.query(Job).filter(Job.JobKey.like("DEEP_TREE.%"), Job.JobType == "WORKFLOW").count()
    assert frames >= 30

    started = clock.time()
    code, run, items, log = run_flow("DEEP_TREE")
    took = clock.time() - started

    assert code == 0, log[-2000:]
    runs = db.query(JobRun).filter(JobRun.JobKey.like("DEEP_TREE%"), JobRun.JobType == "WORKFLOW").count()
    assert runs == frames + 1
    print(f"\n{frames} frames, ten levels deep: ran in {took:.1f} s")
    assert took < 120

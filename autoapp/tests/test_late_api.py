"""
Late in Job History and the clock lines of the run view (docs/WORKFLOWS_PHASE8.md, step 6): the Late flag and its
reason on runs and on a workflow run's items, the search by it, and, for a run still going, each timed entry that
has not fired yet with the time it works out to.
"""
from datetime import datetime, timedelta, timezone

from core.models import Job, JobRun, ReactionEvent, WorkflowRunItem
from test_workflow_clock import events, run_clocked, timed  # noqa: F401 (fixture)
from test_workflow_runner import flow, results, sim  # noqa: F401 (fixtures)

RUNS = "/api/v1/runs"


def test_a_late_run_is_flagged_with_its_reason_and_can_be_searched_for(sim, flow, run_clocked, db, client):
    slow, quick = sim("SLOW", wait=6), sim("QUICK")
    timed(db, slow, "RUNS_LONGER_THAN", "LENGTH", ("MARK_AS_LATE", {}), minutes=30)
    flow("LATE_FLOW", [("Slow", slow), ("Quick", quick)])
    code, run, items, log = run_clocked("LATE_FLOW")
    assert code == 0, log

    late = client.get(RUNS, params={"late": "true"}).json()
    assert [r["job_key"] for r in late] == ["SLOW"]
    assert late[0]["late"] and "has run longer than 30m" in late[0]["late_reason"] and late[0]["late_since"]
    never = {r["job_key"] for r in client.get(RUNS, params={"late": "false"}).json()}
    assert never == {"QUICK", "LATE_FLOW"}

    detail = client.get(f"{RUNS}/{run.RunID}").json()
    by_name = {i["name"]: i for i in detail["items"]}
    assert by_name["Slow"]["late"] and not by_name["Quick"]["late"]
    assert [e["action"] for e in detail["reactions"]] == ["MARK_AS_LATE"]


def a_running_workflow(db, flow, sim, started_minutes_ago):
    """A workflow run recorded as going now: Wait is running, Report waits for it. Nothing runs; only the record is read."""
    wait, report = sim("WAIT"), sim("REPORT")
    timed(db, wait, "NOT_ENDED_BY", "AFTER_START", ("MARK_AS_LATE", {}), minutes=60)
    timed(db, report, "NOT_STARTED_BY", "AFTER_START", ("NOTIFY", {}), minutes=90, order=2)
    timed(db, report, "RUNS_LONGER_THAN", "LENGTH", ("MARK_AS_LATE", {}), minutes=45, order=3)
    workflow = flow("GOING", [("Wait", wait), ("Report", report, ["Wait"])])
    started = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=started_minutes_ago)
    run = JobRun(RunID="r-going", JobKey="GOING", Job_MasterObject_id=workflow.MasterObject_id, JobType="WORKFLOW",
                 SchedulerInstanceID="G1", Status="RUNNING", StartedDateTime=started)
    db.add(run)
    db.flush()
    for item in workflow.items:
        db.add(WorkflowRunItem(WorkflowRun_id=run.id, Item_id=item.id, Path=item.ItemName, ItemName=item.ItemName,
                               JobKey=item.job.JobKey, ItemOrder=item.ItemOrder,
                               Status="RUNNING" if item.ItemName == "Wait" else "PENDING",
                               StartedDateTime=started if item.ItemName == "Wait" else None))
    db.commit()
    return run


def test_a_running_workflow_shows_what_each_item_is_due_by(sim, flow, db, client):
    a_running_workflow(db, flow, sim, started_minutes_ago=20)
    items = {i["name"]: i for i in client.get(f"{RUNS}/r-going").json()["items"]}

    wait = items["Wait"]["clock"]
    assert len(wait) == 1 and wait[0].startswith("Not ended by: due by ")
    assert "(in 39 minutes)" in wait[0] or "(in 40 minutes)" in wait[0]
    assert "60 minutes after the run started at" in wait[0]
    report = items["Report"]["clock"]
    assert [line.split(":")[0] for line in report] == ["Not started by"]    # "runs longer than" only while it runs
    assert "(in 69 minutes)" in report[0] or "(in 70 minutes)" in report[0]


def test_an_entry_that_fired_is_left_out_of_the_clock_lines(sim, flow, db, client):
    run = a_running_workflow(db, flow, sim, started_minutes_ago=75)
    wait_action = db.query(Job).filter_by(JobKey="WAIT").one().reactions[0].actions[0]
    db.add(ReactionEvent(WorkflowRun_id=run.id, WorkflowPath="Wait", ReactionAction_id=wait_action.id,
                         Action="MARK_AS_LATE", Result="TOOK_EFFECT", Message="Marked as late."))
    db.commit()
    items = {i["name"]: i for i in client.get(f"{RUNS}/r-going").json()["items"]}
    assert items["Wait"]["clock"] == []
    assert "Not started by: due by " in items["Report"]["clock"][0]


def test_an_ended_run_has_no_clock_lines(sim, flow, db, client):
    run = a_running_workflow(db, flow, sim, started_minutes_ago=20)
    run.Status = "SUCCESS"
    db.commit()
    detail = client.get(f"{RUNS}/r-going").json()
    assert detail["clock"] == [] and all(i["clock"] == [] for i in detail["items"])

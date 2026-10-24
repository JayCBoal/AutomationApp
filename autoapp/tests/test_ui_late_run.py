"""
Late and the clock lines on a run's pages (docs/WORKFLOWS_PHASE8.md, step 6), in a real browser against a real server:
the workflow run's outline, side panel and diagram, and a job run's log page.
"""
import pytest
from playwright.sync_api import expect

from core.models import JobRun, ReactionEvent, WorkflowRunItem, utcnow
from test_late_api import a_running_workflow
from test_workflow_runner import flow, sim  # noqa: F401 (fixtures)


@pytest.fixture(autouse=True)
def outline_view(page):
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'outline')")


def test_a_running_workflow_shows_what_each_job_is_due_by_and_marks_a_late_one(page, sim, flow, db):
    run = a_running_workflow(db, flow, sim, started_minutes_ago=20)
    page.goto("/ui/workflow.html?key=GOING&run=r-going")
    wait = page.locator("#run-items li[data-name='Wait']")
    expect(wait.locator(".run-clock-line")).to_contain_text("Not ended by: due by")
    expect(wait.locator(".tag.late")).to_be_hidden()

    row = db.query(WorkflowRunItem).filter_by(WorkflowRun_id=run.id, ItemName="Wait").one()
    row.LateDateTime, row.LateReason = utcnow(), "'Wait' had not ended by 03:00"
    db.commit()
    page.reload()
    expect(wait.locator(".tag.late")).to_be_visible()


def test_the_side_panel_of_a_late_job_says_why_and_what_fired(page, sim, flow, db):
    run = a_running_workflow(db, flow, sim, started_minutes_ago=75)
    row = db.query(WorkflowRunItem).filter_by(WorkflowRun_id=run.id, ItemName="Report").one()
    row.LateDateTime, row.LateReason = utcnow(), "'Report' had not started by 03:00"
    row.LateCause = "waiting for 'Wait', which has been running since 01:10"
    db.add(ReactionEvent(WorkflowRun_id=run.id, WorkflowPath="Report", Action="MARK_AS_LATE", Result="TOOK_EFFECT",
                         Message="'Report' had not started by 03:00. Marked as late."))
    db.commit()
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'diagram')")
    page.goto("/ui/workflow.html?key=GOING&run=r-going")
    page.locator("#run-diagram .wf-box").first.wait_for()
    page.locator("#run-diagram .wf-box", has_text="Report").click()
    side = page.locator("#run-side")
    expect(side.locator(".run-late-reason")).to_contain_text("had not started by 03:00")
    expect(side.locator(".run-late-reason")).to_contain_text("waiting for 'Wait'")
    expect(side.locator(".reaction-events")).to_contain_text("Marked as late.")
    expect(page.locator("#run-diagram")).to_contain_text("Late")


def test_a_late_job_run_says_so_on_its_log_page(page, db):
    run = JobRun(RunID="r-late", JobKey="SLOWPOKE", SchedulerInstanceID="I1", Status="SUCCESS", StartedDateTime=utcnow(),
                 EndedDateTime=utcnow(), LateDateTime=utcnow(), LateReason="'SLOWPOKE' has run longer than 30m")
    db.add(run)
    db.flush()
    db.add(ReactionEvent(JobRun_id=run.id, Action="MARK_AS_LATE", Result="TOOK_EFFECT", Message="Marked as late."))
    db.commit()
    page.goto("/ui/log.html?run=r-late")
    expect(page.locator("#run-late-line")).to_contain_text("has run longer than 30m")
    page.locator("#run-reactions summary").click()
    expect(page.locator("#run-reactions")).to_contain_text("Marked as late.")

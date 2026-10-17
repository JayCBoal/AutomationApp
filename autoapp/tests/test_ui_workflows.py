"""
Workflows in the web interface (docs/WORKFLOWS_PHASE1.md, step 4), in a real browser against a
real server: the workflow page's outline, running a workflow and watching it, Cancel, and
workflows on the Job Search, Job Detail and Job History pages.
"""
import pytest

from app.models import Job, WorkflowItem, WorkflowPrerequisite
from conftest import wait_for_search


@pytest.fixture
def sims(seed, db):
    """Two jobs of one Simulate step each: SIM_FIRST (waits 'wait' seconds) and SIM_SECOND."""
    def _make(wait=0):
        for key, seconds in (("SIM_FIRST", wait), ("SIM_SECOND", 0)):
            seed.step(seed.job(key), 1, "SIMULATE", title="Pretend", WaitSeconds=str(seconds))
        db.commit()
    return _make


@pytest.fixture
def saved_flow(seed, db, sims):
    """FLOW: First, then Second once First has succeeded."""
    def _make(wait=0):
        sims(wait)
        first_job, second_job = (db.query(Job).filter(Job.JobKey == k).one() for k in ("SIM_FIRST", "SIM_SECOND"))
        flow = seed._add(Job(JobKey="FLOW", JobType="WORKFLOW", Description="Two in a row"))
        first = seed._add(WorkflowItem(workflow=flow, ItemName="First", job=first_job, ItemOrder=1))
        second = seed._add(WorkflowItem(workflow=flow, ItemName="Second", job=second_job, ItemOrder=2))
        seed._add(WorkflowPrerequisite(item=second, target=first, Test="SUCCESS"))
        db.commit()
    return _make


def needs(page):
    return [n.inner_text() for n in page.locator("#outline .wf-needs").all()]


def wait_for_run_end(page, timeout=60000):
    page.wait_for_function(
        "() => ['Succeeded', 'Failed'].some(w => (document.querySelector('#run-status')?.textContent || '').startsWith(w))",
        timeout=timeout)


def test_a_workflow_is_built_in_the_outline_and_saved(page, sims, db):
    sims()
    page.goto("/ui/workflow.html?new")
    page.locator("#workflow-key").fill("NEW_FLOW")
    page.locator("#add-job").click()
    page.locator("#add-job").click()
    jobs, names = page.locator(".item-job"), page.locator(".item-name")
    jobs.nth(0).fill("SIM_FIRST")
    names.nth(0).fill("Check")
    jobs.nth(1).fill("SIM_SECOND")
    page.locator(".add-prerequisite").nth(1).click()
    page.locator(".prereq-test").select_option("RC")
    page.locator(".prereq-codes").fill("0-4")

    page.locator("#submit-button").click()

    page.locator("#save-notice").wait_for()
    assert page.locator("#save-notice").inner_text().startswith("Saved.")
    assert needs(page) == ["Starts when the workflow starts", "After Check gave return codes 0-4"]
    assert page.locator("#runnability .ready-text").is_visible()
    db.expire_all()
    flow = db.query(Job).filter(Job.JobKey == "NEW_FLOW").one()
    assert (flow.JobType, [i.ItemName for i in flow.items]) == ("WORKFLOW", ["Check", "SIM_SECOND"])
    assert [(p.target.ItemName, p.Test, p.ReturnCodes) for p in flow.items[1].prerequisites] == [("Check", "RC", "0-4")]


def test_renaming_a_job_keeps_what_waits_for_it(page, saved_flow):
    saved_flow()
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#edit-button").click()
    page.locator(".item-name").nth(0).fill("Opening")
    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()
    assert needs(page) == ["Starts when the workflow starts", "After Opening succeeded"]
    assert "Changed 'Opening': renamed from 'First'." in page.locator("#save-notice").inner_text()


def test_a_workflow_is_run_from_its_page_and_watched_to_the_end(page, saved_flow):
    saved_flow()
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#run-button").click()
    wait_for_run_end(page)
    assert page.locator("#run-status").inner_text() == "Succeeded"
    states = [s.inner_text() for s in page.locator("#run-items .wf-state").all()]
    assert states == ["Succeeded · return code 0", "Succeeded · return code 0"]
    assert page.locator("#run-items a").count() == 2             # each job's log
    page.locator("#runs tbody tr").first.wait_for()


def test_a_run_can_be_cancelled_from_the_page(page, saved_flow):
    saved_flow(wait=4)
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#run-button").click()
    page.wait_for_function("() => document.querySelector('#run-items .wf-state')?.textContent === 'Running'", timeout=30000)
    page.locator("#cancel-run-button").click()
    wait_for_run_end(page)
    assert page.locator("#run-status").inner_text() == "Failed (the workflow was cancelled)"
    assert page.locator("#run-items .wf-state").nth(1).inner_text() == "Not run: the workflow was cancelled"


def test_workflows_on_the_job_search_and_job_detail_pages(page, saved_flow):
    saved_flow()
    page.goto("/ui/jobs.html?job_type=WORKFLOW")
    wait_for_search(page)
    rows = page.locator("table.results tbody tr")
    assert rows.count() == 1
    assert "Workflow" in rows.first.inner_text() and "2 jobs" in rows.first.inner_text()
    rows.first.locator("a.job-key").click()
    page.wait_for_url("**/workflow.html?key=FLOW")

    page.goto("/ui/job.html?key=FLOW")                         # the job page sends a workflow to its own page
    page.wait_for_url("**/workflow.html?key=FLOW")
    page.locator("#outline").wait_for()


def test_success_return_codes_are_set_on_the_job_page(page, sims, db):
    sims()
    page.goto("/ui/job.html?key=SIM_FIRST")
    page.locator("#edit-button").click()
    page.locator("#job-success-codes").fill("0,4")
    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()
    db.expire_all()
    assert db.query(Job).filter(Job.JobKey == "SIM_FIRST").one().SuccessReturnCodes == "0, 4"


def test_job_history_shows_a_workflow_run_with_its_jobs(page, saved_flow):
    saved_flow()
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#run-button").click()
    wait_for_run_end(page)
    page.goto("/ui/history.html?job_type=WORKFLOW")
    wait_for_search(page)
    page.locator("a.inside-link").first.click()
    wait_for_search(page)
    keys = sorted(k.inner_text() for k in page.locator("table.results a.job-key").all())
    assert keys == ["FLOW", "SIM_FIRST", "SIM_SECOND"]
    assert page.locator("a.parent-link:visible").count() == 2


def test_disabling_a_job_used_in_a_workflow_warns_first_and_the_workflow_says_so(page, saved_flow, db):
    saved_flow()
    page.goto("/ui/job.html?key=SIM_SECOND")
    page.locator("#edit-button").click()
    page.locator("#job-enabled").uncheck()
    said = []
    page.once("dialog", lambda dialog: (said.append(dialog.message), dialog.dismiss()))
    page.locator("#submit-button").click()
    assert said and "It is used in 1 workflow: FLOW." in said[0] and "will end Disabled" in said[0]
    db.expire_all()
    assert db.query(Job).filter(Job.JobKey == "SIM_SECOND").one().IsActive          # cancelled: not saved

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()
    db.expire_all()
    assert not db.query(Job).filter(Job.JobKey == "SIM_SECOND").one().IsActive

    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#check-warnings li").first.wait_for()
    assert page.locator("#check-warnings li").inner_text().startswith("'Second' is disabled")
    assert page.locator("#runnability .ready-text").is_visible()                    # it still runs
    page.locator("#run-button").click()
    wait_for_run_end(page)
    assert [s.inner_text() for s in page.locator("#run-items .wf-state").all()] == [
        "Succeeded · return code 0", "Disabled"]

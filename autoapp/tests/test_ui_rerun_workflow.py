"""
Rerun on the workflow page and in Job History (docs/WORKFLOWS_PHASE7.md, step 4): the dialog for a workflow run, a job
inside it and a failed row in Job History, the choice for a step that may or may not have changed something, and the
x2 on a box that has run twice.
"""
import pytest

from app.models import Job, JobRun
from conftest import wait_for_search
from test_reruns import make_unknown
from test_workflow_reopen import fix
from test_workflow_runner import flow, sim    # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def outline_view(page):
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'outline')")


@pytest.fixture
def failed_run(page, sim, flow, db):
    """WF: Extract succeeds, Load fails, Report waits for Load. Run from the page, and waits until it has failed."""
    flow("WF", [("Extract", sim("EXTRACT")), ("Load", sim("LOAD", fail=True), ["Extract"]), ("Report", sim("REPORT"), ["Load"])])
    page.goto("/ui/workflow.html?key=WF")
    page.locator("#run-button").click()
    wait_for_status(page, "Failed")
    return page


def wait_for_status(page, words):
    page.wait_for_function("words => document.querySelector('#run-status')?.textContent.startsWith(words)", arg=words, timeout=60000)


def test_resume_from_the_workflow_page_goes_on_where_the_run_stopped(failed_run, db):
    page = failed_run
    fix(db, "LOAD")

    page.locator("#rerun-button").click()
    items = page.locator("#rerun-items").inner_text()
    assert "Load" in items and "Report" in items and "Extract" not in items          # what Resume touches

    page.locator("#rerun-resume").click()
    wait_for_status(page, "Succeeded")
    assert page.locator("#run-items .wf-state").all_inner_texts()[1].endswith("attempt 2")


def test_restart_runs_every_item_again(failed_run, db):
    page = failed_run
    fix(db, "LOAD")

    page.locator("#rerun-button").click()
    page.locator("#rerun-restart").click()

    wait_for_status(page, "Succeeded")
    assert page.locator("#run-items .wf-state").all_inner_texts()[0].endswith("attempt 2")     # Extract ran again


def test_a_failed_job_inside_the_run_can_be_run_again_on_its_own(failed_run, db):
    page = failed_run
    fix(db, "LOAD")

    page.locator("#run-items li", has_text="Load").locator(".rerun-item").click()
    assert "Load" in page.locator("#rerun-summary").inner_text()
    page.locator("#rerun-resume").click()

    wait_for_status(page, "Succeeded")
    states = page.locator("#run-items .wf-state").all_inner_texts()
    assert states[1].endswith("attempt 2")
    assert states[2].startswith("Not run")         # only the job chosen was run again, not what waited for it


def test_a_step_that_may_have_changed_something_is_decided_for_each_job_before_resume_can_be_chosen(failed_run, db, tmp_path):
    page = failed_run
    load_run = db.query(JobRun).filter(JobRun.JobKey == "LOAD").one().RunID
    make_unknown(tmp_path, load_run)

    page.locator("#rerun-button").click()
    assert "may or may not have changed something" in page.locator("#rerun-decisions").inner_text()
    assert page.locator("#rerun-resume").is_disabled()
    assert page.locator("#rerun-restart").is_enabled()
    page.locator("#rerun-decisions").get_by_label("Count it as done").check()
    assert page.locator("#rerun-resume").is_enabled()


def test_a_run_that_is_running_or_succeeded_has_no_rerun_button(page, sim, flow):
    flow("OK", [("Only", sim("ONLY"))])
    page.goto("/ui/workflow.html?key=OK")
    page.locator("#run-button").click()
    wait_for_status(page, "Succeeded")
    assert page.locator("#rerun-button").is_hidden()


def test_job_history_has_a_rerun_button_on_a_failed_run(failed_run, db):
    page = failed_run
    fix(db, "LOAD")
    page.goto("/ui/history.html?job_type=WORKFLOW")
    wait_for_search(page)

    page.locator("button.rerun-row").first.click()
    page.locator("#rerun-restart").click()

    page.wait_for_url("**/workflow.html?*run=*")
    wait_for_status(page, "Succeeded")


def test_a_box_that_has_run_twice_is_marked_x2_on_the_diagram(failed_run, db):
    page = failed_run
    fix(db, "LOAD")
    page.locator("#rerun-button").click()
    page.locator("#rerun-resume").click()
    wait_for_status(page, "Succeeded")

    page.locator("#view-diagram").click()
    marks = page.locator("#run-diagram svg text", has_text="×2")
    page.locator("#run-diagram svg").first.wait_for()
    marks.first.wait_for()
    assert marks.count() == 1                  # Load only; Report had not run before

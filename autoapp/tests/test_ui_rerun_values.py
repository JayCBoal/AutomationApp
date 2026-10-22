"""
The values choices of a workflow's Resume on the Rerun dialog (docs/WORKFLOWS_PHASE7.md, step 4b-3): one list for each
workflow, use and resumed job, Edit sent back by level, the finished jobs named, and Refresh showing what changed.
"""
import pytest

from app.models import Audit, Job, Variable
from test_ui_rerun_workflow import wait_for_status
from test_workflow_runner import flow, sim    # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def outline_view(page):
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'outline')")


@pytest.fixture
def valued(page, seed, flow, db):
    """Extract succeeds; Load fails while the workflow's Fail is True; Report waits for Load. Run from the page."""
    load, extract, report = seed.job("LOAD"), seed.job("EXTRACT"), seed.job("REPORT")
    seed.step(load, 1, "SIMULATE", title="Load", Fail="${Fail}", Messages="Region ${Region}")
    seed.step(extract, 1, "SIMULATE", title="Extract", Fail="False")
    seed.step(report, 1, "SIMULATE", title="Report", Fail="False")
    workflow = flow("WF", [("Extract", extract), ("Load", load, ["Extract"]), ("Report", report, ["Load"])])
    seed.set_vars(workflow, Fail="True", Region="EU")
    db.commit()
    page.goto("/ui/workflow.html?key=WF")
    page.locator("#run-button").click()
    wait_for_status(page, "Failed")
    page.locator("#rerun-button").click()
    page.locator("#rerun-levels").wait_for()
    return page


def test_the_workflows_values_are_listed_once_with_the_finished_jobs_named_when_edited(valued):
    page = valued
    assert page.locator("#rerun-kept-jobs").is_hidden()          # nothing is changing yet
    assert page.locator(".rerun-level[data-kind=workflow]").count() == 1
    assert "Fail" in page.locator(".rerun-level[data-kind=workflow]").inner_text()
    assert "Fail" not in page.locator(".rerun-level[data-kind=job]").all_inner_texts().__str__()

    page.locator("#rerun-levels").get_by_label("Edit").check()
    page.get_by_label("Value of Fail in Workflow WF").fill("False")

    assert "Extract" in page.locator("#rerun-kept-jobs").inner_text()


def test_an_edit_in_the_workflows_list_reaches_the_job_that_resumes(valued, db):
    page = valued
    page.locator("#rerun-levels").get_by_label("Edit").check()
    page.get_by_label("Value of Fail in Workflow WF").fill("False")

    page.locator("#rerun-resume").click()

    wait_for_status(page, "Succeeded")
    assert db.query(Audit).filter(Audit.Action == "JOB_RESUMED_WITH_EDITS").count() >= 1


def test_refresh_shows_a_workflow_value_that_now_reads_differently(valued, db):
    page = valued
    owner = db.query(Job).filter(Job.JobKey == "WF").one().MasterObject_id
    db.query(Variable).filter_by(MasterObject_id=owner, VarName="Region").one().VarValue = "US"
    db.commit()
    page.locator("#rerun-close").click()
    page.locator("#rerun-button").click()
    page.locator("#rerun-levels").wait_for()

    page.locator("#rerun-levels").get_by_label("Refresh").check()

    changes = page.locator(".rerun-level[data-kind=workflow] .rerun-level-changes")
    assert "Region" in changes.inner_text() and "EU" in changes.inner_text() and "US" in changes.inner_text()
    assert "Extract" in page.locator("#rerun-kept-jobs").inner_text()

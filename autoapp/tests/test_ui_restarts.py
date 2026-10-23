"""
The Restarts box and Job History's "Restarted ×N" (docs/WORKFLOWS_PHASE7.md, step 5-3): a job run again on its own, and
a workflow run reopened with a frame inside it.
"""
import pytest

from conftest import wait_for_search
from test_control_file import gated_job, put_gate
from test_ui_rerun import run_to_failure, wait_for_outcome
from test_ui_rerun_workflow import failed_run, outline_view, wait_for_status    # noqa: F401 (fixtures)
from test_workflow_reopen import fix
from test_workflow_runner import flow, sim    # noqa: F401  (fixtures)


@pytest.fixture
def gated(seed, endpoints, db):
    gated_job(seed, name="DEV-RES")
    db.commit()


def test_a_job_run_again_lists_its_restarts_and_job_history_says_restarted(page, gated, tmp_path):
    run_to_failure(page)
    assert page.locator("#restarts-box").is_hidden() and page.locator("#restarted-count").is_hidden()
    put_gate(tmp_path, "a.ok", job="DEV-RES")
    page.locator("#rerun-button").click()
    page.locator("#rerun-resume").click()
    wait_for_outcome(page, "Succeeded")
    page.wait_for_function("() => document.querySelector('#job-log').textContent.includes('Resumed from attempt 1')")
    log_page = page.get_by_text("Its log page").get_attribute("href")

    page.goto("/ui/" + log_page)
    page.locator("#restarts-box").wait_for()

    box = page.locator("#restarts-box").inner_text()
    assert "Resumed from attempt 1" in box and "you (web interface)" in box
    assert page.locator("#restarted-count").inner_text() == "Restarted 1 time"

    page.goto("/ui/history.html")
    wait_for_search(page)
    page.locator(".restarted:visible").first.wait_for()     # the rows are drawn just after the search ends
    marks = page.locator(".restarted:visible").all_inner_texts()
    assert marks == ["Restarted ×1"]
    assert page.locator(".restarted:visible").get_attribute("title") == "Resumed by you"
    assert "attempt 2" not in page.locator("tbody").inner_text()


def test_a_reopened_workflow_run_lists_its_restarts_in_the_workflow_page(failed_run, db):
    page = failed_run
    fix(db, "LOAD")
    page.locator("#rerun-button").click()
    page.locator("#rerun-resume").click()
    wait_for_status(page, "Succeeded")

    page.locator("#restarts-box").wait_for()

    box = page.locator("#restarts-box").inner_text()
    assert "Resumed from attempt 1" in box and "Load goes on from attempt 1" in box
    assert page.locator("#restarted-count").inner_text() == "Restarted 1 time"


def test_a_job_run_again_inside_a_workflow_run_names_what_was_chosen(failed_run, db):
    page = failed_run
    fix(db, "LOAD")
    page.locator("#run-items li", has_text="Load").locator(".rerun-item").click()
    page.locator("#rerun-restart").click()
    wait_for_status(page, "Succeeded")

    page.locator("#restarts-box").wait_for()

    box = page.locator("#restarts-box").inner_text()
    assert "Restarted from the beginning" in box and "Run again: Load" in box

"""
Rerun on the Run Job page and a run's log page: Resume and Restart from beginning for a failed job,
and the dialog that asks about a step that may or may not have changed something.
"""
import pytest

from test_control_file import gated_job, put_gate
from test_reruns import make_unknown


@pytest.fixture
def gated(seed, endpoints, db):
    gated_job(seed, name="DEV-RES")
    db.commit()


def run_to_failure(page):
    page.goto("/ui/run.html?key=DEV-RES")
    page.locator("#run-check .status").wait_for()
    page.locator("#run-button").click()
    page.wait_for_function("() => document.querySelector('#run-outcome')?.textContent === 'Failed'", timeout=30000)


def wait_for_outcome(page, words):
    page.wait_for_function("words => document.querySelector('#run-outcome')?.textContent === words", arg=words, timeout=30000)


def test_resume_picks_up_a_failed_job_and_the_page_follows_the_new_attempt(page, gated, tmp_path):
    run_to_failure(page)
    put_gate(tmp_path, "a.ok", job="DEV-RES")

    page.locator("#rerun-button").click()
    assert "1 step finished" in page.locator("#rerun-summary").inner_text()
    page.locator("#rerun-resume").click()

    wait_for_outcome(page, "Succeeded")
    page.wait_for_function("() => document.querySelector('#job-log').textContent.includes('finished in the earlier attempt')")


def test_restart_runs_the_whole_job_again(page, gated):
    run_to_failure(page)

    page.locator("#rerun-button").click()
    page.locator("#rerun-restart").click()

    wait_for_outcome(page, "Failed")
    page.wait_for_function("() => document.querySelector('#job-log').textContent.includes('Collect')")
    assert "finished in the earlier attempt" not in page.locator("#job-log").inner_text()


def test_a_step_that_may_have_changed_something_is_decided_before_resume_can_be_chosen(page, gated, tmp_path):
    run_to_failure(page)
    run_id = page.evaluate("() => document.querySelector('[x-data]')._x_dataStack[0].run.run_id")
    make_unknown(tmp_path, run_id)

    page.locator("#rerun-button").click()
    assert "not known whether this step changed anything" in page.locator("#rerun-decision").inner_text()
    assert page.locator("#rerun-resume").is_disabled()
    page.get_by_label("Count it as done").check()
    assert page.locator("#rerun-resume").is_enabled()
    page.locator("#rerun-resume").click()

    wait_for_outcome(page, "Succeeded")
    page.wait_for_function("() => document.querySelector('#job-log').textContent.includes('counted as done')")


def test_a_job_that_succeeded_has_no_rerun_button(page, gated, tmp_path):
    put_gate(tmp_path, "a.ok", job="DEV-RES")
    page.goto("/ui/run.html?key=DEV-RES")
    page.locator("#run-check .status").wait_for()
    page.locator("#run-button").click()
    wait_for_outcome(page, "Succeeded")

    assert page.locator("#rerun-button").count() == 0 or not page.locator("#rerun-button").is_visible()

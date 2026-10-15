"""
The Run Job page and a run's log page, in a real browser against a real server.
Running a job starts the real runner, as a scheduler would.
"""
import pytest

from conftest import wait_for_search


@pytest.fixture
def collect(seed, endpoints, db):
    job = seed.job("DEV-COLLECT")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    broken = seed.job("DEV-BROKEN")
    seed.step(broken, 1, Source="nowhere/*.csv", Dest="out")
    db.commit()


def run_it(page):
    page.locator("#run-button").click()
    page.wait_for_function("() => ['Succeeded', 'Failed'].includes(document.querySelector('#run-outcome')?.textContent)",
                           timeout=30000)


def test_a_job_is_run_from_the_page_and_its_log_shown(page, collect):
    page.goto("/ui/run.html?key=DEV-COLLECT")
    page.locator("#run-check .status").wait_for()
    assert page.locator("#run-check .status").inner_text() == "Ready to run"
    page.locator("#run-instance").fill("UI-BROWSER-1")

    run_it(page)

    assert page.locator("#run-outcome").inner_text() == "Succeeded"
    assert "--instance-id UI-BROWSER-1" in page.locator("#run-command").inner_text()
    page.wait_for_function("() => document.querySelector('#job-log').textContent.includes('completed successfully')")
    log = page.locator("#job-log").inner_text()
    assert "BEGIN Step 1: Collect" in log


def test_a_failing_job_says_so_and_its_errors_stand_out(page, collect):
    page.goto("/ui/run.html?key=DEV-BROKEN")
    page.locator("#run-check .status").wait_for()           # nothing to find is only known when it runs

    run_it(page)

    assert page.locator("#run-outcome").inner_text() == "Failed"
    page.locator("#job-log .log-error").first.wait_for()
    assert "failed" in page.locator("#job-log .log-error").last.inner_text()


def test_the_run_button_waits_for_a_job_that_exists(page, collect):
    page.goto("/ui/run.html")
    page.wait_for_load_state("networkidle")
    assert page.locator("#run-button").is_disabled()

    page.locator("#run-job").fill("DEV-COLLECT")

    page.locator("#run-check .status").wait_for()
    assert page.locator("#run-button").is_enabled()


def test_job_history_links_to_each_runs_log(page, collect):
    page.goto("/ui/run.html?key=DEV-COLLECT")
    page.locator("#run-check .status").wait_for()
    run_it(page)

    page.goto("/ui/history.html")
    wait_for_search(page)
    page.locator("a.run-log").first.click()

    page.wait_for_url("**/ui/log.html?run=*")
    page.locator("#job-log").wait_for()
    assert page.locator("#run-outcome").inner_text() == "SUCCESS"
    assert "completed successfully" in page.locator("#job-log").inner_text()


def test_the_job_editor_has_a_run_button(page, collect):
    page.goto("/ui/job.html?key=DEV-COLLECT")
    page.wait_for_load_state("networkidle")

    page.locator("#run-job-button").click()

    page.wait_for_url("**/ui/run.html?key=DEV-COLLECT")
    assert page.locator("#run-job").input_value() == "DEV-COLLECT"

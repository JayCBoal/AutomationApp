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


def test_a_business_date_can_be_given(page, collect):
    page.goto("/ui/run.html?key=DEV-COLLECT")
    page.locator("#run-check .status").wait_for()
    page.locator("#run-business-date").fill("2026-09-30")

    run_it(page)

    assert "--business-date 2026-09-30" in page.locator("#run-command").inner_text()


def test_a_scheduler_is_registered_on_its_detail_page(page, db):
    page.goto("/ui/detail.html?kind=schedulers&new")
    page.wait_for_selector("#field-name")
    page.locator("#field-name").fill("CTM_PROD")
    page.locator("#field-technology").select_option("CONTROL_M")
    page.locator("#field-api_url").fill("https://ctm.example/automation-api")

    with page.expect_response(lambda r: r.request.method == "POST" and "/api/v1/schedulers" in r.url):
        page.locator("#submit-button").click()

    page.locator("#save-notice").wait_for(state="visible")
    assert page.locator("#field-technology").input_value() == "CONTROL_M"
    assert page.locator("#scheduler-runs").inner_text() == "0 runs"
    page.goto("/ui/search.html?kind=schedulers&technology=CONTROL_M")
    page.locator("a.item-name").first.wait_for()
    assert [a.inner_text() for a in page.locator("a.item-name").all()] == ["CTM_PROD"]


def test_a_job_is_found_with_the_job_search_criteria_and_chosen(page, collect, db):
    page.goto("/ui/run.html")
    assert sorted(r.locator("a.job-key").inner_text() for r in wait_for_search(page).all()) == ["DEV-BROKEN", "DEV-COLLECT"]
    page.locator("input[name=job_key]").fill("collect")
    page.locator("form[aria-label='Search criteria'] button[type=submit]").click()
    rows = wait_for_search(page)
    page.wait_for_function("() => document.querySelectorAll('table.results tbody tr').length === 1")
    assert "1 job," in page.locator("#result-summary").inner_text()

    rows.first.locator(".choose-job").click()

    assert page.locator("#run-job").input_value() == "DEV-COLLECT"
    page.locator("#run-check .status").wait_for()
    assert page.locator("#run-check .status").inner_text() == "Ready to run"
    assert rows.first.locator(".choose-job").inner_text() == "Chosen"
    assert "job_key=collect" in page.url and "key=DEV-COLLECT" in page.url     # both kept, for a reload


def test_the_search_finds_workflows_by_type(page, collect, seed, db):
    from core.models import Job
    db.add(Job(JobKey="DEV-FLOW", JobType="WORKFLOW", Description="A workflow"))
    db.commit()
    page.goto("/ui/run.html?job_type=WORKFLOW")
    rows = wait_for_search(page)
    assert [r.locator("a.job-key").inner_text() for r in rows.all()] == ["DEV-FLOW"]
    assert "Workflow" in rows.first.inner_text() and "0 jobs" in rows.first.inner_text()

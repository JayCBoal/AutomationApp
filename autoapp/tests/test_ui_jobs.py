"""
The Job Search page, in a real browser, against a real server.
The browser fixtures are in conftest.py.
"""
import csv

import pytest

from conftest import wait_for_search


@pytest.fixture
def jobs(db, seed, endpoints):
    """Three jobs: one that collects and delivers, one that only picks up, one disabled with a mistake in it."""
    collect = seed.job("DEV-LEGAL-COLLECT")
    collect.Description = "Collects legal extracts and delivers them to billing"
    seed.step(collect, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(collect, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")

    pickup = seed.job("dev-billing-pickup")
    seed.step(pickup, 1, title="Pick up", SourceEndpoint="BILLING_INBOX", Dest="to_load")
    seed.step(pickup, 2, title="Not yet", Source="to_load/*.csv", Dest="done").IsActive = False

    broken = seed.job("DEV-BROKEN")
    broken.IsActive = False
    seed.step(broken, 1, title="Collect", SourceEndpoint="NO_SUCH_ENDPOINT", Dest="incoming", Mvoe="True")
    db.commit()


def open_jobs(page, address="/ui/jobs.html"):
    page.goto(address)
    return wait_for_search(page)


def search(page):
    page.get_by_role("button", name="Search").click()
    page.wait_for_timeout(50)
    return wait_for_search(page)


def row_for(rows, job_key):
    return rows.filter(has=rows.page.locator(".job-key", has_text=job_key)).first


def test_page_lists_jobs_in_name_order_with_what_each_uses(page, jobs):
    rows = open_jobs(page)

    assert [row.locator(".job-key").inner_text() for row in rows.all()] == [
        "dev-billing-pickup", "DEV-BROKEN", "DEV-LEGAL-COLLECT"]
    assert "3 jobs, in name order" in page.locator("#result-summary").inner_text()

    collect = row_for(rows, "DEV-LEGAL-COLLECT")
    assert "Collects legal extracts and delivers them to billing" in collect.inner_text()
    assert collect.locator(".status").first.inner_text() == "Enabled"
    assert "2 steps" in collect.inner_text()
    assert [tag.inner_text() for tag in collect.locator(".tag").all()] == ["BILLING_INBOX", "LEGAL_EXTRACTS"]
    assert "Never run" in collect.inner_text()

    assert "1 step (+1 disabled)" in row_for(rows, "dev-billing-pickup").inner_text()
    assert row_for(rows, "DEV-BROKEN").locator(".status").first.inner_text() == "Disabled"


def test_last_run_shows_how_the_most_recent_run_went(page, jobs, outbox, run_runner, load_spool):
    run_runner("DEV-LEGAL-COLLECT", "88421")
    load_spool()
    succeeded = row_for(open_jobs(page), "DEV-LEGAL-COLLECT").locator(".last-run").inner_text()

    for leftover in outbox.glob("*.csv"):
        leftover.unlink()
    run_runner("DEV-LEGAL-COLLECT", "88422", "--run-number", "2")       # nothing left to collect
    load_spool()
    failed = row_for(open_jobs(page), "DEV-LEGAL-COLLECT").locator(".last-run")

    assert "SUCCESS" in succeeded and "instance 88421" in succeeded
    assert failed.locator(".status").inner_text() == "FAILED"
    assert "instance 88422" in failed.inner_text() and "run 2" in failed.inner_text()
    assert "No files matched" in failed.locator(".error-text").inner_text()


def test_criteria_narrow_the_results_and_clear_restores_them(page, jobs):
    open_jobs(page)

    page.locator("input[name=job_key]").fill("LEGAL")
    assert search(page).count() == 1

    page.locator("input[name=job_key]").fill("")
    page.locator("input[name=endpoint]").fill("billing_inbox")
    assert search(page).count() == 2

    page.locator("select[name=active]").select_option("false")
    assert search(page).count() == 0
    assert page.locator("#result-summary").inner_text() == "No jobs match these criteria."

    page.locator("input[name=endpoint]").fill("")
    rows = search(page)
    assert [row.locator(".job-key").inner_text() for row in rows.all()] == ["DEV-BROKEN"]

    page.get_by_role("button", name="Clear").click()
    page.wait_for_function("document.querySelectorAll('table.results tbody tr').length === 3")
    assert page.locator("select[name=active]").input_value() == ""


def test_a_search_can_be_bookmarked(page, jobs):
    open_jobs(page)
    page.locator("input[name=description]").fill("legal")
    page.locator("select[name=active]").select_option("true")
    search(page)
    address = page.url

    assert "description=legal" in address and "active=true" in address
    rows = open_jobs(page, address)
    assert rows.count() == 1
    assert page.locator("input[name=description]").input_value() == "legal"
    assert page.locator("select[name=active]").input_value() == "true"


def test_a_job_that_would_run_says_ready_in_green_and_one_that_would_not_says_check_in_bold_red(page, jobs):
    rows = open_jobs(page)
    ready_row, broken_row = row_for(rows, "DEV-LEGAL-COLLECT"), row_for(rows, "DEV-BROKEN")
    ready = ready_row.locator(".ready-text")
    broken = broken_row.get_by_role("button", name="Check")

    def look(link):
        return link.evaluate("e => [getComputedStyle(e).color, getComputedStyle(e).fontWeight]")

    def colour(name):
        return page.evaluate(f"""() => {{
            const probe = document.createElement('span');
            probe.style.color = getComputedStyle(document.documentElement).getPropertyValue('{name}');
            document.body.appendChild(probe);
            const shown = getComputedStyle(probe).color;
            probe.remove();
            return shown;
        }}""")

    assert ready.inner_text() == "Ready to run"
    assert look(ready) == [colour("--success"), "400"]              # green, not bold
    assert broken.inner_text() == "Check"
    assert look(broken) == [colour("--failure"), "700"]             # red and bold
    assert colour("--success") != colour("--failure")
    assert broken.get_attribute("title") == "2 problems found: click to see"
    # "Ready to run" is plain text, with nothing to click; a job shows one or the other, never both
    assert ready_row.locator("button.check-link").is_hidden()
    assert ready_row.get_by_role("button").count() == 0         # no button is on show in that row
    assert broken_row.locator(".ready-text").is_hidden()


def test_check_on_a_job_fixed_since_the_search_says_it_is_now_ready(page, jobs, db):
    """The red link reflects the search. Clicking it checks again, so a job mended in the meantime shows as ready."""
    from app.models import Job, JobStepParameter
    rows = open_jobs(page)
    broken = db.query(Job).filter(Job.JobKey == "DEV-BROKEN").one()
    broken.IsActive = True
    for parameter in broken.steps[0].parameters:
        if parameter.ParamName == "Mvoe":
            db.delete(parameter)
        elif parameter.ParamName == "SourceEndpoint":
            parameter.ParamValue = "LEGAL_EXTRACTS"
    db.commit()

    row_for(rows, "DEV-BROKEN").get_by_role("button", name="Check").click()

    window = page.locator("dialog.check")
    window.locator(".all-clear").wait_for()
    assert window.locator("h2").inner_text() == "Check: DEV-BROKEN"
    assert "No problems found. This job is ready to run." in window.inner_text()
    assert window.locator("ul.problems").count() == 0

    window.get_by_role("button", name="Close").click()
    assert not window.is_visible()


def test_check_lists_every_problem_in_a_job(page, jobs):
    rows = open_jobs(page)

    row_for(rows, "DEV-BROKEN").get_by_role("button", name="Check").click()

    window = page.locator("dialog.check")
    window.locator("ul.problems li").first.wait_for()
    problems = [item.inner_text() for item in window.locator("ul.problems li").all()]
    assert window.locator("h2").inner_text() == "Check: DEV-BROKEN"
    assert "2 problems found" in window.inner_text()
    assert problems[0] == "Job 'DEV-BROKEN' is disabled."
    assert problems[1].startswith("Step 1 ('Collect'): Unknown parameter 'Mvoe'.")
    assert window.locator(".all-clear").count() == 0


def test_operations_link_opens_the_log_for_that_job(page, jobs, run_runner, load_spool):
    run_runner("DEV-LEGAL-COLLECT", "88421")
    load_spool()
    rows = open_jobs(page)

    row_for(rows, "DEV-LEGAL-COLLECT").get_by_role("link", name="Operations").click()

    page.wait_for_url("**/ui/operations.html?job_key=DEV-LEGAL-COLLECT")
    assert wait_for_search(page).count() == 4
    assert page.locator("input[name=job_key]").input_value() == "DEV-LEGAL-COLLECT"


def test_export_as_csv_gives_the_jobs_on_screen(page, jobs, run_runner, load_spool):
    run_runner("DEV-LEGAL-COLLECT", "88421")
    load_spool()
    open_jobs(page, "/ui/jobs.html?active=true")

    with page.expect_download() as download:
        page.get_by_role("button", name="Export as CSV").click()

    assert download.value.suggested_filename == "autoapp_jobs.csv"
    with open(download.value.path(), newline="") as f:
        exported = {row["Job"]: row for row in csv.DictReader(f)}
    assert sorted(exported) == ["DEV-LEGAL-COLLECT", "dev-billing-pickup"]
    collect = exported["DEV-LEGAL-COLLECT"]
    assert (collect["Enabled"], collect["Enabled steps"], collect["Disabled steps"]) == ("Yes", "2", "0")
    assert collect["Endpoints"] == "BILLING_INBOX; LEGAL_EXTRACTS"
    assert (collect["Ready to run"], collect["Problems"]) == ("Yes", "0")
    assert (collect["Last run status"], collect["Last run instance ID"]) == ("SUCCESS", "88421")
    assert exported["dev-billing-pickup"]["Last run status"] == ""


def test_text_from_the_database_is_shown_as_text_not_run_as_html(page, db, seed):
    markup = '<img src=x onerror="window.hacked=true">'
    job = seed.job("DEV-ODD")
    job.Description = f"Description {markup}"
    seed.step(job, 1, SourceEndpoint=f"E{markup}", Dest="in")
    db.commit()

    rows = open_jobs(page)
    rows.get_by_role("button", name="Check").click()
    page.locator("dialog.check ul.problems li").first.wait_for()

    assert page.locator("main img").count() == 0
    assert page.evaluate("window.hacked") is None
    assert markup in rows.inner_text() and markup in page.locator("dialog.check").inner_text()


def test_jobs_is_marked_as_the_current_page_in_the_navigation(page, jobs):
    open_jobs(page)

    assert "current" in page.locator("nav.app-nav").get_by_role("link", name="Jobs").get_attribute("class")
    assert page.title() == "Jobs - AutoApp"

"""
The Job Search page, in a real browser, against a real server.
The browser fixtures are in conftest.py.
"""
import csv

import pytest

from conftest import wait_for_search


@pytest.fixture
def jobs(db, seed, endpoints):
    """Four jobs: one that collects and delivers, one that only picks up, one with a mistake in it, one disabled."""
    collect = seed.job("DEV-LEGAL-COLLECT")
    collect.Description = "Collects legal extracts and delivers them to billing"
    seed.step(collect, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(collect, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")

    pickup = seed.job("dev-billing-pickup")
    seed.step(pickup, 1, title="Pick up", SourceEndpoint="BILLING_INBOX", Dest="to_load")
    seed.step(pickup, 2, title="Not yet", Source="to_load/*.csv", Dest="done").IsActive = False

    broken = seed.job("DEV-BROKEN")
    seed.step(broken, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming", Mvoe="True")
    seed.step(broken, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="NO_SUCH_ENDPOINT")

    retired = seed.job("DEV-RETIRED")
    retired.IsActive = False
    seed.step(retired, 1, title="Collect", SourceEndpoint="NO_SUCH_ENDPOINT", Dest="incoming")
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
        "dev-billing-pickup", "DEV-BROKEN", "DEV-LEGAL-COLLECT", "DEV-RETIRED"]
    assert "4 jobs, in name order" in page.locator("#result-summary").inner_text()

    collect = row_for(rows, "DEV-LEGAL-COLLECT")
    assert "Collects legal extracts and delivers them to billing" in collect.inner_text()
    assert collect.locator(".status").first.inner_text() == "Enabled"
    assert "2 steps" in collect.inner_text()
    assert [tag.inner_text() for tag in collect.locator(".tag").all()] == ["BILLING_INBOX", "LEGAL_EXTRACTS"]
    assert "Never run" in collect.inner_text()

    assert "1 step (+1 disabled)" in row_for(rows, "dev-billing-pickup").inner_text()
    assert row_for(rows, "DEV-RETIRED").locator(".status").first.inner_text() == "Disabled"


def test_each_job_says_when_it_was_last_changed_and_by_whom(page, jobs):
    rows = open_jobs(page)

    changed = row_for(rows, "DEV-LEGAL-COLLECT").locator(".last-changed")
    assert changed.locator("div").first.inner_text().startswith("20")
    assert changed.locator("div").nth(1).inner_text() == "by system"


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
    assert [row.locator(".job-key").inner_text() for row in rows.all()] == ["DEV-RETIRED"]

    page.get_by_role("button", name="Clear").click()
    page.wait_for_function("document.querySelectorAll('table.results tbody tr').length === 4")
    assert page.locator("select[name=active]").input_value() == ""


def test_the_job_and_endpoint_boxes_offer_drop_downs(page, jobs):
    open_jobs(page)
    page.wait_for_selector("#lookup-endpoints", state="attached")

    assert page.locator("input[name=job_key]").get_attribute("list") == "lookup-jobs"
    assert page.locator("input[name=endpoint]").get_attribute("list") == "lookup-endpoints"
    assert [o.get_attribute("value") for o in page.locator("#lookup-endpoints option").all()] == [
        "BILLING_INBOX", "LEGAL_EXTRACTS"]
    assert page.locator("#lookup-jobs option").count() == 4
    assert page.locator("input[name=description]").get_attribute("list") is None


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
    assert broken.get_attribute("title") == "2 problems found: click to see"         # one in each step
    # "Ready to run" is plain text, with nothing to click; a job shows one or the other, never both
    assert ready_row.locator("button.check-link").is_hidden()
    assert ready_row.get_by_role("button").count() == 0         # no button is on show in that row
    assert broken_row.locator(".ready-text").is_hidden()


def test_a_disabled_job_says_disabled_in_grey_with_no_link_whatever_else_is_wrong(page, jobs):
    rows = open_jobs(page)
    retired = row_for(rows, "DEV-RETIRED")          # disabled, and its step names an endpoint that does not exist

    label = retired.locator(".disabled-text")
    muted = page.evaluate("""() => {
        const probe = document.createElement('span');
        probe.style.color = getComputedStyle(document.documentElement).getPropertyValue('--muted');
        document.body.appendChild(probe);
        const shown = getComputedStyle(probe).color;
        probe.remove();
        return shown;
    }""")
    assert label.inner_text() == "Disabled"
    assert label.evaluate("e => [getComputedStyle(e).color, getComputedStyle(e).fontWeight]") == [muted, "400"]
    assert retired.get_by_role("button").count() == 0               # no Check link
    assert retired.locator(".ready-text").is_hidden()
    # and the other jobs do not say Disabled
    assert row_for(rows, "DEV-BROKEN").locator(".disabled-text").is_hidden()
    assert row_for(rows, "DEV-LEGAL-COLLECT").locator(".disabled-text").is_hidden()


def test_job_key_opens_the_job_locked_and_edit_opens_it_unlocked(page, jobs):
    rows = open_jobs(page)
    row_for(rows, "dev-billing-pickup").locator("a.job-key").click()
    page.wait_for_url("**/ui/job.html?key=dev-billing-pickup")
    page.wait_for_selector("#job-key")
    assert page.locator("#job-key").is_disabled()

    rows = open_jobs(page)
    row_for(rows, "DEV-LEGAL-COLLECT").get_by_role("link", name="Edit").click()
    page.wait_for_url("**/ui/job.html?key=DEV-LEGAL-COLLECT&edit")
    page.wait_for_selector("#cancel-button:visible")
    assert page.locator("#job-key").is_enabled()


def test_new_job_button_opens_a_blank_job_ready_to_fill_in(page, jobs):
    open_jobs(page)

    page.get_by_role("link", name="New job").click()

    page.wait_for_url("**/ui/job.html?new")
    page.wait_for_selector("#job-key")
    assert page.locator("#job-key").input_value() == "" and page.locator("#job-key").is_enabled()


def test_check_on_a_job_fixed_since_the_search_says_it_is_now_ready(page, jobs, db):
    """The red link reflects the search. Clicking it checks again, so a job mended in the meantime shows as ready."""
    from app.models import Job, JobStepParameter
    rows = open_jobs(page)
    broken = db.query(Job).filter(Job.JobKey == "DEV-BROKEN").one()
    for step in broken.steps:
        for parameter in step.parameters:
            if parameter.ParamName == "Mvoe":
                db.delete(parameter)
            elif parameter.ParamName == "DestEndpoint":
                parameter.ParamValue = "BILLING_INBOX"
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
    assert problems[0].startswith("Step 1 ('Collect'): Unknown parameter 'Mvoe'.")
    assert problems[1].startswith("Step 2 ('Deliver'): 'DestEndpoint' refers to Endpoint 'NO_SUCH_ENDPOINT'")
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
    assert sorted(exported) == ["DEV-BROKEN", "DEV-LEGAL-COLLECT", "dev-billing-pickup"]     # not the disabled one
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

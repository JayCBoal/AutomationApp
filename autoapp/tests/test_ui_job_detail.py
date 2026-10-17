"""
The Job Detail page as it arrives: showing a job, locked. Changing a job is in
test_ui_job_edit.py. Both run in a real browser against a real server; the
browser fixtures are in conftest.py.
"""
import pytest

from app.models import StepType


@pytest.fixture
def jobs(db, seed, endpoints):
    job = seed.job("DEV-LEGAL-COLLECT", Folder="staging")
    job.Description = "Collects legal extracts and delivers them to billing"
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX",
              Move="True", Checksum="${VerifyFiles}", LogLevel="SUMMARY")
    seed.step(job, 3, title="Tidy up", Source="incoming/*.csv", Dest="${Folder}", AllowNoFiles="True").IsActive = False

    other = seed.job("DEV-OTHER")
    seed.step(other, 1, title="Only step", SourceEndpoint="LEGAL_EXTRACTS", Dest="in")
    db.commit()


def open_job(page, key="DEV-LEGAL-COLLECT"):
    page.goto(f"/ui/job.html?key={key}")
    page.wait_for_selector("#job-key, #page-error:visible")
    page.wait_for_load_state("networkidle")
    return page.locator(".step")


def expand(step):
    """Opens a step and waits until its parameters are on show."""
    step.locator(".expander").click()
    step.locator(".step-body").wait_for(state="visible")


def expand_all(page, steps):
    page.get_by_role("button", name="Expand all").click()
    for step in steps.all():
        step.locator(".step-body").wait_for(state="visible")


def field(step, name):
    return step.locator(f'.field-row[data-parameter="{name}"]')


def test_page_shows_the_job_and_how_a_scheduler_would_run_it(page, jobs):
    open_job(page)

    assert page.locator("#job-key").input_value() == "DEV-LEGAL-COLLECT"
    assert page.locator("#job-description").input_value() == "Collects legal extracts and delivers them to billing"
    assert page.locator("#job-enabled").is_checked()
    assert page.locator("#command-line").inner_text() == (
        "python3 -m engine.runner --job-key DEV-LEGAL-COLLECT --instance-id <the scheduler's instance ID>")
    assert page.title() == "DEV-LEGAL-COLLECT - AutoApp"
    assert "current" in page.locator("nav.app-nav").get_by_role("link", name="Jobs").get_attribute("class")


def test_the_page_arrives_locked(page, jobs):
    steps = open_job(page)
    expand_all(page, steps)

    assert page.locator("#job-key").is_disabled() and page.locator("#job-description").is_disabled()
    boxes = steps.locator("input:visible, select:visible")
    assert boxes.count() > 20
    assert all(box.is_disabled() for box in boxes.all())
    assert page.locator("#edit-button").is_enabled()
    assert not page.locator("#submit-button").is_visible()


def test_steps_are_listed_in_order_and_start_collapsed(page, jobs):
    steps = open_job(page)

    assert [(s.locator(".step-order").inner_text(), s.locator(".step-title").inner_text()) for s in steps.all()] == [
        ("1", "Collect"), ("2", "Deliver"), ("3", "Tidy up")]
    assert [s.locator(".tag").inner_text() for s in steps.all()] == ["Copy Files"] * 3
    assert all(not s.locator(".step-body").is_visible() for s in steps.all())
    # collapsed, a step still says where it takes files from and puts them
    assert steps.nth(0).locator(".step-summary").inner_text() == "LEGAL_EXTRACTS → incoming"
    assert steps.nth(1).locator(".step-summary").inner_text() == "incoming/*.csv → BILLING_INBOX"
    # the disabled step is listed, unticked and struck through
    assert [s.locator(".step-head input[type=checkbox]").is_checked() for s in steps.all()] == [True, True, False]
    assert "disabled" in steps.nth(2).get_attribute("class")


def test_the_expand_button_is_big_enough_to_see_and_hit(page, jobs):
    steps = open_job(page)

    box = steps.nth(0).locator(".expander").bounding_box()

    assert box["width"] >= 28 and box["height"] >= 26
    assert steps.nth(0).locator(".expander").inner_text() == "▶"
    expand(steps.nth(0))
    assert steps.nth(0).locator(".expander").inner_text() == "▼"


def test_a_step_expands_and_collapses(page, jobs):
    steps = open_job(page)
    first, second = steps.nth(0), steps.nth(1)

    first.locator(".expander").click()
    first.locator(".step-body").wait_for(state="visible")
    assert not second.locator(".step-body").is_visible()
    assert not first.locator(".step-summary").is_visible()
    assert first.locator(".expander").get_attribute("aria-expanded") == "true"

    first.locator(".expander").click()
    first.locator(".step-body").wait_for(state="hidden")
    assert first.locator(".expander").get_attribute("aria-expanded") == "false"

    page.get_by_role("button", name="Expand all").click()
    for step in steps.all():
        step.locator(".step-body").wait_for(state="visible")
    page.get_by_role("button", name="Collapse all").click()
    for step in steps.all():
        step.locator(".step-body").wait_for(state="hidden")


def test_a_steps_form_has_one_field_per_catalog_parameter_in_catalog_order(page, jobs):
    steps = open_job(page)
    expand(steps.nth(0))

    rows = steps.nth(0).locator(".field-row[data-parameter]")
    assert [row.get_attribute("data-parameter") for row in rows.all()] == [
        "Source", "Dest", "RenameMask", "Move", "CreateFolder", "Checksum", "AllowNoFiles", "LogLevel"]
    # required parameters are marked, and each field explains itself
    assert [row.locator(".required").is_visible() for row in rows.all()] == [True, True] + [False] * 6
    assert field(steps.nth(0), "Move").locator(".field-help").inner_text() == (
        "Remove each file from the source once it has arrived")


def test_a_location_shows_whether_it_is_an_endpoint_or_a_working_folder_path(page, jobs):
    steps = open_job(page)
    expand(steps.nth(0))

    source, dest = field(steps.nth(0), "Source"), field(steps.nth(0), "Dest")
    radios = lambda row: [radio.is_checked() for radio in row.locator("input[type=radio]").all()]
    assert radios(source) == [True, False]                           # [endpoint, working folder path]
    assert (source.locator(".endpoint-value").input_value(), source.locator(".path-value").input_value()) == (
        "LEGAL_EXTRACTS", "")
    assert radios(dest) == [False, True]
    assert (dest.locator(".endpoint-value").input_value(), dest.locator(".path-value").input_value()) == ("", "incoming")


def test_stored_values_are_shown_and_missing_ones_show_the_default(page, jobs):
    steps = open_job(page)
    expand_all(page, steps)
    collect, deliver, tidy = steps.nth(0), steps.nth(1), steps.nth(2)

    # true/false parameters are tick boxes
    assert field(deliver, "Move").locator("input[type=checkbox]").is_checked()
    assert not field(deliver, "Move").get_by_text("default").is_visible()        # a stored value, not a default
    assert not field(collect, "Move").locator("input[type=checkbox]").is_checked()
    assert field(collect, "Move").get_by_text("default").is_visible()
    assert field(collect, "CreateFolder").locator("input[type=checkbox]").is_checked()      # default is True
    assert field(tidy, "AllowNoFiles").locator("input[type=checkbox]").is_checked()
    # a choice is a list
    assert field(deliver, "LogLevel").locator("select").input_value() == "SUMMARY"
    assert field(collect, "LogLevel").locator("select").input_value() == ""
    assert [o.inner_text() for o in field(collect, "LogLevel").locator("option").all()] == [
        "(not set)", "DEBUG", "DETAIL", "SUMMARY", "SILENT"]
    # placeholders are shown as written, not resolved
    assert field(tidy, "Dest").locator(".path-value").input_value() == "${Folder}"


def test_a_true_or_false_value_written_as_a_placeholder_is_shown_as_text(page, jobs):
    steps = open_job(page)
    expand(steps.nth(1))

    checksum = field(steps.nth(1), "Checksum")

    assert checksum.locator("input[type=checkbox]").count() == 0
    assert checksum.locator("input[type=text]").input_value() == "${VerifyFiles}"


def test_a_job_that_would_run_says_so(page, jobs):
    open_job(page, "DEV-OTHER")

    assert page.locator("#runnability").inner_text() == "Ready to run"
    assert not page.locator("#job-problems").is_visible()


def test_a_job_with_problems_lists_them(page, jobs):
    """Step 2's Checksum is ${VerifyFiles}, and the job has no such variable."""
    open_job(page)

    assert page.locator("#runnability").inner_text() == "1 problem found by the pre-run check"
    [problem] = [item.inner_text() for item in page.locator("#job-problems li").all()]
    assert problem.startswith("Step 2 ('Deliver')") and "${VerifyFiles}" in problem


def test_a_disabled_job_says_so_and_its_other_problems_are_still_listed(page, db, seed, endpoints):
    job = seed.job("DEV-RETIRED")
    job.IsActive = False
    seed.step(job, 1, title="Collect", SourceEndpoint="NO_SUCH_ENDPOINT", Dest="incoming")
    db.commit()

    open_job(page, "DEV-RETIRED")

    assert not page.locator("#job-enabled").is_checked()
    assert "Disabled. The runner refuses a disabled job." in page.locator("#runnability").inner_text()
    [problem] = [item.inner_text() for item in page.locator("#job-problems li").all()]
    assert "NO_SUCH_ENDPOINT" in problem                    # "is disabled" is not repeated as a problem


def test_a_parameter_the_step_type_does_not_have_is_pointed_out(page, db, seed, endpoints):
    job = seed.job("DEV-TYPO")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming", Mvoe="True")
    db.commit()

    steps = open_job(page, "DEV-TYPO")
    expand(steps.nth(0))

    unknown = steps.nth(0).locator(".unknown-parameters")
    assert unknown.is_visible()
    assert "Not parameters of this step type" in unknown.inner_text()
    assert unknown.locator(".label").inner_text() == "Mvoe"
    assert unknown.locator("input").input_value() == "True"


def test_a_step_with_nothing_wrong_shows_no_unknown_parameters(page, jobs):
    steps = open_job(page)
    expand_all(page, steps)

    assert all(not s.locator(".unknown-parameters").is_visible() for s in steps.all())


def test_a_step_whose_type_has_no_catalog_entry_shows_what_it_stores(page, db, seed):
    job = seed.job("DEV-FUTURE")
    seed.step(job, 1, title="Run a query", code="SQL_EXEC", Query="SELECT 1")
    db.commit()

    steps = open_job(page, "DEV-FUTURE")
    expand(steps.nth(0))

    assert steps.nth(0).locator(".tag").inner_text() == "SQL_EXEC"
    assert steps.nth(0).locator(".unknown-parameters .label").inner_text() == "Query"
    assert "Unknown step type" in page.locator("#job-problems").inner_text()


def test_the_selector_lists_every_job_and_opens_the_one_chosen(page, jobs):
    open_job(page)

    selector = page.locator("#job-selector")
    assert selector.input_value() == "DEV-LEGAL-COLLECT"
    assert [o.get_attribute("value") for o in page.locator("#job-keys option").all()] == ["DEV-LEGAL-COLLECT", "DEV-OTHER"]

    selector.fill("DEV-OTHER")
    selector.dispatch_event("change")

    page.wait_for_url("**/ui/job.html?key=DEV-OTHER")
    page.wait_for_selector("#job-key")
    assert page.locator("#job-key").input_value() == "DEV-OTHER"


def test_typing_something_that_is_not_a_job_goes_nowhere(page, jobs):
    open_job(page)

    page.locator("#job-selector").fill("DEV-OTH")
    page.locator("#job-selector").dispatch_event("change")
    page.wait_for_timeout(300)

    assert page.url.endswith("key=DEV-LEGAL-COLLECT")


def test_with_no_job_chosen_the_page_asks_for_one(page, jobs):
    page.goto("/ui/job.html")
    page.wait_for_selector("#choose-prompt")

    assert "Choose a job above" in page.locator("#choose-prompt").inner_text()
    assert page.locator("#job-key").count() == 0


def test_an_unknown_job_says_so(page_expecting_refusals, jobs):
    page = page_expecting_refusals
    page.goto("/ui/job.html?key=NO_SUCH_JOB")
    page.wait_for_selector("#page-error:visible")

    assert "No job with JobKey 'NO_SUCH_JOB' exists." in page.locator("#page-error").inner_text()
    assert page.locator("#job-key").count() == 0


def test_the_operations_link_opens_this_jobs_operations(page, jobs, run_runner, load_spool):
    open_job(page, "DEV-OTHER")

    page.get_by_role("link", name="See its operations").click()

    page.wait_for_url("**/ui/operations.html?job_key=DEV-OTHER")


def test_text_from_the_database_is_shown_as_text_not_run_as_html(page, db, seed):
    markup = '<img src=x onerror="window.hacked=true">'
    job = seed.job("DEV-ODD")
    job.Description = f"D{markup}"
    seed.step(job, 1, title=f"T{markup}", SourceEndpoint=f"E{markup}", Dest=f"p{markup}", **{"Odd": f"V{markup}"})
    db.commit()

    steps = open_job(page, "DEV-ODD")
    expand(steps.nth(0))

    assert page.locator("main img").count() == 0
    assert page.evaluate("window.hacked") is None
    assert steps.nth(0).locator(".step-title").inner_text() == f"T{markup}"
    assert field(steps.nth(0), "Source").locator(".endpoint-value").input_value() == f"E{markup}"

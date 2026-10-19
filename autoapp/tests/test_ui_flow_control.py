"""
Steps inside steps on the Job Detail page (docs/FLOW_CONTROL.md): an If with its
branches, loops, moving steps in and out of blocks, step names and On failure.
In a real browser, against a real server; the browser fixtures are in conftest.py.
"""
import pytest

from test_ui_job_edit import edit, expand, field, open_job, stored, submit


@pytest.fixture
def job(db, seed, endpoints):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", name="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Archive", name="Archive", Source="incoming/*.csv", Dest="archive")
    seed.step(job, 3, title="Deliver", name="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX")
    db.commit()


def numbers(page):
    return page.locator(".step .step-order").all_inner_texts()


def retype(step, code):
    step.locator("select.step-type").select_option(code)


def test_a_step_turned_into_an_if_gets_its_then_and_can_be_given_an_else(page, job):
    steps = open_job(page)
    edit(page)
    archive = steps.nth(1)
    retype(archive, "IF")
    expand(archive)
    field(archive, "Condition").locator(".cond-text-tab").click()      # a new condition opens in the builder
    field(archive, "Condition").locator("textarea").fill("%{Collect.FileCount} > 0")
    assert page.locator('.step-branch[data-branch="THEN"]').count() == 1

    page.locator(".add-step-into").first.click()                 # a step inside the Then
    inner = page.locator('.step[data-step-number="2.1"]')
    inner.locator(".step-title-input").fill("Keep a copy")
    field(inner, "Source").locator('input[type=radio][value="path"]').check()
    field(inner, "Source").locator(".path-value").fill("incoming/*.csv")
    field(inner, "Dest").locator('input[type=radio][value="path"]').check()
    field(inner, "Dest").locator(".path-value").fill("kept")
    page.locator(".add-else").click()
    assert numbers(page) == ["1", "2", "2.1", "3"]

    submit(page)
    saved = stored(page)["steps"]
    assert [s["step_type"] for s in saved] == ["COPY_FILES", "IF", "COPY_FILES"]
    then, otherwise = saved[1]["children"]
    assert (then["step_type"], otherwise["step_type"]) == ("THEN", "ELSE")
    assert [(s["number"], s["title"], s["name"]) for s in then["children"]] == [("2.1", "Keep a copy", "Keep_a_copy")]


def test_a_new_steps_name_follows_its_title_until_it_is_changed_by_hand(page, job):
    open_job(page)
    edit(page)
    page.locator("#add-step").click()
    new = page.locator('.step[data-step-number="4"]')
    new.locator(".step-title-input").fill("Check the files")
    assert new.locator("input.step-name").input_value() == "Check_the_files"
    new.locator("input.step-name").fill("Check")
    new.locator(".step-title-input").fill("Check the files again")
    assert new.locator("input.step-name").input_value() == "Check"


def test_a_saved_steps_name_does_not_follow_its_title(page, job):
    steps = open_job(page)
    edit(page)
    steps.nth(0).locator(".step-title-input").fill("Collect the batch")
    expand(steps.nth(0))
    assert steps.nth(0).locator("input.step-name").input_value() == "Collect"


def test_a_step_is_moved_into_a_loop_and_out_again(page, job):
    steps = open_job(page)
    edit(page)
    retype(steps.nth(1), "WHILE")
    page.locator('.step[data-step-number="3"] .move-in').click()
    assert numbers(page) == ["1", "2", "2.1"]
    page.locator('.step[data-step-number="2.1"] .move-out').click()
    assert numbers(page) == ["1", "2", "3"]


def test_on_failure_is_saved(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))
    steps.nth(0).locator("select.step-on-failure").select_option("CONTINUE")
    submit(page)
    assert stored(page)["steps"][0]["on_failure"] == "CONTINUE"
    assert "on failure" in page.locator("#save-notice").inner_text()


def test_a_condition_comparing_a_number_with_text_is_pointed_out_under_it(page, job):
    steps = open_job(page)
    edit(page)
    archive = steps.nth(1)
    retype(archive, "IF")
    expand(archive)
    field(archive, "Condition").locator(".cond-text-tab").click()      # a new condition opens in the builder
    field(archive, "Condition").locator("textarea").fill("%{Collect.FileCount} > '1'")
    warning = field(archive, "Condition").locator(".field-warning")
    warning.wait_for(state="visible")
    assert "compares a number with text" in warning.inner_text()

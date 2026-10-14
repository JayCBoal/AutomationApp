"""
The job editor's Variables panel, and its live preview of what each value
resolves to. In a real browser, against a real server; the browser fixtures
are in conftest.py.
"""
import pytest

from app.models import Variable


@pytest.fixture
def job(db, seed, endpoints):
    job = seed.job("DEV-LOAD", Folder="staging")
    db.add(Variable(MasterObject_id=job.MasterObject_id, VarName="ApiToken", VarValue="s3cr3t-t0ken", IsSecret=True))
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="${Folder}/in")
    seed.step(job, 2, title="Deliver", Source="${Folder}/in/*.csv", DestEndpoint="BILLING_INBOX")
    db.commit()


def open_job(page, key="DEV-LOAD"):
    page.goto(f"/ui/job.html?key={key}")
    page.wait_for_selector("#job-key")
    page.wait_for_load_state("networkidle")
    return page.locator(".step")


def edit(page):
    page.locator("#edit-button").click()
    page.locator("#cancel-button").wait_for(state="visible")


def submit(page):
    with page.expect_response(lambda r: "/api/v1/jobs" in r.url and "/preview" not in r.url
                              and r.request.method in ("POST", "PUT")):
        page.locator("#submit-button").click()
    page.wait_for_function("() => Alpine.$data(document.querySelector('main')).busy === false")


def expand(step):
    step.locator(".expander").click()
    step.locator(".step-body").wait_for(state="visible")


def field(step, name):
    return step.locator(f'.field-row[data-parameter="{name}"]')


def variables(page):
    return page.locator("table.variables tbody tr")


def wait_for_preview(page):
    """The preview follows the form after a short pause; this waits until it has caught up."""
    page.wait_for_timeout(450)
    page.wait_for_load_state("networkidle")


def stored(page, key="DEV-LOAD"):
    return page.request.get(f"/api/v1/jobs/{key}").json()


# --- The Variables panel --------------------------------------------------------------------------

def test_a_jobs_variables_are_listed_and_a_secrets_value_is_not_shown(page, job):
    open_job(page)

    rows = variables(page)
    assert [row.locator(".variable-name").input_value() for row in rows.all()] == ["ApiToken", "Folder"]
    token, folder = rows.nth(0), rows.nth(1)
    assert folder.locator(".variable-value").input_value() == "staging"
    assert not folder.locator(".variable-secret").is_checked()
    assert token.locator(".variable-secret").is_checked()
    assert token.locator(".variable-value").input_value() == ""                 # the value never reaches the page
    assert token.locator(".variable-value").get_attribute("type") == "password"
    assert token.locator(".variable-value").get_attribute("placeholder") == "Set. Type a new value to replace it."
    assert "s3cr3t-t0ken" not in page.content()
    # locked until Edit is pressed
    assert all(box.is_disabled() for box in rows.locator("input").all())
    assert not page.locator("#add-variable").is_visible()


def test_a_job_with_no_variables_says_so(page, db, seed, endpoints):
    seed.step(seed.job("DEV-PLAIN"), 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="in")
    db.commit()

    open_job(page, "DEV-PLAIN")

    assert page.locator("#no-variables").is_visible()
    assert not page.locator("table.variables").is_visible()


def test_a_variable_is_added_changed_and_removed(page, job):
    open_job(page)
    edit(page)

    page.locator("#add-variable").click()
    new = variables(page).nth(2)
    new.locator(".variable-name").fill("Pattern")
    new.locator(".variable-value").fill("*.csv")
    new.locator(".variable-description").fill("Which files to take")
    variables(page).nth(1).locator(".variable-value").fill("holding")           # Folder
    submit(page)

    assert page.locator("#save-notice").inner_text() == "Saved. Added variable Pattern. Changed variable Folder."
    saved = {v["name"]: v for v in stored(page)["variables"]}
    assert (saved["Pattern"]["value"], saved["Pattern"]["description"]) == ("*.csv", "Which files to take")
    assert saved["Folder"]["value"] == "holding"

    edit(page)
    variables(page).filter(has=page.locator('.variable-name')).nth(0).locator(".remove-variable").click()    # ApiToken
    submit(page)
    assert page.locator("#save-notice").inner_text() == "Saved. Removed variable ApiToken."
    assert [v["name"] for v in stored(page)["variables"]] == ["Folder", "Pattern"]


def test_saving_other_changes_leaves_a_secret_as_it_was(page, db, job):
    open_job(page)
    edit(page)
    page.locator("#job-description").fill("Edited")

    submit(page)

    assert page.locator("#save-notice").inner_text() == "Saved. Changed the description."
    db.commit()
    assert db.query(Variable).filter(Variable.VarName == "ApiToken").one().VarValue == "s3cr3t-t0ken"


def test_typing_into_a_secret_replaces_it(page, db, job):
    open_job(page)
    edit(page)

    variables(page).nth(0).locator(".variable-value").fill("n3w-t0ken")
    submit(page)

    assert page.locator("#save-notice").inner_text() == "Saved. Changed variable ApiToken."
    db.commit()
    assert db.query(Variable).filter(Variable.VarName == "ApiToken").one().VarValue == "n3w-t0ken"
    assert variables(page).nth(0).locator(".variable-value").input_value() == ""    # and it is hidden again


def test_ticking_secret_hides_what_is_typed(page, job):
    open_job(page)
    edit(page)
    value = variables(page).nth(1).locator(".variable-value")           # Folder
    assert value.get_attribute("type") == "text"

    variables(page).nth(1).locator(".variable-secret").check()

    assert value.get_attribute("type") == "password"


def test_a_variable_name_that_cannot_be_used_is_refused_and_stays_open(page_expecting_refusals, job):
    page = page_expecting_refusals
    open_job(page)
    edit(page)
    page.locator("#add-variable").click()
    variables(page).nth(2).locator(".variable-name").fill("has space")

    submit(page)

    assert "Invalid variable name 'has space'" in page.locator("#page-error").inner_text()
    assert page.locator("#submit-button").is_enabled()
    assert [v["name"] for v in stored(page)["variables"]] == ["ApiToken", "Folder"]


# --- Preview --------------------------------------------------------------------------------------

def test_each_location_shows_where_it_really_is(page, job, outbox, tmp_path):
    steps = open_job(page)
    expand(steps.nth(0))
    wait_for_preview(page)

    work = tmp_path / "work" / "DEV-LOAD"
    assert field(steps.nth(0), "Source").locator(".preview.resolved").inner_text() == f"→ {outbox}/Legal_Batch_*.csv"
    assert field(steps.nth(0), "Dest").locator(".preview.resolved").inner_text() == f"→ {work}/staging/in"


def test_a_value_without_a_placeholder_shows_no_preview(page, job):
    steps = open_job(page)
    expand(steps.nth(0))
    wait_for_preview(page)

    assert not field(steps.nth(0), "RenameMask").locator(".preview.resolved").is_visible()
    assert steps.nth(0).locator(".preview.error-text:visible").count() == 0


def test_the_preview_follows_the_form_as_it_is_edited(page, job, tmp_path):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))
    dest = field(steps.nth(0), "Dest")
    work = tmp_path / "work" / "DEV-LOAD"

    dest.locator(".path-value").fill("${Folder}/arrivals_${DATE:yyyy}")
    wait_for_preview(page)
    assert dest.locator(".preview.resolved").inner_text().startswith(f"→ {work}/staging/arrivals_20")

    variables(page).nth(1).locator(".variable-value").fill("holding")       # change the variable it uses
    wait_for_preview(page)
    assert dest.locator(".preview.resolved").inner_text().startswith(f"→ {work}/holding/arrivals_20")

    field(steps.nth(0), "RenameMask").locator("input[type=text]").fill("${FILE:STEM}_${Folder}${FILE:EXT}")
    wait_for_preview(page)
    assert field(steps.nth(0), "RenameMask").locator(".preview.resolved").inner_text() == "→ ${FILE:STEM}_holding${FILE:EXT}"
    # nothing has been saved by any of this
    assert stored(page)["steps"][0]["parameters"]["Dest"] == "${Folder}/in"


def test_a_value_that_cannot_be_resolved_says_why_under_the_field(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))
    mask = field(steps.nth(0), "RenameMask")

    mask.locator("input[type=text]").fill("${FILE:STEM}_${DATE:YYYYMMDD}")
    wait_for_preview(page)

    assert "'Y' in the date mask 'YYYYMMDD' is not understood" in mask.locator(".preview.error-text").inner_text()
    assert not mask.locator(".preview.resolved").is_visible()


def test_would_it_run_follows_the_form_before_it_is_saved(page, job):
    steps = open_job(page)
    assert page.locator("#runnability").inner_text() == "Ready to run"
    edit(page)
    expand(steps.nth(0))

    field(steps.nth(0), "Dest").locator(".path-value").fill("/etc/outside")
    wait_for_preview(page)

    assert "1 problem found by the pre-run check" in page.locator("#runnability").inner_text()
    assert page.locator("#unsaved-note").inner_text() == "(as it is on screen, not yet saved)"
    assert "outside the job's working folder" in page.locator("#job-problems li").inner_text()

    field(steps.nth(0), "Dest").locator(".path-value").fill("incoming")
    wait_for_preview(page)
    assert page.locator("#runnability").inner_text().startswith("Ready to run")


def test_a_secret_is_masked_in_the_preview(page, job, tmp_path):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))

    field(steps.nth(0), "Dest").locator(".path-value").fill("in_${ApiToken}")
    wait_for_preview(page)

    shown = field(steps.nth(0), "Dest").locator(".preview.resolved").inner_text()
    assert shown == f"→ {tmp_path}/work/DEV-LOAD/in_********"
    assert "s3cr3t-t0ken" not in page.content()


# --- A variable that does not exist yet -----------------------------------------------------------

def test_a_placeholder_naming_no_variable_offers_to_add_it(page, job, tmp_path):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))
    dest = field(steps.nth(0), "Dest")

    dest.locator(".path-value").fill("${ArchiveFolder}/${Folder}")
    wait_for_preview(page)

    offers = dest.locator(".add-missing")
    assert [offer.inner_text() for offer in offers.all()] == ["Add variable ArchiveFolder"]     # Folder exists
    assert "${ArchiveFolder}" in dest.locator(".preview.error-text").inner_text()

    offers.first.click()

    new = variables(page).nth(2)
    assert new.locator(".variable-name").input_value() == "ArchiveFolder"
    assert page.evaluate("document.activeElement.classList.contains('variable-value')")     # ready for its value
    new.locator(".variable-value").fill("archive")
    wait_for_preview(page)
    assert dest.locator(".add-missing").count() == 0
    assert dest.locator(".preview.resolved").inner_text() == f"→ {tmp_path}/work/DEV-LOAD/archive/staging"

    submit(page)
    assert page.locator("#runnability").inner_text() == "Ready to run"
    assert {v["name"] for v in stored(page)["variables"]} == {"ApiToken", "ArchiveFolder", "Folder"}


def test_built_in_placeholders_are_not_offered_as_variables_to_add(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))

    field(steps.nth(0), "RenameMask").locator("input[type=text]").fill("${FILE:STEM}_${DATE:yyyyMMdd}_${SYS:INSTANCE_ID}")
    wait_for_preview(page)

    assert field(steps.nth(0), "RenameMask").locator(".add-missing").count() == 0


def test_nothing_is_offered_while_the_page_is_locked(page, db, seed, endpoints):
    job = seed.job("DEV-GAP")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="${NoSuchVariable}/in")
    db.commit()

    steps = open_job(page, "DEV-GAP")
    expand(steps.nth(0))
    wait_for_preview(page)

    assert field(steps.nth(0), "Dest").locator(".add-missing").count() == 0
    assert "${NoSuchVariable}" in field(steps.nth(0), "Dest").locator(".preview.error-text").inner_text()


def test_a_new_job_is_previewed_before_it_is_saved_or_named(page, db, endpoints, tmp_path):
    db.commit()
    page.goto("/ui/job.html?new")
    page.wait_for_selector("#job-key")
    page.locator("#add-step").click()
    step = page.locator(".step").nth(0)
    step.locator(".step-body").wait_for(state="visible")

    field(step, "Dest").locator('input[type=radio][value="path"]').check()
    field(step, "Dest").locator(".path-value").fill("incoming")
    wait_for_preview(page)
    assert field(step, "Dest").locator(".preview.resolved").inner_text() == f"→ {tmp_path}/work/UNNAMED-JOB/incoming"

    page.locator("#job-key").fill("DEV-NEW")
    wait_for_preview(page)
    assert field(step, "Dest").locator(".preview.resolved").inner_text() == f"→ {tmp_path}/work/DEV-NEW/incoming"
    assert page.request.get("/api/v1/jobs/DEV-NEW").status == 404

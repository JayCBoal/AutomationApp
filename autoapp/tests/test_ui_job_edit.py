"""
Changing a job on the Job Detail page: unlock, edit, add, remove and reorder
steps, save, rename, create and delete. In a real browser, against a real
server; the browser fixtures are in conftest.py.
"""
import json

import pytest

from app.models import Audit, Job


@pytest.fixture
def job(db, seed, endpoints):
    job = seed.job("DEV-LOAD")
    job.Description = "Collects and delivers"
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Archive", Source="incoming/*.csv", Dest="archive")
    seed.step(job, 3, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    db.commit()


def open_job(page, key="DEV-LOAD", extra=""):
    page.goto(f"/ui/job.html?key={key}{extra}")
    page.wait_for_selector("#job-key")
    page.wait_for_load_state("networkidle")
    return page.locator(".step")


def edit(page):
    page.locator("#edit-button").click()
    page.locator("#cancel-button").wait_for(state="visible")


def submit(page):
    """Presses Save and waits until the server has answered and the page has shown the result."""
    with page.expect_response(lambda r: "/api/v1/jobs" in r.url and r.request.method in ("POST", "PUT")):
        page.locator("#submit-button").click()
    page.wait_for_function("() => Alpine.$data(document.querySelector('main')).busy === false")


def expand(step):
    step.locator(".expander").click()
    step.locator(".step-body").wait_for(state="visible")


def field(step, name):
    return step.locator(f'.field-row[data-parameter="{name}"]')


def stored(page, key="DEV-LOAD"):
    """The job as the API now has it."""
    response = page.request.get(f"/api/v1/jobs/{key}")
    assert response.ok, response.text()
    return response.json()


def titles(job):
    return [step["title"] for step in job["steps"]]


# --- Locking, unlocking and Save ----------------------------------------------------------------

def test_edit_unlocks_and_submit_waits_for_a_change(page, job):
    open_job(page)
    assert page.locator("#job-description").is_disabled()

    edit(page)

    assert page.locator("#job-description").is_enabled() and page.locator("#job-key").is_enabled()
    assert page.locator("#submit-button").is_disabled()           # nothing has changed yet
    assert page.locator("#job-selector").is_disabled()            # no wandering off mid-edit
    assert not page.locator("#edit-button").is_visible()

    page.locator("#job-description").fill("Collects and delivers, daily")
    assert page.locator("#submit-button").is_enabled()

    page.locator("#job-description").fill("Collects and delivers")           # typed back to what it was
    assert page.locator("#submit-button").is_disabled()


def test_a_change_is_saved_and_the_page_locks_again(page, db, job):
    steps = open_job(page)
    edit(page)
    page.locator("#job-description").fill("Collects, archives and delivers")
    expand(steps.nth(1))
    field(steps.nth(1), "Checksum").locator("input[type=checkbox]").check()

    submit(page)

    notice = page.locator("#save-notice").inner_text()
    assert notice == "Saved. Changed the description. Changed step 2 ('Archive'): parameters."
    assert page.locator("#job-description").is_disabled() and page.locator("#edit-button").is_visible()
    saved = stored(page)
    assert saved["description"] == "Collects, archives and delivers"
    assert saved["steps"][1]["parameters"] == {"Source": "incoming/*.csv", "Dest": "archive", "Checksum": "True"}
    assert saved["steps"][0]["parameters"] == {"SourceEndpoint": "LEGAL_EXTRACTS", "Dest": "incoming"}    # untouched
    # and it is in the audit log
    db.commit()
    audit = db.query(Audit).one()
    assert (audit.Action, audit.PerformedBy) == ("JOB_UPDATED", "web interface")
    assert json.loads(audit.Details)["changes"] == ["Changed the description.", "Changed step 2 ('Archive'): parameters."]


def test_what_was_saved_is_what_a_fresh_load_shows(page, job):
    steps = open_job(page)
    edit(page)
    steps.nth(0).locator(".step-title-input").fill("Collect extracts")
    submit(page)

    steps = open_job(page)

    assert steps.nth(0).locator(".step-title").inner_text() == "Collect extracts"


def test_cancel_puts_everything_back(page, job):
    steps = open_job(page)
    edit(page)
    page.locator("#job-description").fill("Something else")
    steps.nth(0).locator(".step-title-input").fill("Renamed")
    page.once("dialog", lambda dialog: dialog.accept())           # "Discard the changes you have made?"

    page.locator("#cancel-button").click()

    page.locator("#edit-button").wait_for(state="visible")
    assert page.locator("#job-description").input_value() == "Collects and delivers"
    assert steps.nth(0).locator(".step-title").inner_text() == "Collect"
    assert stored(page)["description"] == "Collects and delivers"


def test_declining_to_discard_keeps_the_changes_on_screen(page, job):
    open_job(page)
    edit(page)
    page.locator("#job-description").fill("Something else")
    page.once("dialog", lambda dialog: dialog.dismiss())

    page.locator("#cancel-button").click()

    assert page.locator("#job-description").input_value() == "Something else"
    assert page.locator("#submit-button").is_enabled()


def test_cancel_without_changes_asks_nothing(page, job):
    open_job(page)
    edit(page)
    questions = []
    page.on("dialog", lambda dialog: (questions.append(dialog.message), dialog.accept()))

    page.locator("#cancel-button").click()

    page.locator("#edit-button").wait_for(state="visible")
    assert questions == []


# --- Parameters ---------------------------------------------------------------------------------

def test_a_location_is_switched_from_a_path_to_an_endpoint(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(1))
    dest = field(steps.nth(1), "Dest")
    assert dest.locator(".endpoint-value").is_disabled() and dest.locator(".path-value").is_enabled()

    dest.locator('input[type=radio][value="endpoint"]').check()
    assert dest.locator(".endpoint-value").is_enabled() and dest.locator(".path-value").is_disabled()
    dest.locator(".endpoint-value").fill("BILLING_INBOX")
    submit(page)

    assert stored(page)["steps"][1]["parameters"] == {"Source": "incoming/*.csv", "DestEndpoint": "BILLING_INBOX"}


def test_an_endpoint_box_offers_the_registered_endpoints(page, job):
    """
    The drop-down is the browser's own: it lists these options under the box and narrows them as you type.
    A test cannot see the browser's list on screen, so this checks what the list is given.
    """
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))

    box = field(steps.nth(0), "Source").locator(".endpoint-value")
    offered = page.locator("#endpoint-names option")

    assert box.get_attribute("list") == "endpoint-names"
    assert field(steps.nth(0), "Dest").locator(".endpoint-value").get_attribute("list") == "endpoint-names"
    assert [option.get_attribute("value") for option in offered.all()] == ["BILLING_INBOX", "LEGAL_EXTRACTS"]
    label = offered.nth(1).get_attribute("label")           # whose it is and where it points
    assert label.startswith("LEGAL_APP") and label.endswith("app_outbox/Legal_Batch_*.csv")
    assert field(steps.nth(0), "Source").locator(".path-value").get_attribute("list") is None    # not on path boxes


def test_a_name_that_is_not_a_registered_endpoint_is_pointed_out_as_it_is_typed(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))
    source = field(steps.nth(0), "Source")
    warning = source.locator(".not-registered")
    assert not warning.is_visible()                         # LEGAL_EXTRACTS is registered

    source.locator(".endpoint-value").fill("LEGAL_EXTRACT")
    warning.wait_for(state="visible")
    assert warning.inner_text() == "No endpoint is registered under this name. Register it"

    source.locator(".endpoint-value").fill("BILLING_INBOX")
    warning.wait_for(state="hidden")

    source.locator(".endpoint-value").fill("")              # an empty box is merely unfinished
    assert not warning.is_visible()


# --- Registering an endpoint without leaving the page ------------------------------------------

def test_a_new_endpoint_is_registered_from_the_step_and_put_in_its_box(page, db, job, tmp_path, run_runner):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(1))                                    # Archive: its Dest is a working-folder path
    dest = field(steps.nth(1), "Dest")

    dest.locator(".new-endpoint").click()

    window = page.locator("dialog.endpoint")
    window.wait_for(state="visible")
    assert page.locator("#endpoint-filename_pattern").input_value() == "*"            # every file, unless told otherwise
    page.locator("#endpoint-name").fill("LEGAL_ARCHIVE")
    page.locator("#endpoint-application").fill("LEGAL_APP")
    page.locator("#endpoint-path").fill(str(tmp_path / "legal_archive"))
    page.locator("#endpoint-description").fill("Where extracts are kept")
    create(page, "endpoint")

    assert not window.is_visible()
    assert dest.locator(".endpoint-value").input_value() == "LEGAL_ARCHIVE"
    assert dest.locator('input[type=radio][value="endpoint"]').is_checked()   # switched over from the path
    assert not dest.locator(".not-registered").is_visible()
    assert "LEGAL_ARCHIVE" in [o.get_attribute("value") for o in page.locator("#endpoint-names option").all()]
    # the endpoint exists already, before the job is saved
    registered = {e["name"]: e for e in page.request.get("/api/v1/endpoints").json()}
    assert registered["LEGAL_ARCHIVE"]["application"] == "LEGAL_APP"
    assert registered["LEGAL_ARCHIVE"]["description"] == "Where extracts are kept"
    assert "DestEndpoint" not in stored(page)["steps"][1]["parameters"]

    submit(page)

    assert stored(page)["steps"][1]["parameters"] == {"Source": "incoming/*.csv", "DestEndpoint": "LEGAL_ARCHIVE"}
    assert page.locator("#runnability").inner_text() == "Ready to run"
    assert run_runner("DEV-LOAD").returncode == 0
    assert sorted(p.name for p in (tmp_path / "legal_archive").iterdir()) == ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]


def test_a_name_typed_into_the_box_is_carried_into_the_new_endpoint_form(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))
    source = field(steps.nth(0), "Source")
    source.locator(".endpoint-value").fill("LEGAL_EXTRACTS_V2")
    source.locator(".not-registered").wait_for(state="visible")

    source.locator(".register-it").click()

    page.locator("dialog.endpoint").wait_for(state="visible")
    assert page.locator("#endpoint-name").input_value() == "LEGAL_EXTRACTS_V2"


def test_a_registered_name_in_the_box_is_not_offered_as_the_new_name(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))

    field(steps.nth(0), "Source").locator(".new-endpoint").click()         # the box holds LEGAL_EXTRACTS

    page.locator("dialog.endpoint").wait_for(state="visible")
    assert page.locator("#endpoint-name").input_value() == ""


def test_a_refused_endpoint_says_why_and_stays_open_for_correction(page_expecting_refusals, db, job):
    page = page_expecting_refusals
    steps = open_job(page)
    edit(page)
    expand(steps.nth(1))
    dest = field(steps.nth(1), "Dest")
    dest.locator(".new-endpoint").click()
    window = page.locator("dialog.endpoint")
    window.wait_for(state="visible")

    page.locator("#endpoint-name").fill("BILLING_INBOX")                   # already registered
    page.locator("#endpoint-path").fill("/somewhere")
    create(page, "endpoint")

    assert window.is_visible()
    assert page.locator("#endpoint-error").inner_text() == "An endpoint named 'BILLING_INBOX' is already registered."
    assert dest.locator(".endpoint-value").input_value() == ""             # the step is untouched

    page.locator("#endpoint-name").fill("BILLING_ARCHIVE")
    page.locator("#endpoint-application").fill("NO_SUCH_APP")
    create(page, "endpoint")
    assert page.locator("#endpoint-error").inner_text() == "There is no application named 'NO_SUCH_APP'."

    page.locator("#endpoint-application").fill("BILLING_APP")
    create(page, "endpoint")
    assert not window.is_visible()
    assert dest.locator(".endpoint-value").input_value() == "BILLING_ARCHIVE"


def test_cancelling_the_new_endpoint_form_registers_nothing_and_leaves_the_step_alone(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(1))
    dest = field(steps.nth(1), "Dest")
    dest.locator(".new-endpoint").click()
    window = page.locator("dialog.endpoint")
    window.wait_for(state="visible")
    page.locator("#endpoint-name").fill("NEVER_CREATED")
    page.locator("#endpoint-path").fill("/somewhere")

    window.get_by_role("button", name="Cancel").click()

    assert not window.is_visible()
    assert dest.locator(".path-value").input_value() == "archive" and dest.locator(".endpoint-value").input_value() == ""
    assert [e["name"] for e in page.request.get("/api/v1/endpoints").json()] == ["BILLING_INBOX", "LEGAL_EXTRACTS"]
    assert page.locator("#submit-button").is_disabled()                    # nothing about the job has changed


def open_new_endpoint(page, steps, step=1, parameter="Dest"):
    edit(page)
    expand(steps.nth(step))
    box = field(steps.nth(step), parameter)
    box.locator(".new-endpoint").click()
    page.locator("dialog.endpoint").wait_for(state="visible")
    return box


def create(page, kind):
    """Presses Create in a New ... window and waits for the server's answer."""
    with page.expect_response(lambda r: r.request.method == "POST" and "/api/v1/" in r.url):
        page.locator(f"#create-{kind}").click()
    page.wait_for_timeout(150)


def test_the_new_endpoint_form_offers_the_applications_and_sites_there_are(page, job):
    steps = open_job(page)
    open_new_endpoint(page, steps)

    assert page.locator("#endpoint-application").get_attribute("list") == "lookup-applications"
    assert page.locator("#endpoint-site").get_attribute("list") == "lookup-sites"
    assert [o.get_attribute("value") for o in page.locator("#lookup-applications option").all()] == [
        "BILLING_APP", "LEGAL_APP"]


def test_a_site_and_its_entity_are_registered_from_inside_the_new_endpoint_form(page, db, job):
    """Three windows deep: the endpoint needs a site that does not exist, and the site an entity that does not."""
    steps = open_job(page)
    dest = open_new_endpoint(page, steps)
    page.locator("#endpoint-name").fill("ACME_PAYMENTS")
    page.locator("#endpoint-path").fill("/inbound/payments")

    page.locator("dialog.endpoint .create-new[data-creates=site]").click()
    page.locator("dialog.site").wait_for(state="visible")
    assert (page.locator("#site-port").input_value(), page.locator("#site-protocol").input_value()) == ("22", "SFTP")
    page.locator("#site-name").fill("ACME_SFTP")
    page.locator("#site-host").fill("sftp.acmebank.example")

    page.locator("dialog.site .create-new[data-creates=entity]").click()
    page.locator("dialog.entity").wait_for(state="visible")
    page.locator("#entity-name").fill("ACME_BANK")
    page.locator("#entity-abbr").fill("ACME")
    create(page, "entity")

    # back in the site window, with the new entity filled in
    assert not page.locator("dialog.entity").is_visible() and page.locator("dialog.site").is_visible()
    assert page.locator("#site-entity").input_value() == "ACME_BANK"
    create(page, "site")

    # back in the endpoint window, with the new site filled in and what was typed before still there
    assert not page.locator("dialog.site").is_visible() and page.locator("dialog.endpoint").is_visible()
    assert page.locator("#endpoint-site").input_value() == "ACME_SFTP"
    assert page.locator("#endpoint-name").input_value() == "ACME_PAYMENTS"
    create(page, "endpoint")

    assert not page.locator("dialog.endpoint").is_visible()
    assert dest.locator(".endpoint-value").input_value() == "ACME_PAYMENTS"
    registered = {e["name"]: e for e in page.request.get("/api/v1/endpoints").json()}
    assert (registered["ACME_PAYMENTS"]["site"], registered["ACME_PAYMENTS"]["entity"]) == ("ACME_SFTP", "ACME_BANK")
    # and each is now offered wherever its kind is asked for
    offered = lambda kind: [o.get_attribute("value") for o in page.locator(f"#lookup-{kind} option").all()]
    assert "ACME_SFTP" in offered("sites") and "ACME_BANK" in offered("entities")


def test_an_application_is_registered_from_inside_the_new_endpoint_form(page, db, job):
    steps = open_job(page)
    open_new_endpoint(page, steps)
    page.locator("#endpoint-application").fill("PAYMENTS_APP")          # typed first, then found not to exist

    page.locator("dialog.endpoint .create-new[data-creates=application]").click()

    page.locator("dialog.application").wait_for(state="visible")
    assert page.locator("#application-name").input_value() == "PAYMENTS_APP"      # carried into the new window
    page.locator("#application-abbr").fill("PAY")
    create(page, "application")
    assert page.locator("#endpoint-application").input_value() == "PAYMENTS_APP"
    assert "PAYMENTS_APP" in [o.get_attribute("value") for o in page.locator("#lookup-applications option").all()]


def test_cancelling_an_inner_window_returns_to_the_outer_one_unchanged(page, job):
    steps = open_job(page)
    open_new_endpoint(page, steps)
    page.locator("#endpoint-name").fill("KEPT")
    page.locator("dialog.endpoint .create-new[data-creates=site]").click()
    page.locator("dialog.site").wait_for(state="visible")
    page.locator("#site-name").fill("NEVER_CREATED")

    page.locator("dialog.site").get_by_role("button", name="Cancel").click()

    page.locator("dialog.site").wait_for(state="detached")
    assert page.locator("dialog.endpoint").is_visible()
    assert (page.locator("#endpoint-name").input_value(), page.locator("#endpoint-site").input_value()) == ("KEPT", "")


def test_a_refused_inner_window_says_why(page_expecting_refusals, db, job):
    page = page_expecting_refusals
    steps = open_job(page)
    open_new_endpoint(page, steps)
    page.locator("dialog.endpoint .create-new[data-creates=application]").click()
    page.locator("dialog.application").wait_for(state="visible")

    page.locator("#application-name").fill("LEGAL_APP")                 # already registered
    page.locator("#application-abbr").fill("LGL")
    create(page, "application")

    assert page.locator("dialog.application").is_visible()
    assert page.locator("#application-error").inner_text() == "An application named 'LEGAL_APP' is already registered."


def test_new_endpoint_links_are_only_there_while_editing(page, job):
    steps = open_job(page)
    expand(steps.nth(0))
    assert not field(steps.nth(0), "Source").locator(".new-endpoint").is_visible()

    edit(page)

    assert field(steps.nth(0), "Source").locator(".new-endpoint").is_visible()


def test_a_tick_box_put_back_to_default_is_no_longer_stored(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(2))
    move = field(steps.nth(2), "Move")
    assert move.locator("input[type=checkbox]").is_checked() and not move.get_by_text("default").is_visible()

    move.locator(".reset-field").click()

    move.get_by_text("default").wait_for(state="visible")
    assert not move.locator("input[type=checkbox]").is_checked()
    submit(page)
    assert stored(page)["steps"][2]["parameters"] == {"Source": "incoming/*.csv", "DestEndpoint": "BILLING_INBOX"}


def test_unticking_a_box_that_defaults_to_ticked_stores_false(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))

    field(steps.nth(0), "CreateFolder").locator("input[type=checkbox]").uncheck()
    submit(page)

    assert stored(page)["steps"][0]["parameters"]["CreateFolder"] == "False"


def test_a_rename_mask_is_typed_into_the_step_and_saved_as_written(page, job):
    """A new parameter on the step type appears in the editor without any change to the page."""
    steps = open_job(page)
    edit(page)
    expand(steps.nth(2))
    mask = field(steps.nth(2), "RenameMask")
    assert "${FILE:STEM}" in mask.locator(".field-help").inner_text()           # the field explains its placeholders

    mask.locator("input[type=text]").fill("${FILE:STEM}_${DATE:yyyyMMdd}${FILE:EXT}")
    submit(page)

    assert stored(page)["steps"][2]["parameters"]["RenameMask"] == "${FILE:STEM}_${DATE:yyyyMMdd}${FILE:EXT}"
    assert page.locator("#runnability").inner_text() == "Ready to run"


def test_a_mistake_in_a_rename_mask_shows_as_a_problem_after_saving(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(2))

    field(steps.nth(2), "RenameMask").locator("input[type=text]").fill("${FILE:STEM}_${DATE:YYYYMMDD}")
    submit(page)

    assert page.locator("#runnability").inner_text() == "1 problem found by the pre-run check"
    problem = page.locator("#job-problems li").inner_text()
    assert problem.startswith("Step 3 ('Deliver'): 'Y' in the date mask 'YYYYMMDD' is not understood")


def test_a_choice_is_set_from_its_list(page, job):
    steps = open_job(page)
    edit(page)
    expand(steps.nth(0))

    field(steps.nth(0), "LogLevel").locator("select").select_option("SILENT")
    submit(page)

    assert stored(page)["steps"][0]["parameters"]["LogLevel"] == "SILENT"


def test_a_parameter_the_step_type_does_not_have_can_be_removed(page, db, seed, endpoints):
    job = seed.job("DEV-TYPO")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming", Mvoe="True")
    db.commit()
    steps = open_job(page, "DEV-TYPO")
    assert "1 problem found" in page.locator("#runnability").inner_text()
    edit(page)
    expand(steps.nth(0))

    steps.nth(0).locator(".remove-unknown").click()
    submit(page)

    assert stored(page, "DEV-TYPO")["steps"][0]["parameters"] == {"SourceEndpoint": "LEGAL_EXTRACTS", "Dest": "incoming"}
    assert page.locator("#runnability").inner_text() == "Ready to run"


# --- Steps --------------------------------------------------------------------------------------

def test_a_step_is_added_at_the_end_open_and_ready_to_fill_in(page, job):
    steps = open_job(page)
    edit(page)

    page.locator("#add-step").click()

    new = steps.nth(3)
    new.locator(".step-body").wait_for(state="visible")
    new.locator(".step-title-input").fill("Keep a copy")
    field(new, "Source").locator('input[type=radio][value="path"]').check()
    field(new, "Source").locator(".path-value").fill("archive/*.csv")
    field(new, "Dest").locator('input[type=radio][value="path"]').check()
    field(new, "Dest").locator(".path-value").fill("kept")
    field(new, "AllowNoFiles").locator("input[type=checkbox]").check()
    submit(page)

    assert page.locator("#save-notice").inner_text() == "Saved. Added step 4 ('Keep a copy')."
    saved = stored(page)
    assert titles(saved) == ["Collect", "Archive", "Deliver", "Keep a copy"]
    assert saved["steps"][3]["parameters"] == {"Source": "archive/*.csv", "Dest": "kept", "AllowNoFiles": "True"}
    assert saved["steps"][3]["step_type"] == "COPY_FILES"


def test_the_step_type_list_shows_each_types_name(page, job):
    steps = open_job(page)
    edit(page)

    chooser = steps.nth(0).locator("select.step-type")

    # The parts of an If (Then, Else If, Else) are never offered on their own
    assert [option.inner_text() for option in chooser.locator("option").all()] == [
        "Check Files", "Copy Files", "Delete Files", "For Each File", "If", "Run SQL", "Simulate", "Unzip Files", "While",
        "Zip Files"]
    assert chooser.evaluate("e => e.options[e.selectedIndex].text") == "Copy Files"
    assert chooser.input_value() == "COPY_FILES"


def test_a_sql_statement_gets_a_box_of_several_lines(page, job):
    steps = open_job(page)
    edit(page)

    expand(steps.nth(0))
    steps.nth(0).locator("select.step-type").select_option("RUN_SQL")

    statement = steps.nth(0).locator('.field-row[data-parameter="Statement"] textarea')
    statement.fill("SELECT invoice_no\nFROM invoices\nWHERE status = 'OPEN'")
    assert statement.get_attribute("rows") == "4"


def test_a_step_is_removed_after_confirming(page, job):
    steps = open_job(page)
    edit(page)
    questions = []
    page.once("dialog", lambda dialog: (questions.append(dialog.message), dialog.accept()))

    steps.nth(1).locator(".remove-step").click()

    assert questions == ["Remove step 2 ('Archive')?"]
    assert steps.count() == 2
    submit(page)
    assert page.locator("#save-notice").inner_text() == "Saved. Removed step 'Archive'."
    assert titles(stored(page)) == ["Collect", "Deliver"]


def test_declining_to_remove_a_step_keeps_it(page, job):
    steps = open_job(page)
    edit(page)
    page.once("dialog", lambda dialog: dialog.dismiss())

    steps.nth(1).locator(".remove-step").click()

    assert steps.count() == 3
    assert page.locator("#submit-button").is_disabled()


def test_steps_are_reordered_with_the_arrows(page, job):
    steps = open_job(page)
    edit(page)
    assert steps.nth(0).locator(".move-up").is_disabled() and steps.nth(2).locator(".move-down").is_disabled()

    steps.nth(2).locator(".move-up").click()            # Deliver above Archive
    steps.nth(0).locator(".move-down").click()          # Collect below Deliver

    assert [s.locator(".step-title-input").input_value() for s in steps.all()] == ["Deliver", "Collect", "Archive"]
    assert [s.locator(".step-order").inner_text() for s in steps.all()] == ["1", "2", "3"]
    submit(page)
    assert page.locator("#save-notice").inner_text() == "Saved. Reordered the steps."
    saved = stored(page)
    assert [(s["order"], s["title"]) for s in saved["steps"]] == [(1, "Deliver"), (2, "Collect"), (3, "Archive")]


def test_a_step_is_disabled_with_its_tick_box(page, job):
    steps = open_job(page)
    edit(page)

    steps.nth(1).locator(".step-enabled").uncheck()
    submit(page)

    assert page.locator("#save-notice").inner_text() == "Saved. Changed step 2 ('Archive'): disabled."
    assert [s["active"] for s in stored(page)["steps"]] == [True, False, True]
    assert "disabled" in steps.nth(1).get_attribute("class")


def test_the_whole_job_is_disabled_with_its_tick_box(page, job):
    open_job(page)
    edit(page)

    page.locator("#job-enabled").uncheck()
    submit(page)

    assert stored(page)["active"] is False
    assert "Disabled. The runner refuses a disabled job." in page.locator("#runnability").inner_text()


# --- What saving reports ------------------------------------------------------------------------

def test_a_job_saved_with_a_mistake_in_it_is_saved_and_the_problem_is_shown(page, job):
    steps = open_job(page)
    assert page.locator("#runnability").inner_text() == "Ready to run"
    edit(page)
    expand(steps.nth(0))
    field(steps.nth(0), "Source").locator(".endpoint-value").fill("NO_SUCH_ENDPOINT")

    submit(page)

    assert page.locator("#save-notice").inner_text().startswith("Saved.")
    assert page.locator("#runnability").inner_text() == "1 problem found by the pre-run check"
    assert "NO_SUCH_ENDPOINT" in page.locator("#job-problems li").inner_text()
    assert stored(page)["steps"][0]["parameters"]["SourceEndpoint"] == "NO_SUCH_ENDPOINT"


def test_a_job_built_in_the_editor_runs(page, db, endpoints, run_runner, tmp_path):
    """The whole point: define a job on the page, and the runner runs it."""
    db.commit()
    page.goto("/ui/job.html?new")
    page.wait_for_selector("#job-key")
    steps = page.locator(".step")
    assert page.locator("#submit-button").is_disabled() and page.locator("#no-steps").is_visible()

    page.locator("#job-key").fill("DEV-BUILT-BY-HAND")
    page.locator("#job-description").fill("Made in the job editor")
    page.locator("#add-step").click()
    collect = steps.nth(0)
    collect.locator(".step-title-input").fill("Collect")
    field(collect, "Source").locator('input[type=radio][value="endpoint"]').check()
    field(collect, "Source").locator(".endpoint-value").fill("LEGAL_EXTRACTS")
    field(collect, "Dest").locator('input[type=radio][value="path"]').check()
    field(collect, "Dest").locator(".path-value").fill("incoming")
    page.locator("#add-step").click()
    deliver = steps.nth(1)
    deliver.locator(".step-title-input").fill("Deliver")
    field(deliver, "Source").locator('input[type=radio][value="path"]').check()
    field(deliver, "Source").locator(".path-value").fill("incoming/*.csv")
    field(deliver, "Dest").locator('input[type=radio][value="endpoint"]').check()
    field(deliver, "Dest").locator(".endpoint-value").fill("BILLING_INBOX")
    field(deliver, "Move").locator("input[type=checkbox]").check()
    submit(page)

    assert page.locator("#save-notice").inner_text() == "Saved. Created job 'DEV-BUILT-BY-HAND'."
    assert page.url.endswith("job.html?key=DEV-BUILT-BY-HAND")
    assert page.locator("#runnability").inner_text() == "Ready to run"
    assert "--job-key DEV-BUILT-BY-HAND" in page.locator("#command-line").inner_text()

    result = run_runner("DEV-BUILT-BY-HAND")

    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in (tmp_path / "app_inbox").iterdir()) == ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]
    assert list((tmp_path / "work" / "DEV-BUILT-BY-HAND" / "incoming").iterdir()) == []      # moved on


def test_a_new_job_with_an_unusable_key_is_refused_and_stays_open_for_correction(page_expecting_refusals, db, job):
    page = page_expecting_refusals
    page.goto("/ui/job.html?new")
    page.wait_for_selector("#job-key")

    page.locator("#job-key").fill("has a space")
    submit(page)

    assert "Invalid JobKey 'has a space'" in page.locator("#page-error").inner_text()
    assert page.locator("#job-key").is_enabled() and page.locator("#submit-button").is_enabled()

    page.locator("#job-key").fill("DEV-LOAD")                       # already taken
    submit(page)
    assert page.locator("#page-error").inner_text() == "A job with JobKey 'DEV-LOAD' already exists."

    page.locator("#job-key").fill("DEV-NEW")
    submit(page)
    assert page.locator("#save-notice").inner_text() == "Saved. Created job 'DEV-NEW'."
    assert not page.locator("#page-error").is_visible()


def test_cancelling_a_new_job_goes_back_to_the_job_search(page, job):
    page.goto("/ui/job.html?new")
    page.wait_for_selector("#job-key")

    page.locator("#cancel-button").click()

    page.wait_for_url("**/ui/jobs.html")


# --- Renaming -----------------------------------------------------------------------------------

def test_renaming_warns_first_and_then_moves_the_job_to_its_new_key(page, db, job):
    open_job(page)
    edit(page)
    page.locator("#job-key").fill("DEV-LOAD-DAILY")
    questions = []
    page.once("dialog", lambda dialog: (questions.append(dialog.message), dialog.accept()))

    submit(page)

    assert "Rename this job from 'DEV-LOAD' to 'DEV-LOAD-DAILY'?" in questions[0]
    assert "scheduler" in questions[0] and "working folder" in questions[0]
    assert page.locator("#save-notice").inner_text() == "Saved. Renamed from 'DEV-LOAD' to 'DEV-LOAD-DAILY'."
    assert page.url.endswith("job.html?key=DEV-LOAD-DAILY")
    assert "--job-key DEV-LOAD-DAILY" in page.locator("#command-line").inner_text()
    assert titles(stored(page, "DEV-LOAD-DAILY")) == ["Collect", "Archive", "Deliver"]
    assert db.query(Job).filter(Job.JobKey == "DEV-LOAD").count() == 0


def test_declining_the_rename_warning_saves_nothing(page, job):
    open_job(page)
    edit(page)
    page.locator("#job-key").fill("DEV-LOAD-DAILY")
    page.once("dialog", lambda dialog: dialog.dismiss())

    page.locator("#submit-button").click()
    page.wait_for_timeout(300)

    assert stored(page)["job_key"] == "DEV-LOAD"
    assert page.locator("#job-key").input_value() == "DEV-LOAD-DAILY"          # still on screen, still unsaved


# --- Deleting -----------------------------------------------------------------------------------

def test_a_job_that_has_never_run_is_deleted_after_confirming(page, db, job):
    open_job(page)
    edit(page)
    questions = []
    page.once("dialog", lambda dialog: (questions.append(dialog.message), dialog.accept()))

    page.locator("#delete-button").click()

    page.wait_for_url("**/ui/jobs.html")
    assert questions == ["Delete job 'DEV-LOAD' and all its steps? This cannot be undone."]
    db.commit()
    assert db.query(Job).count() == 0


def test_a_job_that_has_run_cannot_be_deleted_and_says_to_disable_it(
        page_expecting_refusals, db, job, run_runner, load_spool):
    page = page_expecting_refusals
    run_runner("DEV-LOAD")
    load_spool()
    open_job(page)
    edit(page)
    page.once("dialog", lambda dialog: dialog.accept())

    page.locator("#delete-button").click()

    page.locator("#page-error").wait_for(state="visible")
    assert "has run 1 time, so it cannot be deleted. Disable it instead" in page.locator("#page-error").inner_text()
    assert stored(page)["job_key"] == "DEV-LOAD"


def test_declining_to_delete_keeps_the_job(page, job):
    open_job(page)
    edit(page)
    page.once("dialog", lambda dialog: dialog.dismiss())

    page.locator("#delete-button").click()
    page.wait_for_timeout(300)

    assert stored(page)["job_key"] == "DEV-LOAD"
    assert "job.html" in page.url

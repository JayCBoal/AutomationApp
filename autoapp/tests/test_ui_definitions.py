"""
The search and detail pages shared by applications, entities, sites and
endpoints, in a real browser against a real server. The browser fixtures are in conftest.py.
"""
import pytest

from app.models import Endpoint, Variable
from conftest import wait_for_search


@pytest.fixture
def world(db, seed, tmp_path):
    legal = seed.application("LEGAL_APP", Root=str(tmp_path))
    legal.Description = "Case management"
    billing = seed.application("BILLING_APP")
    bank = seed.entity("ACME_BANK")
    seed.entity("GLOBEX")
    sftp = seed.site("ACME_SFTP", bank, host="sftp.acme.example")
    seed.endpoint("LEGAL_EXTRACTS", "${APP.Root}/app_outbox", "Legal_Batch_*.csv", application=legal)
    seed.endpoint("BILLING_INBOX", tmp_path / "app_inbox", "*.csv", application=billing)
    seed.endpoint("ACME_PAYMENTS", "/inbound", "PAY_*.csv", application=billing, site=sftp)
    db.add(Variable(MasterObject_id=bank.MasterObject_id, VarName="Password", VarValue="s3cr3t", IsSecret=True))
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, Source="incoming/*.csv", DestEndpoint="BILLING_INBOX")
    db.commit()


def open_search(page, kind, extra=""):
    page.goto(f"/ui/search.html?kind={kind}{extra}")
    return wait_for_search(page)


def open_detail(page, kind, name, extra=""):
    page.goto(f"/ui/detail.html?kind={kind}&name={name}{extra}")
    page.wait_for_selector("#field-name")
    page.wait_for_load_state("networkidle")


def edit(page):
    page.locator("#edit-button").click()
    page.locator("#cancel-button").wait_for(state="visible")


def submit(page):
    with page.expect_response(lambda r: r.request.method == "PUT"):
        page.locator("#submit-button").click()
    page.wait_for_function("() => Alpine.$data(document.querySelector('main')).busy === false")


def stored(page, kind, name):
    return page.request.get(f"/api/v1/{kind}/{name}").json()


# --- Search pages ---------------------------------------------------------------------------------

@pytest.mark.parametrize("kind, title, names", [
    ("applications", "Application Search", ["BILLING_APP", "LEGAL_APP"]),
    ("entities", "Entity Search", ["ACME_BANK", "GLOBEX"]),
    ("sites", "Site Search", ["ACME_SFTP"]),
    ("endpoints", "Endpoint Search", ["ACME_PAYMENTS", "BILLING_INBOX", "LEGAL_EXTRACTS"]),
])
def test_each_kind_has_a_search_page_listing_them_in_name_order(page, world, kind, title, names):
    rows = open_search(page, kind)

    assert [row.locator(".item-name").inner_text() for row in rows.all()] == names
    assert page.locator(".page-title").inner_text() == title
    assert page.title() == f"{title} - RunMyFiles"


def test_a_search_row_shows_its_fields_and_what_uses_it(page, world):
    rows = open_search(page, "endpoints")

    payments = rows.filter(has_text="ACME_PAYMENTS")
    cell = lambda column, line: payments.locator(f'td[data-column="{column}"] .{line}').inner_text()
    assert (cell("Application", "main"), cell("Site", "main"), cell("Site", "sub")) == ("BILLING_APP", "ACME_SFTP", "ACME_BANK")
    assert (cell("Path", "main"), cell("Path", "sub")) == ("/inbound", "PAY_*.csv")
    assert [row.locator(".used-by").inner_text() for row in rows.all()] == ["0 jobs", "1 job", "1 job"]


def test_rows_are_two_lines_with_the_description_under_the_name_and_when_each_last_changed(page, db, world):
    from app.models import Application
    db.query(Application).filter(Application.Name == "LEGAL_APP").one().ModifiedBy = "jsmith"
    db.commit()

    rows = open_search(page, "applications")

    legal = rows.filter(has_text="LEGAL_APP")
    assert legal.locator('td[data-column="Application"] .item-name').inner_text() == "LEGAL_APP"
    assert legal.locator('td[data-column="Application"] .sub').inner_text() == "Case management"
    assert legal.locator('td[data-column="Status"] .main').inner_text() == "Active"
    changed = legal.locator(".last-changed")
    assert changed.locator("div").first.inner_text().startswith("20")          # a date
    assert changed.locator("div").nth(1).inner_text() == "by jsmith"
    assert [t.lower() for t in page.locator("thead th").all_inner_texts()[-3:-1]] == ["used by", "last changed"]


def test_criteria_narrow_a_search_and_are_kept_in_the_address(page, world):
    open_search(page, "endpoints")

    page.locator("input[name=application]").fill("billing")
    page.locator("input[name=site]").fill("sftp")
    page.get_by_role("button", name="Search").click()
    page.wait_for_timeout(50)
    rows = wait_for_search(page)

    assert [row.locator(".item-name").inner_text() for row in rows.all()] == ["ACME_PAYMENTS"]
    assert "application=billing" in page.url and "site=sftp" in page.url and "kind=endpoints" in page.url
    assert page.locator("input[name=application]").get_attribute("list") == "lookup-applications"


def test_active_is_searched_with_a_list(page, db, world):
    from app.models import Entity
    db.query(Entity).filter(Entity.Name == "GLOBEX").one().IsActive = False
    db.commit()

    rows = open_search(page, "entities", "&active=false")

    assert [row.locator(".item-name").inner_text() for row in rows.all()] == ["GLOBEX"]
    assert page.locator("select[name=active]").input_value() == "false"


def test_the_navigation_marks_the_kind_being_shown(page, world):
    open_search(page, "sites")
    nav = page.locator("nav.app-nav")

    assert "current" in nav.get_by_role("link", name="Sites").get_attribute("class")
    assert "current" not in (nav.get_by_role("link", name="Endpoints").get_attribute("class") or "")

    open_detail(page, "endpoints", "BILLING_INBOX")
    assert "current" in nav.get_by_role("link", name="Endpoints").get_attribute("class")


def test_new_from_a_search_page_opens_a_blank_detail_page(page, world):
    open_search(page, "entities")

    page.locator("#new-button").click()

    page.wait_for_url("**/ui/detail.html?kind=entities&new")
    page.wait_for_selector("#field-name")
    assert page.locator("#field-name").input_value() == "" and page.locator("#field-name").is_enabled()
    assert page.locator("#field-active").is_checked()                       # new ones start active
    assert page.locator(".page-title").inner_text() == "New entity"
    assert page.locator("#submit-button").is_disabled()                     # nothing typed yet
    assert not page.locator("#delete-button").is_visible()


def test_an_unknown_kind_says_so(page, world):
    page.goto("/ui/search.html?kind=widgets")

    page.get_by_text("There is no page for widgets.").wait_for()


# --- Detail pages ---------------------------------------------------------------------------------

def test_a_detail_page_shows_the_fields_and_arrives_locked(page, world):
    open_detail(page, "sites", "ACME_SFTP")

    value = lambda name: page.locator(f"#field-{name}").input_value()
    assert (value("name"), value("entity"), value("host"), value("port"), value("protocol")) == (
        "ACME_SFTP", "ACME_BANK", "sftp.acme.example", "22", "SFTP")
    assert page.locator("#field-active").is_checked()
    assert all(box.is_disabled() for box in page.locator("main section input").all())
    assert page.locator(".page-title").inner_text() == "Site: ACME_SFTP"


def test_used_by_links_to_what_uses_it(page, world):
    open_detail(page, "endpoints", "LEGAL_EXTRACTS")

    links = page.locator("#used-by a")
    assert [link.inner_text() for link in links.all()] == ["DEV-LOAD"]
    links.first.click()
    page.wait_for_url("**/ui/job.html?key=DEV-LOAD")


def test_an_endpoint_links_to_the_files_taken_from_it_and_delivered_to_it(page, world):
    open_detail(page, "endpoints", "BILLING_INBOX")

    assert page.locator("#files-from").get_attribute("href") == "operations.html?source_endpoint=BILLING_INBOX"
    assert page.locator("#files-to").get_attribute("href") == "operations.html?dest_endpoint=BILLING_INBOX"


def test_an_endpoints_entity_is_shown_but_set_through_its_site(page, world):
    open_detail(page, "endpoints", "ACME_PAYMENTS", "&edit")

    assert page.locator("#field-entity").input_value() == "ACME_BANK"
    assert page.locator("#field-entity").is_disabled() and page.locator("#field-site").is_enabled()


def test_fields_are_changed_and_saved(page, world):
    open_detail(page, "sites", "ACME_SFTP")
    edit(page)
    assert page.locator("#submit-button").is_disabled()

    page.locator("#field-host").fill("files.acme.example")
    page.locator("#field-port").fill("2222")
    page.locator("#field-active").uncheck()
    submit(page)

    assert page.locator("#save-notice").inner_text() == (
        "Saved. Changed the host. Changed the port. Deactivated the site.")
    saved = stored(page, "sites", "ACME_SFTP")
    assert (saved["host"], saved["port"], saved["active"]) == ("files.acme.example", 2222, False)
    assert page.locator("#field-host").is_disabled()


def test_renaming_an_endpoint_keeps_the_jobs_that_use_it_working(page, world, outbox, run_runner):
    open_detail(page, "endpoints", "LEGAL_EXTRACTS")
    edit(page)

    page.locator("#field-name").fill("LEGAL_EXTRACT_FILES")
    submit(page)

    assert "Updated 1 job step that named it." in page.locator("#save-notice").inner_text()
    assert page.url.endswith("name=LEGAL_EXTRACT_FILES")
    assert run_runner("DEV-LOAD").returncode == 0


def test_a_site_is_moved_to_an_entity_registered_on_the_spot(page, world):
    open_detail(page, "sites", "ACME_SFTP")
    edit(page)

    page.locator(".create-new[data-creates=entity]").click()
    page.locator("dialog.entity").wait_for(state="visible")
    page.locator("#entity-name").fill("ACME_GROUP")
    page.locator("#entity-abbr").fill("AG")
    page.locator("#create-entity").click()
    page.locator("dialog.entity").wait_for(state="detached")
    assert page.locator("#field-entity").input_value() == "ACME_GROUP"
    submit(page)

    assert stored(page, "sites", "ACME_SFTP")["entity"] == "ACME_GROUP"


def test_a_refused_change_says_why_and_stays_open(page_expecting_refusals, world):
    page = page_expecting_refusals
    open_detail(page, "endpoints", "BILLING_INBOX")
    edit(page)

    page.locator("#field-name").fill("LEGAL_EXTRACTS")
    submit(page)

    assert page.locator("#page-error").inner_text() == "An endpoint named 'LEGAL_EXTRACTS' is already registered."
    assert page.locator("#submit-button").is_enabled()


def test_variables_are_edited_and_a_secret_is_never_shown(page, db, world, tmp_path):
    open_detail(page, "entities", "ACME_BANK")
    rows = page.locator("table.variables tbody tr")
    assert rows.count() == 1 and rows.first.locator(".variable-value").input_value() == ""
    assert "s3cr3t" not in page.content()
    edit(page)

    page.locator("#add-variable").click()
    rows.nth(1).locator(".variable-name").fill("Contact")
    rows.nth(1).locator(".variable-value").fill("ops@acme.example")
    submit(page)

    assert page.locator("#save-notice").inner_text() == "Saved. Added variable Contact."
    db.commit()
    assert db.query(Variable).filter(Variable.VarName == "Password").one().VarValue == "s3cr3t"     # kept


def test_an_application_root_changed_here_moves_where_its_endpoint_points(page, world, run_runner, tmp_path):
    moved = tmp_path / "moved"
    (moved / "app_outbox").mkdir(parents=True)
    (moved / "app_outbox" / "Legal_Batch_7.csv").write_text("id\n7")
    open_detail(page, "applications", "LEGAL_APP")
    edit(page)

    page.locator("table.variables tbody tr").first.locator(".variable-value").fill(str(moved))
    submit(page)

    assert run_runner("DEV-LOAD").returncode == 0
    assert [p.name for p in (tmp_path / "app_inbox").iterdir()] == ["Legal_Batch_7.csv"]


def test_an_endpoint_has_no_variables_panel(page, world):
    open_detail(page, "endpoints", "BILLING_INBOX")

    assert page.locator("table.variables").count() == 0


def test_something_nothing_uses_is_deleted_after_confirming(page, db, world):
    open_detail(page, "entities", "GLOBEX")
    assert page.locator("#used-by-none").is_visible()
    edit(page)
    page.once("dialog", lambda dialog: dialog.accept())

    page.locator("#delete-button").click()

    page.wait_for_url("**/ui/search.html?kind=entities")
    assert page.request.get("/api/v1/entities/GLOBEX").status == 404


def test_something_in_use_is_not_deleted_and_says_what_uses_it(page_expecting_refusals, world):
    page = page_expecting_refusals
    open_detail(page, "applications", "BILLING_APP")
    edit(page)
    page.once("dialog", lambda dialog: dialog.accept())

    page.locator("#delete-button").click()

    page.locator("#page-error").wait_for(state="visible")
    assert page.locator("#page-error").inner_text().startswith(
        "Application 'BILLING_APP' cannot be deleted while 2 endpoints use it: ACME_PAYMENTS, BILLING_INBOX.")


def test_the_selector_opens_another_of_the_same_kind(page, world):
    open_detail(page, "applications", "LEGAL_APP")

    page.locator("#item-selector").fill("BILLING_APP")
    page.locator("#item-selector").dispatch_event("change")

    page.wait_for_url("**/ui/detail.html?kind=applications&name=BILLING_APP")


def test_text_from_the_database_is_shown_as_text_not_run_as_html(page, db, seed):
    markup = '<img src=x onerror="window.hacked=true">'
    seed.endpoint("ODD", f"/x{markup}", f"*{markup}")
    db.query(Endpoint).filter(Endpoint.Name == "ODD").one().Description = markup
    db.commit()

    rows = open_search(page, "endpoints")
    assert markup in rows.first.inner_text()
    open_detail(page, "endpoints", "ODD")

    assert page.locator("main img").count() == 0
    assert page.evaluate("window.hacked") is None
    assert page.locator("#field-path").input_value() == f"/x{markup}"


# --- Creating from the detail page ----------------------------------------------------------------

def submit_new(page):
    with page.expect_response(lambda r: r.request.method == "POST"):
        page.locator("#submit-button").click()
    page.wait_for_function("() => Alpine.$data(document.querySelector('main')).busy === false")


def test_a_new_application_is_created_with_its_variables_and_as_inactive_in_one_go(page, db, world):
    page.goto("/ui/detail.html?kind=applications&new")
    page.wait_for_selector("#field-name")

    page.locator("#field-name").fill("PAYMENTS_APP")
    page.locator("#field-abbr").fill("PAY")
    page.locator("#field-description").fill("Sends payments")
    page.locator("#field-active").uncheck()
    page.locator("#add-variable").click()
    row = page.locator("table.variables tbody tr").first
    row.locator(".variable-name").fill("Root")
    row.locator(".variable-value").fill("/data/payments")
    submit_new(page)

    assert page.locator("#save-notice").inner_text() == "Saved. Created application 'PAYMENTS_APP'."
    assert page.url.endswith("detail.html?kind=applications&name=PAYMENTS_APP")
    assert page.locator("#field-name").is_disabled()                        # locked again, now it exists
    created = stored(page, "applications", "PAYMENTS_APP")
    assert (created["abbr"], created["description"], created["active"]) == ("PAY", "Sends payments", False)
    assert created["variables"] == [{"name": "Root", "value": "/data/payments", "secret": False, "description": None}]
    assert page.locator("#used-by-none").is_visible()


def test_a_new_site_starts_with_the_usual_port_and_protocol(page, world):
    page.goto("/ui/detail.html?kind=sites&new")
    page.wait_for_selector("#field-name")

    assert (page.locator("#field-port").input_value(), page.locator("#field-protocol").input_value()) == ("22", "SFTP")
    page.locator("#field-name").fill("GLOBEX_SFTP")
    page.locator("#field-entity").fill("GLOBEX")
    page.locator("#field-host").fill("sftp.globex.example")
    submit_new(page)

    created = stored(page, "sites", "GLOBEX_SFTP")
    assert (created["entity"], created["port"], created["protocol"]) == ("GLOBEX", 22, "SFTP")


def test_a_new_endpoint_can_register_its_application_on_the_spot(page, world):
    page.goto("/ui/detail.html?kind=endpoints&new")
    page.wait_for_selector("#field-name")
    assert page.locator("#field-filename_pattern").input_value() == "*"

    page.locator("#field-name").fill("PAYMENTS_OUT")
    page.locator(".create-new[data-creates=application]").click()
    page.locator("dialog.application").wait_for(state="visible")
    page.locator("#application-name").fill("PAYMENTS_APP")
    page.locator("#application-abbr").fill("PAY")
    page.locator("#create-application").click()
    page.locator("dialog.application").wait_for(state="detached")
    page.locator("#field-path").fill("/data/payments/out")
    submit_new(page)

    created = stored(page, "endpoints", "PAYMENTS_OUT")
    assert (created["application"], created["path"], created["filename_pattern"]) == ("PAYMENTS_APP", "/data/payments/out", "*")


def test_cancelling_a_new_one_goes_back_to_the_search_page(page, world):
    page.goto("/ui/detail.html?kind=entities&new")
    page.wait_for_selector("#field-name")

    page.locator("#cancel-button").click()

    page.wait_for_url("**/ui/search.html?kind=entities")


def test_a_new_one_that_cannot_be_created_says_why_and_stays_open(page_expecting_refusals, world):
    page = page_expecting_refusals
    page.goto("/ui/detail.html?kind=entities&new")
    page.wait_for_selector("#field-name")

    page.locator("#field-name").fill("ACME_BANK")                            # already registered
    page.locator("#field-abbr").fill("AB")
    submit_new(page)

    assert page.locator("#page-error").inner_text() == "An entity named 'ACME_BANK' is already registered."
    assert page.locator("#field-name").is_enabled() and page.url.endswith("&new")


def test_new_on_a_detail_page_opens_a_blank_one_of_the_same_kind(page, world):
    open_detail(page, "sites", "ACME_SFTP")

    page.locator("#new-button").click()

    page.wait_for_url("**/ui/detail.html?kind=sites&new")

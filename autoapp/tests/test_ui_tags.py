"""
Tags in the web interface, in a real browser against a real server: the tag
search and detail pages, the Tags panel on the other detail pages and in the job
editor (showing what a tag would give before it is added), the Tag box on the
search pages, and the Settings page. The browser fixtures are in conftest.py.
"""
import pytest

from app.models import Tag, Variable
from conftest import wait_for_search


@pytest.fixture
def world(db, seed):
    """
        Finance        Ledger = GL01, Region = EU, Token (secret)
          Reporting    Region = US
        Ops            Region = APAC

    LEGAL_APP carries Finance/Reporting; DEV-REPORT carries it too, and uses ${Ledger}.
    """
    finance = seed.tag("Finance", Ledger="GL01", Region="EU")
    db.add(Variable(MasterObject_id=finance.MasterObject_id, VarName="Token", VarValue="s3cr3t", IsSecret=True))
    reporting = seed.tag("Reporting", parent=finance, Region="US")
    seed.tag("Ops", Region="APAC")
    legal = seed.application("LEGAL_APP")
    seed.application("BILLING_APP")
    job = seed.job("DEV-REPORT")
    seed.step(job, 1, Source="in/*.csv", Dest="out/${Ledger}")
    seed.job("DEV-OTHER")
    seed.attach(reporting, legal, job)
    db.commit()


def open_detail(page, kind, name):
    page.goto(f"/ui/detail.html?kind={kind}&name={name}")
    page.wait_for_selector("#field-name")
    page.wait_for_load_state("networkidle")


def edit(page):
    page.locator("#edit-button").click()
    page.locator("#cancel-button").wait_for(state="visible")


def submit(page, method="PUT"):
    with page.expect_response(lambda r: r.request.method == method and "/api/v1/" in r.url):
        page.locator("#submit-button").click()
    page.wait_for_function("() => Alpine.$data(document.querySelector('main')).busy === false")


def consider(page, path):
    with page.expect_response(lambda r: "/tag-variables" in r.url):
        page.locator("#tag-candidate").fill(path)
    page.locator("#tag-preview").wait_for(state="visible")


def chips(page):
    return [chip.inner_text().replace("×", "").strip() for chip in page.locator("#tag-list .tag-chip").all()]


# --- Tag pages ------------------------------------------------------------------------------------

def test_tags_are_listed_each_under_its_parent(page, world):
    page.goto("/ui/search.html?kind=tags")
    wait_for_search(page)

    assert [a.inner_text() for a in page.locator("a.item-name").all()] == ["Finance", "Finance / Reporting", "Ops"]


def test_a_tag_page_shows_what_it_inherits_and_hides_secrets(page, world):
    open_detail(page, "tags", "Finance/Reporting")

    assert page.locator("#field-parent").input_value() == "Finance"
    inherited = page.locator("#inherited-variables tbody tr")
    assert [row.locator("td").nth(0).inner_text() for row in inherited.all()] == ["Ledger", "Token"]
    assert inherited.nth(1).locator("td").nth(1).inner_text() == "********"
    assert "s3cr3t" not in page.content()
    assert page.locator("#used-by").inner_text().count("(") == 2          # LEGAL_APP and DEV-REPORT


def test_a_new_tag_is_made_under_a_parent(page, world):
    page.goto("/ui/detail.html?kind=tags&new")
    page.wait_for_selector("#field-name")
    page.locator("#field-name").fill("Audit")
    page.locator("#field-parent").fill("Finance/Reporting")

    submit(page, "POST")

    assert page.locator("#save-notice").inner_text() == "Saved. Created tag 'Finance / Reporting / Audit'."
    assert page.request.get("/api/v1/tags/Finance/Reporting/Audit").ok


# --- The Tags panel -------------------------------------------------------------------------------

def test_a_detail_page_shows_its_tags_and_what_they_give(page, world):
    open_detail(page, "applications", "LEGAL_APP")

    assert chips(page) == ["Finance / Reporting"]
    page.locator("#tags-give").wait_for(state="visible")
    rows = {r.locator("td").nth(0).inner_text(): r.locator("td").nth(2).inner_text()
            for r in page.locator("#tags-give tbody tr").all()}
    assert rows == {"Ledger": "Finance", "Region": "Finance / Reporting", "Token": "Finance"}
    assert page.locator("section[aria-label='Variables'] #tags-give").count() == 1    # listed with its variables
    assert page.locator("section[aria-label='Tags'] #tags-give").count() == 0


def test_the_job_editor_lists_what_its_tags_give_under_variables(page, world):
    page.goto("/ui/job.html?key=DEV-REPORT")
    page.locator("section[aria-label='Variables'] #tags-give").wait_for(state="visible")

    assert page.locator("#tags-give h3").inner_text() == "From its tags"
    assert page.locator("section[aria-label='Tags'] #tags-give").count() == 0


def test_an_endpoint_lists_what_its_tags_give_under_variables(page, world, seed, db, tmp_path):
    seed.attach(db.query(Tag).filter(Tag.Name == "Ops").one(), seed.endpoint("LEDGER_DROP", tmp_path))
    db.commit()
    open_detail(page, "endpoints", "LEDGER_DROP")

    page.locator("section[aria-label='Variables'] #tags-give").wait_for(state="visible")
    assert page.locator("#tags-give tbody tr td").first.inner_text() == "Region"


def test_a_tags_variables_are_shown_before_it_is_added(page, world):
    open_detail(page, "applications", "BILLING_APP")
    edit(page)

    consider(page, "Finance/Reporting")

    preview = page.locator("#tag-preview")
    assert "Finance / Reporting would give:" in preview.inner_text()
    values = {r.locator("td").nth(0).inner_text(): r.locator("td").nth(1).inner_text()
              for r in preview.locator("tbody tr").all()}
    assert values == {"Ledger": "GL01", "Region": "US", "Token": "********"}
    assert chips(page) == []                                       # considered, not added


def test_a_conflict_is_pointed_out_before_the_tag_is_added(page, world):
    open_detail(page, "applications", "LEGAL_APP")
    edit(page)

    consider(page, "Ops")

    page.locator("#tag-preview .tag-conflict").wait_for(state="visible")
    assert "Variable 'Region' is given different values by tags" in page.locator("#tag-preview .tag-conflict").inner_text()


def test_tags_are_added_and_removed_and_saved(page, world):
    open_detail(page, "applications", "LEGAL_APP")
    edit(page)
    consider(page, "Ops")
    page.locator("#add-tag").click()
    page.locator("#tag-list .tag-chip").nth(0).locator(".remove-tag").click()      # Finance / Reporting

    submit(page)

    assert page.locator("#save-notice").inner_text() == "Saved. Added tag Ops. Removed tag Finance / Reporting."
    assert page.request.get("/api/v1/applications/LEGAL_APP").json()["tags"] == ["Ops"]


def test_the_add_button_waits_for_a_tag_that_exists(page, world):
    open_detail(page, "applications", "BILLING_APP")
    edit(page)

    page.locator("#tag-candidate").fill("Nope")
    assert page.locator("#add-tag").is_disabled()
    page.locator("#tag-candidate").fill("Ops")
    assert page.locator("#add-tag").is_enabled()


def test_the_job_editor_has_the_tags_panel_and_warns_of_conflicts_it_does_not_use(page, world):
    page.goto("/ui/job.html?key=DEV-REPORT")
    page.wait_for_load_state("networkidle")
    assert chips(page) == ["Finance / Reporting"]
    page.locator("#edit-button").click()

    consider(page, "Ops")
    page.locator("#add-tag").click()

    page.locator("#job-warnings li").wait_for(state="visible")
    assert "Variable 'Region'" in page.locator("#job-warnings").inner_text()
    assert page.locator("#job-problems").is_hidden()          # DEV-REPORT uses Ledger, not Region


def test_a_variable_a_tag_gives_is_not_offered_as_missing(page, world):
    page.goto("/ui/job.html?key=DEV-REPORT")
    page.wait_for_load_state("networkidle")
    page.locator("#tags-give").wait_for(state="visible")
    page.locator("#edit-button").click()

    assert page.locator("text=Add variable Ledger").count() == 0


# --- Searching by tag -----------------------------------------------------------------------------

def test_every_search_page_has_a_tag_box(page, world):
    page.goto("/ui/search.html?kind=applications&tag=Finance")
    wait_for_search(page)
    assert [a.inner_text() for a in page.locator("a.item-name").all()] == ["LEGAL_APP"]

    page.goto("/ui/jobs.html?tag=Finance")
    wait_for_search(page)
    assert [a.inner_text() for a in page.locator("a.job-key").all()] == ["DEV-REPORT"]
    assert page.locator(".job-tags").first.inner_text() == "Finance / Reporting"


# --- Settings -------------------------------------------------------------------------------------

def test_the_variable_precedence_is_put_in_order_and_saved(page, world):
    page.goto("/ui/settings.html")
    setting = page.locator('[data-setting="VariablePrecedence"]')
    setting.wait_for()
    assert setting.locator(".save-setting").is_disabled()
    # shown highest priority first
    assert [li.get_attribute("data-choice") for li in setting.locator("li").all()] == [
        "JOB", "TAG", "ENDPOINT", "APP", "ENTITY", "SYS", "ENV"]

    setting.locator('[data-choice="TAG"] .move-up').click()          # the job's tags over its own variables
    with page.expect_response(lambda r: r.request.method == "PUT"):
        setting.locator(".save-setting").click()

    page.locator("#save-notice").wait_for(state="visible")
    assert "to ENV,SYS,ENTITY,APP,ENDPOINT,JOB,TAG." in page.locator("#save-notice").inner_text()
    assert page.request.get("/api/v1/settings").json()[0]["value"][-2:] == ["JOB", "TAG"]
    assert [li.get_attribute("data-choice") for li in setting.locator("li").all()][:2] == ["TAG", "JOB"]

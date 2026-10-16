"""
How the pages hold together while they scroll, in a real browser: the page header
stays put on every page, a detail page's own header (the object's name and its
buttons) stays just under it, and the Operations Log's criteria scroll away and can
be folded. The browser fixtures are in conftest.py.
"""
import pytest

from conftest import wait_for_search


@pytest.fixture
def long_job(seed, db):
    """A job with enough steps to need scrolling in a short window."""
    job = seed.job("DEV-LONG")
    for order in range(1, 9):
        seed.step(job, order, Source=f"in/{order}/*.csv", Dest=f"out/{order}")
    db.commit()


def top_of(page, selector):
    return page.locator(selector).first.bounding_box()["y"]


def scroll_to_bottom(page):
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(100)


def test_the_page_header_and_the_jobs_own_header_stay_put(page, long_job):
    page.set_viewport_size({"width": 1400, "height": 500})
    page.goto("/ui/job.html?key=DEV-LONG")
    page.locator("#job-key").wait_for()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Expand all").click()
    scroll_to_bottom(page)

    assert page.evaluate("window.scrollY") > 300                           # the page did scroll
    assert top_of(page, "#app-chrome") == 0
    chrome_height = page.locator("#app-chrome").bounding_box()["height"]
    assert top_of(page, ".selector") == pytest.approx(chrome_height, abs=1)
    page.locator("#edit-button").click()                                   # still in reach
    page.locator("#submit-button").wait_for(state="visible")


def test_a_detail_pages_own_header_stays_put(page, seed, db):
    for number in range(30):
        seed.application(f"APP_{number:02}")
    db.commit()
    page.set_viewport_size({"width": 1400, "height": 400})
    page.goto("/ui/detail.html?kind=applications&name=APP_00")
    page.locator("#field-name").wait_for()
    page.wait_for_load_state("networkidle")
    scroll_to_bottom(page)

    if page.evaluate("window.scrollY") > 0:
        chrome_height = page.locator("#app-chrome").bounding_box()["height"]
        assert top_of(page, ".selector") == pytest.approx(chrome_height, abs=1)
    assert page.locator("#edit-button").is_visible()


def test_the_operations_logs_criteria_scroll_away_but_the_header_stays(page, seed, db):
    page.set_viewport_size({"width": 1400, "height": 420})
    page.goto("/ui/operations.html")
    wait_for_search(page)
    page.evaluate("document.querySelector('main').style.paddingBottom = '2000px'")   # room to scroll
    scroll_to_bottom(page)

    assert top_of(page, "#app-chrome") == 0
    assert top_of(page, "form[aria-label='Search criteria']") < 0


def test_the_operations_logs_criteria_fold_away_and_stay_folded(page, db):
    page.goto("/ui/operations.html?source_filename=Open_Invoices&job_key=DEV-BILLING")
    wait_for_search(page)
    assert page.locator(".criteria").is_visible()

    page.locator("#fold-criteria").click()
    assert page.locator(".criteria").is_hidden()
    assert page.locator("#criteria-summary").inner_text() == "Source filename: Open_Invoices · Job: DEV-BILLING"
    page.get_by_role("button", name="Search").wait_for(state="visible")      # searching still works folded

    page.reload()
    wait_for_search(page)
    assert page.locator(".criteria").is_hidden()                           # this viewer's choice is kept
    page.locator("#fold-criteria").click()
    assert page.locator(".criteria").is_visible()


def test_the_operations_log_opened_from_a_scheduler_starts_folded(page, db):
    page.goto("/ui/operations.html?job_key=DEV-BILLING&instance_id=SIS-3&embed=1")
    wait_for_search(page)

    assert page.locator(".criteria").is_hidden()
    assert page.locator("#criteria-summary").inner_text() == "Job: DEV-BILLING · Instance ID: SIS-3"

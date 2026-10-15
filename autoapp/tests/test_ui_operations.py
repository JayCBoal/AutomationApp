"""
The Operations Log page, in a real browser.

Each test starts a real API server, runs real jobs, opens the page in headless
Chromium and reads what is on screen. The browser fixtures are in conftest.py.
"""
import csv

import pytest

from app.telemetry_ingest import ingest_records
from conftest import wait_for_search

FILE_1 = "Legal_Batch_1.csv"


@pytest.fixture
def collect_and_deliver(seed, endpoints):
    """Collect from LEGAL_EXTRACTS, copy to an archive folder, move to BILLING_INBOX: two files, six operations."""
    job = seed.job("DEV-COLLECT")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Archive", Source="incoming/*.csv", Dest="archive")
    seed.step(job, 3, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    return job


def open_log(page, address="/ui/operations.html"):
    page.goto(address)
    return wait_for_search(page)


def search(page):
    page.get_by_role("button", name="Search").click()
    page.wait_for_function("!document.querySelector('#result-summary').textContent.includes('Searching')")
    page.wait_for_timeout(100)
    return page.locator("table.results tbody tr")


def spooled_operation(seq, filename, ended="2026-10-12T14:00:00Z", **fields):
    return {"Record": "OPERATION", "RunID": "run-made-by-hand", "Seq": seq, "OpType": "COPY", "Status": "SUCCESS",
            "SourcePath": "/in", "SourceFilename": filename, "DestPath": "/out", "DestFilename": filename,
            "EndedAtUtc": ended, **fields}


def ingest_by_hand(db, operations):
    """For cases the runner cannot produce on demand: a chosen time, an odd filename, hundreds of rows."""
    start = {"Record": "RUN_START", "RunID": "run-made-by-hand", "Seq": 1, "JobKey": "DEV-BY-HAND",
             "InstanceID": "70001", "StartedAtUtc": "2026-10-12T13:59:00Z"}
    ingest_records(db, [start] + operations)
    db.commit()


# --- What the page shows -----------------------------------------------------------------------

def test_page_lists_every_operation_newest_first(page, collect_and_deliver, run_runner, load_spool):
    run_runner("DEV-COLLECT", "88421")
    load_spool()

    rows = open_log(page)

    assert rows.count() == 6
    assert "6 operations, newest first" in page.locator("#result-summary").inner_text()
    assert "America/New_York" in page.locator("#result-summary").inner_text()
    newest, oldest = rows.nth(0), rows.nth(5)
    assert "MOVE" in newest.inner_text() and "step 3" in newest.inner_text()
    assert "COPY" in oldest.inner_text() and "step 1" in oldest.inner_text()


def test_a_row_shows_both_sides_of_the_operation(page, collect_and_deliver, run_runner, load_spool, outbox, tmp_path):
    run_runner("DEV-COLLECT", "88421")
    load_spool()

    rows = open_log(page, "/ui/operations.html?source_endpoint=LEGAL&source_filename=Batch_1")

    assert rows.count() == 1
    source, dest = rows.locator("td.location").nth(0), rows.locator("td.location").nth(1)
    assert source.locator(".place").inner_text() == "LEGAL_EXTRACTS"
    assert source.locator(".owners").inner_text() == "LEGAL_APP"
    assert source.locator(".file").inner_text() == f"{FILE_1} (4 bytes)"
    assert source.locator(".path").inner_text() == str(outbox)
    assert dest.locator(".place").inner_text() == "Working folder"       # no endpoint on this side
    assert dest.locator(".path").inner_text() == str(tmp_path / "work" / "DEV-COLLECT" / "incoming")
    assert "DEV-COLLECT" in rows.inner_text() and "instance 88421" in rows.inner_text()
    assert rows.locator(".status").inner_text() == "SUCCESS"


def test_a_failed_operation_shows_its_error(page, seed, endpoints, run_runner, load_spool):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="missing", CreateFolder="False")
    run_runner("DEV-LOAD", "88421")
    load_spool()

    rows = open_log(page)

    assert rows.count() == 1
    assert rows.locator(".status").inner_text() == "FAILED"
    assert "No such file or directory" in rows.locator(".error-text").inner_text()


def test_times_are_shown_in_the_viewers_time_zone(page, db):
    """The browser in these tests is set to New York, four hours behind UTC in October."""
    ingest_by_hand(db, [spooled_operation(2, "a.csv", ended="2026-10-12T14:00:00Z")])

    rows = open_log(page)

    assert "2026-10-12 10:00:00" in rows.nth(0).inner_text()


def test_text_from_the_database_is_shown_as_text_not_run_as_html(page, db):
    """A filename is whatever someone named a file. It must never be treated as page markup."""
    ingest_by_hand(db, [spooled_operation(2, '<img src=x onerror="window.hacked=true">.csv')])

    rows = open_log(page)

    assert '<img src=x onerror="window.hacked=true">.csv' in rows.nth(0).inner_text()
    assert page.locator("table.results img").count() == 0
    assert page.evaluate("window.hacked") is None


def test_no_field_from_the_database_is_treated_as_html_in_the_table_or_the_trace(page, db):
    markup = '<img src=x onerror="window.hacked=true">'
    short = "<img src=x>"                                # for the fields that only hold a few characters
    ingest_records(db, [
        {"Record": "RUN_START", "RunID": "run-made-by-hand", "Seq": 1, "JobKey": f"JOB{markup}",
         "InstanceID": f"I{markup}", "Scheduler": markup, "StartedAtUtc": "2026-10-12T13:59:00Z"},
        spooled_operation(2, f"file{markup}.csv", OpType=f"T{markup}", Status=f"S{short}",
                          SourcePath=f"/in{markup}", DestPath=f"/out{markup}", Error=f"E{markup}",
                          Details={f"K{markup}": f"V{markup}"}),
    ])
    db.commit()

    rows = open_log(page)
    rows.get_by_role("button", name="Trace").click()
    page.wait_for_selector("dialog.trace .hop")

    assert page.locator("main img").count() == 0
    assert page.evaluate("window.hacked") is None
    assert markup in rows.nth(0).inner_text() and markup in page.locator("dialog.trace").inner_text()
    assert f"S{short}" in rows.nth(0).inner_text()


def test_when_there_are_more_results_than_the_page_can_show_it_says_so(page, db):
    ingest_by_hand(db, [spooled_operation(seq, f"file_{seq}.csv") for seq in range(2, 503)])    # 501 operations

    rows = open_log(page)

    assert rows.count() == 500
    assert page.locator(".message.capped").is_visible()
    assert "Only the newest 500 are shown" in page.locator(".message.capped").inner_text()


def test_the_too_many_results_note_is_hidden_otherwise(page, collect_and_deliver, run_runner, load_spool):
    run_runner("DEV-COLLECT", "88421")
    load_spool()

    open_log(page)

    assert not page.locator(".message.capped").is_visible()


def test_an_empty_log_says_so(page, db):
    open_log(page)

    assert page.locator("#result-summary").inner_text() == "No operations match these criteria."
    assert not page.locator("table.results").is_visible()
    assert page.get_by_role("button", name="Export as CSV").is_disabled()


# --- Searching ---------------------------------------------------------------------------------

def test_criteria_narrow_the_results_and_clear_restores_them(page, collect_and_deliver, run_runner, load_spool):
    run_runner("DEV-COLLECT", "88421")
    load_spool()
    open_log(page)

    page.locator("input[name=dest_endpoint]").fill("billing")       # any case, part of the name
    assert search(page).count() == 2

    page.locator("input[name=dest_filename]").fill("batch_1")       # criteria combine
    assert search(page).count() == 1

    page.locator("select[name=op_type]").select_option("COPY")
    assert search(page).count() == 0
    assert page.locator("#result-summary").inner_text() == "No operations match these criteria."

    page.get_by_role("button", name="Clear").click()
    page.wait_for_function("document.querySelectorAll('table.results tbody tr').length === 6")
    assert page.locator("input[name=dest_endpoint]").input_value() == ""


def test_application_entity_and_site_are_searched_on_each_side_separately(page, collect_and_deliver, run_runner, load_spool):
    """Two files: collected from LEGAL_APP's endpoint, archived, delivered to BILLING_APP's endpoint."""
    run_runner("DEV-COLLECT", "88421")
    load_spool()
    open_log(page)
    boxes = lambda group: [box.get_attribute("name") for box in
                           page.locator("fieldset", has=page.locator("legend", has_text=group)).locator("input").all()]
    assert boxes("Source") == ["source_endpoint", "source_application", "source_entity", "source_site",
                               "source_path", "source_filename"]
    assert boxes("Destination") == ["dest_endpoint", "dest_application", "dest_entity", "dest_site",
                                    "dest_path", "dest_filename"]

    page.locator("input[name=source_application]").fill("legal")
    assert search(page).count() == 2                                  # the two collects
    page.locator("input[name=source_application]").fill("billing")
    assert search(page).count() == 0                                  # billing is only ever a destination here
    page.locator("input[name=source_application]").fill("")
    page.locator("input[name=dest_application]").fill("billing")
    assert search(page).count() == 2                                  # the two deliveries
    assert "dest_application=billing" in page.url


def test_boxes_that_name_something_registered_offer_a_drop_down_of_what_there_is(
        page, collect_and_deliver, run_runner, load_spool):
    """
    The drop-down is the browser's own: it lists these options under the box and narrows them as you type.
    A test cannot see the browser's list on screen, so this checks which list each box is given.
    """
    run_runner("DEV-COLLECT", "88421", "--scheduler", "CTM_PROD")
    load_spool()
    open_log(page)
    page.wait_for_selector("#lookup-endpoints", state="attached")

    def offered(box_name):
        box = page.locator(f"input[name={box_name}]")
        return [o.get_attribute("value") for o in page.locator(f"datalist#{box.get_attribute('list')} option").all()]

    assert offered("source_endpoint") == offered("dest_endpoint") == ["BILLING_INBOX", "LEGAL_EXTRACTS"]
    assert offered("source_application") == offered("dest_application") == ["BILLING_APP", "LEGAL_APP"]
    assert offered("job_key") == ["DEV-COLLECT"]
    assert offered("scheduler") == ["CTM_PROD"]
    assert page.locator("input[name=source_entity]").get_attribute("list") == "lookup-entities"
    assert page.locator("input[name=dest_site]").get_attribute("list") == "lookup-sites"
    # free-text boxes have no list
    assert page.locator("input[name=source_path]").get_attribute("list") is None
    assert page.locator("input[name=dest_filename]").get_attribute("list") is None
    label = page.locator("datalist#lookup-endpoints option").nth(1).get_attribute("label")
    assert label.startswith("LEGAL_APP") and label.endswith("Legal_Batch_*.csv")


def test_scheduler_is_shown_and_can_be_searched(page, collect_and_deliver, run_runner, load_spool):
    run_runner("DEV-COLLECT", "88421", "--scheduler", "CTM_PROD")
    run_runner("DEV-COLLECT", "88422")                               # no scheduler name given
    load_spool()
    rows = open_log(page)
    assert rows.count() == 12
    assert rows.locator(".scheduler:visible").count() == 6           # shown where there is one, and only there
    assert rows.locator(".scheduler:visible").first.inner_text() == "scheduler CTM_PROD"

    page.locator("input[name=scheduler]").fill("ctm")
    rows = search(page)

    assert rows.count() == 6
    assert all("instance 88421" in row.inner_text() for row in rows.all())
    assert "scheduler=ctm" in page.url
    # and it is on each hop of a trace
    rows.first.get_by_role("button", name="Trace").click()
    page.wait_for_selector("dialog.trace .hop")
    assert "scheduler CTM_PROD" in page.locator("dialog.trace .hop").first.inner_text()


def test_pressing_enter_in_a_box_runs_the_search(page, collect_and_deliver, run_runner, load_spool):
    run_runner("DEV-COLLECT", "88421")
    load_spool()
    open_log(page)

    page.locator("input[name=source_path]").fill("incoming")
    page.locator("input[name=source_path]").press("Enter")

    page.wait_for_function("document.querySelectorAll('table.results tbody tr').length === 4")


def test_a_search_can_be_bookmarked(page, collect_and_deliver, run_runner, load_spool):
    """The criteria go into the page address, and an address with criteria in it runs that search."""
    run_runner("DEV-COLLECT", "88421")
    load_spool()
    open_log(page)
    page.locator("input[name=source_endpoint]").fill("legal")
    page.locator("select[name=status]").select_option("SUCCESS")
    search(page)
    address = page.url

    assert "source_endpoint=legal" in address and "status=SUCCESS" in address
    rows = open_log(page, address)
    assert rows.count() == 2
    assert page.locator("input[name=source_endpoint]").input_value() == "legal"
    assert page.locator("select[name=status]").input_value() == "SUCCESS"


def test_date_criteria_are_in_the_viewers_time_zone(page, db):
    """An operation that ended at 14:00 UTC ended at 10:00 in New York."""
    ingest_by_hand(db, [spooled_operation(2, "a.csv", ended="2026-10-12T14:00:00Z")])
    open_log(page)

    page.locator("input[name=date_from]").fill("2026-10-12T10:00")
    page.locator("input[name=date_to]").fill("2026-10-12T10:00")
    assert search(page).count() == 1                    # both ends are inclusive

    page.locator("input[name=date_from]").fill("2026-10-12T10:01")
    page.locator("input[name=date_to]").fill("")
    assert search(page).count() == 0

    page.locator("input[name=date_from]").fill("")
    page.locator("input[name=date_to]").fill("2026-10-12T09:59")
    assert search(page).count() == 0


# --- Trace -------------------------------------------------------------------------------------

def test_trace_link_shows_the_files_whole_route(page, collect_and_deliver, seed, run_runner, load_spool):
    load = seed.job("DEV-BILLING-LOAD")
    seed.step(load, 1, SourceEndpoint="BILLING_INBOX", Dest="to_load", Move="True")
    run_runner("DEV-COLLECT", "88421")
    run_runner("DEV-BILLING-LOAD", "88430")
    load_spool()
    rows = open_log(page, "/ui/operations.html?dest_endpoint=BILLING_INBOX&dest_filename=Batch_1")

    rows.get_by_role("button", name="Trace").click()
    page.wait_for_selector("dialog.trace .hop")

    window = page.locator("dialog.trace")
    hops = window.locator(".hop")
    assert window.locator("h2").inner_text() == f"Trace: {FILE_1}"
    assert "4 operations handled this file" in window.inner_text()
    assert [hop.locator(".number").inner_text() for hop in hops.all()] == ["1.", "2.", "3.", "4."]
    # where the file entered, and where it ended up
    assert hops.nth(0).locator(".place").nth(0).inner_text() == "LEGAL_EXTRACTS"
    assert hops.nth(2).locator(".place").nth(1).inner_text() == "BILLING_INBOX"
    assert "DEV-BILLING-LOAD" in hops.nth(3).inner_text() and "instance 88430" in hops.nth(3).inner_text()
    # the archive copy and the delivery both follow the collect; the pick-up follows the delivery
    assert "follows 1" in hops.nth(1).inner_text() and "follows 1" in hops.nth(2).inner_text()
    assert "follows 3" in hops.nth(3).inner_text()
    # each hop is indented one step further than the hop it follows
    assert [hop.evaluate("e => e.style.marginLeft") for hop in hops.all()] == ["0px", "22px", "22px", "44px"]
    # the operation whose link was clicked is the outlined one
    assert [("selected" in (hop.get_attribute("class") or "")) for hop in hops.all()] == [False, False, True, False]


def test_trace_window_closes_and_can_be_bookmarked(page, collect_and_deliver, run_runner, load_spool):
    run_runner("DEV-COLLECT", "88421")
    load_spool()
    rows = open_log(page, "/ui/operations.html?dest_endpoint=BILLING_INBOX&dest_filename=Batch_1")
    rows.get_by_role("button", name="Trace").click()
    page.wait_for_selector("dialog.trace .hop")
    address_with_trace = page.url

    page.locator("dialog.trace").get_by_role("button", name="Close").click()

    assert not page.locator("dialog.trace").is_visible()
    assert "trace=" in address_with_trace
    page.wait_for_function("!location.search.includes('trace=')")      # closing takes the trace out of the address

    open_log(page, address_with_trace)                  # the address reopens the same trace
    page.wait_for_selector("dialog.trace .hop")
    assert page.locator("dialog.trace .hop").count() == 3


def test_a_failed_hop_is_marked_in_the_trace(page, seed, endpoints, run_runner, load_spool):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", CreateFolder="False")
    run_runner("DEV-LOAD", "88421")
    load_spool()
    rows = open_log(page, "/ui/operations.html?status=FAILED")

    rows.get_by_role("button", name="Trace").click()
    page.wait_for_selector("dialog.trace .hop")

    hops = page.locator("dialog.trace .hop")
    assert [hop.locator(".status").inner_text() for hop in hops.all()] == ["SUCCESS", "FAILED"]
    assert "No such file or directory" in hops.nth(1).locator(".error-text").inner_text()


# --- Export ------------------------------------------------------------------------------------

def test_export_as_csv_gives_the_rows_on_screen_with_every_field(page, collect_and_deliver, run_runner, load_spool, outbox):
    run_runner("DEV-COLLECT", "88421")
    load_spool()
    open_log(page, "/ui/operations.html?source_endpoint=legal")

    with page.expect_download() as download:
        page.get_by_role("button", name="Export as CSV").click()

    assert download.value.suggested_filename == "autoapp_operations.csv"
    with open(download.value.path(), newline="") as f:
        exported = list(csv.DictReader(f))
    assert len(exported) == 2                           # the search on screen, not the whole log
    row = exported[-1]
    assert (row["Source endpoint"], row["Source application"]) == ("LEGAL_EXTRACTS", "LEGAL_APP")
    assert (row["Source path"], row["Source filename"], row["Source size"]) == (str(outbox), FILE_1, "4")
    assert (row["Job"], row["Step"], row["Instance ID"], row["Run number"]) == ("DEV-COLLECT", "1", "88421", "1")
    assert (row["Type"], row["Status"], row["Error"]) == ("COPY", "SUCCESS", "")
    assert row["Run ID"] != "" and row["Ended (UTC)"].startswith("20")     # fields the table does not show


def test_exported_values_containing_commas_and_quotes_stay_in_their_column(page, db):
    ingest_by_hand(db, [spooled_operation(2, 'a "quoted", name.csv')])
    open_log(page)

    with page.expect_download() as download:
        page.get_by_role("button", name="Export as CSV").click()

    with open(download.value.path(), newline="") as f:
        [row] = list(csv.DictReader(f))
    assert row["Source filename"] == 'a "quoted", name.csv'
    assert row["Destination path"] == "/out"


# --- Around the page ---------------------------------------------------------------------------

def test_page_is_dark_by_default_and_remembers_a_switch_to_light(page, db):
    open_log(page)
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    dark_background = page.evaluate("getComputedStyle(document.body).backgroundColor")

    page.get_by_role("button", name="Light mode").click()

    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") != dark_background
    open_log(page)                                      # a fresh load of the page
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert page.get_by_role("button", name="Dark mode").is_visible()


def test_navigation_links_only_to_pages_that_exist(page, db):
    open_log(page)
    nav = page.locator("nav.app-nav")

    assert [link.inner_text() for link in nav.locator("a").all()] == [
        "Main Index", "Applications", "Entities", "Sites", "Jobs", "Endpoints", "Operations Log", "Job History", "Audit Log"]
    assert nav.locator("span.planned").count() == 0                  # every page is built
    assert "current" in nav.get_by_role("link", name="Operations Log").get_attribute("class")

    nav.get_by_role("link", name="Main Index").click()
    page.wait_for_selector(".index-card")
    assert [card.locator(".name").inner_text() for card in page.locator("a.index-card[href]").all()] == [
        "Applications", "Entities", "Sites", "Jobs", "Endpoints", "Operations Log", "Job History", "Audit Log"]
    page.locator("a.index-card[href]", has_text="Operations Log").click()
    page.wait_for_url("**/ui/operations.html")


def test_the_server_address_alone_opens_the_web_interface(page, db):
    page.goto("/")

    page.wait_for_selector(".index-card")
    assert page.url.endswith("/ui/")
    assert page.title() == "AutoApp"

"""
The pages a scheduler (a WLA) opens inside its own interface, and the messages
they send it. Each address here is one docs/INTEGRATION.md promises a WLA plug-in
it can rely on; if one of these tests has to change, so does that document.

Each test puts the page in an iframe on a stand-in host page, as a WLA would, and
records the messages it sends.
"""
import json

import pytest


@pytest.fixture
def world(seed, endpoints, db):
    job = seed.job("DEV-COLLECT")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    db.commit()


@pytest.fixture
def host(page, live_api):
    """Opens a AutoApp address inside a stand-in WLA page. Returns (frame, messages)."""
    def _open(address):
        page.set_content(f"""
            <html><body>
              <h1>Stand-in WLA</h1>
              <script>
                window.messages = [];
                window.addEventListener("message", event => window.messages.push(event.data));
              </script>
              <iframe id="autoapp" src="{live_api}{address}" style="width: 1300px; height: 800px"></iframe>
            </body></html>""")
        frame = page.frame_locator("#autoapp")
        return frame, lambda: page.evaluate("window.messages")
    return _open


def wait_for_message(page, event):
    page.wait_for_function(f"() => window.messages.some(m => m.event === {json.dumps(event)})", timeout=15000)
    return next(m for m in page.evaluate("window.messages") if m["event"] == event)


# --- What embedding changes -------------------------------------------------------------------

def test_an_embedded_page_has_no_header_or_navigation(page, host, world):
    frame, _ = host("/ui/job.html?key=DEV-COLLECT&embed=1")

    frame.locator(".embed-bar").wait_for()
    assert frame.locator("nav.app-nav").count() == 0
    assert frame.locator("#job-selector").is_hidden()
    assert frame.locator("#open-in-autoapp").get_attribute("href") == "/ui/job.html?key=DEV-COLLECT"


def test_the_same_page_on_its_own_still_has_them(page, world):
    page.goto("/ui/job.html?key=DEV-COLLECT")
    page.wait_for_load_state("networkidle")

    assert page.locator("nav.app-nav").count() == 1
    assert page.locator(".embed-bar").count() == 0


def test_links_from_an_embedded_page_stay_embedded(page, host, world):
    frame, _ = host("/ui/job.html?key=DEV-COLLECT&embed=1&theme=light")
    frame.locator("#run-job-button").wait_for()

    frame.locator("#run-job-button").click()

    frame.locator("#run-job").wait_for()
    assert frame.locator(".embed-bar").count() == 1
    assert frame.locator("html").get_attribute("data-theme") == "light"


def test_the_host_can_choose_light_or_dark(page, host, world):
    frame, _ = host("/ui/operations.html?job_key=DEV-COLLECT&embed=1&theme=light")

    frame.locator(".embed-bar").wait_for()
    assert frame.locator("html").get_attribute("data-theme") == "light"


# --- The job editor -----------------------------------------------------------------------------

def test_the_job_editor_says_when_it_is_ready(page, host, world):
    host("/ui/job.html?key=DEV-COLLECT&embed=1")

    ready = wait_for_message(page, "ready")

    assert ready == {"source": "AutoApp", "event": "ready", "page": "job", "job_key": "DEV-COLLECT",
                     "exists": True, "valid": True}


def test_the_job_editor_says_what_it_saved(page, host, world):
    frame, _ = host("/ui/job.html?key=DEV-COLLECT&embed=1")
    frame.locator("#edit-button").click()
    frame.locator("#job-description").fill("Changed from the WLA")

    frame.locator("#submit-button").click()

    saved = wait_for_message(page, "saved")
    assert (saved["page"], saved["job_key"], saved["created"], saved["valid"]) == ("job", "DEV-COLLECT", False, True)
    assert saved["changes"] == ["Changed the description."]
    assert saved["previous_key"] is None


def test_a_new_job_starts_with_the_key_the_wla_suggests(page, host, world):
    frame, _ = host("/ui/job.html?new&key=DEV-FROM-WLA&embed=1")

    frame.locator("#job-key").wait_for()
    assert frame.locator("#job-key").input_value() == "DEV-FROM-WLA"
    ready = wait_for_message(page, "ready")
    assert (ready["job_key"], ready["exists"]) == ("DEV-FROM-WLA", False)

    frame.locator("#submit-button").click()

    saved = wait_for_message(page, "saved")
    assert (saved["job_key"], saved["created"]) == ("DEV-FROM-WLA", True)


def test_cancelling_a_new_job_tells_the_wla(page, host, world):
    frame, _ = host("/ui/job.html?new&key=DEV-FROM-WLA&embed=1")
    frame.locator("#job-key").wait_for()
    frame.locator("#job-description").fill("Not wanted after all")
    page.once("dialog", lambda dialog: dialog.accept())

    frame.locator("#cancel-button").click()

    assert wait_for_message(page, "cancelled")["job_key"] == "DEV-FROM-WLA"
    assert frame.locator(".embed-bar").count() == 1                 # still in place, not sent to Job Search


def test_deleting_a_job_tells_the_wla(page, host, seed, db, world):
    seed.job("DEV-UNWANTED")
    db.commit()
    frame, _ = host("/ui/job.html?key=DEV-UNWANTED&embed=1")
    frame.locator("#edit-button").click()
    page.once("dialog", lambda dialog: dialog.accept())

    frame.locator("#delete-button").click()

    assert wait_for_message(page, "deleted")["job_key"] == "DEV-UNWANTED"
    assert frame.locator("#save-notice").inner_text() == "Deleted job 'DEV-UNWANTED'."


def test_messages_go_only_to_the_host_named(page, host, world):
    """With host=, a page on any other origin hears nothing; the stand-in host here is about:blank."""
    host("/ui/job.html?key=DEV-COLLECT&embed=1&host=https://wla.example")
    frame = page.frame_locator("#autoapp")
    frame.locator(".embed-bar").wait_for()
    page.wait_for_timeout(1000)

    assert page.evaluate("window.messages") == []


# --- The other addresses ------------------------------------------------------------------------

def test_the_operations_log_for_one_run(page, host, world, run_runner):
    run_runner("DEV-COLLECT", "WLA-881")
    frame, _ = host("/ui/operations.html?job_key=DEV-COLLECT&instance_id=WLA-881&embed=1")

    frame.locator("#result-summary").wait_for()
    page.wait_for_timeout(500)
    assert frame.locator("input[name=instance_id]").input_value() == "WLA-881"
    assert frame.locator(".embed-bar").count() == 1


def test_a_runs_log_and_the_jobs_history(page, host, world, run_runner, load_spool, client):
    run_runner("DEV-COLLECT", "WLA-882")
    load_spool()
    [run] = client.get("/api/v1/runs").json()

    frame, _ = host(f"/ui/log.html?run={run['run_id']}&embed=1")
    frame.locator("#job-log").wait_for()
    assert "completed successfully" in frame.locator("#job-log").inner_text()

    frame, _ = host("/ui/log.html?job_key=DEV-COLLECT&instance_id=WLA-882&embed=1")
    frame.locator("#job-log").wait_for()
    assert "instance WLA-882" in frame.locator(".run-panel").inner_text()

    frame, _ = host("/ui/history.html?job_key=DEV-COLLECT&embed=1")
    frame.locator("a.run-log").first.wait_for()
    assert frame.locator(".embed-bar").count() == 1

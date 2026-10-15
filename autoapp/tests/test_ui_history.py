"""The Job History and Audit Log pages, in a real browser against a real server."""
import pytest

from conftest import wait_for_search


@pytest.fixture
def runs(seed, endpoints, outbox, run_runner, load_spool, db):
    good = seed.job("DEV-COLLECT")
    seed.step(good, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    bad = seed.job("DEV-BROKEN")
    seed.step(bad, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="missing", CreateFolder="False")
    run_runner("DEV-COLLECT", "1001")
    run_runner("DEV-BROKEN", "1002")
    run_runner("DEV-COLLECT", "1003", "--run-number", "2", "--scheduler", "CTM_PROD")
    load_spool()
    db.commit()


def test_job_history_lists_runs_newest_first(page, runs):
    page.goto("/ui/history.html")
    rows = wait_for_search(page)

    assert [row.locator(".job-key").inner_text() for row in rows.all()] == ["DEV-COLLECT", "DEV-BROKEN", "DEV-COLLECT"]
    newest, failed = rows.nth(0), rows.nth(1)
    assert newest.locator(".status").inner_text() == "SUCCESS"
    assert "instance 1003" in newest.inner_text() and "run 2" in newest.inner_text()
    assert "scheduler CTM_PROD" in newest.inner_text()
    assert newest.locator("a.files").inner_text() == "2 operations"
    assert failed.locator(".status").inner_text() == "FAILED"
    assert "No such file or directory" in failed.locator(".error-text").first.inner_text()
    assert "1 failed" in failed.inner_text()
    assert "3 runs, newest first" in page.locator("#result-summary").inner_text()


def test_job_history_is_searched_and_links_to_the_job_and_its_files(page, runs):
    page.goto("/ui/history.html?status=FAILED")
    rows = wait_for_search(page)
    assert rows.count() == 1 and page.locator("select[name=status]").input_value() == "FAILED"

    rows.first.locator("a.files").click()
    page.wait_for_url("**/ui/operations.html?job_key=DEV-BROKEN&instance_id=1002")
    assert wait_for_search(page).count() == 1

    page.goto("/ui/history.html?scheduler=ctm")
    rows = wait_for_search(page)
    assert rows.count() == 1
    rows.first.locator(".job-key").click()
    page.wait_for_url("**/ui/job.html?key=DEV-COLLECT")


@pytest.fixture
def changes(page, db, seed, endpoints):
    db.commit()
    page.request.post("/api/v1/jobs", data={"job_key": "DEV-LOAD", "steps": []})
    page.request.put("/api/v1/jobs/DEV-LOAD", data={"job_key": "DEV-LOAD", "description": "Edited", "steps": []})
    page.request.post("/api/v1/entities", data={"name": "ACME_BANK", "abbr": "ACME"})
    page.request.delete("/api/v1/entities/ACME_BANK")
    page.request.put("/api/v1/endpoints/BILLING_INBOX", data={"description": "Billing loads from here"})


def test_the_audit_log_says_what_was_changed_and_how(page, changes):
    page.goto("/ui/audit.html")
    rows = wait_for_search(page)

    assert [row.locator(".action").inner_text() for row in rows.all()] == [
        "Endpoint updated", "Entity deleted", "Entity created", "Job updated", "Job created"]
    assert [row.locator(".subject").inner_text() for row in rows.all()] == [
        "BILLING_INBOX", "ACME_BANK", "ACME_BANK", "DEV-LOAD", "DEV-LOAD"]
    assert rows.nth(3).locator(".change").inner_text() == "Changed the description."
    assert "web interface" in rows.nth(0).inner_text()


def test_the_audit_log_links_to_what_still_exists(page, changes):
    page.goto("/ui/audit.html")
    rows = wait_for_search(page)

    assert rows.nth(1).locator("a.subject").count() == 0              # a deleted entity has nowhere to go
    rows.nth(0).locator("a.subject").click()
    page.wait_for_url("**/ui/detail.html?kind=endpoints&name=BILLING_INBOX")


def test_the_audit_log_is_searched(page, changes):
    page.goto("/ui/audit.html")
    wait_for_search(page)

    page.locator("input[name=action]").fill("deleted")
    page.get_by_role("button", name="Search").click()
    page.wait_for_timeout(50)
    rows = wait_for_search(page)

    assert [row.locator(".action").inner_text() for row in rows.all()] == ["Entity deleted"]
    assert "action=deleted" in page.url

"""
A job's summary for a scheduler to show in its own interface:
GET /api/v1/jobs/{key}/summary, and the card page that shows it (ui/summary.html).
"""
import pytest


@pytest.fixture
def world(seed, endpoints, db, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))
    job = seed.job("DEV-COLLECT")
    job.Description = "Collects the legal extracts"
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    seed.attach(seed.tag("Legal"), job)
    db.commit()


def test_the_summary_says_what_the_job_does_in_brief(client, world):
    summary = client.get("/api/v1/jobs/DEV-COLLECT/summary").json()

    assert (summary["job_key"], summary["description"], summary["active"], summary["ready"]) == (
        "DEV-COLLECT", "Collects the legal extracts", True, True)
    assert [(s["order"], s["title"], s["line"]) for s in summary["steps"]] == [
        (1, "Collect", "LEGAL_EXTRACTS  →  incoming"), (2, "Deliver", "incoming/*.csv  →  BILLING_INBOX")]
    assert (summary["endpoints"], summary["tags"], summary["run"]) == (["BILLING_INBOX", "LEGAL_EXTRACTS"], ["Legal"], None)


def test_the_summarys_links_are_full_addresses(client, world):
    links = client.get("/api/v1/jobs/DEV-COLLECT/summary").json()["links"]

    assert links["editor"] == "http://testserver/ui/job.html?key=DEV-COLLECT"
    assert links["operations"] == "http://testserver/ui/operations.html?job_key=DEV-COLLECT"
    assert links["history"] == "http://testserver/ui/history.html?job_key=DEV-COLLECT"


def test_the_summary_describes_the_last_run_or_the_one_asked_for(client, world, run_runner, load_spool):
    run_runner("DEV-COLLECT", "WLA-1")
    run_runner("DEV-COLLECT", "WLA-2")
    load_spool()

    latest = client.get("/api/v1/jobs/DEV-COLLECT/summary").json()["run"]
    first = client.get("/api/v1/jobs/DEV-COLLECT/summary", params={"instance_id": "WLA-1"}).json()["run"]

    assert latest["instance_id"] == "WLA-2" and first["instance_id"] == "WLA-1"
    assert (first["status"], first["operations"]) == ("SUCCESS", 4)
    assert first["links"]["operations"] == "http://testserver/ui/operations.html?job_key=DEV-COLLECT&instance_id=WLA-1"
    assert first["links"]["log"].startswith("http://testserver/ui/log.html?run=")


def test_a_job_with_problems_says_what_they_are(client, seed, db, world):
    job = seed.job("DEV-BROKEN")
    seed.step(job, 1, Source="in/${Missing}", Dest="out")
    db.commit()

    summary = client.get("/api/v1/jobs/DEV-BROKEN/summary").json()

    assert summary["ready"] is False
    assert any("${Missing}" in p for p in summary["problems"])


def test_an_unknown_job_is_404(client):
    assert client.get("/api/v1/jobs/NOPE/summary").status_code == 404


def test_the_summary_card_shows_it_embedded(page, world):
    page.goto("/ui/summary.html?key=DEV-COLLECT&embed=1")
    page.locator("#summary-steps li").first.wait_for()

    assert page.locator("#summary-ready").inner_text() == "Ready to run"
    assert [li.locator("code").inner_text() for li in page.locator("#summary-steps li").all()] == [
        "LEGAL_EXTRACTS → incoming", "incoming/*.csv → BILLING_INBOX"]
    assert page.locator("#summary-run").inner_text() == "Never run."
    assert "embed=1" in page.locator("#summary-editor").get_attribute("href")     # it stays embedded
    assert page.locator(".embed-bar").count() == 1

"""Job History (GET /api/v1/runs) and the Audit Log (GET /api/v1/audits)."""
import pytest


@pytest.fixture
def runs(seed, endpoints, outbox, run_runner, load_spool, db):
    """Three runs of two jobs: a success, a failure, and a success through a named scheduler."""
    good = seed.job("DEV-COLLECT")
    seed.step(good, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    bad = seed.job("DEV-BROKEN")
    seed.step(bad, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="missing", CreateFolder="False")
    run_runner("DEV-COLLECT", "1001")
    run_runner("DEV-BROKEN", "1002")
    run_runner("DEV-COLLECT", "1003", "--run-number", "2", "--scheduler", "CTM_PROD")
    load_spool()
    db.commit()


def instances(response):
    assert response.status_code == 200, response.text
    return [run["instance_id"] for run in response.json()]


def test_runs_are_listed_newest_first_with_what_each_did(client, runs):
    newest, failed, first = client.get("/api/v1/runs").json()

    assert [r["instance_id"] for r in (newest, failed, first)] == ["1003", "1002", "1001"]
    assert (newest["job_key"], newest["status"], newest["run_number"], newest["scheduler"]) == (
        "DEV-COLLECT", "SUCCESS", 2, "CTM_PROD")
    assert (newest["operations"], newest["failed_operations"]) == (2, 0)
    assert newest["duration_seconds"] >= 0 and newest["host"]
    assert (failed["status"], failed["operations"], failed["failed_operations"]) == ("FAILED", 1, 1)
    assert "No such file or directory" in failed["error"]


@pytest.mark.parametrize("criteria, expected", [
    ({"job_key": "collect"}, ["1003", "1001"]),
    ({"status": "failed"}, ["1002"]),
    ({"instance_id": "1001"}, ["1001"]),
    ({"instance_id": "100"}, []),
    ({"scheduler": "ctm"}, ["1003"]),
    ({"date_from": "2099-01-01T00:00:00"}, []),
    ({"limit": 1}, ["1003"]),
])
def test_runs_can_be_searched(client, runs, criteria, expected):
    assert instances(client.get("/api/v1/runs", params=criteria)) == expected


def test_a_run_that_never_got_going_is_listed_with_its_reason(client, db, run_runner, load_spool):
    run_runner("NO_SUCH_JOB", "1004")
    load_spool()
    db.commit()

    [run] = client.get("/api/v1/runs").json()

    assert (run["job_key"], run["status"], run["operations"]) == ("NO_SUCH_JOB", "FAILED", 0)
    assert run["error"] == "No job with JobKey 'NO_SUCH_JOB' exists."


@pytest.fixture
def changes(client, db, seed, endpoints):
    db.commit()
    client.post("/api/v1/jobs", json={"job_key": "DEV-LOAD", "steps": []})
    client.put("/api/v1/jobs/DEV-LOAD", json={"job_key": "DEV-LOAD", "description": "Edited", "steps": []})
    client.post("/api/v1/entities", json={"name": "ACME_BANK", "abbr": "ACME"})
    client.put("/api/v1/endpoints/BILLING_INBOX", json={"description": "Billing loads from here"})
    client.delete("/api/v1/entities/ACME_BANK")


def test_changes_are_listed_newest_first_saying_what_changed(client, changes):
    audits = client.get("/api/v1/audits").json()

    assert [(a["action"], a["kind"], a["name"]) for a in audits] == [
        ("ENTITY_DELETED", "entities", "ACME_BANK"),
        ("ENDPOINT_UPDATED", "endpoints", "BILLING_INBOX"),
        ("ENTITY_CREATED", "entities", "ACME_BANK"),
        ("JOB_UPDATED", "jobs", "DEV-LOAD"),
        ("JOB_CREATED", "jobs", "DEV-LOAD"),
    ]
    assert audits[3]["changes"] == ["Changed the description."]
    assert all(a["performed_by"] == "web interface" and a["time"] for a in audits)


@pytest.mark.parametrize("criteria, expected", [
    ({"action": "deleted"}, ["ENTITY_DELETED"]),
    ({"action": "job"}, ["JOB_UPDATED", "JOB_CREATED"]),
    ({"action": "entity created"}, ["ENTITY_CREATED"]),           # spaces work as underscores
    ({"name": "billing"}, ["ENDPOINT_UPDATED"]),
    ({"name": "dev-load"}, ["JOB_UPDATED", "JOB_CREATED"]),
    ({"name": "description"}, []),                                # only the name of what changed is searched
    ({"performed_by": "web"}, ["ENTITY_DELETED", "ENDPOINT_UPDATED", "ENTITY_CREATED", "JOB_UPDATED", "JOB_CREATED"]),
    ({"date_to": "2000-01-01T00:00:00"}, []),
    ({"limit": 2}, ["ENTITY_DELETED", "ENDPOINT_UPDATED"]),
])
def test_changes_can_be_searched(client, changes, criteria, expected):
    assert [a["action"] for a in client.get("/api/v1/audits", params=criteria).json()] == expected

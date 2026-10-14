"""/api/v1/endpoints: listing the registered endpoints, and registering a new one."""
import json

import pytest

from app.models import Audit, Endpoint

ROUTE = "/api/v1/endpoints"


def test_endpoints_are_listed_in_name_order_with_who_owns_them(client, db, seed):
    bank = seed.entity("ACME_BANK")
    seed.endpoint("legal_extracts", "${APP.Root}/outbox", "${FilePattern}", application=seed.application("LEGAL_APP"))
    seed.endpoint("ACME_PAYMENTS", "/inbound", "PAY_*.csv", application=seed.application("PAYMENTS_APP"),
                  site=seed.site("ACME_SFTP", bank))
    seed.endpoint("BARE", "/data/in")
    db.commit()

    response = client.get(ROUTE)

    assert response.status_code == 200
    assert [e["name"] for e in response.json()] == ["ACME_PAYMENTS", "BARE", "legal_extracts"]      # whatever their case
    payments, bare, legal = response.json()
    assert payments == {"name": "ACME_PAYMENTS", "application": "PAYMENTS_APP", "site": "ACME_SFTP",
                        "entity": "ACME_BANK", "path": "/inbound", "filename_pattern": "PAY_*.csv", "description": None}
    assert (legal["application"], legal["site"], legal["entity"]) == ("LEGAL_APP", None, None)
    assert (legal["path"], legal["filename_pattern"]) == ("${APP.Root}/outbox", "${FilePattern}")     # as registered
    assert (bare["application"], bare["site"]) == (None, None)


def test_endpoints_can_be_narrowed_by_part_of_the_name(client, db, seed):
    for name in ("LEGAL_EXTRACTS", "BILLING_INBOX", "BILLING_OUTBOX"):
        seed.endpoint(name, "/x")
    db.commit()

    names = lambda **criteria: [e["name"] for e in client.get(ROUTE, params=criteria).json()]

    assert names(name="billing") == ["BILLING_INBOX", "BILLING_OUTBOX"]
    assert names(name="BOX") == ["BILLING_INBOX", "BILLING_OUTBOX"]
    assert names(name="nothing") == []
    assert names(limit=1) == ["BILLING_INBOX"]


def test_no_endpoints_gives_an_empty_list(client):
    assert client.get(ROUTE).json() == []


# --- Registering an endpoint ------------------------------------------------------------------

def test_an_endpoint_is_registered_and_can_then_be_listed(client, db, seed):
    seed.application("LEGAL_APP")
    db.commit()

    response = client.post(ROUTE, json={
        "name": "LEGAL_EXTRACTS", "application": "LEGAL_APP", "path": "${APP.Root}/outbox",
        "filename_pattern": "Legal_*.csv", "description": "Client extracts",
    })

    assert response.status_code == 201
    assert response.json() == {
        "name": "LEGAL_EXTRACTS", "application": "LEGAL_APP", "site": None, "entity": None,
        "path": "${APP.Root}/outbox", "filename_pattern": "Legal_*.csv", "description": "Client extracts"}
    assert client.get(ROUTE).json() == [response.json()]
    assert [e["value"] for e in client.get("/api/v1/lookups").json()["endpoints"]] == ["LEGAL_EXTRACTS"]


def test_only_a_name_and_a_path_are_needed(client):
    response = client.post(ROUTE, json={"name": "SCRATCH", "path": "/data/scratch"})

    assert response.status_code == 201
    assert (response.json()["filename_pattern"], response.json()["application"]) == ("*", None)     # every file


def test_an_endpoint_on_a_site_belongs_to_that_sites_entity(client, db, seed):
    seed.site("ACME_SFTP", seed.entity("ACME_BANK"))
    db.commit()

    created = client.post(ROUTE, json={"name": "ACME_PAYMENTS", "site": "ACME_SFTP", "path": "/inbound"}).json()

    assert (created["site"], created["entity"]) == ("ACME_SFTP", "ACME_BANK")


def test_a_newly_registered_endpoint_can_be_used_by_a_job_at_once(client, db, seed, run_runner, tmp_path, outbox):
    seed.set_vars(seed.application("LEGAL_APP"), Root=str(tmp_path))
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="NEW_EXTRACTS", Dest="incoming")
    db.commit()

    client.post(ROUTE, json={"name": "NEW_EXTRACTS", "application": "LEGAL_APP",
                             "path": "${APP.Root}/app_outbox", "filename_pattern": "*.csv"})
    result = run_runner("DEV-LOAD")

    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in (tmp_path / "work" / "DEV-LOAD" / "incoming").iterdir()) == [
        "Legal_Batch_1.csv", "Legal_Batch_2.csv"]


def test_a_name_already_registered_is_refused(client, db, seed):
    seed.endpoint("LEGAL_EXTRACTS", "/x")
    db.commit()

    response = client.post(ROUTE, json={"name": "LEGAL_EXTRACTS", "path": "/y"})

    assert response.status_code == 409
    assert response.json()["detail"] == "An endpoint named 'LEGAL_EXTRACTS' is already registered."
    assert db.query(Endpoint).one().Path == "/x"


def test_the_same_name_in_different_case_is_a_different_endpoint(client, db, seed):
    seed.endpoint("LEGAL_EXTRACTS", "/x")
    db.commit()

    assert client.post(ROUTE, json={"name": "legal_extracts", "path": "/y"}).status_code == 201


@pytest.mark.parametrize("name", ["", "   ", "has space", "slash/inside", "-leading-dash"])
def test_an_unusable_name_is_refused(client, db, name):
    response = client.post(ROUTE, json={"name": name, "path": "/x"})

    assert response.status_code == 422
    assert db.query(Endpoint).count() == 0


@pytest.mark.parametrize("fields, message", [
    ({"path": "   "}, "An endpoint needs a path."),
    ({"path": "/x", "filename_pattern": " "}, "An endpoint needs a filename pattern. Use * for every file."),
    ({"path": "/x", "application": "NO_SUCH_APP"}, "There is no application named 'NO_SUCH_APP'."),
    ({"path": "/x", "site": "NO_SUCH_SITE"}, "There is no site named 'NO_SUCH_SITE'."),
])
def test_what_is_missing_or_unknown_is_refused_with_the_reason(client, db, fields, message):
    response = client.post(ROUTE, json={"name": "NEW_ENDPOINT", **fields})

    assert response.status_code == 422
    assert response.json()["detail"] == message
    assert db.query(Endpoint).count() == 0


def test_registering_an_endpoint_is_recorded_in_the_audit_log(client, db):
    client.post(ROUTE, json={"name": "SCRATCH", "path": "/data/scratch"})
    client.post(ROUTE, json={"name": "SCRATCH", "path": "/elsewhere"})          # refused: nothing to record

    [audit] = db.query(Audit).all()
    assert (audit.Action, audit.PerformedBy) == ("ENDPOINT_CREATED", "web interface")
    assert json.loads(audit.Details) == {"endpoint": "SCRATCH", "changes": ["Registered endpoint 'SCRATCH'."]}

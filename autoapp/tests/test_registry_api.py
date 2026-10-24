"""Registering applications, entities and sites: POST on /api/v1/applications, /entities and /sites."""
import json

import pytest

from core.models import Application, Audit, Entity, Site


def lookups(client, kind):
    return [entry["value"] for entry in client.get("/api/v1/lookups").json()[kind]]


# --- Applications ---------------------------------------------------------------------------------

def test_an_application_is_registered_and_offered_in_drop_downs(client, db):
    response = client.post("/api/v1/applications", json={"name": "LEGAL_APP", "abbr": "LGL", "description": "Case management"})

    assert response.status_code == 201
    assert response.json() == {"name": "LEGAL_APP", "abbr": "LGL", "description": "Case management"}
    assert lookups(client, "applications") == ["LEGAL_APP"]
    assert db.query(Application).one().CreatedBy == "web interface"


def test_an_application_name_or_abbreviation_already_in_use_is_refused(client, db, seed):
    seed.application("LEGAL_APP")               # the seeder gives it the abbreviation LEGAL_APP
    db.commit()

    taken_name = client.post("/api/v1/applications", json={"name": "LEGAL_APP", "abbr": "LGL"})
    taken_abbr = client.post("/api/v1/applications", json={"name": "LEGAL_TWO", "abbr": "LEGAL_APP"})

    assert (taken_name.status_code, taken_name.json()["detail"]) == (409, "An application named 'LEGAL_APP' is already registered.")
    assert (taken_abbr.status_code, taken_abbr.json()["detail"]) == (
        409, "The abbreviation 'LEGAL_APP' is already used by another application.")
    assert db.query(Application).count() == 1


@pytest.mark.parametrize("body, message", [
    ({"name": "has space", "abbr": "X"}, "Invalid application name 'has space'"),
    ({"name": "LEGAL_APP", "abbr": "  "}, "An application needs an abbreviation."),
])
def test_an_unusable_application_is_refused_with_the_reason(client, db, body, message):
    response = client.post("/api/v1/applications", json=body)

    assert response.status_code == 422 and message in response.json()["detail"]
    assert db.query(Application).count() == 0


# --- Entities -------------------------------------------------------------------------------------

def test_an_entity_is_registered(client, db):
    response = client.post("/api/v1/entities", json={"name": "ACME_BANK", "abbr": "ACME", "description": "Receives payments"})

    assert response.status_code == 201
    assert response.json() == {"name": "ACME_BANK", "abbr": "ACME", "description": "Receives payments"}
    assert lookups(client, "entities") == ["ACME_BANK"]


def test_an_entity_name_already_registered_is_refused(client, db, seed):
    seed.entity("ACME_BANK")
    db.commit()

    response = client.post("/api/v1/entities", json={"name": "ACME_BANK", "abbr": "ACME"})

    assert (response.status_code, response.json()["detail"]) == (409, "An entity named 'ACME_BANK' is already registered.")


# --- Sites ----------------------------------------------------------------------------------------

def test_a_site_is_registered_for_an_entity(client, db, seed):
    seed.entity("ACME_BANK")
    db.commit()

    response = client.post("/api/v1/sites", json={"name": "ACME_SFTP", "entity": "ACME_BANK", "host": "sftp.acme.example",
                                                  "port": 2222, "protocol": "sftp", "description": "File transfer"})

    assert response.status_code == 201
    assert response.json() == {"name": "ACME_SFTP", "entity": "ACME_BANK", "host": "sftp.acme.example", "port": 2222,
                               "protocol": "SFTP", "description": "File transfer"}
    assert lookups(client, "sites") == ["ACME_SFTP"]
    assert db.query(Site).one().entity.Name == "ACME_BANK"


def test_a_site_needs_only_a_name_and_a_host(client):
    response = client.post("/api/v1/sites", json={"name": "INTERNAL_NAS", "host": "nas01"})

    assert response.status_code == 201
    assert (response.json()["port"], response.json()["protocol"], response.json()["entity"]) == (22, "SFTP", None)


@pytest.mark.parametrize("body, status, message", [
    ({"name": "ACME_SFTP", "host": "  "}, 422, "A site needs a host."),
    ({"name": "ACME_SFTP", "host": "h", "entity": "NO_SUCH_ENTITY"}, 422, "There is no entity named 'NO_SUCH_ENTITY'."),
    ({"name": "bad name", "host": "h"}, 422, "Invalid site name 'bad name'"),
    ({"name": "ACME_SFTP", "host": "h", "port": 70000}, 422, None),
])
def test_an_unusable_site_is_refused(client, db, body, status, message):
    response = client.post("/api/v1/sites", json=body)

    assert response.status_code == status
    if message:
        assert message in response.json()["detail"]
    assert db.query(Site).count() == 0


def test_a_site_name_already_registered_is_refused(client, db, seed):
    seed.site("ACME_SFTP", seed.entity("ACME_BANK"))
    db.commit()

    response = client.post("/api/v1/sites", json={"name": "ACME_SFTP", "host": "elsewhere"})

    assert (response.status_code, response.json()["detail"]) == (409, "A site named 'ACME_SFTP' is already registered.")


def test_an_endpoint_can_be_registered_on_a_site_just_created(client):
    client.post("/api/v1/entities", json={"name": "ACME_BANK", "abbr": "ACME"})
    client.post("/api/v1/sites", json={"name": "ACME_SFTP", "entity": "ACME_BANK", "host": "sftp.acme.example"})
    client.post("/api/v1/applications", json={"name": "PAYMENTS_APP", "abbr": "PAY"})

    endpoint = client.post("/api/v1/endpoints", json={"name": "ACME_PAYMENTS", "application": "PAYMENTS_APP",
                                                      "site": "ACME_SFTP", "path": "/inbound"}).json()

    assert (endpoint["application"], endpoint["site"], endpoint["entity"]) == ("PAYMENTS_APP", "ACME_SFTP", "ACME_BANK")


def test_each_registration_is_recorded_in_the_audit_log(client, db):
    client.post("/api/v1/applications", json={"name": "LEGAL_APP", "abbr": "LGL"})
    client.post("/api/v1/entities", json={"name": "ACME_BANK", "abbr": "ACME"})
    client.post("/api/v1/sites", json={"name": "ACME_SFTP", "host": "h"})
    client.post("/api/v1/sites", json={"name": "ACME_SFTP", "host": "h"})            # refused: nothing recorded

    audits = [(a.Action, json.loads(a.Details)["changes"], a.MasterObject_id is not None) for a in db.query(Audit).order_by(Audit.id)]
    assert audits == [
        ("APPLICATION_CREATED", ["Registered application 'LEGAL_APP'."], True),
        ("ENTITY_CREATED", ["Registered entity 'ACME_BANK'."], True),
        ("SITE_CREATED", ["Registered site 'ACME_SFTP'."], True),
    ]


def test_a_new_application_entity_or_site_can_start_inactive_and_with_variables(client, db):
    variables = [{"name": "Root", "value": "/data/x"}, {"name": "Password", "value": "s3cr3t", "secret": True}]

    client.post("/api/v1/applications", json={"name": "X_APP", "abbr": "X", "active": False, "variables": variables})
    client.post("/api/v1/entities", json={"name": "X_CORP", "abbr": "X", "variables": variables[:1]})
    client.post("/api/v1/sites", json={"name": "X_SFTP", "host": "h", "active": False})

    application = client.get("/api/v1/applications/X_APP").json()
    assert application["active"] is False
    assert [(v["name"], v["value"], v["secret"]) for v in application["variables"]] == [
        ("Password", None, True), ("Root", "/data/x", False)]
    assert client.get("/api/v1/entities/X_CORP").json()["variables"][0]["value"] == "/data/x"
    assert client.get("/api/v1/sites/X_SFTP").json()["active"] is False


def test_a_new_one_with_an_unusable_variable_is_refused_entirely(client, db):
    response = client.post("/api/v1/applications", json={"name": "X_APP", "abbr": "X", "variables": [{"name": "bad name", "value": "v"}]})

    assert response.status_code == 422 and "Invalid variable name" in response.json()["detail"]
    assert db.query(Application).count() == 0

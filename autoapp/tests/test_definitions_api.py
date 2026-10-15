"""
Searching, viewing, changing and removing applications, entities, sites and
endpoints: GET, PUT and DELETE on /api/v1/{applications,entities,sites,endpoints}.
"""
import json

import pytest

from app.models import Audit, Endpoint, Entity, JobStepParameter, Operation, Site, Variable


@pytest.fixture
def world(db, seed, tmp_path):
    """Two applications, an entity with a site, three endpoints, and a job that uses two of them."""
    legal = seed.application("LEGAL_APP", Root=str(tmp_path))
    legal.Description = "Case management"
    billing = seed.application("BILLING_APP")
    bank = seed.entity("ACME_BANK", Contact="ops@acme.example")
    seed.entity("GLOBEX")
    sftp = seed.site("ACME_SFTP", bank, host="sftp.acme.example")
    seed.endpoint("LEGAL_EXTRACTS", "${APP.Root}/app_outbox", "Legal_Batch_*.csv", application=legal)
    seed.endpoint("BILLING_INBOX", tmp_path / "app_inbox", "*.csv", application=billing)
    seed.endpoint("ACME_PAYMENTS", "/inbound", "PAY_*.csv", application=billing, site=sftp)
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, Source="incoming/*.csv", DestEndpoint="BILLING_INBOX")
    other = seed.job("DEV-OTHER")
    seed.step(other, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="in")
    db.commit()


def names(response):
    assert response.status_code == 200, response.text
    return [item["name"] for item in response.json()]


# --- Searching ------------------------------------------------------------------------------------

def test_each_kind_is_listed_in_name_order(client, world):
    assert names(client.get("/api/v1/applications")) == ["BILLING_APP", "LEGAL_APP"]
    assert names(client.get("/api/v1/entities")) == ["ACME_BANK", "GLOBEX"]
    assert names(client.get("/api/v1/sites")) == ["ACME_SFTP"]
    assert names(client.get("/api/v1/endpoints")) == ["ACME_PAYMENTS", "BILLING_INBOX", "LEGAL_EXTRACTS"]


def test_a_search_row_says_how_much_uses_it(client, world):
    applications = {a["name"]: a for a in client.get("/api/v1/applications").json()}
    endpoints = {e["name"]: e for e in client.get("/api/v1/endpoints").json()}

    assert (applications["BILLING_APP"]["used_by_count"], applications["LEGAL_APP"]["used_by_count"]) == (2, 1)
    assert endpoints["LEGAL_EXTRACTS"]["used_by_count"] == 2          # two jobs
    assert endpoints["ACME_PAYMENTS"]["used_by_count"] == 0


@pytest.mark.parametrize("route, criteria, expected", [
    ("/api/v1/endpoints", {"name": "inbox"}, ["BILLING_INBOX"]),
    ("/api/v1/endpoints", {"application": "billing"}, ["ACME_PAYMENTS", "BILLING_INBOX"]),
    ("/api/v1/endpoints", {"site": "sftp"}, ["ACME_PAYMENTS"]),
    ("/api/v1/endpoints", {"entity": "acme"}, ["ACME_PAYMENTS"]),           # through its site
    ("/api/v1/endpoints", {"filename_pattern": "pay_"}, ["ACME_PAYMENTS"]),
    ("/api/v1/endpoints", {"path": "/inbound"}, ["ACME_PAYMENTS"]),
    ("/api/v1/endpoints", {"application": "billing", "site": "sftp"}, ["ACME_PAYMENTS"]),
    ("/api/v1/applications", {"description": "CASE"}, ["LEGAL_APP"]),
    ("/api/v1/sites", {"entity": "acme_bank", "host": "acme.example"}, ["ACME_SFTP"]),
    ("/api/v1/sites", {"port": "22"}, ["ACME_SFTP"]),
    ("/api/v1/sites", {"port": "2222"}, []),
    ("/api/v1/entities", {"name": "nobody"}, []),
])
def test_any_field_can_be_a_search_criterion(client, world, route, criteria, expected):
    assert names(client.get(route, params=criteria)) == expected


def test_search_by_active_or_not(client, db, world):
    db.query(Entity).filter(Entity.Name == "GLOBEX").one().IsActive = False
    db.commit()

    assert names(client.get("/api/v1/entities", params={"active": "true"})) == ["ACME_BANK"]
    assert names(client.get("/api/v1/entities", params={"active": "false"})) == ["GLOBEX"]


def test_an_unknown_kind_is_404(client):
    assert client.get("/api/v1/widgets").status_code == 404


# --- One ------------------------------------------------------------------------------------------

def test_one_endpoint_with_the_jobs_that_use_it(client, world):
    endpoint = client.get("/api/v1/endpoints/LEGAL_EXTRACTS").json()

    assert {k: endpoint[k] for k in ("name", "application", "site", "entity", "path", "filename_pattern")} == {
        "name": "LEGAL_EXTRACTS", "application": "LEGAL_APP", "site": None, "entity": None,
        "path": "${APP.Root}/app_outbox", "filename_pattern": "Legal_Batch_*.csv"}
    assert endpoint["used_by"] == [{"kind": "jobs", "name": "DEV-LOAD"}, {"kind": "jobs", "name": "DEV-OTHER"}]
    assert "variables" not in endpoint                                   # an endpoint holds no variables


def test_one_application_with_its_variables_and_its_endpoints(client, world, tmp_path):
    application = client.get("/api/v1/applications/LEGAL_APP").json()

    assert (application["name"], application["abbr"], application["active"]) == ("LEGAL_APP", "LEGAL_APP", True)
    assert application["variables"] == [{"name": "Root", "value": str(tmp_path), "secret": False, "description": None}]
    assert application["used_by"] == [{"kind": "endpoints", "name": "LEGAL_EXTRACTS"}]


def test_one_site_and_one_entity(client, world):
    site = client.get("/api/v1/sites/ACME_SFTP").json()
    entity = client.get("/api/v1/entities/ACME_BANK").json()

    assert (site["entity"], site["host"], site["port"], site["protocol"]) == ("ACME_BANK", "sftp.acme.example", 22, "SFTP")
    assert site["used_by"] == [{"kind": "endpoints", "name": "ACME_PAYMENTS"}]
    assert entity["used_by"] == [{"kind": "sites", "name": "ACME_SFTP"}]
    assert entity["variables"][0]["name"] == "Contact"


def test_one_that_does_not_exist_is_404(client, world):
    response = client.get("/api/v1/sites/NO_SUCH_SITE")

    assert (response.status_code, response.json()["detail"]) == (404, "No site named 'NO_SUCH_SITE' exists.")


# --- Changing -------------------------------------------------------------------------------------

def test_fields_are_changed_and_the_change_is_described(client, db, world):
    response = client.put("/api/v1/sites/ACME_SFTP", json={"host": "files.acme.example", "port": 2222,
                                                         "protocol": "ftps", "description": "New server"})

    assert response.status_code == 200
    site = response.json()["item"]
    assert (site["host"], site["port"], site["protocol"], site["description"]) == ("files.acme.example", 2222, "FTPS", "New server")
    assert response.json()["changes"] == ["Changed the host.", "Changed the port.", "Changed the protocol.",
                                          "Changed the description."]
    assert site["modified_by"] == "web interface"


def test_fields_left_out_stay_as_they_are(client, world):
    client.put("/api/v1/sites/ACME_SFTP", json={"description": "Only this"})

    site = client.get("/api/v1/sites/ACME_SFTP").json()
    assert (site["host"], site["entity"], site["description"]) == ("sftp.acme.example", "ACME_BANK", "Only this")


def test_saving_unchanged_records_nothing(client, db, world):
    current = client.get("/api/v1/endpoints/BILLING_INBOX").json()

    response = client.put("/api/v1/endpoints/BILLING_INBOX", json=current)

    assert response.json()["changes"] == []
    assert db.query(Audit).count() == 0


def test_what_something_belongs_to_is_changed_by_name(client, world):
    response = client.put("/api/v1/endpoints/ACME_PAYMENTS", json={"application": "LEGAL_APP", "site": ""})

    endpoint = response.json()["item"]
    assert (endpoint["application"], endpoint["site"], endpoint["entity"]) == ("LEGAL_APP", None, None)
    assert response.json()["changes"] == ["Changed the application.", "Changed the site."]


def test_a_rename_of_an_application_keeps_its_endpoints(client, world):
    response = client.put("/api/v1/applications/LEGAL_APP", json={"name": "LEGAL_SYSTEM"})

    assert response.json()["changes"] == ["Renamed from 'LEGAL_APP' to 'LEGAL_SYSTEM'."]
    assert client.get("/api/v1/endpoints/LEGAL_EXTRACTS").json()["application"] == "LEGAL_SYSTEM"


def test_renaming_an_endpoint_renames_it_in_every_job_step_that_names_it(client, db, world, run_runner, outbox, tmp_path):
    response = client.put("/api/v1/endpoints/LEGAL_EXTRACTS", json={"name": "LEGAL_EXTRACT_FILES"})

    assert response.json()["changes"] == ["Renamed from 'LEGAL_EXTRACTS' to 'LEGAL_EXTRACT_FILES'.",
                                          "Updated 2 job steps that named it."]
    db.expire_all()
    assert {p.ParamValue for p in db.query(JobStepParameter).filter(JobStepParameter.ParamName == "SourceEndpoint")} == {
        "LEGAL_EXTRACT_FILES"}
    assert run_runner("DEV-LOAD").returncode == 0                          # the job still runs
    assert client.get("/api/v1/endpoints/LEGAL_EXTRACT_FILES").json()["used_by"][0]["name"] == "DEV-LOAD"


@pytest.mark.parametrize("route, body, status, message", [
    ("/api/v1/endpoints/BILLING_INBOX", {"name": "LEGAL_EXTRACTS"}, 409, "An endpoint named 'LEGAL_EXTRACTS' is already registered."),
    ("/api/v1/endpoints/BILLING_INBOX", {"name": "bad name"}, 422, "Invalid endpoint name 'bad name'"),
    ("/api/v1/endpoints/BILLING_INBOX", {"path": "  "}, 422, "An endpoint needs a path."),
    ("/api/v1/endpoints/BILLING_INBOX", {"application": "NO_SUCH_APP"}, 422, "There is no application named 'NO_SUCH_APP'."),
    ("/api/v1/sites/ACME_SFTP", {"port": "twenty-two"}, 422, "The port must be a whole number"),
    ("/api/v1/sites/ACME_SFTP", {"port": 70000}, 422, "The port must be between 1 and 65535."),
    ("/api/v1/sites/ACME_SFTP", {"entity": "NOBODY"}, 422, "There is no entity named 'NOBODY'."),
    ("/api/v1/applications/LEGAL_APP", {"abbr": "BILLING_AP"[:10]}, 409, None),
    ("/api/v1/applications/LEGAL_APP", {"abbr": ""}, 422, "An application needs an abbr."),
])
def test_a_change_that_cannot_be_made_is_refused_and_nothing_changes(client, db, world, route, body, status, message):
    before = client.get(route).json()

    response = client.put(route, json=body)

    assert response.status_code == status
    if message:
        assert message in response.json()["detail"]
    assert client.get(route).json() == before


def test_variables_are_changed_with_a_secret_kept_unless_replaced(client, db, world, tmp_path):
    client.put("/api/v1/applications/LEGAL_APP", json={"variables": [
        {"name": "Root", "value": str(tmp_path)}, {"name": "Password", "value": "s3cr3t", "secret": True}]})
    current = client.get("/api/v1/applications/LEGAL_APP").json()
    assert [(v["name"], v["value"]) for v in current["variables"]] == [("Password", None), ("Root", str(tmp_path))]

    response = client.put("/api/v1/applications/LEGAL_APP", json={"variables": current["variables"]})      # sent back blank

    assert response.json()["changes"] == []
    db.expire_all()
    assert db.query(Variable).filter(Variable.VarName == "Password").one().VarValue == "s3cr3t"


def test_an_application_variable_changed_here_changes_where_its_endpoint_points(client, db, world, run_runner, tmp_path):
    moved = tmp_path / "moved"
    (moved / "app_outbox").mkdir(parents=True)
    (moved / "app_outbox" / "Legal_Batch_9.csv").write_text("id\n9")

    client.put("/api/v1/applications/LEGAL_APP", json={"variables": [{"name": "Root", "value": str(moved)}]})

    assert run_runner("DEV-OTHER").returncode == 0
    assert [p.name for p in (tmp_path / "work" / "DEV-OTHER" / "in").iterdir()] == ["Legal_Batch_9.csv"]


def test_deactivating_is_recorded(client, world):
    response = client.put("/api/v1/entities/GLOBEX", json={"active": False})

    assert (response.json()["item"]["active"], response.json()["changes"]) == (False, ["Deactivated the entity."])


# --- Removing -------------------------------------------------------------------------------------

def test_something_nothing_uses_is_deleted(client, db, world):
    assert client.delete("/api/v1/entities/GLOBEX").status_code == 204

    assert client.get("/api/v1/entities/GLOBEX").status_code == 404
    db.expire_all()
    assert db.query(Entity).count() == 1


@pytest.mark.parametrize("route, message", [
    ("/api/v1/endpoints/LEGAL_EXTRACTS", "Endpoint 'LEGAL_EXTRACTS' cannot be deleted while 2 jobs use it: DEV-LOAD, DEV-OTHER. Change them first."),
    ("/api/v1/applications/BILLING_APP", "Application 'BILLING_APP' cannot be deleted while 2 endpoints use it: ACME_PAYMENTS, BILLING_INBOX."),
    ("/api/v1/sites/ACME_SFTP", "Site 'ACME_SFTP' cannot be deleted while 1 endpoint uses it: ACME_PAYMENTS. Change it first."),
    ("/api/v1/entities/ACME_BANK", "Entity 'ACME_BANK' cannot be deleted while 1 site uses it: ACME_SFTP."),
])
def test_something_still_in_use_is_not_deleted(client, world, route, message):
    response = client.delete(route)

    assert response.status_code == 409
    assert response.json()["detail"].startswith(message)
    assert client.get(route).status_code == 200


def test_an_endpoint_that_only_history_mentions_can_be_deleted_and_the_history_keeps_its_paths(
        client, db, world, outbox, run_runner, load_spool, tmp_path):
    assert run_runner("DEV-LOAD").returncode == 0
    load_spool()
    client.put("/api/v1/jobs/DEV-LOAD", json={"job_key": "DEV-LOAD", "steps": []})     # the job stops using it
    client.delete("/api/v1/jobs/DEV-OTHER")

    assert client.delete("/api/v1/endpoints/BILLING_INBOX").status_code == 204

    db.expire_all()
    delivered = db.query(Operation).filter(Operation.DestPath == str(tmp_path / "app_inbox")).all()
    assert len(delivered) == 2 and all(op.DestEndpoint_id is None for op in delivered)


def test_changes_and_removals_are_in_the_audit_log(client, db, world):
    client.put("/api/v1/sites/ACME_SFTP", json={"port": 2222})
    client.delete("/api/v1/entities/GLOBEX")
    client.delete("/api/v1/entities/ACME_BANK")                     # refused: nothing recorded

    db.expire_all()
    assert [(a.Action, json.loads(a.Details)["changes"]) for a in db.query(Audit).order_by(Audit.id)] == [
        ("SITE_UPDATED", ["Changed the port."]),
        ("ENTITY_DELETED", ["Deleted entity 'GLOBEX'."]),
    ]

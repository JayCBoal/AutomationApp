"""
The RunMyJobs connector (app/connectors/runmyjobs.py), against a stand-in for
RunMyJobs' Inbound REST extension. The stand-in answers the way Redwood's published
specification (swagger.yml 1.1.0.0) says the real one does: the job definition as
JSON, with its JobDefinitionParameters. This shows the connector reads that shape;
it cannot show that a real RunMyJobs answers exactly so.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.models import Scheduler, Variable

API_KEY = "rmj-test-key"
BASE = "/redwood/demo/api-extension/External/REDWOOD/Redwood_RestService/rest/v1"

JOB_DEFINITIONS = {
    "GLOBAL.AUTOAPP_BILLING_EXPORT": {
        "Name": "AUTOAPP_BILLING_EXPORT", "Partition": "GLOBAL", "Description": "Billing exports through AutoApp",
        "JobDefinitionType": "BASH",
        "JobDefinitionParameters": [
            {"Name": "Region", "DefaultExpression": "EU", "Direction": "In", "DataType": "String",
             "Password": False, "DisplayOrder": 2},
            {"Name": "ExportPassword", "DefaultExpression": None, "Direction": "In", "DataType": "String",
             "Password": True, "DisplayOrder": 3},
            {"Name": "RowsWritten", "DefaultExpression": None, "Direction": "Out", "DataType": "Number",
             "Password": False, "DisplayOrder": 4},
            {"Name": "AutoAppJobKey", "DefaultExpression": "DEV-REGIONAL", "Direction": "In", "DataType": "String",
             "Password": False, "DisplayOrder": 1},
            {"Name": "Ledger", "DefaultExpression": "GL01", "Direction": "InOut", "DataType": "String",
             "Password": False, "DisplayOrder": 5},
        ],
    },
}


class FakeInboundRest(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("X-API-KEY") != API_KEY:
            return self._send(401, {"code": "401", "message": "Unauthorized"})
        prefix = BASE + "/JobDefinition/"
        if not self.path.startswith(prefix):
            return self._send(404, {"code": "404", "message": "Not found"})
        key = self.path[len(prefix):]
        if key not in JOB_DEFINITIONS:
            return self._send(404, {"code": "404", "message": f"Unable to find object JobDefinition:{key}"})
        self._send(200, JOB_DEFINITIONS[key])


@pytest.fixture
def rmj():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeInboundRest)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}{BASE}"
    server.shutdown()


@pytest.fixture
def registered(db, rmj):
    scheduler = Scheduler(Name="RMJ_DEV", Technology="RUNMYJOBS", ApiUrl=rmj)
    db.add(scheduler)
    db.flush()
    db.add(Variable(MasterObject_id=scheduler.MasterObject_id, VarName="ApiToken", VarValue=API_KEY, IsSecret=True))
    db.commit()
    return scheduler


def test_the_connector_reads_a_job_definitions_parameters(client, registered):
    response = client.get("/api/v1/schedulers/RMJ_DEV/jobs/GLOBAL.AUTOAPP_BILLING_EXPORT")

    assert response.status_code == 200, response.text
    job = response.json()
    assert job["description"] == "Billing exports through AutoApp"
    # in RunMyJobs' display order; an Out parameter is not set before the run, and AutoAppJobKey is AutoApp's own
    assert job["parameters"] == [
        {"name": "Region", "value": "EU", "secret": False},
        {"name": "ExportPassword", "value": None, "secret": True},
        {"name": "Ledger", "value": "GL01", "secret": False},
    ]


def test_the_api_key_is_sent_as_x_api_key(client, db, registered):
    db.query(Variable).filter(Variable.VarName == "ApiToken").one().VarValue = "wrong"
    db.commit()

    response = client.get("/api/v1/schedulers/RMJ_DEV/jobs/GLOBAL.AUTOAPP_BILLING_EXPORT")

    assert response.status_code == 502
    assert "refused AutoApp's API key" in response.json()["detail"]


def test_an_unknown_job_definition_says_so(client, registered):
    response = client.get("/api/v1/schedulers/RMJ_DEV/jobs/GLOBAL.NOPE")

    assert (response.status_code, response.json()["detail"]) == (
        502, "RunMyJobs ('RMJ_DEV') has no job definition 'GLOBAL.NOPE'.")


def test_a_job_is_named_by_its_business_key(client, registered):
    response = client.get("/api/v1/schedulers/RMJ_DEV/jobs/AUTOAPP_BILLING_EXPORT")

    assert response.status_code == 502
    assert "give it as <partition>.<name>, e.g. GLOBAL.AUTOAPP_BILLING_EXPORT" in response.json()["detail"]


def test_the_pre_run_check_uses_runmyjobs_parameters(client, seed, endpoints, db, registered, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))
    job = seed.job("DEV-REGIONAL")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="in_${Region}_${Ledger}")
    db.commit()

    plain = client.get("/api/v1/jobs/DEV-REGIONAL/check").json()
    with_rmj = client.get("/api/v1/jobs/DEV-REGIONAL/check",
                          params={"scheduler": "RMJ_DEV", "wla_job": "GLOBAL.AUTOAPP_BILLING_EXPORT"}).json()

    assert plain["valid"] is False
    assert with_rmj["valid"] is True, with_rmj["problems"]

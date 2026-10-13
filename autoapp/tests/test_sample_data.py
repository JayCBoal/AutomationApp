"""
SQL/Seed_Sample_Data.sql: the sample definitions must fit the schema and
actually run. The seed is loaded into a database built from the models, its
file locations are pointed at the test's temp folder, and both sample jobs are
run with the real runner.
"""
from sqlalchemy import text

from app.models import Endpoint, Job, StepDefinition, Variable
from create_dev_db import load_seed


def test_sample_jobs_run_and_hand_a_file_from_one_to_the_other(db, run_runner, load_spool, client, tmp_path):
    load_seed(db)
    for root in db.query(Variable).filter(Variable.VarName == "Root"):
        root.VarValue = root.VarValue.replace("/tmp/autoapp_sample", str(tmp_path))
    outbox = tmp_path / "legal_app" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "Legal_Batch_001.csv").write_text("client,amount\nACME,100\n")

    collect = run_runner("DEV-LEGAL-COLLECT_AND_DELIVER", "1001")
    load = run_runner("DEV-BILLING-LOAD", "1002")

    assert (collect.returncode, load.returncode) == (0, 0), collect.stderr + load.stderr
    assert (tmp_path / "work" / "DEV-BILLING-LOAD" / "to_load" / "Legal_Batch_001.csv").exists()

    load_spool()
    db.commit()
    [picked_up] = client.get("/api/v1/operations", params={"job_key": "DEV-BILLING-LOAD"}).json()
    trace = client.get(f"/api/v1/operations/{picked_up['id']}/trace").json()
    assert [(hop["job_key"], hop["source"]["endpoint"], hop["dest"]["endpoint"]) for hop in trace["hops"]] == [
        ("DEV-LEGAL-COLLECT_AND_DELIVER", "LEGAL_APP_EXTRACTS", None),
        ("DEV-LEGAL-COLLECT_AND_DELIVER", None, None),
        ("DEV-LEGAL-COLLECT_AND_DELIVER", None, "BILLING_APP_INBOX"),
        ("DEV-BILLING-LOAD", "BILLING_APP_INBOX", None),
    ]


def test_rows_inserted_by_plain_sql_get_the_schema_defaults(db):
    """The seed leaves out IsActive and the like; a job that came out disabled would never run."""
    load_seed(db)

    assert all(job.IsActive is True for job in db.query(Job))
    assert all(step.IsActive is True for job in db.query(Job) for step in job.steps)
    assert db.execute(text("SELECT CreatedBy, CreatedDateTime FROM MasterObjects WHERE id = 5")).one()[0] == "system"
    assert db.execute(text("SELECT CreatedDateTime FROM MasterObjects WHERE id = 5")).scalar() is not None


def test_sample_endpoint_on_a_remote_site_belongs_to_its_entity(db):
    load_seed(db)

    endpoint = db.query(Endpoint).filter(Endpoint.Name == "ACME_BANK_PAYMENTS").one()

    assert (endpoint.site.Name, endpoint.site.entity.Name) == ("ACME_BANK_SFTP", "ACME_BANK")
    assert (endpoint.site.Port, endpoint.site.Protocol) == (22, "SFTP")


def test_step_catalog_lists_the_parameters_the_file_handler_reads(db):
    load_seed(db)

    names = {d.ParamName for d in db.query(StepDefinition)}

    assert names == {"Source", "SourceEndpoint", "Dest", "DestEndpoint", "Move", "CreateFolder", "Checksum", "AllowNoFiles", "LogLevel"}

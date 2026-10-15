"""
SQL/Seed_Sample_Data.sql: the sample definitions must fit the schema and
actually run. The seed is loaded into a database built from the models, its
file locations are pointed at the test's temp folder, and the sample jobs are
run with the real runner.
"""
from sqlalchemy import text

from app.catalog import sync_catalog
from app.models import Endpoint, Job, StepType, Variable
from create_dev_db import create_sales_db, load_seed
from engine.handlers import HANDLER_REGISTRY


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


def test_sample_export_jobs_query_the_sales_database_and_hand_the_reports_to_finance(
        db, run_runner, load_spool, client, tmp_path):
    load_seed(db)
    for root in db.query(Variable).filter(Variable.VarName == "Root"):
        root.VarValue = root.VarValue.replace("/tmp/autoapp_sample", str(tmp_path))
    create_sales_db(tmp_path / "sales.db")
    db.query(Variable).filter(Variable.VarName == "SalesDbUrl").one().VarValue = f"sqlite:///{tmp_path / 'sales.db'}"

    export = run_runner("DEV-BILLING-INVOICE_EXPORT", "1003")
    report = run_runner("DEV-FINANCE-LOAD_REPORTS", "1004")

    assert (export.returncode, report.returncode) == (0, 0), export.stderr + report.stderr
    work = tmp_path / "work" / "DEV-FINANCE-LOAD_REPORTS"
    [day] = list((work / "reports").iterdir())
    invoices = (day / f"Open_Invoices_{day.name}.csv").read_text().splitlines()
    assert invoices[0] == "invoice_no,customer_code,customer_name,invoice_date,due_date,total_amount,status"
    assert len(invoices) == 1 + 12                             # the sample has 8 open and 4 overdue invoices
    assert (day / f"Payments_{day.name}.csv").exists()
    assert [p.name for p in (work / "archive").iterdir()] == [f"Billing_{day.name}.zip"]
    assert list((tmp_path / "finance_app" / "inbox").iterdir()) == []

    load_spool()
    db.commit()
    [unpacked] = client.get("/api/v1/operations", params={"op_type": "UNZIP", "filename": "Open_Invoices"}).json()
    trace = client.get(f"/api/v1/operations/{unpacked['id']}/trace").json()
    assert [(hop["job_key"], hop["op_type"]) for hop in trace["hops"]] == [
        ("DEV-BILLING-INVOICE_EXPORT", "SQL_EXPORT"),
        ("DEV-BILLING-INVOICE_EXPORT", "CHECK"),
        ("DEV-BILLING-INVOICE_EXPORT", "ZIP_MOVE"),
        ("DEV-FINANCE-LOAD_REPORTS", "MOVE"),
        ("DEV-FINANCE-LOAD_REPORTS", "UNZIP"),
        ("DEV-FINANCE-LOAD_REPORTS", "CHECK"),
        ("DEV-FINANCE-LOAD_REPORTS", "MOVE"),
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


def test_sample_step_type_is_the_one_the_catalog_knows(db):
    """The seed creates the step type its jobs use; syncing the catalog must fill it in, not add a second one."""
    load_seed(db)

    sync_catalog(db)

    assert all(t.HandlerClass in HANDLER_REGISTRY for t in db.query(StepType))
    assert len({t.HandlerClass for t in db.query(StepType)}) == db.query(StepType).count()
    [step_type] = db.query(StepType).filter_by(HandlerClass="COPY_FILES").all()
    assert step_type.TypeName == "Copy Files"
    assert [d.ParamName for d in step_type.definitions][:2] == ["Source", "Dest"]

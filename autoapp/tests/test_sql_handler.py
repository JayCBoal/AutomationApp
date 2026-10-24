"""
Run SQL: the real handler against a real SQLite database in a temp folder, with real spool output.
"""
import csv
import sqlite3

import pytest

from engine.handlers.sql_handler import RunSqlHandler, safe_url
from engine.telemetry_client import LocalSpoolTelemetryClient


@pytest.fixture
def sales(tmp_path):
    """A small database of invoices. Returns its URL."""
    path = tmp_path / "sales.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE invoices (invoice_no TEXT, customer TEXT, amount NUMERIC, note TEXT);
            INSERT INTO invoices VALUES ('INV-1', 'ACME', 100.50, NULL);
            INSERT INTO invoices VALUES ('INV-2', 'GLOBEX, LTD', 250, 'paid "early"');
            INSERT INTO invoices VALUES ('INV-3', 'INITECH', 75, NULL);
        """)
    return f"sqlite:///{path}"


def run_handler(spool, params):
    config = {"StepID": 401, "StepType": "RUN_SQL", "StepOrder": 1, "Title": "Query"}
    with LocalSpoolTelemetryClient(spool_dir=str(spool), instance_id="T1") as telemetry:
        return RunSqlHandler(step_config=config, telemetry_client=telemetry).run(params)


def count(url):
    with sqlite3.connect(url.removeprefix("sqlite:///")) as connection:
        return connection.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]


def test_a_query_writes_its_rows_to_csv(sales, tmp_path, spool_records):
    out = tmp_path / "out" / "invoices.csv"

    result = run_handler(tmp_path / "spool", {
        "Database": sales, "Statement": "SELECT invoice_no, customer, amount, note FROM invoices ORDER BY invoice_no",
        "ResultFile": str(out)})

    assert result["status"] == "SUCCESS"
    assert "The query returned 3 rows." in result["result"]["details"]["summary"]
    with open(out, newline="") as f:
        assert list(csv.reader(f)) == [
            ["invoice_no", "customer", "amount", "note"],
            ["INV-1", "ACME", "100.5", ""],
            ["INV-2", "GLOBEX, LTD", "250", 'paid "early"'],      # commas and quotes survive the round trip
            ["INV-3", "INITECH", "75", ""],
        ]
    [record] = spool_records(tmp_path / "spool")
    assert (record["OpType"], record["Status"]) == ("SQL_EXPORT", "SUCCESS")
    assert (record["SourcePath"], record["SourceFilename"]) == (None, None)
    assert (record["DestPath"], record["DestFilename"], record["DestSize"]) == (
        str(out.parent), "invoices.csv", out.stat().st_size)
    assert record["Details"]["Rows"] == 3
    assert record["Details"]["Statement"].startswith("SELECT invoice_no")


def test_the_header_line_can_be_left_out(sales, tmp_path):
    out = tmp_path / "invoices.csv"

    run_handler(tmp_path / "spool", {"Database": sales, "Statement": "SELECT invoice_no FROM invoices",
                                     "ResultFile": str(out), "IncludeHeader": "False"})

    assert out.read_text().splitlines() == ["INV-1", "INV-2", "INV-3"]


def test_a_query_with_no_rows_writes_just_the_header(sales, tmp_path):
    out = tmp_path / "invoices.csv"

    run_handler(tmp_path / "spool", {"Database": sales, "Statement": "SELECT invoice_no FROM invoices WHERE 1 = 0",
                                     "ResultFile": str(out)})

    assert out.read_text().splitlines() == ["invoice_no"]


def test_a_result_file_is_not_replaced_unless_told_to(sales, tmp_path):
    out = tmp_path / "invoices.csv"
    out.write_text("yesterday")
    params = {"Database": sales, "Statement": "SELECT 1 AS one", "ResultFile": str(out)}

    with pytest.raises(FileExistsError):
        run_handler(tmp_path / "spool", params)
    assert out.read_text() == "yesterday"

    run_handler(tmp_path / "spool", {**params, "Overwrite": "True"})
    assert out.read_text().splitlines() == ["one", "1"]


def test_a_query_without_a_result_file_is_recorded_without_one(sales, tmp_path, spool_records):
    result = run_handler(tmp_path / "spool", {"Database": sales, "Statement": "SELECT * FROM invoices"})

    assert result["status"] == "SUCCESS"
    [record] = spool_records(tmp_path / "spool")
    assert (record["OpType"], record["DestFilename"], record["Details"]["Rows"]) == ("SQL", None, 3)


def test_changes_are_rolled_back_unless_commit_is_set(sales, tmp_path, spool_records):
    """So a statement can be tried safely; keeping its changes is a deliberate choice."""
    params = {"Database": sales, "Statement": "DELETE FROM invoices WHERE customer = 'ACME'"}

    result = run_handler(tmp_path / "spool", params)
    assert "The statement changed 1 row; rolled back, as Commit is False." in result["result"]["details"]["summary"]
    assert count(sales) == 3

    result = run_handler(tmp_path / "spool", {**params, "Commit": "True"})
    assert "The statement changed 1 row; committed." in result["result"]["details"]["summary"]
    assert count(sales) == 2
    assert spool_records(tmp_path / "spool")[-1]["Details"]["RowsAffected"] == 1


def test_a_failing_statement_fails_the_step_with_the_databases_reason(sales, tmp_path, spool_records):
    with pytest.raises(RuntimeError) as error:
        run_handler(tmp_path / "spool", {"Database": sales, "Statement": "SELECT * FROM no_such_table"})

    assert "no such table: no_such_table" in str(error.value)
    [record] = spool_records(tmp_path / "spool")
    assert (record["OpType"], record["Status"]) == ("SQL", "FAILED")
    assert "no such table" in record["Error"]


def test_a_result_file_needs_a_query(sales, tmp_path):
    with pytest.raises(ValueError) as error:
        run_handler(tmp_path / "spool", {"Database": sales, "Statement": "UPDATE invoices SET note = 'x'",
                                         "ResultFile": str(tmp_path / "out.csv")})

    assert "returned no rows to write" in str(error.value)
    assert not (tmp_path / "out.csv").exists()
    assert count(sales) == 3


def test_a_bad_database_url_is_a_clear_error(tmp_path, spool_records):
    with pytest.raises(ValueError) as error:
        run_handler(tmp_path / "spool", {"Database": "not a url", "Statement": "SELECT 1"})

    assert "'Database' is not a database URL AutoApp can use" in str(error.value)


def test_the_password_is_never_recorded(tmp_path, spool_records):
    """The database cannot be reached, so the driver's error is recorded too; neither may hold the password."""
    url = "mysql+pymysql://report_user:Sup3rSecret@127.0.0.1:1/sales?connect_timeout=1"

    with pytest.raises(RuntimeError):
        run_handler(tmp_path / "spool", {"Database": url, "Statement": "SELECT 1"})

    [record] = spool_records(tmp_path / "spool")
    assert record["Details"]["Database"] == "mysql+pymysql://report_user:***@127.0.0.1:1/sales?connect_timeout=1"
    assert "Sup3rSecret" not in str(record)


def test_safe_url_hides_only_the_password():
    assert safe_url("mysql+pymysql://u:pw@db.example.com/sales") == "mysql+pymysql://u:***@db.example.com/sales"
    assert safe_url("sqlite:////tmp/sales.db") == "sqlite:////tmp/sales.db"


# --- Through the runner ----------------------------------------------------------------------

def test_an_export_job_takes_its_database_from_a_secret_and_starts_the_files_trace(
        db, seed, sales, run_runner, load_spool, client, tmp_path):
    from core.models import Variable
    job = seed.job("DEV-EXPORT")
    db.add(Variable(MasterObject_id=job.MasterObject_id, VarName="SalesDbUrl", VarValue=sales, IsSecret=True))
    seed.step(job, 1, title="Export", code="RUN_SQL", Database="${SalesDbUrl}",
              Statement="SELECT invoice_no, amount FROM invoices", ResultFile="out/invoices.csv")
    seed.step(job, 2, title="Pack", code="ZIP_FILES", Source="out/*.csv", Dest="send/invoices.zip")

    result = run_runner("DEV-EXPORT", "88421", "--log-level", "DEBUG")

    assert result.returncode == 0, result.stderr
    assert sales not in result.stdout + result.stderr          # the job log shows the secret masked
    assert (tmp_path / "work" / "DEV-EXPORT" / "out" / "invoices.csv").read_text().startswith("invoice_no,amount")
    load_spool()
    export = client.get("/api/v1/operations", params={"op_type": "SQL_EXPORT"}).json()
    assert len(export) == 1
    hops = client.get(f"/api/v1/operations/{export[0]['id']}/trace").json()["hops"]
    assert [(hop["op_type"], hop["dest"]["filename"]) for hop in hops] == [
        ("SQL_EXPORT", "invoices.csv"), ("ZIP", "invoices.zip")]


def test_the_job_log_names_the_database_without_its_password(tmp_path):
    url = "mysql+pymysql://report_user:Sup3rSecret@db.example.com/sales"
    for written in ("${SalesDbUrl}", url):
        config = {"StepID": 401, "StepType": "RUN_SQL", "RawParams": {"Database": written, "Statement": "SELECT 1"}}
        handler = RunSqlHandler(step_config=config, telemetry_client=None)

        [database, _] = handler.describe({"Database": url, "Statement": "SELECT 1"})

        assert "Sup3rSecret" not in database
        assert database == ("Database: ${SalesDbUrl}  (resolved: mysql+pymysql://report_user:***@db.example.com/sales)"
                            if written.startswith("${") else "Database: mysql+pymysql://report_user:***@db.example.com/sales")

"""Telemetry spooler: records land in a .jsonl.tmp file that is renamed on close."""
from engine.telemetry_client import LocalSpoolTelemetryClient


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def test_spool_file_is_tmp_while_open_and_jsonl_after_close(tmp_path):
    spool = tmp_path / "spool"

    with LocalSpoolTelemetryClient(spool_dir=str(spool), instance_id="T1") as client:
        client.log_operation(op_type="COPY_FILES", step_id=1, status="SUCCESS", execution_time_ms=5)
        during = names(spool)

    after = names(spool)
    assert len(during) == 1 and during[0].endswith(".jsonl.tmp")
    assert len(after) == 1 and after[0].endswith(".jsonl")
    assert "T1" in after[0]


def test_operation_record_contents(tmp_path, spool_records):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T2") as client:
        client.log_operation(
            op_type="COPY_FILES", step_id=7, status="SUCCESS", execution_time_ms=12,
            source_path="/in/a.csv", dest_path="/out/a.csv", bytes_transferred=2048,
            details={"checksum": "abc"}
        )

    [record] = spool_records(tmp_path)
    assert record["InstanceID"] == "T2"
    assert record["StepID"] == 7
    assert record["OpType"] == "COPY_FILES"
    assert record["Status"] == "SUCCESS"
    assert record["SourcePath"] == "/in/a.csv"
    assert record["DestPath"] == "/out/a.csv"
    assert record["BytesTransferred"] == 2048
    assert record["Details"] == {"checksum": "abc"}


def test_audit_record_contents(tmp_path, spool_records):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T3") as client:
        client.log_audit(
            action="STEP_EXECUTION_FAILURE", actor="tester", resource_type="JobStep",
            resource_id="102", status="FAILED", details={"error": "Permission denied"}
        )

    [record] = spool_records(tmp_path)
    assert record["IsAudit"] is True
    assert record["Action"] == "STEP_EXECUTION_FAILURE"
    assert record["ResourceId"] == "102"
    assert record["Status"] == "FAILED"
    assert record["Details"] == {"error": "Permission denied"}


def test_records_are_written_in_order_one_per_line(tmp_path, spool_records):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T4") as client:
        for step_id in (1, 2, 3):
            client.log_operation(op_type="COPY_FILES", step_id=step_id, status="SUCCESS", execution_time_ms=1)

    assert [r["StepID"] for r in spool_records(tmp_path)] == [1, 2, 3]

"""Telemetry spooler: records land in a .jsonl.tmp file that is renamed when the run ends."""
import json

from engine.telemetry_client import LocalSpoolTelemetryClient


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def test_spool_file_is_tmp_while_open_and_jsonl_after_close(tmp_path):
    spool = tmp_path / "spool"

    with LocalSpoolTelemetryClient(spool_dir=str(spool), instance_id="T1") as client:
        client.start_run("DEV-LOAD")
        during = names(spool)

    after = names(spool)
    assert len(during) == 1 and during[0].endswith(".jsonl.tmp")
    assert len(after) == 1 and after[0].endswith(".jsonl")
    assert "T1" in after[0]


def test_each_record_is_on_disk_as_soon_as_it_is_written(tmp_path):
    """A run that is killed part-way must still leave what it had recorded."""
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T1") as client:
        client.start_run("DEV-LOAD")
        [spool_file] = tmp_path.iterdir()

        assert json.loads(spool_file.read_text())["Record"] == "RUN_START"


def test_run_start_record_carries_what_the_scheduler_passed(tmp_path, spool_records):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="88421") as client:
        client.start_run("DEV-LOAD", run_number=3, scheduler="CTM_PROD")

    [record] = spool_records(tmp_path)
    assert record["Record"] == "RUN_START"
    assert record["JobKey"] == "DEV-LOAD"
    assert record["InstanceID"] == "88421"
    assert record["RunNumber"] == 3
    assert record["Scheduler"] == "CTM_PROD"
    assert record["RunID"] == client.run_id


def test_file_operation_record_contents(tmp_path, spool_records):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T2") as client:
        client.log_operation(
            op_type="COPY", status="SUCCESS", step_id=7, step_order=2,
            source_path="/in", source_filename="a.csv", source_size=2048, source_endpoint_id=11,
            dest_path="/out", dest_filename="b.csv", dest_size=2048, dest_endpoint_id=None,
            checksum="abc",
        )

    [record] = spool_records(tmp_path)
    assert record["Record"] == "OPERATION"
    assert (record["StepID"], record["StepOrder"]) == (7, 2)
    assert (record["OpType"], record["Status"]) == ("COPY", "SUCCESS")
    assert (record["SourcePath"], record["SourceFilename"], record["SourceSize"]) == ("/in", "a.csv", 2048)
    assert (record["DestPath"], record["DestFilename"], record["DestSize"]) == ("/out", "b.csv", 2048)
    assert record["SourceEndpointID"] == 11
    assert record["DestEndpointID"] is None
    assert record["Checksum"] == "abc"
    assert record["Error"] is None


def test_run_end_record_carries_the_error(tmp_path, spool_records):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T3") as client:
        client.end_run("FAILED", error="Permission denied")

    [record] = spool_records(tmp_path)
    assert record["Record"] == "RUN_END"
    assert record["Status"] == "FAILED"
    assert record["Error"] == "Permission denied"


def test_records_are_numbered_in_the_order_written_and_share_the_run_id(tmp_path, spool_records):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T4") as client:
        client.start_run("DEV-LOAD")
        client.log_operation(op_type="COPY", status="SUCCESS")
        client.log_operation(op_type="COPY", status="SUCCESS")
        client.end_run("SUCCESS")

    records = spool_records(tmp_path)
    assert [r["Record"] for r in records] == ["RUN_START", "OPERATION", "OPERATION", "RUN_END"]
    assert [r["Seq"] for r in records] == [1, 2, 3, 4]
    assert {r["RunID"] for r in records} == {client.run_id}


def test_two_runs_of_the_same_instance_get_separate_files_and_run_ids(tmp_path):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T5") as first:
        first.start_run("DEV-LOAD")
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T5") as second:
        second.start_run("DEV-LOAD")

    assert first.run_id != second.run_id
    assert len(names(tmp_path)) == 2


def test_without_an_api_address_the_spool_file_stays_for_later_delivery(tmp_path):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T6") as client:
        client.start_run("DEV-LOAD")
        assert client.deliver() is False

    [spool_file] = names(tmp_path)
    assert spool_file.endswith(".jsonl")


def test_unreachable_api_leaves_the_spool_file_and_raises_nothing(tmp_path, unused_api_url):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T7", api_url=unused_api_url) as client:
        client.start_run("DEV-LOAD")
        assert client.deliver() is False
        client.end_run("SUCCESS")

    [spool_file] = names(tmp_path)
    assert spool_file.endswith(".jsonl")

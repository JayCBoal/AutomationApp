"""
POST /api/v1/telemetry/records: a runner's spool records arriving over HTTP
and landing in JobRuns and Operations.

The records are produced by the real spool writer, then posted to the real API.
"""
from datetime import datetime

from core.models import JobRun, Operation
from engine.telemetry_client import LocalSpoolTelemetryClient

ROUTE = "/api/v1/telemetry/records"


def spool_a_run(tmp_path, spool_records, job_key="DEV-LOAD", instance_id="88421", files=("a.csv", "b.csv"),
                status="SUCCESS", error=None, **operation_fields):
    """Writes one run to a spool file with the real client and returns its records."""
    spool = tmp_path / f"spool_{len(list(tmp_path.iterdir()))}"
    with LocalSpoolTelemetryClient(spool_dir=str(spool), instance_id=instance_id) as client:
        client.start_run(job_key, run_number=2, scheduler="CTM_PROD")
        for name in files:
            client.log_operation(
                op_type="COPY", status="SUCCESS", step_order=1,
                source_path="/apps/legal/outbox", source_filename=name, source_size=10,
                dest_path="/work/DEV-LOAD/incoming", dest_filename=name, dest_size=10,
                **operation_fields,
            )
        client.end_run(status, error=error)
    return spool_records(spool)


def test_a_run_and_its_operations_are_stored(client, db, seed, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    db.commit()
    records = spool_a_run(tmp_path, spool_records)

    response = client.post(ROUTE, json={"records": records})

    assert response.status_code == 201
    assert response.json() == {"runs_started": 1, "runs_ended": 1, "operations_added": 2, "duplicates_skipped": 0}
    [run] = db.query(JobRun).all()
    assert run.RunID == records[0]["RunID"]
    assert (run.JobKey, run.Job_MasterObject_id) == ("DEV-LOAD", job.MasterObject_id)
    assert (run.SchedulerInstanceID, run.RunNumber, run.SchedulerName) == ("88421", 2, "CTM_PROD")
    assert (run.Status, run.ErrorMessage) == ("SUCCESS", None)
    assert run.StartedDateTime <= run.EndedDateTime

    first, second = run.operations
    assert (first.Seq, second.Seq) == (2, 3)
    assert (first.OpType, first.OpStatus, first.StepOrder) == ("COPY", "SUCCESS", 1)
    assert (first.SourcePath, first.SourceFilename, first.SourceSize) == ("/apps/legal/outbox", "a.csv", 10)
    assert (first.DestPath, first.DestFilename, first.DestSize) == ("/work/DEV-LOAD/incoming", "a.csv", 10)
    assert second.SourceFilename == "b.csv"


def test_times_are_stored_as_utc(client, db, tmp_path, spool_records):
    records = spool_a_run(tmp_path, spool_records, files=("a.csv",))
    records[1]["EndedAtUtc"] = "2026-10-12T14:03:07.512Z"

    client.post(ROUTE, json={"records": records})

    assert db.query(Operation).one().EndedDateTime == datetime(2026, 10, 12, 14, 3, 7, 512000)


def test_sending_the_same_records_twice_stores_them_once(client, db, tmp_path, spool_records):
    records = spool_a_run(tmp_path, spool_records)

    client.post(ROUTE, json={"records": records})
    again = client.post(ROUTE, json={"records": records})

    assert again.status_code == 201
    assert again.json() == {"runs_started": 0, "runs_ended": 0, "operations_added": 0, "duplicates_skipped": 4}
    assert db.query(JobRun).count() == 1
    assert db.query(Operation).count() == 2


def test_a_run_can_arrive_in_pieces(client, db, tmp_path, spool_records):
    """The runner posts after each step, so a run is visible while it is still going."""
    start, first_file, second_file, end = spool_a_run(tmp_path, spool_records)

    client.post(ROUTE, json={"records": [start, first_file]})
    run = db.query(JobRun).one()
    assert (run.Status, run.EndedDateTime, len(run.operations)) == ("RUNNING", None, 1)

    # the next post overlaps the first, as it would after a response went missing
    client.post(ROUTE, json={"records": [first_file, second_file, end]})
    db.commit()
    run = db.query(JobRun).one()
    assert (run.Status, len(run.operations)) == ("SUCCESS", 2)
    assert run.EndedDateTime is not None


def test_a_failed_run_keeps_its_error(client, db, tmp_path, spool_records):
    records = spool_a_run(tmp_path, spool_records, job_key="NO_SUCH_JOB", files=(),
                          status="FAILED", error="No job with JobKey 'NO_SUCH_JOB' exists.")

    client.post(ROUTE, json={"records": records})

    run = db.query(JobRun).one()
    assert (run.JobKey, run.Job_MasterObject_id) == ("NO_SUCH_JOB", None)
    assert (run.Status, run.ErrorMessage) == ("FAILED", "No job with JobKey 'NO_SUCH_JOB' exists.")


def test_endpoint_links_are_stored(client, db, seed, tmp_path, spool_records):
    source = seed.endpoint("LEGAL_EXTRACTS", "/apps/legal/outbox")
    db.commit()
    records = spool_a_run(tmp_path, spool_records, files=("a.csv",), source_endpoint_id=source.id)

    client.post(ROUTE, json={"records": records})

    operation = db.query(Operation).one()
    assert (operation.SourceEndpoint_id, operation.DestEndpoint_id) == (source.id, None)
    assert operation.source_endpoint.Name == "LEGAL_EXTRACTS"


def test_an_endpoint_deleted_since_the_run_leaves_the_link_empty_and_keeps_the_path(
        client, db, tmp_path, spool_records):
    records = spool_a_run(tmp_path, spool_records, files=("a.csv",), source_endpoint_id=999)

    response = client.post(ROUTE, json={"records": records})

    assert response.status_code == 201
    operation = db.query(Operation).one()
    assert operation.SourceEndpoint_id is None
    assert operation.SourcePath == "/apps/legal/outbox"


def test_two_runs_in_one_batch_are_kept_apart(client, db, tmp_path, spool_records):
    first = spool_a_run(tmp_path, spool_records, instance_id="1001", files=("a.csv",))
    second = spool_a_run(tmp_path, spool_records, instance_id="1002", files=("b.csv", "c.csv"))

    client.post(ROUTE, json={"records": first + second})

    runs = {run.SchedulerInstanceID: run for run in db.query(JobRun).all()}
    assert [op.SourceFilename for op in runs["1001"].operations] == ["a.csv"]
    assert [op.SourceFilename for op in runs["1002"].operations] == ["b.csv", "c.csv"]


def test_an_operation_for_an_unknown_run_is_refused_and_nothing_is_stored(client, db, tmp_path, spool_records):
    start, first_file, second_file, end = spool_a_run(tmp_path, spool_records)

    response = client.post(ROUTE, json={"records": [first_file, second_file, end]})

    assert response.status_code == 422
    assert "RUN_START" in response.json()["detail"]
    assert db.query(Operation).count() == 0


def test_a_malformed_record_is_refused_and_nothing_is_stored(client, db, tmp_path, spool_records):
    records = spool_a_run(tmp_path, spool_records)
    del records[2]["OpType"]

    response = client.post(ROUTE, json={"records": records})

    assert response.status_code == 422
    assert db.query(JobRun).count() == 0
    assert db.query(Operation).count() == 0


def test_a_value_too_long_for_its_column_is_refused_with_a_reason(client, db, tmp_path, spool_records):
    """Otherwise it would be stored cut short on one database and crash another."""
    records = spool_a_run(tmp_path, spool_records)
    records[1]["Status"] = "S" * 21                       # the column holds 20 characters

    response = client.post(ROUTE, json={"records": records})

    assert response.status_code == 422
    assert "Status" in response.text and "20 characters" in response.text
    assert db.query(JobRun).count() == 0


def test_an_unknown_record_type_is_refused(client, db, tmp_path, spool_records):
    records = spool_a_run(tmp_path, spool_records)
    records[1]["Record"] = "SOMETHING_ELSE"

    assert client.post(ROUTE, json={"records": records}).status_code == 422
    assert db.query(JobRun).count() == 0


def test_a_batch_with_a_bad_record_stores_none_of_it(client, db, tmp_path, spool_records):
    """All or nothing, so the sender can simply send the whole batch again once it is fixed."""
    good = spool_a_run(tmp_path, spool_records, instance_id="1001")
    orphan = spool_a_run(tmp_path, spool_records, instance_id="1002")[1]     # an operation without its RUN_START

    response = client.post(ROUTE, json={"records": good + [orphan]})

    assert response.status_code == 422
    assert db.query(JobRun).count() == 0
    assert db.query(Operation).count() == 0


def test_records_may_arrive_out_of_order_within_a_batch(client, db, tmp_path, spool_records):
    records = spool_a_run(tmp_path, spool_records)

    response = client.post(ROUTE, json={"records": list(reversed(records))})

    assert response.status_code == 201
    run = db.query(JobRun).one()
    assert (run.Status, [op.SourceFilename for op in run.operations]) == ("SUCCESS", ["a.csv", "b.csv"])


# --- Operations that are not files --------------------------------------------------------------

def spool_a_run_without_files(tmp_path, spool_records, instance_id="2001", statement="DELETE FROM staging"):
    """A run whose only step ran a SQL statement, as a future SQL step type would record it."""
    spool = tmp_path / f"spool_{len(list(tmp_path.iterdir()))}"
    with LocalSpoolTelemetryClient(spool_dir=str(spool), instance_id=instance_id) as client:
        client.start_run("DEV-CLEANUP")
        client.log_operation(op_type="SQL", status="SUCCESS", step_order=1,
                             details={"Statement": statement, "RowsAffected": 12})
        client.end_run("SUCCESS")
    return spool_records(spool)


def test_an_operation_without_a_file_is_stored_with_its_details(client, db, tmp_path, spool_records):
    records = spool_a_run_without_files(tmp_path, spool_records)

    assert client.post(ROUTE, json={"records": records}).status_code == 201

    [logged] = client.get("/api/v1/operations", params={"job_key": "DEV-CLEANUP"}).json()
    assert (logged["op_type"], logged["status"]) == ("SQL", "SUCCESS")
    assert logged["details"] == {"Statement": "DELETE FROM staging", "RowsAffected": 12}
    assert (logged["source"]["filename"], logged["dest"]["filename"]) == (None, None)


def test_a_file_operation_has_no_details_unless_given(client, db, tmp_path, spool_records):
    client.post(ROUTE, json={"records": spool_a_run(tmp_path, spool_records, files=("a.csv",))})

    [logged] = client.get("/api/v1/operations").json()
    assert logged["details"] is None


def test_operations_without_files_are_not_linked_to_each_other_in_a_trace(client, db, tmp_path, spool_records):
    """Neither has a file to follow, so each one's trace is only itself."""
    first = spool_a_run_without_files(tmp_path, spool_records, instance_id="2001")
    second = spool_a_run_without_files(tmp_path, spool_records, instance_id="2002")
    client.post(ROUTE, json={"records": first + second})

    for logged in client.get("/api/v1/operations").json():
        trace = client.get(f"/api/v1/operations/{logged['id']}/trace").json()
        assert [hop["id"] for hop in trace["hops"]] == [logged["id"]]

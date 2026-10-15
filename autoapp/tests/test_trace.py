"""
The operations log and the file trace, through the API.

Each test runs real jobs with the real runner, loads the spool they leave, and
asks the API about the result. Layout, inside pytest's temp folder:

    app_outbox/     Endpoint LEGAL_EXTRACTS (application LEGAL_APP), holding Legal_Batch_1.csv and _2.csv
    app_inbox/      Endpoint BILLING_INBOX  (application BILLING_APP)
    work/<JobKey>/  each job's working folder
"""
import pytest

FILE_1 = "Legal_Batch_1.csv"


@pytest.fixture
def collect_and_deliver(seed, endpoints):
    """Collect from LEGAL_EXTRACTS, copy to an archive folder, move to BILLING_INBOX."""
    job = seed.job("DEV-COLLECT")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Archive", Source="incoming/*.csv", Dest="archive")
    seed.step(job, 3, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    return job


@pytest.fixture
def api(client, db, load_spool):
    """Loads whatever the runner has spooled, then returns helpers for asking the API."""
    class Api:
        def operations(self, **criteria):
            load_spool()
            db.commit()
            response = client.get("/api/v1/operations", params=criteria)
            assert response.status_code == 200, response.text
            return response.json()

        def trace(self, operation_id):
            response = client.get(f"/api/v1/operations/{operation_id}/trace")
            assert response.status_code == 200, response.text
            return response.json()

        def trace_of(self, **criteria):
            [operation] = self.operations(**criteria)
            return self.trace(operation["id"])
    return Api()


def route(trace):
    """A trace as readable text: one 'from -> to' line per hop ('from' alone for a check or a delete)."""
    def place(location):
        return f'{location["endpoint"] or location["path"].rsplit("/", 1)[-1]}/{location["filename"]}'
    return [f'{hop["job_key"]} {hop["op_type"]} {place(hop["source"])}'
            + (f' -> {place(hop["dest"])}' if hop["dest"]["filename"] else '') for hop in trace["hops"]]


# --- Operations log -------------------------------------------------------------------------

def test_log_has_one_row_per_file_per_step_newest_first(collect_and_deliver, run_runner, api):
    run_runner("DEV-COLLECT", "88421")

    operations = api.operations()

    assert len(operations) == 6
    assert [(op["step_order"], op["source"]["filename"]) for op in operations] == [
        (3, "Legal_Batch_2.csv"), (3, FILE_1), (2, "Legal_Batch_2.csv"), (2, FILE_1),
        (1, "Legal_Batch_2.csv"), (1, FILE_1),
    ]


def test_log_row_describes_both_sides(collect_and_deliver, run_runner, api, outbox, tmp_path):
    run_runner("DEV-COLLECT", "88421", "--run-number", "2", "--scheduler", "CTM_PROD")

    collect = api.operations(filename=FILE_1)[-1]

    assert collect["source"] == {
        "endpoint": "LEGAL_EXTRACTS", "application": "LEGAL_APP", "entity": None, "site": None,
        "path": str(outbox), "filename": FILE_1, "size": 4,
    }
    assert collect["dest"] == {      # inside the working folder: no endpoint
        "endpoint": None, "application": None, "entity": None, "site": None,
        "path": str(tmp_path / "work" / "DEV-COLLECT" / "incoming"), "filename": FILE_1, "size": 4,
    }
    assert (collect["op_type"], collect["status"], collect["error"]) == ("COPY", "SUCCESS", None)
    assert (collect["job_key"], collect["instance_id"], collect["run_number"], collect["scheduler"]) == (
        "DEV-COLLECT", "88421", 2, "CTM_PROD")
    assert collect["started"] <= collect["ended"]


def test_log_can_be_searched(collect_and_deliver, seed, run_runner, api):
    other = seed.job("DEV-OTHER")
    seed.step(other, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="in")
    run_runner("DEV-COLLECT", "88421")
    run_runner("DEV-OTHER", "88422")

    assert len(api.operations()) == 8
    assert len(api.operations(filename="batch_1")) == 4                 # part of the name, any case
    assert len(api.operations(filename="nothing_like_this")) == 0
    assert len(api.operations(endpoint="billing")) == 2                 # either side of the operation
    assert len(api.operations(endpoint="LEGAL_EXTRACTS")) == 4
    assert len(api.operations(job_key="other")) == 2
    assert len(api.operations(instance_id="88421")) == 6
    assert len(api.operations(instance_id="8842")) == 0                 # instance ID is exact
    assert len(api.operations(status="failed")) == 0
    assert len(api.operations(filename="batch_1", job_key="DEV-OTHER")) == 1    # criteria combine
    assert len(api.operations(limit=3)) == 3


def test_log_can_be_searched_by_one_side_only(collect_and_deliver, run_runner, api):
    """Two files through three steps: collect (endpoint -> incoming), archive, deliver (incoming -> endpoint)."""
    run_runner("DEV-COLLECT", "88421")

    assert len(api.operations(source_endpoint="legal")) == 2           # only the collect step reads from it
    assert len(api.operations(dest_endpoint="legal")) == 0
    assert len(api.operations(dest_endpoint="billing_inbox")) == 2
    assert len(api.operations(source_path="/INCOMING")) == 4           # archive and deliver read from incoming
    assert len(api.operations(dest_path="/incoming")) == 2
    assert len(api.operations(dest_path="/archive")) == 2
    assert len(api.operations(source_filename="batch_2", dest_path="archive")) == 1
    assert len(api.operations(dest_filename="BATCH_1")) == 3
    assert len(api.operations(op_type="move")) == 2
    assert len(api.operations(op_type="COPY")) == 4
    assert len(api.operations(op_type="COP")) == 0                     # the type is exact


def test_log_can_be_searched_by_application_entity_and_site(seed, endpoints, run_runner, api, tmp_path):
    """An endpoint on a site belongs to that site's entity. Ingested by hand: no step type reaches remote sites yet."""
    from app.telemetry_ingest import ingest_records
    bank = seed.entity("ACME_BANK")
    upload = seed.endpoint("ACME_PAYMENTS", "/inbound", "*.csv", application=seed.application("PAYMENTS_APP"),
                           site=seed.site("ACME_SFTP", bank))
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    run_runner("DEV-LOAD", "88421")
    ingest_records(seed.db, [
        {"Record": "RUN_START", "RunID": "r-remote", "Seq": 1, "JobKey": "DEV-SEND", "InstanceID": "88500",
         "StartedAtUtc": "2026-10-12T10:00:00Z"},
        {"Record": "OPERATION", "RunID": "r-remote", "Seq": 2, "OpType": "UPLOAD", "Status": "SUCCESS",
         "SourcePath": "/work/out", "SourceFilename": "PAY_1.csv", "DestPath": "/inbound",
         "DestFilename": "PAY_1.csv", "DestEndpointID": upload.id, "EndedAtUtc": "2026-10-12T10:00:01Z"},
    ])

    assert len(api.operations()) == 3
    assert len(api.operations(application="legal_app")) == 2           # source side of the two collects
    assert len(api.operations(application="payments")) == 1            # destination side of the upload
    assert len(api.operations(entity="acme")) == 1
    assert len(api.operations(site="acme_sftp")) == 1
    assert len(api.operations(entity="nobody")) == 0
    # and each side on its own
    assert len(api.operations(source_application="legal")) == 2
    assert len(api.operations(dest_application="legal")) == 0
    assert len(api.operations(dest_application="PAYMENTS_APP")) == 1
    assert len(api.operations(dest_entity="acme_bank")) == 1 and len(api.operations(source_entity="acme")) == 0
    assert len(api.operations(dest_site="sftp")) == 1 and len(api.operations(source_site="sftp")) == 0
    assert len(api.operations(source_application="legal", dest_site="acme")) == 0       # criteria combine
    [sent] = api.operations(site="ACME")
    assert (sent["dest"]["endpoint"], sent["dest"]["application"], sent["dest"]["entity"], sent["dest"]["site"]) == (
        "ACME_PAYMENTS", "PAYMENTS_APP", "ACME_BANK", "ACME_SFTP")


def test_log_can_be_searched_by_scheduler(collect_and_deliver, run_runner, api):
    run_runner("DEV-COLLECT", "88421", "--scheduler", "CTM_PROD")
    run_runner("DEV-COLLECT", "0001", "--scheduler", "RMJ_FINANCE")
    run_runner("DEV-COLLECT", "88422")                                    # the runner was not told a scheduler

    assert len(api.operations()) == 18
    assert len(api.operations(scheduler="ctm")) == 6                      # part of the name, any case
    assert len(api.operations(scheduler="RMJ_FINANCE")) == 6
    assert len(api.operations(scheduler="_")) == 12
    assert len(api.operations(scheduler="autosys")) == 0
    assert {op["scheduler"] for op in api.operations(scheduler="rmj")} == {"RMJ_FINANCE"}


def test_log_can_be_searched_by_time(collect_and_deliver, run_runner, api):
    run_runner("DEV-COLLECT", "88421")
    operations = api.operations()
    newest, oldest = operations[0]["ended"], operations[-1]["ended"]

    assert len(api.operations(date_from=oldest, date_to=newest)) == 6      # both ends inclusive
    assert len(api.operations(date_from="2099-01-01T00:00:00")) == 0
    assert len(api.operations(date_to="2000-01-01T00:00:00")) == 0


# --- File trace -----------------------------------------------------------------------------

def test_trace_follows_one_file_through_every_step(collect_and_deliver, run_runner, api):
    run_runner("DEV-COLLECT", "88421")

    trace = api.trace_of(filename=FILE_1, endpoint="BILLING_INBOX")

    assert trace["filename"] == FILE_1
    assert route(trace) == [
        f"DEV-COLLECT COPY LEGAL_EXTRACTS/{FILE_1} -> incoming/{FILE_1}",
        f"DEV-COLLECT COPY incoming/{FILE_1} -> archive/{FILE_1}",
        f"DEV-COLLECT MOVE incoming/{FILE_1} -> BILLING_INBOX/{FILE_1}",
    ]
    collect, archive, deliver = trace["hops"]
    assert collect["follows"] is None
    assert archive["follows"] == collect["id"]      # the file was copied to two places from 'incoming',
    assert deliver["follows"] == collect["id"]      # so both hops follow the collect


def test_trace_is_the_same_whichever_hop_it_starts_from(collect_and_deliver, run_runner, api):
    run_runner("DEV-COLLECT", "88421")
    hops = [op["id"] for op in api.operations(filename=FILE_1)]

    traces = [api.trace(operation_id) for operation_id in hops]

    assert len(hops) == 3
    assert all(route(trace) == route(traces[0]) for trace in traces)
    assert len(traces[0]["hops"]) == 3


def test_trace_continues_into_the_job_that_picks_the_file_up(collect_and_deliver, seed, run_runner, api):
    load = seed.job("DEV-BILLING-LOAD")
    seed.step(load, 1, SourceEndpoint="BILLING_INBOX", Dest="to_load", Move="True")
    run_runner("DEV-COLLECT", "88421")
    run_runner("DEV-BILLING-LOAD", "88430")

    trace = api.trace_of(filename=FILE_1, job_key="DEV-BILLING-LOAD")

    assert route(trace) == [
        f"DEV-COLLECT COPY LEGAL_EXTRACTS/{FILE_1} -> incoming/{FILE_1}",
        f"DEV-COLLECT COPY incoming/{FILE_1} -> archive/{FILE_1}",
        f"DEV-COLLECT MOVE incoming/{FILE_1} -> BILLING_INBOX/{FILE_1}",
        f"DEV-BILLING-LOAD MOVE BILLING_INBOX/{FILE_1} -> to_load/{FILE_1}",
    ]
    assert [hop["instance_id"] for hop in trace["hops"]] == ["88421", "88421", "88421", "88430"]
    assert trace["hops"][3]["follows"] == trace["hops"][2]["id"]


def test_trace_follows_a_file_through_a_rename(seed, endpoints, run_runner, api):
    job = seed.job("DEV-RENAME")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, Source=f"incoming/{FILE_1}", Dest="out/for_billing.csv", Move="True")
    seed.step(job, 3, Source="out/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    run_runner("DEV-RENAME", "88421")

    trace = api.trace_of(endpoint="BILLING_INBOX")

    assert route(trace) == [
        f"DEV-RENAME COPY LEGAL_EXTRACTS/{FILE_1} -> incoming/{FILE_1}",
        f"DEV-RENAME MOVE incoming/{FILE_1} -> out/for_billing.csv",
        "DEV-RENAME MOVE out/for_billing.csv -> BILLING_INBOX/for_billing.csv",
    ]
    # a filename search finds the operation that gave the file its new name, as well as the one that read it
    assert len(api.operations(filename="for_billing")) == 2


def test_trace_follows_a_file_into_an_archive_and_out_again(seed, endpoints, run_runner, api, tmp_path):
    seed.endpoint("BILLING_ARCHIVES", tmp_path / "app_inbox", "*.zip")
    send = seed.job("DEV-SEND")
    seed.step(send, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(send, 2, code="CHECK_FILES", Source="incoming/*.csv", MinCount="2")
    seed.step(send, 3, code="ZIP_FILES", Source="incoming/*.csv", DestEndpoint="BILLING_ARCHIVES",
              ArchiveName="batch.zip", Move="True")
    receive = seed.job("DEV-RECEIVE")
    seed.step(receive, 1, SourceEndpoint="BILLING_ARCHIVES", Dest="incoming", Move="True")
    seed.step(receive, 2, code="UNZIP_FILES", Source="incoming/*.zip", Dest="loaded")
    seed.step(receive, 3, code="DELETE_FILES", Source="incoming/*.zip")
    assert run_runner("DEV-SEND", "88421").returncode == 0
    assert run_runner("DEV-RECEIVE", "88430").returncode == 0

    trace = api.trace_of(filename=FILE_1, job_key="DEV-RECEIVE")

    # the archive's own journey belongs to both files; each file comes out the other end on its own
    assert route(trace) == [
        f"DEV-SEND COPY LEGAL_EXTRACTS/{FILE_1} -> incoming/{FILE_1}",
        f"DEV-SEND CHECK incoming/{FILE_1}",
        f"DEV-SEND ZIP_MOVE incoming/{FILE_1} -> BILLING_ARCHIVES/batch.zip",
        "DEV-RECEIVE MOVE BILLING_ARCHIVES/batch.zip -> incoming/batch.zip",
        f"DEV-RECEIVE UNZIP incoming/batch.zip -> loaded/{FILE_1}",
        "DEV-RECEIVE DELETE incoming/batch.zip",
    ]
    copy, check, zipped, move, unzip, delete = trace["hops"]
    assert (check["follows"], zipped["follows"], move["follows"]) == (copy["id"], copy["id"], zipped["id"])
    assert (unzip["follows"], delete["follows"]) == (move["id"], move["id"])

    other = api.trace_of(filename="Legal_Batch_2.csv", job_key="DEV-RECEIVE")
    assert route(other)[0] == "DEV-SEND COPY LEGAL_EXTRACTS/Legal_Batch_2.csv -> incoming/Legal_Batch_2.csv"
    assert route(other)[4] == "DEV-RECEIVE UNZIP incoming/batch.zip -> loaded/Legal_Batch_2.csv"

    # from the archive itself there is no one file to follow back, so the trace starts with the archive
    archive = api.trace(move["id"])
    assert route(archive) == [
        "DEV-RECEIVE MOVE BILLING_ARCHIVES/batch.zip -> incoming/batch.zip",
        f"DEV-RECEIVE UNZIP incoming/batch.zip -> loaded/{FILE_1}",
        "DEV-RECEIVE UNZIP incoming/batch.zip -> loaded/Legal_Batch_2.csv",
        "DEV-RECEIVE DELETE incoming/batch.zip",
    ]


def test_a_deleted_file_is_the_end_of_its_route(seed, endpoints, run_runner, api, tmp_path):
    job = seed.job("DEV-CLEAN")
    collect = seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, code="DELETE_FILES", Source="incoming/*.csv")
    run_runner("DEV-CLEAN", "88421")

    (tmp_path / "work" / "DEV-CLEAN" / "incoming" / FILE_1).write_text("put here by hand")
    collect.IsActive = False
    run_runner("DEV-CLEAN", "88500")

    original = api.trace_of(filename=FILE_1, instance_id="88421", op_type="COPY")
    assert route(original) == [
        f"DEV-CLEAN COPY LEGAL_EXTRACTS/{FILE_1} -> incoming/{FILE_1}",
        f"DEV-CLEAN DELETE incoming/{FILE_1}",
    ]


def test_same_filename_on_another_day_is_a_separate_trace(collect_and_deliver, run_runner, api):
    """The outbox holds the same filenames for both runs, as a daily feed would."""
    run_runner("DEV-COLLECT", "88421")
    run_runner("DEV-COLLECT", "88499")

    first_day = api.trace_of(filename=FILE_1, endpoint="BILLING_INBOX", instance_id="88421")
    second_day = api.trace_of(filename=FILE_1, endpoint="BILLING_INBOX", instance_id="88499")

    assert {hop["instance_id"] for hop in first_day["hops"]} == {"88421"}
    assert {hop["instance_id"] for hop in second_day["hops"]} == {"88499"}
    assert len(first_day["hops"]) == len(second_day["hops"]) == 3


def test_same_filename_on_another_day_is_separate_even_when_nothing_moves_it(seed, endpoints, run_runner, api):
    """Copies only: the first day's file is still in 'incoming' until the second day's collect replaces it."""
    job = seed.job("DEV-COPY")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, Source="incoming/*.csv", DestEndpoint="BILLING_INBOX")
    run_runner("DEV-COPY", "88421")
    run_runner("DEV-COPY", "88499")

    first_day = api.trace_of(filename=FILE_1, endpoint="BILLING_INBOX", instance_id="88421")
    second_day = api.trace_of(filename=FILE_1, endpoint="BILLING_INBOX", instance_id="88499")

    assert [hop["instance_id"] for hop in first_day["hops"]] == ["88421", "88421"]
    assert [hop["instance_id"] for hop in second_day["hops"]] == ["88499", "88499"]


def test_a_file_that_was_moved_on_is_not_linked_to_a_later_file_at_the_same_path(
        seed, endpoints, run_runner, api, tmp_path):
    """After a move the path is empty. A file that turns up there later, by some other means, is a different file."""
    job = seed.job("DEV-LOAD")
    collect = seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    deliver = seed.step(job, 2, Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    run_runner("DEV-LOAD", "88421")

    (tmp_path / "work" / "DEV-LOAD" / "incoming" / FILE_1).write_text("put here by hand")
    collect.IsActive = deliver.IsActive = False
    seed.step(job, 3, Source=f"incoming/{FILE_1}", Dest="reprocessed")
    run_runner("DEV-LOAD", "88500")

    by_hand = api.trace_of(instance_id="88500")
    original = api.trace_of(filename=FILE_1, endpoint="BILLING_INBOX")

    assert route(by_hand) == [f"DEV-LOAD COPY incoming/{FILE_1} -> reprocessed/{FILE_1}"]
    assert len(original["hops"]) == 2
    assert {hop["instance_id"] for hop in original["hops"]} == {"88421"}


def test_trace_shows_where_a_file_stopped(seed, endpoints, run_runner, api):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", CreateFolder="False")

    assert run_runner("DEV-LOAD", "88421").returncode == 1

    [failed] = api.operations(status="failed")
    trace = api.trace(failed["id"])
    collect, deliver = trace["hops"]
    assert route(trace) == [
        f"DEV-LOAD COPY LEGAL_EXTRACTS/{FILE_1} -> incoming/{FILE_1}",
        f"DEV-LOAD COPY incoming/{FILE_1} -> BILLING_INBOX/{FILE_1}",
    ]
    assert (collect["status"], deliver["status"]) == ("SUCCESS", "FAILED")
    assert "No such file or directory" in deliver["error"]
    assert deliver["dest"]["size"] is None


def test_a_failed_delivery_is_not_treated_as_having_arrived(seed, endpoints, run_runner, api, tmp_path):
    """Nothing reached the inbox, so a file picked up from it later did not come from the failed attempt."""
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", CreateFolder="False")
    pickup = seed.job("DEV-BILLING-LOAD")
    seed.step(pickup, 1, SourceEndpoint="BILLING_INBOX", Dest="to_load")
    assert run_runner("DEV-LOAD", "88421").returncode == 1

    (tmp_path / "app_inbox").mkdir()
    (tmp_path / "app_inbox" / FILE_1).write_text("put here by hand")
    run_runner("DEV-BILLING-LOAD", "88430")

    trace = api.trace_of(job_key="DEV-BILLING-LOAD")
    [failed] = api.operations(status="FAILED")
    trace_of_failure = api.trace(failed["id"])

    assert route(trace) == [f"DEV-BILLING-LOAD COPY BILLING_INBOX/{FILE_1} -> to_load/{FILE_1}"]
    assert {hop["job_key"] for hop in trace_of_failure["hops"]} == {"DEV-LOAD"}


def test_a_failed_overwrite_does_not_hide_the_file_that_is_still_there(seed, endpoints, run_runner, api, tmp_path):
    """A second collect fails to replace the file, so what is delivered afterwards is the first collect's file."""
    job = seed.job("DEV-LOAD")
    collect = seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    run_runner("DEV-LOAD", "88421")

    collected = tmp_path / "work" / "DEV-LOAD" / "incoming" / FILE_1
    collected.chmod(0o444)                                  # read-only: the next copy onto it fails
    assert run_runner("DEV-LOAD", "88422").returncode == 1
    collected.chmod(0o644)

    collect.IsActive = False
    seed.step(job, 2, Source=f"incoming/{FILE_1}", DestEndpoint="BILLING_INBOX")
    run_runner("DEV-LOAD", "88423")

    trace = api.trace_of(endpoint="BILLING_INBOX")

    assert [(hop["instance_id"], hop["status"]) for hop in trace["hops"]] == [
        ("88421", "SUCCESS"), ("88423", "SUCCESS")]


def test_trace_of_an_unknown_operation_is_404(client):
    response = client.get("/api/v1/operations/12345/trace")

    assert response.status_code == 404
    assert "12345" in response.json()["detail"]


def test_filenames_that_differ_only_by_case_are_different_files(seed, endpoints, outbox, run_runner, api):
    """On Linux 'Report.csv' and 'report.csv' are two files. The database must not treat them as one."""
    (outbox / "Legal_Batch_A.csv").write_text("upper")
    (outbox / "Legal_Batch_a.csv").write_text("lower, and longer")
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, Source="incoming/Legal_Batch_[Aa].csv", DestEndpoint="BILLING_INBOX", Move="True")
    assert run_runner("DEV-LOAD", "88421").returncode == 0

    [delivered_upper] = [op for op in api.operations(endpoint="BILLING_INBOX")
                         if op["source"]["filename"] == "Legal_Batch_A.csv"]
    trace = api.trace(delivered_upper["id"])

    assert [hop["dest"]["filename"] for hop in trace["hops"]] == ["Legal_Batch_A.csv", "Legal_Batch_A.csv"]
    assert [hop["dest"]["size"] for hop in trace["hops"]] == [5, 5]


def test_trace_order_does_not_depend_on_the_order_spool_files_were_loaded(
        collect_and_deliver, seed, run_runner, client, db, tmp_path):
    """A spool file can arrive late. The trace must go by when things happened, not when they were loaded."""
    from app.telemetry_ingest import ingest_records
    from engine.spool_delivery import read_spool_file

    load = seed.job("DEV-BILLING-LOAD")
    seed.step(load, 1, SourceEndpoint="BILLING_INBOX", Dest="to_load", Move="True")
    run_runner("DEV-COLLECT", "88421")
    run_runner("DEV-BILLING-LOAD", "88430")

    first, second = sorted((tmp_path / "spool").glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    ingest_records(db, read_spool_file(second))         # the later run's spool file is loaded first
    ingest_records(db, read_spool_file(first))
    db.commit()

    [picked_up] = client.get("/api/v1/operations", params={"job_key": "DEV-BILLING-LOAD", "filename": FILE_1}).json()
    trace = client.get(f"/api/v1/operations/{picked_up['id']}/trace").json()

    assert [hop["instance_id"] for hop in trace["hops"]] == ["88421", "88421", "88421", "88430"]

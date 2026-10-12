"""
Runner: launched as a separate process, the way a scheduler would launch it,
against a throwaway database. Checks the exit code, the files and the spool.

Layout used by these tests, all inside pytest's temp folder:
    app_outbox/              an application's folder, registered as Endpoint LEGAL_EXTRACTS
    app_inbox/               another application's folder, registered as Endpoint BILLING_INBOX
    work/<JobKey>/           the job's working folder

The run_runner, outbox and endpoints fixtures are in conftest.py.
"""


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def test_job_moves_files_from_one_endpoint_to_another_through_the_working_folder(
        seed, run_runner, endpoints, outbox, tmp_path, spool_records):
    source, dest = endpoints
    job = seed.job("DEV-LOAD")
    # Seeded out of order on purpose: steps must run by StepOrder.
    seed.step(job, 3, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Archive", Source="incoming/*.csv", Dest="archive/${SYS:INSTANCE_ID}")

    result = run_runner(job.JobKey, instance_id="RUN_001")

    work = tmp_path / "work" / "DEV-LOAD"
    batch = ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]
    assert result.returncode == 0, result.stderr
    assert names(outbox) == batch + ["other.txt"]            # collected by copy; source untouched
    assert names(work / "archive" / "RUN_001") == batch
    assert names(work / "incoming") == []                    # moved on by the last step
    assert names(tmp_path / "app_inbox") == batch

    records = spool_records(tmp_path / "spool")
    start, *operations, end = records
    assert (start["Record"], start["JobKey"], start["InstanceID"]) == ("RUN_START", "DEV-LOAD", "RUN_001")
    assert (end["Record"], end["Status"], end["Error"]) == ("RUN_END", "SUCCESS", None)
    # One record per file per step: two files through three steps
    assert [(r["StepOrder"], r["OpType"], r["SourceFilename"]) for r in operations] == [
        (1, "COPY", "Legal_Batch_1.csv"), (1, "COPY", "Legal_Batch_2.csv"),
        (2, "COPY", "Legal_Batch_1.csv"), (2, "COPY", "Legal_Batch_2.csv"),
        (3, "MOVE", "Legal_Batch_1.csv"), (3, "MOVE", "Legal_Batch_2.csv"),
    ]
    assert {r["Status"] for r in operations} == {"SUCCESS"}
    assert [(r["SourceEndpointID"], r["DestEndpointID"]) for r in operations[::2]] == [
        (source.id, None),      # Collect: from a registered endpoint into the working folder
        (None, None),           # Archive: a hop inside the working folder
        (None, dest.id),        # Deliver: out of the working folder to a registered endpoint
    ]


def test_run_number_and_scheduler_name_are_recorded(seed, run_runner, endpoints, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")

    result = run_runner(job.JobKey, "00A1B", "--run-number", "3", "--scheduler", "CTM_PROD")

    assert result.returncode == 0, result.stderr
    start = spool_records(tmp_path / "spool")[0]
    assert (start["InstanceID"], start["RunNumber"], start["Scheduler"]) == ("00A1B", 3, "CTM_PROD")


def test_run_number_defaults_to_one_and_scheduler_to_none(seed, run_runner, endpoints, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")

    run_runner(job.JobKey)

    start = spool_records(tmp_path / "spool")[0]
    assert (start["RunNumber"], start["Scheduler"]) == (1, None)


def test_disabled_job_does_not_run(seed, run_runner, endpoints, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    job.IsActive = False
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert "disabled" in result.stderr
    assert not (tmp_path / "work").exists()
    end = spool_records(tmp_path / "spool")[-1]
    assert (end["Status"], end["Error"]) == ("FAILED", "Job 'DEV-LOAD' is disabled.")


def test_disabled_step_is_skipped(seed, run_runner, endpoints, tmp_path):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, Source="incoming/*.csv", DestEndpoint="BILLING_INBOX").IsActive = False

    result = run_runner(job.JobKey)

    assert result.returncode == 0, result.stderr
    assert names(tmp_path / "work" / "DEV-LOAD" / "incoming") == ["Legal_Batch_1.csv", "Legal_Batch_2.csv"]
    assert not (tmp_path / "app_inbox").exists()


def test_raw_path_outside_the_working_folder_fails_the_job(seed, run_runner, outbox, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, Source=str(outbox / "*.csv"), Dest="incoming")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert "outside the job's working folder" in result.stderr
    assert "SourceEndpoint" in result.stderr
    assert not (tmp_path / "work" / "DEV-LOAD" / "incoming").exists()
    assert spool_records(tmp_path / "spool")[-1]["Status"] == "FAILED"


def test_unresolved_placeholder_fails_the_job_before_touching_files(seed, run_runner, endpoints, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="${NoSuchFolder}/out")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert "${NoSuchFolder}" in result.stderr
    assert names(tmp_path / "work" / "DEV-LOAD") == []
    start, end = spool_records(tmp_path / "spool")      # no file was touched, but the run is on record
    assert (start["Record"], end["Record"], end["Status"]) == ("RUN_START", "RUN_END", "FAILED")
    assert "${NoSuchFolder}" in end["Error"]


def test_failing_step_stops_the_job(seed, run_runner, endpoints, tmp_path, spool_records):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="missing", CreateFolder="False")
    seed.step(job, 2, SourceEndpoint="LEGAL_EXTRACTS", DestEndpoint="BILLING_INBOX")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert not (tmp_path / "app_inbox").exists()
    assert spool_records(tmp_path / "spool")[-1]["Status"] == "FAILED"


def test_unknown_step_type_fails_the_job(seed, run_runner):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, code="SQL_EXEC", Query="SELECT 1")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert "SQL_EXEC" in result.stderr


def test_only_the_job_whose_key_is_passed_runs(seed, run_runner, endpoints, tmp_path):
    for key in ("DEV-LOAD-A", "DEV-LOAD-B"):
        seed.step(seed.job(key), 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")

    result = run_runner("DEV-LOAD-B")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "work" / "DEV-LOAD-B" / "incoming").exists()
    assert not (tmp_path / "work" / "DEV-LOAD-A").exists()


def test_unknown_job_fails(seed, run_runner, tmp_path, spool_records):
    seed.job("DEV-LOAD")

    result = run_runner("NO_SUCH_JOB")

    assert result.returncode == 1
    assert "NO_SUCH_JOB" in result.stderr
    start, end = spool_records(tmp_path / "spool")
    assert start["JobKey"] == "NO_SUCH_JOB"
    assert end["Status"] == "FAILED"


def test_job_with_no_steps_fails(seed, run_runner):
    job = seed.job("DEV-LOAD")

    result = run_runner(job.JobKey)

    assert result.returncode == 1
    assert "no active steps" in result.stderr

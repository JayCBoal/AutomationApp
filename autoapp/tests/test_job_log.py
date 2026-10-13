"""
The job log: what the runner prints for the scheduler to capture.

Each test runs a real job as a separate process and reads its stdout and stderr.
"""
import pytest

from app.models import Variable


@pytest.fixture
def job(seed, endpoints):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Deliver", Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    return job


def lines_about(output, text):
    return [line for line in output.splitlines() if text in line]


def test_default_level_logs_parameters_and_every_file(job, run_runner, outbox, tmp_path):
    result = run_runner("DEV-LOAD", "88421")

    out = result.stdout
    incoming = tmp_path / "work" / "DEV-LOAD" / "incoming"
    assert result.stderr == ""
    assert "[INFO] Job 'DEV-LOAD', instance 88421, run number 1" in out
    assert "[INFO] BEGIN Step 1: Collect (COPY_FILES)" in out
    # each parameter as written in the job, and what it resolved to
    assert f"SourceEndpoint: LEGAL_EXTRACTS  (resolved: {outbox}/Legal_Batch_*.csv)" in out
    assert f"Dest: incoming  (resolved: {incoming})" in out
    assert lines_about(out, "Move:")[0].endswith("    Move: True")       # nothing to resolve: shown once
    # every file handled
    assert f"[INFO] Copied '{outbox}/Legal_Batch_1.csv'\n\tto '{incoming}/Legal_Batch_1.csv' (4 bytes)" in out
    assert f"[INFO] Moved '{incoming}/Legal_Batch_2.csv'\n\tto '{tmp_path}/app_inbox/Legal_Batch_2.csv' (4 bytes)" in out
    assert len(lines_about(out, "Copied '")) == 2 and len(lines_about(out, "Moved '")) == 2
    # what each step came to
    assert "END Step 1: Collect (COPY_FILES): SUCCESS. Copied 2 file(s), 8 bytes." in out
    assert "END Step 2: Deliver (COPY_FILES): SUCCESS. Moved 2 file(s), 8 bytes." in out
    assert "[INFO] Job 'DEV-LOAD' completed successfully." in out


def test_summary_level_logs_one_line_per_step(job, run_runner):
    result = run_runner("DEV-LOAD", "88421", "--log-level", "SUMMARY")

    out = result.stdout
    assert [line.split("] ", 1)[1] for line in out.splitlines()] == [
        "Job 'DEV-LOAD', instance 88421, run number 1",
        lines_about(out, "END Step 1")[0].split("] ", 1)[1],
        lines_about(out, "END Step 2")[0].split("] ", 1)[1],
        "Job 'DEV-LOAD' completed successfully.",
    ]
    assert "Copied 2 file(s), 8 bytes." in lines_about(out, "END Step 1")[0]


def test_silent_level_logs_nothing_when_the_job_succeeds(job, run_runner):
    result = run_runner("DEV-LOAD", "88421", "--log-level", "silent")      # any case

    assert result.returncode == 0
    assert (result.stdout, result.stderr) == ("", "")


def test_silent_level_still_logs_errors(seed, endpoints, run_runner):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="missing", CreateFolder="False")

    result = run_runner("DEV-LOAD", "88421", "--log-level", "SILENT")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "[ERROR] Could not copy" in result.stderr            # which file
    assert "[ERROR] END Step 1: Collect (COPY_FILES): FAILED" in result.stderr
    assert "[ERROR] Job 'DEV-LOAD' failed:" in result.stderr


def test_errors_go_to_stderr_and_the_rest_to_stdout(seed, endpoints, run_runner):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, title="Deliver", Source="incoming/*.csv", Dest="missing", CreateFolder="False")

    result = run_runner("DEV-LOAD", "88421")

    assert "END Step 1: Collect (COPY_FILES): SUCCESS" in result.stdout
    assert "[ERROR]" not in result.stdout
    assert "BEGIN Step 2" in result.stdout
    assert all("[ERROR]" in line for line in result.stderr.splitlines() if line.startswith("20"))
    assert "Job 'DEV-LOAD' failed" in result.stderr


def test_debug_level_adds_troubleshooting_detail(job, run_runner, tmp_path):
    default = run_runner("DEV-LOAD", "88421").stdout
    (tmp_path / "work").rename(tmp_path / "work_first_run")
    debug = run_runner("DEV-LOAD", "88422", "--log-level", "DEBUG").stdout

    assert "[DEBUG]" not in default
    assert f"[DEBUG] Working folder: {tmp_path / 'work' / 'DEV-LOAD'}" in debug
    assert "[DEBUG] Files matching" in debug
    assert "BEGIN Step 1" in debug and "Copied '" in debug        # and everything DETAIL shows


def test_a_step_that_matches_nothing_fails_and_says_how_to_allow_it(seed, endpoints, run_runner, spool_records, tmp_path):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", Source="incoming/*.xml", DestEndpoint="BILLING_INBOX")

    result = run_runner("DEV-LOAD", "88421")

    assert result.returncode == 1
    assert "[ERROR] END Step 1: Collect (COPY_FILES): FAILED" in result.stderr
    assert "[ERROR] Job 'DEV-LOAD' failed: No files matched '" in result.stderr
    assert "incoming/*.xml'. If that is acceptable for this step, set AllowNoFiles to True." in result.stderr
    # the run record carries the reason, so the question "did the job even look?" has an answer
    end = spool_records(tmp_path / "spool")[-1]
    assert (end["Status"], "incoming/*.xml" in end["Error"]) == ("FAILED", True)


def test_an_allowed_no_match_is_a_warning(seed, endpoints, run_runner):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", Source="incoming/*.xml", DestEndpoint="BILLING_INBOX", AllowNoFiles="True")

    detail = run_runner("DEV-LOAD", "88421")
    summary = run_runner("DEV-LOAD", "88422", "--log-level", "SUMMARY")
    silent = run_runner("DEV-LOAD", "88423", "--log-level", "SILENT")

    for result in (detail, summary):
        assert result.returncode == 0
        assert "[WARN] No files matched '" in result.stdout
        assert "incoming/*.xml'" in result.stdout
        assert "SUCCESS. No files matched; nothing was done." in result.stdout
    assert (silent.stdout, silent.stderr) == ("", "")


def test_a_step_can_be_quieter_than_the_job(job, seed, run_runner):
    seed.step(job, 3, title="Quiet", Source="incoming/*.csv", Dest="unused", LogLevel="SILENT", AllowNoFiles="True")

    result = run_runner("DEV-LOAD", "88421")

    assert result.returncode == 0, result.stderr
    assert "BEGIN Step 2" in result.stdout
    assert lines_about(result.stdout, "Step 3") == []
    assert "LogLevel" not in result.stdout
    assert "Job 'DEV-LOAD' completed successfully." in result.stdout     # the job's own level is back


def test_a_step_can_be_more_detailed_than_the_job(job, seed, run_runner):
    job.steps[0].parameters.append(_param("LogLevel", "detail"))

    result = run_runner("DEV-LOAD", "88421", "--log-level", "SILENT")

    assert "BEGIN Step 1" in result.stdout and len(lines_about(result.stdout, "Copied '")) == 2
    assert "LogLevel" not in result.stdout          # it steers the log; it is not one of the step's own parameters
    assert lines_about(result.stdout, "Step 2") == []
    assert "completed successfully" not in result.stdout


def test_an_unknown_step_log_level_fails_the_job_and_names_the_step(job, run_runner):
    job.steps[1].parameters.append(_param("LogLevel", "CHATTY"))

    result = run_runner("DEV-LOAD", "88421")

    assert result.returncode == 1
    assert ("Step 2 ('Deliver'): 'LogLevel' must be one of DEBUG, DETAIL, SUMMARY, SILENT, not 'CHATTY'."
            in result.stderr)


def test_an_unknown_runner_log_level_is_refused(job, run_runner):
    result = run_runner("DEV-LOAD", "88421", "--log-level", "CHATTY")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_secret_variable_values_never_reach_the_log(db, seed, endpoints, run_runner, tmp_path):
    job = seed.job("DEV-LOAD")
    db.add(Variable(MasterObject_id=job.MasterObject_id, VarName="Token", VarValue="s3cr3t-t0ken", IsSecret=True))
    seed.set_vars(job, Batch="plain-value")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="in_${Token}_${Batch}")

    result = run_runner("DEV-LOAD", "88421", "--log-level", "DEBUG")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "work" / "DEV-LOAD" / "in_s3cr3t-t0ken_plain-value").is_dir()    # the real value was used
    assert "s3cr3t-t0ken" not in result.stdout + result.stderr
    assert "in_********_plain-value" in result.stdout


def test_secret_values_are_masked_in_error_messages_too(db, seed, endpoints, run_runner):
    job = seed.job("DEV-LOAD")
    db.add(Variable(MasterObject_id=job.MasterObject_id, VarName="Token", VarValue="s3cr3t-t0ken", IsSecret=True))
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="in_${Token}/x", CreateFolder="False")

    result = run_runner("DEV-LOAD", "88421")

    assert result.returncode == 1
    assert "s3cr3t-t0ken" not in result.stdout + result.stderr
    assert "in_********" in result.stderr


def _param(name, value):
    from app.models import JobStepParameter
    return JobStepParameter(ParamName=name, ParamValue=value)

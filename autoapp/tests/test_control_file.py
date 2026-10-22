"""
The control file and picking up a run (docs/WORKFLOWS_PHASE7.md, proposals 1 to 4): what a job keeps as it
goes, and a later attempt that resumes from it. Jobs run as a scheduler would run them, as a separate
process, with the layout of test_runner.py; each step that must fail does so on a gate file that is missing
until the test puts it there.
"""
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from app.log_agent import LocalAgent
from app.models import JobRun, Variable
from conftest import AUTOAPP_DIR, subprocess_env
from engine import job_log
from engine.control_file import ControlRecord, ControlWriter, control_name


@pytest.fixture
def attempt(db, db_url, tmp_path, load_spool):
    """Runs a job, naming its run, and loads what it left into the database so a later run can find it."""
    def _attempt(job_key, *extra, run_id=None):
        run_id = run_id or str(uuid.uuid4())
        db.commit()
        done = subprocess.run(
            [sys.executable, "-m", "engine.runner", "--job-key", job_key, "--instance-id", "RES-1",
             "--spool-dir", str(tmp_path / "spool"), "--working-root", str(tmp_path / "work"),
             "--run-id", run_id, *extra],
            cwd=AUTOAPP_DIR, env=subprocess_env(db_url), capture_output=True, text=True)
        load_spool()
        return run_id, done
    return _attempt


def operations(tmp_path, run_id):
    """What a run did, from its spool file, which loading it into the database moved to 'delivered'."""
    records = [json.loads(line) for spool in (tmp_path / "spool").rglob("*.jsonl") for line in spool.read_text().splitlines()]
    return [r for r in records if r["Record"] == "OPERATION" and r["RunID"] == run_id]


def log_of(tmp_path, run_id) -> str:
    return next((tmp_path / "logs").rglob(f"{run_id}.log")).read_text()


def control_of(tmp_path, run_id) -> ControlRecord:
    return ControlRecord.read(next((tmp_path / "logs").rglob(f"{run_id}.control")))


def put_gate(tmp_path, *names, job="RES"):
    """The files the gate steps wait for."""
    gate = tmp_path / "work" / job / "gate"
    gate.mkdir(parents=True, exist_ok=True)
    for name in names:
        (gate / name).write_text("ok")


def gated_job(seed, gates=("a",), name="RES"):
    """Collect, then one gate step per name (it fails until its file is there), then Report."""
    job = seed.job(name)
    seed.step(job, 1, title="Collect", name="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    for order, gate in enumerate(gates, start=2):
        seed.step(job, order, title=f"Gate {gate}", Source=f"gate/{gate}.ok", Dest="passed")
    seed.step(job, len(gates) + 2, "SIMULATE", title="Report", Messages="Collected %{Collect.FileCount} files")
    return job


# ---------- Picking up a job ----------

def test_a_resumed_job_does_not_run_again_what_finished_and_still_knows_its_outputs(
        seed, endpoints, attempt, tmp_path):
    gated_job(seed)
    first, failed = attempt("RES")
    assert failed.returncode == 1
    put_gate(tmp_path, "a.ok")

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 0, resumed.stderr
    assert not [op for op in operations(tmp_path, second) if op["StepNumber"] == "1"]
    log = log_of(tmp_path, second)
    assert "Step 1: Collect (COPY_FILES): finished in the earlier attempt" in log
    assert "Collected 2 files" in log                   # %{Collect.FileCount}, from the earlier attempt's record


def test_a_third_attempt_picks_up_both_earlier_ones(seed, endpoints, attempt, tmp_path):
    gated_job(seed, gates=("a", "b"))
    first, _ = attempt("RES")
    put_gate(tmp_path, "a.ok")
    second, again = attempt("RES", "--resume-run-id", first)
    assert again.returncode == 1                        # now it fails at gate b
    put_gate(tmp_path, "b.ok")

    third, done = attempt("RES", "--resume-run-id", second)

    assert done.returncode == 0, done.stderr
    assert {op["StepNumber"] for op in operations(tmp_path, third)} == {"3", "4"}
    assert "Gate a (COPY_FILES): finished in the earlier attempt" in log_of(tmp_path, third)


def test_a_failed_step_is_recorded_with_what_it_knew(seed, endpoints, attempt, tmp_path):
    gated_job(seed)
    first, _ = attempt("RES")

    failure = control_of(tmp_path, first).failure("2|")

    assert (failure["knew"], failure["stopped"], failure["operator_decides"]) == ("PARTLY_DONE", False, False)


def test_a_resumed_job_keeps_the_first_attempts_business_date(seed, endpoints, attempt, tmp_path):
    gated_job(seed, gates=("a", "b"))
    first, _ = attempt("RES", "--business-date", "2026-03-31")
    put_gate(tmp_path, "a.ok")

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 1                      # stops at gate b, so its file is kept
    assert control_of(tmp_path, second).business_date.isoformat() == "2026-03-31"


# ---------- Flow control ----------

def test_an_if_keeps_the_branch_it_took(seed, db, endpoints, attempt, tmp_path):
    job = seed.job("RES", Mode="A")
    choice = seed.step(job, 1, "IF", title="Which way", Condition="${Mode} = 'A'")
    then = seed.step(job, 1, "THEN", parent=choice)
    seed.step(job, 1, parent=then, title="Gate", Source="gate/a.ok", Dest="passed")
    otherwise = seed.step(job, 2, "ELSE", parent=choice)
    seed.step(job, 1, "SIMULATE", parent=otherwise, title="Other way", Messages="took the Else")
    first, failed = attempt("RES")
    assert failed.returncode == 1
    db.query(Variable).filter(Variable.VarName == "Mode").one().VarValue = "B"      # the condition would now say Else
    put_gate(tmp_path, "a.ok")

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 0, resumed.stderr
    log = log_of(tmp_path, second)
    assert "The earlier attempt took the Then branch" in log and "took the Else" not in log


def loop_job(seed, kind="FOR_EACH_FILE"):
    job = seed.job("RES")
    if kind == "FOR_EACH_FILE":
        loop = seed.step(job, 1, kind, title="Each", name="Each", SourceEndpoint="LEGAL_EXTRACTS")
        seed.step(job, 1, parent=loop, title="Copy one", Source="%{File.FullName}", Dest="per_file")
        seed.step(job, 2, parent=loop, title="Gate", Source="gate/%{File.BaseName}.ok", Dest="passed")
    return job


def test_a_for_each_file_goes_on_from_the_pass_that_failed_with_the_files_it_matched_then(
        seed, endpoints, outbox, attempt, tmp_path):
    loop_job(seed)
    put_gate(tmp_path, "Legal_Batch_1.ok")                  # pass 1 gets through its gate; pass 2 does not
    first, failed = attempt("RES")
    assert failed.returncode == 1
    put_gate(tmp_path, "Legal_Batch_2.ok")
    (outbox / "Legal_Batch_3.csv").write_text("id\n3")      # arrived since: not part of this run

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 0, resumed.stderr
    # Pass 1 is not done again, nor pass 2's copy, which finished; only its gate, and batch 3 is not in the run
    assert {(op["StepNumber"], op["SourceFilename"]) for op in operations(tmp_path, second)} == {
        ("1.2", "Legal_Batch_2.ok")}
    assert "Legal_Batch_3" not in log_of(tmp_path, second)


def test_a_while_goes_on_from_its_pass_count(seed, endpoints, attempt, tmp_path):
    job = seed.job("RES")
    loop = seed.step(job, 1, "WHILE", title="Loop", name="Loop", Condition="%{Loop.Passes} < 3", MaxIterations="10")
    seed.step(job, 1, parent=loop, title="Gate", Source="gate/pass%{Loop.Passes}.ok", Dest="passed")
    seed.step(job, 2, "SIMULATE", title="Report", Messages="Passes: %{Loop.Passes}")
    put_gate(tmp_path, "pass1.ok")
    first, failed = attempt("RES")
    assert failed.returncode == 1
    put_gate(tmp_path, "pass2.ok", "pass3.ok")

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 0, resumed.stderr
    log = log_of(tmp_path, second)
    assert "Passes: 3" in log
    assert not [op for op in operations(tmp_path, second) if op["Iteration"] == "1"]      # pass 1 is not done again


# ---------- A file step ----------

def test_a_file_step_skips_the_files_already_done_and_counts_them(seed, endpoints, outbox, attempt, tmp_path):
    (outbox / "Legal_Batch_3.csv").write_text("id\n3")
    job = seed.job("RES")
    seed.step(job, 1, title="Collect", name="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, "SIMULATE", title="Report", Messages="Collected %{Collect.FileCount} files")
    locked = outbox / "Legal_Batch_2.csv"
    locked.chmod(0)                                         # the second file cannot be read
    first, failed = attempt("RES")
    assert failed.returncode == 1
    locked.chmod(0o644)

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 0, resumed.stderr
    assert [op["SourceFilename"] for op in operations(tmp_path, second) if op["OpType"] == "COPY"] == [
        "Legal_Batch_2.csv", "Legal_Batch_3.csv"]
    assert "Collected 3 files" in log_of(tmp_path, second)


def test_a_file_that_arrived_complete_before_the_stop_is_not_copied_again(seed, endpoints, attempt, tmp_path):
    gated_job(seed)
    first, _ = attempt("RES")
    # As if the runner was killed after the copy but before it noted the file done
    path = next((tmp_path / "logs").rglob(f"{first}.control"))
    kept = [line for line in path.read_text().splitlines() if '"e": "file_end"' not in line
            and '"e": "end"' not in line and '"e": "pass_end"' not in line and '"e": "failed"' not in line]
    path.write_text("\n".join(kept) + "\n")
    put_gate(tmp_path, "a.ok")

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 0, resumed.stderr
    assert [op for op in operations(tmp_path, second) if op["StepNumber"] == "1"] == []     # both files were there, whole
    assert "had arrived complete when the earlier attempt stopped" in log_of(tmp_path, second)


def test_an_unzip_takes_out_only_the_files_the_earlier_attempt_did_not(seed, endpoints, attempt, tmp_path):
    import zipfile
    work = tmp_path / "work" / "RES"
    work.mkdir(parents=True)
    with zipfile.ZipFile(work / "pack.zip", "w") as pack:
        for name in ("a.txt", "sub/b.txt", "c.txt"):
            pack.writestr(name, f"{name} contents")
    job = seed.job("RES")
    seed.step(job, 1, "UNZIP_FILES", title="Open", name="Open", Source="pack.zip", Dest="out")
    seed.step(job, 2, "SIMULATE", title="Report", Messages="Took out %{Open.FileCount}")
    (work / "out").mkdir()
    (work / "out" / "sub").write_text("in the way")        # the second file's folder cannot be made
    first, failed = attempt("RES")
    assert failed.returncode == 1
    (work / "out" / "sub").unlink()

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 0, resumed.stderr
    assert [op["DestFilename"] for op in operations(tmp_path, second) if op["OpType"] == "UNZIP"] == ["b.txt", "c.txt"]
    assert "Took out 3" in log_of(tmp_path, second)


# ---------- A run that is stopped ----------

def test_a_killed_job_leaves_its_record_right_and_says_what_the_step_knew(seed, endpoints, db, db_url, tmp_path):
    job = seed.job("RES")
    seed.step(job, 1, title="Collect", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(job, 2, "SIMULATE", title="Slow", WaitSeconds="60")
    db.commit()
    run_id = str(uuid.uuid4())
    runner = subprocess.Popen(
        [sys.executable, "-m", "engine.runner", "--job-key", "RES", "--instance-id", "RES-K",
         "--spool-dir", str(tmp_path / "spool"), "--working-root", str(tmp_path / "work"), "--run-id", run_id],
        cwd=AUTOAPP_DIR, env=subprocess_env(db_url), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 30
        while time.time() < deadline and '"key": "2|"' not in "".join(
                p.read_text() for p in (tmp_path / "logs").rglob("*.control")):
            time.sleep(0.2)
        runner.send_signal(signal.SIGTERM)
        runner.wait(timeout=30)
    finally:
        runner.kill()

    record = control_of(tmp_path, run_id)
    assert record.finished("1|") is not None
    failure = record.failure("2|")
    assert (failure["knew"], failure["stopped"]) == ("NOT_DONE", True)


def test_a_record_cut_short_by_a_hard_kill_is_still_read(tmp_path):
    path = tmp_path / "x.control"
    writer = ControlWriter(path)
    writer.write("begin", key="1|", name=None)
    writer.write("end", key="1|", name="A", done=True, signal="CONTINUE", outputs={"FileCount": 2}, return_code=None)
    writer.close()
    with open(path, "a") as f:
        f.write('{"e": "begin", "key": "2|", "na')           # the runner died in the middle of a line

    record = ControlRecord.read(path)

    assert record.finished("1|")["outputs"] == {"FileCount": 2}
    assert record.finished("2|") is None


def test_a_secret_never_reaches_the_control_file(tmp_path):
    job_log.configure("DETAIL", secrets=["s3cret-value"])
    path = tmp_path / "x.control"
    writer = ControlWriter(path)
    writer.write("end", key="1|", name="A", done=True, outputs={"ErrorMessage": "refused for s3cret-value"})
    writer.close()
    job_log.configure("DETAIL", secrets=[])

    assert "s3cret-value" not in path.read_text() and "********" in path.read_text()


# ---------- Where it lives, and when it cannot be used ----------

def test_the_control_file_is_removed_with_the_log(tmp_path):
    agent = LocalAgent("somehost")
    log_file = "2026-10-20/abc.log"
    (agent.folder / "2026-10-20").mkdir(parents=True)
    (agent.folder / log_file).write_text("log")
    (agent.folder / control_name(log_file)).write_text("{}")

    agent.remove(log_file)

    assert not (agent.folder / "2026-10-20").exists()


def test_a_run_whose_record_is_gone_says_so_in_plain_words(seed, endpoints, attempt, tmp_path):
    gated_job(seed)
    first, _ = attempt("RES")
    next((tmp_path / "logs").rglob(f"{first}.control")).unlink()

    _, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 1
    assert "is not there; it is removed with the job log. Restart the job from the beginning." in resumed.stdout + resumed.stderr


def test_a_run_from_another_host_cannot_be_picked_up_here(seed, db, endpoints, attempt, tmp_path):
    gated_job(seed)
    first, _ = attempt("RES")
    db.query(JobRun).filter(JobRun.RunID == first).one().Host = "some-other-host"

    _, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 1
    assert "ran on host 'some-other-host'" in resumed.stdout + resumed.stderr


def test_a_run_nobody_knows_cannot_be_picked_up(seed, endpoints, attempt):
    gated_job(seed)

    _, resumed = attempt("RES", "--resume-run-id", str(uuid.uuid4()))

    assert resumed.returncode == 1
    assert "is not known" in resumed.stdout + resumed.stderr

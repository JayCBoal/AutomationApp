"""
The control file's life (docs/WORKFLOWS_PHASE7.md, step 5-1): it goes when the run Succeeded and no Reaction changed
that, with the file of the attempt it picked up. A failed, killed or Reaction-overridden run keeps its file. The job
log says how an attempt started.
"""
import json

import pytest

from core.control_file import ControlRecord
from test_control_file import attempt, control_of, gated_job, log_of, put_gate        # noqa: F401 (attempt is a fixture)
from test_launches import get    # noqa: F401
from test_workflow_reactions import react
from test_workflow_reopen import run_workflow
from test_workflow_resume_values_api import plan_of
from test_workflow_runner import flow, sim, start    # noqa: F401  (fixtures)


def control_files(tmp_path, run_id):
    return list((tmp_path / "logs").rglob(f"{run_id}.control"))


def test_a_clean_success_removes_the_control_file(seed, endpoints, attempt, tmp_path):
    gated_job(seed)
    put_gate(tmp_path, "a.ok")

    first, done = attempt("RES")

    assert done.returncode == 0, done.stderr
    assert control_files(tmp_path, first) == []
    assert log_of(tmp_path, first)                              # the log stays


def test_a_failed_run_keeps_its_control_file(seed, endpoints, attempt, tmp_path):
    gated_job(seed)

    first, failed = attempt("RES")

    assert failed.returncode == 1 and len(control_files(tmp_path, first)) == 1


def test_a_resumed_success_removes_its_own_file_and_the_one_it_picked_up(seed, endpoints, attempt, tmp_path):
    gated_job(seed)
    first, _ = attempt("RES")
    put_gate(tmp_path, "a.ok")

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 0, resumed.stderr
    assert control_files(tmp_path, first) == [] and control_files(tmp_path, second) == []


def test_a_resume_that_fails_again_still_lets_the_next_resume_pick_up(seed, endpoints, attempt, tmp_path):
    gated_job(seed, gates=("a", "b"))
    first, _ = attempt("RES")
    put_gate(tmp_path, "a.ok")
    second, again = attempt("RES", "--resume-run-id", first)
    assert again.returncode == 1
    put_gate(tmp_path, "b.ok")

    third, done = attempt("RES", "--resume-run-id", second)

    assert done.returncode == 0, done.stderr
    assert [len(control_files(tmp_path, run)) for run in (first, second, third)] == [1, 0, 0]   # the first attempt's file stays: only the file picked up from goes


def test_a_restart_leaves_the_earlier_attempts_file(seed, endpoints, attempt, tmp_path):
    gated_job(seed)
    first, _ = attempt("RES")
    put_gate(tmp_path, "a.ok")

    second, restarted = attempt("RES", "--attempt", "2")

    assert restarted.returncode == 0, restarted.stderr
    assert len(control_files(tmp_path, first)) == 1 and control_files(tmp_path, second) == []
    assert "Restarted from the beginning (attempt 2); attempt 1 failed." in log_of(tmp_path, second)


def test_a_success_a_reaction_counts_as_failed_keeps_its_file(seed, endpoints, db, attempt, tmp_path):
    gated_job(seed)
    put_gate(tmp_path, "a.ok")
    react(db, db_job(db, "RES"), "SUCCESS", ("COUNT_AS_FAILED", {}))

    first, done = attempt("RES")

    assert done.returncode == 1
    assert len(control_files(tmp_path, first)) == 1


def test_a_failure_a_reaction_counts_as_succeeded_keeps_its_file(seed, endpoints, db, attempt, tmp_path):
    gated_job(seed)
    react(db, db_job(db, "RES"), "FAILED", ("COUNT_AS_SUCCEEDED", {}))

    first, done = attempt("RES")

    assert done.returncode == 0
    assert len(control_files(tmp_path, first)) == 1


def db_job(db, key):
    from core.models import Job
    return db.query(Job).filter(Job.JobKey == key).one()


# ---------- What the job log says ----------

def test_the_log_says_which_steps_had_finished_and_which_runs_again(seed, endpoints, attempt, tmp_path):
    gated_job(seed, gates=("a", "b"))
    first, _ = attempt("RES")
    put_gate(tmp_path, "a.ok")

    second, _ = attempt("RES", "--resume-run-id", first, "--attempt", "2")

    assert "Resumed from attempt 1: step 1 had finished; step 2 runs again." in log_of(tmp_path, second)


def test_the_log_says_when_every_step_had_finished(seed, endpoints, attempt, tmp_path):
    job = seed.job("RES")
    seed.step(job, 1, "SIMULATE", title="Report", Messages="done")
    seed.step(job, 2, "SIMULATE", title="Return", ReturnCode="9")
    first, failed = attempt("RES")
    assert failed.returncode == 1

    second, _ = attempt("RES", "--resume-run-id", first, "--attempt", "2")

    assert "Resumed from attempt 1: all steps had finished." in log_of(tmp_path, second)


# ---------- The known edge ----------

def test_a_job_a_workflow_reaction_counts_as_failed_has_no_record_to_resume_from(sim, flow, db, live_api):
    extract = sim("EXTRACT")
    flow("WF", [("Extract", extract)])
    react(db, extract, "SUCCESS", ("COUNT_AS_FAILED", {}))
    run = run_workflow(live_api, "WF", "UI-E1")
    assert run["status"] == "FAILED"

    plan = plan_of(live_api, run)

    assert "is not there" in plan["resume_problem"] and "Restart" in plan["resume_problem"]

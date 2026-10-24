"""
Advanced rerun of a job on its own (docs/WORKFLOWS_PHASE7.md, step 6d): start at a chosen top-level step, skip a step,
and the plan's list of steps. The engine is driven as a scheduler would run it (a separate process, as in
test_control_file.py); the API tests go through the plan and the request.
"""
import json

import pytest

from core.models import Variable
from test_control_file import attempt, control_of, gated_job, log_of, operations, put_gate     # noqa: F401 (attempt is a fixture)
from test_launches import follow, get, post
from test_rerun_advanced import plan_of, rerun     # noqa: F401
from test_reruns import gated, make_unknown, run_and_wait       # noqa: F401 (gated is a fixture)


def steps_run(tmp_path, run_id):
    return {op["StepNumber"] for op in operations(tmp_path, run_id)}


# ---------- The engine ----------

def test_starting_at_an_earlier_step_runs_it_and_every_step_after_it_again_though_they_finished(
        seed, endpoints, attempt, tmp_path):
    gated_job(seed, gates=("a", "b"))
    put_gate(tmp_path, "a.ok")
    first, failed = attempt("RES")
    assert failed.returncode == 1 and steps_run(tmp_path, first) >= {"1", "2"}      # Collect and Gate a finished
    put_gate(tmp_path, "b.ok")

    second, done = attempt("RES", "--resume-run-id", first, "--from-step", "1")

    assert done.returncode == 0, done.stderr
    assert {"1", "2", "3"} <= steps_run(tmp_path, second)
    log = log_of(tmp_path, second)
    assert "starting at step 1" in log and "finished in the earlier attempt" not in log


def test_starting_at_a_later_step_counts_the_steps_before_it_as_done_and_passes_over_the_one_that_failed(
        seed, endpoints, attempt, tmp_path):
    gated_job(seed, gates=("a", "b"))
    first, failed = attempt("RES")                      # fails at Gate a (step 2)
    assert failed.returncode == 1
    put_gate(tmp_path, "b.ok")

    second, done = attempt("RES", "--resume-run-id", first, "--from-step", "3")

    assert done.returncode == 0, done.stderr
    assert steps_run(tmp_path, second) == {"3", "4"}    # Collect was not done again; Gate a was passed over
    log = log_of(tmp_path, second)
    assert "Step 1: Collect (COPY_FILES): finished in the earlier attempt" in log
    assert "Step 2: Gate a (COPY_FILES): skipped, as the operator chose to start at step 3" in log
    assert "Collected 2 files" in log                   # the finished step's outputs came back


def test_a_block_is_one_unit_so_starting_at_it_asks_its_condition_again(seed, db, endpoints, attempt, tmp_path):
    job = seed.job("RES", Mode="A")
    choice = seed.step(job, 1, "IF", title="Which way", Condition="${Mode} = 'A'")
    then = seed.step(job, 1, "THEN", parent=choice)
    seed.step(job, 1, parent=then, title="Gate", Source="gate/a.ok", Dest="passed")
    otherwise = seed.step(job, 2, "ELSE", parent=choice)
    seed.step(job, 1, "SIMULATE", parent=otherwise, title="Other way", Messages="took the Else")
    first, failed = attempt("RES")
    assert failed.returncode == 1
    db.query(Variable).filter(Variable.VarName == "Mode").one().VarValue = "B"
    put_gate(tmp_path, "a.ok")

    second, done = attempt("RES", "--resume-run-id", first, "--from-step", "1", "--refresh-values")

    assert done.returncode == 0, done.stderr
    log = log_of(tmp_path, second)
    assert "The earlier attempt took the Then branch" not in log and "took the Else" in log


def test_a_skipped_step_is_not_run_and_reads_as_skipped(seed, endpoints, attempt, tmp_path):
    job = seed.job("RES")
    seed.step(job, 1, "SIMULATE", title="Prepare", Messages="prepared")
    seed.step(job, 2, title="Gate", name="Gate", Source="gate/a.ok", Dest="passed")
    seed.step(job, 3, "SIMULATE", title="Report", Messages="Gate was %{Gate.Status}, files %{Gate.FileCount}.")
    first, failed = attempt("RES")
    assert failed.returncode == 1

    second, done = attempt("RES", "--resume-run-id", first, "--skip-steps", json.dumps(["2"]))

    assert done.returncode == 0, done.stderr
    assert not steps_run(tmp_path, second) & {"1", "2"}
    log = log_of(tmp_path, second)
    assert "Step 2: Gate (COPY_FILES): skipped, as the operator chose to skip it" in log
    assert "Gate was SKIPPED, files ." in log


def test_a_skipped_step_stays_skipped_for_a_later_attempt_and_is_not_a_failure_to_decide_on(
        seed, endpoints, attempt, tmp_path):
    gated_job(seed, gates=("a", "b"))
    first, _ = attempt("RES")
    second, failed = attempt("RES", "--resume-run-id", first, "--skip-steps", json.dumps(["2"]))
    assert failed.returncode == 1                       # Gate b fails now
    assert control_of(tmp_path, second).open_failure()["step"] == "3"
    put_gate(tmp_path, "b.ok")

    third, done = attempt("RES", "--resume-run-id", second)

    assert done.returncode == 0, done.stderr
    assert steps_run(tmp_path, third) == {"3", "4"}
    assert "Step 2: Gate a (COPY_FILES): skipped in the earlier attempt, so it is not run again" in log_of(tmp_path, third)


def test_a_file_step_started_at_copies_its_files_again(seed, endpoints, attempt, tmp_path):
    gated_job(seed, gates=("a", "b"))
    put_gate(tmp_path, "a.ok")
    first, failed = attempt("RES")
    assert failed.returncode == 1                       # Collect and Gate a finished; Gate b has no file
    put_gate(tmp_path, "b.ok")

    second, done = attempt("RES", "--resume-run-id", first, "--from-step", "1")

    assert done.returncode == 0, done.stderr
    copied = [op for op in operations(tmp_path, second) if op["StepNumber"] == "1"]
    assert len(copied) == 2                             # Collect's two files, copied again


def test_a_step_the_job_no_longer_has_is_refused_in_words(seed, endpoints, attempt, tmp_path):
    gated_job(seed)
    first, _ = attempt("RES")

    second, refused = attempt("RES", "--resume-run-id", first, "--from-step", "9")

    assert refused.returncode == 1
    assert "no active step 9" in log_of(tmp_path, second)


def test_starting_at_a_step_without_an_attempt_to_pick_up_is_refused(seed, endpoints, attempt, tmp_path):
    gated_job(seed)

    run, refused = attempt("RES", "--from-step", "1")

    assert refused.returncode == 1
    assert "needs an earlier attempt" in log_of(tmp_path, run)


# ---------- The API ----------

def rerun_plan(api, run_id, **query):
    return plan_of(api, {"run_id": run_id}, **query)


def advanced(api, run, **body):
    return rerun(api, run, **body)


@pytest.fixture
def two_gates(seed, endpoints, db):
    gated_job(seed, gates=("a", "b"), name="DEV-RES")
    db.commit()


def test_the_plan_lists_the_top_level_steps_and_what_each_finished(live_api, two_gates):
    _, run = run_and_wait(live_api, "DEV-RES", "UI-S1")

    plan = rerun_plan(live_api, run["run_id"])

    assert plan["advanced"] and plan["can_resume"] and plan["refusal"] is None
    assert [(s["number"], s["title"], s["state"]) for s in plan["steps"]] == [
        ("1", "Collect", "finished"), ("2", "Gate a", "failed"), ("3", "Gate b", "not_run"), ("4", "Report", "not_run")]
    assert all(s["file_step"] for s in plan["steps"][:3]) and not plan["steps"][3]["file_step"]
    assert plan["steps"][1]["why"] is None and plan["items"] == []      # a gate step knows what it did


def test_the_plan_for_a_choice_says_what_each_step_gets(live_api, two_gates):
    _, run = run_and_wait(live_api, "DEV-RES", "UI-S2")

    plan = rerun_plan(live_api, run["run_id"], from_step="3", skip_steps=["4"])

    assert plan["steps_problem"] is None and plan["from_step"] == "3" and plan["skip_steps"] == ["4"]
    assert {s["number"]: s["gets"] for s in plan["steps"]} == {
        "1": "done", "2": "skipped", "3": "run", "4": "skipped"}
    assert "starts at step 3" in plan["summary"]


def test_choices_that_make_no_sense_are_refused_in_words(live_api, two_gates):
    _, run = run_and_wait(live_api, "DEV-RES", "UI-S3")

    def problem(**query):
        return rerun_plan(live_api, run["run_id"], **query)["steps_problem"]

    assert "no step 9" in problem(from_step="9")
    assert "already finished" in problem(skip_steps=["1"])
    assert "already finished" in problem(from_step="3", skip_steps=["1"])       # it counts as done before the start
    assert problem(from_step="1", skip_steps=["1"]) is None        # at or after the start is fine


def test_a_skip_and_a_start_run_as_the_next_attempt_and_are_recorded(live_api, two_gates, tmp_path, db):
    _, first = run_and_wait(live_api, "DEV-RES", "UI-S4")
    put_gate(tmp_path, "b.ok", job="DEV-RES")

    response = advanced(live_api, first, from_step="3", skip_steps=["4"])
    assert response.status_code == 202, response.text
    _, second = follow(live_api, response.json())

    assert (second["status"], second["attempt"]) == ("SUCCESS", 2)
    log = "\n".join(second["log"])
    assert "starting at step 3" in log and "Step 4: Report (Simulate): skipped, as the operator chose to skip it" in log
    restarts = second["restarts"]
    assert restarts[-1]["kind"] == "ADVANCED" and restarts[-1]["words"] == "Resumed from attempt 1, by step"
    assert restarts[-1]["steps"] == [
        "Started at step 3 'Gate b'.", "Passed over step 2 'Gate a', which had not finished.", "Skipped step 4 'Report'."]


def test_a_step_of_unknown_effect_that_is_passed_over_needs_no_decision_but_one_that_runs_again_does(live_api, two_gates, tmp_path):
    _, first = run_and_wait(live_api, "DEV-RES", "UI-S5")
    make_unknown(tmp_path, first["run_id"])

    nothing = advanced(live_api, first, skip_steps=["3"])
    assert nothing.status_code == 422 and "may or may not have changed" in nothing.text      # step 2 still runs again
    skipped = advanced(live_api, first, skip_steps=["2"])
    assert skipped.status_code == 202, skipped.text
    _, second = follow(live_api, skipped.json())
    assert second["status"] == "FAILED"                 # on to Gate b, which has no file


def test_a_succeeded_job_a_workflow_item_and_a_choice_with_no_record_are_refused(live_api, two_gates, tmp_path):
    put_gate(tmp_path, "a.ok", "b.ok", job="DEV-RES")
    _, done = run_and_wait(live_api, "DEV-RES", "UI-S6")
    assert done["status"] == "SUCCESS"

    assert advanced(live_api, done, from_step="1").status_code == 409
    assert "succeeded" in rerun_plan(live_api, done["run_id"])["refusal"]


def test_values_can_be_edited_with_a_start_step(live_api, seed, endpoints, db, tmp_path):
    job = gated_job(seed, gates=("a",), name="DEV-RES")
    seed.set_vars(job, Mode="A")
    seed.step(job, 9, "SIMULATE", title="Say", Messages="Mode is ${Mode}")
    db.commit()
    _, first = run_and_wait(live_api, "DEV-RES", "UI-S7")
    put_gate(tmp_path, "a.ok", job="DEV-RES")

    response = advanced(live_api, first, from_step="2", edits={"Mode": "B"})
    assert response.status_code == 202, response.text
    _, second = follow(live_api, response.json())

    assert second["status"] == "SUCCESS" and any("Mode is B" in line for line in second["log"])

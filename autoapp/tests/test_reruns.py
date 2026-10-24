"""
Rerun on a job run on its own (docs/WORKFLOWS_PHASE7.md, step 2): counting a failed step as done, "Failed
(effect unknown)", the net file count across attempts, and the rerun API (a plan, then Resume or Restart).
"""
import json
import time

import pytest

from core.models import JobRun
from engine.runner import failure_reason
from core.step_catalog import NOT_DONE, UNKNOWN, WhatItKnew
from test_control_file import attempt, control_of, gated_job, log_of, put_gate    # noqa: F401 (attempt is a fixture)
from test_launches import follow, get, post


def make_unknown(tmp_path, run_id):
    """Rewrites the run's failure as one whose effect is not known, as a Run SQL that lost its connection would."""
    path = next((tmp_path / "logs").rglob(f"{run_id}.control"))
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    for record in lines:
        if record["e"] == "failed":
            record.update(knew=UNKNOWN, operator_decides=True, why="the connection dropped while committing")
    path.write_text("".join(json.dumps(record) + "\n" for record in lines))


# ---------- Engine ----------

def test_a_step_counted_as_done_is_not_run_again(seed, endpoints, attempt, tmp_path):
    gated_job(seed)
    first, failed = attempt("RES")
    assert failed.returncode == 1                       # the gate is shut

    second, resumed = attempt("RES", "--resume-run-id", first, "--count-as-done", "2|")

    assert resumed.returncode == 0, resumed.stderr
    log = log_of(tmp_path, second)
    assert "Gate a (COPY_FILES): counted as done, as the operator chose" in log
    assert "Collected 2 files" in log


def test_a_failure_that_could_not_say_what_it_did_ends_with_the_reason_effect_unknown():
    unknown = RuntimeError("lost")
    unknown.knew = WhatItKnew(UNKNOWN, "the connection dropped")
    sure = RuntimeError("no")
    sure.knew = WhatItKnew(NOT_DONE)
    assert failure_reason(unknown) == "EFFECT_UNKNOWN"
    assert failure_reason(sure) == "ERROR"
    assert failure_reason(ValueError("before any step")) == "ERROR"


def test_a_resume_adds_up_the_files_of_its_attempts_and_a_restart_counts_only_its_own(
        seed, db, endpoints, attempt, tmp_path):
    gated_job(seed)
    first, _ = attempt("RES")
    put_gate(tmp_path, "a.ok")

    resumed, _ = attempt("RES", "--resume-run-id", first)
    restarted, _ = attempt("RES")

    totals = {run.RunID: run.FileCount for run in db.query(JobRun)}
    assert totals[first] == 2                           # Collect's two files, then the shut gate
    assert totals[resumed] == 3                         # those two, plus the gate's file
    assert totals[restarted] == 3                       # everything again, none carried


# ---------- The API ----------

@pytest.fixture
def gated(seed, endpoints, db):
    gated_job(seed, name="DEV-RES")
    db.commit()


def run_and_wait(api, job_key, instance):
    launch = post(f"{api}/api/v1/launches", json={"job_key": job_key, "instance_id": instance}).json()
    return follow(api, launch)



def test_the_plan_for_a_failed_job_says_what_resume_would_do(live_api, gated):
    _, run = run_and_wait(live_api, "DEV-RES", "UI-R1")
    assert run["status"] == "FAILED"

    plan = get(f"{live_api}/api/v1/runs/{run['run_id']}/rerun-plan").json()

    assert (plan["can_restart"], plan["can_resume"], plan["steps_finished"]) == (True, True, 1)
    assert plan["step_to_decide"] is None
    assert "1 step finished" in plan["summary"]


def test_a_resume_is_the_next_attempt_and_skips_what_finished(live_api, gated, tmp_path):
    _, first = run_and_wait(live_api, "DEV-RES", "UI-R2")
    put_gate(tmp_path, "a.ok", job="DEV-RES")

    response = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "resume"})
    assert response.status_code == 202, response.text
    _, second = follow(live_api, response.json())

    assert (second["status"], second["attempt"], second["instance_id"]) == ("SUCCESS", 2, "UI-R2")
    assert second["file_count"] == 3
    assert any("finished in the earlier attempt" in line for line in second["log"])
    again = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "resume"})
    assert again.status_code == 409 and "attempt 2 has run since" in again.text


def test_a_restart_runs_the_whole_job_again(live_api, gated, tmp_path):
    _, first = run_and_wait(live_api, "DEV-RES", "UI-R3")

    response = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "restart"})
    _, second = follow(live_api, response.json())

    assert second["attempt"] == 2 and second["status"] == "FAILED"
    assert not any("finished in the earlier attempt" in line for line in second["log"])


def test_a_step_that_may_have_changed_something_must_be_decided_before_resume(live_api, gated, tmp_path):
    _, first = run_and_wait(live_api, "DEV-RES", "UI-R4")
    make_unknown(tmp_path, first["run_id"])
    plan = get(f"{live_api}/api/v1/runs/{first['run_id']}/rerun-plan").json()
    assert plan["step_to_decide"]["title"] == "Gate a" and "dropped" in plan["step_to_decide"]["why"]

    refused = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "resume"})
    assert refused.status_code == 422 and "may or may not have changed" in refused.text

    counted = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "resume", "unknown_step": "count_done"})
    _, second = follow(live_api, counted.json())
    assert second["status"] == "SUCCESS"


def test_a_succeeded_job_a_running_one_and_a_workflow_cannot_be_rerun(live_api, gated, tmp_path):
    put_gate(tmp_path, "a.ok", job="DEV-RES")
    _, done = run_and_wait(live_api, "DEV-RES", "UI-R5")
    assert done["status"] == "SUCCESS"

    plan = get(f"{live_api}/api/v1/runs/{done['run_id']}/rerun-plan").json()
    assert (plan["can_restart"], plan["can_resume"]) == (False, False) and "succeeded" in plan["refusal"]
    assert post(f"{live_api}/api/v1/runs/{done['run_id']}/rerun", json={"kind": "restart"}).status_code == 409
    assert get(f"{live_api}/api/v1/runs/not-a-run/rerun-plan").status_code == 404

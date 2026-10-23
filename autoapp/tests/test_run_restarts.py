"""
The record of a run being run again (docs/WORKFLOWS_PHASE7.md, step 5-2): the RunRestarts row and the Audit Log row
the API writes for each request, the list on the run (an operator's and a Reaction's merged), and the migration.
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.models import Audit, JobRun, RunRestart
from app.run_restarts import restarts_for
from test_control_file import gated_job, put_gate
from test_launches import follow, get, post     # noqa: F401
from test_reaction_resume import alone, open_gate_soon      # noqa: F401
from test_reruns import gated, make_unknown, run_and_wait     # noqa: F401 (gated is a fixture)
from test_frames_engine import tree    # noqa: F401 (fixture)
from test_workflow_reopen import run_workflow
from test_workflow_resume_values_api import rerun, valued    # noqa: F401 (valued is a fixture)
from test_workflow_runner import flow, sim, start    # noqa: F401  (fixtures)

MIGRATION = Path(__file__).resolve().parents[2] / "SQL" / "migrate_restarts.py"


def audits(db, action):
    db.expire_all()
    return [json.loads(a.Details)["changes"] for a in db.query(Audit).filter(Audit.Action == action).order_by(Audit.id)]


def restart_of(api, run_id):
    return get(f"{api}/api/v1/runs/{run_id}").json()["restarts"]


# ---------- A job on its own ----------

def test_a_resume_writes_one_restart_row_and_one_audit_row(live_api, gated, tmp_path, db):
    _, first = run_and_wait(live_api, "DEV-RES", "UI-RR1")
    put_gate(tmp_path, "a.ok", job="DEV-RES")

    response = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "resume"})
    _, second = follow(live_api, response.json())

    row = db.query(RunRestart).one()
    assert (row.RunID, row.Number, row.Kind, row.Scope, row.PerformedBy) == (second["run_id"], 1, "RESUME", "", "web interface")
    assert json.loads(row.Details)["from_attempt"] == 1
    assert audits(db, "JOB_RESUMED") == [["Resumed 'DEV-RES' from attempt 1."]]
    assert audits(db, "JOB_RESTARTED") == []


def test_a_restart_writes_its_rows_and_the_latest_attempts_page_lists_the_whole_chain(live_api, gated, tmp_path, db):
    _, first = run_and_wait(live_api, "DEV-RES", "UI-RR2")
    _, second = follow(live_api, post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "restart"}).json())
    put_gate(tmp_path, "a.ok", job="DEV-RES")
    _, third = follow(live_api, post(f"{live_api}/api/v1/runs/{second['run_id']}/rerun", json={"kind": "resume"}).json())

    listed = restart_of(live_api, third["run_id"])

    assert [(r["number"], r["kind"], r["by"]) for r in listed] == [(1, "RESTART", "web interface"), (2, "RESUME", "web interface")]
    assert [r["words"] for r in listed][1] == "Resumed from attempt 2"
    assert restart_of(live_api, first["run_id"]) == listed          # the same chain from any attempt's page
    assert audits(db, "JOB_RESTARTED") == [["Restarted 'DEV-RES' from the beginning (it was attempt 1)."]]


def test_a_decision_on_a_step_of_unknown_effect_is_kept_with_the_restart(live_api, gated, tmp_path, db):
    _, first = run_and_wait(live_api, "DEV-RES", "UI-RR3")
    make_unknown(tmp_path, first["run_id"])

    _, second = follow(live_api, post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun",
                                      json={"kind": "resume", "unknown_step": "count_done"}).json())

    listed = restart_of(live_api, second["run_id"])
    assert listed[0]["decisions"] == ["Step 2 'Gate a': counted as done, as chosen."]
    assert audits(db, "JOB_RESUMED")[0][0] == "Resumed 'DEV-RES' from attempt 1: Step 2 'Gate a' counted as done, as chosen."


def test_a_refused_request_writes_nothing(live_api, gated, tmp_path, db):
    _, first = run_and_wait(live_api, "DEV-RES", "UI-RR4")
    make_unknown(tmp_path, first["run_id"])

    refused = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "resume"})            # 422: no choice
    odd = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun", json={"kind": "sometimes"})
    missing = post(f"{live_api}/api/v1/runs/nope/rerun", json={"kind": "restart"})

    assert (refused.status_code, odd.status_code, missing.status_code) == (422, 422, 404)
    assert db.query(RunRestart).count() == 0 and db.query(Audit).filter(Audit.Action.like("JOB_RE%")).count() == 0


def test_a_reactions_rerun_is_in_the_list_beside_the_operators(seed, endpoints, db, run_runner, load_spool, tmp_path):
    alone(seed, db, "RESUME")
    timer = open_gate_soon(tmp_path)
    run_runner("RES")
    timer.join()
    load_spool()
    db.commit()
    db.expire_all()
    latest = db.query(JobRun).filter(JobRun.JobKey == "RES").order_by(JobRun.id.desc()).first()

    listed = restarts_for(db, latest)

    assert [(r.number, r.kind, r.by, r.from_attempt) for r in listed] == [(1, "RESUME", "a Reaction", 1)]
    assert "from where it failed" in listed[0].message
    assert db.query(RunRestart).count() == 0            # not copied into the table


# ---------- A workflow ----------

def test_a_workflow_resume_is_recorded_on_the_reopened_run_and_the_edit_rows_stay(valued, live_api, db):
    response = rerun(live_api, valued, level_edits={"": {"workflow": {"Fail": "False"}}})
    _, run = follow(live_api, response.json())

    row = db.query(RunRestart).one()
    assert (row.RunID, row.Number, row.Kind) == (valued["run_id"], 1, "RESUME")
    details = json.loads(row.Details)
    assert details["items"] == ["Load goes on from attempt 1", "Report runs again from the beginning"]
    assert details["edits"] == ["Resumed 'WF' with variable Fail changed from 'True' to 'False'."]
    assert len(audits(db, "JOB_RESUMED_WITH_EDITS")) == 1
    resumed = audits(db, "JOB_RESUMED")
    assert resumed[0][0] == "Resumed 'WF' from attempt 1: 'Load' and 'Report' run again."
    assert restart_of(live_api, valued["run_id"])[0]["items"] == details["items"]


def test_the_second_time_a_workflow_is_reopened_is_number_two(valued, live_api, db):
    follow(live_api, rerun(live_api, valued, kind="restart").json())
    follow(live_api, rerun(live_api, valued, kind="restart").json())

    assert [r["number"] for r in restart_of(live_api, valued["run_id"])] == [1, 2]
    assert sorted(r.Number for r in db.query(RunRestart)) == [1, 2]
    assert len(audits(db, "JOB_RESTARTED")) == 2


# ---------- The migration ----------

def test_the_migration_adds_the_table_and_can_be_run_again(tmp_path):
    database = tmp_path / "old.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE ReactionActions (id INTEGER PRIMARY KEY, Action TEXT)")
    connection.execute("INSERT INTO ReactionActions (Action) VALUES ('RERUN')")
    connection.commit()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}

    outputs = [subprocess.run([sys.executable, str(MIGRATION)], env=env, check=True, capture_output=True, text=True).stdout
               for _ in range(2)]

    assert "Added tables: RunRestarts" in outputs[0] and "Added tables: none" in outputs[1]
    assert connection.execute("SELECT Action, RerunMode FROM ReactionActions").fetchall() == [("RERUN", "RESTART")]
    assert [r[1] for r in connection.execute("PRAGMA table_info(RunRestarts)")] == [
        "id", "RunID", "Number", "Kind", "Scope", "PerformedBy", "ChosenDateTime", "Details"]


# ---------- The step 4b gap: an edit reaching a job inside a reopened frame ----------

def test_an_edit_made_to_a_frames_variable_reaches_the_job_inside_it(seed, tree, live_api, db):
    inner = seed.job("INNER")
    seed.step(inner, 1, "SIMULATE", title="Inner", Fail="${Fail}")
    top, made = tree("TOP", {"Frame": {"Inner": inner}})
    seed.set_vars(made["Frame"].job, Fail="True")
    db.commit()
    first = run_workflow(live_api, "TOP", "UI-FR1")
    assert first["status"] == "FAILED"

    response = rerun(live_api, first, level_edits={"Frame": {"workflow": {"Fail": "False"}}})
    assert response.status_code == 202, response.text
    _, run = follow(live_api, response.json())

    assert run["status"] == "SUCCESS"
    row = db.query(RunRestart).one()
    assert json.loads(row.Details)["edits"] == ["Resumed 'TOP.Frame' with variable Fail changed from 'True' to 'False'."]
    assert audits(db, "JOB_RESUMED_WITH_EDITS") == [json.loads(row.Details)["edits"]]

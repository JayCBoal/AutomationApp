"""
DEV-RESTARTS_SAMPLE (docs/WORKFLOWS_PHASE7.md, step 7): the walk-through in the seed comment, one choice at a time.
The workflow is run and reopened with the real runner, the way the Rerun dialog starts it.
"""
import json
import subprocess
import sys

import pytest

from app.log_agent import run_log
from app.models import JobRun, Variable, WorkflowRunItem
from conftest import AUTOAPP_DIR, subprocess_env
from create_dev_db import create_restart_files, load_seed
from test_workflow_reopen import reopen     # noqa: F401  (fixture)

KEY = "DEV-RESTARTS_SAMPLE"
FIRST = {"Load": "FAILED", "Post": "NOT_RUN", "Reconcile": "NOT_RUN", "Notify": "NOT_RUN", "Report": "NOT_RUN"}


@pytest.fixture
def sample(db, db_url, tmp_path):
    """The seed, pointed at the test's folders, and the workflow run once: Load fails at the empty fourth file."""
    load_seed(db)
    for root in db.query(Variable).filter(Variable.VarName == "Root"):
        root.VarValue = root.VarValue.replace("/tmp/autoapp_sample", str(tmp_path))
    db.commit()
    folder = tmp_path / "legal_app" / "restarts_in"
    create_restart_files(folder)
    env = {**subprocess_env(db_url), "AUTOAPP_WORKFLOW_POLL_SECONDS": "0.2"}
    done = subprocess.run([sys.executable, "-m", "engine.runner", "--job-key", KEY, "--instance-id", "RS-W1",
                           "--spool-dir", str(tmp_path / "spool"), "--working-root", str(tmp_path / "work")],
                          cwd=AUTOAPP_DIR, env=env, capture_output=True, text=True, timeout=180)
    assert done.returncode == 1, done.stdout[-3000:]
    db.expire_all()
    run = db.query(JobRun).filter(JobRun.JobKey == KEY).one()
    (folder / "restart_4.csv").write_text("row\n4\n")          # step 2 of the walk-through
    return run, folder


def items_of(db):
    db.expire_all()
    run = db.query(JobRun).filter(JobRun.JobKey == KEY, JobRun.ParentRun_id.is_(None)).one()
    return run, {i.ItemName: i for i in db.query(WorkflowRunItem).filter_by(WorkflowRun_id=run.id)}


def log_of(db, run):
    return "\n".join(run_log(run))


def statuses(items):
    return {name: item.Status for name, item in items.items()}


def resume_through_post(reopen, run):
    """Steps 2 and 3: Resume (Load does the rest, Post fails unknown), then Resume counting Post as done."""
    second = reopen(run, "resume")
    third = reopen(run, "resume", "--rerun-decisions", json.dumps({"Post": "count_done"}))
    return second, third


def test_it_fails_at_the_empty_file_and_everything_after_it_is_not_run(sample, db):
    run, items = items_of(db)
    assert statuses(items) == FIRST and run.Status == "FAILED"


def test_resume_does_the_rest_of_load_and_stops_at_the_post_whose_effect_is_unknown(sample, reopen, db):
    run, _ = sample

    reopen(run, "resume")

    run, items = items_of(db)
    assert (items["Load"].Status, items["Load"].Attempt) == ("SUCCESS", 2)
    assert (items["Post"].Status, items["Post"].Reason) == ("FAILED", "EFFECT_UNKNOWN")
    assert items["Load"].child_run.FileCount == 5                         # the net count over both attempts
    assert statuses(items)["Reconcile"] == "NOT_RUN"


def test_counting_post_as_done_lets_reconcile_run_and_its_reaction_resumes_balance(sample, reopen, db):
    run, _ = sample

    second, third = resume_through_post(reopen, run)

    run, items = items_of(db)
    assert statuses(items) == {"Load": "SUCCESS", "Post": "SUCCESS", "Reconcile": "SUCCESS", "Notify": "SUCCESS",
                               "Report": "SUCCESS"}, third.stdout + third.stderr
    assert run.Status == "SUCCESS"
    frame = items["Reconcile"].child_run
    inner = {i.ItemName: i for i in db.query(WorkflowRunItem).filter_by(WorkflowRun_id=frame.id)}
    assert (inner["Match"].Status, inner["Match"].Attempt) == ("SUCCESS", 1)             # not run again
    assert (inner["Balance"].Status, inner["Balance"].Attempt) == ("SUCCESS", 2)         # failed once, then passed
    assert frame.Attempt == 2 and items["Reconcile"].Attempt == 2
    log = log_of(db, run)
    assert "picked up again (resume)" in log


def test_dont_run_on_notify_and_ignoring_it_lets_report_run_without_it(sample, reopen, db):
    run, _ = sample
    resume_through_post(reopen, run)
    run, _ = items_of(db)

    reopen(run, "advanced", "--reopen-items", json.dumps({"Notify": "dont_run", "Report": "restart"}),
           "--ignore-waits", json.dumps({"Report": ["Notify"]}))

    run, items = items_of(db)
    assert (items["Notify"].Status, items["Report"].Status, items["Report"].Attempt) == ("SKIPPED", "SUCCESS", 2)


def test_report_alone_can_be_started_from_a_chosen_job_with_other_values(sample, reopen, db):
    run, _ = sample
    resume_through_post(reopen, run)
    run, _ = items_of(db)

    reopen(run, "advanced", "--reopen-items", json.dumps({"Report": "restart"}))

    run, items = items_of(db)
    assert items["Report"].Attempt == 2 and items["Notify"].Attempt == 1                  # only Report ran again
    assert "Reporting for EU" in "\n".join(run_log(items["Report"].child_run))

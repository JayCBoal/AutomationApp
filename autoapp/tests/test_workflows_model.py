"""
Workflows in the database (docs/WORKFLOWS.md, docs/WORKFLOWS_PHASE1.md): a workflow is a
Job of type WORKFLOW, its items and prerequisites, and the migration that brings an older
database up to date.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from core.models import Job, JobRun, WorkflowItem, WorkflowPrerequisite, WorkflowRunItem

MIGRATION = Path(__file__).resolve().parents[2] / "SQL" / "migrate_workflows.py"


def workflow_with_two_jobs(db):
    first, second = Job(JobKey="FIRST"), Job(JobKey="SECOND")
    flow = Job(JobKey="FLOW", JobType="WORKFLOW")
    db.add_all([first, second, flow])
    db.flush()
    a = WorkflowItem(workflow=flow, ItemName="First", job=first, ItemOrder=1)
    b = WorkflowItem(workflow=flow, ItemName="Second", job=second, ItemOrder=2)
    db.add_all([a, b])
    db.flush()
    db.add(WorkflowPrerequisite(item=b, target=a, Test="SUCCESS"))
    db.commit()
    return flow, a, b


def test_a_job_is_a_steps_job_unless_it_says_otherwise(db):
    job = Job(JobKey="PLAIN")
    db.add(job)
    db.commit()
    assert (job.JobType, job.SuccessReturnCodes, job.Owner_MasterObject_id) == ("STEPS", None, None)


def test_a_workflow_holds_its_items_in_order_with_their_prerequisites(db):
    flow, a, b = workflow_with_two_jobs(db)
    db.expire_all()
    assert [item.ItemName for item in flow.items] == ["First", "Second"]
    assert [(p.target.ItemName, p.Test) for p in flow.items[1].prerequisites] == [("First", "SUCCESS")]
    assert flow.items[0].job.JobKey == "FIRST"


def test_two_items_of_a_workflow_cannot_share_a_name(db):
    flow, a, b = workflow_with_two_jobs(db)
    db.add(WorkflowItem(workflow=flow, ItemName="First", job=b.job, ItemOrder=3))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_a_workflow_deletes_its_items_and_prerequisites(db):
    flow, a, b = workflow_with_two_jobs(db)
    db.delete(flow)
    db.commit()
    assert db.query(WorkflowItem).count() == 0 and db.query(WorkflowPrerequisite).count() == 0
    assert db.query(Job).filter(Job.JobKey.in_(["FIRST", "SECOND"])).count() == 2


def test_a_workflow_run_records_its_items_and_its_job_runs_point_to_it(db):
    flow, a, b = workflow_with_two_jobs(db)
    run = JobRun(RunID="wf-1", JobKey="FLOW", SchedulerInstanceID="I1", JobType="WORKFLOW")
    db.add(run)
    db.flush()
    child = JobRun(RunID="job-1", JobKey="FIRST", SchedulerInstanceID="I1-1", ParentRun_id=run.id,
                   WorkflowPath="First", ReturnCode=0, Status="SUCCESS")
    db.add(child)
    db.flush()
    db.add_all([WorkflowRunItem(WorkflowRun_id=run.id, Item_id=a.id, Path="First", ItemName="First", JobKey="FIRST",
                                Status="SUCCESS", ChildRun_id=child.id, Attempt=1),
                WorkflowRunItem(WorkflowRun_id=run.id, Item_id=b.id, Path="Second", ItemName="Second", JobKey="SECOND")])
    db.commit()
    items = db.query(WorkflowRunItem).order_by(WorkflowRunItem.id).all()
    assert [(i.Path, i.Status, i.Attempt) for i in items] == [("First", "SUCCESS", 1), ("Second", "PENDING", 0)]
    assert items[0].child_run.ParentRun_id == run.id and child.Attempt == 1


# ---------- Bringing an older database up to date ----------

OLD_SCHEMA = """
    CREATE TABLE MasterObjects (id INTEGER PRIMARY KEY, ObjectType VARCHAR(20));
    CREATE TABLE Jobs (MasterObject_id INTEGER PRIMARY KEY REFERENCES MasterObjects(id), JobKey VARCHAR(320),
                       Description TEXT, IsActive BOOLEAN);
    CREATE TABLE JobRuns (id INTEGER PRIMARY KEY, RunID VARCHAR(36), JobKey VARCHAR(320), Status VARCHAR(20));
    INSERT INTO MasterObjects VALUES (1, 'JOB');
    INSERT INTO Jobs VALUES (1, 'OLD_JOB', NULL, 1);
    INSERT INTO JobRuns VALUES (1, 'r1', 'OLD_JOB', 'SUCCESS'), (2, 'r2', 'OLD_JOB', 'FAILED'), (3, 'r3', 'OLD_JOB', 'RUNNING');
"""


def test_the_migration_adds_what_workflows_need_and_keeps_the_data(tmp_path):
    database = tmp_path / "old.db"
    connection = sqlite3.connect(database)
    connection.executescript(OLD_SCHEMA)
    connection.commit()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    outputs = [subprocess.run([sys.executable, str(MIGRATION)], env=env, check=True, capture_output=True, text=True).stdout
               for _ in range(2)]                  # a second run finds nothing to do
    assert "Added columns: none" in outputs[1] and "Added tables: none" in outputs[1]

    assert connection.execute("SELECT JobKey, JobType, SuccessReturnCodes FROM Jobs").fetchall() == [("OLD_JOB", "STEPS", None)]
    runs = connection.execute("SELECT RunID, ReturnCode, JobType, Attempt FROM JobRuns ORDER BY id").fetchall()
    assert runs == [("r1", 0, "STEPS", 1), ("r2", 1, "STEPS", 1), ("r3", None, "STEPS", 1)]
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"WorkflowItems", "WorkflowPrerequisites", "WorkflowRunItems"} <= tables

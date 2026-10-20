"""
Workflows Phase 5, step 1: what an outside prerequisite is stored as, and the migration that adds it.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine

from app.models import Base, Job, WorkflowItem, WorkflowPrerequisite, WorkflowPrerequisiteCheck

MIGRATION = Path(__file__).resolve().parents[2] / "SQL" / "migrate_outside_dependencies.py"
OLD_PREREQUISITES = """CREATE TABLE WorkflowPrerequisites (
    id INTEGER PRIMARY KEY AUTOINCREMENT, Item_id INTEGER NOT NULL REFERENCES WorkflowItems (id) ON DELETE CASCADE,
    TargetItem_id INTEGER REFERENCES WorkflowItems (id) ON DELETE CASCADE,
    Test VARCHAR(20) NOT NULL DEFAULT 'SUCCESS', ReturnCodes VARCHAR(100), "Condition" TEXT)"""


def a_use(db):
    job, flow = Job(JobKey="LOAD"), Job(JobKey="FLOW", JobType="WORKFLOW")
    db.add_all([job, flow])
    db.flush()
    item = WorkflowItem(workflow=flow, ItemName="Load", job=job, ItemOrder=1)
    db.add(item)
    db.flush()
    return job, flow, item


def test_a_prerequisite_is_a_job_in_its_own_workflow_that_waits_for_ever_unless_it_says_otherwise(db):
    _, _, item = a_use(db)
    db.add(WorkflowPrerequisite(Item_id=item.id))
    db.commit()
    p = db.query(WorkflowPrerequisite).one()
    assert (p.Kind, p.Test, p.WaitMode, p.WaitFrom, p.Required, p.OnlyAfterStart) == (
        "JOB", "SUCCESS", "DEFAULT", "OTHERS", True, False)
    assert item.OnUnmet == "NOT_RUN"


def test_an_outside_prerequisite_can_be_a_workflow_an_endpoint_or_a_time(db):
    _, flow, item = a_use(db)
    other = Job(JobKey="MONTH_END", JobType="WORKFLOW")
    db.add(other)
    db.flush()
    db.add(WorkflowPrerequisite(Item_id=item.id, Kind="OTHER_JOB", TargetName="MONTH_END",
                                TargetJob_MasterObject_id=other.MasterObject_id, LookBackHours=6, OnlyAfterStart=True))
    db.add(WorkflowPrerequisite(Item_id=item.id, Kind="TIME", TargetName="Window",
                                TimeCondition="%{Now.Time} BETWEEN '06:00' AND '18:00'", WaitMode="MINUTES",
                                WaitMinutes=30, Required=False))
    db.commit()
    kinds = [(p.Kind, p.TargetName, p.Required) for p in item.prerequisites]
    assert kinds == [("OTHER_JOB", "MONTH_END", True), ("TIME", "Window", False)]
    assert item.prerequisites[0].target_workflow.JobKey == "MONTH_END"


def test_what_a_prerequisite_found_is_kept_with_the_run(db):
    from app.models import JobRun
    run = JobRun(RunID="r1", JobKey="FLOW", SchedulerInstanceID="I")
    db.add(run)
    db.flush()
    db.add(WorkflowPrerequisiteCheck(WorkflowRun_id=run.id, Path="Load", Kind="OTHER_JOB", TargetName="MONTH_END.Extract",
                                     Result="HOLDS", UsedRunID="abc", Message="used the latest run"))
    db.commit()
    check = db.query(WorkflowPrerequisiteCheck).one()
    assert (check.Result, check.CheckedDateTime is not None) == ("HOLDS", True)


def test_the_migration_adds_what_outside_dependencies_need_and_keeps_the_data(tmp_path):
    database = tmp_path / "phase4.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    engine.dispose()
    connection = sqlite3.connect(database)
    connection.execute("DROP TABLE WorkflowPrerequisiteChecks")      # a database as Phase 4 left it
    connection.execute("DROP TABLE WorkflowPrerequisites")
    connection.execute(OLD_PREREQUISITES)
    connection.execute("ALTER TABLE WorkflowItems DROP COLUMN OnUnmet")
    for id_, key, kind in ((1, "FLOW", "WORKFLOW"), (2, "LOAD", "STEPS")):
        connection.execute(f"INSERT INTO MasterObjects (id, ObjectType) VALUES ({id_}, 'JOB')")
        connection.execute(f"INSERT INTO Jobs (MasterObject_id, JobKey, JobType) VALUES ({id_}, '{key}', '{kind}')")
    connection.execute("INSERT INTO WorkflowItems (id, Workflow_MasterObject_id, ItemName, Job_MasterObject_id) "
                       "VALUES (1, 1, 'A', 2), (2, 1, 'B', 2)")
    connection.execute("INSERT INTO WorkflowPrerequisites (Item_id, TargetItem_id, Test) VALUES (2, 1, 'SUCCESS')")
    connection.commit()

    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    outputs = [subprocess.run([sys.executable, str(MIGRATION)], env=env, check=True, capture_output=True, text=True).stdout
               for _ in range(2)]                  # a second run finds nothing to do
    assert "Added columns: none" in outputs[1] and "Added tables: none" in outputs[1]

    assert connection.execute("SELECT Item_id, TargetItem_id, Test, Kind, WaitMode, WaitFrom, Required "
                              "FROM WorkflowPrerequisites").fetchall() == [(2, 1, "SUCCESS", "JOB", "DEFAULT", "OTHERS", 1)]
    assert connection.execute("SELECT OnUnmet FROM WorkflowItems").fetchall() == [("NOT_RUN",), ("NOT_RUN",)]
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "WorkflowPrerequisiteChecks" in tables

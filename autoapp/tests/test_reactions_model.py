"""
Reactions in the database (docs/WORKFLOWS_PHASE3.md, step 1): a job's own Reactions and a
use's override, their actions, the record of those that fired, the new run columns, and the
migration that brings a Phase 2 database up to date.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError

# A failed CHECK is an IntegrityError on SQLite and an OperationalError on MariaDB
REFUSED = (IntegrityError, OperationalError)

from app.models import (Base, Job, JobRun, Reaction, ReactionAction, ReactionEvent, WorkflowItem, WorkflowRunItem)

MIGRATION = Path(__file__).resolve().parents[2] / "SQL" / "migrate_reactions.py"
NEW_TABLES = ("ReactionEvents", "ReactionActions", "Reactions")
NEW_COLUMNS = [("WorkflowItems", "DisabledHere"), ("WorkflowItems", "ReactionsOverridden"),
               ("JobRuns", "KillRequestedDateTime"), ("JobRuns", "ProcessID"), ("JobRuns", "StatusBeforeOverride"),
               ("WorkflowRunItems", "StatusBeforeOverride"), ("WorkflowRunItems", "ProcessID")]


def a_use(db):
    job, flow = Job(JobKey="LOAD"), Job(JobKey="FLOW", JobType="WORKFLOW")
    db.add_all([job, flow])
    db.flush()
    item = WorkflowItem(workflow=flow, ItemName="Load", job=job, ItemOrder=1)
    db.add(item)
    db.flush()
    return job, flow, item


def test_a_job_has_reactions_in_order_each_with_its_actions(db):
    job, _, _ = a_use(db)
    rerun = Reaction(Job_MasterObject_id=job.MasterObject_id, Section="NEXT", ReactionOrder=1, WhenTest="RC",
                     WhenReturnCodes="8")
    rerun.actions.append(ReactionAction(ActionOrder=1, Action="RERUN", MaxTimes=2, WaitSeconds=30))
    fail = Reaction(Job_MasterObject_id=job.MasterObject_id, Section="NEXT", ReactionOrder=2, WhenTest="FAILED")
    fail.actions.append(ReactionAction(ActionOrder=1, Action="COUNT_AS_FAILED"))
    db.add_all([fail, rerun])
    db.commit()
    db.expire_all()

    assert [(r.ReactionOrder, r.WhenTest, [a.Action for a in r.actions]) for r in job.reactions] == [
        (1, "RC", ["RERUN"]), (2, "FAILED", ["COUNT_AS_FAILED"])]


def test_a_use_overrides_its_jobs_reactions_only_when_it_says_so(db):
    job, _, item = a_use(db)
    db.add(Reaction(Item_id=item.id, WhenTest="SUCCESS"))
    db.commit()
    assert (item.ReactionsOverridden, item.DisabledHere) == (False, None)
    assert len(item.reactions) == 1 and job.reactions == []


def test_a_reaction_belongs_to_a_job_or_a_use_never_both_or_neither(db):
    job, _, item = a_use(db)
    db.add(Reaction(Job_MasterObject_id=job.MasterObject_id, Item_id=item.id))
    with pytest.raises(REFUSED):
        db.commit()
    db.rollback()
    db.add(Reaction())
    with pytest.raises(REFUSED):
        db.commit()


def test_removing_a_use_removes_its_reactions_and_their_actions(db):
    _, _, item = a_use(db)
    reaction = Reaction(Item_id=item.id, WhenTest="FAILED")
    reaction.actions.append(ReactionAction(Action="SKIP_BRANCH"))
    db.add(reaction)
    db.commit()
    db.delete(item)
    db.commit()
    assert db.query(Reaction).count() == 0 and db.query(ReactionAction).count() == 0


def test_a_run_keeps_what_it_ended_as_before_a_reaction_counted_it_otherwise(db):
    _, flow, _ = a_use(db)
    workflow_run = JobRun(RunID="w1", JobKey="FLOW", SchedulerInstanceID="I", JobType="WORKFLOW", Status="RUNNING")
    run = JobRun(RunID="r1", JobKey="LOAD", SchedulerInstanceID="I", Status="SUCCESS", StatusBeforeOverride="FAILED",
                 ReturnCode=4, ProcessID=4242)
    db.add_all([workflow_run, run])
    db.flush()
    db.add(ReactionEvent(JobRun_id=run.id, WorkflowRun_id=workflow_run.id, WorkflowPath="Load",
                         Action="COUNT_AS_SUCCEEDED", Message="Return code 4 counted as succeeded"))
    db.add(WorkflowRunItem(WorkflowRun_id=workflow_run.id, Path="Load", ItemName="Load", JobKey="LOAD",
                           Status="SUCCESS", StatusBeforeOverride="FAILED"))
    db.commit()
    event = db.query(ReactionEvent).one()
    assert (event.Result, event.EventDateTime is not None) == ("TOOK_EFFECT", True)
    assert (run.Status, run.StatusBeforeOverride, run.KillRequestedDateTime) == ("SUCCESS", "FAILED", None)


def test_the_migration_adds_what_reactions_need_and_keeps_the_data(tmp_path):
    database = tmp_path / "phase2.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    engine.dispose()
    connection = sqlite3.connect(database)
    for table in NEW_TABLES:                                     # a database as Phase 2 left it
        connection.execute(f"DROP TABLE {table}")
    for table, column in NEW_COLUMNS:
        connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    connection.execute("INSERT INTO MasterObjects (id, ObjectType) VALUES (1, 'JOB')")
    connection.execute("INSERT INTO Jobs (MasterObject_id, JobKey) VALUES (1, 'OLD_JOB')")
    connection.execute("INSERT INTO JobRuns (RunID, JobKey, SchedulerInstanceID, Status) VALUES ('r1', 'OLD_JOB', 'I', 'SUCCESS')")
    connection.commit()

    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    outputs = [subprocess.run([sys.executable, str(MIGRATION)], env=env, check=True, capture_output=True, text=True).stdout
               for _ in range(2)]                  # a second run finds nothing to do
    assert "Added columns: none" in outputs[1] and "Added tables: none" in outputs[1]

    assert connection.execute("SELECT RunID, Status, StatusBeforeOverride, ProcessID FROM JobRuns").fetchall() == [
        ("r1", "SUCCESS", None, None)]
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(NEW_TABLES) <= tables

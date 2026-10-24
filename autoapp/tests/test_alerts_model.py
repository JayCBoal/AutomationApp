"""
Time Whens, Late flags and Alerts in the database (docs/WORKFLOWS_PHASE8.md, step 1): what a Reaction keeps for a
time When and for Notify, the Late flag on runs and items, the alert, its outbox and the mail settings, and the
migration that brings a Phase 7 database up to date.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError

from core.models import (Alert, AlertDelivery, AlertRecipient, Base, Credential, Job, JobRun, MailSetting, Reaction,
                        ReactionAction, ReactionEvent, WorkflowRunItem, utcnow)

REFUSED = (IntegrityError, OperationalError)
MIGRATION = Path(__file__).resolve().parents[2] / "SQL" / "migrate_late_alerts.py"
NEW_TABLES = ("AlertDeliveries", "AlertRecipients", "MailSettings", "Alerts")
NEW_COLUMNS = [("Reactions", name) for name in
                ("WhenTimeKind", "WhenClockTime", "WhenMinutes", "WhenPercent", "WhenRunCount")] + \
              [("WorkflowRunItems", "ReadyDateTime")] + \
              [(table, name) for table in ("JobRuns", "WorkflowRunItems")
               for name in ("LateDateTime", "LateReason", "LateCause")]


def an_alert(db, name="Ops"):
    alert = Alert(Name=name, Subject="%{Job} is late", Message="Deadline missed")
    alert.recipients.append(AlertRecipient(RecipientOrder=2, Address="b@example.com"))
    alert.recipients.append(AlertRecipient(RecipientOrder=1, Address="a@example.com"))
    db.add(alert)
    db.flush()
    return alert


def test_a_time_when_keeps_how_its_time_is_given(db):
    job = Job(JobKey="LOAD")
    db.add(job)
    db.flush()
    db.add_all([
        Reaction(Job_MasterObject_id=job.MasterObject_id, Section="ALSO", WhenTest="NOT_ENDED_BY",
                 WhenTimeKind="CLOCK", WhenClockTime="03:00"),
        Reaction(Job_MasterObject_id=job.MasterObject_id, Section="ALSO", ReactionOrder=2,
                 WhenTest="RUNS_LONGER_THAN", WhenTimeKind="HISTORY", WhenPercent=50, WhenRunCount=10)])
    db.commit()
    clock, history = job.reactions
    assert (clock.WhenTimeKind, clock.WhenClockTime, clock.WhenMinutes) == ("CLOCK", "03:00", None)
    assert (history.WhenPercent, history.WhenRunCount) == (50, 10)
    assert set(Reaction.TIME_TESTS).isdisjoint(Reaction.TESTS)       # the API takes them only once they work


def test_notify_names_an_alert_that_cannot_be_deleted_while_used(db):
    job = Job(JobKey="LOAD")
    alert = an_alert(db)
    db.add(job)
    db.flush()
    reaction = Reaction(Job_MasterObject_id=job.MasterObject_id, WhenTest="FAILED", Section="ALSO")
    reaction.actions.append(ReactionAction(Action="NOTIFY", Alert_id=alert.id, SkipIfCauseLate=True))
    db.add(reaction)
    db.commit()
    assert [r.Address for r in alert.recipients] == ["a@example.com", "b@example.com"]
    assert reaction.actions[0].alert is alert and reaction.actions[0].SkipIfCauseLate is True
    db.delete(alert)
    with pytest.raises(REFUSED):
        db.commit()


def test_a_run_and_an_item_carry_a_late_flag_apart_from_their_status(db):
    run = JobRun(RunID="w1", JobKey="FLOW", SchedulerInstanceID="I", JobType="WORKFLOW", Status="RUNNING")
    db.add(run)
    db.flush()
    due = utcnow()
    item = WorkflowRunItem(WorkflowRun_id=run.id, Path="X", ItemName="X", JobKey="X", ReadyDateTime=due,
                           LateDateTime=due, LateReason="'X' not started by 03:00",
                           LateCause="waiting for 'U', which has been running since 01:10")
    db.add(item)
    db.commit()
    assert (item.Status, item.LateReason, item.ReadyDateTime) == ("PENDING", "'X' not started by 03:00", due)
    assert (run.LateDateTime, run.LateReason, run.LateCause) == (None, None, None)


def test_deleting_an_alert_keeps_its_deliveries(db):
    alert = an_alert(db)
    db.add(AlertDelivery(Alert_id=alert.id, AlertName="Ops", RunID="r1", WorkflowPath="X", Recipients="a@example.com",
                         Subject="s", Body="b"))
    db.commit()
    db.delete(alert)
    db.commit()
    delivery = db.query(AlertDelivery).one()
    assert (delivery.Alert_id, delivery.AlertName, delivery.Status, delivery.Attempts, delivery.IsTest) == (
        None, "Ops", "PENDING", 0, False)
    assert db.query(AlertRecipient).count() == 0


def test_an_alert_name_is_unique(db):
    an_alert(db)
    db.add(Alert(Name="Ops", Subject="s", Message="m"))
    with pytest.raises(REFUSED):
        db.commit()


def test_mail_settings_keep_the_login_as_a_credential(db):
    login = Credential(Name="MailLogin", CredType="PASSWORD", SecretData="not shown")
    db.add(login)
    db.flush()
    db.add(MailSetting(id=1, Host="localhost", Port=8025, SenderAddress="autoapp@example.com",
                       Credential_MasterObject_id=login.MasterObject_id))
    db.commit()
    settings = db.query(MailSetting).one()
    assert (settings.Port, settings.UseTls, settings.credential.Name) == (8025, False, "MailLogin")


def test_the_migration_adds_what_phase_8_needs_and_keeps_the_data(tmp_path):
    database = tmp_path / "phase7.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    engine.dispose()
    connection = sqlite3.connect(database)
    connection.execute("DROP TABLE ReactionActions")        # rebuilt below: SQLite cannot drop a column with a foreign key
    for table in NEW_TABLES:
        connection.execute(f"DROP TABLE {table}")
    for table, column in NEW_COLUMNS:
        connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    connection.execute("CREATE TABLE ReactionActions (id INTEGER PRIMARY KEY, Reaction_id INTEGER, ActionOrder INTEGER, "
                       "Action VARCHAR(30), MaxTimes INTEGER, WaitSeconds INTEGER, RerunMode VARCHAR(10), "
                       "TargetItem_id INTEGER, TargetJob_MasterObject_id INTEGER)")
    connection.execute("INSERT INTO MasterObjects (id, ObjectType) VALUES (1, 'JOB')")
    connection.execute("INSERT INTO Jobs (MasterObject_id, JobKey) VALUES (1, 'OLD_JOB')")
    connection.execute("INSERT INTO Reactions (Job_MasterObject_id, WhenTest) VALUES (1, 'FAILED')")
    connection.execute("INSERT INTO ReactionActions (Reaction_id, ActionOrder, Action) VALUES (1, 1, 'COUNT_AS_FAILED')")
    connection.execute("INSERT INTO JobRuns (RunID, JobKey, SchedulerInstanceID, Status) VALUES ('r1', 'OLD_JOB', 'I', 'SUCCESS')")
    connection.commit()

    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    outputs = [subprocess.run([sys.executable, str(MIGRATION)], env=env, check=True, capture_output=True, text=True).stdout
               for _ in range(2)]                  # a second run finds nothing to do
    assert "Added columns: none" in outputs[1] and "Added tables: none" in outputs[1]

    assert connection.execute("SELECT Action, Alert_id, SkipIfCauseLate FROM ReactionActions").fetchall() == [
        ("COUNT_AS_FAILED", None, 0)]
    assert connection.execute("SELECT RunID, Status, LateDateTime FROM JobRuns").fetchall() == [("r1", "SUCCESS", None)]
    assert connection.execute("SELECT WhenTest, WhenTimeKind FROM Reactions").fetchall() == [("FAILED", None)]
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(NEW_TABLES) <= tables


def test_an_event_for_a_job_that_never_started_has_no_job_run(db):
    flow = JobRun(RunID="w1", JobKey="FLOW", SchedulerInstanceID="I", JobType="WORKFLOW", Status="RUNNING")
    db.add(flow)
    db.flush()
    db.add(ReactionEvent(JobRun_id=None, WorkflowRun_id=flow.id, WorkflowPath="X", Action="MARK_AS_LATE",
                         Message="'X' not started by 03:00"))
    db.commit()
    event = db.query(ReactionEvent).one()
    assert (event.JobRun_id, event.WorkflowRun_id, event.WorkflowPath) == (None, flow.id, "X")


def test_the_migration_lets_old_events_stay_while_new_ones_may_have_no_job_run(tmp_path):
    database = tmp_path / "required.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    engine.dispose()
    connection = sqlite3.connect(database)
    connection.execute("DROP TABLE ReactionEvents")             # as Phase 7 had it: a job run was required
    connection.execute("CREATE TABLE ReactionEvents (id INTEGER PRIMARY KEY AUTOINCREMENT, JobRun_id INTEGER NOT NULL "
                       "REFERENCES JobRuns(id) ON DELETE CASCADE, WorkflowRun_id INTEGER REFERENCES JobRuns(id) "
                       "ON DELETE CASCADE, WorkflowPath VARCHAR(1000), ReactionAction_id INTEGER REFERENCES "
                       "ReactionActions(id) ON DELETE SET NULL, Action VARCHAR(30) NOT NULL, "
                       "Result VARCHAR(20) NOT NULL DEFAULT 'TOOK_EFFECT', Message TEXT, EventDateTime DATETIME NOT NULL)")
    connection.execute("CREATE INDEX ix_ReactionEvents_JobRun_id ON ReactionEvents (JobRun_id)")
    connection.execute("INSERT INTO JobRuns (RunID, JobKey, SchedulerInstanceID, Status) VALUES ('r1', 'J', 'I', 'SUCCESS')")
    connection.execute("INSERT INTO ReactionEvents (JobRun_id, Action, Message, EventDateTime) "
                       "VALUES (1, 'RERUN', 'kept', '2026-10-01 00:00:00')")
    connection.commit()

    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    outputs = [subprocess.run([sys.executable, str(MIGRATION)], env=env, check=True, capture_output=True, text=True).stdout
               for _ in range(2)]
    assert "changed now" in outputs[0] and "already so" in outputs[1]

    assert connection.execute("SELECT JobRun_id, Action, Result, Message FROM ReactionEvents").fetchall() == [
        (1, "RERUN", "TOOK_EFFECT", "kept")]
    connection.execute("INSERT INTO ReactionEvents (JobRun_id, Action, EventDateTime) VALUES (NULL, 'NOTIFY', '2026-10-02')")
    connection.commit()
    indexes = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE tbl_name = 'ReactionEvents' AND type = 'index'")]
    assert "ix_ReactionEvents_JobRun_id" in indexes

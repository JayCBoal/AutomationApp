#!/usr/bin/env python3
"""
Brings a database built before workflows Phase 8, step 1 (2026-10-23) up to date, keeping its data.

    DATABASE_URL=... python3 SQL/migrate_late_alerts.py

Adds, where it is missing:
    Reactions.WhenTimeKind, WhenClockTime, WhenMinutes, WhenPercent, WhenRunCount (the time Whens)
    ReactionActions.Alert_id, SkipIfCauseLate (Notify)
    JobRuns and WorkflowRunItems: LateDateTime, LateReason, LateCause (the Late flag)
    WorkflowRunItems.ReadyDateTime (when an item's own prerequisites were met)
    ReactionEvents.JobRun_id may now be empty: a job that never started has no run to point at
    the tables Alerts, AlertRecipients, AlertDeliveries and MailSettings

Nothing already there changes: no Reaction, run or item behaves differently until a time When is saved.
Works on SQLite and MariaDB, and can be run again safely. Nothing is dropped or renamed. Back up a
database you care about first.
Needs the Restarts migration (migrate_restarts.py) to have run first.
"""
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "autoapp"))
sys.path.insert(0, str(REPO_DIR / "SQL"))

from sqlalchemy import create_engine, inspect, text

from core.models import Alert, AlertDelivery, AlertRecipient, MailSetting, ReactionEvent
from migrate_workflows import add_missing_columns as add_columns

LATE = [("LateDateTime", "{datetime} NULL"), ("LateReason", "TEXT NULL"), ("LateCause", "TEXT NULL")]
COLUMNS = (
    [("Reactions", "WhenTimeKind", "VARCHAR(12) NULL", None),
     ("Reactions", "WhenClockTime", "VARCHAR(5) NULL", None),
     ("Reactions", "WhenMinutes", "INTEGER NULL", None),
     ("Reactions", "WhenPercent", "INTEGER NULL", None),
     ("Reactions", "WhenRunCount", "INTEGER NULL", None),
     ("ReactionActions", "Alert_id", "INTEGER NULL", "Alerts(id) ON DELETE RESTRICT"),
     ("ReactionActions", "SkipIfCauseLate", "BOOLEAN NOT NULL DEFAULT 0", None),
     ("WorkflowRunItems", "ReadyDateTime", "{datetime} NULL", None)]
    + [(table, name, definition, None) for table in ("JobRuns", "WorkflowRunItems") for name, definition in LATE]
)
# Alerts first: AlertRecipients and AlertDeliveries refer to it
NEW_TABLES = [Alert.__table__, AlertRecipient.__table__, AlertDelivery.__table__, MailSetting.__table__]


def add_tables(connection) -> list:
    existing = set(inspect(connection).get_table_names())
    missing = [table for table in NEW_TABLES if table.name not in existing]
    for table in missing:
        table.create(connection)
    return [table.name for table in missing]


def event_run_is_required(connection) -> bool:
    columns = inspect(connection).get_columns("ReactionEvents")
    return not next(c for c in columns if c["name"] == "JobRun_id")["nullable"]


def allow_events_without_a_run(connection) -> bool:
    """Makes ReactionEvents.JobRun_id optional, keeping every row. Returns whether it had to."""
    if not event_run_is_required(connection):
        return False
    if connection.dialect.name in ("mysql", "mariadb"):
        connection.execute(text("ALTER TABLE ReactionEvents MODIFY JobRun_id INTEGER NULL"))
        return True
    # SQLite cannot change a column in place: the table is rebuilt and its rows copied across
    connection.execute(text("ALTER TABLE ReactionEvents RENAME TO ReactionEvents_old"))
    for index in inspect(connection).get_indexes("ReactionEvents_old"):
        connection.execute(text(f"DROP INDEX {index['name']}"))
    ReactionEvent.__table__.create(connection)
    names = ", ".join(column.name for column in ReactionEvent.__table__.columns)
    connection.execute(text(f"INSERT INTO ReactionEvents ({names}) SELECT {names} FROM ReactionEvents_old"))
    connection.execute(text("DROP TABLE ReactionEvents_old"))
    return True


def migrate(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        # The tables go in first: ReactionActions.Alert_id refers to Alerts
        tables = add_tables(connection)
        added = add_columns(connection, COLUMNS)
        changed = allow_events_without_a_run(connection)
    engine.dispose()
    print(f"Added tables: {', '.join(tables) if tables else 'none (all were there)'}.")
    print(f"Added columns: {', '.join(added) if added else 'none (all were there)'}.")
    print(f"Reaction events may be without a job run: {'changed now' if changed else 'already so'}.")


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL to the database to bring up to date.")
    migrate(url)

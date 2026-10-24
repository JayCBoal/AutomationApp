#!/usr/bin/env python3
"""
Brings a database built before workflows Phase 3 (2026-10-18) up to date, keeping its data.

    DATABASE_URL=... python3 SQL/migrate_reactions.py

Adds, where they are missing:
    WorkflowItems.DisabledHere, WorkflowItems.ReactionsOverridden
    JobRuns.KillRequestedDateTime, JobRuns.ProcessID, JobRuns.StatusBeforeOverride
    WorkflowRunItems.StatusBeforeOverride, WorkflowRunItems.ProcessID
    the tables Reactions, ReactionActions and ReactionEvents
No existing value changes: a workflow's jobs are not disabled here, and no use overrides
its job's Reactions.

Works on SQLite and MariaDB, and can be run again safely: what is already there
is left alone. Nothing is dropped or renamed. Back up a database you care about first.
Needs the workflows migration (migrate_workflows.py) to have run first.
"""
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "autoapp"))
sys.path.insert(0, str(REPO_DIR / "SQL"))

from sqlalchemy import create_engine, inspect

from core.models import Reaction, ReactionAction, ReactionEvent
from migrate_workflows import add_missing_columns as add_columns

# (table, column, its definition for ALTER TABLE ... ADD COLUMN, the foreign key it carries or None)
COLUMNS = [
    ("WorkflowItems", "DisabledHere", "VARCHAR(20) NULL", None),
    ("WorkflowItems", "ReactionsOverridden", "BOOLEAN NOT NULL DEFAULT 0", None),
    ("JobRuns", "KillRequestedDateTime", "{datetime} NULL", None),
    ("JobRuns", "ProcessID", "INTEGER NULL", None),
    ("JobRuns", "StatusBeforeOverride", "VARCHAR(20) NULL", None),
    ("WorkflowRunItems", "StatusBeforeOverride", "VARCHAR(20) NULL", None),
    ("WorkflowRunItems", "ProcessID", "INTEGER NULL", None),
]
NEW_TABLES = [Reaction.__table__, ReactionAction.__table__, ReactionEvent.__table__]


def add_missing_tables(connection) -> list:
    existing = set(inspect(connection).get_table_names())
    missing = [table for table in NEW_TABLES if table.name not in existing]
    for table in missing:
        table.create(connection)
    return [table.name for table in missing]


def migrate(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        added = add_columns(connection, COLUMNS)
        tables = add_missing_tables(connection)
    engine.dispose()
    print(f"Added columns: {', '.join(added) if added else 'none (all were there)'}.")
    print(f"Added tables: {', '.join(tables) if tables else 'none (all were there)'}.")


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL to the database to bring up to date.")
    migrate(url)

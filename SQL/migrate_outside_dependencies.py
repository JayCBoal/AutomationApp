#!/usr/bin/env python3
"""
Brings a database built before outside dependencies (workflows Phase 5, 2026-10-19) up to date,
keeping its data.

    DATABASE_URL=... python3 SQL/migrate_outside_dependencies.py

Adds, where they are missing:
    WorkflowItems.OnUnmet
    WorkflowPrerequisites: Kind, TargetName, TargetJob_MasterObject_id, LookBackHours, OnlyAfterStart,
        Endpoint_MasterObject_id, FilePattern, MinAgeSeconds, TimeCondition, WaitMode, WaitMinutes,
        WaitUntil, WaitFrom, WaitFromPrerequisite_id, Required
    the table WorkflowPrerequisiteChecks
Every prerequisite already there stays what it was: a job in its own workflow (Kind JOB), waiting
with no limit as before, and every job still ends Not run when it cannot start (OnUnmet NOT_RUN).
The default wait is a setting with a default of its own, so it needs nothing in the database.

Works on SQLite and MariaDB, and can be run again safely: what is already there
is left alone. Nothing is dropped or renamed. Back up a database you care about first.
Needs the earlier workflow migrations (up to migrate_workflow_variables.py) to have run first.
"""
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "autoapp"))
sys.path.insert(0, str(REPO_DIR / "SQL"))

from sqlalchemy import create_engine, inspect

from app.models import WorkflowPrerequisiteCheck
from migrate_workflows import add_missing_columns as add_columns

P = "WorkflowPrerequisites"
# (table, column, its definition for ALTER TABLE ... ADD COLUMN, the foreign key it carries or None)
COLUMNS = [
    ("WorkflowItems", "OnUnmet", "VARCHAR(10) NOT NULL DEFAULT 'NOT_RUN'", None),
    (P, "Kind", "VARCHAR(12) NOT NULL DEFAULT 'JOB'", None),
    (P, "TargetName", "VARCHAR(100) NULL", None),
    (P, "TargetJob_MasterObject_id", "INTEGER NULL", "Jobs(MasterObject_id) ON DELETE RESTRICT"),
    (P, "LookBackHours", "INTEGER NULL", None),
    (P, "OnlyAfterStart", "BOOLEAN NOT NULL DEFAULT 0", None),
    (P, "Endpoint_MasterObject_id", "INTEGER NULL", "Endpoints(MasterObject_id) ON DELETE RESTRICT"),
    (P, "FilePattern", "VARCHAR(256) NULL", None),
    (P, "MinAgeSeconds", "INTEGER NULL", None),
    (P, "TimeCondition", "TEXT NULL", None),
    (P, "WaitMode", "VARCHAR(10) NOT NULL DEFAULT 'DEFAULT'", None),
    (P, "WaitMinutes", "INTEGER NULL", None),
    (P, "WaitUntil", "VARCHAR(5) NULL", None),
    (P, "WaitFrom", "VARCHAR(10) NOT NULL DEFAULT 'OTHERS'", None),
    (P, "WaitFromPrerequisite_id", "INTEGER NULL", "WorkflowPrerequisites(id) ON DELETE SET NULL"),
    (P, "Required", "BOOLEAN NOT NULL DEFAULT 1", None),
    ("WorkflowPrerequisiteChecks", "Attempt", "INTEGER NOT NULL DEFAULT 1", None),
    ("WorkflowPrerequisiteChecks", "SeenStatus", "VARCHAR(20) NULL", None),
]


def add_missing_tables(connection) -> list:
    existing = set(inspect(connection).get_table_names())
    if WorkflowPrerequisiteCheck.__tablename__ in existing:
        return []
    WorkflowPrerequisiteCheck.__table__.create(connection)
    return [WorkflowPrerequisiteCheck.__tablename__]


def migrate(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        tables = add_missing_tables(connection)
        added = add_columns(connection, COLUMNS)
    engine.dispose()
    print(f"Added columns: {', '.join(added) if added else 'none (all were there)'}.")
    print(f"Added tables: {', '.join(tables) if tables else 'none (all were there)'}.")


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL to the database to bring up to date.")
    migrate(url)

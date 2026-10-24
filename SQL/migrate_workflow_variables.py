#!/usr/bin/env python3
"""
Brings a database built before workflow variables (the rest of workflows Phase 4, 2026-10-19)
up to date, keeping its data.

    DATABASE_URL=... python3 SQL/migrate_workflow_variables.py

Adds, where they are missing:
    JobRuns.WorkflowVariables
    the table WorkflowItemVariables
No existing value changes: runs from before have no variables fixed, and no use has variables
of its own. The Variable precedence setting needs nothing: a saved order gets the two new
levels, Workflow and This use, in their places when it is read (engine/settings.py).

Works on SQLite and MariaDB, and can be run again safely: what is already there
is left alone. Nothing is dropped or renamed. Back up a database you care about first.
Needs the earlier workflow migrations (up to migrate_conditions.py) to have run first.
"""
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "autoapp"))
sys.path.insert(0, str(REPO_DIR / "SQL"))

from sqlalchemy import create_engine, inspect

from core.models import WorkflowItemVariable
from migrate_workflows import add_missing_columns as add_columns

# (table, column, its definition for ALTER TABLE ... ADD COLUMN, the foreign key it carries or None)
COLUMNS = [
    ("JobRuns", "WorkflowVariables", "TEXT NULL", None),
]


def add_missing_tables(connection) -> list:
    existing = set(inspect(connection).get_table_names())
    if WorkflowItemVariable.__tablename__ in existing:
        return []
    WorkflowItemVariable.__table__.create(connection)
    return [WorkflowItemVariable.__tablename__]


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

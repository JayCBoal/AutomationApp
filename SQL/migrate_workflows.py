#!/usr/bin/env python3
"""
Brings a database built before workflows (2026-10-17) up to date, keeping its data.

    DATABASE_URL=... python3 SQL/migrate_workflows.py

Adds, where they are missing:
    Jobs.JobType, Jobs.Owner_MasterObject_id, Jobs.SuccessReturnCodes
    JobRuns.ReturnCode, JobRuns.Reason, JobRuns.JobType, JobRuns.ParentRun_id,
    JobRuns.WorkflowPath, JobRuns.Attempt, JobRuns.CancelRequestedDateTime
    the tables WorkflowItems, WorkflowPrerequisites and WorkflowRunItems
Every existing job becomes a STEPS job, and every finished run gets the return code
its status implies (0 for SUCCESS, 1 for FAILED), as the runner reported then.

Works on SQLite and MariaDB, and can be run again safely: what is already there
is left alone. Nothing is dropped or renamed. Back up a database you care about first.
"""
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "autoapp"))

from sqlalchemy import create_engine, inspect, text

from app.models import WorkflowItem, WorkflowPrerequisite, WorkflowRunItem

# (table, column, its definition for ALTER TABLE ... ADD COLUMN, the foreign key it carries or None)
COLUMNS = [
    ("Jobs", "JobType", "VARCHAR(20) NOT NULL DEFAULT 'STEPS'", None),
    ("Jobs", "Owner_MasterObject_id", "INTEGER NULL", "Jobs(MasterObject_id) ON DELETE CASCADE"),
    ("Jobs", "SuccessReturnCodes", "VARCHAR(100) NULL", None),
    ("JobRuns", "ReturnCode", "INTEGER NULL", None),
    ("JobRuns", "Reason", "VARCHAR(40) NULL", None),
    ("JobRuns", "JobType", "VARCHAR(20) NOT NULL DEFAULT 'STEPS'", None),
    ("JobRuns", "ParentRun_id", "INTEGER NULL", "JobRuns(id) ON DELETE SET NULL"),
    ("JobRuns", "WorkflowPath", "VARCHAR(1000) NULL", None),
    ("JobRuns", "Attempt", "INTEGER NOT NULL DEFAULT 1", None),
    ("JobRuns", "CancelRequestedDateTime", "{datetime} NULL", None),
]
NEW_TABLES = [WorkflowItem.__table__, WorkflowPrerequisite.__table__, WorkflowRunItem.__table__]


def add_missing_columns(connection) -> list:
    """Adds each column the database lacks. Returns the names of those added."""
    inspector = inspect(connection)
    mariadb = connection.dialect.name in ("mysql", "mariadb")
    added = []
    for table, column, definition, reference in COLUMNS:
        if column in {c["name"] for c in inspector.get_columns(table)}:
            continue
        definition = definition.format(datetime="DATETIME(6)" if mariadb else "DATETIME")
        if reference and not mariadb:
            definition += f" REFERENCES {reference}"
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        if reference and mariadb:
            # MariaDB ignores REFERENCES written on a column; the constraint is added on its own
            connection.execute(text(
                f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_{column} FOREIGN KEY ({column}) REFERENCES {reference}"))
        added.append(f"{table}.{column}")
    if "JobRuns.ParentRun_id" in added:
        connection.execute(text("CREATE INDEX ix_JobRuns_ParentRun_id ON JobRuns (ParentRun_id)"))
    return added


def add_missing_tables(connection) -> list:
    existing = set(inspect(connection).get_table_names())
    missing = [table for table in NEW_TABLES if table.name not in existing]
    for table in missing:
        table.create(connection)
    return [table.name for table in missing]


def fill_return_codes(connection) -> int:
    """Finished runs from before return codes were recorded: 0 for SUCCESS, 1 for FAILED."""
    result = connection.execute(text(
        "UPDATE JobRuns SET ReturnCode = CASE Status WHEN 'SUCCESS' THEN 0 ELSE 1 END "
        "WHERE ReturnCode IS NULL AND Status IN ('SUCCESS', 'FAILED')"))
    return result.rowcount


def migrate(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        added = add_missing_columns(connection)
        tables = add_missing_tables(connection)
        filled = fill_return_codes(connection)
    engine.dispose()
    print(f"Added columns: {', '.join(added) if added else 'none (all were there)'}.")
    print(f"Added tables: {', '.join(tables) if tables else 'none (all were there)'}.")
    print(f"Gave {filled} finished run(s) the return code their status implies.")


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL to the database to bring up to date.")
    migrate(url)

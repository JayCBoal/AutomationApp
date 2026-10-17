#!/usr/bin/env python3
"""
Brings a database built before flow control (2026-10-16) up to date, keeping its data.

    DATABASE_URL=... python3 SQL/migrate_flow_control.py

Adds, where they are missing:
    JobSteps.ParentStep_id, JobSteps.StepName, JobSteps.OnFailure
    Operations.StepNumber, Operations.Iteration
and gives every step without a name one made from its title, as the editor would.

Works on SQLite and MariaDB, and can be run again safely: what is already there
is left alone. Nothing is dropped or renamed. Back up a database you care about first.
"""
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "autoapp"))

from sqlalchemy import create_engine, inspect, text

from app.job_store import name_from_title

# (table, column, its definition for ALTER TABLE ... ADD COLUMN)
COLUMNS = [
    ("JobSteps", "ParentStep_id", "INTEGER NULL REFERENCES JobSteps(id) ON DELETE CASCADE"),
    ("JobSteps", "StepName", "VARCHAR(64) NULL"),
    ("JobSteps", "OnFailure", "VARCHAR(20) NOT NULL DEFAULT 'FAIL_JOB'"),
    ("Operations", "StepNumber", "VARCHAR(50) NULL"),
    ("Operations", "Iteration", "VARCHAR(50) NULL"),
]


def add_missing_columns(connection) -> list:
    """Adds each column the database lacks. Returns the names of those added."""
    inspector = inspect(connection)
    mariadb = connection.dialect.name in ("mysql", "mariadb")
    added = []
    for table, column, definition in COLUMNS:
        if column in {c["name"] for c in inspector.get_columns(table)}:
            continue
        if mariadb and "REFERENCES" in definition:
            # MariaDB ignores REFERENCES written on a column; the constraint is added on its own
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER NULL"))
            connection.execute(text(
                f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_{column} FOREIGN KEY ({column}) "
                f"REFERENCES {table}(id) ON DELETE CASCADE"))
        else:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        added.append(f"{table}.{column}")
    return added


def name_unnamed_steps(connection) -> int:
    """Gives each step without a StepName one made from its title. Returns how many were named."""
    rows = connection.execute(text(
        "SELECT id, StepTitle, StepOrder FROM JobSteps WHERE StepName IS NULL OR StepName = ''")).all()
    for step_id, title, order in rows:
        connection.execute(text("UPDATE JobSteps SET StepName = :name WHERE id = :id"),
                           {"name": name_from_title(title, order or 1), "id": step_id})
    return len(rows)


def migrate(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        added = add_missing_columns(connection)
        named = name_unnamed_steps(connection)
    engine.dispose()
    print(f"Added: {', '.join(added) if added else 'nothing (all columns were there)'}.")
    print(f"Named {named} step(s) from their titles.")


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL to the database to bring up to date.")
    migrate(url)

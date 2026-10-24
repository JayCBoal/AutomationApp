#!/usr/bin/env python3
"""
Brings a database built before workflows Phase 7, step 3a (2026-10-20) up to date, keeping its data.

    DATABASE_URL=... python3 SQL/migrate_restarts.py

Adds, where it is missing:
    ReactionActions.RerunMode (RESTART or RESUME)
    the table RunRestarts (2026-10-22, step 5): the record of each time an operator ran a run again
Every Rerun this job that exists becomes RESTART, so nothing that ran before runs differently.
A Rerun saved from now on without a choice is RESUME. Runs restarted before the table existed have no row in it.

Works on SQLite and MariaDB, and can be run again safely: what is already there is left alone.
Nothing is dropped or renamed. Back up a database you care about first.
Needs the Reactions migration (migrate_reactions.py) to have run first.
"""
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "autoapp"))
sys.path.insert(0, str(REPO_DIR / "SQL"))

from sqlalchemy import create_engine, inspect, text

from core.models import RunRestart
from migrate_workflows import add_missing_columns as add_columns

COLUMNS = [("ReactionActions", "RerunMode", "VARCHAR(10) NULL", None)]
NEW_TABLES = [RunRestart.__table__]


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
        changed = connection.execute(text(
            "UPDATE ReactionActions SET RerunMode = 'RESTART' WHERE Action = 'RERUN' AND RerunMode IS NULL")).rowcount
    engine.dispose()
    print(f"Added columns: {', '.join(added) if added else 'none (all were there)'}.")
    print(f"Added tables: {', '.join(tables) if tables else 'none (all were there)'}.")
    print(f"Rerun this job set to Restart from the beginning: {changed}.")


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL to the database to bring up to date.")
    migrate(url)

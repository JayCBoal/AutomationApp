#!/usr/bin/env python3
"""
Moves job logs out of the database (2026-10-17): each run's log becomes a file on the host that
ran it, as core/log_files.py lays them out, and the run's record says where.

    DATABASE_URL=... AUTOAPP_LOG_ROOT=... python3 SQL/migrate_log_files.py

AUTOAPP_LOG_ROOT is where the files go: the log root the server and runners use (if unset, the
logs folder beside the runner, autoapp/logs).

  - adds JobRuns.LogFile and JobRuns.LogRemovedDateTime, where they are missing;
  - writes each run's rows from JobRunLogs to <log root>/<host>/<YYYY-MM-DD>/<RunID>.log, the
    date being the day the run started, and records the file on the run;
  - drops the JobRunLogs table, with the owner's approval (2026-10-17): its logs are now files.

Works on SQLite and MariaDB, and can be run again safely: a database already moved is left alone.
Back up a database you care about first.
"""
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "autoapp"))

from sqlalchemy import create_engine, inspect, text

from core import log_files

# (column, its definition for ALTER TABLE ... ADD COLUMN)
COLUMNS = [("LogFile", "VARCHAR(500) NULL"), ("LogRemovedDateTime", "{datetime} NULL")]


def add_missing_columns(connection) -> list:
    mariadb = connection.dialect.name in ("mysql", "mariadb")
    existing = {c["name"] for c in inspect(connection).get_columns("JobRuns")}
    added = []
    for column, definition in COLUMNS:
        if column not in existing:
            definition = definition.format(datetime="DATETIME(6)" if mariadb else "DATETIME")
            connection.execute(text(f"ALTER TABLE JobRuns ADD COLUMN {column} {definition}"))
            added.append(column)
    return added


def write_log_files(connection) -> int:
    """Writes each run's logged lines to its file, and records where. Returns how many runs had a log."""
    runs = connection.execute(text(
        "SELECT r.id, r.RunID, r.Host, r.StartedDateTime FROM JobRuns r "
        "WHERE r.LogFile IS NULL AND EXISTS (SELECT 1 FROM JobRunLogs l WHERE l.JobRun_id = r.id)")).all()
    for run_id, run_key, host, started in runs:
        chunks = connection.execute(text("SELECT LogText FROM JobRunLogs WHERE JobRun_id = :id ORDER BY Seq"),
                                    {"id": run_id}).scalars().all()
        log_file = log_files.new_log_file(run_key, _as_datetime(started))
        path = log_files.host_folder(host) / log_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(chunk + "\n" for chunk in chunks), encoding="utf-8")
        connection.execute(text("UPDATE JobRuns SET LogFile = :file WHERE id = :id"), {"file": log_file, "id": run_id})
    return len(runs)


def _as_datetime(value):
    """SQLite gives a stored time back as text."""
    from datetime import datetime
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def migrate(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        added = add_missing_columns(connection)
        had_table = "JobRunLogs" in inspect(connection).get_table_names()
        written = write_log_files(connection) if had_table else 0
        if had_table:
            connection.execute(text("DROP TABLE JobRunLogs"))
    engine.dispose()
    print(f"Added columns: {', '.join('JobRuns.' + c for c in added) if added else 'none (both were there)'}.")
    print(f"Wrote {written} run log(s) to files under {log_files.log_root()}.")
    print("Dropped the JobRunLogs table." if had_table else "There was no JobRunLogs table to move.")


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL to the database to bring up to date.")
    migrate(url)

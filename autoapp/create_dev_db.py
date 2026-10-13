#!/usr/bin/env python3
"""
Creates a development database with the sample data from SQL/Seed_Sample_Data.sql.

    cd autoapp
    python3 create_dev_db.py

The database is the one DATABASE_URL names (default: autoapp.db in this folder).
It must be empty or not exist yet: this script never deletes anything. To start
again, delete autoapp.db and run it once more.

It also creates the sample input files the first job collects, and prints the
commands to run next.
"""
import re
import sys
from pathlib import Path

from sqlalchemy import inspect

from app.catalog import sync_catalog
from app.database import DATABASE_URL, SessionLocal, engine
from app.models import Application, Base, Variable

SEED_FILE = Path(__file__).resolve().parents[1] / "SQL" / "Seed_Sample_Data.sql"


def sql_statements(script: str) -> list:
    """Splits a SQL script into statements, dropping comment lines."""
    without_comments = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in re.split(r";\s*$", without_comments, flags=re.MULTILINE) if s.strip()]


def load_seed(db) -> None:
    # Sent to the database exactly as written: the script contains ${...} and ':' that are not for us to interpret
    connection = db.connection()
    for statement in sql_statements(SEED_FILE.read_text()):
        connection.exec_driver_sql(statement)
    db.commit()


def create_sample_files(db) -> Path:
    """Puts two extract files, and one file the job should ignore, in the legal application's outbox."""
    root = (
        db.query(Variable.VarValue)
        .join(Application, Application.MasterObject_id == Variable.MasterObject_id)
        .filter(Application.Name == "LEGAL_APP", Variable.VarName == "Root")
        .scalar()
    )
    outbox = Path(root) / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    (outbox / "Legal_Batch_001.csv").write_text("client,amount\nACME,100\n")
    (outbox / "Legal_Batch_002.csv").write_text("client,amount\nGLOBEX,250\nINITECH,75\n")
    (outbox / "readme.txt").write_text("Not part of the batch; the job should leave this alone.\n")
    return outbox


def main():
    existing = inspect(engine).get_table_names()
    if existing:
        sys.exit(f"{DATABASE_URL} already contains tables, so nothing was changed.\n"
                 "To start again with a SQLite database, delete the autoapp.db file and run this once more.")

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        load_seed(db)
        sync_catalog(db)
        outbox = create_sample_files(db)
    finally:
        db.close()

    print(f"Created {DATABASE_URL} with the sample data.")
    print(f"Sample input files are in {outbox}")
    print("""
Try it (from this folder):

  python3 -m engine.runner --job-key DEV-LEGAL-COLLECT_AND_DELIVER --instance-id 1001 --working-root /tmp/autoapp_sample/work
  python3 -m engine.runner --job-key DEV-BILLING-LOAD --instance-id 1002 --working-root /tmp/autoapp_sample/work
  python3 -m engine.spool_delivery

  python3 -m uvicorn app.main:app --port 8000
      then open  http://localhost:8000/   and choose Operations Log
""")


if __name__ == "__main__":
    main()

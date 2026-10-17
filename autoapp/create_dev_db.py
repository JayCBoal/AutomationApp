#!/usr/bin/env python3
"""
Creates a development database with the sample data from SQL/Seed_Sample_Data.sql.

    cd autoapp
    python3 create_dev_db.py

The database is the one DATABASE_URL names (default: autoapp.db in this folder).
It must be empty or not exist yet: this script never deletes anything. To start
again, delete autoapp.db and run it once more.

It also creates the sample input files the first job collects and the sample
sales database the export jobs query (SQL/Sample_Sales_Data.sql, as SQLite, at
/tmp/autoapp_sample/sales.db), and prints the commands to run next.
"""
import re
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import inspect

from app.catalog import sync_catalog
from app.database import DATABASE_URL, SessionLocal, engine
from app.models import Application, Base, Variable

SEED_FILE = Path(__file__).resolve().parents[1] / "SQL" / "Seed_Sample_Data.sql"
SALES_FILE = Path(__file__).resolve().parents[1] / "SQL" / "Sample_Sales_Data.sql"
SALES_DB = Path("/tmp/autoapp_sample/sales.db")      # where the seed's SalesDbUrl variable points


def sql_statements(script: str) -> list:
    """Splits a SQL script into statements, dropping comment lines."""
    without_comments = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in re.split(r";\s*$", without_comments, flags=re.MULTILINE) if s.strip()]


def load_seed(db) -> None:
    # Sent to the database exactly as written: the script contains ${...}, %{...} and ':' that are not for us
    # to interpret. Straight to the driver's own cursor with no parameters, as MariaDB's driver otherwise
    # reads each % as the start of a parameter.
    cursor = db.connection().connection.cursor()
    try:
        for statement in sql_statements(SEED_FILE.read_text()):
            cursor.execute(statement)
    finally:
        cursor.close()
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


def create_sales_db(path: Path = SALES_DB) -> bool:
    """Builds the sample sales database as SQLite. Leaves one that is already there alone."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SALES_FILE.read_text())
    return True


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
    made_sales_db = create_sales_db()

    print(f"Created {DATABASE_URL} with the sample data.")
    print(f"Sample input files are in {outbox}")
    print(f"{'Created' if made_sales_db else 'Kept the existing'} sample sales database {SALES_DB}")
    print("""
Try it (from this folder):

  python3 -m engine.runner --job-key DEV-LEGAL-COLLECT_AND_DELIVER --instance-id 1001 --working-root /tmp/autoapp_sample/work
  python3 -m engine.runner --job-key DEV-BILLING-LOAD --instance-id 1002 --working-root /tmp/autoapp_sample/work
  python3 -m engine.runner --job-key DEV-BILLING-INVOICE_EXPORT --instance-id 1003 --working-root /tmp/autoapp_sample/work
  python3 -m engine.runner --job-key DEV-FINANCE-LOAD_REPORTS --instance-id 1004 --working-root /tmp/autoapp_sample/work
  python3 -m engine.spool_delivery

  AUTOAPP_WORKING_ROOT=/tmp/autoapp_sample/work python3 -m uvicorn app.main:app --port 8000
      then open  http://localhost:8000/   and choose Jobs or Operations Log
""")


if __name__ == "__main__":
    main()

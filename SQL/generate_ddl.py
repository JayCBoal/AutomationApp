#!/usr/bin/env python3
"""
Writes SQL/Create_Tables.sql, the MariaDB script that creates AutoApp's tables.

    python3 SQL/generate_ddl.py

The Python models in autoapp/app/models.py define the schema; this script turns
them into MariaDB statements. Run it after changing the models. Do not edit
Create_Tables.sql by hand.
"""
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "autoapp"))

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import Base

OUTPUT = Path(__file__).with_name("Create_Tables.sql")

# Tables that earlier versions of the schema created and this one does not
RETIRED_TABLES = ["AsyncInstances", "AsyncParentInstances", "Processes", "Sources", "Deliveries"]


def build() -> str:
    dialect = mysql.dialect()
    tables = list(Base.metadata.sorted_tables)      # parents before the tables that refer to them

    out = [
        "-- ============================================================================",
        "-- AutoApp schema for MariaDB",
        "--",
        "-- Generated from autoapp/app/models.py by SQL/generate_ddl.py.",
        "-- Do not edit by hand: change the models and run the script.",
        "--",
        "-- WARNING: this drops every AutoApp table, and the data in it, before",
        "-- creating the tables again.",
        "-- ============================================================================",
        "",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "",
    ]
    out += [f"DROP TABLE IF EXISTS {name};" for name in RETIRED_TABLES]
    out += [f"DROP TABLE IF EXISTS {table.name};" for table in reversed(tables)]
    out += ["", "SET FOREIGN_KEY_CHECKS = 1;", ""]

    for table in tables:
        statement = str(CreateTable(table).compile(dialect=dialect)).strip()
        out += [statement + ";", ""]
        for index in sorted(table.indexes, key=lambda i: i.name):
            out += [str(CreateIndex(index).compile(dialect=dialect)).strip() + ";", ""]

    return "\n".join(out)


if __name__ == "__main__":
    OUTPUT.write_text(build())
    print(f"Wrote {OUTPUT.relative_to(REPO_DIR)}")

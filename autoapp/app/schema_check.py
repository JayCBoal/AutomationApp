"""
Compares the database's tables with the ones this version of RunMyFiles expects.

A database built by an earlier version lacks whatever has been added since.
Without this check that shows up as an unexplained "Internal Server Error" on
whichever page first needs the missing column.
"""
from typing import List

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from app.models import Base


def schema_problems(connection: Connection) -> List[str]:
    """What the models have that the database does not, e.g. ["StepDefinitions.DisplayOrder"]."""
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    problems = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            problems.append(f"table {table.name}")
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
        problems += [f"{table.name}.{column.name}" for column in table.columns if column.name not in existing_columns]
    return problems


def out_of_date_message(problems: List[str]) -> str:
    return (
        "The database is out of date for this version of RunMyFiles. It is missing: "
        + ", ".join(problems)
        + ". Rebuild it (see 'A development database' in the README), or add what is missing."
    )

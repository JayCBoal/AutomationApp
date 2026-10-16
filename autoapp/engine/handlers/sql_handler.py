"""
Run SQL: runs one statement against a database and, for a query, can write the
rows to a CSV file.

The database is given as a connection URL, normally held in a secret variable
so the password never appears in the job:

    Database    ${SalesDbUrl}       e.g. mysql+pymysql://user:password@host/sales
    Statement   SELECT ... FROM invoices WHERE invoice_date = '${DATE:yyyy-MM-dd}'
    ResultFile  out/invoices_${DATE:yyyyMMdd}.csv

The step is recorded as one operation, SQL, or SQL_EXPORT when it wrote a file.
The record names the database without its password. A CSV it wrote is the
start of that file's route in the file trace.
"""
import csv
import os
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from engine import job_log
from engine.handlers.base_handler import BaseHandler
from engine.step_catalog import BOOLEAN, DEST, LOCATION, STRING, TEXT, Param
from engine.telemetry_client import utc_now_iso

STATEMENT_KEPT = 2000      # characters of the statement kept in the operation record


def safe_url(url: str) -> str:
    """The connection URL with any password replaced by ***, for logs and records."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except (ArgumentError, ValueError):
        return "(not a valid database URL)"


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


class RunSqlHandler(BaseHandler):
    CODE = "RUN_SQL"
    NAME = "Run SQL"
    DESCRIPTION = "Runs one SQL statement; a query's rows can be written to a CSV file"

    PARAMETERS = (
        Param("Database", STRING, required=True,
              description="The database's connection URL, such as mysql+pymysql://user:password@host/name. "
                          "Keep it in a secret variable, such as ${SalesDbUrl}, so the password stays hidden."),
        Param("Statement", TEXT, required=True,
              description="One SQL statement. It may use variables, such as ${DATE:yyyy-MM-dd}."),
        Param("ResultFile", LOCATION, location_role=DEST,
              description="Where to write a query's rows as CSV, such as out/invoices_${DATE:yyyyMMdd}.csv"),
        Param("IncludeHeader", BOOLEAN, default="True", description="Start the CSV with a line of column names"),
        Param("Commit", BOOLEAN, default="False",
              description="Keep the changes the statement makes. Otherwise they are rolled back."),
        Param("Overwrite", BOOLEAN, default="False", description="Replace a result file of the same name"),
        Param("CreateFolder", BOOLEAN, default="True", description="Create the result file's folder if it does not exist"),
    )

    def describe(self, resolved_params: Dict[str, Any]) -> List[str]:
        """As for any step, but never with the database password, whether or not it came from a secret."""
        written = str(self.step_config.get("RawParams", {}).get("Database", ""))
        resolved = safe_url(resolved_params.get("Database") or "")
        lines = []
        for line in super().describe(resolved_params):
            if line.startswith("Database:"):
                # written in the job as a variable: show it, and what it came to without the password
                line = f"Database: {written}  (resolved: {resolved})" if "${" in written else f"Database: {resolved}"
            lines.append(line)
        return lines

    def execute_step(self, params: dict) -> dict:
        url, statement = params["Database"], params["Statement"].strip()
        result_file, commit = params.get("ResultFile"), params["Commit"]
        hidden = safe_url(url)
        details = {"Database": hidden, "Statement": statement[:STATEMENT_KEPT]}
        result = {"details": {"summary": [], "ops": []}}
        started_at = utc_now_iso()

        if result_file:
            if os.path.isdir(result_file):
                raise ValueError(f"'ResultFile' is a folder ({result_file}); give the CSV file's name.")
            if os.path.exists(result_file) and not params["Overwrite"]:
                raise FileExistsError(f"'{result_file}' already exists. Set Overwrite to True to replace it.")
            if params["CreateFolder"]:
                Path(result_file).parent.mkdir(parents=True, exist_ok=True)

        def failed(message: str):
            message = message.replace(url, hidden)     # the driver may repeat the URL, password and all
            self.record_operation("SQL", "FAILED", details, error=message, started_at=started_at)
            job_log.error(f"The statement failed on {hidden}: {message}")
            return message

        try:
            engine = create_engine(url, poolclass=NullPool)
        except (ArgumentError, ValueError, ImportError) as e:
            raise ValueError(failed(f"'Database' is not a database URL RunMyFiles can use: {e}")) from None

        job_log.detail(f"Running on {hidden}:\n\t{statement}")
        rows, columns, affected = [], [], None
        try:
            with engine.connect() as connection:
                with connection.begin() as transaction:
                    cursor = connection.exec_driver_sql(statement)
                    if cursor.returns_rows:
                        columns = list(cursor.keys())
                        rows = cursor.fetchall()
                    else:
                        affected = cursor.rowcount
                    if commit:
                        transaction.commit()
                    else:
                        transaction.rollback()
        except SQLAlchemyError as e:
            reason = str(getattr(e, "orig", None) or e).splitlines()[0]
            raise RuntimeError(failed(reason)) from None
        finally:
            engine.dispose()

        if columns:
            details["Rows"] = len(rows)
            result["details"]["summary"].append(f"The query returned {plural(len(rows), 'row')}.")
            for row in rows[:10]:
                job_log.debug("\t" + " | ".join("" if v is None else str(v) for v in row))
        else:
            details["RowsAffected"] = affected
            changed = f"The statement changed {plural(affected, 'row')}" if affected is not None and affected >= 0 \
                else "The statement ran"
            if commit:
                result["details"]["summary"].append(f"{changed}; committed.")
            else:
                result["details"]["summary"].append(f"{changed}; rolled back, as Commit is False.")
                if affected:
                    job_log.warning("The changes were rolled back. Set Commit to True to keep them.")

        if not result_file:
            self.record_operation("SQL", "SUCCESS", details, started_at=started_at)
            return result
        if not columns:
            raise ValueError(failed("'ResultFile' is set, but the statement returned no rows to write; "
                                    "only a query (such as SELECT) has rows."))

        partial = result_file + ".partial"
        try:
            with open(partial, "w", newline="", encoding="utf-8") as out:
                writer = csv.writer(out)
                if params["IncludeHeader"]:
                    writer.writerow(columns)
                writer.writerows(["" if v is None else v for v in row] for row in rows)
            os.replace(partial, result_file)
        except OSError as e:
            if os.path.exists(partial):
                os.remove(partial)
            self.record_file_operation("SQL_EXPORT", "FAILED", None, result_file, error=str(e),
                                       started_at=started_at, details=details)
            raise
        size = os.path.getsize(result_file)
        self.record_file_operation("SQL_EXPORT", "SUCCESS", None, result_file, dest_size=size,
                                   started_at=started_at, details=details)
        job_log.detail(f"Wrote {plural(len(rows), 'row')} to '{result_file}' ({size} bytes)")
        result["details"]["summary"].append(f"Wrote them to {os.path.basename(result_file)}.")
        return result

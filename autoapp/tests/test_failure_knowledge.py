"""
What a failed step knew about its effect (docs/WORKFLOWS_PHASE7.md, proposal 3): every step type
says, one that does not counts as unknown, and Run SQL answers by how far its statement got.
"""
import sqlite3

import pytest
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from engine.handlers import HANDLERS
from engine.handlers.base_handler import BaseHandler
from engine.handlers.sql_handler import RunSqlHandler, commits_by_itself
from engine.step_catalog import NOT_DONE, PARTLY_DONE, UNKNOWN, WhatItKnew
from engine.telemetry_client import LocalSpoolTelemetryClient


class SaysNothing(BaseHandler):
    CODE = "SAYS_NOTHING"

    def execute_step(self, resolved_params):
        raise RuntimeError("boom")


@pytest.mark.parametrize("handler", HANDLERS, ids=lambda h: h.CODE)
def test_every_step_type_says_what_a_failed_step_knew(handler):
    assert handler.FAILURE_KNOWLEDGE in (NOT_DONE, PARTLY_DONE, UNKNOWN)


def test_a_step_type_that_does_not_say_counts_as_unknown(tmp_path):
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path), instance_id="T1") as telemetry:
        knew = SaysNothing({"StepID": 1}, telemetry).what_failed_step_knew(RuntimeError("boom"))

    assert knew.answer == UNKNOWN
    assert "not known" in knew.why


def test_the_answers_for_the_step_types_are_the_ones_agreed():
    answers = {h.CODE: h.FAILURE_KNOWLEDGE for h in HANDLERS}

    assert answers["COPY_FILES"] == answers["DELETE_FILES"] == answers["UNZIP_FILES"] == PARTLY_DONE
    assert answers["ZIP_FILES"] == NOT_DONE         # its archive is written under another name and renamed whole
    assert answers["CHECK_FILES"] == answers["SET_RETURN_CODE"] == answers["SIMULATE"] == NOT_DONE


# --- Run SQL: the answer depends on how far the statement got ------------------------------------

@pytest.fixture
def sales(tmp_path):
    path = tmp_path / "sales.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE invoices (invoice_no TEXT)")
    return f"sqlite:///{path}"


def fail_and_ask(tmp_path, params):
    """Runs Run SQL, which must fail, and returns what the step says it knew."""
    config = {"StepID": 1, "StepType": "RUN_SQL", "StepOrder": 1, "Title": "Load"}
    with LocalSpoolTelemetryClient(spool_dir=str(tmp_path / "spool"), instance_id="T1") as telemetry:
        handler = RunSqlHandler(step_config=config, telemetry_client=telemetry)
        with pytest.raises(Exception) as failure:
            handler.run(params)
        return handler.what_failed_step_knew(failure.value)


def test_a_statement_that_never_reached_the_database_was_not_done(tmp_path):
    knew = fail_and_ask(tmp_path, {"Database": "not a url", "Statement": "SELECT 1"})

    assert knew.answer == NOT_DONE


def test_a_connection_that_could_not_be_made_was_not_done(tmp_path):
    knew = fail_and_ask(tmp_path, {"Database": f"sqlite:///{tmp_path}/no/such/folder/x.db", "Statement": "SELECT 1"})

    assert knew.answer == NOT_DONE
    assert "nothing was sent" in knew.why


def test_a_statement_the_database_refused_was_not_done(sales, tmp_path):
    knew = fail_and_ask(tmp_path, {"Database": sales, "Statement": "INSERT INTO missing VALUES (1)", "Commit": "True"})

    assert knew.answer == NOT_DONE
    assert "rolled it back" in knew.why


def test_a_connection_that_dropped_after_sending_is_unknown(sales, tmp_path, monkeypatch):
    def drop(self, *args, **kwargs):
        raise OperationalError("INSERT", {}, Exception(2013, "Lost connection to server during query"))
    monkeypatch.setattr(Connection, "exec_driver_sql", drop)

    knew = fail_and_ask(tmp_path, {"Database": sales, "Statement": "INSERT INTO invoices VALUES ('A')"})

    assert knew.answer == UNKNOWN
    assert "connection dropped" in knew.why


def test_a_failure_in_the_commit_is_unknown(sales, tmp_path, monkeypatch):
    from sqlalchemy.engine.base import RootTransaction

    def fail_to_commit(self):
        raise OperationalError("COMMIT", {}, Exception("disk I/O error"))
    monkeypatch.setattr(RootTransaction, "commit", fail_to_commit)

    knew = fail_and_ask(tmp_path, {"Database": sales, "Statement": "INSERT INTO invoices VALUES ('A')", "Commit": "True"})

    assert knew.answer == UNKNOWN
    assert "committing" in knew.why


def test_a_result_file_that_failed_after_a_commit_is_partly_done_and_left_to_the_operator(sales, tmp_path):
    out = str(tmp_path / "out.csv")
    params = {"Database": sales, "Statement": "INSERT INTO invoices VALUES ('A')", "ResultFile": out}

    committed = fail_and_ask(tmp_path, {**params, "Commit": "True"})
    rolled_back = fail_and_ask(tmp_path, {**params, "Commit": "False"})

    assert committed.answer == PARTLY_DONE and committed.operator_decides
    assert "twice" in committed.why
    assert rolled_back.answer == NOT_DONE and not rolled_back.operator_decides


def test_only_an_unknown_effect_or_a_part_that_cannot_be_finished_is_left_to_the_operator():
    assert WhatItKnew(UNKNOWN).operator_decides
    assert WhatItKnew(PARTLY_DONE, cannot_finish=True).operator_decides
    assert not WhatItKnew(PARTLY_DONE).operator_decides
    assert not WhatItKnew(NOT_DONE).operator_decides


def test_mysql_and_mariadb_commit_a_ddl_statement_as_it_runs():
    assert commits_by_itself("create table t (a int)", "mysql+pymysql://u:p@host/db")
    assert commits_by_itself("DROP TABLE t", "mariadb+pymysql://u:p@host/db")
    assert not commits_by_itself("DROP TABLE t", "sqlite:///x.db")
    assert not commits_by_itself("INSERT INTO t VALUES (1)", "mysql+pymysql://u:p@host/db")

"""
Shared pytest fixtures.

By default every test gets its own throwaway SQLite database inside pytest's
per-test temp folder (tmp_path), so tests never touch autoapp.db or each other.

To run the same tests against a database server, name a database kept for
testing in AUTOAPP_TEST_DATABASE_URL, for example:

    AUTOAPP_TEST_DATABASE_URL="mysql+pymysql://@localhost/autoapp_test?unix_socket=/run/mysqld/mysqld.sock" python3 -m pytest

Its tables are built once per run from SQL/Create_Tables.sql, the same script
an installation would use, and emptied before each test. EVERYTHING IN THAT
DATABASE IS DELETED, so its name must contain "test".
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from core.database import get_db
from app.main import app
from app.telemetry_ingest import ingest_records
from create_dev_db import sql_statements
from engine.spool_delivery import sweep

os.environ.setdefault("AUTOAPP_MAIL_SENDER", "off")      # tests send by hand: see app/main.py

AUTOAPP_DIR = Path(__file__).resolve().parents[1]
CREATE_TABLES_SCRIPT = AUTOAPP_DIR.parent / "SQL" / "Create_Tables.sql"
SERVER_DATABASE_URL = os.getenv("AUTOAPP_TEST_DATABASE_URL")

from core.models import (
    Application, Base, Endpoint, Entity, Job, JobStep, JobStepParameter, Site, StepType, Tag, TagAssignment, Variable
)


@pytest.fixture(scope="session")
def server_database():
    """Builds the tables in the server test database, once per test run, from the installation script."""
    database = make_url(SERVER_DATABASE_URL).database or ""
    if "test" not in database.lower():
        pytest.exit(f"Refusing to run: AUTOAPP_TEST_DATABASE_URL names database '{database}'. The tests delete "
                    f"everything in the database they use, so its name must contain 'test'.", returncode=2)
    engine = create_engine(SERVER_DATABASE_URL)
    with engine.begin() as connection:
        for statement in sql_statements(CREATE_TABLES_SCRIPT.read_text()):
            connection.exec_driver_sql(statement)
    yield engine
    engine.dispose()


@pytest.fixture
def db_url(tmp_path, request):
    if not SERVER_DATABASE_URL:
        return f"sqlite:///{tmp_path / 'autoapp_test.db'}"

    engine = request.getfixturevalue("server_database")
    with engine.begin() as connection:
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        for table in Base.metadata.sorted_tables:
            connection.exec_driver_sql(f"TRUNCATE TABLE `{table.name}`")
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
    return SERVER_DATABASE_URL


def connect_args(db_url) -> dict:
    # SQLite only: lets the API's worker threads use a connection opened by another thread
    return {"check_same_thread": False} if db_url.startswith("sqlite") else {}


@pytest.fixture
def db(db_url):
    if db_url.startswith("sqlite"):
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
    else:
        # So the test sees what the runner and the API have committed without ending its own transaction first
        engine = create_engine(db_url, isolation_level="READ COMMITTED")
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


class Seeder:
    """Small helpers for inserting just the rows a test needs."""

    def __init__(self, db):
        self.db = db

    def _add(self, obj):
        self.db.add(obj)
        self.db.flush()
        return obj

    def set_vars(self, owner, **variables):
        for name, value in variables.items():
            self.db.add(Variable(MasterObject_id=owner.MasterObject_id, VarName=name, VarValue=value))
        self.db.flush()

    def job(self, key="TEST_JOB", **variables):
        job = self._add(Job(JobKey=key))
        self.set_vars(job, **variables)
        return job

    def entity(self, name, **variables):
        entity = self._add(Entity(Name=name, Abbr=name[:10]))
        self.set_vars(entity, **variables)
        return entity

    def application(self, name, **variables):
        app = self._add(Application(Name=name, Abbr=name[:10]))
        self.set_vars(app, **variables)
        return app

    def site(self, name, entity, host="sftp.example.com"):
        return self._add(Site(Name=name, Host=host, Entity_MasterObject_id=entity.MasterObject_id))

    def endpoint(self, name, path, pattern="*", application=None, site=None):
        return self._add(Endpoint(
            Name=name, Path=str(path), FilenamePattern=pattern,
            Application_MasterObject_id=application.MasterObject_id if application else None,
            Site_MasterObject_id=site.MasterObject_id if site else None,
        ))

    def tag(self, name, parent=None, **variables):
        tag = self._add(Tag(Name=name, Parent_MasterObject_id=parent.MasterObject_id if parent else None))
        self.set_vars(tag, **variables)
        return tag

    def attach(self, tag, *targets):
        for target in targets:
            self._add(TagAssignment(Tag_MasterObject_id=tag.MasterObject_id,
                                    Target_MasterObject_id=target.MasterObject_id))

    def step_type(self, code="COPY_FILES", name="Copy Files"):
        existing = self.db.query(StepType).filter(StepType.HandlerClass == code).first()
        return existing or self._add(StepType(TypeName=name, HandlerClass=code))

    def step(self, job, order, code="COPY_FILES", title=None, parent=None, name=None, on_failure="FAIL_JOB", **params):
        step = self._add(JobStep(
            job_id=job.MasterObject_id,
            StepType_id=self.step_type(code, code).id,
            StepOrder=order,
            Title=title or f"Step {order}",
            ParentStep_id=parent.id if parent else None,
            StepName=name,
            OnFailure=on_failure,
        ))
        for name, value in params.items():
            self.db.add(JobStepParameter(job_step_id=step.id, ParamName=name, ParamValue=value))
        self.db.flush()
        return step


@pytest.fixture
def seed(db):
    return Seeder(db)


def read_spool(spool_dir) -> list:
    """Returns the records from the completed (.jsonl) spool files in a folder."""
    records = []
    for spool_file in sorted(Path(spool_dir).glob("*.jsonl")):
        for line in spool_file.read_text().splitlines():
            records.append(json.loads(line))
    return records


def read_logs(log_root) -> str:
    """Every job log written under a log root, oldest first: the runs of one test."""
    files = sorted(Path(log_root).rglob("*.log"), key=lambda path: path.stat().st_mtime)
    return "\n".join(path.read_text() for path in files)


@pytest.fixture
def spool_records():
    return read_spool


@pytest.fixture
def client(db, db_url):
    """
    The API, called over HTTP in-process, reading and writing the test's database.
    Requests get their own database sessions, as on a real server, so a test
    must db.commit() what it seeded before calling, and db.commit() again before
    reading back what a request changed (a session does not see other sessions'
    changes until its own transaction ends).
    """
    # The server updates the step catalog as it starts. Anything a fixture has seeded so far is
    # committed first, or the server's session would wait on the test's unfinished transaction.
    db.commit()
    engine = create_engine(db_url, connect_args=connect_args(db_url))
    make_session = sessionmaker(bind=engine)

    def override_get_db():
        session = make_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def live_api(db, db_url, tmp_path):
    """A real API server in its own process, on the test's database. Yields its address."""
    db.commit()         # see the note in the client fixture
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=AUTOAPP_DIR,
        # The server needs to know where working folders live to check a job's file locations
        env={**subprocess_env(db_url), "AUTOAPP_WORKING_ROOT": str(tmp_path / "work"),
             "AUTOAPP_SPOOL_DIR": str(tmp_path / "spool")},
    )
    try:
        deadline = time.time() + 20
        while True:
            try:
                urllib.request.urlopen(url + "/health", timeout=1)
                break
            except OSError:
                if server.poll() is not None or time.time() > deadline:
                    raise RuntimeError("The API server did not start.")
                time.sleep(0.1)
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture
def unused_api_url():
    """An address nothing is listening on."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


def subprocess_env(db_url) -> dict:
    """
    Environment for a runner or server process: the test's database and log folder, and no settings
    leaking in from the shell.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUTOAPP_")}
    env["DATABASE_URL"] = db_url
    env["AUTOAPP_LOG_ROOT"] = os.environ["AUTOAPP_LOG_ROOT"]
    return env


@pytest.fixture(autouse=True)
def log_root(tmp_path, monkeypatch):
    """Every test keeps its job logs in a folder of its own, read by the in-process API and its processes alike."""
    folder = tmp_path / "logs"
    monkeypatch.setenv("AUTOAPP_LOG_ROOT", str(folder))
    return folder


@pytest.fixture
def run_runner(db, db_url, tmp_path):
    """Runs a job the way a scheduler would: as a separate process. Returns the finished process."""
    def _run(job_key, instance_id="RUN_001", *extra_args):
        db.commit()
        return subprocess.run(
            [sys.executable, "-m", "engine.runner",
             "--job-key", job_key,
             "--instance-id", instance_id,
             "--spool-dir", str(tmp_path / "spool"),
             "--working-root", str(tmp_path / "work"),
             *extra_args],
            cwd=AUTOAPP_DIR,
            env=subprocess_env(db_url),
            capture_output=True, text=True,
        )
    return _run


@pytest.fixture
def outbox(tmp_path):
    folder = tmp_path / "app_outbox"
    folder.mkdir()
    (folder / "Legal_Batch_1.csv").write_text("id\n1")
    (folder / "Legal_Batch_2.csv").write_text("id\n2")
    (folder / "other.txt").write_text("not part of the feed")
    return folder


@pytest.fixture
def endpoints(seed, outbox, tmp_path):
    source = seed.endpoint("LEGAL_EXTRACTS", outbox, "Legal_Batch_*.csv", application=seed.application("LEGAL_APP"))
    dest = seed.endpoint("BILLING_INBOX", tmp_path / "app_inbox", "*.csv", application=seed.application("BILLING_APP"))
    return source, dest


@pytest.fixture
def load_spool(db, tmp_path):
    """Loads the spool files the runner left behind into the test's database."""
    def _load():
        delivered, failed = sweep(tmp_path / "spool", lambda records: ingest_records(db, records))
        assert not failed, failed
        db.commit()
        return delivered
    return _load


# --- Browser tests of the web interface -----------------------------------------------------
# These fixtures drive real pages in headless Chromium. A test that uses them is skipped, with
# the reason shown, on a machine that has no Chromium or no 'playwright' package.
# To watch a test happen, run it with AUTOAPP_TEST_SHOW_BROWSER=1.

@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api", reason="the 'playwright' package is not installed")
    path = os.getenv("AUTOAPP_TEST_BROWSER") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not path:
        pytest.skip("no Chromium browser found (set AUTOAPP_TEST_BROWSER to its path)")
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=path, args=["--no-sandbox"], headless=not os.getenv("AUTOAPP_TEST_SHOW_BROWSER"))
        yield browser
        browser.close()


@pytest.fixture
def page(browser, live_api):
    """
    A fresh browser window pointed at the test's API server, with its clock set to New York.
    Fails the test if the page logs a script error.
    """
    context = browser.new_context(base_url=live_api, viewport={"width": 1400, "height": 900},
                                  timezone_id="America/New_York", accept_downloads=True)
    page = context.new_page()
    problems = []
    page.on("pageerror", lambda error: problems.append(str(error)))
    page.on("console", lambda message: problems.append(message.text) if message.type == "error" else None)
    yield page
    context.close()
    assert problems == [], f"the page reported errors: {problems}"


@pytest.fixture
def page_expecting_refusals(browser, live_api):
    """
    As the page fixture, for a test in which the server is meant to refuse something
    (not found, key already taken, ...). The browser logs each refusal as an error,
    which the page fixture would count as a fault in the page.
    """
    context = browser.new_context(base_url=live_api, viewport={"width": 1400, "height": 900},
                                  timezone_id="America/New_York", accept_downloads=True)
    page = context.new_page()
    problems = []
    page.on("pageerror", lambda error: problems.append(str(error)))      # a script error is still a fault
    yield page
    context.close()
    assert problems == [], f"the page reported errors: {problems}"


def wait_for_search(page):
    """Waits until a search page has finished searching, and returns its result rows."""
    page.wait_for_function("document.querySelector('#result-summary').textContent.trim() !== '' "
                           "&& !document.querySelector('#result-summary').textContent.includes('Searching')")
    return page.locator("table.results tbody tr")

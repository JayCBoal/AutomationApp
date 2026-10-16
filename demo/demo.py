#!/usr/bin/env python3
"""
The RunMyFiles demo: a clean, self-contained setup to present from.

    python3 demo/demo.py setup     build a fresh demo (deletes the previous one)
    python3 demo/demo.py start     start RunMyFiles and the Stand-in Scheduler
    python3 demo/demo.py stop      stop them
    python3 demo/demo.py status    what is running, and where

Everything lives in one folder, /tmp/autoapp_demo (or wherever AUTOAPP_DEMO_DIR
says): a SQLite database, the sample sales database, the sample files, the jobs'
working folders and the spool. A short path, so that the paths the pages show are
easy to read, and say nothing about the machine's user. On a Chromebook /tmp is
emptied when Linux restarts: run setup again (it takes seconds).
It has nothing to do with the development database, and uses its own ports so it
can run beside the development servers:

    RunMyFiles                 http://localhost:8200/
    Stand-in Scheduler      http://localhost:8210/

The walkthrough to present from is demo/DEMO.md.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AUTOAPP_DIR = REPO / "autoapp"
STANDIN_DIR = REPO / "demo" / "scheduler_standin"
WORKSPACE = Path(os.environ.get("AUTOAPP_DEMO_DIR") or "/tmp/autoapp_demo")
AUTOAPP_PORT, STANDIN_PORT = 8200, 8210
AUTOAPP_URL, STANDIN_URL = f"http://localhost:{AUTOAPP_PORT}", f"http://localhost:{STANDIN_PORT}"
STANDIN_TOKEN = "demo-token"
PIDS = WORKSPACE / "servers.json"


def environment() -> dict:
    """The demo's own settings, with none of the development ones (dev_env.sh) leaking in."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AUTOAPP_", "STANDIN_")) and k != "DATABASE_URL"}
    env.update({
        "DATABASE_URL": f"sqlite:///{WORKSPACE / 'autoapp_demo.db'}",
        "AUTOAPP_WORKING_ROOT": str(WORKSPACE / "work"),
        "AUTOAPP_SPOOL_DIR": str(WORKSPACE / "spool"),
        "STANDIN_DATABASE_URL": f"sqlite:///{WORKSPACE / 'standin_demo.db'}",
        "STANDIN_TOKEN": STANDIN_TOKEN,
        "STANDIN_NAME": "STANDIN",
        "STANDIN_AUTOAPP_URL": AUTOAPP_URL,
    })
    return env


def say(text):
    print(f"  {text}", flush=True)


def python(code: str, cwd: Path) -> None:
    """Runs a piece of Python in the demo's environment, in its own process."""
    result = subprocess.run([sys.executable, "-c", code], cwd=cwd, env=environment(), capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"Setup failed:\n{result.stdout}{result.stderr}")


# ---------- setup ----------

BUILD_AUTOAPP = r'''
import os
from pathlib import Path
from app.database import SessionLocal, engine
from app.models import Base, Scheduler, Variable
from app.catalog import sync_catalog
from create_dev_db import load_seed, create_sales_db, create_sample_files

workspace = Path(os.environ["AUTOAPP_WORKING_ROOT"]).parent
Base.metadata.create_all(engine)
db = SessionLocal()
load_seed(db)
# The sample data's files live under /tmp/autoapp_sample; the demo keeps its own in its workspace
for variable in db.query(Variable).filter(Variable.VarName == "Root"):
    variable.VarValue = variable.VarValue.replace("/tmp/autoapp_sample", str(workspace / "files"))
db.query(Variable).filter(Variable.VarName == "SalesDbUrl").one().VarValue = f"sqlite:///{workspace / 'sales.db'}"
standin = db.query(Scheduler).filter(Scheduler.Name == "STANDIN").one()
standin.ApiUrl = os.environ["STANDIN_URL"]
db.query(Variable).filter(Variable.MasterObject_id == standin.MasterObject_id, Variable.VarName == "ApiToken").one().VarValue = os.environ["STANDIN_TOKEN"]
db.commit()
sync_catalog(db)
create_sample_files(db)
db.close()
create_sales_db(workspace / "sales.db")
'''

BUILD_STANDIN = r'''
from standin.app import Job, Parameter, SessionLocal
db = SessionLocal()
jobs = [
    ("LEGAL_COLLECT", "DEV-LEGAL-COLLECT_AND_DELIVER", "Collects the legal extracts and hands them to billing", False, []),
    ("BILLING_LOAD", "DEV-BILLING-LOAD", "Billing picks up what legal delivered", False, []),
    ("BILLING_EXPORT", "DEV-BILLING-INVOICE_EXPORT", "Nightly export of open invoices and payments for finance", True,
     [("SalesRegion", "EMEA", False), ("ExportPassword", "demo-secret-123", True)]),
    ("FINANCE_REPORTS", "DEV-FINANCE-LOAD_REPORTS", "Finance unpacks and checks the billing reports", False, []),
]
for name, key, description, business_date, parameters in jobs:
    db.add(Job(name=name, autoapp_job_key=key, description=description, business_date=business_date,
               parameters=[Parameter(name=n, value=v, secret=s) for n, v, s in parameters]))
db.commit()
db.close()
'''


def submit(job: str) -> None:
    """Submits one of the stand-in's jobs through its API, as a user of it would, and waits for the run to end."""
    def call(method, path):
        request = urllib.request.Request(STANDIN_URL + path, method=method,
                                         headers={"Authorization": f"Bearer {STANDIN_TOKEN}"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    run = call("POST", f"/api/jobs/{job}/submit")
    for _ in range(150):
        run = call("GET", f"/api/runs/{run['id']}")
        if run["status"] != "RUNNING":
            break
        time.sleep(0.2)
    if run["status"] != "SUCCESS":
        sys.exit(f"The history run of {job} did not succeed:\n{run.get('output')}")


def setup() -> None:
    if running():
        stop()
    print(f"Building the demo in {WORKSPACE} ...")
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    (WORKSPACE / "logs").mkdir(parents=True)

    say("RunMyFiles' database, with the sample data, the sales database and the sample files")
    os.environ["STANDIN_URL"] = STANDIN_URL
    python(f"import os; os.environ['STANDIN_URL'] = {STANDIN_URL!r}\n" + BUILD_AUTOAPP, AUTOAPP_DIR)

    say("The Stand-in Scheduler, with a job for each RunMyFiles job")
    python(BUILD_STANDIN, STANDIN_DIR)

    say("Some history: the stand-in collecting the legal extracts and loading them into billing")
    start(quiet=True)
    try:
        submit("LEGAL_COLLECT")
        submit("BILLING_LOAD")
    finally:
        stop(quiet=True)
    print("Done. Next:  python3 demo/demo.py start")


# ---------- start, stop, status ----------

def running() -> dict:
    """The servers this script started that are still alive: {name: pid}."""
    try:
        pids = json.loads(PIDS.read_text())
    except (OSError, ValueError):
        return {}
    alive = {}
    for name, pid in pids.items():
        try:
            os.kill(pid, 0)
            alive[name] = pid
        except OSError:
            pass
    return alive


def answering(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=1)
        return True
    except OSError:
        return False


def start(quiet: bool = False) -> None:
    if not (WORKSPACE / "autoapp_demo.db").exists():
        sys.exit("There is no demo yet. Build it first:  python3 demo/demo.py setup")
    if running():
        print("The demo is already running.")
        status()
        return
    for url in (AUTOAPP_URL + "/health", STANDIN_URL + "/api/config"):
        if answering(url):
            sys.exit(f"Something else is already answering at {url}. Stop it, or change the ports in demo/demo.py.")
    if not quiet:
        print("Starting the demo ...")
    pids = {}
    servers = {
        "autoapp": (AUTOAPP_DIR, ["app.main:app", "--port", str(AUTOAPP_PORT)], AUTOAPP_URL + "/health"),
        "standin": (STANDIN_DIR, ["standin.app:app", "--port", str(STANDIN_PORT)], STANDIN_URL + "/api/config"),
    }
    for name, (cwd, args, check) in servers.items():
        log = open(WORKSPACE / "logs" / f"{name}.log", "a")
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", *args, "--log-level", "warning"],
                                   cwd=cwd, env=environment(), stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        pids[name] = process.pid
        for _ in range(100):
            if answering(check):
                break
            time.sleep(0.2)
        else:
            PIDS.write_text(json.dumps(pids))
            stop()
            sys.exit(f"{name} did not start. See {WORKSPACE}/logs/{name}.log")
    PIDS.write_text(json.dumps(pids))
    if not quiet:
        status()


def stop(quiet: bool = False) -> None:
    for name, pid in running().items():
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass
        if not quiet:
            say(f"Stopped {name}.")
    # Wait until both have let go of their ports, so a start straight after works
    for _ in range(50):
        if not (answering(AUTOAPP_URL + "/health") or answering(STANDIN_URL + "/api/config")):
            break
        time.sleep(0.1)
    if PIDS.exists():
        PIDS.unlink()


def status() -> None:
    alive = running()
    for name, url, label in (("autoapp", AUTOAPP_URL, "RunMyFiles"), ("standin", STANDIN_URL, "Stand-in Scheduler")):
        state = "running" if name in alive else "not running"
        say(f"{label:<20} {url}/   ({state})")
    if not alive:
        say("Start it with:  python3 demo/demo.py start")


def main():
    commands = {"setup": setup, "start": lambda: start(), "stop": lambda: stop(), "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    try:
        import sqlalchemy, uvicorn  # noqa: F401  (the project's packages, needed by everything below)
    except ModuleNotFoundError:
        sys.exit(f"RunMyFiles' Python packages are not available here. Switch on the project environment first:\n\n"
                 f"    source {REPO}/.venv/bin/activate\n")
    commands[sys.argv[1]]()


if __name__ == "__main__":
    main()

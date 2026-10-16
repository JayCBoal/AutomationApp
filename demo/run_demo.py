#!/usr/bin/env python3
"""
RunMyFiles demo: seed a database, run one job, and leave everything on disk to look at.

    python3 demo/run_demo.py

This is NOT a test. It asserts nothing and always shows whatever actually
happened. Each run writes to a new folder under demo/output/, so earlier runs
are kept for comparison.

The job picks up extract files from one application and hands them to another:

    Step 1 "Collect extracts"   copy  Endpoint LEGAL_APP_EXTRACTS -> incoming/        (working folder)
    Step 2 "Archive"            copy  incoming/*.csv              -> archive/<today>/ (working folder)
    Step 3 "Deliver to billing" move  incoming/*.csv              -> Endpoint BILLING_APP_INBOX

Locations outside the job's working folder are registered Endpoints. The runner
records every file it handles in a spool file; the demo then loads that into
the database and prints the route one file took.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
AUTOAPP_DIR = REPO_DIR / "autoapp"
sys.path.insert(0, str(AUTOAPP_DIR))

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError:
    sys.exit("RunMyFiles' Python packages are not available in this terminal.\n"
             f"Switch on the project environment first:\n\n    source {REPO_DIR}/.venv/bin/activate\n\n"
             "If that file does not exist, see 'Quick start' in README.md.")

from app.models import (
    Application, Base, Endpoint, Job, JobStep, JobStepParameter, StepType, Variable
)
from app.trace import search_operations, trace_operation


def heading(text):
    print(f"\n=== {text} " + "=" * max(0, 70 - len(text)))


def show_tree(folder, skip=()):
    for path in sorted(folder.rglob("*")):
        if path.name in skip:
            continue
        depth = len(path.relative_to(folder).parts) - 1
        suffix = "/" if path.is_dir() else f"  ({path.stat().st_size} bytes)"
        print("    " + "  " * depth + path.name + suffix)


def seed(db_url, run_dir):
    """Creates the schema and one runnable job. Returns the JobKey."""
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    def add(obj):
        db.add(obj)
        db.flush()
        return obj

    def set_var(owner, name, value):
        db.add(Variable(MasterObject_id=owner.MasterObject_id, VarName=name, VarValue=value))

    # Applications, each with a variable saying where its files live
    legal_app = add(Application(Name="LEGAL_APP", Abbr="LGL"))
    billing_app = add(Application(Name="BILLING_APP", Abbr="BIL"))
    set_var(legal_app, "Root", str(run_dir / "legal_app"))
    set_var(billing_app, "Root", str(run_dir / "billing_app"))

    # Endpoints: the registered places files come from and go to.
    # ${APP.Root} means "the Root variable of this endpoint's own application".
    endpoints = [
        add(Endpoint(Name="LEGAL_APP_EXTRACTS", Application_MasterObject_id=legal_app.MasterObject_id,
                     Path="${APP.Root}/outbox", FilenamePattern="${FilePattern}",
                     Description="Client extract files produced by the legal application")),
        add(Endpoint(Name="BILLING_APP_INBOX", Application_MasterObject_id=billing_app.MasterObject_id,
                     Path="${APP.Root}/inbox", FilenamePattern="*.csv",
                     Description="Files for the billing application to load")),
    ]

    copy_type = add(StepType(TypeName="Copy Files", HandlerClass="COPY_FILES"))
    job = add(Job(JobKey="DEMO-LEGAL-COLLECT_AND_DELIVER", Description="Demo job"))
    set_var(job, "FilePattern", "Legal_Batch_*.csv")

    steps = [
        ("Collect extracts", {"SourceEndpoint": "LEGAL_APP_EXTRACTS", "Dest": "incoming"}),
        ("Archive", {"Source": "incoming/*.csv", "Dest": "archive/${DATE:yyyyMMdd}"}),
        ("Deliver to billing", {"Source": "incoming/*.csv", "DestEndpoint": "BILLING_APP_INBOX", "Move": "True"}),
    ]
    for order, (title, params) in enumerate(steps, start=1):
        step = add(JobStep(job_id=job.MasterObject_id, StepType_id=copy_type.id, StepOrder=order, Title=title))
        for name, value in params.items():
            db.add(JobStepParameter(job_step_id=step.id, ParamName=name, ParamValue=value))

    db.commit()

    print(f"    JobKey  : {job.JobKey}")
    print(f"    Variable: FilePattern = Legal_Batch_*.csv   [job]")
    for app in (legal_app, billing_app):
        print(f"    Variable: Root = {app.variables[0].VarValue}   [application {app.Name}]")
    for endpoint in endpoints:
        print(f"    Endpoint {endpoint.id}: {endpoint.Name}   [application {endpoint.application.Name}]")
        print(f"                Path = {endpoint.Path}    FilenamePattern = {endpoint.FilenamePattern}")
    for order, (title, params) in enumerate(steps, start=1):
        print(f"    Step {order}  : {title}")
        for name, value in params.items():
            print(f"                {name} = {value}")

    job_key = job.JobKey
    db.close()
    engine.dispose()
    return job_key


def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = REPO_DIR / "demo" / "output" / f"run_{stamp}"
    outbox = run_dir / "legal_app" / "outbox"
    outbox.mkdir(parents=True)
    db_url = f"sqlite:///{run_dir / 'demo.db'}"
    instance_id = f"DEMO_{stamp}"

    heading("1. Seeding the database")
    print(f"    {db_url}")
    job_key = seed(db_url, run_dir)

    heading("2. Creating input files in the legal application's outbox")
    (outbox / "Legal_Batch_001.csv").write_text("client,amount\nACME,100\n")
    (outbox / "Legal_Batch_002.csv").write_text("client,amount\nGLOBEX,250\nINITECH,75\n")
    (outbox / "readme.txt").write_text("Not part of the batch; the job should leave this alone.\n")
    show_tree(run_dir, skip=("demo.db",))

    heading("3. Running the job (the command a scheduler would issue)")
    command = [sys.executable, "-m", "engine.runner",
               "--job-key", job_key,
               "--instance-id", instance_id,
               "--spool-dir", str(run_dir / "spool"),
               "--working-root", str(run_dir / "work")]
    print(f"    cd {AUTOAPP_DIR}")
    print(f"    DATABASE_URL={db_url} \\")
    print("    " + " ".join(command) + "\n")
    sys.stdout.flush()
    result = subprocess.run(command, cwd=AUTOAPP_DIR, env={**os.environ, "DATABASE_URL": db_url})

    heading("4. Result")
    print(f"    Exit code: {result.returncode}")

    heading("5. Files after the run")
    show_tree(run_dir, skip=("demo.db",))

    heading("6. Telemetry spool (what the runner recorded, one line per record)")
    spool_files = sorted((run_dir / "spool").glob("*.jsonl")) if (run_dir / "spool").exists() else []
    if not spool_files:
        print("    (no spool files were written)")
    for spool_file in spool_files:
        print(f"    {spool_file.name}")
        for line in spool_file.read_text().splitlines():
            record = json.loads(line)
            if record["Record"] == "RUN_START":
                print(f"      RUN_START  job {record['JobKey']}, instance {record['InstanceID']}, "
                      f"run number {record['RunNumber']}")
            elif record["Record"] == "RUN_END":
                print(f"      RUN_END    {record['Status']}  {record['Error'] or ''}")
            else:
                print(f"      OPERATION  step {record['StepOrder']} {record['OpType']:<5} {record['Status']:<8} "
                      f"{record['SourceFilename']}  ({record['SourceSize']} bytes)")

    heading("7. Loading the spool into the database")
    command = [sys.executable, "-m", "engine.spool_delivery", "--spool-dir", str(run_dir / "spool")]
    print("    " + " ".join(command) + "\n")
    sys.stdout.flush()
    subprocess.run(command, cwd=AUTOAPP_DIR, env={**os.environ, "DATABASE_URL": db_url})

    heading("8. File trace: the route of one file, from the database")
    engine = create_engine(db_url)
    db = sessionmaker(bind=engine)()
    delivered = search_operations(db, filename="Legal_Batch_001.csv", endpoint="BILLING_APP_INBOX")
    if not delivered:
        print("    (no delivery of Legal_Batch_001.csv was recorded)")
    else:
        def place(location):
            if location.endpoint:
                return f"Endpoint {location.endpoint} [application {location.application}]"
            return "working folder: " + str(Path(location.path).relative_to(run_dir / "work"))

        trace = trace_operation(db, delivered[0].id)
        print(f"    {trace.filename}")
        for number, hop in enumerate(trace.hops, start=1):
            print(f"      {number}. {hop.op_type:<5} {hop.status:<8} job {hop.job_key}, "
                  f"instance {hop.instance_id}, step {hop.step_order}")
            print(f"           from: {place(hop.source)}")
            print(f"           to  : {place(hop.dest)}   ({hop.dest.size} bytes)")
    db.close()
    engine.dispose()

    print(f"\nEverything from this run is in:\n    {run_dir}\n")


if __name__ == "__main__":
    main()

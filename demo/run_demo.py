#!/usr/bin/env python3
"""
AutoApp demo: seed a database, run one job, and leave everything on disk to look at.

    python3 demo/run_demo.py

This is NOT a test. It asserts nothing and always shows whatever actually
happened. Each run writes to a new folder under demo/output/, so earlier runs
are kept for comparison.

The job picks up extract files from one application and hands them to another:

    Step 1 "Collect extracts"   copy  Endpoint LEGAL_APP_EXTRACTS -> incoming/        (working folder)
    Step 2 "Archive"            copy  incoming/*.csv              -> archive/<today>/ (working folder)
    Step 3 "Deliver to billing" move  incoming/*.csv              -> Endpoint BILLING_APP_INBOX

Locations outside the job's working folder are registered Endpoints; the
telemetry spool records which Endpoint each operation read from or wrote to.
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

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Application, Base, Endpoint, Job, JobStep, JobStepParameter, Process, StepType, Variable
)


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
    """Creates the schema and one runnable job. Returns the JobKey and {endpoint id: name}."""
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
    proc = add(Process(Name="DEMO-LEGAL-JAYCO-CLNT_EXTRACT", Description="Demo process"))
    job = add(Job(process_id=proc.MasterObject_id, Name="COLLECT_AND_DELIVER",
                  JobKey=f"{proc.Name}--COLLECT_AND_DELIVER", Description="Demo job"))
    set_var(job, "FilePattern", "Legal_Batch_*.csv")

    steps = [
        ("Collect extracts", {"SourceEndpoint": "LEGAL_APP_EXTRACTS", "Dest": "incoming"}),
        ("Archive", {"Source": "incoming/*.csv", "Dest": "archive/${SYS:YYYYMMDD}"}),
        ("Deliver to billing", {"Source": "incoming/*.csv", "DestEndpoint": "BILLING_APP_INBOX", "Move": "True"}),
    ]
    for order, (title, params) in enumerate(steps, start=1):
        step = add(JobStep(job_id=job.MasterObject_id, StepType_id=copy_type.id, StepOrder=order, Title=title))
        for name, value in params.items():
            db.add(JobStepParameter(job_step_id=step.id, ParamName=name, ParamValue=value))

    db.commit()

    print(f"    Process : {proc.Name}")
    print(f"    Job     : {job.Name}")
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
    endpoint_names = {endpoint.id: endpoint.Name for endpoint in endpoints}
    db.close()
    engine.dispose()
    return job_key, endpoint_names


def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = REPO_DIR / "demo" / "output" / f"run_{stamp}"
    outbox = run_dir / "legal_app" / "outbox"
    outbox.mkdir(parents=True)
    db_url = f"sqlite:///{run_dir / 'demo.db'}"
    instance_id = f"DEMO_{stamp}"

    heading("1. Seeding the database")
    print(f"    {db_url}")
    job_key, endpoint_names = seed(db_url, run_dir)

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

    heading("6. Telemetry spool")

    def endpoint_label(endpoint_id):
        return f"Endpoint {endpoint_names[endpoint_id]}" if endpoint_id else "working folder"

    spool_files = sorted((run_dir / "spool").glob("*")) if (run_dir / "spool").exists() else []
    if not spool_files:
        print("    (no spool files were written)")
    for spool_file in spool_files:
        print(f"    {spool_file.name}")
        for line in spool_file.read_text().splitlines():
            record = json.loads(line)
            if record.get("IsAudit"):
                print(f"      AUDIT      {record['Action']:<24} {record['Status']:<8} {record['Details'] or ''}")
            else:
                print(f"      OPERATION  step {record['StepID']} {record['OpType']:<12} {record['Status']:<8} "
                      f"{record['BytesTransferred']} bytes, {record['ExecutionTimeMs']} ms")
                print(f"                 from: {endpoint_label(record['SourceEndpointID'])}")
                print(f"                 to  : {endpoint_label(record['DestEndpointID'])}")
                for op in record["Details"].get("ops", []):
                    print(f"                 {op['OpType']:<5} {Path(op['Source']).relative_to(run_dir)}"
                          f"  ->  {Path(op['Dest']).relative_to(run_dir)}")

    print(f"\nEverything from this run is in:\n    {run_dir}\n")


if __name__ == "__main__":
    main()

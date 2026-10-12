#!/usr/bin/env python3
"""
AutoApp demo: seed a database, run one job, and leave everything on disk to look at.

    python3 demo/run_demo.py

This is NOT a test. It asserts nothing and always shows whatever actually
happened. Each run writes to a new folder under demo/output/, so earlier runs
are kept for comparison.

The job it runs:
    Step 1 "Archive inbound files"  copy  inbound/Legal_Batch_*.csv -> archive/<today>/
    Step 2 "Deliver to outbound"    move  inbound/Legal_Batch_*.csv -> outbound/
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

from app.models import Base, Job, JobStep, JobStepParameter, Process, StepType, Variable


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
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    copy_type = StepType(TypeName="Copy Files", HandlerClass="COPY_FILES")
    proc = Process(Name="DEMO-LEGAL-JAYCO-CLNT_EXTRACT", Description="Demo process")
    db.add_all([copy_type, proc])
    db.flush()
    job = Job(process_id=proc.MasterObject_id, Name="ARCHIVE_AND_DELIVER",
              JobKey=f"{proc.Name}--ARCHIVE_AND_DELIVER", Description="Demo job")
    db.add(job)
    db.flush()

    variables = {
        proc: {
            "InboundFolder": str(run_dir / "inbound"),
            "ArchiveFolder": str(run_dir / "archive"),
            "OutboundFolder": str(run_dir / "outbound"),
        },
        job: {"FilePattern": "Legal_Batch_*.csv"},
    }
    for owner, values in variables.items():
        for name, value in values.items():
            db.add(Variable(MasterObject_id=owner.MasterObject_id, VarName=name, VarValue=value))

    steps = [
        ("Archive inbound files", {"Source": "${InboundFolder}/${FilePattern}",
                                   "Dest": "${ArchiveFolder}/${SYS:YYYYMMDD}"}),
        ("Deliver to outbound", {"Source": "${InboundFolder}/${FilePattern}",
                                 "Dest": "${OutboundFolder}", "Move": "True"}),
    ]
    for order, (title, params) in enumerate(steps, start=1):
        step = JobStep(job_id=job.MasterObject_id, StepType_id=copy_type.id, StepOrder=order, Title=title)
        db.add(step)
        db.flush()
        for name, value in params.items():
            db.add(JobStepParameter(job_step_id=step.id, ParamName=name, ParamValue=value))

    db.commit()
    job_key = job.JobKey

    print(f"    Process : {proc.Name}")
    print(f"    Job     : {job.Name}")
    print(f"    JobKey  : {job_key}")
    for owner_label, values in (("process", variables[proc]), ("job", variables[job])):
        for name, value in values.items():
            print(f"    Variable: {name} = {value}   [{owner_label}]")
    for order, (title, params) in enumerate(steps, start=1):
        print(f"    Step {order}  : {title}")
        for name, value in params.items():
            print(f"                {name} = {value}")

    db.close()
    engine.dispose()
    return job_key


def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = REPO_DIR / "demo" / "output" / f"run_{stamp}"
    inbound = run_dir / "inbound"
    inbound.mkdir(parents=True)
    db_url = f"sqlite:///{run_dir / 'demo.db'}"
    instance_id = f"DEMO_{stamp}"

    heading("1. Seeding the database")
    print(f"    {db_url}")
    job_key = seed(db_url, run_dir)

    heading("2. Creating input files")
    (inbound / "Legal_Batch_001.csv").write_text("client,amount\nACME,100\n")
    (inbound / "Legal_Batch_002.csv").write_text("client,amount\nGLOBEX,250\nINITECH,75\n")
    (inbound / "readme.txt").write_text("Not part of the batch; the job should leave this alone.\n")
    show_tree(run_dir, skip=("demo.db",))

    heading("3. Running the job (the command a scheduler would issue)")
    command = [sys.executable, "-m", "engine.runner",
               "--job-key", job_key,
               "--instance-id", instance_id,
               "--spool-dir", str(run_dir / "spool")]
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
                print(f"      OPERATION  step {record['StepID']} {record['OpType']:<14} {record['Status']:<8} "
                      f"{record['BytesTransferred']} bytes, {record['ExecutionTimeMs']} ms")
                for op in record["Details"].get("ops", []):
                    print(f"                 {op['OpType']:<5} {op['Source']}")
                    print(f"                    -> {op['Dest']}")

    print(f"\nEverything from this run is in:\n    {run_dir}\n")


if __name__ == "__main__":
    main()

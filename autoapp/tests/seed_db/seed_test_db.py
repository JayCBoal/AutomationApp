import os
import sys
from pathlib import Path

# Ensure app package is visible
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import engine, SessionLocal
from app.models import (
    Base, Application, Entity, Site, Process, Job, 
    JobStep, StepType, JobStepParameter, Variable, Tag
)

# 1. Clear old local SQLite file if it exists
if os.path.exists("autoapp.db"):
    os.remove("autoapp.db")

print("Creating database schema...")
Base.metadata.create_all(bind=engine)

db = SessionLocal()

try:
    print("Seeding test data...")

    # --- 1. Global Variable attached to a Tag ---
    tag_global = Tag(TagName="GLOBAL_ENV", Category="System")
    db.add(tag_global)
    db.flush()

    var_global = Variable(
        MasterObject_id=tag_global.MasterObject_id,
        VarName="SYS:WORKING_FOLDER",
        VarValue="/tmp/autoapp/work/${JOB.Name}"
    )
    db.add(var_global)

    # --- 2. Process ---
    proc = Process(
        Name="DEV-PROCESS",
        Description="Sample Development Ingestion Process"
    )
    db.add(proc)
    db.flush()

    # --- 3. Job ---
    job = Job(
        process_id=proc.MasterObject_id,
        Name="JOBA",
        ExecutionOrder=1,
        Description="Core Ingestion Task A"
    )
    db.add(job)
    db.flush()

    # --- 4. Step Type & Steps ---
    step_type = StepType(
        TypeName="SFTP_TRANSFER",
        HandlerClass="SFTPDownloadHandler",
        Description="SFTP File Transfer Handler"
    )
    db.add(step_type)
    db.flush()

    step = JobStep(
        job_id=job.MasterObject_id,
        StepOrder=1,
        StepType_id=step_type.id,
        Title="Download Inbound CSV File"
    )
    db.add(step)
    db.flush()

    # --- 5. Step Parameters ---
    p1 = JobStepParameter(
        job_step_id=step.id,
        ParamName="remote_file",
        ParamValue="/inbound/data.csv"
    )
    p2 = JobStepParameter(
        job_step_id=step.id,
        ParamName="target_folder",
        ParamValue="${SYS:WORKING_FOLDER}/inbound"
    )
    db.add_all([p1, p2])

    db.commit()
    print("Database successfully seeded cleanly! 'autoapp.db' is ready.")

except Exception as e:
    db.rollback()
    print(f"Error seeding database: {e}")
finally:
    db.close()
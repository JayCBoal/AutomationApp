"""
tests/seed_db/seed_test_db.py
Phase 2 Database Seed Script using SQLAlchemy Models
"""
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, Application, Entity, Process, Job, Variable, StepType, 
    StepDefinition, JobStep, JobStepParameter
)

DB_PATH = "autoapp.db"
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine)

def seed_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing database file: {DB_PATH}")

    Base.metadata.create_all(engine)
    db = SessionLocal()

    try:
        print("Seeding Step Catalog (COPY_FILES & SQL_EXEC)...")
        # Step Types (TypeName maps to "Name", HandlerClass maps to "Code")
        st_copy = StepType(
            TypeName="Copy Files", 
            HandlerClass="COPY_FILES", 
            Description="Local file copy, move, and archiving", 
            IsActive=True
        )
        st_sql = StepType(
            TypeName="SQL Execution", 
            HandlerClass="SQL_EXEC", 
            Description="Executes SQL statements or scripts", 
            IsActive=True
        )
        
        db.add_all([st_copy, st_sql])
        db.flush()

        # Step Definitions (ParamName maps to "ParameterName")
        defs = [
            # COPY_FILES
            StepDefinition(StepType_id=st_copy.id, ParamName="Source", DataType="STRING", IsRequired=True),
            StepDefinition(StepType_id=st_copy.id, ParamName="Dest", DataType="STRING", IsRequired=True),
            StepDefinition(StepType_id=st_copy.id, ParamName="Move", DataType="BOOLEAN", IsRequired=False, DefaultValue="False"),
            StepDefinition(StepType_id=st_copy.id, ParamName="CreateFolder", DataType="BOOLEAN", IsRequired=False, DefaultValue="True"),
            # SQL_EXEC
            StepDefinition(StepType_id=st_sql.id, ParamName="ConnectionString", DataType="STRING", IsRequired=True),
            StepDefinition(StepType_id=st_sql.id, ParamName="Query", DataType="STRING", IsRequired=True),
        ]
        db.add_all(defs)
        db.flush()

        print("Seeding Domain Entities via Polymorphic Models...")
        # 1. Application (Requires Abbr)
        app_jay = Application(
            Name="LEGAL_APP",
            Abbr="LGL",
            Description="Legal Processing Application",
            IsActive=True,
            CreatedBy="system"
        )
        db.add(app_jay)

        # 2. Entity (Note: Entity has Name, Abbr, Description)
        ent_legal = Entity(
            Name="LEGAL",
            Abbr="LGL",
            Description="Legal Department",
            CreatedBy="system"
        )
        db.add(ent_legal)
        db.flush()

        # 3. Process
        proc_extract = Process(
            Name="DEV-LEGAL-EXTRACT",
            Description="Legal Data Extract & Archive Workflow",
            IsActive=True,
            CreatedBy="system"
        )
        db.add(proc_extract)
        db.flush()

        # 4. Job
        job_extract = Job(
            process_id=proc_extract.MasterObject_id,
            Name="RUN_EXTRACT",
            Description="Extracts files and logs audit entry",
            ExecutionOrder=1,
            IsActive=True,
            CreatedBy="system"
        )
        db.add(job_extract)
        db.flush()

        print("Seeding Variables...")
        # 5. Variables (Bound directly to MasterObject_id of parent entity/process)
        vars_seed = [
            Variable(MasterObject_id=ent_legal.MasterObject_id, VarName="WorkingFolder", VarValue="./test_data/working"),
            Variable(MasterObject_id=ent_legal.MasterObject_id, VarName="ArchiveFolder", VarValue="./test_data/archive"),
            Variable(MasterObject_id=proc_extract.MasterObject_id, VarName="BatchFilePattern", VarValue="Legal_Batch_${SYS:YYYYMMDD}.csv"),
        ]
        db.add_all(vars_seed)

        print("Seeding Demo Job Steps...")
        # Step 1: COPY_FILES
        step1 = JobStep(job_id=job_extract.MasterObject_id, StepType_id=st_copy.id, StepOrder=1, IsActive=True)
        db.add(step1)
        db.flush()

        step1_params = [
            JobStepParameter(job_step_id=step1.id, ParamName="Source", ParamValue="${WorkingFolder}/${BatchFilePattern}"),
            JobStepParameter(job_step_id=step1.id, ParamName="Dest", ParamValue="${ArchiveFolder}/${BatchFilePattern}"),
            JobStepParameter(job_step_id=step1.id, ParamName="CreateFolder", ParamValue="True"),
        ]
        db.add_all(step1_params)

        # Step 2: SQL_EXEC
        step2 = JobStep(job_id=job_extract.MasterObject_id, StepType_id=st_sql.id, StepOrder=2, IsActive=True)
        db.add(step2)
        db.flush()

        step2_params = [
            JobStepParameter(job_step_id=step2.id, ParamName="ConnectionString", ParamValue="sqlite:///autoapp.db"),
            JobStepParameter(job_step_id=step2.id, ParamName="Query", ParamValue="UPDATE Jobs SET Description='Last run completed' WHERE MasterObject_id=${JOB.MasterObject_id}"),
        ]
        db.add_all(step2_params)

        db.commit()
        print("Database seeded successfully!")

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
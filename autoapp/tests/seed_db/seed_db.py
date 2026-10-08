# seed_db.py
from app.database import engine, SessionLocal
from app.models import Base, MasterObject, Application, Process, Job, JobStep, StepType, JobStepParameter, Variable

# Create tables
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Add a MasterObject & Process
obj_proc = MasterObject(ObjectType="PROCESS", CreatedBy="test")
db.add(obj_proc)
db.flush()

proc = Process(MasterObject_id=obj_proc.MasterObject_id, Name="DEV-PROCESS", Abbr="DEVPROC")
db.add(proc)
db.flush()

# Add a MasterObject & Job
obj_job = MasterObject(ObjectType="JOB", CreatedBy="test")
db.add(obj_job)
db.flush()

job = Job(MasterObject_id=obj_job.MasterObject_id, process_id=proc.MasterObject_id, Name="JOBA", JobOrder=1)
db.add(job)
db.commit()

print("Database tables created and seeded with DEV-PROCESS and JOBA!")
db.close()
"""
The Stand-in Scheduler.

A deliberately small workload automation product, for trying AutoApp's
scheduler integration without a real one. It is a separate application with its
own database, as a real WLA would be, and it only talks to AutoApp the way a
real one would:

  - it runs AutoApp jobs by starting AutoApp's runner as an OS job, with the
    job's parameters in the environment (docs/INTEGRATION.md, section 1);
  - its pages open AutoApp's pages embedded (section 2);
  - it has an API, which AutoApp's connector for it reads a job's parameters from.

Run it from demo/scheduler_standin:

    python3 -m uvicorn standin.app:app --port 8100

Settings, from the environment:

    STANDIN_DATABASE_URL   its own database (default: SQLite file standin.db beside this folder)
    STANDIN_TOKEN          the token its API wants (default: standin-dev-token)
    STANDIN_NAME           what AutoApp calls it: the runner's --scheduler (default: STANDIN)
    STANDIN_AUTOAPP_URL    the AutoApp server, for its pages and the runner's --api-url (default: http://localhost:8000)
    STANDIN_AUTOAPP_DIR    AutoApp's code, where the runner is (default: the autoapp folder of this repository)

The runner it starts gets the rest of this process's environment, including
DATABASE_URL and AUTOAPP_WORKING_ROOT, so start it where AutoApp's settings are
loaded (dev_env.sh).
"""
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

DATABASE_URL = os.environ.get("STANDIN_DATABASE_URL") or f"sqlite:///{HERE.parent / 'standin.db'}"
TOKEN = os.environ.get("STANDIN_TOKEN", "standin-dev-token")
NAME = os.environ.get("STANDIN_NAME", "STANDIN")
AUTOAPP_URL = os.environ.get("STANDIN_AUTOAPP_URL", "http://localhost:8000").rstrip("/")
AUTOAPP_DIR = Path(os.environ.get("STANDIN_AUTOAPP_DIR") or REPO / "autoapp")
JOB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    autoapp_job_key = Column(String(320), nullable=True)     # the AutoApp job this one runs; set when it is first saved there
    description = Column(Text, nullable=True)
    business_date = Column(Boolean, nullable=False, default=False)   # give each run today's date as its business date
    parameters = relationship("Parameter", cascade="all, delete-orphan", order_by="Parameter.name")
    runs = relationship("Run", cascade="all, delete-orphan", back_populates="job")


class Parameter(Base):
    __tablename__ = "parameters"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    value = Column(Text, nullable=False, default="")
    secret = Column(Boolean, nullable=False, default=False)


class Run(Base):
    __tablename__ = "runs"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    instance_id = Column(String(64), nullable=False)
    business_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="RUNNING")      # RUNNING, SUCCESS, FAILED
    exit_code = Column(Integer, nullable=True)
    command = Column(Text, nullable=False)
    output = Column(Text, nullable=False, default="")
    started = Column(DateTime, nullable=False, default=utcnow)
    ended = Column(DateTime, nullable=True)
    job = relationship("Job", back_populates="runs")


Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def authorised(authorization: Optional[str] = Header(None), sec_fetch_site: Optional[str] = Header(None)):
    """
    Another program, such as AutoApp's connector, must send 'Authorization: Bearer <token>',
    as a real WLA's API would want a credential. The Stand-in's own pages are let through:
    a browser marks their requests Sec-Fetch-Site: same-origin, which no other site's page
    can do. Like AutoApp's own pages, they have no user accounts; it is a stand-in.
    """
    if authorization == f"Bearer {TOKEN}" or sec_fetch_site == "same-origin":
        return
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The Stand-in Scheduler's API needs its token.")


# ---------- What the API takes and gives ----------

class ParameterIn(BaseModel):
    name: str = Field(..., max_length=100)
    value: Optional[str] = Field(None, description="For a secret that exists already, null keeps its value")
    secret: bool = False


class ParameterOut(BaseModel):
    name: str
    value: Optional[str] = Field(None, description="Null for a secret: a secret is never given out")
    secret: bool


class JobIn(BaseModel):
    name: str = Field(..., max_length=100)
    autoapp_job_key: Optional[str] = None
    description: Optional[str] = None
    business_date: bool = False
    parameters: List[ParameterIn] = []


class JobOut(BaseModel):
    name: str
    autoapp_job_key: Optional[str] = None
    description: Optional[str] = None
    business_date: bool
    parameters: List[ParameterOut]
    last_run: Optional["RunOut"] = None


class RunOut(BaseModel):
    id: int
    job: str
    autoapp_job_key: Optional[str] = None
    instance_id: str
    business_date: Optional[date] = None
    status: str
    exit_code: Optional[int] = None
    command: str
    output: Optional[str] = None
    started: datetime
    ended: Optional[datetime] = None


JobOut.model_rebuild()


def describe_run(run: Run, with_output=True) -> RunOut:
    return RunOut(id=run.id, job=run.job.name, autoapp_job_key=run.job.autoapp_job_key, instance_id=run.instance_id,
                  business_date=run.business_date, status=run.status, exit_code=run.exit_code, command=run.command,
                  output=run.output if with_output else None, started=run.started, ended=run.ended)


def describe_job(job: Job) -> JobOut:
    last = max(job.runs, key=lambda r: r.id) if job.runs else None
    return JobOut(name=job.name, autoapp_job_key=job.autoapp_job_key, description=job.description,
                  business_date=job.business_date,
                  parameters=[ParameterOut(name=p.name, value=None if p.secret else p.value, secret=p.secret)
                              for p in job.parameters],
                  last_run=describe_run(last, with_output=False) if last else None)


def find_job(db: Session, name: str) -> Job:
    job = db.query(Job).filter(Job.name == name).first()
    if job is None:
        raise HTTPException(404, f"The Stand-in Scheduler has no job '{name}'.")
    return job


# ---------- The API ----------

app = FastAPI(title="Stand-in Scheduler", description="Plays a WLA's part for AutoApp. See the module's docstring.")


@app.get("/api/config")
def config():
    """What the pages need to know: where AutoApp is, and what AutoApp calls this scheduler. Needs no token."""
    return {"autoapp_url": AUTOAPP_URL, "scheduler_name": NAME}


@app.get("/api/jobs", response_model=List[JobOut], dependencies=[Depends(authorised)])
def list_jobs(db: Session = Depends(get_db)):
    return [describe_job(job) for job in db.query(Job).order_by(Job.name)]


@app.get("/api/jobs/{name}", response_model=JobOut, dependencies=[Depends(authorised)])
def get_job(name: str, db: Session = Depends(get_db)):
    """One job with its parameters. This is what AutoApp's connector reads. Secret values are not given."""
    return describe_job(find_job(db, name))


def apply(db: Session, job: Job, payload: JobIn) -> None:
    if not JOB_NAME.match(payload.name.strip()):
        raise HTTPException(422, f"Invalid job name '{payload.name}': letters, digits, '-', '_' and '.'.")
    job.name = payload.name.strip()
    job.autoapp_job_key = (payload.autoapp_job_key or "").strip() or None
    job.description = (payload.description or "").strip() or None
    job.business_date = payload.business_date
    names = [p.name.strip() for p in payload.parameters]
    for name in names:
        if not PARAMETER_NAME.match(name):
            raise HTTPException(422, f"Invalid parameter name '{name}': letters, digits and underscores.")
    if len(set(names)) != len(names):
        raise HTTPException(422, "A parameter is listed more than once.")
    have = {p.name: p for p in job.parameters}
    job.parameters = []
    for wanted in payload.parameters:
        old = have.get(wanted.name.strip())
        value = old.value if (wanted.value is None and old is not None and old.secret and wanted.secret) else (wanted.value or "")
        job.parameters.append(Parameter(name=wanted.name.strip(), value=value, secret=wanted.secret))


@app.post("/api/jobs", response_model=JobOut, status_code=201, dependencies=[Depends(authorised)])
def create_job(payload: JobIn, db: Session = Depends(get_db)):
    if db.query(Job).filter(Job.name == payload.name.strip()).first():
        raise HTTPException(409, f"There is already a job '{payload.name.strip()}'.")
    job = Job()
    apply(db, job, payload)
    db.add(job)
    db.commit()
    return describe_job(job)


@app.put("/api/jobs/{name}", response_model=JobOut, dependencies=[Depends(authorised)])
def change_job(name: str, payload: JobIn, db: Session = Depends(get_db)):
    job = find_job(db, name)
    if payload.name.strip() != name and db.query(Job).filter(Job.name == payload.name.strip()).first():
        raise HTTPException(409, f"There is already a job '{payload.name.strip()}'.")
    apply(db, job, payload)
    db.commit()
    return describe_job(job)


@app.delete("/api/jobs/{name}", status_code=204, dependencies=[Depends(authorised)])
def delete_job(name: str, db: Session = Depends(get_db)):
    db.delete(find_job(db, name))
    db.commit()


def _finish(run_id: int, process: subprocess.Popen) -> None:
    """Waits for the runner, as a WLA waits for an OS job, and keeps its output and exit code."""
    output, _ = process.communicate()
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        run.output = output or ""
        run.exit_code = process.returncode
        run.status = "SUCCESS" if process.returncode == 0 else "FAILED"
        run.ended = utcnow()
        db.commit()
    finally:
        db.close()


@app.post("/api/jobs/{name}/submit", response_model=RunOut, status_code=202, dependencies=[Depends(authorised)])
def submit(name: str, db: Session = Depends(get_db)):
    """
    Runs the job now: starts AutoApp's runner as an OS job, the way a WLA would.
    The job's parameters go into its environment; the names of the secret ones go
    in AUTOAPP_MASK_ENV, so the runner masks their values in the job log.
    """
    job = find_job(db, name)
    if not job.autoapp_job_key:
        raise HTTPException(422, f"Job '{name}' has no AutoApp job yet. Edit it in AutoApp first.")
    run = Run(job=job, instance_id="pending", command="", business_date=date.today() if job.business_date else None)
    db.add(run)
    db.flush()
    run.instance_id = f"SIS-{run.id}"

    command = ["python3", "-m", "engine.runner", "--job-key", job.autoapp_job_key, "--instance-id", run.instance_id,
               "--scheduler", NAME, "--api-url", AUTOAPP_URL]
    if run.business_date:
        command += ["--business-date", run.business_date.isoformat()]
    if os.environ.get("AUTOAPP_WORKING_ROOT"):
        command += ["--working-root", os.environ["AUTOAPP_WORKING_ROOT"]]
    if os.environ.get("AUTOAPP_SPOOL_DIR"):
        command += ["--spool-dir", os.environ["AUTOAPP_SPOOL_DIR"]]
    run.command = " ".join(command)
    db.commit()

    environment = {**os.environ, **{p.name: p.value for p in job.parameters},
                   "AUTOAPP_MASK_ENV": ",".join(p.name for p in job.parameters if p.secret)}
    process = subprocess.Popen([sys.executable] + command[1:], cwd=AUTOAPP_DIR, env=environment, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    threading.Thread(target=_finish, args=(run.id, process), daemon=True).start()
    return describe_run(run)


@app.get("/api/jobs/{name}/autoapp", dependencies=[Depends(authorised)])
def autoapp_summary(name: str, db: Session = Depends(get_db)):
    """
    The AutoApp job this one runs, as AutoApp describes it for a scheduler
    (GET /api/v1/jobs/{key}/summary), asked by this server the way a real WLA's
    plug-in would ask from its server. Gives {"summary": ...} or {"error": "..."}.
    """
    job = find_job(db, name)
    if not job.autoapp_job_key:
        return {"summary": None, "error": None}
    query = urllib.parse.urlencode({"scheduler": NAME, "wla_job": job.name})
    url = f"{AUTOAPP_URL}/api/v1/jobs/{urllib.parse.quote(job.autoapp_job_key, safe='')}/summary?{query}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return {"summary": json.loads(response.read().decode("utf-8")), "error": None}
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail")
        except ValueError:
            detail = None
        return {"summary": None, "error": detail or f"AutoApp answered {e.code}."}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"summary": None, "error": f"Could not reach AutoApp at {AUTOAPP_URL}: {e}"}


@app.get("/api/runs", response_model=List[RunOut], dependencies=[Depends(authorised)])
def list_runs(job: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Run).order_by(Run.id.desc())
    if job:
        query = query.join(Job).filter(Job.name == job)
    return [describe_run(run, with_output=False) for run in query.limit(200)]


@app.get("/api/runs/{run_id}", response_model=RunOut, dependencies=[Depends(authorised)])
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, f"There is no run {run_id}.")
    return describe_run(run)


# ---------- Its pages ----------

app.mount("/ui", StaticFiles(directory=HERE / "static", html=True), name="ui")
# The look is borrowed from AutoApp, then changed (standin.css), so the two are never mistaken for each other
app.mount("/autoapp-ui", StaticFiles(directory=AUTOAPP_DIR / "ui"), name="autoapp-ui")


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/ui/")

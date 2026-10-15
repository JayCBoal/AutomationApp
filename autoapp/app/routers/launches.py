"""
Running a job from the web interface, as a scheduler would:

    POST /api/v1/launches                 start the runner for a job; returns at once
    GET  /api/v1/launches/{launch_id}     whether that runner is still going, and how it ended

The server starts the real runner (python3 -m engine.runner) as a separate
process, with the same command line a scheduler would use, plus the run ID the
page then follows. The runner records the run, its operations and its job log
through this API as it goes, so the run appears in Job History and its log can
be read while it runs (GET /api/v1/runs/{run_id}).

The server keeps its launches in memory: after a restart, a launch's process is
forgotten, but its run, operations and log are in the database as usual. There
are no user accounts yet, so anyone who can reach the page can run a job.
"""
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job, JobRun
from engine import job_log

router = APIRouter(prefix="/api/v1/launches", tags=["Runs"])

AUTOAPP_DIR = Path(__file__).resolve().parents[2]
SCHEDULER_NAME = "AutoApp UI"
OUTPUT_KEPT = 200           # lines of the runner's own output kept, for a runner that never got going


class LaunchRequest(BaseModel):
    job_key: str
    instance_id: Optional[str] = Field(
        None, max_length=100, description="Leave out for one made from the time, e.g. UI-20261015-183012")
    log_level: str = Field(job_log.DEFAULT_LEVEL, description="DEBUG, DETAIL, SUMMARY or SILENT")


class LaunchOut(BaseModel):
    launch_id: str
    run_id: str = Field(..., description="The run's ID in Job History; GET /api/v1/runs/{run_id} follows it")
    job_key: str
    instance_id: str
    command: str = Field(..., description="The command the server ran, as a scheduler would run it")
    state: str = Field(..., description="RUNNING while the runner process is going, then FINISHED")
    recorded: bool = Field(False, description="Whether the run has reached the database yet, so it can be read")
    exit_code: Optional[int] = Field(None, description="0 if every step succeeded, 1 if the job failed")
    output: List[str] = Field(default_factory=list, description=(
        "The runner's own output, once it has finished. The same as the run's log, unless the runner "
        "failed before it could record the run"))


class _Launch:
    def __init__(self, launch_id, run_id, job_key, instance_id, command, process, output_path):
        self.launch_id, self.run_id, self.job_key, self.instance_id = launch_id, run_id, job_key, instance_id
        self.command, self.process, self.output_path = command, process, output_path

    def describe(self, db: Optional[Session] = None) -> LaunchOut:
        code = self.process.poll()
        recorded = db is not None and db.query(JobRun.id).filter(JobRun.RunID == self.run_id).first() is not None
        output = []
        if code is not None:
            try:
                output = Path(self.output_path).read_text(errors="replace").splitlines()[-OUTPUT_KEPT:]
            except OSError:
                pass
        return LaunchOut(launch_id=self.launch_id, run_id=self.run_id, job_key=self.job_key,
                         instance_id=self.instance_id, command=self.command,
                         state="RUNNING" if code is None else "FINISHED", exit_code=code, output=output,
                         recorded=recorded)


_launches: Dict[str, _Launch] = {}
_lock = threading.Lock()


def _instance_id() -> str:
    return datetime.now().strftime("UI-%Y%m%d-%H%M%S")


@router.post("", response_model=LaunchOut, status_code=status.HTTP_202_ACCEPTED)
def launch(payload: LaunchRequest, request: Request, db: Session = Depends(get_db)):
    """Starts a job. The answer comes at once; follow the run with GET /api/v1/runs/{run_id}."""
    job_key = payload.job_key.strip()
    if not db.query(Job.MasterObject_id).filter(Job.JobKey == job_key).first():
        raise HTTPException(404, f"No job with JobKey '{job_key}' exists.")
    try:
        level = payload.log_level.strip().upper()
        job_log.level_number(level)         # refuses a level the runner would not know
    except ValueError as e:
        raise HTTPException(422, str(e))
    instance_id = (payload.instance_id or "").strip() or _instance_id()
    if db.query(JobRun.id).filter(JobRun.JobKey == job_key, JobRun.SchedulerInstanceID == instance_id).first():
        raise HTTPException(409, f"Job '{job_key}' has already run as instance '{instance_id}'. "
                                 f"Give another instance ID, or leave it blank for a new one.")

    run_id = str(uuid.uuid4())
    api_url = str(request.base_url).rstrip("/")
    working_root = os.environ.get("AUTOAPP_WORKING_ROOT")
    command = [sys.executable, "-m", "engine.runner", "--job-key", job_key, "--instance-id", instance_id,
               "--log-level", level, "--scheduler", SCHEDULER_NAME, "--api-url", api_url,
               "--spool-dir", os.environ.get("AUTOAPP_SPOOL_DIR") or str(AUTOAPP_DIR / "spool"), "--run-id", run_id]
    if working_root:
        command += ["--working-root", working_root]

    output = tempfile.NamedTemporaryFile(prefix="autoapp_launch_", suffix=".log", delete=False)
    try:
        process = subprocess.Popen(command, cwd=AUTOAPP_DIR, stdout=output, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL)
    finally:
        output.close()

    shown = " ".join(["python3", "-m", "engine.runner", "--job-key", job_key, "--instance-id", instance_id,
                      "--log-level", level])
    entry = _Launch(str(uuid.uuid4()), run_id, job_key, instance_id, shown, process, output.name)
    with _lock:
        _launches[entry.launch_id] = entry
    return entry.describe()


@router.get("/{launch_id}", response_model=LaunchOut)
def get_launch(launch_id: str, db: Session = Depends(get_db)):
    with _lock:
        entry = _launches.get(launch_id)
    if entry is None:
        raise HTTPException(404, "This server has no record of that launch. If it was restarted since, "
                                 "look for the run in Job History.")
    return entry.describe(db)

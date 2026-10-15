"""
The records of what happened: job runs, and changes to definitions.

    GET /api/v1/runs             Job History: one row per run of a job
    GET /api/v1/runs/{run_id}    one run, with its job log
    GET /api/v1/audits    Audit Log: one row per change to a job, endpoint, application, entity or site
"""
import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Audit, JobRun, JobRunLog, Operation

MAX_RESULTS = 500
router = APIRouter(tags=["History"])


class RunOut(BaseModel):
    run_id: str
    job_key: str
    instance_id: str
    run_number: int
    scheduler: Optional[str] = None
    host: Optional[str] = None
    status: str
    started: Optional[datetime] = None
    ended: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    operations: int
    failed_operations: int
    has_log: bool = False


@router.get("/api/v1/runs", response_model=List[RunOut])
def list_runs(
    job_key: Optional[str] = Query(None, description="Part of a JobKey"),
    instance_id: Optional[str] = Query(None, description="The scheduler's instance ID, exact"),
    scheduler: Optional[str] = Query(None, description="Part of the scheduler's name"),
    status: Optional[str] = Query(None, description="SUCCESS, FAILED or RUNNING"),
    date_from: Optional[datetime] = Query(None, description="Runs that started at or after this time (UTC)"),
    date_to: Optional[datetime] = Query(None, description="Runs that started at or before this time (UTC)"),
    limit: int = Query(MAX_RESULTS, ge=1, le=MAX_RESULTS),
    db: Session = Depends(get_db),
):
    """Job History: every run AutoApp has a record of, newest first, with how many files each handled."""
    query = db.query(JobRun)
    if job_key:
        query = query.filter(JobRun.JobKey.ilike(f"%{job_key}%"))
    if instance_id:
        query = query.filter(JobRun.SchedulerInstanceID == instance_id)
    if scheduler:
        query = query.filter(JobRun.SchedulerName.ilike(f"%{scheduler}%"))
    if status:
        query = query.filter(JobRun.Status == status.upper())
    if date_from:
        query = query.filter(JobRun.StartedDateTime >= date_from)
    if date_to:
        query = query.filter(JobRun.StartedDateTime <= date_to)
    runs = query.order_by(JobRun.StartedDateTime.desc(), JobRun.id.desc()).limit(limit).all()

    counts = {}
    if runs:
        rows = (
            db.query(Operation.JobRun_id, func.count(Operation.id),
                     func.sum(case((Operation.OpStatus == "FAILED", 1), else_=0)))
            .filter(Operation.JobRun_id.in_([run.id for run in runs])).group_by(Operation.JobRun_id)
        )
        counts = {run_id: (total, int(failed or 0)) for run_id, total, failed in rows}
    logged = set()
    if runs:
        logged = {run_id for (run_id,) in db.query(JobRunLog.JobRun_id).filter(
            JobRunLog.JobRun_id.in_([run.id for run in runs])).distinct()}
    return [_describe(run, counts.get(run.id, (0, 0)), run.id in logged) for run in runs]


def _describe(run: JobRun, counts, has_log: bool) -> RunOut:
    return RunOut(
        run_id=run.RunID, job_key=run.JobKey, instance_id=run.SchedulerInstanceID, run_number=run.RunNumber,
        scheduler=run.SchedulerName, host=run.Host, status=run.Status, started=run.StartedDateTime,
        ended=run.EndedDateTime,
        duration_seconds=(run.EndedDateTime - run.StartedDateTime).total_seconds()
        if run.StartedDateTime and run.EndedDateTime else None,
        error=run.ErrorMessage, operations=counts[0], failed_operations=counts[1], has_log=has_log,
    )


class RunDetail(RunOut):
    log: List[str] = []


@router.get("/api/v1/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str, db: Session = Depends(get_db)):
    """
    One run, with its job log as far as it has arrived: the runner sends it after
    each step, so a run still going shows what it has done so far. Secret values
    were masked by the runner.
    """
    run = db.query(JobRun).filter(JobRun.RunID == run_id).first()
    if run is None:
        raise HTTPException(404, f"AutoApp has no record of run '{run_id}'.")
    total, failed = (db.query(func.count(Operation.id), func.sum(case((Operation.OpStatus == "FAILED", 1), else_=0)))
                     .filter(Operation.JobRun_id == run.id).one())
    chunks = db.query(JobRunLog.LogText).filter(JobRunLog.JobRun_id == run.id).order_by(JobRunLog.Seq).all()
    lines = [line for (text,) in chunks for line in text.split("\n")]
    return RunDetail(**_describe(run, (total or 0, int(failed or 0)), bool(chunks)).model_dump(), log=lines)


class AuditOut(BaseModel):
    id: int
    time: Optional[datetime] = None
    action: str
    kind: Optional[str] = None          # jobs, endpoints, applications, entities or sites
    name: Optional[str] = None          # the job key or name of what was changed
    performed_by: Optional[str] = None
    changes: List[str]


# Which key in an audit row's details names what was changed, by the start of its action
_SUBJECTS = {"JOB": ("jobs", "job_key"), "ENDPOINT": ("endpoints", "endpoint"),
             "APPLICATION": ("applications", "application"), "ENTITY": ("entities", "entity"), "SITE": ("sites", "site"),
             "TAG": ("tags", "tag"), "SETTING": ("settings", "setting")}


@router.get("/api/v1/audits", response_model=List[AuditOut])
def list_audits(
    action: Optional[str] = Query(None, description="Part of the action, such as JOB_UPDATED or DELETED"),
    name: Optional[str] = Query(None, description="Part of the name of what was changed"),
    performed_by: Optional[str] = Query(None, description="Part of who made the change"),
    date_from: Optional[datetime] = Query(None, description="Changes at or after this time (UTC)"),
    date_to: Optional[datetime] = Query(None, description="Changes at or before this time (UTC)"),
    limit: int = Query(MAX_RESULTS, ge=1, le=MAX_RESULTS),
    db: Session = Depends(get_db),
):
    """The Audit Log: every change to a definition, newest first, with what it changed in words."""
    query = db.query(Audit)
    if action:
        query = query.filter(Audit.Action.ilike(f"%{action.replace(' ', '_')}%"))
    if performed_by:
        query = query.filter(Audit.PerformedBy.ilike(f"%{performed_by}%"))
    if name:
        query = query.filter(Audit.Details.ilike(f"%{name}%"))
    if date_from:
        query = query.filter(Audit.CreatedDateTime >= date_from)
    if date_to:
        query = query.filter(Audit.CreatedDateTime <= date_to)

    results = []
    for audit in query.order_by(Audit.CreatedDateTime.desc(), Audit.id.desc()):
        details = json.loads(audit.Details) if audit.Details else {}
        kind, key = _SUBJECTS.get(audit.Action.split("_")[0], (None, None))
        subject = details.get(key) if key else None
        if name and (subject is None or name.lower() not in subject.lower()):
            continue                        # the name appeared somewhere else in the details
        results.append(AuditOut(id=audit.id, time=audit.CreatedDateTime, action=audit.Action, kind=kind, name=subject,
                                performed_by=audit.PerformedBy, changes=details.get("changes", [])))
        if len(results) >= limit:
            break
    return results

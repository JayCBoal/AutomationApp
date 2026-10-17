"""
The records of what happened: job runs, and changes to definitions.

    GET /api/v1/runs             Job History: one row per run of a job or a workflow
    GET /api/v1/runs/{run_id}    one run, with its job log, and a workflow run's jobs
    POST /api/v1/runs/{run_id}/cancel   asks a workflow run to start nothing more
    GET /api/v1/audits    Audit Log: one row per change to a job, endpoint, application, entity or site
"""
import json
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Audit, JobRun, JobRunLog, Operation, WorkflowRunItem, utcnow

MAX_RESULTS = 500
router = APIRouter(tags=["History"])


class RunOut(BaseModel):
    run_id: str
    job_key: str
    instance_id: str
    run_number: int
    scheduler: Optional[str] = None
    business_date: Optional[date] = None
    host: Optional[str] = None
    status: str
    started: Optional[datetime] = None
    ended: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    operations: int
    failed_operations: int
    has_log: bool = False
    job_type: str = "STEPS"
    return_code: Optional[int] = None
    reason: Optional[str] = None
    parent_run_id: Optional[str] = None
    workflow_path: Optional[str] = None
    attempt: int = 1


@router.get("/api/v1/runs", response_model=List[RunOut])
def list_runs(
    job_key: Optional[str] = Query(None, description="Part of a JobKey"),
    instance_id: Optional[str] = Query(None, description="The scheduler's instance ID, exact"),
    scheduler: Optional[str] = Query(None, description="Part of the scheduler's name"),
    status: Optional[str] = Query(None, description="SUCCESS, FAILED or RUNNING"),
    date_from: Optional[datetime] = Query(None, description="Runs that started at or after this time (UTC)"),
    date_to: Optional[datetime] = Query(None, description="Runs that started at or before this time (UTC)"),
    job_type: Optional[str] = Query(None, description="STEPS for job runs, WORKFLOW for workflow runs"),
    within: Optional[str] = Query(None, description="A run's RunID: that run and the runs inside it, however deep"),
    limit: int = Query(MAX_RESULTS, ge=1, le=MAX_RESULTS),
    db: Session = Depends(get_db),
):
    """Job History: every run AutoApp has a record of, newest first, with how many files each handled."""
    query = db.query(JobRun)
    if job_type:
        query = query.filter(JobRun.JobType == job_type.strip().upper())
    if within:
        query = query.filter(JobRun.id.in_(_run_and_inside(db, within)))
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
    parents = _parent_run_ids(db, runs)
    return [_describe(run, counts.get(run.id, (0, 0)), run.id in logged, parents.get(run.ParentRun_id)) for run in runs]


def _run_and_inside(db: Session, run_id: str) -> List[int]:
    """The ids of a run and of every run inside it: a workflow's job runs, and theirs if they are workflows."""
    top = db.query(JobRun.id).filter(JobRun.RunID == run_id).first()
    found, frontier = ([top[0]] if top else []), ([top[0]] if top else [])
    while frontier:
        frontier = [i for (i,) in db.query(JobRun.id).filter(JobRun.ParentRun_id.in_(frontier))]
        found += frontier
    return found


def _parent_run_ids(db: Session, runs) -> dict:
    ids = {run.ParentRun_id for run in runs if run.ParentRun_id}
    return dict(db.query(JobRun.id, JobRun.RunID).filter(JobRun.id.in_(ids)).all()) if ids else {}


def _describe(run: JobRun, counts, has_log: bool, parent_run_id: Optional[str] = None) -> RunOut:
    return RunOut(
        run_id=run.RunID, job_key=run.JobKey, instance_id=run.SchedulerInstanceID, run_number=run.RunNumber,
        scheduler=run.SchedulerName, business_date=run.BusinessDate, host=run.Host, status=run.Status,
        started=run.StartedDateTime,
        ended=run.EndedDateTime,
        duration_seconds=(run.EndedDateTime - run.StartedDateTime).total_seconds()
        if run.StartedDateTime and run.EndedDateTime else None,
        error=run.ErrorMessage, operations=counts[0], failed_operations=counts[1], has_log=has_log,
        job_type=run.JobType or "STEPS", return_code=run.ReturnCode, reason=run.Reason, parent_run_id=parent_run_id,
        workflow_path=run.WorkflowPath, attempt=run.Attempt or 1,
    )


class RunItemOut(BaseModel):
    """One job of a workflow run, and where it stands, whether or not it has started."""
    name: str
    path: str
    job_key: str
    status: str = "PENDING"
    reason: Optional[str] = None
    return_code: Optional[int] = None
    attempt: int = 0
    run_id: Optional[str] = None
    started: Optional[datetime] = None
    ended: Optional[datetime] = None


class RunDetail(RunOut):
    log: List[str] = []
    items: List[RunItemOut] = []
    cancel_requested: bool = False


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
    parent = db.get(JobRun, run.ParentRun_id).RunID if run.ParentRun_id and db.get(JobRun, run.ParentRun_id) else None
    return RunDetail(**_describe(run, (total or 0, int(failed or 0)), bool(chunks), parent).model_dump(), log=lines,
                     items=_run_items(db, run), cancel_requested=run.CancelRequestedDateTime is not None)


def _run_items(db: Session, run: JobRun) -> List[RunItemOut]:
    rows = db.query(WorkflowRunItem).filter(WorkflowRunItem.WorkflowRun_id == run.id).order_by(WorkflowRunItem.ItemOrder)
    return [RunItemOut(name=r.ItemName, path=r.Path, job_key=r.JobKey, status=r.Status, reason=r.Reason,
                       return_code=r.ReturnCode, attempt=r.Attempt, run_id=r.child_run.RunID if r.child_run else None,
                       started=r.StartedDateTime, ended=r.EndedDateTime) for r in rows]


@router.post("/api/v1/runs/{run_id}/cancel", response_model=RunDetail)
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    """
    Asks a workflow run that is still going to start nothing more. The jobs running now
    finish; those not started will not run. (Cancelling a single job comes later.)
    """
    run = db.query(JobRun).filter(JobRun.RunID == run_id).first()
    if run is None:
        raise HTTPException(404, f"AutoApp has no record of run '{run_id}'.")
    if run.JobType != "WORKFLOW":
        raise HTTPException(422, f"Run '{run_id}' is a job's run. Only a workflow run can be cancelled for now.")
    if run.Status != "RUNNING":
        raise HTTPException(409, f"Workflow '{run.JobKey}' has already ended ({run.Status}), so there is nothing to cancel.")
    if run.CancelRequestedDateTime is None:
        run.CancelRequestedDateTime = utcnow()
        db.commit()
    return get_run(run_id, db)


class AuditOut(BaseModel):
    id: int
    time: Optional[datetime] = None
    action: str
    kind: Optional[str] = None          # jobs, endpoints, applications, entities or sites
    name: Optional[str] = None          # the job key or name of what was changed
    performed_by: Optional[str] = None
    changes: List[str]


# Which key in an audit row's details names what was changed, by the start of its action
_SUBJECTS = {"JOB": ("jobs", "job_key"), "ENDPOINT": ("endpoints", "endpoint"), "SCHEDULER": ("schedulers", "scheduler"),
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

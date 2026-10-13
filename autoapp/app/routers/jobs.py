from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional

from app.database import get_db
from app.models import Job, JobRun, JobStep, JobStepParameter
from app.schemas import (
    JobCheckResult, JobInitRequest, JobInitResponse, JobStepPayloadSchema, JobSummary, LastRun
)
from engine.step_catalog import ENDPOINT_SUFFIX
from engine.handlers import get_handler
from engine.preflight import prepare_job
from engine.scope_engine import ScopeResolutionEngine
from engine.step_params import resolve_step

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])

MAX_RESULTS = 500


def job_problems(db: Session, job: Job) -> List[str]:
    """Everything that would stop the job from running, as the runner would report it. Runs nothing."""
    problems = []
    if not job.IsActive:
        problems.append(f"Job '{job.JobKey}' is disabled.")
    engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="CHECK")
    engine.build_context()
    return problems + prepare_job(db, job, engine)[1]


@router.get("", response_model=List[JobSummary])
def list_jobs(
    job_key: Optional[str] = Query(None, description="Part of a JobKey"),
    description: Optional[str] = Query(None, description="Part of the description"),
    active: Optional[bool] = Query(None, description="true for enabled jobs only, false for disabled only"),
    endpoint: Optional[str] = Query(None, description="Part of the name of an endpoint one of the job's steps uses"),
    limit: int = Query(MAX_RESULTS, ge=1, le=MAX_RESULTS),
    db: Session = Depends(get_db),
):
    """
    The job search. Text criteria ignore case and match anywhere in the field.
    Jobs are returned in name order, each with its step count, the endpoints it
    uses and its most recent run.
    """
    endpoint_param = JobStepParameter.ParamName.like(f"%{ENDPOINT_SUFFIX}")

    query = db.query(Job)
    if job_key:
        query = query.filter(Job.JobKey.ilike(f"%{job_key}%"))
    if description:
        query = query.filter(Job.Description.ilike(f"%{description}%"))
    if active is not None:
        query = query.filter(Job.IsActive.is_(active))
    if endpoint:
        uses_endpoint = (
            db.query(JobStep.id)
            .join(JobStepParameter, JobStepParameter.job_step_id == JobStep.id)
            .filter(JobStep.job_id == Job.MasterObject_id, endpoint_param,
                    JobStepParameter.ParamValue.ilike(f"%{endpoint}%"))
        )
        query = query.filter(uses_endpoint.exists())
    jobs = query.order_by(func.lower(Job.JobKey), Job.JobKey).limit(limit).all()
    if not jobs:
        return []

    job_ids = [job.MasterObject_id for job in jobs]
    job_keys = [job.JobKey for job in jobs]

    # Steps and the endpoints they name, for all the jobs found, in two queries
    step_counts = {job_id: [0, 0] for job_id in job_ids}        # [enabled, disabled]
    for job_id, is_active in db.query(JobStep.job_id, JobStep.IsActive).filter(JobStep.job_id.in_(job_ids)):
        step_counts[job_id][0 if is_active else 1] += 1

    endpoints = {job_id: set() for job_id in job_ids}
    named = (
        db.query(JobStep.job_id, JobStepParameter.ParamValue)
        .join(JobStepParameter, JobStepParameter.job_step_id == JobStep.id)
        .filter(JobStep.job_id.in_(job_ids), endpoint_param)
    )
    for job_id, endpoint_name in named:
        if endpoint_name:
            endpoints[job_id].add(endpoint_name)

    # The most recent run of each job: the one with the latest start time
    latest = (
        db.query(JobRun.JobKey, func.max(JobRun.StartedDateTime).label("started"))
        .filter(JobRun.JobKey.in_(job_keys))
        .group_by(JobRun.JobKey)
        .subquery()
    )
    last_runs = {}
    recent = db.query(JobRun).join(
        latest, (JobRun.JobKey == latest.c.JobKey) & (JobRun.StartedDateTime == latest.c.started))
    for run in recent.order_by(JobRun.id):
        last_runs[run.JobKey] = LastRun(
            status=run.Status, started=run.StartedDateTime, ended=run.EndedDateTime,
            instance_id=run.SchedulerInstanceID, run_number=run.RunNumber, error=run.ErrorMessage,
        )

    # Each job found is put through the pre-run check, so the search shows at a glance which would run
    problem_counts = {job.MasterObject_id: len(job_problems(db, job)) for job in jobs}

    return [
        JobSummary(
            job_key=job.JobKey,
            description=job.Description,
            active=bool(job.IsActive),
            step_count=step_counts[job.MasterObject_id][0],
            disabled_step_count=step_counts[job.MasterObject_id][1],
            endpoints=sorted(endpoints[job.MasterObject_id]),
            ready=problem_counts[job.MasterObject_id] == 0,
            problem_count=problem_counts[job.MasterObject_id],
            last_run=last_runs.get(job.JobKey),
            modified=job.ModifiedDateTime or job.CreatedDateTime,
            modified_by=job.ModifiedBy or job.CreatedBy,
        )
        for job in jobs
    ]


@router.post("/init", response_model=JobInitResponse, status_code=status.HTTP_200_OK)
def initialize_job(payload: JobInitRequest, db: Session = Depends(get_db)):
    """Resolves the job's variable scope and returns its steps with parameters interpolated."""

    # 1. Lookup Job by its JobKey
    job = db.query(Job).filter(Job.JobKey == payload.job_key).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No job with JobKey '{payload.job_key}' exists."
        )

    # 2. Instantiate and evaluate Scope Engine
    engine = ScopeResolutionEngine(
        db=db,
        job_id=job.MasterObject_id,
        instance_id=payload.instance_id
    )
    resolved_vars = engine.build_context()

    # 3. Fetch steps and interpolate parameter text
    job_steps = (
        db.query(JobStep)
        .filter(JobStep.job_id == job.MasterObject_id)
        .order_by(JobStep.StepOrder)
        .all()
    )

    compiled_steps: List[JobStepPayloadSchema] = []
    for step in job_steps:
        step_type = step.step_type.HandlerClass if step.step_type else None
        try:
            handler_cls = get_handler(step_type) if step_type else None
        except ValueError:
            handler_cls = None  # no handler on this server; parameters are still interpolated

        try:
            resolved = resolve_step(step, handler_cls, engine, db)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        compiled_steps.append(
            JobStepPayloadSchema(
                step_number=step.StepOrder,
                step_type=step.step_type.TypeName if step.step_type else "GENERIC",
                handler_class=step_type or "BaseHandler",
                title=step.Title,
                parameters=resolved.params,
                source_endpoint_id=resolved.source_endpoint_id,
                dest_endpoint_id=resolved.dest_endpoint_id
            )
        )

    working_folder = engine.working_folder or ""

    return JobInitResponse(
        status="SUCCESS",
        execution_instance_id=payload.instance_id,
        job_id=job.MasterObject_id,
        working_folder=working_folder,
        variables=resolved_vars,
        steps=compiled_steps
    )


@router.get("/{job_key}/check", response_model=JobCheckResult)
def check_job(job_key: str, db: Session = Depends(get_db)):
    """
    Checks a job without running it: every active step against its step type,
    every placeholder, every file location. Returns each problem found, exactly
    as the runner would report it. The same check is made whenever the job runs.
    """
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No job with JobKey '{job_key}' exists.")

    problems = job_problems(db, job)
    return JobCheckResult(job_key=job_key, valid=not problems, problems=problems)

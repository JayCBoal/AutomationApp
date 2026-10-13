from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional

from app.database import get_db
from app.models import Job, JobStep
from app.schemas import JobCheckResult, JobInitRequest, JobInitResponse, JobStepPayloadSchema
from engine.handlers import get_handler
from engine.preflight import prepare_job
from engine.scope_engine import ScopeResolutionEngine
from engine.step_params import resolve_step

router = APIRouter(prefix="/api/v1/jobs", tags=["Job Execution"])


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

    problems = []
    if not job.IsActive:
        problems.append(f"Job '{job_key}' is disabled.")
    engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="CHECK")
    engine.build_context()
    problems += prepare_job(db, job, engine)[1]
    return JobCheckResult(job_key=job_key, valid=not problems, problems=problems)

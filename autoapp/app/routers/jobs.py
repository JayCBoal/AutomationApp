from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional

from app.database import get_db
from app.models import Job, Process, JobStep
from app.schemas import JobInitRequest, JobInitResponse, JobStepPayloadSchema
from engine.scope_engine import ScopeResolutionEngine

router = APIRouter(prefix="/api/v1/jobs", tags=["Job Execution"])


@router.post("/init", response_model=JobInitResponse, status_code=status.HTTP_200_OK)
def initialize_job(payload: JobInitRequest, db: Session = Depends(get_db)):
    """Resolves job scope hierarchy using either direct Job lookup or Process + Job pair."""
    
    # 1. Lookup Job and Process (supports both direct job lookup and process-scoped lookup)
    if payload.process_name:
        process = db.query(Process).filter(Process.Name == payload.process_name).first()
        if not process:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Process '{payload.process_name}' not found."
            )
        job = (
            db.query(Job)
            .filter(Job.process_id == process.MasterObject_id, Job.Name == payload.job_name)
            .first()
        )
    else:
        # Direct Job Lookup — traverse to parent Process automatically
        job = db.query(Job).filter(Job.Name == payload.job_name).first()
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job '{payload.job_name}' not found."
            )
        process = db.query(Process).filter(Process.MasterObject_id == job.process_id).first()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{payload.job_name}' could not be resolved."
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
        interpolated_params: Dict[str, Any] = {}
        for param in step.parameters:
            interpolated_params[param.ParamName] = engine.interpolate(param.ParamValue)

        compiled_steps.append(
            JobStepPayloadSchema(
                step_number=step.StepOrder,
                step_type=step.step_type.TypeName if step.step_type else "GENERIC",
                handler_class=step.step_type.HandlerClass if step.step_type else "BaseHandler",
                title=step.Title,
                parameters=interpolated_params
            )
        )

    working_folder = engine.interpolate("${SYS:WORKING_FOLDER}")

    return JobInitResponse(
        status="SUCCESS",
        execution_instance_id=payload.instance_id,
        job_id=job.MasterObject_id,
        process_id=process.MasterObject_id if process else job.process_id,
        working_folder=working_folder,
        variables=resolved_vars,
        steps=compiled_steps
    )
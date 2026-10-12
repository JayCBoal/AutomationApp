from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional

from app.database import get_db
from app.models import Job, JobStep
from app.schemas import JobInitRequest, JobInitResponse, JobStepPayloadSchema
from engine.scope_engine import ScopeResolutionEngine

router = APIRouter(prefix="/api/v1/jobs", tags=["Job Execution"])


@router.post("/init", response_model=JobInitResponse, status_code=status.HTTP_200_OK)
def initialize_job(payload: JobInitRequest, db: Session = Depends(get_db)):
    """Resolves the job's variable scope and returns its steps with parameters interpolated."""

    # 1. Lookup Job by its JobKey; the parent Process follows from the Job
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
        interpolated_params: Dict[str, Any] = {}
        for param in step.parameters:
            try:
                interpolated_params[param.ParamName] = engine.interpolate(param.ParamValue)
            except ValueError as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Step {step.StepOrder} ('{step.Title}'), parameter '{param.ParamName}': {e}"
                )

        compiled_steps.append(
            JobStepPayloadSchema(
                step_number=step.StepOrder,
                step_type=step.step_type.TypeName if step.step_type else "GENERIC",
                handler_class=step.step_type.HandlerClass if step.step_type else "BaseHandler",
                title=step.Title,
                parameters=interpolated_params
            )
        )

    working_folder = str(engine.scoped_vars["SYS"].get("WORKING_FOLDER", ""))

    return JobInitResponse(
        status="SUCCESS",
        execution_instance_id=payload.instance_id,
        job_id=job.MasterObject_id,
        process_id=job.process_id,
        working_folder=working_folder,
        variables=resolved_vars,
        steps=compiled_steps
    )
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from engine.scope_engine import ScopeResolutionEngine

router = APIRouter(prefix="/api/v1/variables", tags=["Variable Utility"])


@router.get("/resolve", status_code=status.HTTP_200_OK)
def resolve_variables(job_id: int, instance_id: str = "UTILITY_RESOLVE", db: Session = Depends(get_db)):
    """Standalone utility endpoint to inspect variable cascade resolution for a job."""
    engine = ScopeResolutionEngine(db=db, job_id=job_id, instance_id=instance_id)
    resolved_vars = engine.build_context()
    return {"job_id": job_id, "variables": resolved_vars}
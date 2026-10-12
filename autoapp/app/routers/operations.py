from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import FileTrace, OperationOut
from app.trace import MAX_RESULTS, search_operations, trace_operation

router = APIRouter(prefix="/api/v1/operations", tags=["Operations Log"])


@router.get("", response_model=List[OperationOut])
def list_operations(
    filename: Optional[str] = Query(None, description="Part of a filename, on either side of the operation"),
    endpoint: Optional[str] = Query(None, description="Part of an endpoint name, on either side"),
    job_key: Optional[str] = Query(None, description="Part of a JobKey"),
    instance_id: Optional[str] = Query(None, description="The scheduler's instance ID, exact"),
    status: Optional[str] = Query(None, description="SUCCESS or FAILED"),
    date_from: Optional[datetime] = Query(None, description="Operations that ended at or after this time (UTC)"),
    date_to: Optional[datetime] = Query(None, description="Operations that ended at or before this time (UTC)"),
    limit: int = Query(MAX_RESULTS, ge=1, le=MAX_RESULTS),
    db: Session = Depends(get_db),
):
    """The operations log: one row per file handled, newest first."""
    return search_operations(db, filename=filename, endpoint=endpoint, job_key=job_key,
                             instance_id=instance_id, status=status,
                             date_from=date_from, date_to=date_to, limit=limit)


@router.get("/{operation_id}/trace", response_model=FileTrace)
def get_trace(operation_id: int, db: Session = Depends(get_db)):
    """The whole route of the file that one operation handled."""
    trace = trace_operation(db, operation_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"No operation with id {operation_id} exists.")
    return trace

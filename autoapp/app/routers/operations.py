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
    source_endpoint: Optional[str] = Query(None, description="Part of the source endpoint's name"),
    source_path: Optional[str] = Query(None, description="Part of the source path"),
    source_filename: Optional[str] = Query(None, description="Part of the source filename"),
    source_application: Optional[str] = Query(None, description="Part of the source endpoint's application name"),
    source_entity: Optional[str] = Query(None, description="Part of the name of the entity that owns the source site"),
    source_site: Optional[str] = Query(None, description="Part of the source endpoint's site name"),
    dest_endpoint: Optional[str] = Query(None, description="Part of the destination endpoint's name"),
    dest_path: Optional[str] = Query(None, description="Part of the destination path"),
    dest_filename: Optional[str] = Query(None, description="Part of the destination filename"),
    dest_application: Optional[str] = Query(None, description="Part of the destination endpoint's application name"),
    dest_entity: Optional[str] = Query(None, description="Part of the name of the entity that owns the destination site"),
    dest_site: Optional[str] = Query(None, description="Part of the destination endpoint's site name"),
    application: Optional[str] = Query(None, description="Part of an application name, on either side"),
    entity: Optional[str] = Query(None, description="Part of an entity name, on either side"),
    site: Optional[str] = Query(None, description="Part of a site name, on either side"),
    job_key: Optional[str] = Query(None, description="Part of a JobKey"),
    instance_id: Optional[str] = Query(None, description="The scheduler's instance ID, exact"),
    scheduler: Optional[str] = Query(None, description="Part of the name of the scheduler that started the run"),
    op_type: Optional[str] = Query(None, description="Operation type, exact: COPY, MOVE, ..."),
    status: Optional[str] = Query(None, description="SUCCESS or FAILED"),
    date_from: Optional[datetime] = Query(None, description="Operations that ended at or after this time (UTC)"),
    date_to: Optional[datetime] = Query(None, description="Operations that ended at or before this time (UTC)"),
    limit: int = Query(MAX_RESULTS, ge=1, le=MAX_RESULTS),
    db: Session = Depends(get_db),
):
    """
    The operations log: one row per thing a step did, newest first.
    Text criteria ignore case and match anywhere in the field. Times are UTC.
    """
    return search_operations(
        db, filename=filename, endpoint=endpoint,
        source_endpoint=source_endpoint, source_path=source_path, source_filename=source_filename,
        source_application=source_application, source_entity=source_entity, source_site=source_site,
        dest_endpoint=dest_endpoint, dest_path=dest_path, dest_filename=dest_filename,
        dest_application=dest_application, dest_entity=dest_entity, dest_site=dest_site,
        application=application, entity=entity, site=site,
        job_key=job_key, instance_id=instance_id, scheduler=scheduler, op_type=op_type, status=status,
        date_from=date_from, date_to=date_to, limit=limit,
    )


@router.get("/{operation_id}/trace", response_model=FileTrace)
def get_trace(operation_id: int, db: Session = Depends(get_db)):
    """The whole route of the file that one operation handled."""
    trace = trace_operation(db, operation_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"No operation with id {operation_id} exists.")
    return trace

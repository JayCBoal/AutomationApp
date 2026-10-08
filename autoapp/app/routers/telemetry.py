from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Operation, Audit
from app.schemas import OpsTelemetryItem, BatchOpsTelemetryRequest, AuditTelemetryItem

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry Ingestion"])


@router.post("/ops", status_code=status.HTTP_201_CREATED)
def log_operation(item: OpsTelemetryItem, db: Session = Depends(get_db)):
    """Ingests a single operational event directly from an active step handler."""
    record = Operation(
        InstanceID=item.execution_instance_id,
        StepNumber=item.step_number,
        OpType=item.op_type,
        OpStatus=item.op_status,
        BytesTransferred=item.bytes_transferred,
        SourceURI=item.source_uri,
        DestinationURI=item.destination_uri,
        Details=item.details
    )
    db.add(record)
    db.commit()
    return {"status": "LOGGED", "execution_instance_id": item.execution_instance_id}


@router.post("/ops/batch", status_code=status.HTTP_201_CREATED)
def log_operation_batch(payload: BatchOpsTelemetryRequest, db: Session = Depends(get_db)):
    """Bulk-ingests spooled operational events flushed by parse_ops.py after an outage."""
    records = [
        Operation(
            InstanceID=item.execution_instance_id,
            StepNumber=item.step_number,
            OpType=item.op_type,
            OpStatus=item.op_status,
            BytesTransferred=item.bytes_transferred,
            SourceURI=item.source_uri,
            DestinationURI=item.destination_uri,
            Details=item.details
        )
        for item in payload.events
    ]
    db.bulk_save_objects(records)
    db.commit()
    return {"status": "BATCH_LOGGED", "count": len(records)}


@router.post("/audit", status_code=status.HTTP_201_CREATED)
def log_audit(item: AuditTelemetryItem, db: Session = Depends(get_db)):
    """Ingests console logs and execution heartbeats."""
    record = Audit(
        InstanceID=item.execution_instance_id,
        StepNumber=item.step_number,
        LogLevel=item.log_level,
        Message=item.message,
        SourceComponent=item.source_component
    )
    db.add(record)
    db.commit()
    return {"status": "LOGGED"}
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import TelemetryBatch, TelemetryIngestResult
from app.telemetry_ingest import ingest_batch

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry Ingestion"])


@router.post("/records", response_model=TelemetryIngestResult, status_code=status.HTTP_201_CREATED)
def receive_records(batch: TelemetryBatch, db: Session = Depends(get_db)):
    """
    Receives run telemetry from a runner: the lines of its spool file, in any batch size.
    Records already received are skipped, so a batch can safely be sent again.
    """
    try:
        return ingest_batch(db, batch)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

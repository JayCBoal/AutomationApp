"""
Loads telemetry records (see app/schemas.py) into JobRuns and Operations.

Used by the /api/v1/telemetry/records route and by engine.spool_delivery.
Loading is safe to repeat: a run is identified by its RunID and an operation by
its position (Seq) in that run, and anything already stored is skipped.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Endpoint, Job, JobRun, JobStep, Operation
from app.schemas import OperationRecord, RunEndRecord, RunStartRecord, TelemetryBatch, TelemetryIngestResult


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """DateTime columns hold UTC without timezone info."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def ingest_records(db: Session, records: List[Dict[str, Any]]) -> TelemetryIngestResult:
    """Validates and loads raw records, as read from a spool file. Raises ValueError if they are malformed."""
    return ingest_batch(db, TelemetryBatch.model_validate({"records": records}))


def ingest_batch(db: Session, batch: TelemetryBatch) -> TelemetryIngestResult:
    result = TelemetryIngestResult(runs_started=0, runs_ended=0, operations_added=0, duplicates_skipped=0)
    runs: Dict[str, Optional[JobRun]] = {}

    def find_run(run_id: str) -> Optional[JobRun]:
        if run_id not in runs:
            runs[run_id] = db.query(JobRun).filter(JobRun.RunID == run_id).first()
        return runs[run_id]

    def existing_id(model, row_id: Optional[int]) -> Optional[int]:
        """A step or endpoint may have been deleted since the run; the link is then left empty."""
        if row_id is None or db.get(model, row_id) is None:
            return None
        return row_id

    try:
        for record in sorted(batch.records, key=lambda r: (r.RunID, r.Seq)):
            run = find_run(record.RunID)

            if isinstance(record, RunStartRecord):
                if run:
                    result.duplicates_skipped += 1
                    continue
                job = db.query(Job).filter(Job.JobKey == record.JobKey).first()
                run = JobRun(
                    RunID=record.RunID,
                    JobKey=record.JobKey,
                    Job_MasterObject_id=job.MasterObject_id if job else None,
                    SchedulerInstanceID=record.InstanceID,
                    RunNumber=record.RunNumber,
                    SchedulerName=record.Scheduler,
                    Host=record.Host,
                    Status="RUNNING",
                    StartedDateTime=_naive_utc(record.StartedAtUtc),
                )
                db.add(run)
                db.flush()
                runs[record.RunID] = run
                result.runs_started += 1
                continue

            if not run:
                raise ValueError(
                    f"{record.Record} record for run '{record.RunID}' arrived before that run's RUN_START record."
                )

            if isinstance(record, OperationRecord):
                already = db.query(Operation.id).filter(
                    Operation.JobRun_id == run.id, Operation.Seq == record.Seq
                ).first()
                if already:
                    result.duplicates_skipped += 1
                    continue
                db.add(Operation(
                    JobRun_id=run.id,
                    Seq=record.Seq,
                    JobStep_id=existing_id(JobStep, record.StepID),
                    StepOrder=record.StepOrder,
                    OpType=record.OpType,
                    OpStatus=record.Status,
                    SourceEndpoint_id=existing_id(Endpoint, record.SourceEndpointID),
                    SourcePath=record.SourcePath,
                    SourceFilename=record.SourceFilename,
                    SourceSize=record.SourceSize,
                    DestEndpoint_id=existing_id(Endpoint, record.DestEndpointID),
                    DestPath=record.DestPath,
                    DestFilename=record.DestFilename,
                    DestSize=record.DestSize,
                    Checksum=record.Checksum,
                    Details=json.dumps(record.Details) if record.Details else None,
                    ErrorMessage=record.Error,
                    StartedDateTime=_naive_utc(record.StartedAtUtc),
                    EndedDateTime=_naive_utc(record.EndedAtUtc),
                ))
                result.operations_added += 1

            elif isinstance(record, RunEndRecord):
                if run.EndedDateTime is not None:
                    result.duplicates_skipped += 1
                    continue
                run.Status = record.Status
                run.ErrorMessage = record.Error
                run.EndedDateTime = _naive_utc(record.EndedAtUtc)
                result.runs_ended += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    return result

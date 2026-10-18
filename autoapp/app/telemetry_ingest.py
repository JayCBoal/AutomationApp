"""
Loads telemetry records (see app/schemas.py) into JobRuns and Operations. The job log is not among
them: it is a file on the host that ran the job, and RUN_START says where (engine/log_files.py).

Used by the /api/v1/telemetry/records route and by engine.spool_delivery.
Loading is safe to repeat: a run is identified by its RunID and an operation by
its position (Seq) in that run, and anything already stored is skipped.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Endpoint, Job, JobRun, JobStep, Operation, ReactionAction, ReactionEvent
from app.schemas import (LogRecord, OperationRecord, ReactionRecord, RunEndRecord, RunStartRecord, TelemetryBatch,
                         TelemetryIngestResult)


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
                parent = find_run(record.ParentRunID) if record.ParentRunID else None
                run = JobRun(
                    RunID=record.RunID,
                    JobKey=record.JobKey,
                    Job_MasterObject_id=job.MasterObject_id if job else None,
                    SchedulerInstanceID=record.InstanceID,
                    RunNumber=record.RunNumber,
                    SchedulerName=record.Scheduler,
                    BusinessDate=record.BusinessDate,
                    Host=record.Host,
                    LogFile=record.LogFile,
                    Status="RUNNING",
                    StartedDateTime=_naive_utc(record.StartedAtUtc),
                    ParentRun_id=parent.id if parent else None,
                    WorkflowPath=record.WorkflowPath,
                    Attempt=record.Attempt,
                    ProcessID=record.ProcessID,
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
                    StepNumber=record.StepNumber,
                    Iteration=record.Iteration,
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

            elif isinstance(record, LogRecord):
                continue        # from a runner older than log files: its lines are not kept

            elif isinstance(record, RunEndRecord):
                if run.EndedDateTime is not None:
                    result.duplicates_skipped += 1
                    continue
                run.Status = record.Status
                run.ErrorMessage = record.Error
                run.ReturnCode = record.ReturnCode
                run.Reason = record.Reason
                run.StatusBeforeOverride = record.StatusBeforeOverride
                run.EndedDateTime = _naive_utc(record.EndedAtUtc)
                result.runs_ended += 1

            elif isinstance(record, ReactionRecord):
                if db.query(ReactionEvent.id).filter(ReactionEvent.JobRun_id == run.id, ReactionEvent.Action == record.Action,
                                                     ReactionEvent.EventDateTime == _naive_utc(record.AtUtc)).first():
                    result.duplicates_skipped += 1
                    continue
                action_id = existing_id(ReactionAction, record.ReactionActionID)
                db.add(ReactionEvent(JobRun_id=run.id, ReactionAction_id=action_id, Action=record.Action,
                                     Result=record.Result, Message=record.Message, EventDateTime=_naive_utc(record.AtUtc)))

        db.commit()
    except Exception:
        db.rollback()
        raise
    return result

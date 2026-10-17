"""
Run telemetry: written to a local spool file first, then delivered through the API.

Every run gets its own spool file, one JSON record per line:

    RUN_START   which job, and the identifiers the scheduler passed
    OPERATION   one thing a step did: for a file step, one file
    LOG         lines of the job log, as the runner printed them (secrets masked)
    RUN_END     how the run finished

The file is "<name>.jsonl.tmp" while the run is in progress and is renamed to
"<name>.jsonl" when it ends. If an API address is configured the records are
also posted as the run goes; a spool file whose records have all arrived is
moved to the "delivered" subfolder. Anything left behind is picked up later by
engine.spool_delivery, so an unreachable API never fails or loses a run.
"""
import json
import os
import re
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.spool_delivery import DeliveryError, mark_delivered, post_records


def utc_now_iso() -> str:
    """Current UTC time to the millisecond, e.g. 2026-10-12T14:03:07.512Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class LocalSpoolTelemetryClient:
    def __init__(self, spool_dir: str = "./spool", instance_id: Optional[str] = None,
                 api_url: Optional[str] = None, run_id: Optional[str] = None):
        self.spool_dir = Path(spool_dir)
        self.instance_id = str(instance_id or 0)
        self.api_url = api_url
        self.run_id = run_id or str(uuid.uuid4())
        self.spool_dir.mkdir(parents=True, exist_ok=True)

        safe_instance = re.sub(r"[^A-Za-z0-9_.-]", "_", self.instance_id)
        base_name = f"run_{safe_instance}_{self.run_id}"
        self.active_file_path = self.spool_dir / f"{base_name}.jsonl.tmp"
        self.completed_file_path = self.spool_dir / f"{base_name}.jsonl"

        # Line-buffered, so each record is on disk as soon as it is written
        self._file_handle = open(self.active_file_path, "a", encoding="utf-8", buffering=1)
        self._seq = 0
        self._undelivered: List[Dict[str, Any]] = []
        self._delivery_abandoned = False

    def _write(self, record_type: str, fields: Dict[str, Any]) -> None:
        self._seq += 1
        record = {"Record": record_type, "RunID": self.run_id, "Seq": self._seq, **fields}
        self._file_handle.write(json.dumps(record) + "\n")
        self._undelivered.append(record)

    def start_run(self, job_key: str, run_number: int = 1, scheduler: Optional[str] = None,
                  business_date=None, parent_run_id: Optional[str] = None, workflow_path: Optional[str] = None,
                  attempt: int = 1) -> None:
        # A job run inside a workflow run says which, where in the workflow it is, and which attempt
        workflow = {"ParentRunID": parent_run_id, "WorkflowPath": workflow_path, "Attempt": attempt} if parent_run_id else {}
        self._write("RUN_START", {**workflow,
            "JobKey": job_key,
            "InstanceID": self.instance_id,
            "RunNumber": run_number,
            "Scheduler": scheduler,
            "BusinessDate": business_date.isoformat() if business_date else None,
            "Host": socket.gethostname(),
            "StartedAtUtc": utc_now_iso(),
        })

    def log_operation(
        self,
        op_type: str,
        status: str,
        step_id: Optional[int] = None,
        step_order: Optional[int] = None,
        step_number: Optional[str] = None,
        iteration: Optional[str] = None,
        source_path: Optional[str] = None,
        source_filename: Optional[str] = None,
        source_size: Optional[int] = None,
        source_endpoint_id: Optional[int] = None,
        dest_path: Optional[str] = None,
        dest_filename: Optional[str] = None,
        dest_size: Optional[int] = None,
        dest_endpoint_id: Optional[int] = None,
        checksum: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
    ) -> None:
        """
        Records one thing a step did. For a file, give the source and destination;
        for anything else, describe it in details.
        """
        self._write("OPERATION", {
            "StepID": step_id,
            "StepOrder": step_order,
            "StepNumber": step_number,
            "Iteration": iteration,
            "OpType": op_type,
            "Status": status,
            "SourcePath": source_path,
            "SourceFilename": source_filename,
            "SourceSize": source_size,
            "SourceEndpointID": source_endpoint_id,
            "DestPath": dest_path,
            "DestFilename": dest_filename,
            "DestSize": dest_size,
            "DestEndpointID": dest_endpoint_id,
            "Checksum": checksum,
            "Details": details,
            "Error": error,
            "StartedAtUtc": started_at,
            "EndedAtUtc": ended_at or utc_now_iso(),
        })

    def log_lines(self, lines: List[str]) -> None:
        """Records lines of the job log. Nothing is written for none."""
        if lines:
            self._write("LOG", {"Lines": list(lines)})

    def end_run(self, status: str, error: Optional[str] = None, return_code: Optional[int] = None,
                reason: Optional[str] = None) -> None:
        self._write("RUN_END", {"Status": status, "Error": error, "ReturnCode": return_code, "Reason": reason,
                                "EndedAtUtc": utc_now_iso()})

    def deliver(self) -> bool:
        """
        Posts the records not yet delivered. Returns True if nothing is left to send.
        Never raises: after one failure the run stops trying, and the spool file
        is left for engine.spool_delivery to send later.
        """
        if not self.api_url or self._delivery_abandoned:
            return False
        if self._undelivered:
            try:
                post_records(self.api_url, self._undelivered, timeout=5)
            except DeliveryError:
                self._delivery_abandoned = True
                return False
            self._undelivered = []
        return True

    def close(self) -> None:
        """Ends the spool file: a last delivery attempt, then .tmp becomes .jsonl."""
        if self._file_handle.closed:
            return
        delivered = self.deliver()
        self._file_handle.close()
        os.replace(self.active_file_path, self.completed_file_path)
        if delivered:
            mark_delivered(self.completed_file_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

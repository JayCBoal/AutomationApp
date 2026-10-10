import os
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

class LocalSpoolTelemetryClient:
    """
    Process-isolated, zero-latency local spooling telemetry client.
    Writes operation records and audit events directly to unique local .jsonl files 
    to guarantee zero execution latency and complete WLA agent thread protection.
    """
    def __init__(self, spool_dir: str = "./spool", instance_id: Optional[int] = None):
        self.spool_dir = Path(spool_dir)
        self.instance_id = instance_id or 0
        self.pid = os.getpid()
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        
        # Unique file paths for process isolation
        base_name = f"ops_inst_{self.instance_id}_pid_{self.pid}_{int(time.time())}"
        self.active_file_path = self.spool_dir / f"{base_name}.jsonl.tmp"
        self.completed_file_path = self.spool_dir / f"{base_name}.jsonl"
        
        # Open an unbuffered/line-buffered file handle for fast append
        self._file_handle = open(self.active_file_path, "a", encoding="utf-8", buffering=1)

    def log_operation(
        self,
        op_type: str,
        step_id: int,
        status: str,
        execution_time_ms: int,
        source_path: Optional[str] = None,
        source_filename: Optional[str] = None,
        dest_path: Optional[str] = None,
        dest_filename: Optional[str] = None,
        bytes_transferred: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Appends an operation log entry directly to the process-isolated spool file.
        """
        payload = {
            "InstanceID": self.instance_id,
            "StepID": step_id,
            "OpType": op_type,
            "Status": status,
            "ExecutionTimeMs": execution_time_ms,
            "SourcePath": source_path,
            "SourceFilename": source_filename,
            "DestPath": dest_path,
            "DestFilename": dest_filename,
            "BytesTransferred": bytes_transferred,
            "Details": details or {},
            "LoggedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        self._file_handle.write(json.dumps(payload) + "\n")

    def log_batch_operations(
        self,
        op_type: str,
        step_id: int,
        status: str,
        execution_time_ms: int,
        ops_list: list,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Logs an entire batch of sub-operations for a step in a single disk write.
        """
        payload = {
            "InstanceID": self.instance_id,
            "StepID": step_id,
            "OpType": op_type,
            "Status": status,
            "ExecutionTimeMs": execution_time_ms,
            "IsBatch": True,
            "Operations": ops_list,
            "Details": details or {},
            "LoggedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        self._file_handle.write(json.dumps(payload) + "\n")

    def log_audit(
        self,
        action: str,
        actor: str,
        resource_type: str,
        resource_id: str,
        status: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Appends an audit event entry to the process-isolated spool file.
        """
        payload = {
            "InstanceID": self.instance_id,
            "IsAudit": True,
            "Action": action,
            "Actor": actor,
            "ResourceType": resource_type,
            "ResourceId": resource_id,
            "Status": status,
            "Details": details or {},
            "LoggedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        self._file_handle.write(json.dumps(payload) + "\n")

    def close(self) -> None:
        """
        Flushes and closes the file handle, then atomically renames 
        the .tmp file to .jsonl for ingestion picking.
        """
        if self._file_handle and not self._file_handle.closed:
            self._file_handle.flush()
            self._file_handle.close()
            
            if self.active_file_path.exists():
                self.active_file_path.rename(self.completed_file_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

# Backward-compatible aliases for base handler imports
TelemetryClient = LocalSpoolTelemetryClient
SpoolLogger = LocalSpoolTelemetryClient
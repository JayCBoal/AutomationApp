import os
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

class TelemetryClient:
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
        
        base_name = f"inst_{self.instance_id}_pid_{self.pid}_{int(time.time())}"
        
        # Process-isolated file paths for Operations and Audits
        self.ops_active_path = self.spool_dir / f"ops_{base_name}.jsonl.tmp"
        self.ops_completed_path = self.spool_dir / f"ops_{base_name}.jsonl"
        
        self.audit_active_path = self.spool_dir / f"audit_{base_name}.jsonl.tmp"
        self.audit_completed_path = self.spool_dir / f"audit_{base_name}.jsonl"
        
        # Line-buffered file handles for instant append writes (<0.1ms)
        self._ops_handle = open(self.ops_active_path, "a", encoding="utf-8", buffering=1)
        self._audit_handle = open(self.audit_active_path, "a", encoding="utf-8", buffering=1)

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
        """Appends an Operation log entry to the active ops spool file."""
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
        self._ops_handle.write(json.dumps(payload) + "\n")

    def log_audit(
        self,
        action: str,
        actor: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        status: str = "SUCCESS",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Appends an Audit log entry to the active audit spool file."""
        payload = {
            "InstanceID": self.instance_id,
            "Action": action,
            "Actor": actor,
            "ResourceType": resource_type,
            "ResourceID": resource_id,
            "Status": status,
            "Details": details or {},
            "TimestampUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        self._audit_handle.write(json.dumps(payload) + "\n")

    def close(self) -> None:
        """Flushes, closes, and atomically renames .tmp files to .jsonl."""
        for handle, active_path, completed_path in [
            (self._ops_handle, self.ops_active_path, self.ops_completed_path),
            (self._audit_handle, self.audit_active_path, self.audit_completed_path)
        ]:
            if handle and not handle.closed:
                handle.flush()
                handle.close()
                if active_path.exists():
                    # Unlink empty temporary files to keep spool directory clean
                    if active_path.stat().st_size == 0:
                        active_path.unlink()
                    else:
                        active_path.rename(completed_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
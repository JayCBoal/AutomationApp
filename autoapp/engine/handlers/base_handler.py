import os
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from engine import job_log
from engine.telemetry_client import LocalSpoolTelemetryClient

class BaseHandler(ABC):
    """
    Abstract base class for all execution handlers.
    Provides standardized step execution wrapping, execution timing,
    job logging, and a helper for recording each file a step handles.

    Logging, for every step type (see engine/job_log.py for the levels):
      - run() logs the step's parameters, as written and as resolved, and a
        closing line with the outcome. A handler gets these without writing any code.
      - A handler calls job_log.detail() for each thing it does (each file
        copied, each statement run), and returns a one-line account of the
        whole step in result["details"]["summary"].
    """
    # Parameters that hold file locations, mapped to their role ("source" or "dest").
    # Each may be given as a raw path inside the working folder (e.g. Source) or as
    # the name of a registered Endpoint (e.g. SourceEndpoint). See engine/step_params.py.
    PATH_PARAMS: Dict[str, str] = {}

    # Whether the handler can reach Endpoints that live on a remote Site
    SUPPORTS_REMOTE_SITES = False

    def __init__(self, step_config: Dict[str, Any], telemetry_client: LocalSpoolTelemetryClient):
        self.step_config = step_config
        self.step_id = step_config.get("StepID")
        self.telemetry = telemetry_client

    @abstractmethod
    def execute_step(self, resolved_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler-specific execution logic. Must be overridden by subclasses.
        Returns a dictionary describing what the step did.
        """
        pass

    def describe(self, resolved_params: Dict[str, Any]) -> List[str]:
        """
        One line per parameter: the value as written in the job, and what it resolved to
        if that is different. A handler may override this to describe itself better.
        """
        lines = []
        for name, written in self.step_config.get("RawParams", {}).items():
            path_param = name[:-len("Endpoint")] if name.endswith("Endpoint") else None
            if path_param in self.PATH_PARAMS:
                lines.append(f"{name}: {written}  (resolved: {resolved_params.get(path_param)})")
                continue
            resolved = resolved_params.get(name)
            if resolved is not None and str(resolved) != str(written):
                lines.append(f"{name}: {written}  (resolved: {resolved})")
            else:
                lines.append(f"{name}: {written}")
        return lines

    def run(self, resolved_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wrapper method executed by runner.py. Logs the step, calls execute_step() and times it.
        A failure is raised to the runner, which records it against the run.
        """
        label = (f"Step {self.step_config.get('StepOrder')}: {self.step_config.get('Title')} "
                 f"({self.step_config.get('StepType')})")
        job_log.detail(f"BEGIN {label}")
        for line in self.describe(resolved_params):
            job_log.detail(f"    {line}")

        start_time = time.perf_counter()
        try:
            result_data = self.execute_step(resolved_params) or {}
        except Exception:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            job_log.error(f"END {label}: FAILED ({elapsed_ms} ms)")
            raise
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        outcome = " ".join(result_data.get("details", {}).get("summary", []))
        job_log.summary(f"END {label}: SUCCESS. {outcome} ({elapsed_ms} ms)".replace(".  (", ". ("))
        return {"status": "SUCCESS", "execution_time_ms": elapsed_ms, "result": result_data}

    def record_file_operation(
        self,
        op_type: str,
        status: str,
        source: str,
        dest: str,
        source_size: Optional[int] = None,
        dest_size: Optional[int] = None,
        checksum: Optional[str] = None,
        error: Optional[str] = None,
        started_at: Optional[str] = None,
    ) -> None:
        """Records one file this step handled, given its full source and destination paths."""
        self.telemetry.log_operation(
            op_type=op_type,
            status=status,
            step_id=self.step_id,
            step_order=self.step_config.get("StepOrder"),
            source_path=os.path.dirname(source),
            source_filename=os.path.basename(source),
            source_size=source_size,
            source_endpoint_id=self.step_config.get("SourceEndpointID"),
            dest_path=os.path.dirname(dest),
            dest_filename=os.path.basename(dest),
            dest_size=dest_size,
            dest_endpoint_id=self.step_config.get("DestEndpointID"),
            checksum=checksum,
            error=error,
            started_at=started_at,
        )

    def record_operation(
        self,
        op_type: str,
        status: str,
        details: Dict[str, Any],
        error: Optional[str] = None,
        started_at: Optional[str] = None,
    ) -> None:
        """
        Records something this step did that is not a file: a SQL statement run, a REST
        call made, an email sent. details says what, e.g. {"Statement": ..., "RowsAffected": 12}.
        """
        self.telemetry.log_operation(
            op_type=op_type,
            status=status,
            step_id=self.step_id,
            step_order=self.step_config.get("StepOrder"),
            details=details,
            error=error,
            started_at=started_at,
        )

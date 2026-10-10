import os
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from engine.telemetry_client import TelemetryClient

class BaseHandler(ABC):
    """
    Abstract base class for all execution handlers.
    Provides standardized step execution wrapping, execution timing, 
    and local spool telemetry logging.
    """
    def __init__(self, step_config: Dict[str, Any], telemetry_client: TelemetryClient):
        self.step_config = step_config
        self.step_id = step_config.get("StepID")
        self.telemetry = telemetry_client

    @abstractmethod
    def execute_step(self, resolved_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler-specific execution logic. Must be overridden by subclasses.
        Returns a dictionary with operation metrics (source_path, dest_path, details, etc.).
        """
        pass

    def run(self, resolved_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wrapper method executed by runner.py.
        Measures execution timing, calls execute_step(), and emits telemetry.
        """
        start_time = time.perf_counter()
        status = "SUCCESS"
        error_message = None
        result_data = {}

        try:
            result_data = self.execute_step(resolved_params) or {}
        except Exception as e:
            status = "FAILED"
            error_message = str(e)
            
            # Emit security/audit event on failure
            self.telemetry.log_audit(
                action="STEP_EXECUTION_FAILURE",
                actor=f"Runner_PID_{os.getpid()}",
                resource_type="JobStep",
                resource_id=str(self.step_id),
                status="FAILED",
                details={
                    "error": error_message, 
                    "step_type": self.step_config.get("StepType")
                }
            )
            raise e
        finally:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            
            details = result_data.get("details", {})
            if error_message:
                details["error_message"] = error_message

            # Log operational telemetry
            self.telemetry.log_operation(
                op_type=self.step_config.get("StepType"),
                step_id=self.step_id,
                status=status,
                execution_time_ms=elapsed_ms,
                source_path=result_data.get("source_path"),
                source_filename=result_data.get("source_filename"),
                dest_path=result_data.get("dest_path"),
                dest_filename=result_data.get("dest_filename"),
                bytes_transferred=result_data.get("bytes_transferred"),
                details=details
            )

        return {"status": status, "execution_time_ms": elapsed_ms, "result": result_data}
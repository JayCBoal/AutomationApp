"""
The Simulate step: stands in for real work while a workflow is built and tried, so its
shape can be tested before the real jobs exist (docs/WORKFLOWS.md). It writes what it is
told to the job log, takes as long as it is told, ends with the return code it is told,
and can fail on purpose.
"""
import time

from engine import job_log
from engine.handlers.base_handler import BaseHandler
from engine.step_catalog import BOOLEAN, CHOICE, INTEGER, NOT_DONE, STRING, TEXT, Param
from engine.telemetry_client import utc_now_iso

MESSAGE_LEVELS = ("SUMMARY", "DETAIL", "WARNING", "ERROR")
_WRITERS = {"SUMMARY": job_log.summary, "DETAIL": job_log.detail, "WARNING": job_log.warning, "ERROR": job_log.error}


class SimulateHandler(BaseHandler):
    CODE = "SIMULATE"
    FAILURE_KNOWLEDGE = NOT_DONE
    NAME = "Simulate"
    DESCRIPTION = ("Stands in for real work while a workflow is built and tried: writes what it is told to the "
                   "job log, waits, and ends with a chosen return code")

    PARAMETERS = (
        Param("Messages", TEXT, description="Lines to write to the job log, one per line"),
        Param("MessageLevel", CHOICE, default="SUMMARY", choices=MESSAGE_LEVELS,
              description="How the lines are written: SUMMARY and DETAIL as information, or as warnings or errors"),
        Param("WaitSeconds", INTEGER, default="0", description="How long the step takes, in seconds"),
        Param("ReturnCode", INTEGER, default="0", description=(
            "The return code the job ends with, unless a later step sets another. Whether it means success "
            "is up to the job's Success return codes")),
        Param("Fail", BOOLEAN, default="False", description="Make the step fail, as real work might"),
        Param("FailMessage", STRING, default="Simulated failure", description="What the failure says"),
    )

    def execute_step(self, params: dict) -> dict:
        code, wait = params["ReturnCode"], params["WaitSeconds"]
        if code < 0 or wait < 0:
            raise ValueError("ReturnCode and WaitSeconds cannot be below 0.")
        started_at = utc_now_iso()
        lines = [line for line in (params.get("Messages") or "").splitlines() if line.strip()]
        for line in lines:
            _WRITERS[params["MessageLevel"]](line)
        if wait:
            job_log.detail(f"Waiting {wait} second{'' if wait == 1 else 's'}")
            time.sleep(wait)

        # A step's own ReturnCode output, and the job's return code from here on. Failing with no code
        # of its own, it leaves the job's at 1, as any failed step does.
        failed = bool(params["Fail"])
        self.outputs["ReturnCode"] = code if code or not failed else 1
        self.job_return_code = code if code or not failed else None
        self.record_operation("SIMULATE", "FAILED" if failed else "SUCCESS",
                              {"ReturnCode": code, "WaitSeconds": wait, "Lines": len(lines)},
                              error=params["FailMessage"] if failed else None, started_at=started_at)
        if failed:
            raise RuntimeError(params["FailMessage"])
        return {"details": {"summary": [f"Return code {code}" + (f", after {wait} s." if wait else ".")]}}

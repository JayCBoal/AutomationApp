"""
The Set Return Code step: sets the job's return code, and the job carries on
(docs/WORKFLOWS_PHASE3.md). Several can run in one job; the last one run wins. Inside an If,
a job chooses its own code ("no files arrived: 4"). When the job ends, its Success return
codes decide whether the code means Succeeded or Failed.
"""
from core import job_log
from core.handlers.base_handler import BaseHandler
from core.step_catalog import INTEGER, NOT_DONE, STRING, Param
from core.telemetry_client import utc_now_iso


class SetReturnCodeHandler(BaseHandler):
    CODE = "SET_RETURN_CODE"
    FAILURE_KNOWLEDGE = NOT_DONE
    NAME = "Set Return Code"
    DESCRIPTION = "Sets the job's return code and carries on; if several run, the last one wins"

    PARAMETERS = (
        Param("ReturnCode", INTEGER, required=True, description=(
            "The job's return code from here on, unless a later step sets another. Whether it means success "
            "is up to the job's Success return codes")),
        Param("Message", STRING, description="Why, written to the job log beside the code"),
    )

    def execute_step(self, params: dict) -> dict:
        code = params["ReturnCode"]
        if code < 0:
            raise ValueError("ReturnCode cannot be below 0.")
        started_at = utc_now_iso()
        message = (params.get("Message") or "").strip()
        summary = f"Return code set to {code}" + (f": {message}" if message else ".")
        job_log.summary(summary)

        self.outputs["ReturnCode"] = code
        self.job_return_code = code
        self.record_operation("SET_RETURN_CODE", "SUCCESS", {"ReturnCode": code}, started_at=started_at)
        return {"details": {"summary": [summary]}}

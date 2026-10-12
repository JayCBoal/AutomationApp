#!/usr/bin/env python3
"""
AutoApp execution runner.

Runs every active step of one Job, in StepOrder, and returns an OS exit code
(0 = all steps succeeded, 1 = the job failed) for the calling WLA scheduler.
"""
import argparse
import logging
import os
import sys
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Job, JobStep
from engine.handlers import get_handler
from engine.scope_engine import ScopeResolutionEngine
from engine.telemetry_client import LocalSpoolTelemetryClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AutoApp.Runner")


def resolve_step_params(step: JobStep, scope_engine: ScopeResolutionEngine) -> Dict[str, Any]:
    """Interpolates a step's parameters; an unresolved placeholder fails the step."""
    try:
        return {p.ParamName: scope_engine.interpolate(p.ParamValue) for p in step.parameters}
    except ValueError as e:
        raise ValueError(f"Step {step.StepOrder} ('{step.Title}'): {e}") from e


def run_job(db: Session, job_key: str, instance_id: str, spool_dir: str) -> int:
    """Executes the job and returns the exit code to hand back to the scheduler."""
    actor = f"Runner_PID_{os.getpid()}"

    with LocalSpoolTelemetryClient(spool_dir=spool_dir, instance_id=instance_id) as telemetry:

        def audit(action: str, status: str, details: Dict[str, Any] = None) -> None:
            telemetry.log_audit(
                action=action, actor=actor, resource_type="Job",
                resource_id=job_key, status=status, details=details
            )

        try:
            job = db.query(Job).filter(Job.JobKey == job_key).first()
            if not job:
                raise ValueError(f"No job with JobKey '{job_key}' exists.")
            job_id = job.MasterObject_id

            scope_engine = ScopeResolutionEngine(db=db, job_id=job_id, instance_id=instance_id)
            scope_engine.build_context()

            steps = (
                db.query(JobStep)
                .filter(JobStep.job_id == job_id, JobStep.IsActive.is_(True))
                .order_by(JobStep.StepOrder)
                .all()
            )
            if not steps:
                raise ValueError(f"Job '{job_key}' has no active steps.")

            audit("JOB_STARTED", "STARTED", {"step_count": len(steps)})

            for step in steps:
                step_type = step.step_type.HandlerClass
                logger.info(f"Step {step.StepOrder}: {step.Title} (type {step_type})")

                handler_cls = get_handler(step_type)
                resolved_params = resolve_step_params(step, scope_engine)
                handler = handler_cls(
                    step_config={"StepID": step.id, "StepType": step_type, "Title": step.Title},
                    telemetry_client=telemetry
                )
                handler.run(resolved_params)

        except Exception as e:
            logger.error(f"Job '{job_key}' failed: {e}")
            audit("JOB_FAILED", "FAILED", {"error": str(e)})
            return 1

        audit("JOB_COMPLETED", "SUCCESS")
        logger.info(f"Job '{job_key}' completed successfully.")
        return 0


def main():
    parser = argparse.ArgumentParser(description="AutoApp Lightweight Execution Runner")
    parser.add_argument("--job-key", required=True, help="JobKey of the target Job (e.g. DEV-PROC--JOBA)")
    parser.add_argument("--instance-id", required=True, help="Unique execution Instance ID passed from WLA")
    parser.add_argument("--spool-dir", default="./spool", help="Directory for telemetry spool files")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        exit_code = run_job(db, args.job_key, args.instance_id, args.spool_dir)
    finally:
        db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

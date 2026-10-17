#!/usr/bin/env python3
"""
AutoApp execution runner.

Runs the active steps of one Job, in order (with its If, For Each File and While steps
deciding which of the steps inside them run, and how often: engine/executor.py), and
returns an OS exit code (0 = the job succeeded, 1 = it failed) for the calling WLA scheduler.
"""
import argparse
import os
import sys
import uuid
from datetime import date, datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Job, Variable
from engine import job_log
from engine.executor import Executor
from engine.preflight import describe_problems, prepare_job
from engine.scope_engine import ScopeResolutionEngine
from engine.telemetry_client import LocalSpoolTelemetryClient

def run_job(db: Session, job_key: str, instance_id: str, spool_dir: str,
            working_root: Optional[str] = None, run_number: int = 1,
            scheduler: Optional[str] = None, api_url: Optional[str] = None, run_id: Optional[str] = None,
            business_date: Optional[date] = None, environment: Optional[Dict[str, str]] = None) -> int:
    """
    Executes the job and returns the exit code to hand back to the scheduler.
    environment is what ${ENV:...} and the ENV level read: this process's own, unless given.
    """
    environment = dict(os.environ) if environment is None else environment
    with LocalSpoolTelemetryClient(spool_dir=spool_dir, instance_id=instance_id, api_url=api_url,
                                   run_id=run_id) as telemetry:
        def send_log():
            # The job log goes with the run's records, so it can be read with the run
            telemetry.log_lines(job_log.take_lines())

        telemetry.start_run(job_key, run_number=run_number, scheduler=scheduler, business_date=business_date)
        job_log.summary(f"Job '{job_key}', instance {instance_id}, run number {run_number}"
                        + (f", business date {business_date.isoformat()}" if business_date else ""))
        job_log.debug(f"Run ID {telemetry.run_id}; spool file {telemetry.active_file_path}")
        send_log()
        telemetry.deliver()         # so the run shows as running straight away

        try:
            job = db.query(Job).filter(Job.JobKey == job_key).first()
            if not job:
                raise ValueError(f"No job with JobKey '{job_key}' exists.")
            if not job.IsActive:
                raise ValueError(f"Job '{job_key}' is disabled.")
            job_id = job.MasterObject_id

            global_config = {"WORKING_ROOT": working_root} if working_root else {}
            scope_engine = ScopeResolutionEngine(
                db=db, job_id=job_id, instance_id=instance_id, global_config=global_config,
                environment=environment, business_date=business_date,
            )
            scope_engine.build_context()
            if scope_engine.working_folder:
                os.makedirs(scope_engine.working_folder, exist_ok=True)
            job_log.debug(f"Working folder: {scope_engine.working_folder}")

            # Every step is checked and resolved before the first one runs
            prepared_steps, problems = prepare_job(db, job, scope_engine)
            if problems:
                raise ValueError(describe_problems(problems))

            def after_step():
                # Send what a step recorded; a failure here never affects the job
                send_log()
                telemetry.deliver()

            Executor(db, scope_engine, telemetry, after_step).run_all(prepared_steps)

        except Exception as e:
            job_log.error(f"Job '{job_key}' failed: {e}")
            send_log()
            telemetry.end_run("FAILED", error=str(e))
            return 1

        job_log.summary(f"Job '{job_key}' completed successfully.")
        send_log()
        telemetry.end_run("SUCCESS")
        return 0


def business_date_argument(text: str) -> date:
    for form in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text.strip(), form).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"'{text}' is not a date: use YYYY-MM-DD or YYYYMMDD, e.g. 2026-10-15")


def main():
    parser = argparse.ArgumentParser(description="AutoApp Lightweight Execution Runner")
    parser.add_argument("--job-key", required=True, help="JobKey of the target Job (e.g. DEV-LEGAL-CLIENT_EXTRACT)")
    parser.add_argument("--instance-id", required=True, help="The scheduler's unique ID for this job instance")
    parser.add_argument("--run-number", type=int, default=1,
                        help="Run or restart count, for schedulers that reuse the instance ID (default: 1)")
    parser.add_argument("--scheduler", default=os.getenv("AUTOAPP_SCHEDULER"),
                        help="Name of the scheduler issuing the instance ID, where there is more than one "
                             "(default: the AUTOAPP_SCHEDULER environment variable)")
    parser.add_argument("--spool-dir", default="./spool", help="Directory for telemetry spool files")
    parser.add_argument("--api-url", default=os.getenv("AUTOAPP_API_URL"),
                        help="Address of the AutoApp API to deliver telemetry to "
                             "(default: the AUTOAPP_API_URL environment variable; if unset, telemetry stays in the spool)")
    parser.add_argument("--working-root", default=None,
                        help="Root of job working folders (default: the AUTOAPP_WORKING_ROOT environment variable)")
    parser.add_argument("--business-date", type=business_date_argument, default=None,
                        help="The date the run is for, where the scheduler has one (Control-M's order date): "
                             "YYYY-MM-DD or YYYYMMDD. Steps use it as ${BUSINESS_DATE:yyyyMMdd}; without it, "
                             "that is the date the run started.")
    parser.add_argument("--mask-env", default=os.getenv("AUTOAPP_MASK_ENV", ""),
                        help="Names of environment variables, separated by commas, whose values must never appear "
                             "in the job log: the scheduler's secret job parameters (default: the AUTOAPP_MASK_ENV "
                             "environment variable)")
    parser.add_argument("--run-id", type=uuid.UUID, default=None,
                        help="The ID to record the run under (default: a new one). AutoApp's own Run Job page "
                             "passes one, so it can follow the run; a scheduler leaves it out.")
    parser.add_argument("--log-level", default=os.getenv("AUTOAPP_LOG_LEVEL", job_log.DEFAULT_LEVEL),
                        type=str.upper, choices=list(job_log.LEVELS),
                        help="How much the job log says: DETAIL (default) logs every action, SUMMARY one line "
                             "per step, SILENT errors only, DEBUG adds troubleshooting detail. "
                             "A step can set its own with a LogLevel parameter.")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        # Values of secret variables must never reach the log: AutoApp's own, and the scheduler's it names
        secrets = [value for (value,) in db.query(Variable.VarValue).filter(Variable.IsSecret.is_(True))]
        secrets += [os.environ[name.strip()] for name in args.mask_env.split(",") if name.strip() in os.environ]
        job_log.configure(args.log_level, secrets=secrets)
        exit_code = run_job(db, args.job_key, args.instance_id, args.spool_dir, args.working_root,
                            run_number=args.run_number, scheduler=args.scheduler, api_url=args.api_url,
                            run_id=str(args.run_id) if args.run_id else None, business_date=args.business_date)
    finally:
        db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

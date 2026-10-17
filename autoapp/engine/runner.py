#!/usr/bin/env python3
"""
AutoApp execution runner.

Runs the active steps of one Job, in order (with its If, For Each File and While steps
deciding which of the steps inside them run, and how often: engine/executor.py), and
returns an OS exit code (0 = the job succeeded, 1 = it failed) for the calling WLA scheduler.

The job's return code is 0 unless a step sets another (the Simulate step does); the job
succeeded if its steps did and that code is one of its Success return codes ("0" unless set).
The code is recorded with the run; the exit code stays 0 or 1 (docs/INTEGRATION.md).

A job that is a workflow is handed to engine/workflow_runner.py, so it is started the same way.
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
from engine import job_log, return_codes
from engine.executor import Executor
from engine.preflight import describe_problems, prepare_job
from engine.scope_engine import ScopeResolutionEngine
from engine.telemetry_client import LocalSpoolTelemetryClient

def run_job(db: Session, job_key: str, instance_id: str, spool_dir: str,
            working_root: Optional[str] = None, run_number: int = 1,
            scheduler: Optional[str] = None, api_url: Optional[str] = None, run_id: Optional[str] = None,
            business_date: Optional[date] = None, environment: Optional[Dict[str, str]] = None,
            parent_run_id: Optional[str] = None, workflow_path: Optional[str] = None, attempt: int = 1) -> int:
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

        telemetry.start_run(job_key, run_number=run_number, scheduler=scheduler, business_date=business_date,
                            parent_run_id=parent_run_id, workflow_path=workflow_path, attempt=attempt)
        job_log.summary(f"Job '{job_key}', instance {instance_id}, run number {run_number}"
                        + (f", business date {business_date.isoformat()}" if business_date else ""))
        job_log.debug(f"Run ID {telemetry.run_id}; spool file {telemetry.active_file_path}")
        send_log()
        telemetry.deliver()         # so the run shows as running straight away

        executor, success_codes = None, None
        try:
            job = db.query(Job).filter(Job.JobKey == job_key).first()
            if not job:
                raise ValueError(f"No job with JobKey '{job_key}' exists.")
            if not job.IsActive:
                raise ValueError(f"Job '{job_key}' is disabled.")
            job_id, success_codes = job.MasterObject_id, job.SuccessReturnCodes

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

            executor = Executor(db, scope_engine, telemetry, after_step)
            executor.run_all(prepared_steps)

        except Exception as e:
            job_log.error(f"Job '{job_key}' failed: {e}")
            send_log()
            code = executor.job_return_code if executor and executor.job_return_code is not None else 1
            telemetry.end_run("FAILED", error=str(e), return_code=code, reason="ERROR")
            return 1
        return _finish(job_key, executor.job_return_code, success_codes, telemetry, send_log)


def _finish(job_key: str, code: Optional[int], success_codes: Optional[str], telemetry, send_log) -> int:
    """Ends a job whose steps all went as they should: it succeeded if its return code is a success code."""
    code = 0 if code is None else code
    if not return_codes.matches(code, success_codes):
        message = (f"Job '{job_key}' ended with return code {code}, which its Success return codes "
                   f"({success_codes or return_codes.DEFAULT_SUCCESS}) do not include.")
        job_log.error(message)
        send_log()
        telemetry.end_run("FAILED", error=message, return_code=code, reason="RETURN_CODE")
        return 1
    job_log.summary(f"Job '{job_key}' completed successfully" + (f", return code {code}." if code else "."))
    send_log()
    telemetry.end_run("SUCCESS", return_code=code)
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
    parser.add_argument("--parent-run-id", default=None,
                        help="Given by the workflow runner: the workflow run this job runs in")
    parser.add_argument("--workflow-path", default=None, help="Given by the workflow runner: the job's place in it")
    parser.add_argument("--attempt", type=int, default=1, help="Given by the workflow runner: which attempt this is")
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
        job = db.query(Job).filter(Job.JobKey == args.job_key).first()
        if job is not None and job.JobType == "WORKFLOW":
            exit_code = start_workflow(db, job, args)
        else:
            exit_code = run_job(db, args.job_key, args.instance_id, args.spool_dir, args.working_root,
                                run_number=args.run_number, scheduler=args.scheduler, api_url=args.api_url,
                                run_id=str(args.run_id) if args.run_id else None, business_date=args.business_date,
                                parent_run_id=args.parent_run_id, workflow_path=args.workflow_path,
                                attempt=args.attempt)
    finally:
        db.close()
    sys.exit(exit_code)


def start_workflow(db: Session, workflow: Job, args) -> int:
    from engine.workflow_runner import RunOptions, run_workflow
    options = RunOptions(instance_id=args.instance_id, spool_dir=args.spool_dir,
                         run_id=str(args.run_id) if args.run_id else None, run_number=args.run_number,
                         scheduler=args.scheduler, api_url=args.api_url,
                         working_root=args.working_root or os.getenv("AUTOAPP_WORKING_ROOT"),
                         business_date=args.business_date, log_level=args.log_level,
                         parent_run_id=args.parent_run_id, workflow_path=args.workflow_path, attempt=args.attempt)
    return run_workflow(db, workflow, options)


if __name__ == "__main__":
    main()

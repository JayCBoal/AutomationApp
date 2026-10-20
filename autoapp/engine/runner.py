#!/usr/bin/env python3
"""
AutoApp execution runner.

Runs the active steps of one Job, in order (with its If, For Each File and While steps
deciding which of the steps inside them run, and how often: engine/executor.py), and
returns an OS exit code (0 = the job succeeded, 1 = it failed) for the calling WLA scheduler.

The job's return code is 0 unless a step sets another (Set Return Code and Simulate do); the job
succeeded if its steps did and that code is one of its Success return codes ("0" unless set).
The code is recorded with the run; the exit code stays 0 or 1 (docs/INTEGRATION.md).

A job that is a workflow is handed to engine/workflow_runner.py, so it is started the same way.

Told to stop (SIGTERM, as Kill sends), the job ends Failed, Reason KILLED, with no return code.
A job run on its own carries out its own Reactions (engine/reactions.py): Count as, Rerun this
job (a new run, the next attempt, in this same process) and Start a workflow. In a workflow,
the workflow runner carries them out instead.
"""
import argparse
import os
import signal
import sys
import time
import uuid
from datetime import date, datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Job, Variable, WorkflowItemVariable
from engine import job_log, log_files, return_codes, workflow_vars
from engine.executor import Executor
from engine.preflight import describe_problems, prepare_job
from engine.reactions import OwnReactions, read_rules
from engine.scope_engine import ScopeResolutionEngine
from engine.telemetry_client import LocalSpoolTelemetryClient

class Killed(BaseException):
    """Raised when the runner is told to stop. Not an Exception, so no step's On failure can carry on past it."""


def _killed(_signal_number, _frame):
    raise Killed()


def run_job(db: Session, job_key: str, instance_id: str, spool_dir: str,
            working_root: Optional[str] = None, run_number: int = 1,
            scheduler: Optional[str] = None, api_url: Optional[str] = None, run_id: Optional[str] = None,
            business_date: Optional[date] = None, environment: Optional[Dict[str, str]] = None,
            parent_run_id: Optional[str] = None, workflow_path: Optional[str] = None, attempt: int = 1,
            own: Optional[OwnReactions] = None) -> int:
    """
    Executes the job and returns the exit code to hand back to the scheduler.
    environment is what ${ENV:...} and the ENV level read: this process's own, unless given.
    own: the job's own Reactions, when it runs on its own.
    """
    environment = dict(os.environ) if environment is None else environment
    signal.signal(signal.SIGTERM, _killed)
    with LocalSpoolTelemetryClient(spool_dir=spool_dir, instance_id=instance_id, api_url=api_url,
                                   run_id=run_id) as telemetry:
        log_file = log_files.start(telemetry.run_id)
        telemetry.start_run(job_key, run_number=run_number, scheduler=scheduler, business_date=business_date,
                            parent_run_id=parent_run_id, workflow_path=workflow_path, attempt=attempt,
                            log_file=log_file)
        job_log.summary(f"Job '{job_key}', instance {instance_id}, run number {run_number}"
                        + (f", business date {business_date.isoformat()}" if business_date else ""))
        job_log.debug(f"Run ID {telemetry.run_id}; spool file {telemetry.active_file_path}")
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
            from_workflow = workflow_vars.for_run(db, parent_run_id, workflow_path)
            _log_from_workflow(from_workflow)
            scope_engine = ScopeResolutionEngine(
                db=db, job_id=job_id, instance_id=instance_id, global_config=global_config,
                environment=environment, business_date=business_date, workflow=from_workflow,
            )
            scope_engine.build_context()
            if scope_engine.working_folder:
                os.makedirs(scope_engine.working_folder, exist_ok=True)
            job_log.debug(f"Working folder: {scope_engine.working_folder}")

            # Every step is checked and resolved before the first one runs
            prepared_steps, problems = prepare_job(db, job, scope_engine)
            if problems:
                raise ValueError(describe_problems(problems))

            # Send what a step recorded; a failure here never affects the job
            executor = Executor(db, scope_engine, telemetry, telemetry.deliver)
            executor.run_all(prepared_steps)

        except Killed:
            job_log.error(f"Job '{job_key}' was killed.")
            telemetry.end_run("FAILED", error="Killed while running.", return_code=None, reason="KILLED")
            return 1
        except Exception as e:
            job_log.error(f"Job '{job_key}' failed: {e}")
            code = executor.job_return_code if executor and executor.job_return_code is not None else 1
            return _end(telemetry, own, "FAILED", code, "ERROR", str(e))
        return _finish(job_key, executor.job_return_code, success_codes, telemetry, own)


def _log_from_workflow(levels: Optional[workflow_vars.Levels]) -> None:
    """Names, never values, of the variables the job gets from its workflow and its use there."""
    if levels is None:
        return
    if levels.values or levels.conflicts:
        job_log.detail(f"Variables from workflow '{levels.workflow_key}': "
                       + ", ".join(sorted({*levels.values, *levels.conflicts})) + ".")
    if levels.use_values:
        job_log.detail("Variables set on this use of the job: " + ", ".join(sorted(levels.use_values)) + ".")


def _finish(job_key: str, code: Optional[int], success_codes: Optional[str], telemetry,
            own: Optional[OwnReactions] = None) -> int:
    """Ends a job whose steps all went as they should: it succeeded if its return code is a success code."""
    code = 0 if code is None else code
    if not return_codes.matches(code, success_codes):
        message = (f"Job '{job_key}' ended with return code {code}, which its Success return codes "
                   f"({success_codes or return_codes.DEFAULT_SUCCESS}) do not include.")
        job_log.error(message)
        return _end(telemetry, own, "FAILED", code, "RETURN_CODE", message)
    job_log.summary(f"Job '{job_key}' completed successfully" + (f", return code {code}." if code else "."))
    return _end(telemetry, own, "SUCCESS", code)


def _end(telemetry, own: Optional[OwnReactions], status: str, code: Optional[int], reason: Optional[str] = None,
         error: Optional[str] = None) -> int:
    """Records the run's end, after its own Reactions, if it has any. Returns the exit code."""
    counted = status
    if own is not None:
        def record(act, result, message):
            (job_log.warning if result == "LIMIT_REACHED" else job_log.summary)(message)
            telemetry.record_reaction(act.action, result, message, act.id)
        counted = own.after(status, code, record)
    telemetry.end_run(counted, error=error, return_code=code, reason=reason,
                      status_before_override=status if counted != status else None)
    return 0 if counted == "SUCCESS" else 1


def business_date_argument(text: str) -> date:
    for form in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text.strip(), form).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"'{text}' is not a date: use YYYY-MM-DD or YYYYMMDD, e.g. 2026-10-15")


def main():
    signal.signal(signal.SIGTERM, _killed)          # from the start: Kill can come at any moment
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
        secrets += [value for (value,) in db.query(WorkflowItemVariable.VarValue)
                    .filter(WorkflowItemVariable.IsSecret.is_(True))]
        secrets += [os.environ[name.strip()] for name in args.mask_env.split(",") if name.strip() in os.environ]
        job_log.configure(args.log_level, secrets=secrets)
        exit_code = run_with_reactions(db, args)
    finally:
        db.close()
    sys.exit(exit_code)


def run_with_reactions(db: Session, args) -> int:
    """
    Runs the job, or the workflow. On its own, its own Reactions may run it again: each time a new
    run, the next attempt, under the same instance ID. In a workflow, the workflow runner decides.
    """
    job = db.query(Job).filter(Job.JobKey == args.job_key).first()
    own = None
    if job is not None and job.IsActive and not args.parent_run_id:
        rules = read_rules(job)
        if rules:
            own = OwnReactions(rules, {"spool_dir": args.spool_dir, "api_url": args.api_url,
                                       "working_root": args.working_root, "log_level": args.log_level})
    run_id, attempt = str(args.run_id) if args.run_id else None, args.attempt
    while True:
        if job is not None and job.JobType == "WORKFLOW":
            exit_code = start_workflow(db, job, args, run_id, attempt, own)
        else:
            exit_code = run_job(db, args.job_key, args.instance_id, args.spool_dir, args.working_root,
                                run_number=args.run_number, scheduler=args.scheduler, api_url=args.api_url,
                                run_id=run_id, business_date=args.business_date,
                                parent_run_id=args.parent_run_id, workflow_path=args.workflow_path,
                                attempt=attempt, own=own)
        if own is None or own.rerun is None:
            return exit_code
        time.sleep(own.rerun.wait_seconds)
        run_id, attempt = None, attempt + 1
        db.expire_all()


def start_workflow(db: Session, workflow: Job, args, run_id: Optional[str], attempt: int,
                   own: Optional[OwnReactions]) -> int:
    from engine.workflow_runner import RunOptions, run_workflow
    options = RunOptions(instance_id=args.instance_id, spool_dir=args.spool_dir,
                         run_id=run_id, run_number=args.run_number,
                         scheduler=args.scheduler, api_url=args.api_url,
                         working_root=args.working_root or os.getenv("AUTOAPP_WORKING_ROOT"),
                         business_date=args.business_date, log_level=args.log_level,
                         parent_run_id=args.parent_run_id, workflow_path=args.workflow_path, attempt=attempt)
    return run_workflow(db, workflow, options, own)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
AutoApp execution runner.

Runs the active steps of one Job, in order (with its If, For Each File and While steps
deciding which of the steps inside them run, and how often: engine/executor.py), and
returns an OS exit code (0 = the job succeeded, 1 = it failed) for the calling WLA scheduler.

The job's return code is 0 unless a step sets another (Set Return Code and Simulate do); the job
succeeded if its steps did and that code is one of its Success return codes ("0" unless set).
The code is recorded with the run; the exit code stays 0 or 1 (docs/INTEGRATION.md).

A job that is a workflow is handed to engine/workflow_runner.py, so it is started the same way. Given
--reopen, a workflow picks up a run that has ended, under the same run ID (docs/WORKFLOWS_PHASE7.md).

As it goes, a job keeps a control file beside its log (engine/control_file.py). A run given the ID of an
earlier attempt (resume_run_id) reads that attempt's file and picks up where it stopped: steps that
finished are not run again, an If keeps its branch, a loop goes on from its pass, and a file step skips
the files already done.

Told to stop (SIGTERM, as Kill sends), the job ends Failed, Reason KILLED, with no return code.
A job run on its own carries out its own Reactions (engine/reactions.py): Count as, Rerun this
job (a new run, the next attempt, in this same process) and Start a workflow. In a workflow,
the workflow runner carries them out instead.
"""
import argparse
import json
import os
import signal
import sys
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Job, JobRun, Variable, WorkflowItemVariable
from engine import job_log, log_files, return_codes, run_values, workflow_vars
from engine.control_file import ControlRecord, ControlWriter, NullControl, control_name
from engine.executor import Executor
from engine.preflight import describe_problems, prepare_job
from engine.reactions import OwnReactions, read_rules
from engine.scope_engine import ScopeResolutionEngine
from engine.step_catalog import UNKNOWN
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
            own: Optional[OwnReactions] = None, resume_run_id: Optional[str] = None,
            count_as_done: Optional[str] = None, refresh_values: bool = False,
            value_edits: Optional[Dict[str, str]] = None, drop_values: Optional[List[str]] = None) -> int:
    """
    Executes the job and returns the exit code to hand back to the scheduler.
    environment is what ${ENV:...} and the ENV level read: this process's own, unless given.
    own: the job's own Reactions, when it runs on its own.
    resume_run_id: an earlier attempt to pick up where it stopped, using its control file.
    count_as_done: the key of a step of that attempt the operator says to count as done, not run again.
    refresh_values: a picked-up run reads its variables again; by default it uses the values as that attempt had them.
    value_edits: values the operator changed for a picked-up run, by key (engine/run_values.py); for a job
        started again by Advanced they are the only values pinned, the rest being read fresh.
    drop_values: names of the workflow's or the use's variables that were changed: the run reads them again.
    """
    environment = dict(os.environ) if environment is None else environment
    signal.signal(signal.SIGTERM, _killed)
    if own is not None and resume_run_id and own.run_id == resume_run_id and own.record is not None:
        resume, resume_problem = own.record, None           # this process ran it: its record is in hand, not yet in the database
    else:
        resume, resume_problem = find_earlier_attempt(db, resume_run_id)
    business_date = business_date or (resume.business_date if resume else None)
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
        control = open_control(log_file, resume)
        if own is not None:
            own.control_path = control.path
        if resume:
            telemetry.carry_over(*(own.totals if own is not None and own.record is resume else earlier_totals(db, resume_run_id)))

        executor, success_codes = None, None
        try:
            if resume_problem:
                raise ValueError(resume_problem)
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
                started=resume.started if resume else None,
                pinned=run_values.pins(resume.values if resume else {}, value_edits, keep=not refresh_values,
                                       drop=drop_values) if resume or value_edits else None,
            )
            scope_engine.build_context()
            control.write("job", run_id=telemetry.run_id, job_key=job_key, started=scope_engine.started.isoformat(),
                          business_date=business_date.isoformat() if business_date else None)
            _log_how_it_started(resume, attempt, count_as_done)
            if scope_engine.working_folder:
                os.makedirs(scope_engine.working_folder, exist_ok=True)
            job_log.debug(f"Working folder: {scope_engine.working_folder}")

            # Every step is checked and resolved before the first one runs
            prepared_steps, problems = prepare_job(db, job, scope_engine)
            if problems:
                raise ValueError(describe_problems(problems))

            # Send what a step recorded; a failure here never affects the job
            used = run_values.snapshot(scope_engine)
            control.write("values", values=used)
            if resume:
                _log_values(resume, used, refresh_values, value_edits or {}, drop_values or [])
            executor = Executor(db, scope_engine, telemetry, telemetry.deliver, control=control, resume=resume,
                                count_as_done=count_as_done)
            executor.run_all(prepared_steps)

        except Killed:
            job_log.error(f"Job '{job_key}' was killed.")
            telemetry.end_run("FAILED", error="Killed while running.", return_code=None, reason="KILLED")
            return 1
        except Exception as e:
            job_log.error(f"Job '{job_key}' failed: {e}")
            code = executor.job_return_code if executor and executor.job_return_code is not None else 1
            return _end(telemetry, own, "FAILED", code, failure_reason(e), str(e))
        finally:
            control.close()
        exit_code = _finish(job_key, executor.job_return_code, success_codes, telemetry, own)
        if exit_code == 0 and return_codes.matches(executor.job_return_code or 0, success_codes):
            remove_control_files(control.path, resume)      # it Succeeded, and no Reaction changed that
        return exit_code


def remove_control_files(own_path: Optional[Path], resume: Optional[ControlRecord]) -> None:
    """
    A run that Succeeded has nothing left to pick up: its control file goes, and so does the file of the attempt
    it picked up (this one holds copies of its records, and the job logs keep the history). A failed, killed or
    Reaction-overridden run keeps its file. Never fails the run: a file that is gone already, or cannot be removed,
    goes with its log in any case.
    """
    for path in (own_path, resume.path if resume else None):
        try:
            if path is not None:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def _log_how_it_started(resume: Optional[ControlRecord], attempt: int, count_as_done: Optional[str]) -> None:
    """Says in the job log whether this attempt picks up an earlier one or starts again from the beginning."""
    earlier = f"attempt {attempt - 1}" if attempt > 1 else "the earlier attempt"
    if resume is None:
        if attempt > 1:
            job_log.summary(f"Restarted from the beginning (attempt {attempt}); {earlier} failed.")
        return
    job_log.summary(f"Resumed from {earlier}: {_what_was_finished(resume)}")
    failure = resume.open_failure()
    if failure and failure.get("operator_decides") and failure.get("key") != count_as_done:
        job_log.summary(f"Step {failure['step']} '{failure.get('title')}' may have changed something before it "
                        f"failed: run again, as chosen.")


def _what_was_finished(resume: ControlRecord) -> str:
    """"steps 1 to 3 had finished; step 4 runs again.", in the words the job log uses."""
    failure = resume.open_failure()
    numbers = sorted({int(r["key"].split("|")[0]) for r in resume.ended_steps() if r["key"].split("|")[0].isdigit()})
    if failure is None:
        return "all steps had finished."
    again = f"step {failure['step']} runs again."
    if not numbers:
        return f"no step had finished; {again}"
    if len(numbers) == 1:
        return f"step {numbers[0]} had finished; {again}"
    if numbers == list(range(numbers[0], numbers[-1] + 1)):
        return f"steps {numbers[0]} to {numbers[-1]} had finished; {again}"
    return f"steps {', '.join(str(n) for n in numbers)} had finished; {again}"


def _log_values(resume: ControlRecord, now: Dict[str, dict], refreshed: bool, edits: Dict[str, str],
                dropped: List[str]) -> None:
    """Says in the job log which values a picked-up run reads again, or the operator changed."""
    if refreshed:
        for change in run_values.changes(resume.values, now):
            job_log.summary(f"Refreshed {change.key}: it was '{change.was}', it is now '{change.now}'.")
    for key, value in edits.items():
        was = resume.values.get(key, {}).get("value")
        job_log.summary(f"Edited {key}: it was '{was}', the operator set '{value}'.")
    for name in dropped:
        if not refreshed and {name, f"WORKFLOW.{name}", f"USE.{name}"} & set(resume.values):
            job_log.summary(f"{name} is read again: the workflow's value for it was changed.")


def find_earlier_attempt(db: Session, run_id: Optional[str]) -> Tuple[Optional[ControlRecord], Optional[str]]:
    """
    The control file of the run to pick up, or, in words, why there is none to use. Its file is on the
    host that ran it, so a run that would resume elsewhere, or whose file is gone, cannot.
    """
    if not run_id:
        return None, None
    run = db.query(JobRun).filter(JobRun.RunID == str(run_id)).first()
    if run is None:
        return None, f"Run {run_id} is not known, so there is nothing to pick up. Restart the job from the beginning."
    if (run.Host or log_files.this_host()) != log_files.this_host():
        return None, (f"Run {run_id} ran on host '{run.Host}', and the record of how far it got is kept there; "
                      f"this run is on '{log_files.this_host()}'. Restart the job from the beginning.")
    path = log_files.host_folder(run.Host) / control_name(run.LogFile) if run.LogFile else None
    if path is None or not path.is_file():
        return None, (f"The record of how far run {run_id} got is not there; it is removed with the job log. "
                      f"Restart the job from the beginning.")
    return ControlRecord.read(path), None


def automatic_resume_problem(record: Optional[ControlRecord], problem: Optional[str]) -> Optional[str]:
    """
    Why a Reaction may not Resume a failed run, given its control record (or why there is none), in words,
    or None when it may. The rules are the operator's (docs/WORKFLOWS_PHASE7.md, proposals 3 and 13),
    except that nobody is there to decide: a step whose effect is not known stops it, and Restart from
    the beginning stays a choice.
    """
    if record is None:
        return problem
    failure = record.open_failure()
    if failure is None:
        return ("every step had finished, so there is nothing to pick up (the job failed on its return code). "
                "Choose Restart from the beginning to run it again.")
    if failure.get("operator_decides"):
        return (f"step '{failure.get('title') or failure.get('step')}' failed and AutoApp cannot tell whether it "
                f"changed anything ({failure.get('why') or 'no reason given'}). The job stays failed: Resume it by "
                f"hand and choose what to do about that step, or Restart from the beginning.")
    return None


def own_resume_problem(own: OwnReactions) -> Optional[str]:
    """Why a Reaction cannot Resume the run just ended, from the control file it left; the record is kept to resume from."""
    path = own.control_path
    own.record = ControlRecord.read(path) if path is not None and path.is_file() else None
    problem = None if own.record else ("this run kept no record of how far it got, so there is nothing to pick up. "
                                       "Choose Restart from the beginning.")
    return automatic_resume_problem(own.record, problem)


def earlier_totals(db: Session, run_id: str) -> Tuple[Optional[int], Optional[int]]:
    """The files and bytes the run being picked up had delivered, its own net total if it was a pick-up too."""
    run = db.query(JobRun).filter(JobRun.RunID == str(run_id)).first()
    return (run.FileCount, run.Bytes) if run else (None, None)


def failure_reason(error: Exception) -> str:
    """ERROR, or EFFECT_UNKNOWN (shown as "Failed (effect unknown)") when the failed step could not say what it did."""
    knew = getattr(error, "knew", None) or getattr(error.__cause__, "knew", None)
    return "EFFECT_UNKNOWN" if knew is not None and knew.answer == UNKNOWN else "ERROR"


def open_control(log_file: Optional[str], resume: Optional[ControlRecord]):
    """
    The control file for this run, beside its log. A picked-up run starts its own with the earlier
    attempt's records, so the file alone tells a third attempt everything. Without a log file there is none.
    """
    if log_file is None:
        job_log.warning("This run keeps no record of how far it gets, so it cannot be picked up later.")
        return NullControl()
    control = ControlWriter(log_files.host_folder(log_files.this_host()) / control_name(log_file))
    if resume:
        control.copy_of(resume.records)
        control.write("resumed", from_run=resume.job.get("run_id"))
    return control


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
        own.run_id, own.totals = telemetry.run_id, tuple(telemetry.delivered().values())
        counted = own.after(status, code, record, lambda: own_resume_problem(own))
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
    parser.add_argument("--resume-run-id", default=None,
                        help="Pick up an earlier attempt of this job where it stopped, given its run ID")
    parser.add_argument("--reopen", default=None, choices=["resume", "restart", "advanced"],
                        help="For a workflow: pick up the run --run-id names, which has ended, instead of starting a new one. "
                             "advanced: run again the items --reopen-items names, each as it says")
    parser.add_argument("--reopen-items", default=None,
                        help="With --reopen advanced: a JSON object giving, by path, resume or restart for each item to run again")
    parser.add_argument("--ignore-waits", default=None,
                        help="With --reopen advanced: a JSON object listing, by the job's path, the prerequisites to ignore for this "
                             "reopening only")
    parser.add_argument("--reset-counts", action="store_true",
                        help="With --reopen advanced: the Reactions of the run start their counts from zero")
    parser.add_argument("--reopen-scope", default=None,
                        help="With --reopen: the path of the one item to run again; without it, the whole run")
    parser.add_argument("--rerun-decisions", default=None,
                        help="With --reopen: a JSON object saying, by path, run_again or count_done for each failed step "
                             "whose effect is not known")
    parser.add_argument("--count-as-done", default=None,
                        help="With --resume-run-id: the key of the failed step (e.g. 3|) to count as done and not run again")
    parser.add_argument("--refresh-values", action="store_true",
                        help="With --resume-run-id: read the ${...} values again, not use them as the earlier attempt had them")
    parser.add_argument("--edit-values", default=None,
                        help="With --resume-run-id: a JSON object of values to use instead, by key. "
                             "With --reopen (a workflow): the values changed at each level of the workflow "
                             "(engine/workflow_vars.py, apply_choices)")
    parser.add_argument("--drop-values", default=None,
                        help="With --resume-run-id: a JSON list of names the workflow or the use changed; "
                             "the run reads them again, not as the earlier attempt had them")
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
    run_id, attempt, resume_run_id = str(args.run_id) if args.run_id else None, args.attempt, args.resume_run_id
    count_as_done, reopen = args.count_as_done, args.reopen
    refresh_values, value_edits = args.refresh_values, json.loads(args.edit_values) if args.edit_values else None
    drop_values = json.loads(args.drop_values) if args.drop_values else None
    while True:
        if job is not None and job.JobType == "WORKFLOW":
            exit_code = start_workflow(db, job, args, run_id, attempt, own, reopen, refresh_values, value_edits)
        else:
            exit_code = run_job(db, args.job_key, args.instance_id, args.spool_dir, args.working_root,
                                run_number=args.run_number, scheduler=args.scheduler, api_url=args.api_url,
                                run_id=run_id, business_date=args.business_date,
                                parent_run_id=args.parent_run_id, workflow_path=args.workflow_path,
                                attempt=attempt, own=own, resume_run_id=resume_run_id, count_as_done=count_as_done,
                                refresh_values=refresh_values, value_edits=value_edits, drop_values=drop_values)
        if own is None or own.rerun is None:
            return exit_code
        time.sleep(own.rerun.wait_seconds)
        is_workflow = job is not None and job.JobType == "WORKFLOW"
        resume_run_id = own.run_id if own.rerun.resumes and not is_workflow else None
        # a workflow that resumes is its same run reopened; a restart is a new run under the same instance ID
        run_id, reopen = (own.run_id, "resume") if own.rerun.resumes and is_workflow else (None, None)
        attempt, count_as_done = attempt + 1, None
        args.reopen_scope, args.rerun_decisions, args.reopen_items = None, None, None
        args.ignore_waits, args.reset_counts = None, False
        refresh_values, value_edits, drop_values = False, None, None
        db.expire_all()


def start_workflow(db: Session, workflow: Job, args, run_id: Optional[str], attempt: int,
                   own: Optional[OwnReactions], reopen: Optional[str] = None, refresh_values: bool = False,
                   value_edits: Optional[dict] = None) -> int:
    from engine.workflow_runner import RunOptions, run_workflow
    options = RunOptions(instance_id=args.instance_id, spool_dir=args.spool_dir,
                         run_id=run_id, run_number=args.run_number,
                         scheduler=args.scheduler, api_url=args.api_url,
                         working_root=args.working_root or os.getenv("AUTOAPP_WORKING_ROOT"),
                         business_date=args.business_date, log_level=args.log_level,
                         parent_run_id=args.parent_run_id, workflow_path=args.workflow_path, attempt=attempt,
                         reopen=reopen, reopen_scope=args.reopen_scope if reopen else None,
                         reopen_items=json.loads(args.reopen_items) if reopen == "advanced" and args.reopen_items else None,
                         ignored_waits=json.loads(args.ignore_waits) if reopen == "advanced" and args.ignore_waits else {},
                         reset_counts=bool(reopen == "advanced" and args.reset_counts),
                         decisions=json.loads(args.rerun_decisions) if reopen and args.rerun_decisions else {},
                         refresh_values=bool(reopen and refresh_values), value_edits=(value_edits or {}) if reopen else {})
    return run_workflow(db, workflow, options, own)


if __name__ == "__main__":
    main()

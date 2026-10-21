"""
Running a failed job again from where it stopped, or from the beginning (docs/WORKFLOWS_PHASE7.md):

    GET  /api/v1/runs/{run_id}/rerun-plan   what Resume would do, and whether an operator has to decide first
    POST /api/v1/runs/{run_id}/rerun        start the next attempt: kind "resume" or "restart"

Either is a new run, the next attempt, under the same instance ID. Resume starts the runner with the
earlier attempt's control file (engine/control_file.py), so the steps that finished are not run again. A step
that failed without knowing whether it changed anything must be decided on first: run it again, or count it
as done. The ${...} values the job used come back as they were, unless the operator refreshes them (reads
them again) or edits some (engine/run_values.py). For now this is for a job run on its own; a workflow, or a job inside one, comes with later steps.
"""
import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Audit, Job, JobRun
from app.routers.launches import LaunchOut, start_runner
from engine import job_log, run_values
from engine.control_file import ControlRecord
from engine.runner import find_earlier_attempt
from engine.scope_engine import ScopeResolutionEngine

router = APIRouter(prefix="/api/v1/runs", tags=["Runs"])

RUN_AGAIN, COUNT_AS_DONE = "run_again", "count_done"


class StepToDecide(BaseModel):
    step: str = Field(..., description="The step's number in the job, e.g. 3.1")
    title: str
    why: str = Field(..., description="Why it is not known what the step did, in words")
    key: str = Field(..., description="The step's place in the run, with its loop passes, as the runner names it")


class ValueShown(BaseModel):
    key: str = Field(..., description="What the job wrote: Region for ${Region}, JOB.Region, or ENV:Region")
    value: Optional[str] = Field(None, description="The value the earlier attempt used; absent for a secret")
    secret: bool = Field(False, description="A secret is read again each time, and cannot be edited")


class ValueChange(BaseModel):
    key: str
    was: str
    now: str


class RerunPlan(BaseModel):
    run_id: str
    job_key: str
    attempt: int
    can_restart: bool
    can_resume: bool
    refusal: Optional[str] = Field(None, description="Why neither can be done, in words")
    resume_problem: Optional[str] = Field(None, description="Why Resume cannot be done, in words; Restart can")
    steps_finished: int = 0
    step_to_decide: Optional[StepToDecide] = Field(
        None, description="A failed step that may or may not have changed something: Resume needs the operator's choice")
    summary: str = ""
    values: List[ValueShown] = Field([], description="The ${...} values the earlier attempt used")
    changes: List[ValueChange] = Field(
        [], description="Values that read differently now: what Refresh would use instead of what the earlier attempt had")


class RerunRequest(BaseModel):
    kind: str = Field(..., description="resume or restart")
    unknown_step: Optional[str] = Field(None, description="For a Resume with a step to decide: run_again or count_done")
    refresh_values: bool = Field(False, description="For a Resume: read the ${...} values again, not use them as they were")
    edits: Dict[str, str] = Field({}, description="For a Resume: values to use instead, by key (not for a secret)")
    log_level: str = Field(job_log.DEFAULT_LEVEL, description="DEBUG, DETAIL, SUMMARY or SILENT")


def _find(db: Session, run_id: str) -> JobRun:
    run = db.query(JobRun).filter(JobRun.RunID == run_id).first()
    if run is None:
        raise HTTPException(404, f"AutoApp has no record of run '{run_id}'.")
    return run


def _refusal(db: Session, run: JobRun) -> Optional[str]:
    """Why this run cannot be run again at all, or None."""
    if run.JobType == "WORKFLOW" or run.ParentRun_id is not None:
        return "Running a workflow again, or a job inside one, is not built yet. Only a job run on its own can be rerun for now."
    if run.Status == "RUNNING":
        return f"'{run.JobKey}' is still running. Kill it first if it should be run again."
    if run.Status != "FAILED":
        return f"'{run.JobKey}' succeeded, so there is nothing to pick up. Run it again from the Run Job page."
    later = (db.query(JobRun.Attempt).filter(JobRun.JobKey == run.JobKey, JobRun.SchedulerInstanceID == run.SchedulerInstanceID,
                                            JobRun.Attempt > run.Attempt).first())
    if later:
        return f"This is attempt {run.Attempt}; attempt {later[0]} has run since. Run that one again instead."
    return None


def _step_to_decide(record: Optional[ControlRecord]) -> Optional[StepToDecide]:
    failure = record.open_failure() if record else None
    if failure is None or not failure.get("operator_decides"):
        return None
    return StepToDecide(step=failure.get("step", ""), title=failure.get("title") or "", why=failure.get("why") or "",
                        key=failure["key"])


def make_plan(db: Session, run: JobRun) -> RerunPlan:
    plan = RerunPlan(run_id=run.RunID, job_key=run.JobKey, attempt=run.Attempt, can_restart=False, can_resume=False)
    plan.refusal = _refusal(db, run)
    if plan.refusal:
        return plan
    plan.can_restart = True
    record, problem = find_earlier_attempt(db, run.RunID)
    plan.can_resume, plan.resume_problem = record is not None, problem
    if record is not None:
        plan.steps_finished = len(record.ended_steps())
        plan.step_to_decide = _step_to_decide(record)
        plan.summary = _summary(plan)
        plan.values = [ValueShown(key=key, value=entry.get("value"), secret="secret" in entry)
                       for key, entry in sorted(record.values.items())]
        plan.changes = _changes(db, run, record)
    return plan


def _changes(db: Session, run: JobRun, record: ControlRecord) -> List[ValueChange]:
    """
    Which of the earlier attempt's values read differently now. The server has no environment to look in, so
    an environment variable's value, and what depends on one, is not compared: the run reads it when it starts.
    """
    job = db.query(Job).filter(Job.JobKey == run.JobKey).first()
    if job is None or not record.values:
        return []
    engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id=run.SchedulerInstanceID,
                                   business_date=record.business_date, started=record.started)
    try:
        engine.build_context()
    except ValueError:
        return []
    keys = [key for key, entry in record.values.items() if "value" in entry]
    engine.used.update({key: True for key in keys})
    now = {key: entry for key, entry in run_values.snapshot(engine, secrets=run_values.secret_values(db)).items()
           if "${ENV:" not in entry.get("value", "")}
    return [ValueChange(key=c.key, was=c.was, now=c.now) for c in run_values.changes(record.values, now)]


def _summary(plan: RerunPlan) -> str:
    done = f"{plan.steps_finished} step{'s' if plan.steps_finished != 1 else ''} finished and will not be run again"
    if plan.step_to_decide is None:
        return f"Resume picks up where attempt {plan.attempt} stopped: {done}."
    return (f"Resume picks up where attempt {plan.attempt} stopped: {done}. "
            f"Step {plan.step_to_decide.step} '{plan.step_to_decide.title}' needs your decision first.")


@router.get("/{run_id}/rerun-plan", response_model=RerunPlan)
def rerun_plan(run_id: str, db: Session = Depends(get_db)):
    """What Rerun can do for this run: whether Resume is possible, and a step the operator must decide on."""
    return make_plan(db, _find(db, run_id))


@router.post("/{run_id}/rerun", response_model=LaunchOut, status_code=status.HTTP_202_ACCEPTED)
def rerun(run_id: str, payload: RerunRequest, request: Request, db: Session = Depends(get_db)):
    """Starts the next attempt of a failed job, at once; follow it with GET /api/v1/runs/{run_id} of the answer's run_id."""
    run = _find(db, run_id)
    plan = make_plan(db, run)
    if plan.refusal:
        raise HTTPException(409, plan.refusal)
    kind = payload.kind.strip().lower()
    if kind not in ("resume", "restart"):
        raise HTTPException(422, "Choose resume or restart.")
    level = payload.log_level.strip().upper()
    try:
        job_log.level_number(level)
    except ValueError as e:
        raise HTTPException(422, str(e))
    extra = ["--run-number", str(run.RunNumber), "--attempt", str(run.Attempt + 1)]
    if kind == "resume":
        extra += _resume_arguments(plan, payload.unknown_step)
        extra += _value_arguments(db, run, payload)
    elif payload.refresh_values or payload.edits:
        raise HTTPException(422, "Values can be refreshed or edited for a Resume; a restart reads them all again.")
    return start_runner(request, run.JobKey, run.SchedulerInstanceID, level, run.BusinessDate, extra,
                        scheduler=run.SchedulerName or "AutoApp UI")


def _resume_arguments(plan: RerunPlan, unknown_step: Optional[str]) -> List[str]:
    if not plan.can_resume:
        raise HTTPException(409, plan.resume_problem)
    arguments = ["--resume-run-id", plan.run_id]
    step = plan.step_to_decide
    if step is None:
        return arguments
    if unknown_step not in (RUN_AGAIN, COUNT_AS_DONE):
        raise HTTPException(422, f"Step {step.step} '{step.title}' may or may not have changed something before it failed. "
                                 f"Choose to run it again or to count it as done, or restart the job from the beginning.")
    return arguments + (["--count-as-done", step.key] if unknown_step == COUNT_AS_DONE else [])


def _value_arguments(db: Session, run: JobRun, payload: RerunRequest) -> List[str]:
    """Refresh or edit the earlier attempt's values; an edit is recorded in the Audit Log, by name and never a secret."""
    arguments = ["--refresh-values"] if payload.refresh_values else []
    if not payload.edits:
        return arguments
    record, _ = find_earlier_attempt(db, run.RunID)
    problems = run_values.edit_problems(record.values, payload.edits)
    if problems:
        raise HTTPException(422, " ".join(problems))
    job = db.query(Job).filter(Job.JobKey == run.JobKey).first()
    changes = [f"Resumed '{run.JobKey}' (attempt {run.Attempt + 1}) with {key} changed from "
               f"'{record.values[key]['value']}' to '{value}'." for key, value in sorted(payload.edits.items())]
    db.add(Audit(MasterObject_id=job.MasterObject_id if job else None, Action="JOB_RESUMED_WITH_EDITS",
                 PerformedBy="web interface", Details=json.dumps({"changes": changes})))
    db.commit()
    return arguments + ["--edit-values", json.dumps(payload.edits)]

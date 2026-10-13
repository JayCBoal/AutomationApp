"""
Checks a whole job before any of it runs.

Every active step is checked against its step type and has its parameters and
file locations resolved. Problems in any step are found up front, so a job
never moves files in step 1 only to discover a typing mistake in step 3.

Used by the runner before it starts, and by the API to check a job on request.
"""
from dataclasses import dataclass
from typing import Any, List, Tuple

from sqlalchemy.orm import Session

from app.models import Job, JobStep
from engine.handlers import get_handler
from engine.scope_engine import ScopeResolutionEngine
from engine.step_params import ResolvedStep, resolve_step


@dataclass
class PreparedStep:
    step: JobStep
    handler_cls: Any
    resolved: ResolvedStep


def prepare_job(db: Session, job: Job, scope_engine: ScopeResolutionEngine) -> Tuple[List[PreparedStep], List[str]]:
    """
    Returns the job's active steps, ready to run in order, and a list of problems.
    If the list of problems is not empty the job must not be run.
    """
    steps = (
        db.query(JobStep)
        .filter(JobStep.job_id == job.MasterObject_id, JobStep.IsActive.is_(True))
        .order_by(JobStep.StepOrder)
        .all()
    )
    if not steps:
        return [], [f"Job '{job.JobKey}' has no active steps."]

    prepared: List[PreparedStep] = []
    problems: List[str] = []
    for step in steps:
        try:
            handler_cls = get_handler(step.step_type.HandlerClass)
        except ValueError as e:
            problems.append(f"Step {step.StepOrder} ('{step.Title}'): {e}")
            continue
        try:
            prepared.append(PreparedStep(step, handler_cls, resolve_step(step, handler_cls, scope_engine, db)))
        except ValueError as e:
            problems.append(str(e))        # resolve_step names the step itself
    return prepared, problems


def describe_problems(problems: List[str]) -> str:
    """One problem as it is; several as a counted list."""
    if len(problems) == 1:
        return problems[0]
    return f"{len(problems)} problems were found before the job started:\n" + "\n".join(f"  - {p}" for p in problems)

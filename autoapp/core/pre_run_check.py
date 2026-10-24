"""
The pre-run check: what would stop a job or a workflow from running, in plain words, without running anything.

Used by the server (the editor and the Check pages) and by the workflow runner before it starts a run.
"""
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from core import conditions, workflow_vars
from core.models import Job
from core.preflight import prepare_job
from core.scope_engine import ScopeResolutionEngine


def job_problems(db: Session, job: Job, environment: Optional[Dict[str, str]] = None,
                 warnings: Optional[List[str]] = None, workflow=None) -> List[str]:
    """
    Everything that would stop the job from running, as the runner would report it. Runs nothing.
    environment: what the scheduler will set when it runs the job, if known (a WLA job's parameters).
    warnings: given a list, what is worth knowing but does not stop the job is added to it.
    workflow: for a job used in a workflow, what the workflow gives it (engine.workflow_vars.Levels).
    """
    if job.JobType == "WORKFLOW":
        return workflow_problems(db, job, warnings)
    problems = []
    if not job.IsActive:
        problems.append(f"Job '{job.JobKey}' is disabled.")
    engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="CHECK", environment=environment,
                                   workflow=workflow)
    engine.build_context()
    return problems + prepare_job(db, job, engine, warnings)[1]


def workflow_problems(db: Session, workflow: Job, warnings: Optional[List[str]] = None,
                      seen: Optional[Set[int]] = None) -> List[str]:
    """
    What would stop the workflow from starting, in plain words: only what is wrong with it as a whole.
    A job in it that is disabled, or would fail its own pre-run check, does not stop it: when its turn
    comes it ends Disabled, or fails, and what needs it to succeed does not run. Given a list, warnings
    gets those jobs, so the check can say so before the run. Runs nothing.
    """
    seen = (seen or set()) | {workflow.MasterObject_id}
    problems = []
    if not workflow.IsActive:
        problems.append(f"Workflow '{workflow.JobKey}' is disabled.")
    if not workflow.items:
        problems.append(f"Workflow '{workflow.JobKey}' has no jobs in it yet. Add the jobs it should run.")
    problems += _variable_problems(db, workflow)
    problems += _outside_problems(workflow, warnings)
    if warnings is None:
        return problems
    checked: Dict[int, List[str]] = {}
    for item in workflow.items:
        job = item.job
        if job.MasterObject_id in seen:
            continue
        if not job.IsActive:
            warnings.append(f"'{item.ItemName}' is disabled: it will end Disabled, and what needs it to succeed will not run.")
            continue
        # A job is checked once for each use, which may set variables of its own
        if item.id not in checked:
            checked[item.id] = (workflow_problems(db, job, [], seen) if job.JobType == "WORKFLOW"
                                else job_problems(db, job, workflow=workflow_vars.for_check(db, workflow, item)))
        for problem in checked[item.id][:1]:     # the first is enough to say it would fail
            warnings.append(f"'{item.ItemName}' would fail: {problem}")
    return problems


def _outside_problems(workflow: Job, warnings: Optional[List[str]]) -> List[str]:
    """What is wrong with the files a job waits for (they must be on this server); an unlimited wait is a warning."""
    problems = []
    for item in workflow.items:
        for p in item.prerequisites:
            if p.Kind == "ENDPOINT" and p.endpoint is not None and p.endpoint.site is not None:
                problems.append(f"'{item.ItemName}' waits for files at the endpoint '{p.endpoint.Name}', which is on Site "
                                f"'{p.endpoint.site.Name}'. Only files on this server can be waited for yet.")
            if warnings is not None and p.Kind != "JOB" and p.WaitMode == "NONE":
                warnings.append(f"'{item.ItemName}' waits for '{p.TargetName}' with no limit: if it never happens, "
                                f"the workflow waits for ever.")
    return problems


def _variable_problems(db: Session, workflow: Job) -> List[str]:
    """Each ${...} in the workflow's conditions that has no value, said once. They are filled in as a run starts."""
    texts = [(f"'{item.ItemName}': its Custom rule", item.StartRule) for item in workflow.items
             if item.JoinRule == "CUSTOM" and item.StartRule]
    if workflow.SucceedsWhen:
        texts.append(("Succeeds when", workflow.SucceedsWhen))
    refs = [(where, ref) for where, text in texts for ref in _safe_references(text) if ref.startswith("${")]
    if not refs:
        return []
    engine = ScopeResolutionEngine(db=db, job_id=workflow.MasterObject_id, instance_id="CHECK")
    engine.build_context()
    problems = []
    for where, ref in refs:
        try:
            engine.interpolate(ref)
        except ValueError as e:
            problems.append(f"{where}: {e}")
    return problems


def _safe_references(text: str) -> List[str]:
    try:
        return conditions.references(text)
    except ValueError:
        return []                   # an unclosed quote is refused when saved

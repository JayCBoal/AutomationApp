"""
Running a failed job again from where it stopped, or from the beginning (docs/WORKFLOWS_PHASE7.md):

    GET  /api/v1/runs/{run_id}/rerun-plan   what Resume would do, and whether an operator has to decide first
    POST /api/v1/runs/{run_id}/rerun        start the next attempt: kind "resume" or "restart"

Either is a new run, the next attempt, under the same instance ID. Resume starts the runner with the
earlier attempt's control file (engine/control_file.py), so the steps that finished are not run again. A step
that failed without knowing whether it changed anything must be decided on first: run it again, or count it
as done. The ${...} values the job used come back as they were, unless the operator refreshes them (reads
them again) or edits some (engine/run_values.py). 

A workflow run is reopened, not copied: the same run goes back to Running under the same run ID, and its failed
and unrun items go on (Resume) or all start again (Restart). Chosen on a frame, or a failed job, inside a workflow, it
reopens the run at the top and runs again only that item (docs/WORKFLOWS_PHASE7.md, step 3; engine/reopen.py).
"""
import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Audit, Job, JobRun, utcnow
from app import rerun_advanced, rerun_values, run_restarts
from engine import reopen_tree as rerun_tree
from app.rerun_values import LevelEdit, ValueChange, ValueLevel, ValueShown
from app.routers.launches import LaunchOut, start_runner
from engine import job_log, reopen, run_values
from engine.control_file import ControlRecord
from engine.runner import find_earlier_attempt
from engine.scope_engine import ScopeResolutionEngine

router = APIRouter(prefix="/api/v1/runs", tags=["Runs"])

RUN_AGAIN, COUNT_AS_DONE = reopen.RUN_AGAIN, reopen.COUNT_AS_DONE


class StepToDecide(BaseModel):
    step: str = Field(..., description="The step's number in the job, e.g. 3.1")
    title: str
    why: str = Field(..., description="Why it is not known what the step did, in words")
    key: str = Field(..., description="The step's place in the run, with its loop passes, as the runner names it")
    path: Optional[str] = Field(None, description="In a workflow run: the job's place in it")


class ItemPlan(BaseModel):
    path: str
    job_key: str
    what: str = Field(..., description="What Resume does with it, in words")


class ItemChoice(BaseModel):
    path: str
    job_key: str
    status: str
    is_workflow: bool
    depth: int = Field(..., description="How many embedded workflows it is inside")
    can_resume: bool = Field(..., description="Whether it can be picked up from where it failed; if not, only restarted")
    resume_problem: Optional[str] = None
    waits: List[str] = Field([], description="What it waits for, by name: jobs of its workflow, and things outside it")
    custom_rule: bool = Field(False, description="It starts by a Custom rule: a wait cannot be ignored one by one")


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
    scope: Optional[str] = Field(None, description="In a workflow run: the one item chosen, by path; absent for the whole run")
    reopens_run_id: Optional[str] = Field(None, description="In a workflow run: the run that goes back to Running, the one at the top")
    items: List[ItemPlan] = Field([], description="In a workflow run: what Resume does with each item it touches")
    steps_to_decide: List[StepToDecide] = Field([], description="In a workflow run: every failed step the operator must decide on")
    values: List[ValueShown] = Field([], description="The ${...} values the earlier attempt used")
    changes: List[ValueChange] = Field(
        [], description="Values that read differently now: what Refresh would use instead of what the earlier attempt had")
    value_levels: List[ValueLevel] = Field(
        [], description="In a workflow run: the values to choose about, one list for each workflow, use and resumed job")
    kept_jobs: List[str] = Field([], description="In a workflow run: jobs that Succeeded; they are not run again and keep their values")
    values_note: str = Field("", description="In a workflow run: what to say about the conditions not yet decided")
    advanced: bool = Field(False, description="This is the plan of an Advanced rerun")
    choices: List[ItemChoice] = Field([], description="Advanced: every item of the run, to choose from")
    named_items: Dict[str, str] = Field({}, description="Advanced: what each item named gets, resume or restart, by path")
    items_problem: Optional[str] = Field(None, description="Advanced: why the items named cannot be run, in words")
    ignored: Dict[str, List[str]] = Field({}, description="Advanced: the prerequisites released for this one restart, by the job's path")
    reset_counts: bool = Field(False, description="Advanced: the Reactions of the run start their counts from zero")


class RerunRequest(BaseModel):
    kind: str = Field(..., description="resume, restart, or advanced (item by item, for a workflow run)")
    items: Dict[str, str] = Field({}, description="Advanced: resume or restart for each item, by path")
    shortcut: Optional[str] = Field(None, description="Advanced: from (the jobs chosen and all that waits for them) or only")
    chosen: List[str] = Field([], description="Advanced: the jobs chosen for a shortcut, by path")
    chosen_as: str = Field("resume", description="Advanced: what a failed item chosen gets, resume or restart")
    unknown_step: Optional[str] = Field(None, description="For a Resume with a step to decide: run_again or count_done")
    decisions: Dict[str, str] = Field({}, description="For a workflow run: run_again or count_done for each step to decide, by the job's path")
    refresh_values: bool = Field(False, description="For a Resume: read the ${...} values again, not use them as they were")
    edits: Dict[str, str] = Field({}, description="For a Resume: values to use instead, by key (not for a secret)")
    level_edits: Dict[str, LevelEdit] = Field(
        {}, description="For a workflow's Resume: variables to change, by the workflow's place in the run (empty for the top)")
    job_edits: Dict[str, Dict[str, str]] = Field(
        {}, description="For a workflow's Resume: a job's own values to change, by key, by the job's place in the run")
    ignore: Dict[str, List[str]] = Field({}, description="Advanced: prerequisites to ignore for this one restart, by the job's path")
    reset_counts: bool = Field(False, description="Advanced: the automatic retry counts of the run start again from zero")
    log_level: str = Field(job_log.DEFAULT_LEVEL, description="DEBUG, DETAIL, SUMMARY or SILENT")


def _find(db: Session, run_id: str) -> JobRun:
    run = db.query(JobRun).filter(JobRun.RunID == run_id).first()
    if run is None:
        raise HTTPException(404, f"AutoApp has no record of run '{run_id}'.")
    return run


def _in_a_workflow(run: JobRun) -> bool:
    return run.JobType == "WORKFLOW" or run.ParentRun_id is not None


def _refusal(db: Session, run: JobRun) -> Optional[str]:
    """Why this run cannot be run again at all, or None."""
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
    if _in_a_workflow(run):
        return make_workflow_plan(db, run)
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
        plan.changes = changes_for(db, run, record)
    return plan


def make_workflow_plan(db: Session, run: JobRun) -> RerunPlan:
    tree = rerun_tree.make_tree_plan(db, run)
    plan = RerunPlan(run_id=run.RunID, job_key=run.JobKey, attempt=run.Attempt, can_restart=tree.refusal is None,
                     can_resume=False, refusal=tree.refusal, scope=tree.scope, reopens_run_id=tree.top.RunID)
    if tree.refusal:
        return plan
    plan.can_resume, plan.resume_problem = tree.resume_problem is None, tree.resume_problem
    plan.items = [ItemPlan(path=p.path, job_key=p.job_key, what=_what(p)) for p in tree.picks]
    plan.steps_to_decide = _steps_to_decide(tree)
    plan.steps_finished = sum(len(p.record.ended_steps()) for p in tree.picks if p.record)
    plan.summary = _tree_summary(tree, plan)
    if plan.can_resume:
        plan.value_levels = rerun_values.levels_for(db, tree)
        plan.kept_jobs = rerun_values.kept_jobs(db, tree)
        plan.values_note = rerun_values.note_for(tree)
    return plan


def _what(pick: "rerun_tree.Pick") -> str:
    if pick.action == reopen.ROUTE:
        return "is opened again, to run the item chosen"
    if pick.action == reopen.BYPASS:
        return "is bypassed: it counts as succeeded and does not run"
    if pick.action == reopen.DONT_RUN:
        return "is not run: it ends Skipped, and what waits for its success does not run"
    if pick.goes_on():
        return f"goes on from attempt {pick.attempt}"
    return "runs again from the beginning"


def _steps_to_decide(tree: "rerun_tree.TreePlan") -> List[StepToDecide]:
    found = []
    for pick in tree.picks:
        step = _step_to_decide(pick.record)
        if step is not None:
            step.path = pick.path
            found.append(step)
    return found


def _tree_summary(tree: "rerun_tree.TreePlan", plan: RerunPlan) -> str:
    what = f"'{tree.scope}'" if tree.scope else f"'{tree.top.JobKey}'"
    jobs = [p for p in tree.picks if p.action != reopen.ROUTE]
    text = f"Resume picks up {what} where it stopped: {len(jobs)} item{'s' if len(jobs) != 1 else ''} run again"
    if plan.steps_to_decide:
        return f"{text}. {len(plan.steps_to_decide)} failed step{'s' if len(plan.steps_to_decide) != 1 else ''} need your decision first."
    return text + "."


def changes_for(db: Session, run: JobRun, record: ControlRecord) -> List[ValueChange]:
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


def make_advanced_plan(db: Session, run: JobRun, shortcut: Optional[str] = None, chosen: Optional[List[str]] = None,
                       chosen_as: str = "resume", explicit: Optional[Dict[str, str]] = None,
                       ignore: Optional[Dict[str, List[str]]] = None, reset_counts: bool = False) -> RerunPlan:
    """What Advanced can do for a workflow run: the items to choose from, and, once some are named, what they would get."""
    if not _in_a_workflow(run):
        return RerunPlan(run_id=run.RunID, job_key=run.JobKey, attempt=run.Attempt, can_restart=False, can_resume=False,
                         advanced=True, refusal="Advanced is for workflow runs; a job on its own is run again with Resume or Restart.")
    tree = rerun_tree.make_advanced_plan(db, run)
    plan = RerunPlan(run_id=run.RunID, job_key=run.JobKey, attempt=run.Attempt, can_restart=tree.refusal is None,
                     can_resume=False, refusal=tree.refusal, scope=tree.scope, reopens_run_id=tree.top.RunID, advanced=True)
    if tree.refusal:
        return plan
    plan.choices = [ItemChoice(**vars(c)) for c in tree.choices]
    if not (shortcut or chosen or explicit):
        return plan
    items, plan.items_problem = rerun_advanced.named_items(db, tree, shortcut, chosen or [], chosen_as, explicit or {})
    if plan.items_problem:
        return plan
    tree = rerun_tree.make_advanced_plan(db, run, items)
    plan.named_items, plan.items_problem = items, tree.resume_problem or rerun_advanced.waits_problem(tree, items, ignore or {})
    plan.ignored, plan.reset_counts = (ignore or {}), reset_counts
    plan.items = [ItemPlan(path=p.path, job_key=p.job_key, what=_what(p)) for p in tree.picks]
    plan.steps_to_decide = _steps_to_decide(tree)
    plan.steps_finished = sum(len(p.record.ended_steps()) for p in tree.picks if p.record)
    plan.can_resume = plan.items_problem is None
    if plan.can_resume:
        plan.value_levels = rerun_values.levels_for(db, tree)
        plan.kept_jobs = rerun_values.kept_jobs(db, tree)
        plan.values_note = rerun_values.note_for(tree)
    return plan


@router.get("/{run_id}/rerun-plan", response_model=RerunPlan)
def rerun_plan(run_id: str, advanced: bool = False, shortcut: Optional[str] = None, chosen: List[str] = Query([]),
               chosen_as: str = "resume", db: Session = Depends(get_db)):
    """
    What Rerun can do for this run: whether Resume is possible, and a step the operator must decide on. With
    advanced=true, a workflow run's items to choose from; with chosen (and a shortcut), what they would get.
    """
    run = _find(db, run_id)
    return make_advanced_plan(db, run, shortcut, chosen, chosen_as) if advanced else make_plan(db, run)


@router.post("/{run_id}/rerun", response_model=LaunchOut, status_code=status.HTTP_202_ACCEPTED)
def rerun(run_id: str, payload: RerunRequest, request: Request, db: Session = Depends(get_db)):
    """Starts the next attempt of a failed job, at once; follow it with GET /api/v1/runs/{run_id} of the answer's run_id."""
    run = _find(db, run_id)
    kind = payload.kind.strip().lower()
    if kind not in ("resume", "restart", "advanced"):
        raise HTTPException(422, "Choose resume, restart or advanced.")
    plan = (make_advanced_plan(db, run, payload.shortcut, payload.chosen, payload.chosen_as, payload.items,
                                payload.ignore, payload.reset_counts)
            if kind == "advanced" else make_plan(db, run))
    if plan.refusal:
        raise HTTPException(409, plan.refusal)
    level = payload.log_level.strip().upper()
    try:
        job_log.level_number(level)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if kind == "advanced":
        return _reopen_advanced(db, request, plan, level, payload)
    if _in_a_workflow(run):
        return _reopen(db, request, plan, kind, level, payload)
    extra = ["--run-number", str(run.RunNumber), "--attempt", str(run.Attempt + 1)]
    edits: List[str] = []
    if kind == "resume":
        extra += _resume_arguments(plan, payload.unknown_step)
        arguments, edits = _value_arguments(db, run, payload)
        extra += arguments
    elif payload.refresh_values or payload.edits:
        raise HTTPException(422, "Values can be refreshed or edited for a Resume; a restart reads them all again.")
    launch = start_runner(request, run.JobKey, run.SchedulerInstanceID, level, run.BusinessDate, extra,
                          scheduler=run.SchedulerName or "AutoApp UI")
    _record(db, plan, run.JobKey, kind, launch.run_id, run.Attempt, {"": payload.unknown_step or ""}, payload.refresh_values, edits)
    return launch


def _record(db: Session, plan: RerunPlan, job_key: str, kind: str, run_id: str, number: int, chosen: Dict[str, str],
            refreshed: bool, edits: List[str], chosen_at=None) -> None:
    """The restart record and the Audit Log row for a request that has been started (nothing is written for a refused one)."""
    kind = kind.upper()
    details = run_restarts.details_for(plan, kind, chosen, refreshed, edits)
    said = [run_restarts.headline(plan, job_key, kind, details)] + ([f"{i}." for i in details["items"]] if kind == "RESUME" else [])
    run_restarts.record(db, job_key, run_id, kind, number, plan.scope or "", details, said, chosen_at)


def _reopen(db: Session, request: Request, plan: RerunPlan, kind: str, level: str, payload: RerunRequest) -> LaunchOut:
    """Starts the workflow runner on the run at the top, reopened: the same run ID, the next go at it."""
    top = _find(db, plan.reopens_run_id)
    values, edits = _workflow_values(db, top, plan, kind, payload)
    extra = ["--run-number", str(top.RunNumber), "--attempt", str(top.Attempt), "--reopen", kind]
    if plan.scope:
        extra += ["--reopen-scope", plan.scope]
    decisions: Dict[str, str] = {}
    if kind == "resume":
        if not plan.can_resume:
            raise HTTPException(409, plan.resume_problem)
        decisions = _decisions(plan, payload.decisions)
        extra += ["--rerun-decisions", json.dumps(decisions)] if decisions else []
        extra += values
    number = run_restarts.next_number(db, top.RunID)
    launch = start_runner(request, top.JobKey, top.SchedulerInstanceID, level, top.BusinessDate, extra,
                          scheduler=top.SchedulerName or "AutoApp UI", run_id=top.RunID)
    _record(db, plan, top.JobKey, kind, top.RunID, number, decisions, payload.refresh_values, edits)
    return launch


def _reopen_advanced(db: Session, request: Request, plan: RerunPlan, level: str, payload: RerunRequest) -> LaunchOut:
    """Starts the workflow runner on the run at the top, reopened with an action for each item named."""
    if plan.items_problem:
        raise HTTPException(422 if not plan.named_items else 409, plan.items_problem)
    if not plan.named_items:
        raise HTTPException(422, "Choose at least one item to run again.")
    top = _find(db, plan.reopens_run_id)
    decisions = _decisions(plan, payload.decisions)
    values, edits = _workflow_values(db, top, plan, "advanced", payload)
    extra = ["--run-number", str(top.RunNumber), "--attempt", str(top.Attempt), "--reopen", reopen.ADVANCED,
             "--reopen-items", json.dumps(plan.named_items)] + values
    extra += ["--ignore-waits", json.dumps(plan.ignored)] if plan.ignored else []
    extra += ["--reset-counts"] if plan.reset_counts else []
    extra += ["--rerun-decisions", json.dumps(decisions)] if decisions else []
    number = run_restarts.next_number(db, top.RunID)
    chosen_at = utcnow()                # before the runner starts: the Reactions it counts afterwards come after a reset
    launch = start_runner(request, top.JobKey, top.SchedulerInstanceID, level, top.BusinessDate, extra,
                          scheduler=top.SchedulerName or "AutoApp UI", run_id=top.RunID)
    _record(db, plan, top.JobKey, "advanced", top.RunID, number, decisions, payload.refresh_values, edits, chosen_at)
    return launch


def _decisions(plan: RerunPlan, chosen: Dict[str, str]) -> Dict[str, str]:
    """The choice for every failed step of unknown effect, or a refusal that names the ones missing."""
    missing = [s for s in plan.steps_to_decide if chosen.get(s.path) not in (RUN_AGAIN, COUNT_AS_DONE)]
    if missing:
        names = ", ".join(f"step {s.step} '{s.title}' of '{s.path}'" for s in missing)
        raise HTTPException(422, f"{names} may or may not have changed something before failing. For each, choose to run it "
                                 f"again or to count it as done, or restart from the beginning.")
    return {s.path: chosen[s.path] for s in plan.steps_to_decide}


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


def _value_arguments(db: Session, run: JobRun, payload: RerunRequest):
    """Refresh or edit the earlier attempt's values; an edit is recorded in the Audit Log, by name and never a secret."""
    arguments = ["--refresh-values"] if payload.refresh_values else []
    if not payload.edits:
        return arguments, []
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
    return arguments + ["--edit-values", json.dumps(payload.edits)], changes


def _workflow_values(db: Session, top: JobRun, plan: RerunPlan, kind: str, payload: RerunRequest):
    """Refresh or edit the values of a workflow's Resume; edits are checked, then recorded in the Audit Log. Returns (arguments, edits made)."""
    wanted = payload.refresh_values or payload.level_edits or payload.job_edits or payload.edits
    if not wanted:
        return [], []
    if kind == "restart":
        raise HTTPException(422, "Values can be refreshed or edited for a Resume; a restart reads them all again.")
    if payload.edits:
        raise HTTPException(422, "Use level_edits and job_edits to change the values of a workflow's Resume.")
    if not plan.can_resume:
        raise HTTPException(409, plan.resume_problem)
    run = _find(db, plan.run_id)
    tree = (rerun_tree.make_advanced_plan(db, run, plan.named_items) if kind == "advanced"
            else rerun_tree.make_tree_plan(db, run))
    choices, problems = rerun_values.check_edits(tree, payload.level_edits, payload.job_edits)
    if problems:
        raise HTTPException(422, " ".join(problems))
    arguments, said = (["--refresh-values"] if payload.refresh_values else []), []
    if payload.level_edits or payload.job_edits:
        said = rerun_values.audit(db, tree, choices)
        arguments += ["--edit-values", json.dumps(choices)]
    return arguments, said

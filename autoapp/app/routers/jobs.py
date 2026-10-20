from datetime import date, datetime
from typing import Dict, Any, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_db
from app import embed_store, rename_store, tag_store
from app.workflow_errors import WorkflowError
from app.job_store import JobStoreError, apply_job, delete_job, describe_job, inherited_variables, save_job
from app.models import Job, JobRun, JobStep, JobStepParameter, Operation, Variable
from app.schemas import (
    FieldPreview, JobCheckResult, JobDetail, JobInitRequest, JobInitResponse, JobPreview, JobSave, JobSaveResult,
    JobStepPayloadSchema, JobSummary, LastRun, MakeShared, RenameFacts
)
from engine.step_catalog import ENDPOINT_SUFFIX
from engine.handlers import get_handler
from engine import step_tree, workflow_vars
from engine.handlers.flow import BRANCHES
from engine.preflight import prepare_job
from engine.scope_engine import ScopeResolutionEngine
from engine.step_params import preview_step, resolve_step

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs"])

MAX_RESULTS = 500

# Recorded as who made a change. There are no user accounts yet.
EDITOR_NAME = "web interface"


def workflow_context(db: Session, workflow: Optional[str], use: Optional[str], job_key: Optional[str] = None):
    """
    What a workflow gives the job it runs as `use` (engine.workflow_vars.Levels), or None when no workflow is
    named, so the job is checked on its own. job_key: the job the use must run, when known.
    """
    if not workflow and not use:
        return None
    if not (workflow and use):
        raise HTTPException(status_code=422, detail="Give both the workflow and the use in it, or neither.")
    found = workflow_vars.for_use(db, workflow, use)
    if found is None or (job_key is not None and found[1].job.JobKey != job_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Workflow '{workflow}' has no use '{use}' of job '{job_key or 'this job'}'.")
    return found[0]


def checked_as(workflow: Optional[str], use: Optional[str]) -> Optional[str]:
    return f"workflow '{workflow}', as '{use}'" if workflow and use else None


def job_problems(db: Session, job: Job, environment: Optional[Dict[str, str]] = None,
                 warnings: Optional[List[str]] = None, workflow=None) -> List[str]:
    """
    Everything that would stop the job from running, as the runner would report it. Runs nothing.
    environment: what the scheduler will set when it runs the job, if known (a WLA job's parameters).
    warnings: given a list, what is worth knowing but does not stop the job is added to it.
    workflow: for a job used in a workflow, what the workflow gives it (engine.workflow_vars.Levels).
    """
    if job.JobType == "WORKFLOW":
        from app.workflow_store import workflow_problems
        return workflow_problems(db, job, warnings)
    problems = []
    if not job.IsActive:
        problems.append(f"Job '{job.JobKey}' is disabled.")
    engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="CHECK", environment=environment,
                                   workflow=workflow)
    engine.build_context()
    return problems + prepare_job(db, job, engine, warnings)[1]


@router.get("", response_model=List[JobSummary])
def list_jobs(
    job_key: Optional[str] = Query(None, description="Part of a JobKey"),
    description: Optional[str] = Query(None, description="Part of the description"),
    active: Optional[bool] = Query(None, description="true for enabled jobs only, false for disabled only"),
    endpoint: Optional[str] = Query(None, description="Part of the name of an endpoint one of the job's steps uses"),
    tag: Optional[str] = Query(None, description="Part of a tag's path: jobs carrying that tag, or one under it"),
    job_type: Optional[str] = Query(None, description="STEPS for jobs made of steps, WORKFLOW for workflows"),
    limit: int = Query(MAX_RESULTS, ge=1, le=MAX_RESULTS),
    db: Session = Depends(get_db),
):
    """
    The job search. Text criteria ignore case and match anywhere in the field.
    Jobs are returned in name order, each with its step count, the endpoints it
    uses and its most recent run.
    """
    endpoint_param = JobStepParameter.ParamName.like(f"%{ENDPOINT_SUFFIX}")

    query = db.query(Job).filter(Job.Owner_MasterObject_id.is_(None))      # embedded jobs show in their workflow
    if job_type:
        query = query.filter(Job.JobType == job_type.strip().upper())
    if job_key:
        query = query.filter(Job.JobKey.ilike(f"%{job_key}%"))
    if description:
        query = query.filter(Job.Description.ilike(f"%{description}%"))
    if active is not None:
        query = query.filter(Job.IsActive.is_(active))
    if endpoint:
        uses_endpoint = (
            db.query(JobStep.id)
            .join(JobStepParameter, JobStepParameter.job_step_id == JobStep.id)
            .filter(JobStep.job_id == Job.MasterObject_id, endpoint_param,
                    JobStepParameter.ParamValue.ilike(f"%{endpoint}%"))
        )
        query = query.filter(uses_endpoint.exists())
    if tag and tag.strip():
        query = query.filter(tag_store.carrying(db, tag))
    jobs = query.order_by(func.lower(Job.JobKey), Job.JobKey).limit(limit).all()
    if not jobs:
        return []

    job_ids = [job.MasterObject_id for job in jobs]
    job_keys = [job.JobKey for job in jobs]

    # Steps and the endpoints they name, for all the jobs found, in two queries
    step_counts = {job_id: [0, 0] for job_id in job_ids}        # [enabled, disabled]
    for job_id, is_active in db.query(JobStep.job_id, JobStep.IsActive).filter(JobStep.job_id.in_(job_ids)):
        step_counts[job_id][0 if is_active else 1] += 1

    endpoints = {job_id: set() for job_id in job_ids}
    named = (
        db.query(JobStep.job_id, JobStepParameter.ParamValue)
        .join(JobStepParameter, JobStepParameter.job_step_id == JobStep.id)
        .filter(JobStep.job_id.in_(job_ids), endpoint_param)
    )
    for job_id, endpoint_name in named:
        if endpoint_name:
            endpoints[job_id].add(endpoint_name)

    # The most recent run of each job: the one with the latest start time
    latest = (
        db.query(JobRun.JobKey, func.max(JobRun.StartedDateTime).label("started"))
        .filter(JobRun.JobKey.in_(job_keys))
        .group_by(JobRun.JobKey)
        .subquery()
    )
    last_runs = {}
    recent = db.query(JobRun).join(
        latest, (JobRun.JobKey == latest.c.JobKey) & (JobRun.StartedDateTime == latest.c.started))
    for run in recent.order_by(JobRun.id):
        last_runs[run.JobKey] = LastRun(
            status=run.Status, started=run.StartedDateTime, ended=run.EndedDateTime,
            instance_id=run.SchedulerInstanceID, run_number=run.RunNumber, error=run.ErrorMessage,
        )

    # Each job found is put through the pre-run check, so the search shows at a glance which would run
    problem_counts = {job.MasterObject_id: len(job_problems(db, job)) for job in jobs}

    return [
        JobSummary(
            job_key=job.JobKey,
            job_type=job.JobType or "STEPS",
            item_count=len(job.items) if job.JobType == "WORKFLOW" else 0,
            description=job.Description,
            active=bool(job.IsActive),
            step_count=step_counts[job.MasterObject_id][0],
            disabled_step_count=step_counts[job.MasterObject_id][1],
            endpoints=sorted(endpoints[job.MasterObject_id]),
            ready=problem_counts[job.MasterObject_id] == 0,
            problem_count=problem_counts[job.MasterObject_id],
            last_run=last_runs.get(job.JobKey),
            tags=tag_store.paths_on(job),
            modified=job.ModifiedDateTime or job.CreatedDateTime,
            modified_by=job.ModifiedBy or job.CreatedBy,
        )
        for job in jobs
    ]


@router.post("/init", response_model=JobInitResponse, status_code=status.HTTP_200_OK)
def initialize_job(payload: JobInitRequest, db: Session = Depends(get_db)):
    """Resolves the job's variable scope and returns its steps with parameters interpolated."""

    # 1. Lookup Job by its JobKey
    job = db.query(Job).filter(Job.JobKey == payload.job_key).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No job with JobKey '{payload.job_key}' exists."
        )

    # 2. Instantiate and evaluate Scope Engine
    engine = ScopeResolutionEngine(
        db=db,
        job_id=job.MasterObject_id,
        instance_id=payload.instance_id
    )
    resolved_vars = engine.build_context()

    # 3. Fetch steps and interpolate parameter text
    job_steps = (
        db.query(JobStep)
        .filter(JobStep.job_id == job.MasterObject_id)
        .order_by(JobStep.StepOrder)
        .all()
    )

    compiled_steps: List[JobStepPayloadSchema] = []
    for step in job_steps:
        step_type = step.step_type.HandlerClass if step.step_type else None
        try:
            handler_cls = get_handler(step_type) if step_type else None
        except ValueError:
            handler_cls = None  # no handler on this server; parameters are still interpolated

        try:
            resolved = resolve_step(step, handler_cls, engine, db)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        compiled_steps.append(
            JobStepPayloadSchema(
                step_number=step.StepOrder,
                step_type=step.step_type.TypeName if step.step_type else "GENERIC",
                handler_class=step_type or "BaseHandler",
                title=step.Title,
                parameters=resolved.params,
                source_endpoint_id=resolved.source_endpoint_id,
                dest_endpoint_id=resolved.dest_endpoint_id
            )
        )

    working_folder = engine.working_folder or ""

    return JobInitResponse(
        status="SUCCESS",
        execution_instance_id=payload.instance_id,
        job_id=job.MasterObject_id,
        working_folder=working_folder,
        variables=resolved_vars,
        steps=compiled_steps
    )


@router.get("/{job_key}", response_model=JobDetail)
def get_job(job_key: str, db: Session = Depends(get_db)):
    """One job with all its steps, enabled or not, in order, and each step's parameters as stored."""
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No job with JobKey '{job_key}' exists.")
    return describe_job(job)


def _save(db: Session, payload: JobSave, existing_key: Optional[str]) -> JobSaveResult:
    try:
        job, changes = save_job(db, payload, existing_key, who=EDITOR_NAME)
    except JobStoreError as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=str(e))
    problems = job_problems(db, job)
    return JobSaveResult(job=describe_job(job), valid=not problems, problems=problems, changes=changes)


@router.post("/preview", response_model=JobPreview)
def preview_job(payload: JobSave, existing_key: Optional[str] = Query(
        None, description="The key of the job being edited; leave out for a job not yet saved"),
        scheduler: Optional[str] = Query(None, description="With wla_job: the scheduler the job is edited from"),
        wla_job: Optional[str] = Query(None, description="The scheduler's job, whose parameters it will run with"),
        workflow: Optional[str] = Query(None, description="With use: check it as this workflow runs the job"),
        use: Optional[str] = Query(None, description="With workflow: the name of the job's use in it"),
        db: Session = Depends(get_db)):
    """
    What a job would resolve to if it were saved as submitted: each step's parameters
    with their placeholders and file locations worked out, and whether it would run.
    Nothing is saved. The job editor calls this as its form is changed.
    """
    MASK = "********"
    if existing_key is None and not payload.job_key.strip():
        payload = payload.model_copy(update={"job_key": "UNNAMED-JOB"})     # so a new job can be previewed before it is named
    environment, scheduler_warnings = wla_environment(db, scheduler, wla_job)
    in_workflow = workflow_context(db, workflow, use)
    try:
        job, _ = apply_job(db, payload, existing_key, who=EDITOR_NAME)
        secrets = sorted({value for (value,) in db.query(Variable.VarValue).filter(Variable.IsSecret.is_(True)) if value},
                         key=len, reverse=True)

        def safe(text: Optional[str]) -> Optional[str]:
            for secret in secrets:
                text = text.replace(secret, MASK) if text else text
            return text

        check_warnings: List[str] = []
        problems = [safe(problem) for problem in job_problems(db, job, environment, check_warnings, workflow=in_workflow)]
        engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="PREVIEW", environment=environment,
                                       workflow=in_workflow)
        engine.build_context()
        steps = []
        for node in step_tree.walk(step_tree.build(job.steps)):
            try:
                handler_cls = get_handler(node.code)
            except ValueError:
                handler_cls = None
            fields = {name: FieldPreview(resolved=safe(None if resolved is None else str(resolved)), error=safe(error))
                      for name, (resolved, error) in preview_step(node.step, handler_cls, engine, db).items()}
            # A condition comparing text with a number is pointed out under the condition itself
            mine = [safe(w[len(node.name) + 2:]) for w in check_warnings if w.startswith(node.name + ": ")]
            if mine and "Condition" in fields:
                fields["Condition"].warnings = mine
            steps.append(fields)
        # Tags that disagree about a variable the job does not use: worth saying, but nothing stops
        warnings = scheduler_warnings + [safe(w) for w in check_warnings] + [
            w for w in tag_store.job_tag_warnings(db, job) if not any(w in problem for problem in problems)]
        return JobPreview(valid=not problems, checked_as=checked_as(workflow, use), problems=problems,
                          warnings=warnings, steps=steps,
                          tags=tag_store.paths_on(job), inherited_variables=inherited_variables(db, job))
    except JobStoreError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    finally:
        db.rollback()       # a preview changes nothing


@router.post("", response_model=JobSaveResult, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobSave, db: Session = Depends(get_db)):
    """
    Creates a job with its steps. The job is saved even if the pre-run check finds
    problems with it; they are returned, and the job will not run until they are fixed.
    """
    return _save(db, payload, existing_key=None)


@router.put("/{job_key}", response_model=JobSaveResult)
def update_job(job_key: str, payload: JobSave, db: Session = Depends(get_db)):
    """
    Saves a whole job: its own fields and all its steps, in the order they should run.
    A step sent with its id is changed in place; one without an id is new; one left
    out is deleted. To rename the job, send a different job_key in the body.
    """
    return _save(db, payload, existing_key=job_key)


@router.get("/{job_key}/rename-facts", response_model=RenameFacts)
def rename_facts(job_key: str, db: Session = Depends(get_db)):
    """What renaming the job would leave behind: run history, scheduler definitions, the working folder."""
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No job with JobKey '{job_key}' exists.")
    return rename_store.rename_facts(db, job)


@router.post("/{job_key}/make-shared", response_model=JobSaveResult)
def make_shared(job_key: str, payload: MakeShared, db: Session = Depends(get_db)):
    """Frees an embedded job (or workflow, with what is embedded in it) from its workflow, under a key of your choosing."""
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No job with JobKey '{job_key}' exists.")
    try:
        embed_store.make_shared(db, job, payload.job_key, payload.move_working_folder, EDITOR_NAME)
        db.commit()
    except WorkflowError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    db.refresh(job)
    return JobSaveResult(job=describe_job(job), valid=not job_problems(db, job), problems=job_problems(db, job),
                         changes=[f"Made '{job.JobKey}' a job of its own."])


@router.post("/{job_key}/items/{item_name}/embedded-copy", response_model=JobSaveResult)
def embedded_copy(job_key: str, item_name: str, db: Session = Depends(get_db)):
    """Makes the item run an embedded copy of the shared job it runs now, for when this use needs to differ."""
    workflow = db.query(Job).filter(Job.JobKey == job_key, Job.JobType == "WORKFLOW").first()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No workflow with JobKey '{job_key}' exists.")
    try:
        copy = embed_store.embed_copy(db, workflow, item_name, EDITOR_NAME)
        db.commit()
    except WorkflowError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    db.refresh(workflow)
    return JobSaveResult(job=describe_job(workflow), valid=not job_problems(db, workflow), problems=job_problems(db, workflow),
                         changes=[f"'{item_name}' now runs an embedded copy, '{copy.JobKey}'."])


@router.delete("/{job_key}", status_code=status.HTTP_204_NO_CONTENT)
def remove_job(job_key: str, db: Session = Depends(get_db)):
    """Deletes a job that has never run. One with run history is refused (409): disable it instead."""
    try:
        delete_job(db, job_key, who=EDITOR_NAME)
    except JobStoreError as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=str(e))


@router.get("/{job_key}/check", response_model=JobCheckResult, response_model_exclude_none=True)
def check_job(job_key: str,
              scheduler: Optional[str] = Query(None, description="With wla_job: the scheduler that runs the job"),
              wla_job: Optional[str] = Query(None, description="The scheduler's job, whose parameters it runs with"),
              workflow: Optional[str] = Query(None, description=(
                  "With use: check it as this workflow runs it, with the workflow's variables and the use's")),
              use: Optional[str] = Query(None, description="With workflow: the name of the job's use in it"),
              db: Session = Depends(get_db)):
    """
    Checks a job without running it: every active step against its step type,
    every placeholder, every file location. Returns each problem found, exactly
    as the runner would report it. The same check is made whenever the job runs.
    """
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No job with JobKey '{job_key}' exists.")

    environment, warnings = wla_environment(db, scheduler, wla_job)
    in_workflow = workflow_context(db, workflow, use, job_key)
    # A workflow's warnings name the jobs in it that are disabled or would fail: it runs all the same
    problems = job_problems(db, job, environment, warnings if job.JobType == "WORKFLOW" else None, workflow=in_workflow)
    return JobCheckResult(job_key=job_key, valid=not problems, checked_as=checked_as(workflow, use),
                          problems=problems, warnings=warnings)


def wla_environment(db: Session, scheduler: Optional[str], wla_job: Optional[str]):
    """
    The environment a scheduler's job will run with (its parameters, secrets as ********), and
    any warning about reading it. None, as on the server otherwise, when no WLA job is named
    or it cannot be read; ${ENV:...} is then left for the run.
    """
    if not (scheduler and wla_job):
        return None, []
    from app.connectors import ConnectorError
    from app.routers.schedulers import read_wla_job
    try:
        return read_wla_job(db, scheduler, wla_job).environment(), []
    except ConnectorError as e:
        return None, [f"The scheduler's parameters for this job could not be read, so they are not checked: {e}"]
    except HTTPException as e:
        return None, [str(e.detail)]


# --- A job's summary, for a scheduler to show in its own interface -----------------------------

class SummaryStep(BaseModel):
    order: int
    title: Optional[str] = None
    step_type: str = Field(..., description="The step type's name, e.g. Copy Files")
    active: bool
    line: str = Field(..., description="Where it takes files from and puts them, e.g. LEGAL_EXTRACTS → incoming")


class SummaryRun(BaseModel):
    run_id: str
    instance_id: str
    run_number: int
    scheduler: Optional[str] = None
    business_date: Optional[date] = None
    status: str
    started: Optional[datetime] = None
    ended: Optional[datetime] = None
    error: Optional[str] = None
    operations: int
    failed_operations: int
    links: Dict[str, str] = Field(..., description="log: its job log; operations: the files it handled")


class JobSummaryForHost(BaseModel):
    """What a scheduler needs to show a AutoApp job in its own interface. Links are full addresses."""
    job_key: str
    description: Optional[str] = None
    active: bool
    ready: bool = Field(..., description="Whether the pre-run check finds nothing to stop it")
    problems: List[str]
    warnings: List[str] = []
    steps: List[SummaryStep]
    endpoints: List[str]
    tags: List[str]
    run: Optional[SummaryRun] = Field(None, description="The run asked for with instance_id, or else the latest")
    modified: Optional[datetime] = None
    modified_by: Optional[str] = None
    links: Dict[str, str] = Field(..., description="editor, operations and history: AutoApp's pages for the job")


def _step_line(step: JobStep) -> str:
    """Where a step takes files from and puts them: its file locations in order, by endpoint or path."""
    try:
        handler_cls = get_handler(step.step_type.HandlerClass)
    except ValueError:
        return ""
    stored = {p.ParamName: p.ParamValue for p in step.parameters}
    places = [stored.get(name + ENDPOINT_SUFFIX) or stored.get(name) for name in handler_cls.path_params()]
    return "  →  ".join(p for p in places if p)


@router.get("/{job_key}/summary", response_model=JobSummaryForHost)
def job_summary(job_key: str, request: Request,
                instance_id: Optional[str] = Query(None, description="One run to describe, by the scheduler's instance ID"),
                scheduler: Optional[str] = Query(None, description="With wla_job: the scheduler that runs the job"),
                wla_job: Optional[str] = Query(None, description="The scheduler's job, whose parameters it runs with"),
                db: Session = Depends(get_db)):
    """
    A job described for a scheduler to show in its own interface: whether it would
    run, its steps in a line each, the endpoints and tags, a run, and links to
    AutoApp's pages. A small page showing the same is ui/summary.html. See docs/INTEGRATION.md.
    """
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No job with JobKey '{job_key}' exists.")
    environment, warnings = wla_environment(db, scheduler, wla_job)
    problems = job_problems(db, job, environment)
    base = str(request.base_url).rstrip("/") + "/ui/"

    def address(page: str, **params) -> str:
        return base + page + "?" + urlencode(params)

    # Every step, nested ones too, in the order the job lists them; an If's Then, ElseIf and Else are part of it
    steps = [s for s in step_tree.in_order(job.steps) if s.step_type.HandlerClass not in BRANCHES]
    endpoints = sorted({p.ParamValue for s in steps for p in s.parameters
                        if p.ParamName.endswith(ENDPOINT_SUFFIX) and p.ParamValue}, key=str.lower)

    runs = db.query(JobRun).filter(JobRun.JobKey == job.JobKey)
    if instance_id:
        runs = runs.filter(JobRun.SchedulerInstanceID == instance_id)
    run = runs.order_by(JobRun.StartedDateTime.desc(), JobRun.id.desc()).first()
    run_out = None
    if run:
        total, failed = (db.query(func.count(Operation.id), func.sum(case((Operation.OpStatus == "FAILED", 1), else_=0)))
                         .filter(Operation.JobRun_id == run.id).one())
        run_out = SummaryRun(
            run_id=run.RunID, instance_id=run.SchedulerInstanceID, run_number=run.RunNumber,
            scheduler=run.SchedulerName, business_date=run.BusinessDate, status=run.Status,
            started=run.StartedDateTime, ended=run.EndedDateTime, error=run.ErrorMessage,
            operations=total or 0, failed_operations=int(failed or 0),
            links={"log": address("log.html", run=run.RunID),
                   "operations": address("operations.html", job_key=job.JobKey, instance_id=run.SchedulerInstanceID)},
        )

    editor = {"key": job.JobKey}
    if scheduler and wla_job:
        editor.update(scheduler=scheduler, wla_job=wla_job)
    return JobSummaryForHost(
        job_key=job.JobKey, description=job.Description, active=bool(job.IsActive), ready=not problems,
        problems=problems, warnings=warnings,
        steps=[SummaryStep(order=position, title=s.Title, step_type=s.step_type.TypeName, active=bool(s.IsActive),
                           line=_step_line(s)) for position, s in enumerate(steps, start=1)],
        endpoints=endpoints, tags=tag_store.paths_on(job), run=run_out,
        modified=job.ModifiedDateTime or job.CreatedDateTime, modified_by=job.ModifiedBy or job.CreatedBy,
        links={"editor": address("job.html", **editor), "operations": address("operations.html", job_key=job.JobKey),
               "history": address("history.html", job_key=job.JobKey)},
    )

"""
The condition box's helpers (docs/WORKFLOWS_PHASE4.md): checking a workflow condition as it is
typed, and Explain now, against one of the workflow's past runs.

    GET  /api/v1/conditions/outputs     what every job in a workflow offers to conditions
    GET  /api/v1/conditions/outside-outputs   what files at an endpoint offer, and the time (Now)
    POST /api/v1/conditions/check       problems and warnings, and the jobs the condition names
    POST /api/v1/conditions/explain     the condition worked out with a past run's values, part by part

Nothing is saved.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from core.models import Job, JobRun, WorkflowRunItem
from core import conditions, workflow_conditions

router = APIRouter(prefix="/api/v1/conditions", tags=["Conditions"])


class OutputOut(BaseModel):
    name: str
    data_type: str = Field(..., description="NUMBER, STRING or BOOLEAN (True and False, which are 1 and 0)")
    description: str


class ConditionCheckRequest(BaseModel):
    condition: str
    names: List[str] = Field(default_factory=list, description="The names of the jobs in the workflow, as on screen")
    workflow_key: Optional[str] = Field(None, description="The workflow, if saved, so its ${...} variables are looked up")
    outside: Dict[str, str] = Field(default_factory=dict, description=(
        "The job's own prerequisites outside the workflow, by the name conditions use for each: "
        "OTHER_JOB, ENDPOINT or TIME"))


class ConditionCheckResult(BaseModel):
    problems: List[str]
    warnings: List[str]
    named: List[str] = Field(default_factory=list, description="The jobs the condition names, in order")


class ExplainRequest(BaseModel):
    condition: str
    run_id: str = Field(..., description="A run of the workflow, whose values the condition is worked out with")


class ExplainResult(BaseModel):
    result: str = Field(..., description="TRUE, FALSE or UNKNOWN")
    values: Dict[str, Any]
    explain: Dict[str, Any]


@router.get("/outputs", response_model=List[OutputOut])
def list_outputs():
    """What %{Name.Output} can read of every job in a workflow, in the order the condition box lists them."""
    return [OutputOut(name=name, data_type="BOOLEAN" if name in workflow_conditions.BOOLEANS else kind, description=words)
            for name, (kind, words) in workflow_conditions.OUTPUTS.items()]


class OutsideOutputsOut(BaseModel):
    endpoint: List[OutputOut] = Field(..., description="What files at an endpoint offer: %{INBOUND.FileCount}")
    now: List[OutputOut] = Field(..., description="The time: %{Now.Time}")


@router.get("/outside-outputs", response_model=OutsideOutputsOut)
def list_outside_outputs():
    """What a prerequisite on files, and the time, offers to conditions. A job in another workflow offers /outputs."""
    return OutsideOutputsOut(
        endpoint=[OutputOut(name=name, data_type="NUMBER", description=words)
                  for name, words in workflow_conditions.FILE_OUTPUTS.items()],
        now=[OutputOut(name=name, data_type="STRING", description=words) for name, words in workflow_conditions.NOW_OUTPUTS.items()])


def _variable(db: Session, workflow_key: Optional[str]):
    """How the workflow's ${...} are looked up, or None when it is not saved yet."""
    workflow = db.query(Job).filter(Job.JobKey == workflow_key).first() if workflow_key else None
    if workflow is None:
        return None
    from core.scope_engine import ScopeResolutionEngine
    engine = ScopeResolutionEngine(db=db, job_id=workflow.MasterObject_id, instance_id="CHECK")
    engine.build_context()
    return engine.interpolate


@router.post("/check", response_model=ConditionCheckResult)
def check_condition(request: ConditionCheckRequest, db: Session = Depends(get_db)):
    """A workflow condition as typed: what is wrong with it, what is worth knowing, and the jobs it names."""
    if not request.condition.strip():
        return ConditionCheckResult(problems=["The condition is empty."], warnings=[])
    problems, warnings = workflow_conditions.check(request.condition, request.names, _variable(db, request.workflow_key),
                                                   request.outside)
    try:
        named = workflow_conditions.named_jobs(request.condition, list(request.outside))
    except ValueError:
        named = []
    return ConditionCheckResult(problems=problems, warnings=warnings, named=named)


def run_values(db: Session, run: JobRun) -> Dict[str, Any]:
    """Every %{Name.Output} of a workflow run, as it ended (or stands, for one still going)."""
    values: Dict[str, Any] = {}
    for row in db.query(WorkflowRunItem).filter(WorkflowRunItem.WorkflowRun_id == run.id):
        child = row.child_run
        values.update(workflow_conditions.item_values(
            row.ItemName, row.Status, row.ReturnCode, row.Reason, child.FileCount if child else None,
            child.Bytes if child else None, row.StartedDateTime, row.EndedDateTime))
    return values


@router.post("/explain", response_model=ExplainResult)
def explain_condition(request: ExplainRequest, db: Session = Depends(get_db)):
    """
    Explain now: the condition worked out with the values a past run of the workflow had, each
    part with its own answer. ${...} take the values they have now.
    """
    run = db.query(JobRun).filter(JobRun.RunID == request.run_id).first()
    if run is None or run.JobType != "WORKFLOW":
        raise HTTPException(404, f"AutoApp has no record of a workflow run '{request.run_id}'.")
    values = run_values(db, run)
    variable = _variable(db, run.JobKey)
    try:
        for ref in conditions.references(request.condition):
            if ref.startswith("${"):
                values[ref] = variable(ref) if variable else None
        explained = conditions.explain(request.condition, values)
    except ValueError as e:
        raise HTTPException(422, str(e))
    used = {ref: values.get(ref) for ref in conditions.references(request.condition)}
    return ExplainResult(result={True: "TRUE", False: "FALSE"}.get(explained["result"], "UNKNOWN"),
                         values=used, explain=explained)

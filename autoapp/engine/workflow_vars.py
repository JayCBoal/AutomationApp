"""
Workflow variables (docs/WORKFLOWS_PHASE4.md, decisions 19 to 21).

A job run in a workflow sees two levels a job on its own does not:

    WORKFLOW   the workflow's own variables, over those its tags give
    USE        the variables set on this use of the job in the workflow

The workflow runner fixes both as the run starts, and keeps them on the workflow's run
(JobRuns.WorkflowVariables), so every job in the run sees the same values even if the workflow
is changed while it runs. A workflow's value is filled in then, in the workflow's own context;
one that cannot be (it names a variable only a job has) is kept as written, for the job to fill in.

A secret is kept by name only, never its value: each job reads its current value as it starts.

    {"workflow": {"Region": {"value": "EU"}, "ApiKey": {"secret": true},
                  "Env": {"conflict": "Variable 'Env' is given different values by ..."}},
     "uses": {"Load": {"Region": {"value": "US"}}}}
"""
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Job, JobRun, WorkflowItem, WorkflowRunItem
from engine import tag_vars


@dataclass
class Noted:
    """A variable the workflow's tags disagree about, as the scope engine reports a conflict."""
    name: str
    text: str

    def message(self) -> str:
        return self.text


@dataclass
class Levels:
    """What a job in a workflow gets from it: the WORKFLOW and USE levels."""
    workflow_key: str
    values: Dict[str, Optional[str]] = field(default_factory=dict)
    conflicts: Dict[str, Noted] = field(default_factory=dict)
    use_values: Dict[str, Optional[str]] = field(default_factory=dict)


def fixed_values(db: Session, workflow: Job, instance_id: str, environment: Optional[Dict[str, str]] = None,
                 business_date: Optional[date] = None) -> Dict[str, Any]:
    """The workflow's variables and each use's, as a run starts, ready to keep as JSON."""
    from engine.scope_engine import ScopeResolutionEngine
    engine = ScopeResolutionEngine(db=db, job_id=workflow.MasterObject_id, instance_id=instance_id,
                                   environment=environment, business_date=business_date)
    engine.build_context()
    entries: Dict[str, Dict[str, Any]] = {}
    for name, value, secret in _workflow_variables(db, workflow, entries):
        entries[name] = {"secret": True} if secret else {"value": _filled_in(engine, value)}
    uses = {item.ItemName: {v.VarName: {"secret": True} if v.IsSecret else {"value": v.VarValue}
                            for v in item.variables}
            for item in workflow.items}
    return {"workflow": entries, "uses": uses}


def _workflow_variables(db: Session, workflow: Job, conflicts: Dict[str, Dict[str, Any]]):
    """
    Each variable the workflow gives, as (name, value, secret): its tags' first, then its own over them.
    Those its tags disagree about, and it does not settle, go into conflicts.
    """
    own = {v.VarName: v for v in workflow.variables}
    given = tag_vars.inherited(db, workflow.MasterObject_id)
    for name, conflict in given.conflicts.items():
        if name not in own:
            conflicts[name] = {"conflict": conflict.message(advice=_advice(workflow))}
    found = [(name, g.value, g.secret) for name, g in given.values.items()]
    return found + [(name, v.VarValue, bool(v.IsSecret)) for name, v in own.items()]


def _advice(workflow: Job) -> str:
    return f"Give it a value on workflow '{workflow.JobKey}', or on this use of the job."


def _filled_in(engine, value: Optional[str]) -> Optional[str]:
    try:
        return engine.interpolate(value)
    except ValueError:
        return value                # the job fills it in, with what it can see


def for_run(db: Session, parent_run_id: Optional[str], path: Optional[str]) -> Optional[Levels]:
    """What the workflow run fixed for the job at path, or None if it fixed nothing (or is not a workflow's)."""
    if not parent_run_id:
        return None
    run = db.query(JobRun).filter(JobRun.RunID == str(parent_run_id)).first()
    if run is None or not run.WorkflowVariables:
        return None
    kept = json.loads(run.WorkflowVariables)
    levels = Levels(workflow_key=run.JobKey)
    secrets = _secret_values(db, run.job) if run.job is not None else {}
    for name, entry in kept.get("workflow", {}).items():
        if "conflict" in entry:
            levels.conflicts[name] = Noted(name, entry["conflict"])
        else:
            levels.values[name] = secrets.get(name) if entry.get("secret") else entry.get("value")
    use_secrets = _use_secret_values(db, run, path)
    for name, entry in kept.get("uses", {}).get(_item_name(path), {}).items():
        levels.use_values[name] = use_secrets.get(name) if entry.get("secret") else entry.get("value")
    return levels


def _secret_values(db: Session, workflow: Job) -> Dict[str, Optional[str]]:
    """The current values of the workflow's variables, its own over its tags'."""
    given = tag_vars.inherited(db, workflow.MasterObject_id).plain()
    return {**given, **{v.VarName: v.VarValue for v in workflow.variables}}


def _use_secret_values(db: Session, run: JobRun, path: Optional[str]) -> Dict[str, Optional[str]]:
    row = (db.query(WorkflowRunItem).filter(WorkflowRunItem.WorkflowRun_id == run.id, WorkflowRunItem.Path == path)
           .first())
    item = db.get(WorkflowItem, row.Item_id) if row is not None and row.Item_id else None
    return {v.VarName: v.VarValue for v in item.variables} if item is not None else {}


def _item_name(path: Optional[str]) -> str:
    return (path or "").split("/")[-1]


def for_use(db: Session, workflow_key: str, use_name: str) -> Optional[Tuple[Levels, WorkflowItem]]:
    """What the use called use_name in the saved workflow gives its job, and the use; None if there is no such use."""
    workflow = db.query(Job).filter(Job.JobKey == workflow_key, Job.JobType == "WORKFLOW").first()
    item = next((i for i in workflow.items if i.ItemName == use_name), None) if workflow else None
    return (for_check(db, workflow, item), item) if item else None


def for_check(db: Session, workflow: Job, item: WorkflowItem) -> Levels:
    """What the job of a use would get, from the definitions as they are now: for checks and the page."""
    conflicts: Dict[str, Dict[str, Any]] = {}
    found = _workflow_variables(db, workflow, conflicts)
    return Levels(workflow_key=workflow.JobKey,
                  values={name: value for name, value, _ in found},
                  conflicts={name: Noted(name, entry["conflict"]) for name, entry in conflicts.items()},
                  use_values={v.VarName: v.VarValue for v in item.variables})

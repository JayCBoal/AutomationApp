"""
Embedded and shared, both ways (docs/WORKFLOWS_PHASE6.md, proposal 10; D127):

  - make_shared: an embedded job (or workflow, with everything embedded in it) gets a key of the owner's
    choosing, loses its owner and shows in the lists. The item that used it still does.
  - embed_copy: an item that runs a shared job or workflow now runs an embedded copy of it (steps, variables,
    Reactions, everything inside), for when this use needs to differ. The original is not touched.

Neither merges back, and later changes to the original do not reach the copy.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app import rename_store, workflow_store
from core.models import Audit, Job, WorkflowItem
from app.schemas import (EmbeddedJobSave, JobStepOut, JobStepSave, PrerequisiteOut, PrerequisiteSave, VariableSave,
                         WorkflowItemSave)
from app.workflow_errors import WorkflowError
from core import frames
import json


def _variables(rows) -> List[VariableSave]:
    """Variables with their values, secrets too: the copy is made on the server, so nothing is read back through a page."""
    return [VariableSave(name=v.VarName, value=v.VarValue, secret=bool(v.IsSecret), description=v.Description) for v in rows]


def _steps(steps: List[JobStepOut]) -> List[JobStepSave]:
    return [JobStepSave(title=s.title, name=s.name, active=s.active, on_failure=s.on_failure, step_type=s.step_type,
                        parameters=dict(s.parameters), children=_steps(s.children)) for s in steps]


def _prerequisite(p: PrerequisiteOut, old: str, new: str) -> PrerequisiteSave:
    """A prerequisite as it is saved; one on something inside the copied tree is pointed at the copy's key."""
    saved = PrerequisiteSave(**p.model_dump())
    if p.workflow and (p.workflow == old or p.workflow.startswith(old + ".")):
        saved.workflow = new + p.workflow[len(old):]
    return saved


def to_save(job: Job, old: str, new: str) -> EmbeddedJobSave:
    """A job as a save would send it, ready to make an embedded copy of it. old and new: its key and its copy's."""
    from app.job_store import describe_job
    detail = describe_job(job)
    uses = {item.ItemName: item for item in job.items}
    items = []
    for out in detail.items:
        item = uses[out.name]
        embedded = frames.is_embedded_in(item.job, job)
        items.append(WorkflowItemSave(
            name=out.name, job_key="" if embedded else out.job_key,
            embedded=to_save(item.job, item.job.JobKey, new + item.job.JobKey[len(old):]) if embedded else None,
            join=out.join, rule=out.rule, prerequisites=[_prerequisite(p, old, new) for p in out.prerequisites],
            disabled_here=out.disabled_here, reactions_overridden=out.reactions_overridden, reactions=out.reactions,
            variables=_variables(item.variables), on_unmet=out.on_unmet))
    return EmbeddedJobSave(
        job_type=detail.job_type, description=detail.description, active=detail.active,
        success_return_codes=detail.success_return_codes, steps=_steps(detail.steps), items=items,
        succeeds_when=detail.succeeds_when, return_code_from=detail.return_code_from,
        variables=_variables(job.variables), reactions=detail.reactions)


def _audit(db: Session, job: Job, who: str, changes: List[str]) -> None:
    db.add(Audit(MasterObject_id=job.MasterObject_id, Action="JOB_UPDATED", PerformedBy=who,
                 Details=json.dumps({"job_key": job.JobKey, "changes": changes})))


def embed_copy(db: Session, workflow: Job, item_name: str, who: str) -> Job:
    """Makes the item run an embedded copy of the shared job it runs. Returns the copy."""
    from app.job_store import apply_job
    item = next((i for i in workflow.items if i.ItemName == item_name), None)
    if item is None:
        raise WorkflowError(f"The workflow '{workflow.JobKey}' has no job named '{item_name}'.")
    source = item.job
    if frames.is_embedded_in(source, workflow):
        raise WorkflowError(f"'{item_name}' is already embedded in '{workflow.JobKey}'.")
    key = workflow_store.embedded_key(db, workflow, item_name, None)
    tree = workflow_store.Tree()
    tree.path.append(item_name)
    copy, _ = apply_job(db, to_save(source, source.JobKey, key).model_copy(update={"job_key": key}), None, who,
                        owner=workflow, tree=tree)
    item.job = copy
    workflow_store.wire_tree(db, workflow, tree)
    _audit(db, workflow, who, [f"'{item_name}' now runs an embedded copy of '{source.JobKey}'."])
    return copy


def make_shared(db: Session, job: Job, new_key: str, move_folder: bool, who: str) -> Job:
    """Frees an embedded job from its owner under new_key, and lists it. Raises WorkflowError if that cannot be done."""
    if job.Owner_MasterObject_id is None:
        raise WorkflowError(f"'{job.JobKey}' is not embedded in a workflow, so it is shared already.")
    new_key = new_key.strip()
    if new_key != job.JobKey and db.query(Job.MasterObject_id).filter(Job.JobKey == new_key).first():
        raise WorkflowError(f"A job with the key '{new_key}' already exists. Choose another key.")
    owner, old_key = job.owner, job.JobKey
    if new_key != old_key:
        try:
            rename_store.check_rename(db, job, new_key, move_folder)
        except rename_store.RenameError as e:
            raise WorkflowError(str(e))
        try:
            job.JobKey = new_key
        except ValueError as e:
            raise WorkflowError(str(e))
        if move_folder:
            rename_store.move_folder(old_key, new_key)
    job.owner = None
    db.flush()
    for item in job.items:
        if frames.is_embedded_in(item.job, job):
            workflow_store.rekey(db, job, item.ItemName, item.job)
    _audit(db, owner, who, [f"Made '{old_key}' a job of its own"
                            + (f", under the key '{new_key}'." if new_key != old_key else ".")])
    _audit(db, job, who, [f"Made shared: it no longer belongs to '{owner.JobKey}'."])
    return job

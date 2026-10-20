"""
Frames (docs/WORKFLOWS_PHASE6.md): a workflow embedded in another is drawn and run as a frame. The
embedded jobs and workflows of a workflow, and theirs in turn, are its tree; a job has an owner when it is
embedded. A condition reaches an item inside a frame by a dotted path: %{Transform.Enrich.Status}.
"""
from typing import Dict, List

from app.models import Job


def tree_top(job: Job) -> Job:
    """The job at the top of the embedded jobs a job belongs to: the job itself when it is not embedded."""
    while job.owner is not None:
        job = job.owner
    return job


def is_embedded_in(job: Job, workflow: Job) -> bool:
    return job.Owner_MasterObject_id is not None and job.Owner_MasterObject_id == workflow.MasterObject_id


def inner_paths(jobs: Dict[str, Job], owner: Job, prefix: str = "") -> List[str]:
    """
    The dotted path of every item inside the frames among jobs (item name to its job), at any depth:
    "Transform.Enrich", "Transform.Stage.Load". Only embedded workflows count: another workflow's
    inside can change without this one being saved, so a shared workflow offers its own outputs only.
    """
    found: List[str] = []
    for name, job in jobs.items():
        if job.JobType == "WORKFLOW" and is_embedded_in(job, owner):
            inside = {item.ItemName: item.job for item in job.items}
            found += [f"{prefix}{name}.{inner}" for inner in inside]
            found += inner_paths(inside, job, f"{prefix}{name}.")
    return found


def reachable_names(workflow: Job) -> List[str]:
    """The names a condition in the workflow can use for its items: theirs, and the paths inside its frames."""
    jobs = {item.ItemName: item.job for item in workflow.items}
    return list(jobs) + inner_paths(jobs, workflow)

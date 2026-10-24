"""
The ${...} values of a workflow's Resume (docs/WORKFLOWS_PHASE7.md, step 4b): what the dialog lists, one list for each
level that can be edited, and the checking of the edits it sends back.

    workflow  a workflow's own variables, for the run at the top and for each frame that is reopened
    use       the variables set on one use of a job in a workflow
    job       what a job that resumes read from its own levels (job, application, system and so on)

Each value is shown once. A job's list leaves out a value it got from the workflow or its use (it is the same
value, and editing it there reaches every job that runs again). A job that already Succeeded is not run again and
keeps the values it ran with, so the plan names those jobs.
"""
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.models import Audit, Job, JobRun, WorkflowRunItem
from engine.reopen_tree import Pick, TreePlan
from engine import reopen, run_values, workflow_vars

WORKFLOW, USE, JOB = "workflow", "use", "job"
SUCCEEDED = "SUCCESS"


class ValueShown(BaseModel):
    key: str = Field(..., description="What the job wrote: Region for ${Region}, JOB.Region, or ENV:Region")
    value: Optional[str] = Field(None, description="The value the earlier attempt used; absent for a secret")
    secret: bool = Field(False, description="A secret is read again each time, and cannot be edited")


class ValueChange(BaseModel):
    key: str
    was: str
    now: str


class ValueLevel(BaseModel):
    kind: str = Field(..., description="workflow, use or job")
    path: str = Field(..., description="workflow: the workflow's place in the run (empty for the run at the top); "
                                       "use: the workflow the use is in; job: the job's place in the run")
    name: str = Field(..., description="The workflow's, use's or job's name, for the heading")
    values: List[ValueShown] = []
    changes: List[ValueChange] = Field([], description="Values that read differently now: what a Refresh would use")


class LevelEdit(BaseModel):
    workflow: Dict[str, str] = Field({}, description="The workflow's own variables to change, by name")
    uses: Dict[str, Dict[str, str]] = Field({}, description="The variables of a use to change: use name, then name")


def _workflows(tree: TreePlan) -> List[Tuple[str, JobRun]]:
    """The runs that are reopened, by their place in the run: the one at the top, and each frame that goes on."""
    found = [("", tree.top)]
    found += [(p.path, p.child) for p in tree.picks if p.child is not None and p.child.JobType == "WORKFLOW" and p.goes_on()]
    return found


def _kept(run: JobRun) -> Dict[str, Any]:
    return json.loads(run.WorkflowVariables) if run.WorkflowVariables else {}


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _shown(entries: Dict[str, Any]) -> List[ValueShown]:
    return [ValueShown(key=name, value=entry.get("value"), secret="secret" in entry)
            for name, entry in sorted(entries.items()) if "value" in entry or "secret" in entry]


def _changed(was: Dict[str, Any], now: Dict[str, Any]) -> List[ValueChange]:
    return [ValueChange(key=name, was=was[name]["value"], now=entry["value"])
            for name, entry in sorted(now.items())
            if name in was and "value" in was[name] and "value" in entry and was[name]["value"] != entry["value"]
            and "${ENV:" not in entry["value"]]


def _fresh(db: Session, run: JobRun) -> Dict[str, Any]:
    """The workflow's variables as they read now; environment variables are the scheduler's to read, so left as written."""
    if run.job is None:
        return {}
    return workflow_vars.fixed_values(db, run.job, run.SchedulerInstanceID, environment={}, business_date=run.BusinessDate)


def levels_for(db: Session, tree: TreePlan) -> List[ValueLevel]:
    """Every list the dialog shows: each reopened workflow's variables and its uses', then each resumed job's own."""
    found: List[ValueLevel] = []
    hidden: Dict[str, Dict[str, str]] = {}                      # job path: bare names it got from a workflow or a use
    for path, run in _workflows(tree):
        kept, fresh = _kept(run), _fresh(db, run)
        if kept.get("workflow"):
            found.append(ValueLevel(kind=WORKFLOW, path=path, name=run.JobKey, values=_shown(kept["workflow"]),
                                    changes=_changed(kept["workflow"], fresh.get("workflow", {}))))
        for pick in tree.picks:
            if _parent(pick.path) != path or pick.action in reopen.PASS_OVER:
                continue
            use = pick.path.rsplit("/", 1)[-1]
            entries = kept.get("uses", {}).get(use) or {}
            if entries:
                found.append(ValueLevel(kind=USE, path=path, name=use, values=_shown(entries),
                                        changes=_changed(entries, fresh.get("uses", {}).get(use, {}))))
            hidden[pick.path] = {**{n: e["value"] for n, e in kept.get("workflow", {}).items() if "value" in e},
                                 **{n: e["value"] for n, e in entries.items() if "value" in e}}
    for pick in tree.picks:
        if pick.record is not None and pick.action == reopen.PICK_UP:
            level = _job_level(db, pick, hidden.get(pick.path, {}))
            if level.values:
                found.append(level)
    return found


def _job_level(db: Session, pick: Pick, given: Dict[str, str]) -> ValueLevel:
    """A resuming job's own values: leaves out those it got, unchanged, from its workflow or its use."""
    from app.routers import reruns
    own = {key: entry for key, entry in pick.record.values.items() if not _from_above(key, entry, given)}
    changes = [c for c in reruns.changes_for(db, pick.child, pick.record) if c.key in own]
    return ValueLevel(kind=JOB, path=pick.path, name=pick.job_key, values=_shown(own), changes=changes)


def _from_above(key: str, entry: Dict[str, Any], given: Dict[str, str]) -> bool:
    bare = key.split(".", 1)[1] if key.startswith(("WORKFLOW.", "USE.")) else key
    return bare in given and (key != bare or "value" not in entry or entry["value"] == given[bare])


def kept_jobs(db: Session, tree: TreePlan) -> List[str]:
    """The jobs of the reopened workflows that already Succeeded: they are not run again and keep the values they ran with."""
    ids = [run.id for _, run in _workflows(tree)]
    rows = db.query(WorkflowRunItem).filter(WorkflowRunItem.WorkflowRun_id.in_(ids), WorkflowRunItem.Status == SUCCEEDED)
    found = []
    for row in rows.order_by(WorkflowRunItem.WorkflowRun_id, WorkflowRunItem.ItemOrder):
        child = db.get(JobRun, row.ChildRun_id) if row.ChildRun_id else None
        if child is not None and child.JobType != "WORKFLOW":
            found.append(row.Path)
    return found


def note_for(tree: TreePlan) -> str:
    """What the dialog says about the conditions a workflow has not yet decided."""
    return ("Conditions that have not been decided yet read the new values; a condition already decided stays decided."
            if _workflows(tree) else "")


def check_edits(tree: TreePlan, level_edits: Dict[str, LevelEdit], job_edits: Dict[str, Dict[str, str]]) -> Tuple[Dict[str, Any], List[str]]:
    """The edits in the shape the runner takes ({"levels": ..., "jobs": ...}), and why any cannot be made, in words."""
    problems: List[str] = []
    runs = dict(_workflows(tree))
    levels: Dict[str, Any] = {}
    for path, edit in level_edits.items():
        run = runs.get(path)
        if run is None:
            problems.append(f"'{path or tree.top.JobKey}' is not a workflow this Resume opens again, so its variables cannot be edited.")
            continue
        kept = _kept(run)
        problems += _plain(kept.get("workflow", {}), edit.workflow, f"workflow '{run.JobKey}'")
        for use, names in edit.uses.items():
            problems += _plain(kept.get("uses", {}).get(use, {}), names, f"use '{use}' in '{run.JobKey}'")
        levels[path] = {"workflow": edit.workflow, "uses": edit.uses}
    picks = {p.path: p for p in tree.picks if _can_edit(p, tree.items is not None)}
    jobs: Dict[str, Dict[str, str]] = {}
    for path, edits in job_edits.items():
        pick = picks.get(path)
        if pick is None:
            problems.append(f"'{path}' does not go on from an earlier attempt or start again as a job, so its values cannot be edited.")
            continue
        problems += run_values.edit_problems(pick.record.values, edits) if pick.record is not None else _blank(edits)
        jobs[path] = edits
    return {"levels": levels, "jobs": jobs}, problems


def _can_edit(pick: Pick, advanced: bool) -> bool:
    """A job that goes on from its record, or one Advanced starts again (it reads fresh and pins only what is typed)."""
    if pick.action == reopen.PICK_UP:
        return pick.record is not None
    return advanced and pick.action == reopen.FRESH and (pick.child is None or pick.child.JobType != "WORKFLOW")


def _blank(edits: Dict[str, str]) -> List[str]:
    return ["The name of a value to change cannot be empty." for key in edits if not key.strip()]


def _plain(kept: Dict[str, Any], edits: Dict[str, str], where: str) -> List[str]:
    problems = []
    for name in edits:
        entry = kept.get(name)
        if entry is None or ("value" not in entry and "secret" not in entry):
            problems.append(f"{name} is not a variable of {where} in this run, so there is no value to edit.")
        elif "secret" in entry:
            problems.append(f"{name} is a secret. It is always read when the job runs, and cannot be edited here.")
    return problems


def audit(db: Session, tree: TreePlan, choices: Dict[str, Any]) -> List[str]:
    """
    One JOB_RESUMED_WITH_EDITS row for each job whose own values were edited, and one for each workflow whose own or
    use variables were edited, under that workflow. By name, old and new value, never a secret. Returns every
    sentence written, for the run's restart record.
    """
    every: List[str] = []
    runs = dict(_workflows(tree))
    picks = {p.path: p for p in tree.picks}
    for path, edit in choices["levels"].items():
        run, kept = runs[path], _kept(runs[path])
        said = [f"Resumed '{run.JobKey}' with variable {n} changed from '{kept['workflow'][n]['value']}' to '{v}'."
                for n, v in sorted(edit["workflow"].items())]
        said += [f"Resumed '{run.JobKey}' with variable {n} of use '{use}' changed from '{kept['uses'][use][n]['value']}' to '{v}'."
                 for use, names in sorted(edit["uses"].items()) for n, v in sorted(names.items())]
        _add(db, run.JobKey, said)
        every += said
    for path, edits in choices["jobs"].items():
        pick = picks[path]
        said = [_job_edit_words(pick, k, v) for k, v in sorted(edits.items())]
        _add(db, pick.job_key, said, "JOB_RESUMED_WITH_EDITS" if pick.record is not None else "JOB_RESTARTED_WITH_EDITS")
        every += said
    db.commit()
    return every


def _job_edit_words(pick: Pick, key: str, value: str) -> str:
    if pick.record is not None:
        return f"Resumed '{pick.job_key}' with {key} changed from '{pick.record.values[key]['value']}' to '{value}'."
    return f"Restarted '{pick.job_key}' with {key} set to '{value}'; its other values are read as it starts."


def _add(db: Session, job_key: str, said: List[str], action: str = "JOB_RESUMED_WITH_EDITS") -> None:
    if not said:
        return
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    db.add(Audit(MasterObject_id=job.MasterObject_id if job else None, Action=action,
                 PerformedBy="web interface", Details=json.dumps({"changes": said})))

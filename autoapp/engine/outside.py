"""
What a job in a workflow can wait for outside its own workflow (docs/WORKFLOWS_PHASE5.md): a job
or a whole workflow elsewhere, files at an endpoint, or the time. Each is read from the database
or the disk, never from the operations log (the telemetry principle).

  - find_job / find_workflow: the run of another workflow that counts (decision D18): the run
    executing now, else the most recent completed one, if it passes the prerequisite's limits;
  - look_at_files: the files at a path, and whether every one is old enough (D19);
  - now_values: the time as a value in conditions (D20); `IN WINDOW` is expanded by engine/conditions.py (D103).
"""
import glob
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import JobRun, WorkflowRunItem
from engine import file_age

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def now() -> datetime:
    """This machine's local time. A test replaces it to set the clock."""
    return datetime.now()


def now_values(moment: datetime) -> Dict[str, Any]:
    """%{Now.Time}, %{Now.Date} and %{Now.Weekday} at the moment given."""
    return {"%{Now.Time}": moment.strftime("%H:%M"), "%{Now.Date}": moment.strftime("%Y-%m-%d"),
            "%{Now.Weekday}": WEEKDAYS[moment.weekday()]}


# ---------- Files ----------

@dataclass
class FilesFound:
    count: int
    size: int
    waiting_for: List[str] = field(default_factory=list)     # the matching files still too new

    def holds(self) -> bool:
        return self.count > 0 and not self.waiting_for

    def words(self, pattern: str, min_age: Optional[int]) -> str:
        if self.count == 0:
            return f"No files match '{pattern}'."
        if self.waiting_for:
            return (f"{self.count} file(s) match '{pattern}', but {len(self.waiting_for)} changed within the last "
                    f"{min_age} s: {', '.join(os.path.basename(p) for p in self.waiting_for[:3])}.")
        return f"{self.count} file(s) match '{pattern}'" + (f", none changed within {min_age} s." if min_age else ".")


def look_at_files(pattern: str, min_age_seconds: Optional[int], moment: Optional[float] = None) -> FilesFound:
    """The files matching the pattern, their size, and which are not yet old enough (each unchanged for min_age_seconds)."""
    paths = sorted(p for p in glob.glob(pattern) if os.path.isfile(p))
    young = file_age.too_new(paths, min_age_seconds, moment) if min_age_seconds else []
    return FilesFound(len(paths), sum(os.path.getsize(p) for p in paths if os.path.exists(p)), young)


# ---------- Another workflow's run ----------

@dataclass
class Target:
    """How a job (or a whole workflow) stands in the run of another workflow that counts."""
    status: str
    code: Optional[int]
    reason: Optional[str]
    file_count: Optional[int]
    size: Optional[int]
    started: Optional[datetime]
    ended: Optional[datetime]
    run_id: str
    run_ended: Optional[datetime]
    run_running: bool


def _fresh(ended: Optional[datetime], running: bool, started: Optional[datetime], hours: Optional[int],
           after: Optional[datetime], moment: datetime) -> bool:
    """Whether a run passes the prerequisite's limits: ended within hours of moment (UTC), and started after the waiting run did."""
    if after is not None and (started is None or started <= after):
        return False
    if hours and not running:
        return ended is not None and moment - ended <= timedelta(hours=hours)
    return True


def _best(candidates: List[Target]) -> Optional[Target]:
    """The run executing now, else the most recent that ended."""
    running = [c for c in candidates if c.run_running]
    if running:
        return running[0]
    return candidates[0] if candidates else None


def find_job(db: Session, item_id: int, hours: Optional[int], after: Optional[datetime], moment: datetime) -> Optional[Target]:
    """The use item_id (a job in another workflow) in the run of its workflow that counts, or None."""
    rows = (db.query(WorkflowRunItem, JobRun).join(JobRun, JobRun.id == WorkflowRunItem.WorkflowRun_id)
            .filter(WorkflowRunItem.Item_id == item_id).order_by(JobRun.id.desc()).limit(200))
    found = []
    for row, run in rows:
        running = run.Status == "RUNNING"
        ended = row.EndedDateTime or run.EndedDateTime
        if not _fresh(ended, running, run.StartedDateTime, hours, after, moment):
            continue
        child = row.child_run
        found.append(Target(row.Status, row.ReturnCode, row.Reason, child.FileCount if child else None,
                            child.Bytes if child else None, row.StartedDateTime, row.EndedDateTime, run.RunID,
                            run.EndedDateTime, running))
    return _best(found)


def find_workflow(db: Session, workflow_id: int, hours: Optional[int], after: Optional[datetime],
                  moment: datetime) -> Optional[Target]:
    """A whole workflow (its final status) in its run that counts, or None."""
    rows = (db.query(JobRun).filter(JobRun.Job_MasterObject_id == workflow_id, JobRun.JobType == "WORKFLOW")
            .order_by(JobRun.id.desc()).limit(200))
    found = []
    for run in rows:
        running = run.Status == "RUNNING"
        if not _fresh(run.EndedDateTime, running, run.StartedDateTime, hours, after, moment):
            continue
        found.append(Target(run.Status, run.ReturnCode, run.Reason, run.FileCount, run.Bytes, run.StartedDateTime,
                            run.EndedDateTime, run.RunID, run.EndedDateTime, running))
    return _best(found)


# ---------- A frame's own tree (Phase 6, D122) ----------

def run_tree_ids(db: Session, root_run_id: int) -> List[int]:
    """The ids of a run and of every workflow run below it (a frame's run, a shared workflow's, and so on)."""
    found, level = [root_run_id], [root_run_id]
    while level:
        level = [run_id for (run_id,) in db.query(JobRun.id).filter(JobRun.ParentRun_id.in_(level))]
        found += level
    return found


def find_job_in_tree(db: Session, item_id: int, root_run_id: int) -> Optional[Target]:
    """
    The use item_id as it stands in THIS run of its tree: never an earlier or a later run of the same
    workflow (D122), so a rerun waits for this run's answer and not yesterday's. None while its frame
    has not started.
    """
    rows = (db.query(WorkflowRunItem, JobRun).join(JobRun, JobRun.id == WorkflowRunItem.WorkflowRun_id)
            .filter(WorkflowRunItem.Item_id == item_id, JobRun.id.in_(run_tree_ids(db, root_run_id)))
            .order_by(JobRun.id.desc()))
    found = []
    for row, run in rows:
        child = row.child_run
        found.append(Target(row.Status, row.ReturnCode, row.Reason, child.FileCount if child else None,
                            child.Bytes if child else None, row.StartedDateTime, row.EndedDateTime, run.RunID,
                            run.EndedDateTime, run.Status == "RUNNING"))
    return found[0] if found else None


def find_workflow_in_tree(db: Session, workflow_id: int, root_run_id: int) -> Optional[Target]:
    """A frame as a whole (its final status) in this run of its tree, or None while it has not started."""
    run = (db.query(JobRun).filter(JobRun.Job_MasterObject_id == workflow_id, JobRun.JobType == "WORKFLOW",
                                   JobRun.id.in_(run_tree_ids(db, root_run_id))).order_by(JobRun.id.desc()).first())
    if run is None:
        return None
    return Target(run.Status, run.ReturnCode, run.Reason, run.FileCount, run.Bytes, run.StartedDateTime,
                  run.EndedDateTime, run.RunID, run.EndedDateTime, run.Status == "RUNNING")


def clock_time_after(start: datetime, hhmm: str) -> datetime:
    """The first moment after start that the clock reads hhmm ("02:00")."""
    hour, minute = (int(part) for part in hhmm.split(":"))
    moment = start.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return moment if moment > start else moment + timedelta(days=1)

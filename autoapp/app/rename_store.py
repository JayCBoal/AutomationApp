"""
What renaming a job touches outside the job itself: its run history, its scheduler
definitions and its working folder (<working root>/<JobKey>, which stays named by
the key). The editor asks rename_facts before it saves a rename; the save refuses a
rename while the job runs and, when asked, moves the working folder with it.
"""
import os
import shutil
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Job, JobRun


class RenameError(Exception):
    """A rename that cannot be done. status is the HTTP status to answer with."""
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def working_root() -> Optional[str]:
    return os.environ.get("AUTOAPP_WORKING_ROOT") or None


def folder_of(key: str) -> Optional[str]:
    """Where the job's working folder is on this server's disk, or None when no working root is set."""
    root = working_root()
    return os.path.join(root, key) if root else None


def _runs(db: Session, job: Job):
    return db.query(JobRun).filter((JobRun.Job_MasterObject_id == job.MasterObject_id) | (JobRun.JobKey == job.JobKey))


def rename_facts(db: Session, job: Job) -> dict:
    """What a rename of this job would leave behind, for the warning the editor shows."""
    folder = folder_of(job.JobKey)
    has_folder = bool(folder and os.path.isdir(folder))
    running = _runs(db, job).filter(JobRun.Status == "RUNNING").count() > 0
    return {
        "run_count": _runs(db, job).count(),
        "running": running,
        "working_folder": folder if has_folder else None,
        "can_move_folder": has_folder and not running,
        "needs_warning": has_folder or _runs(db, job).count() > 0,
    }


def check_rename(db: Session, job: Job, new_key: str, move_folder: bool) -> None:
    """Refuses a rename while the job runs, or a folder move that cannot be made."""
    if _runs(db, job).filter(JobRun.Status == "RUNNING").count():
        raise RenameError(f"Job '{job.JobKey}' is running, so it cannot be renamed now. Rename it when the run has ended.")
    target = folder_of(new_key)
    if move_folder and target and os.path.isdir(folder_of(job.JobKey) or "") and os.path.exists(target):
        raise RenameError(f"The working folder '{target}' already exists, so the old one cannot be moved there. "
                          "Move or remove it first, or rename without moving the folder.")


def move_folder(old_key: str, new_key: str) -> bool:
    """Moves the working folder to the new key's name. Returns False when there was no folder to move."""
    old, new = folder_of(old_key), folder_of(new_key)
    if not old or not os.path.isdir(old):
        return False
    try:
        shutil.move(old, new)
    except OSError as e:
        raise RenameError(f"The working folder could not be moved: {e}. The job was not renamed.", status=500)
    return True

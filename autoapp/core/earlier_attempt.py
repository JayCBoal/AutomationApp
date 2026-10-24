"""
Picking up an earlier attempt of a run: the record of how far it got, and whether a Reaction may resume it.
Shared by the server (the Resume pages) and the runners.
"""
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from core import log_files
from core.control_file import ControlRecord, control_name
from core.models import JobRun


def find_earlier_attempt(db: Session, run_id: Optional[str]) -> Tuple[Optional[ControlRecord], Optional[str]]:
    """
    The control file of the run to pick up, or, in words, why there is none to use. Its file is on the
    host that ran it, so a run that would resume elsewhere, or whose file is gone, cannot.
    """
    if not run_id:
        return None, None
    run = db.query(JobRun).filter(JobRun.RunID == str(run_id)).first()
    if run is None:
        return None, f"Run {run_id} is not known, so there is nothing to pick up. Restart the job from the beginning."
    if (run.Host or log_files.this_host()) != log_files.this_host():
        return None, (f"Run {run_id} ran on host '{run.Host}', and the record of how far it got is kept there; "
                      f"this run is on '{log_files.this_host()}'. Restart the job from the beginning.")
    path = log_files.host_folder(run.Host) / control_name(run.LogFile) if run.LogFile else None
    if path is None or not path.is_file():
        return None, (f"The record of how far run {run_id} got is not there; it is removed with the job log. "
                      f"Restart the job from the beginning.")
    return ControlRecord.read(path), None


def automatic_resume_problem(record: Optional[ControlRecord], problem: Optional[str]) -> Optional[str]:
    """
    Why a Reaction may not Resume a failed run, given its control record (or why there is none), in words,
    or None when it may. The rules are the operator's (docs/WORKFLOWS_PHASE7.md, proposals 3 and 13),
    except that nobody is there to decide: a step whose effect is not known stops it, and Restart from
    the beginning stays a choice.
    """
    if record is None:
        return problem
    failure = record.open_failure()
    if failure is None:
        return ("every step had finished, so there is nothing to pick up (the job failed on its return code). "
                "Choose Restart from the beginning to run it again.")
    if failure.get("operator_decides"):
        return (f"step '{failure.get('title') or failure.get('step')}' failed and AutoApp cannot tell whether it "
                f"changed anything ({failure.get('why') or 'no reason given'}). The job stays failed: Resume it by "
                f"hand and choose what to do about that step, or Restart from the beginning.")
    return None

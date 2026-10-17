"""
The workflow runner (docs/WORKFLOWS.md; docs/WORKFLOWS_PHASE1.md, step 3).

Runs a workflow's jobs, each as soon as its prerequisites hold, in parallel unless the
prerequisites say otherwise. engine.runner hands a job over to it when the job is a
workflow, so a scheduler and the Run Job page start a workflow exactly as they start a job.

It works on the database directly, beside the server (in ActiveBatch's terms, on the
server's own virtual queue). It reads the workflow once, at the start, so changing the
workflow does not change a run already going. Each of its jobs runs in a job runner of
its own, which reports through the API as usual; the job run points back to this run.

Every second or so it:
  - collects the jobs that have ended, and how;
  - starts every job whose prerequisites now hold;
  - marks Not run each job whose prerequisites can never hold, which can cascade;
  - after a Cancel, starts nothing more, and marks what has not started Not run.
The workflow ends when every job has a final status: Failed if any job failed (or if it
was cancelled), otherwise Succeeded.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Job, JobRun, JobRunLog, WorkflowRunItem, utcnow
from engine import job_log, return_codes

AUTOAPP_DIR = Path(__file__).resolve().parents[1]
CHILD_SCHEDULER = "AutoApp workflow"
POLL_SECONDS = float(os.getenv("AUTOAPP_WORKFLOW_POLL_SECONDS", "1"))
FINAL = ("SUCCESS", "FAILED", "NOT_RUN")
HOLDS, NEVER, WAIT = "HOLDS", "NEVER", "WAIT"
OUTPUT_KEPT = 20                # lines of a job runner's own output kept, for one that left no record

NEEDS = {"SUCCESS": "succeed", "FAILED": "fail", "ENDED": "end", "RC": "give return code"}


@dataclass
class RunOptions:
    """How the workflow was started: what engine.runner was given."""
    instance_id: str
    spool_dir: str
    run_id: Optional[str] = None
    run_number: int = 1
    scheduler: Optional[str] = None
    api_url: Optional[str] = None
    working_root: Optional[str] = None
    business_date: Optional[date] = None
    log_level: str = job_log.DEFAULT_LEVEL
    parent_run_id: Optional[str] = None
    workflow_path: Optional[str] = None
    attempt: int = 1


@dataclass
class Planned:
    """One job of the workflow, as this run sees it: read once, at the start."""
    name: str
    job_key: str
    join: str
    prerequisites: List[Tuple[str, str, Optional[str]]]       # (target name, test, return codes)
    row: WorkflowRunItem
    process: Optional[subprocess.Popen] = None
    run_id: Optional[str] = None
    output_path: Optional[str] = None


# ---------- Whether a job may start ----------

def prerequisite_state(test: str, codes: Optional[str], status: str, code: Optional[int]) -> str:
    """HOLDS, NEVER (it can no longer hold) or WAIT, given how the job waited for stands."""
    if status not in FINAL:
        return WAIT
    if test == "ENDED":
        return HOLDS                # ended in any way, Not run included, so clean-up jobs still run
    if test == "SUCCESS":
        met = status == "SUCCESS"
    elif test == "FAILED":
        met = status == "FAILED"
    else:
        met = return_codes.matches(code, codes)
    return HOLDS if met else NEVER


def readiness(planned: Planned, by_name: Dict[str, Planned]) -> str:
    """HOLDS when the job may start, NEVER when it never can, WAIT otherwise. ALL or ANY decides."""
    if not planned.prerequisites:
        return HOLDS
    states = [prerequisite_state(test, codes, by_name[target].row.Status, by_name[target].row.ReturnCode)
              for target, test, codes in planned.prerequisites]
    if planned.join == "ANY":
        if HOLDS in states:
            return HOLDS
        return NEVER if all(state == NEVER for state in states) else WAIT
    if NEVER in states:
        return NEVER
    return HOLDS if all(state == HOLDS for state in states) else WAIT


def why_never(planned: Planned, by_name: Dict[str, Planned]) -> str:
    """Which prerequisites can no longer hold, in words: "it waits for 'A' to succeed, and 'A' failed"."""
    reasons = []
    for target, test, codes in planned.prerequisites:
        row = by_name[target].row
        if prerequisite_state(test, codes, row.Status, row.ReturnCode) != NEVER:
            continue
        need = NEEDS[test] + (f" {codes}" if test == "RC" else "")
        reasons.append(f"it waits for '{target}' to {need}, and '{target}' {outcome_words(row)}")
    return "; ".join(reasons)


def outcome_words(row: WorkflowRunItem) -> str:
    code = f" with return code {row.ReturnCode}" if row.ReturnCode is not None else ""
    return {"SUCCESS": f"succeeded{code}", "FAILED": f"failed{code}", "NOT_RUN": "did not run"}.get(row.Status, "has not ended")


# ---------- The run ----------

class WorkflowRunner:
    def __init__(self, db: Session, workflow: Job, options: RunOptions):
        self.db, self.workflow, self.options = db, workflow, options
        self.run_id = options.run_id or str(uuid.uuid4())
        self.record: Optional[JobRun] = None
        self.items: List[Planned] = []
        self.by_name: Dict[str, Planned] = {}
        self.cancelled = False
        self._log_seq = 0

    def run(self) -> int:
        """Runs the workflow to the end. Returns the exit code for whoever started it: 0 if it succeeded, else 1."""
        from app.workflow_store import workflow_problems
        if self.options.working_root:       # so the check of its jobs finds their working folders, as they will
            os.environ["AUTOAPP_WORKING_ROOT"] = self.options.working_root
        self.record = self._record_start()
        job_log.summary(f"Workflow '{self.workflow.JobKey}', instance {self.options.instance_id}")
        problems = workflow_problems(self.db, self.workflow)
        if problems:
            for problem in problems:
                job_log.error(problem)
            return self._finish("FAILED", "ERROR", "The workflow cannot run: " + " ".join(problems))
        self._plan()
        while True:
            self._check_cancel()
            self._collect_ended()
            self._advance()
            self._save()
            if all(p.row.Status in FINAL for p in self.items):
                break
            time.sleep(POLL_SECONDS)
        return self._conclude()

    # --- Starting and ending the run's record ---

    def _record_start(self) -> JobRun:
        parent = None
        if self.options.parent_run_id:
            parent = self.db.query(JobRun).filter(JobRun.RunID == self.options.parent_run_id).first()
        run = JobRun(RunID=self.run_id, JobKey=self.workflow.JobKey, Job_MasterObject_id=self.workflow.MasterObject_id,
                     SchedulerInstanceID=self.options.instance_id, RunNumber=self.options.run_number,
                     SchedulerName=self.options.scheduler, BusinessDate=self.options.business_date,
                     Host=socket.gethostname(), Status="RUNNING", JobType="WORKFLOW", StartedDateTime=utcnow(),
                     ParentRun_id=parent.id if parent else None, WorkflowPath=self.options.workflow_path,
                     Attempt=self.options.attempt)
        self.db.add(run)
        self.db.commit()
        return run

    def _finish(self, status: str, reason: Optional[str], error: Optional[str] = None) -> int:
        self.record.Status, self.record.Reason, self.record.ErrorMessage = status, reason, error
        self.record.ReturnCode = 0 if status == "SUCCESS" else 1
        self.record.EndedDateTime = utcnow()
        self._save()
        return self.record.ReturnCode

    def _conclude(self) -> int:
        failed = [p.name for p in self.items if p.row.Status == "FAILED"]
        not_run = [p.name for p in self.items if p.row.Status == "NOT_RUN"]
        if self.cancelled:
            job_log.error(f"Workflow '{self.workflow.JobKey}' was cancelled.")
            return self._finish("FAILED", "CANCELLED", "Cancelled: nothing more was started.")
        if failed:
            message = f"{_count(failed, 'job')} failed: {', '.join(failed)}."
            job_log.error(f"Workflow '{self.workflow.JobKey}' failed. {message}")
            return self._finish("FAILED", "JOB_FAILED", message)
        job_log.summary(f"Workflow '{self.workflow.JobKey}' completed successfully"
                        + (f"; {_count(not_run, 'job')} did not run, as planned: {', '.join(not_run)}." if not_run else "."))
        return self._finish("SUCCESS", None)

    def _save(self) -> None:
        """Commits the run's state, with the lines the workflow's log has gained."""
        lines = job_log.take_lines()
        if lines:
            self._log_seq += 1
            self.db.add(JobRunLog(JobRun_id=self.record.id, Seq=self._log_seq, LogText="\n".join(lines)))
        self.db.commit()

    # --- Planning, from the workflow as it is now ---

    def _plan(self) -> None:
        base = f"{self.options.workflow_path}/" if self.options.workflow_path else ""
        for position, item in enumerate(self.workflow.items, start=1):
            row = WorkflowRunItem(WorkflowRun_id=self.record.id, Item_id=item.id, Path=base + item.ItemName,
                                  ItemName=item.ItemName, JobKey=item.job.JobKey, ItemOrder=position)
            self.db.add(row)
            prerequisites = [(p.target.ItemName, p.Test, p.ReturnCodes) for p in item.prerequisites if p.target]
            self.items.append(Planned(item.ItemName, item.job.JobKey, item.JoinRule, prerequisites, row))
        self.by_name = {p.name: p for p in self.items}
        job_log.detail(f"{_count(self.items, 'job')}: " + ", ".join(p.name for p in self.items))
        self._save()

    # --- Each pass ---

    def _check_cancel(self) -> None:
        if self.cancelled:
            return
        self.db.commit()                # a new transaction, so it sees what others have committed since
        self.db.refresh(self.record)
        if self.record.CancelRequestedDateTime is not None:
            self.cancelled = True
            job_log.warning("Cancel asked for: nothing more will be started; the jobs running now will finish.")

    def _advance(self) -> None:
        """Starts what may start and marks Not run what never can, until nothing more changes this pass."""
        changed = True
        while changed:
            changed = False
            for planned in self.items:
                if planned.row.Status not in ("PENDING", "WAITING"):
                    continue
                if self.cancelled:
                    self._not_run(planned, "CANCELLED", f"'{planned.name}' will not run: the workflow was cancelled.")
                    changed = True
                    continue
                state = readiness(planned, self.by_name)
                if state == NEVER:
                    self._not_run(planned, "PREREQUISITES_NOT_MET",
                                  f"'{planned.name}' will not run: {why_never(planned, self.by_name)}.")
                    changed = True
                elif state == HOLDS:
                    self._start(planned)
                elif planned.row.Status == "PENDING":
                    planned.row.Status = "WAITING"

    def _not_run(self, planned: Planned, reason: str, message: str) -> None:
        planned.row.Status, planned.row.Reason, planned.row.EndedDateTime = "NOT_RUN", reason, utcnow()
        job_log.summary(message)

    def _start(self, planned: Planned) -> None:
        planned.run_id = str(uuid.uuid4())
        output = tempfile.NamedTemporaryFile(prefix="autoapp_workflow_job_", suffix=".log", delete=False)
        try:
            planned.process = subprocess.Popen(self._command(planned), cwd=AUTOAPP_DIR, stdout=output,
                                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        finally:
            output.close()
        planned.output_path = output.name
        planned.row.Status, planned.row.Attempt, planned.row.StartedDateTime = "RUNNING", 1, utcnow()
        job_log.summary(f"Started '{planned.name}' (job '{planned.job_key}').")

    def _command(self, planned: Planned) -> List[str]:
        o = self.options
        command = [sys.executable, "-m", "engine.runner", "--job-key", planned.job_key,
                   "--instance-id", f"{o.instance_id}-{planned.row.ItemOrder}"[:64], "--scheduler", CHILD_SCHEDULER,
                   "--spool-dir", o.spool_dir, "--run-id", planned.run_id, "--log-level", o.log_level,
                   "--parent-run-id", self.run_id, "--workflow-path", planned.row.Path, "--attempt", "1"]
        if o.api_url:
            command += ["--api-url", o.api_url]
        if o.working_root:
            command += ["--working-root", o.working_root]
        if o.business_date:
            command += ["--business-date", o.business_date.isoformat()]
        return command

    def _collect_ended(self) -> None:
        for planned in self.items:
            if planned.process is None or planned.row.Status != "RUNNING":
                continue
            exit_code = planned.process.poll()
            if exit_code is None:
                continue
            status, code, reason, child = self._outcome(planned, exit_code)
            row = planned.row
            row.Status, row.ReturnCode, row.Reason, row.EndedDateTime = status, code, reason, utcnow()
            row.ChildRun_id = child.id if child else None
            words = "succeeded" if status == "SUCCESS" else "failed"
            job_log.summary(f"'{planned.name}' {words}" + (f", return code {code}." if code is not None else ".")
                            + (f" {child.ErrorMessage}" if status == "FAILED" and child and child.ErrorMessage else ""))

    def _outcome(self, planned: Planned, exit_code: int) -> Tuple[str, Optional[int], Optional[str], Optional[JobRun]]:
        """How the job ended, from its run's record; failing that, from its runner's exit code."""
        child = self._child_run(planned)
        if child is not None and child.EndedDateTime is not None:
            _remove(planned.output_path)
            return child.Status, child.ReturnCode, child.Reason, child
        tail = _tail(planned.output_path)
        job_log.warning(f"'{planned.name}' left no record of how it ended; its runner exited with {exit_code}."
                        + (f" It said: {tail}" if tail else ""))
        status = "SUCCESS" if exit_code == 0 else "FAILED"
        return status, 0 if exit_code == 0 else 1, None if exit_code == 0 else "ERROR", child

    def _child_run(self, planned: Planned) -> Optional[JobRun]:
        """The job's run record. If its records have not arrived through the API, they are loaded from its spool."""
        self.db.commit()                # a new transaction, so it sees what the job runner has committed since
        self.db.expire_all()
        child = self.db.query(JobRun).filter(JobRun.RunID == planned.run_id).first()
        if child is None or child.EndedDateTime is None:
            _load_spool(self.options.spool_dir, planned.run_id)
            self.db.commit()
            self.db.expire_all()
            child = self.db.query(JobRun).filter(JobRun.RunID == planned.run_id).first()
        return child


# ---------- Small helpers ----------

def _count(things, word: str) -> str:
    return f"{len(things)} {word}{'' if len(things) == 1 else 's'}"


def _load_spool(spool_dir: str, run_id: str) -> None:
    """Loads a job run's spool file straight into the database: delivery through the API did not finish."""
    from engine.spool_delivery import load_into_database, read_spool_file
    folder = Path(spool_dir)
    for path in list(folder.glob(f"*_{run_id}.jsonl")) + list(folder.glob(f"delivered/*_{run_id}.jsonl")):
        try:
            load_into_database(read_spool_file(path))
        except Exception as e:          # reported by the caller, which falls back on the exit code
            job_log.debug(f"Could not load {path}: {e}")


def _tail(path: Optional[str]) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [line.rstrip() for line in f.readlines()[-OUTPUT_KEPT:] if line.strip()]
    _remove(path)
    return " / ".join(lines[-3:])


def _remove(path: Optional[str]) -> None:
    if path and os.path.exists(path):
        os.remove(path)


def run_workflow(db: Session, workflow: Job, options: RunOptions) -> int:
    return WorkflowRunner(db, workflow, options).run()

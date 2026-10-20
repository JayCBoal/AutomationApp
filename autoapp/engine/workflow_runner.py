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
  - after a Cancel, starts nothing more, and marks what has not started Not run; after a
    Kill, also kills the jobs running (Failed, KILLED), down through workflows inside it;
  - carries out each ended job's Reactions (engine/reactions.py) before anything that waits
    for it is looked at: Count as, Rerun, Rerun from, Skip, Kill the workflow, Start a workflow.
A job disabled here ends Disabled (Stop here) or Bypassed (Pass through, which counts as
succeeded with return code 0) when its turn comes.
A job with a Custom rule (docs/WORKFLOWS_PHASE4.md) starts as soon as its rule is true, with the
jobs still running counting as unknown, and never runs once it is false; each decision is kept
as a ConditionCheck, with the values it used, for Explain. ${...} in conditions are fixed when
the run starts.
The workflow ends when every job has a final status. By default (docs/WORKFLOWS.md, "When a
workflow succeeds") it fails if a failure went unhandled: a job failed and nothing that waits
for it ran, or a job was cancelled. Otherwise it succeeds, so a failure path that did its job
leaves the workflow green. Its completion rules, where set, say otherwise: Succeeds when (a
condition over its jobs) and Return code from (one of its jobs).
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import (ConditionCheck, Job, JobRun, ReactionEvent, WorkflowPrerequisite, WorkflowPrerequisiteCheck,
                        WorkflowRunItem, utcnow)
from engine import conditions, job_log, log_files, outside, settings, workflow_conditions, workflow_vars
from engine.outside_state import Context, Outside
from engine.prerequisites import FINAL, HOLDS, NEVER, TIMED_OUT, WAIT, SKIPPED_OPTIONAL, prerequisite_state
from engine.reactions import Act, OwnReactions, Rule, judge, read_rules, start_workflow

AUTOAPP_DIR = Path(__file__).resolve().parents[1]
CHILD_SCHEDULER = "AutoApp workflow"
POLL_SECONDS = float(os.getenv("AUTOAPP_WORKFLOW_POLL_SECONDS", "1"))
NOT_STARTED = ("PENDING", "WAITING")
OUTPUT_KEPT = 20                # lines of a job runner's own output kept, for one that left no record

NEEDS = {"SUCCESS": "succeed", "FAILED": "fail", "ENDED": "end", "RC": "give return code", "RULE": "end"}


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
    active: bool = True             # a disabled job ends Disabled when its turn comes: a hard stop
    disabled_here: Optional[str] = None     # STOP or PASS_THROUGH: Disable here, on this use only
    job_type: str = "STEPS"
    rules: List[Rule] = field(default_factory=list)
    process: Optional[subprocess.Popen] = None
    run_id: Optional[str] = None
    output_path: Optional[str] = None
    start_after: float = 0.0        # a rerun waits until then (time.time())
    kill_sent: bool = False
    rule: Optional[str] = None      # with the join CUSTOM: its Custom rule
    file_count: Optional[int] = None    # what its latest attempt reported delivering
    size: Optional[int] = None
    checked_attempt: int = -1       # the attempt its Custom rule's decision was last kept for
    inside_ids: List[int] = field(default_factory=list)     # the ids of the prerequisites above, in the same order
    outside: List[Outside] = field(default_factory=list)    # its prerequisites outside the workflow (Phase 5)
    held: Dict[int, float] = field(default_factory=dict)    # when each prerequisite first held, by id: patience counts from these
    on_unmet: str = "NOT_RUN"       # what happens when it can't start: NOT_RUN or FAIL
    attempt_waited: int = -1        # the attempt the waiting message was last said for


# ---------- Whether a job may start ----------

def run_values(by_name: Dict[str, Planned], variables: Dict[str, Any]) -> Dict[str, Any]:
    """Every %{Name.Output} of the run as it stands, unknown (None) for a job not yet ended, and the variables."""
    values = dict(variables)
    for planned in by_name.values():
        row = planned.row
        values.update(workflow_conditions.item_values(planned.name, row.Status, row.ReturnCode, row.Reason,
                                                      planned.file_count, planned.size,
                                                      row.StartedDateTime, row.EndedDateTime))
        for target in planned.outside:
            values.update(target.values if target.state == HOLDS else target.blank_values())
    values.update(outside.now_values(outside.now()))
    return values


def rule_state(planned: Planned, by_name: Dict[str, Planned], values: Dict[str, Any]) -> Tuple[str, Optional[bool]]:
    """
    Where a Custom rule stands: (HOLDS, NEVER or WAIT, its answer). A rule using IS NULL, coalesce and
    the like is only decided once all its jobs have ended, since those turn unknown into an answer.
    """
    if any(o.state == TIMED_OUT for o in planned.outside):
        return TIMED_OUT, None
    ended = (all(by_name[target].row.Status in FINAL for target, _t, _c in planned.prerequisites)
             and all(o.state != WAIT for o in planned.outside))
    if not ended and conditions.uses_null_tests(planned.rule):
        return WAIT, None
    answer = conditions.decide(planned.rule, values)
    if answer is None:
        return (NEVER if ended else WAIT), None     # unknown once everything is known counts as false
    return (HOLDS if answer else NEVER), answer


def readiness(planned: Planned, by_name: Dict[str, Planned], values: Optional[Dict[str, Any]] = None) -> str:
    """
    HOLDS when the job may start, NEVER when it never can, TIMED_OUT when a prerequisite outside the
    workflow ran out of patience, WAIT otherwise. ALL, ANY or its Custom rule decides.
    """
    if planned.join == "CUSTOM":
        return rule_state(planned, by_name, values if values is not None else run_values(by_name, {}))[0]
    states = [prerequisite_state(test, codes, by_name[target].row.Status, by_name[target].row.ReturnCode)
              for target, test, codes in planned.prerequisites]
    states += [o.state for o in planned.outside]
    if not states:
        return HOLDS
    kept = [state for state in states if state != SKIPPED_OPTIONAL]       # an optional prerequisite that gave up is dropped
    if planned.join == "ANY":
        return _any_of(kept)
    for dead in (NEVER, TIMED_OUT):
        if dead in kept:
            return dead
    return HOLDS if all(state == HOLDS for state in kept) else WAIT


def _any_of(kept: List[str]) -> str:
    """ANY: it may start when one holds; it cannot when every one is dead. Nothing left (all optional gave up): it starts."""
    if not kept or HOLDS in kept:
        return HOLDS
    if all(state in (NEVER, TIMED_OUT) for state in kept):
        return TIMED_OUT if TIMED_OUT in kept else NEVER
    return WAIT


def why_never(planned: Planned, by_name: Dict[str, Planned]) -> str:
    """Which prerequisites can no longer hold, in words: "it waits for 'A' to succeed, and 'A' failed"."""
    if planned.join == "CUSTOM":
        return f"its Custom rule is false: {planned.rule}"
    reasons = []
    for target, test, codes in planned.prerequisites:
        row = by_name[target].row
        if prerequisite_state(test, codes, row.Status, row.ReturnCode) != NEVER:
            continue
        need = NEEDS[test] + (f" {codes}" if test == "RC" else "")
        reasons.append(f"it waits for '{target}' to {need}, and '{target}' {outcome_words(row)}")
    return "; ".join(reasons)


def why_timed_out(planned: Planned) -> str:
    """Which outside prerequisites ran out of patience, in words: "it waited for 'INBOUND' for up to 2 hours, and no files match"."""
    return "; ".join(f"it waited for '{o.name}' {o.limit_words(0)}, and {o.words[:1].lower() + o.words[1:].rstrip('.')}"
                     for o in planned.outside if o.state == TIMED_OUT)


def outcome_words(row: WorkflowRunItem) -> str:
    code = f" with return code {row.ReturnCode}" if row.ReturnCode is not None else ""
    return {"SUCCESS": f"succeeded{code}", "FAILED": f"failed{code}", "NOT_RUN": "did not run",
            "DISABLED": "is disabled", "SKIPPED": "was skipped"}.get(row.Status, "has not ended")


# ---------- The run ----------

class WorkflowRunner:
    def __init__(self, db: Session, workflow: Job, options: RunOptions):
        self.db, self.workflow, self.options = db, workflow, options
        self.run_id = options.run_id or str(uuid.uuid4())
        self.record: Optional[JobRun] = None
        self.items: List[Planned] = []
        self.by_name: Dict[str, Planned] = {}
        self.cancelled = False
        self.killing: Optional[str] = None          # why the workflow is being killed, once it is
        self.times_used: Counter = Counter()        # (path, action id): how often a rerun has run in this run
        self.own: Optional[OwnReactions] = None     # its own Reactions, when it runs on its own
        self.variables: Dict[str, Any] = {}         # the ${...} its conditions use, fixed at the start
        self.record_start_ts = time.time()          # when the run started, for the patience that counts from it

    def run(self) -> int:
        """Runs the workflow to the end. Returns the exit code for whoever started it: 0 if it succeeded, else 1."""
        from app.workflow_store import workflow_problems
        if self.options.working_root:       # so the check of its jobs finds their working folders, as they will
            os.environ["AUTOAPP_WORKING_ROOT"] = self.options.working_root
        self.record = self._record_start()
        self.record_start_ts = time.time()
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
                     Host=log_files.this_host(), LogFile=log_files.start(self.run_id), Status="RUNNING",
                     JobType="WORKFLOW", StartedDateTime=utcnow(),
                     ParentRun_id=parent.id if parent else None, WorkflowPath=self.options.workflow_path,
                     Attempt=self.options.attempt, ProcessID=os.getpid())
        self.db.add(run)
        self.db.commit()
        return run

    def _finish(self, status: str, reason: Optional[str], error: Optional[str] = None) -> int:
        code = self._return_code(status)
        counted = status
        if self.own is not None and reason != "KILLED":
            counted = self.own.after(status, code, self._own_event)
        self.record.Status, self.record.Reason, self.record.ErrorMessage = counted, reason, error
        self.record.StatusBeforeOverride = status if counted != status else None
        self.record.ReturnCode = code
        self.record.FileCount = sum(p.file_count or 0 for p in self.items)
        self.record.Bytes = sum(p.size or 0 for p in self.items)
        self.record.EndedDateTime = utcnow()
        self._save()
        return 0 if counted == "SUCCESS" else 1

    def _return_code(self, status: str) -> int:
        """0 if it succeeded, 1 if not; or, by its completion rules, a chosen job's, where that job has one."""
        source = self.by_name.get(self.workflow.ReturnCodeFrom or "")
        if source is not None and source.row.ReturnCode is not None:
            return source.row.ReturnCode
        return 0 if status == "SUCCESS" else 1

    def _own_event(self, act: Act, result: str, message: str) -> None:
        self.db.add(ReactionEvent(JobRun_id=self.record.id, ReactionAction_id=act.id, Action=act.action,
                                  Result=result, Message=message))

    def _conclude(self) -> int:
        """Succeeded, unless a failure went unhandled or jobs were cancelled; or as its Succeeds when says."""
        if self.workflow.SucceedsWhen and self.items:
            return self._conclude_by_rule()
        cancelled = [p.name for p in self.items if p.row.Reason == "CANCELLED"]
        unhandled, handled = self._failures()
        not_run = [p.name for p in self.items if p.row.Status == "NOT_RUN" and p.row.Reason != "CANCELLED"]
        if self.killing:
            killed = [p.name for p in self.items if p.row.Reason == "KILLED"]
            message = (f"{self.killing}. Killed: {', '.join(killed) or 'none'}; "
                       f"did not start: {', '.join(cancelled) or 'none'}.")
            job_log.error(f"Workflow '{self.workflow.JobKey}' was killed. {message}")
            return self._finish("FAILED", "KILLED", message)
        if cancelled:
            message = f"Cancelled: {_count(cancelled, 'job')} did not start: {', '.join(cancelled)}."
            job_log.error(f"Workflow '{self.workflow.JobKey}' was cancelled. {message}")
            return self._finish("FAILED", "CANCELLED", message)
        if unhandled:
            message = (f"{_count(unhandled, 'job')} failed with nothing that waits for {_it(unhandled)} run: "
                       f"{', '.join(unhandled)}.")
            job_log.error(f"Workflow '{self.workflow.JobKey}' failed. {message}")
            return self._finish("FAILED", "JOB_FAILED", message)
        if handled:
            job_log.summary(f"{_count(handled, 'job')} failed, and what waits for {_it(handled)} ran: "
                            f"{', '.join(handled)}.")
        job_log.summary(f"Workflow '{self.workflow.JobKey}' completed successfully"
                        + (f"; {_count(not_run, 'job')} did not run, as planned: {', '.join(not_run)}." if not_run else "."))
        return self._finish("SUCCESS", None)

    def _conclude_by_rule(self) -> int:
        """Succeeds when, worked out now that every job has ended. A kill or cancel is still its Reason."""
        rule = self.workflow.SucceedsWhen
        values = run_values(self.by_name, self.variables)
        try:
            answer = bool(conditions.decide(rule, values))
        except ValueError as e:
            job_log.error(f"Succeeds when cannot be worked out: {e}")
            return self._finish("FAILED", "ERROR", f"Succeeds when cannot be worked out: {e}")
        self._record_check("SUCCEEDS_WHEN", None, rule, values, answer)
        reason = "KILLED" if self.killing else "CANCELLED" if any(p.row.Reason == "CANCELLED" for p in self.items) else None
        if answer:
            job_log.summary(f"Workflow '{self.workflow.JobKey}' completed successfully: Succeeds when holds.")
            return self._finish("SUCCESS", reason)
        message = f"Succeeds when does not hold: {rule}"
        job_log.error(f"Workflow '{self.workflow.JobKey}' failed. {message}")
        return self._finish("FAILED", reason or "SUCCEEDS_WHEN", message)

    def _failures(self) -> Tuple[List[str], List[str]]:
        """The failed jobs, as (unhandled, handled): handled if a job that waits for it started anyway."""
        waiters: Dict[str, List[Planned]] = {}
        for planned in self.items:
            for target, _test, _codes in planned.prerequisites:
                waiters.setdefault(target, []).append(planned)
        unhandled, handled = [], []
        for planned in self.items:
            if planned.row.Status != "FAILED":
                continue
            ran = any(w.row.Status in ("SUCCESS", "FAILED") for w in waiters.get(planned.name, []))
            (handled if ran else unhandled).append(planned.name)
        return unhandled, handled

    def _save(self) -> None:
        """Commits the run's state. Its log goes straight to its file."""
        self.db.commit()

    # --- Planning, from the workflow as it is now ---

    def _plan(self) -> None:
        base = f"{self.options.workflow_path}/" if self.options.workflow_path else ""
        for position, item in enumerate(self.workflow.items, start=1):
            row = WorkflowRunItem(WorkflowRun_id=self.record.id, Item_id=item.id, Path=base + item.ItemName,
                                  ItemName=item.ItemName, JobKey=item.job.JobKey, ItemOrder=position)
            self.db.add(row)
            inside = [p for p in item.prerequisites if p.Kind == "JOB" and p.target]
            prerequisites = [(p.target.ItemName, p.Test, p.ReturnCodes) for p in inside]
            self.items.append(Planned(item.ItemName, item.job.JobKey, item.JoinRule, prerequisites, row,
                                      active=bool(item.job.IsActive), disabled_here=item.DisabledHere,
                                      job_type=item.job.JobType, rules=read_rules(item.job, item),
                                      rule=item.StartRule if item.JoinRule == "CUSTOM" else None,
                                      inside_ids=[p.id for p in inside], on_unmet=item.OnUnmet,
                                      outside=[self._outside(p) for p in item.prerequisites if p.Kind != "JOB"]))
        self.by_name = {p.name: p for p in self.items}
        self.variables = self._fixed_variables()
        self._fix_workflow_variables()
        job_log.detail(f"{_count(self.items, 'job')}: " + ", ".join(p.name for p in self.items))
        self._save()

    def _outside(self, prerequisite: WorkflowPrerequisite) -> Outside:
        """A prerequisite on something outside the workflow, ready to look at it."""
        target = prerequisite.target
        o = Outside(id=prerequisite.id, name=prerequisite.TargetName or "", kind=prerequisite.Kind,
                    required=bool(prerequisite.Required), test=prerequisite.Test, codes=prerequisite.ReturnCodes,
                    target_item_id=target.id if target else None,
                    target_workflow_id=prerequisite.TargetJob_MasterObject_id,
                    look_back_hours=prerequisite.LookBackHours, only_after_start=bool(prerequisite.OnlyAfterStart),
                    min_age=prerequisite.MinAgeSeconds, time_condition=prerequisite.TimeCondition,
                    wait_mode=prerequisite.WaitMode, wait_minutes=prerequisite.WaitMinutes,
                    wait_until=prerequisite.WaitUntil, wait_from=prerequisite.WaitFrom,
                    wait_from_id=prerequisite.WaitFromPrerequisite_id)
        if prerequisite.Kind == "ENDPOINT":
            o.pattern = self._files_pattern(prerequisite)
        o.values = o.blank_values()
        return o

    def _files_pattern(self, prerequisite: WorkflowPrerequisite) -> str:
        """The folder and file pattern of an endpoint prerequisite, with its ${...} filled in. Empty if it cannot be."""
        from engine.scope_engine import ScopeResolutionEngine
        endpoint = prerequisite.endpoint
        engine = ScopeResolutionEngine(db=self.db, job_id=self.workflow.MasterObject_id, instance_id=self.options.instance_id,
                                       environment=dict(os.environ), business_date=self.options.business_date)
        engine.build_context()
        try:
            folder = engine.interpolate(endpoint.Path, endpoint=endpoint)
            name = engine.interpolate(prerequisite.FilePattern or endpoint.FilenamePattern, endpoint=endpoint)
        except ValueError as e:
            job_log.error(f"'{prerequisite.TargetName}': the endpoint '{endpoint.Name}' cannot be worked out: {e}")
            return ""
        return os.path.join(folder, name)

    def _fix_workflow_variables(self) -> None:
        """Keeps the workflow's variables and each use's on the run, for its jobs to read as they start."""
        fixed = workflow_vars.fixed_values(self.db, self.workflow, self.options.instance_id,
                                           environment=dict(os.environ), business_date=self.options.business_date)
        self.record.WorkflowVariables = json.dumps(fixed)
        if fixed["workflow"]:
            job_log.detail("Variables for its jobs: " + ", ".join(sorted(fixed["workflow"])) + ".")

    def _conditions(self) -> List[str]:
        return [p.rule for p in self.items if p.rule] + ([self.workflow.SucceedsWhen] if self.workflow.SucceedsWhen else [])

    def _fixed_variables(self) -> Dict[str, Any]:
        """The ${...} the conditions use, filled in once, as the run starts (the pre-run check found them all)."""
        refs = {ref for text in self._conditions() for ref in conditions.references(text) if ref.startswith("${")}
        if not refs:
            return {}
        from engine.scope_engine import ScopeResolutionEngine
        engine = ScopeResolutionEngine(db=self.db, job_id=self.workflow.MasterObject_id, instance_id=self.options.instance_id,
                                       environment=dict(os.environ), business_date=self.options.business_date)
        engine.build_context()
        values = {}
        for ref in sorted(refs):
            try:
                values[ref] = engine.interpolate(ref)
            except ValueError as e:
                job_log.warning(f"{ref} has no value, so it counts as unknown: {e}")
                values[ref] = None
        return values

    def _record_check(self, kind: str, path: Optional[str], text: str, values: Dict[str, Any], answer: Optional[bool]) -> None:
        """Keeps a condition's decision, with the values it used, for Explain."""
        used = {ref: values.get(ref) for ref in conditions.references(text)}
        self.db.add(ConditionCheck(WorkflowRun_id=self.record.id, Path=path, Kind=kind, ConditionText=text,
                                   ValuesJson=json.dumps(used), Result={True: "TRUE", False: "FALSE"}.get(answer, "UNKNOWN")))
        shown = ", ".join(f"{ref} = {'unknown' if value is None else repr(value)}" for ref, value in used.items())
        job_log.detail(f"{'Custom rule of ' + repr(path.split('/')[-1]) if path else 'Succeeds when'}: {text} "
                       f"is {'true' if answer else 'false' if answer is False else 'unknown'}" + (f" ({shown})" if shown else ""))

    def _readiness(self, planned: Planned) -> str:
        if planned.join != "CUSTOM":
            return readiness(planned, self.by_name)
        values = run_values(self.by_name, self.variables)
        try:
            state, answer = rule_state(planned, self.by_name, values)
        except ValueError as e:             # checked when saved, so only something the run could not foresee
            job_log.error(f"'{planned.name}': its Custom rule cannot be worked out: {e}")
            return NEVER
        if state != WAIT and planned.checked_attempt != planned.row.Attempt:   # once per attempt, not per pass
            planned.checked_attempt = planned.row.Attempt
            self._record_check("START_RULE", planned.row.Path, planned.rule, values, answer)
        return state

    # --- Each pass ---

    def _check_cancel(self) -> None:
        if self.killing:
            self._kill_running()            # again, for a job that had not recorded its start the last time
            return
        self.db.commit()                # a new transaction, so it sees what others have committed since
        self.db.refresh(self.record)
        if self.record.KillRequestedDateTime is not None:
            self._kill("Kill and Cancel asked for")
        elif self.record.CancelRequestedDateTime is not None and not self.cancelled:
            self.cancelled = True
            job_log.warning("Cancel asked for: nothing more will be started; the jobs running now will finish.")

    def _kill(self, why: str) -> None:
        """Kills the jobs running and cancels those not started. Reactions no longer apply."""
        self.killing, self.cancelled = why, True
        job_log.warning(f"{why}: the jobs running are killed, and nothing more will be started.")
        self._kill_running()

    def _kill_running(self) -> None:
        """A job's runner is told to stop; a workflow inside is asked to kill its own, as this one was."""
        for planned in self.items:
            if planned.row.Status != "RUNNING" or planned.kill_sent or planned.process is None:
                continue
            if planned.job_type == "WORKFLOW":
                child = self.db.query(JobRun).filter(JobRun.RunID == planned.run_id).first()
                if child is None:
                    continue                # not recorded yet: asked again next pass
                child.KillRequestedDateTime = child.KillRequestedDateTime or utcnow()
            elif planned.process.poll() is None:
                planned.process.send_signal(signal.SIGTERM)
            planned.kill_sent = True
            job_log.summary(f"Killing '{planned.name}'.")

    def _advance(self) -> None:
        """Starts what may start and marks Not run what never can, until nothing more changes this pass."""
        changed, looked = True, set()
        while changed:
            changed = False
            for planned in self.items:
                if planned.row.Status not in ("PENDING", "WAITING"):
                    continue
                if self.cancelled:
                    self._not_run(planned, "CANCELLED", f"'{planned.name}' will not run: the workflow was cancelled.")
                    changed = True
                    continue
                if planned.name not in looked:
                    looked.add(planned.name)
                    self._look_outside(planned)
                state = self._readiness(planned)
                if state == NEVER:
                    self._unmet(planned, "PREREQUISITES_NOT_MET", why_never(planned, self.by_name))
                    changed = True
                elif state == TIMED_OUT:
                    self._unmet(planned, "TIMED_OUT", why_timed_out(planned))
                    changed = True
                elif state == HOLDS and (not planned.active or planned.disabled_here):
                    self._disabled(planned)
                    changed = True
                elif state == HOLDS and time.time() >= planned.start_after:
                    self._start(planned)
                elif planned.row.Status == "PENDING":
                    planned.row.Status = "WAITING"

    def _disabled(self, planned: Planned) -> None:
        self._close_checks(planned)
        row = planned.row
        if not planned.active:
            row.Status = "DISABLED"
            job_log.summary(f"'{planned.name}' is disabled (job '{planned.job_key}'), so it does not run.")
        elif planned.disabled_here == "PASS_THROUGH":
            row.Status, row.Reason = "BYPASSED", "DISABLED_PASS_THROUGH"
            job_log.summary(f"'{planned.name}' is disabled here to pass through: it counts as succeeded without running.")
        else:
            row.Status = "DISABLED"
            job_log.summary(f"'{planned.name}' is disabled here, so it does not run.")
        row.EndedDateTime = utcnow()

    def _not_run(self, planned: Planned, reason: str, message: str) -> None:
        self._close_checks(planned)
        planned.row.Status, planned.row.Reason, planned.row.EndedDateTime = "NOT_RUN", reason, utcnow()
        job_log.summary(message)

    def _unmet(self, planned: Planned, reason: str, why: str) -> None:
        """The job can't start (a prerequisite can never hold, or ran out of patience): Not run, or Failed, as the job says."""
        if planned.on_unmet == "FAIL":
            self._close_checks(planned)
            planned.row.Status, planned.row.Reason, planned.row.EndedDateTime = "FAILED", reason, utcnow()
            job_log.error(f"'{planned.name}' fails: {why}.")
        else:
            self._not_run(planned, reason, f"'{planned.name}' will not run: {why}.")

    # --- Prerequisites outside the workflow (docs/WORKFLOWS_PHASE5.md) ---

    def _context(self) -> Context:
        return Context(self.db, self.record.StartedDateTime, utcnow(), outside.now(), time.time(),
                       int(settings.current(self.db, "OutsideWaitHours")))

    def _look_outside(self, planned: Planned) -> None:
        """Reads what the job waits for outside the workflow, judges its patience, and keeps what it found."""
        if not planned.outside:
            return
        ctx = self._context()
        for o in planned.outside:
            o.look(ctx)
        self._note_held(planned, ctx.ts_now)
        every = planned.inside_ids + [o.id for o in planned.outside]
        for o in planned.outside:
            before = o.state
            o.judge(ctx, planned.held, [i for i in every if i != o.id], self.record_start_ts)
            self._note_outside(planned, o, before, ctx.default_hours)

    def _note_held(self, planned: Planned, now_ts: float) -> None:
        """When each prerequisite of the job first held: its patience counts from these."""
        for prerequisite_id, (target, test, codes) in zip(planned.inside_ids, planned.prerequisites):
            row = self.by_name[target].row
            if prerequisite_state(test, codes, row.Status, row.ReturnCode) == HOLDS:
                planned.held.setdefault(prerequisite_id, now_ts)
        for o in planned.outside:
            if o.holding:
                planned.held.setdefault(o.id, now_ts)

    def _note_outside(self, planned: Planned, o: Outside, before: str, default_hours: int) -> None:
        """Keeps what one outside prerequisite found for this attempt, and says in the log when it changes."""
        if o.check is None:
            o.check = WorkflowPrerequisiteCheck(WorkflowRun_id=self.record.id, Path=planned.row.Path,
                                                Attempt=planned.row.Attempt + 1, Kind=o.kind, TargetName=o.name,
                                                Result="WAITING")
            self.db.add(o.check)
            if o.state == WAIT:
                job_log.summary(f"'{planned.name}' waits for '{o.name}', {o.limit_words(default_hours)}.")
        o.check.Result = {WAIT: "WAITING"}.get(o.state, o.state)
        o.check.UsedRunID, o.check.SeenStatus = o.run_id, o.seen
        o.check.Message = o.words if o.state != WAIT else f"Waiting for '{o.name}', {o.limit_words(default_hours)}. {o.words}"
        if o.state != before and o.state != WAIT:
            logged = {HOLDS: job_log.detail, TIMED_OUT: job_log.warning, SKIPPED_OPTIONAL: job_log.summary}[o.state]
            logged({HOLDS: f"'{planned.name}': '{o.name}' holds. {o.words}",
                    TIMED_OUT: f"'{planned.name}': ran out of patience waiting for '{o.name}'. {o.words}",
                    SKIPPED_OPTIONAL: f"'{planned.name}': stopped waiting for the optional '{o.name}' and went on without it. "
                                      f"{o.words}"}[o.state])

    def _close_checks(self, planned: Planned) -> None:
        """The job is decided: what it was still waiting for, it did not need."""
        for o in planned.outside:
            if o.check is not None and o.check.Result == "WAITING":
                o.check.Result = "NOT_NEEDED"

    def _start(self, planned: Planned) -> None:
        self._close_checks(planned)
        planned.run_id, planned.kill_sent = str(uuid.uuid4()), False
        planned.row.Attempt += 1
        output = tempfile.NamedTemporaryFile(prefix="autoapp_workflow_job_", suffix=".log", delete=False)
        try:
            planned.process = subprocess.Popen(self._command(planned), cwd=AUTOAPP_DIR, stdout=output,
                                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        finally:
            output.close()
        planned.output_path = output.name
        planned.row.Status, planned.row.StartedDateTime = "RUNNING", utcnow()
        planned.row.ProcessID = planned.process.pid
        attempt = f", attempt {planned.row.Attempt}" if planned.row.Attempt > 1 else ""
        job_log.summary(f"Started '{planned.name}' (job '{planned.job_key}'{attempt}).")

    def _command(self, planned: Planned) -> List[str]:
        o = self.options
        attempt = planned.row.Attempt
        instance = f"{o.instance_id}-{planned.row.ItemOrder}" + (f".{attempt}" if attempt > 1 else "")
        command = [sys.executable, "-m", "engine.runner", "--job-key", planned.job_key,
                   "--instance-id", instance[:64], "--scheduler", CHILD_SCHEDULER,
                   "--spool-dir", o.spool_dir, "--run-id", planned.run_id, "--log-level", o.log_level,
                   "--parent-run-id", self.run_id, "--workflow-path", planned.row.Path, "--attempt", str(attempt)]
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
            planned.file_count, planned.size = (child.FileCount, child.Bytes) if child else (None, None)
            words = "succeeded" if status == "SUCCESS" else "was killed" if reason == "KILLED" else "failed"
            job_log.summary(f"'{planned.name}' {words}" + (f", return code {code}." if code is not None else ".")
                            + (f" {child.ErrorMessage}" if status == "FAILED" and child and child.ErrorMessage else ""))
            self._react(planned, child)

    # --- Reactions (engine/reactions.py) ---

    def _react(self, planned: Planned, child: Optional[JobRun]) -> None:
        """Carries out the job's Reactions to how it ended. A killed job's are not: someone stopped it."""
        row = planned.row
        if not planned.rules or row.Reason == "KILLED" or self.killing:
            return
        verdict = judge(planned.rules, row.Status, row.ReturnCode,
                        lambda act: self.times_used[(row.Path, act.id)], in_workflow=True)
        for act in verdict.used_up:
            self._event(planned, child, act, "LIMIT_REACHED",
                        f"'{planned.name}': {act.words()} has already run {_count(range(act.max_times), 'time')}, "
                        f"its limit, so the next Reaction that holds applies.")
        if verdict.deciding:
            job_log.summary(f"'{planned.name}': {verdict.deciding.when_words()}, so, as its Reactions say: "
                            + ", ".join(a.words() for a in verdict.decisions) + ".")
        for act in verdict.decisions:
            self._decide(planned, child, act)
        for act in verdict.side_effects:
            self._side_effect(planned, child, act)

    def _decide(self, planned: Planned, child: Optional[JobRun], act: Act) -> None:
        if act.action in ("COUNT_AS_SUCCEEDED", "COUNT_AS_FAILED"):
            message = self._count_as(planned, child, "SUCCESS" if act.action == "COUNT_AS_SUCCEEDED" else "FAILED")
        elif act.action == "SKIP":
            message = self._skip([self.by_name[act.target_item]], f"skipped by '{planned.name}'")
        elif act.action == "SKIP_BRANCH":
            message = self._skip(self._branch(planned), f"the rest of the branch after '{planned.name}'")
        elif act.action == "RERUN":
            message = self._rerun([planned], planned, act)
        elif act.action == "RERUN_FROM":
            message = self._rerun(self._between(self.by_name[act.target_item], planned), planned, act)
        else:
            self._kill(f"'{planned.name}' killed the workflow, as its Reactions say")
            message = "Killed the workflow."
        self._event(planned, child, act, "TOOK_EFFECT", message)

    def _count_as(self, planned: Planned, child: Optional[JobRun], status: str) -> str:
        row = planned.row
        if row.Status == status:
            return f"'{planned.name}' already {outcome_words(row)}."
        row.StatusBeforeOverride, row.Status = row.Status, status
        if child is not None:
            child.StatusBeforeOverride, child.Status = child.StatusBeforeOverride or row.StatusBeforeOverride, status
        return f"'{planned.name}' counted as {'succeeded' if status == 'SUCCESS' else 'failed'}."

    def _skip(self, targets: List[Planned], why: str) -> str:
        skipped = [p for p in targets if p.row.Status in NOT_STARTED]
        for p in skipped:
            p.row.Status, p.row.EndedDateTime = "SKIPPED", utcnow()
        return f"Skipped ({why}): {', '.join(p.name for p in skipped) or 'nothing not yet started'}."

    def _rerun(self, chain: List[Planned], planned: Planned, act: Act) -> str:
        """Runs the chain again, each a new attempt, the first after the action's wait."""
        self.times_used[(planned.row.Path, act.id)] += 1
        for p in chain:
            if p.row.Status == "RUNNING":
                continue                    # still going: its own end stands
            p.row.Status, p.row.ReturnCode, p.row.Reason, p.row.StatusBeforeOverride = "PENDING", None, None, None
            p.row.EndedDateTime, p.process, p.file_count, p.size = None, None, None, None
            p.held.clear()
            for o in p.outside:
                o.forget()
        chain[0].start_after = time.time() + act.wait_seconds
        used = self.times_used[(planned.row.Path, act.id)]
        wait = f" after {act.wait_seconds} s" if act.wait_seconds else ""
        return (f"Rerunning {', '.join(p.name for p in chain)}{wait} "
                f"(rerun {used} of at most {act.max_times}).")

    def _downstream(self, planned: Planned) -> List[Planned]:
        """Every job that waits for this one, directly or not."""
        found, queue = [], [planned.name]
        while queue:
            name = queue.pop()
            for p in self.items:
                if p not in found and any(target == name for target, _t, _c in p.prerequisites):
                    found.append(p)
                    queue.append(p.name)
        return [p for p in self.items if p in found]

    def _branch(self, planned: Planned) -> List[Planned]:
        """
        What waits for this job, directly or not, except the jobs that wait for the outcome it had
        (a failure path, a clean-up waiting for it to end) and what follows them: those still run.
        """
        row = planned.row
        handlers = [p for p in self.items if any(
            target == planned.name and prerequisite_state(test, codes, row.Status, row.ReturnCode) == HOLDS
            for target, test, codes in p.prerequisites)]
        kept = {p.name for h in handlers for p in [h] + self._downstream(h)}
        return [p for p in self._downstream(planned) if p.name not in kept]

    def _between(self, start: Planned, end: Planned) -> List[Planned]:
        """start, and every job on a path from it to end, end included, in outline order."""
        after_start = {p.name for p in self._downstream(start)}
        before_end = {p.name for p in self.items if end in self._downstream(p)}
        names = {start.name, end.name} | (after_start & before_end)
        return [start] + [p for p in self.items if p.name in names and p is not start]

    def _side_effect(self, planned: Planned, child: Optional[JobRun], act: Act) -> None:
        o = self.options
        instance = start_workflow(act.target_job, o.spool_dir, o.api_url, o.working_root, o.log_level)
        self._event(planned, child, act, "TOOK_EFFECT", f"Started workflow '{act.target_job}', instance {instance}.")

    def _event(self, planned: Planned, child: Optional[JobRun], act: Act, result: str, message: str) -> None:
        self.db.add(ReactionEvent(JobRun_id=child.id if child else self.record.id, WorkflowRun_id=self.record.id,
                                  WorkflowPath=planned.row.Path, ReactionAction_id=act.id, Action=act.action,
                                  Result=result, Message=message))
        (job_log.warning if result == "LIMIT_REACHED" else job_log.summary)(message)

    def _outcome(self, planned: Planned, exit_code: int) -> Tuple[str, Optional[int], Optional[str], Optional[JobRun]]:
        """How the job ended, from its run's record; failing that, from its runner's exit code."""
        child = self._child_run(planned)
        if child is not None and child.EndedDateTime is not None:
            _remove(planned.output_path)
            return child.Status, child.ReturnCode, child.Reason, child
        if planned.kill_sent or exit_code < 0:      # a negative exit code: a signal stopped it
            _remove(planned.output_path)
            job_log.warning(f"'{planned.name}' was killed before it could record anything.")
            return "FAILED", None, "KILLED", child
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

def _it(names: List[str]) -> str:
    return "it" if len(names) == 1 else "them"


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


def run_workflow(db: Session, workflow: Job, options: RunOptions, own: Optional[OwnReactions] = None) -> int:
    """Runs the workflow once. own: its own Reactions, when it runs on its own (not inside another)."""
    runner = WorkflowRunner(db, workflow, options)
    runner.own = own
    return runner.run()

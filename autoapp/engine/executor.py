"""
Runs a job's steps, checked and prepared by core/preflight.py, in order: each step
once, the steps inside an If on the branch its conditions choose, and those inside a
For Each File or a While once for each pass (see docs/FLOW_CONTROL.md).

After each step it records the step's outputs (Status and the rest) under its
StepName, for %{...} in the steps after it. When a step fails, its On failure says
what happens: the job fails (FAIL_JOB), goes on (CONTINUE), or ends at once with
success (END_SUCCESS).
"""
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from core import conditions, job_log
from core.control_file import ControlRecord, Journal, NullControl
from core.handlers.file_tools import matching_files, plural
from core.preflight import PreparedStep
from core.run_context import RunContext, file_object, references, shown_time
from core.scope_engine import ScopeResolutionEngine
from core.step_catalog import NOT_DONE, WhatItKnew, normalize_parameters
from core.step_params import LoopFolder, ResolvedStep, resolve_step
from core.telemetry_client import LocalSpoolTelemetryClient

# A step parameter every step type accepts: the job log level for that step alone
LOG_LEVEL_PARAM = "LogLevel"

# What running a list of steps leads to: go on with what comes next, or end the job with success now
CONTINUE, END = "CONTINUE", "END"


def _passes(count: int) -> str:
    return f"{count} pass" if count == 1 else f"{count} passes"


class JobFailed(Exception):
    """A step failed and its On failure is to fail the job. Passes through the blocks around it."""


class Executor:
    def __init__(self, db: Session, scope_engine: ScopeResolutionEngine, telemetry: LocalSpoolTelemetryClient,
                 after_step: Callable[[], None], control=None, resume: Optional[ControlRecord] = None,
                 count_as_done: Optional[str] = None, start_at: Optional[int] = None, skip: Optional[Set[str]] = None,
                 attempt: int = 1):
        self.db, self.scope_engine, self.telemetry = db, scope_engine, telemetry
        self.after_step = after_step            # sends what the step recorded
        self.control = control or NullControl() # what this run keeps so a later attempt can pick up (core/control_file.py)
        self.resume = resume                    # the earlier attempt's record, when this run picks up where it stopped
        self.count_as_done = count_as_done      # the key of a step the operator says to count as done, not run again
        self.start_at = start_at                # Advanced: the top-level step the run starts at; unfinished ones before it are passed over
        self.skip = skip or set()               # Advanced: numbers of top-level steps not to run
        self.attempt = attempt                  # which attempt of the job this is; a step may be told (Simulate's FailUntilAttempt)
        self.context = RunContext()
        self.loops: List[LoopFolder] = []       # the folders of the For Each File loops the run is inside
        self.passes: List[Tuple[str, str]] = [] # each of those loops' pass: ("File 2 of 5: a.csv", "2")
        self.job_return_code: Optional[int] = None  # the last return code a step set for the job, if any did
        if resume:
            self._restore_outputs(resume)

    def _restore_outputs(self, resume: ControlRecord) -> None:
        """Brings back what the earlier attempt's finished steps left for the steps after them."""
        for record in resume.ended_steps():
            if record.get("name") and not record.get("skipped"):
                self.context.record(record["name"], record.get("outputs") or {})
            if record.get("return_code") is not None:
                self.job_return_code = record["return_code"]

    def _key(self, prepared: PreparedStep) -> str:
        """The step's place in the job, with the pass of each loop around it, as the control file names it."""
        return f"{prepared.number}|{'.'.join(number for _, number in self.passes)}"

    # ---------- Running steps ----------

    def run_all(self, steps: List[PreparedStep]) -> str:
        for prepared in steps:
            if self.run(prepared) == END:
                return END
        return CONTINUE

    def run(self, prepared: PreparedStep) -> str:
        """Runs one step, and whatever is inside it. Returns CONTINUE or END; raises JobFailed."""
        key = self._key(prepared)
        earlier = self.resume.finished(key) if self.resume else None
        if earlier:
            job_log.summary(f"{self._label(prepared)}: " + ("skipped in the earlier attempt, so it is not run" if earlier.get("skipped")
                            else "finished in the earlier attempt, so it is not run") + " again.")
            return END if earlier.get("signal") == END else CONTINUE
        if key == self.count_as_done:
            return self._count_as_done(prepared, key)
        passed_over = self._passed_over(prepared)
        if passed_over:
            return self._skip(prepared, key, passed_over)
        started, timer, own = datetime.now(), time.perf_counter(), {}
        self.control.write("begin", key=key, name=prepared.step.StepName)
        try:
            signal = self._perform(prepared, own)
        except JobFailed:
            raise
        except Exception as e:
            self._record(prepared, own, started, timer, error=e)
            if not hasattr(e, "knew"):
                self._note_failed(prepared, e, None)
            return self._after_failure(prepared, e, key)
        self._record(prepared, own, started, timer)
        self._note_end(prepared, key, signal)
        return signal

    def _passed_over(self, prepared: PreparedStep) -> Optional[str]:
        """Why the operator's Advanced choice has this top-level step not run, in words, or None."""
        number = prepared.number
        if "." in number:
            return None
        if number in self.skip:
            return "the operator chose to skip it"
        if self.start_at is not None and int(number) < self.start_at:
            return f"the operator chose to start at step {self.start_at}, and it had not finished"
        return None

    def _skip(self, prepared: PreparedStep, key: str, why: str) -> str:
        """The step does not run: it ends as not run, has no outputs (%{Name.Status} reads SKIPPED), and the job goes on."""
        job_log.summary(f"{self._label(prepared)}: skipped, as {why}.")
        self.control.write("end", key=key, name=prepared.step.StepName, done=True, skipped=True, signal=CONTINUE,
                           outputs=None, return_code=self.job_return_code)
        self.context.outputs.pop(prepared.step.StepName, None)
        return CONTINUE

    def _count_as_done(self, prepared: PreparedStep, key: str) -> str:
        """The operator said this step did its work, though it failed without saying: it is not run again."""
        job_log.summary(f"{self._label(prepared)}: counted as done, as the operator chose; it is not run again.")
        name = prepared.step.StepName
        if name:
            self.context.record(name, {"Status": "SUCCESS", "ReturnCode": 0, "ErrorMessage": None})
        self._note_end(prepared, key, CONTINUE)
        return CONTINUE

    def _note_end(self, prepared: PreparedStep, key: str, signal: str) -> None:
        """The step ended and the job goes on past it: what a later attempt needs of it."""
        name = prepared.step.StepName
        self.control.write("end", key=key, name=name, done=True, signal=signal,
                           outputs=self.context.outputs.get(name) if name else None, return_code=self.job_return_code)

    def _note_failed(self, prepared: PreparedStep, error: BaseException, handler) -> None:
        """What the failed step knew about its effect. A step that never got as far as its handler did nothing."""
        knew = handler.what_failed_step_knew(error) if handler else WhatItKnew(NOT_DONE, "it failed before it did anything")
        error.knew = knew
        self.control.write("failed", key=self._key(prepared), step=prepared.number, title=prepared.step.Title,
                           knew=knew.answer, why=knew.why, operator_decides=knew.operator_decides,
                           stopped=not isinstance(error, Exception))

    def _perform(self, prepared: PreparedStep, own: Dict[str, Any]) -> str:
        work = {"IF": self._run_if, "FOR_EACH_FILE": self._run_for_each, "WHILE": self._run_while}.get(prepared.code)
        if work is None:
            self._run_leaf(prepared, own)
            return CONTINUE
        with job_log.level_for_step(prepared.resolved.params.get(LOG_LEVEL_PARAM)):
            job_log.detail(f"BEGIN {self._label(prepared)}")
            signal, outcome = work(prepared, own)
            job_log.summary(f"END {self._label(prepared)}: {outcome}")
        return signal

    def _after_failure(self, prepared: PreparedStep, error: Exception, key: str) -> str:
        choice = prepared.step.OnFailure or "FAIL_JOB"
        if choice == "CONTINUE":
            job_log.warning(f"{prepared.name} failed, and the job carries on, as its On failure says: {error}")
            signal = CONTINUE
        elif choice == "END_SUCCESS":
            job_log.summary(f"{prepared.name} failed, so the job ends here with success, as its On failure says: {error}")
            signal = END
        else:
            raise JobFailed(str(error)) from error
        self._note_end(prepared, key, signal)
        return signal

    def _record(self, prepared: PreparedStep, own: Dict[str, Any], started: datetime, timer: float,
                error: Optional[Exception] = None) -> None:
        """The step's outputs, for %{StepName...} in the steps after it."""
        if not prepared.step.StepName:
            return
        self.context.record(prepared.step.StepName, {
            "Status": "FAILED" if error else "SUCCESS",
            "ReturnCode": 1 if error else 0,
            "ErrorMessage": str(error) if error else None,
            "StartTime": shown_time(started),
            "EndTime": shown_time(datetime.now()),
            "DurationMs": int((time.perf_counter() - timer) * 1000),
            **own,
        })

    # ---------- One ordinary step ----------

    def _resolve(self, prepared: PreparedStep) -> ResolvedStep:
        """The step's parameters as they stand now: %{...} filled in from the run so far."""
        return resolve_step(prepared.step, prepared.handler_cls, self.scope_engine, self.db,
                            context=self.context, loops=self.loops, label=prepared.name)

    def _run_leaf(self, prepared: PreparedStep, own: Dict[str, Any]) -> None:
        step, handler = prepared.step, None
        try:
            resolved = self._resolve(prepared)
            raw_params = {p.ParamName: p.ParamValue for p in step.parameters if p.ParamName != LOG_LEVEL_PARAM}
            step_log_level = resolved.params.pop(LOG_LEVEL_PARAM, None)
            handler = prepared.handler_cls(step_config=self._config(prepared, resolved, raw_params),
                                           telemetry_client=self.telemetry)
            with job_log.level_for_step(step_log_level):
                handler.run(resolved.params)
        except BaseException as e:      # a Kill too: the step says what it knew as it stops
            self._note_failed(prepared, e, handler)
            raise
        finally:
            if handler is None:
                return
            own.update(handler.outputs)
            if handler.job_return_code is not None:
                self.job_return_code = handler.job_return_code
            # Send what this step recorded; a failure here never affects the job
            self.after_step()

    def _config(self, prepared: PreparedStep, resolved: ResolvedStep, raw_params: Dict[str, Any]) -> Dict[str, Any]:
        step = prepared.step
        return {
            "StepID": step.id, "StepOrder": int(prepared.number.split(".")[0]), "StepNumber": prepared.number,
            "Iteration": ".".join(number for _, number in self.passes) or None,
            "PassLabel": ", ".join(label for label, _ in self.passes) or None,
            "StepType": step.step_type.TypeName, "Title": step.Title, "RawParams": raw_params,
            "SourceEndpointID": resolved.source_endpoint_id, "DestEndpointID": resolved.dest_endpoint_id,
            "Journal": Journal(self.control, self.resume, self._key(prepared)), "Attempt": self.attempt,
        }

    def _label(self, prepared: PreparedStep) -> str:
        label = f"Step {prepared.number}: {prepared.step.Title} ({prepared.step.step_type.TypeName})"
        passes = ", ".join(label for label, _ in self.passes)
        return f"{label} [{passes}]" if passes else label

    # ---------- Conditions ----------

    def _value_of(self, placeholder: str) -> Any:
        if placeholder.startswith("${"):
            return self.scope_engine.interpolate(placeholder)
        (name, prop), = references(placeholder)
        return self.context.value(name, prop or None)

    def _holds(self, prepared: PreparedStep, who: Optional[str] = None) -> bool:
        """Whether a step's condition holds now, logged with the values it used."""
        text = next(p.ParamValue for p in prepared.step.parameters if p.ParamName == "Condition")
        result, used, warnings = conditions.evaluate(text, self._value_of)
        for warning in warnings:
            job_log.warning(f"{who or prepared.name}: {warning}")
        values = f", with {', '.join(used)}" if used else ""
        job_log.detail(f"    {who or 'Condition'}: {text}  is {'true' if result else 'false'}{values}")
        return result

    # ---------- Block steps ----------

    def _run_if(self, prepared: PreparedStep, own: Dict[str, Any]) -> Tuple[str, str]:
        """Runs the Then of the first condition that holds, or the Else if none does."""
        key = self._key(prepared)
        chosen = self.resume.branch(key) if self.resume else None
        if chosen is None:
            chosen = self._choose_branch(prepared)
            self.control.write("branch", key=key, branch=chosen)
        else:
            job_log.detail(f"    The earlier attempt took the {chosen.title()} branch, so its condition is not asked again.")
        return self._run_branch(prepared, chosen)

    def _choose_branch(self, prepared: PreparedStep) -> str:
        """THEN, ELSEIF n, ELSE, or NONE when no condition holds."""
        _, *others = prepared.children
        if self._holds(prepared):
            return "THEN"
        for position, branch in enumerate(others, start=1):
            if branch.code == "ELSEIF" and self._holds(branch, who=f"ElseIf {position}"):
                return f"ELSEIF {position}"
            if branch.code == "ELSE":
                return "ELSE"
        return "NONE"

    def _run_branch(self, prepared: PreparedStep, chosen: str) -> Tuple[str, str]:
        then, *others = prepared.children
        if chosen == "THEN":
            return self.run_all(then.children), "took the Then branch."
        if chosen.startswith("ELSEIF"):
            position = int(chosen.split()[1])
            return self.run_all(others[position - 1].children[0].children), f"took the ElseIf {position} branch."
        if chosen == "ELSE":
            return self.run_all(next(b for b in others if b.code == "ELSE").children), "took the Else branch."
        return CONTINUE, "no condition held, so no branch ran."

    def _parameters(self, prepared: PreparedStep) -> Tuple[Dict[str, Any], ResolvedStep]:
        resolved = self._resolve(prepared)
        return normalize_parameters(prepared.handler_cls.parameters(), resolved.params), resolved

    def _run_for_each(self, prepared: PreparedStep, own: Dict[str, Any]) -> Tuple[str, str]:
        params, resolved = self._parameters(prepared)
        pattern, item = params["Source"], params["ItemName"]
        key = self._key(prepared)
        files = self.resume.files(key) if self.resume else None     # the earlier attempt's list, as matched then
        if files is None:
            files = matching_files(pattern)
            if files:
                self.control.write("files", key=key, files=files)
        own["FileCount"] = len(files)
        if not files:
            if not params["AllowNoFiles"]:
                raise FileNotFoundError(f"No files matched '{pattern}'. If that is acceptable for this step, "
                                        f"set AllowNoFiles to True.")
            return CONTINUE, f"no files matched '{pattern}', so there was nothing to do."
        job_log.detail(f"    {plural(len(files), 'file')} matched '{pattern}'")

        ended = self.resume.passes_ended(key) if self.resume else 0
        unfinished = self.resume.open_pass(key) if self.resume else None
        outer = self.context.files.get(item)        # a loop inside another may reuse its file's name
        try:
            for index, path in enumerate(files, start=1):
                if index <= ended:
                    continue                        # its pass finished in the earlier attempt
                earlier = unfinished.get("file") if unfinished and unfinished["n"] == index else None
                if not earlier and not os.path.isfile(path):
                    job_log.warning(f"{prepared.name}: '{path}' is no longer there, so it was passed over.")
                    self.control.write("pass_end", key=key, n=index, passed_over=True)
                    continue
                # The pass the earlier attempt stopped in keeps the file as it was then: a step may have moved it
                self.context.files[item] = earlier or file_object(path, index, len(files))
                pass_label = f"{item} {index} of {len(files)}: {os.path.basename(path)}"
                if self._one_pass(prepared, pass_label, str(index),
                                  LoopFolder(os.path.dirname(os.path.abspath(path)), resolved.source_endpoint_id),
                                  file=self.context.files[item]) == END:
                    return END, f"ended the job during the pass for '{os.path.basename(path)}'."
        finally:
            if outer is None:
                self.context.files.pop(item, None)
            else:
                self.context.files[item] = outer
        return CONTINUE, f"went through {plural(len(files), 'file')}."

    def _one_pass(self, prepared: PreparedStep, label: str, number: str, folder: Optional[LoopFolder] = None,
                  file: Optional[Dict[str, Any]] = None) -> str:
        """Runs a loop's steps once, with the pass named in the log and on each operation."""
        key = self._key(prepared)               # the loop's own place, before this pass is added to it
        self.control.write("pass_begin", key=key, n=int(number), label=label, file=file)
        self.passes.append((label, number))
        if folder:
            self.loops.append(folder)
        try:
            signal = self.run_all(prepared.children)
        finally:
            self.passes.pop()
            if folder:
                self.loops.pop()
        self.control.write("pass_end", key=key, n=int(number))
        return signal

    def _run_while(self, prepared: PreparedStep, own: Dict[str, Any]) -> Tuple[str, str]:
        params, _ = self._parameters(prepared)
        most, wait = params["MaxIterations"], params["WaitSeconds"]
        key = self._key(prepared)
        # Picking up: the passes that ended count, and one that had started goes on without asking the condition
        passes = own["Passes"] = self.resume.passes_ended(key) if self.resume else 0
        going_on = bool(self.resume and self.resume.open_pass(key))
        if prepared.step.StepName:              # so its condition can read %{Name.Passes} before the first pass
            self.context.record(prepared.step.StepName, {"Passes": passes})
        while going_on or self._holds(prepared):
            if not going_on:
                if passes >= most:
                    raise RuntimeError(f"The condition still held after {_passes(most)}, the most its "
                                       f"MaxIterations allows.")
                if passes and wait:
                    time.sleep(wait)
            going_on = False
            passes = own["Passes"] = passes + 1
            if prepared.step.StepName:          # so the steps inside can read %{Name.Passes} as it goes
                self.context.record(prepared.step.StepName, {"Passes": passes})
            if self._one_pass(prepared, f"pass {passes}", str(passes)) == END:
                return END, f"ended the job during pass {passes}."
        return CONTINUE, f"the condition no longer holds, after {_passes(passes)}."

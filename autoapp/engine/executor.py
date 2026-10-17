"""
Runs a job's steps, checked and prepared by engine/preflight.py, in order: each step
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
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from engine import conditions, job_log
from engine.handlers.file_tools import matching_files, plural
from engine.preflight import PreparedStep
from engine.run_context import RunContext, file_object, references, shown_time
from engine.scope_engine import ScopeResolutionEngine
from engine.step_catalog import normalize_parameters
from engine.step_params import LoopFolder, ResolvedStep, resolve_step
from engine.telemetry_client import LocalSpoolTelemetryClient

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
                 after_step: Callable[[], None]):
        self.db, self.scope_engine, self.telemetry = db, scope_engine, telemetry
        self.after_step = after_step            # sends what the step recorded
        self.context = RunContext()
        self.loops: List[LoopFolder] = []       # the folders of the For Each File loops the run is inside
        self.passes: List[Tuple[str, str]] = [] # each of those loops' pass: ("File 2 of 5: a.csv", "2")

    # ---------- Running steps ----------

    def run_all(self, steps: List[PreparedStep]) -> str:
        for prepared in steps:
            if self.run(prepared) == END:
                return END
        return CONTINUE

    def run(self, prepared: PreparedStep) -> str:
        """Runs one step, and whatever is inside it. Returns CONTINUE or END; raises JobFailed."""
        started, timer, own = datetime.now(), time.perf_counter(), {}
        try:
            signal = self._perform(prepared, own)
        except JobFailed:
            raise
        except Exception as e:
            self._record(prepared, own, started, timer, error=e)
            return self._after_failure(prepared, e)
        self._record(prepared, own, started, timer)
        return signal

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

    def _after_failure(self, prepared: PreparedStep, error: Exception) -> str:
        choice = prepared.step.OnFailure or "FAIL_JOB"
        if choice == "CONTINUE":
            job_log.warning(f"{prepared.name} failed, and the job carries on, as its On failure says: {error}")
            return CONTINUE
        if choice == "END_SUCCESS":
            job_log.summary(f"{prepared.name} failed, so the job ends here with success, as its On failure says: {error}")
            return END
        raise JobFailed(str(error)) from error

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
        step = prepared.step
        resolved = self._resolve(prepared)
        raw_params = {p.ParamName: p.ParamValue for p in step.parameters if p.ParamName != LOG_LEVEL_PARAM}
        step_log_level = resolved.params.pop(LOG_LEVEL_PARAM, None)
        handler = prepared.handler_cls(step_config=self._config(prepared, resolved, raw_params),
                                       telemetry_client=self.telemetry)
        try:
            with job_log.level_for_step(step_log_level):
                handler.run(resolved.params)
        finally:
            own.update(handler.outputs)
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
        then, *others = prepared.children
        if self._holds(prepared):
            return self.run_all(then.children), "took the Then branch."
        for position, branch in enumerate(others, start=1):
            if branch.code == "ELSEIF" and self._holds(branch, who=f"ElseIf {position}"):
                return self.run_all(branch.children[0].children), f"took the ElseIf {position} branch."
            if branch.code == "ELSE":
                return self.run_all(branch.children), "took the Else branch."
        return CONTINUE, "no condition held, so no branch ran."

    def _parameters(self, prepared: PreparedStep) -> Tuple[Dict[str, Any], ResolvedStep]:
        resolved = self._resolve(prepared)
        return normalize_parameters(prepared.handler_cls.parameters(), resolved.params), resolved

    def _run_for_each(self, prepared: PreparedStep, own: Dict[str, Any]) -> Tuple[str, str]:
        params, resolved = self._parameters(prepared)
        pattern, item = params["Source"], params["ItemName"]
        files = matching_files(pattern)
        own["FileCount"] = len(files)
        if not files:
            if not params["AllowNoFiles"]:
                raise FileNotFoundError(f"No files matched '{pattern}'. If that is acceptable for this step, "
                                        f"set AllowNoFiles to True.")
            return CONTINUE, f"no files matched '{pattern}', so there was nothing to do."
        job_log.detail(f"    {plural(len(files), 'file')} matched '{pattern}'")

        outer = self.context.files.get(item)        # a loop inside another may reuse its file's name
        try:
            for index, path in enumerate(files, start=1):
                if not os.path.isfile(path):
                    job_log.warning(f"{prepared.name}: '{path}' is no longer there, so it was passed over.")
                    continue
                self.context.files[item] = file_object(path, index, len(files))
                pass_label = f"{item} {index} of {len(files)}: {os.path.basename(path)}"
                if self._one_pass(prepared, pass_label, str(index),
                                  LoopFolder(os.path.dirname(os.path.abspath(path)), resolved.source_endpoint_id)) == END:
                    return END, f"ended the job during the pass for '{os.path.basename(path)}'."
        finally:
            if outer is None:
                self.context.files.pop(item, None)
            else:
                self.context.files[item] = outer
        return CONTINUE, f"went through {plural(len(files), 'file')}."

    def _one_pass(self, prepared: PreparedStep, label: str, number: str, folder: Optional[LoopFolder] = None) -> str:
        """Runs a loop's steps once, with the pass named in the log and on each operation."""
        self.passes.append((label, number))
        if folder:
            self.loops.append(folder)
        try:
            return self.run_all(prepared.children)
        finally:
            self.passes.pop()
            if folder:
                self.loops.pop()

    def _run_while(self, prepared: PreparedStep, own: Dict[str, Any]) -> Tuple[str, str]:
        params, _ = self._parameters(prepared)
        most, wait = params["MaxIterations"], params["WaitSeconds"]
        passes = own["Passes"] = 0
        if prepared.step.StepName:              # so its condition can read %{Name.Passes} before the first pass
            self.context.record(prepared.step.StepName, {"Passes": 0})
        while self._holds(prepared):
            if passes >= most:
                raise RuntimeError(f"The condition still held after {_passes(most)}, the most its "
                                   f"MaxIterations allows.")
            if passes and wait:
                time.sleep(wait)
            passes = own["Passes"] = passes + 1
            if prepared.step.StepName:          # so the steps inside can read %{Name.Passes} as it goes
                self.context.record(prepared.step.StepName, {"Passes": passes})
            if self._one_pass(prepared, f"pass {passes}", str(passes)) == END:
                return END, f"ended the job during pass {passes}."
        return CONTINUE, f"the condition no longer holds, after {_passes(passes)}."

"""
Turns a JobStep's stored parameters into the values a handler runs with.

File locations follow one rule: a location outside the job's working folder
must be a registered Endpoint. For a handler path parameter such as "Source",
a step sets exactly one of:

    Source          a raw path, which must be inside the working folder
                    (a relative path is taken relative to the working folder)
    SourceEndpoint  the Name of a row in the Endpoints table

An Endpoint's Path and FilenamePattern are interpolated in that Endpoint's own
context, so ${APP.x} and ${ENTITY.x} mean its Application and its Site's Entity.

Inside a For Each File loop, a raw path may also lie in the folder the loop reads
from (a LoopFolder), so a step can take the loop's file wherever it is; its
operations then point at the loop's endpoint, so the trace follows the file.

A value with a %{...} (a step's output, a loop's file) is filled in when the step
runs (context given). Before the run there is no context: such a value is left
as it is, its type and location checked only when the step runs.
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from core.models import Endpoint, JobStep
from engine.rename_mask import check_mask
from engine.run_context import RunContext
from engine.scope_engine import ScopeResolutionEngine
from engine.step_catalog import check_parameters, holds_run_value, normalize_parameters


@dataclass
class ResolvedStep:
    params: Dict[str, Any] = field(default_factory=dict)
    source_endpoint_id: Optional[int] = None
    dest_endpoint_id: Optional[int] = None


@dataclass(frozen=True)
class LoopFolder:
    """The folder a For Each File loop reads from, and its endpoint's id (None in the working folder)."""
    path: str
    endpoint_id: Optional[int] = None


def _inside(root: str, full: str) -> bool:
    return os.path.commonpath([os.path.abspath(root), full]) == os.path.abspath(root)


def _loop_path(path: str, loops: Sequence[LoopFolder]) -> Optional[Tuple[str, Optional[int]]]:
    """An absolute path in the folder of a loop around the step, with that loop's endpoint id."""
    if not os.path.isabs(path):
        return None
    full = os.path.abspath(path)
    for loop in reversed(loops):            # the innermost loop first
        if _inside(loop.path, full):
            return full, loop.endpoint_id
    return None


def _working_folder_path(path: str, param_name: str, working_folder: Optional[str]) -> str:
    """Returns the absolute form of a raw path, refusing anything outside the working folder."""
    if not working_folder:
        raise ValueError(
            f"'{param_name}' is a raw path, but no working folder is configured "
            f"(set AUTOAPP_WORKING_ROOT or pass --working-root). "
            f"Use {param_name}Endpoint for a location outside the working folder."
        )
    root = os.path.abspath(working_folder)
    full = os.path.abspath(os.path.join(root, path))
    if os.path.commonpath([root, full]) != root:
        raise ValueError(
            f"'{param_name}' path '{path}' is outside the job's working folder ({root}). "
            f"Register it as an Endpoint and reference it with {param_name}Endpoint."
        )
    return full


def _endpoint_path(db: Session, name: str, param_name: str, role: str,
                   handler_cls: Any, scope_engine: ScopeResolutionEngine):
    endpoint = db.query(Endpoint).filter(Endpoint.Name == name).first()
    if not endpoint:
        raise ValueError(f"'{param_name}Endpoint' refers to Endpoint '{name}', which is not registered.")
    if endpoint.site and not getattr(handler_cls, "SUPPORTS_REMOTE_SITES", False):
        raise ValueError(
            f"Endpoint '{name}' is on Site '{endpoint.site.Name}' ({endpoint.site.Protocol}); "
            f"this step type can only reach local paths."
        )

    path = scope_engine.interpolate(endpoint.Path, endpoint=endpoint)
    if role == "source":
        pattern = scope_engine.interpolate(endpoint.FilenamePattern, endpoint=endpoint)
        path = os.path.join(path, pattern)
    return endpoint, path


def _raw_location(raw_path: str, param_name: str, scope_engine: ScopeResolutionEngine,
                  context: Optional[RunContext], loops: Sequence[LoopFolder]) -> Tuple[str, Optional[int]]:
    """A raw path's full form, and the endpoint id of the loop folder it lies in, if it lies in one."""
    path = scope_engine.interpolate(raw_path)
    if context is None and holds_run_value(path):
        return path, None                   # only the run can say where it is
    if context is not None:
        path = context.fill_in(path)
    in_loop = _loop_path(path, loops)
    if in_loop:
        return in_loop
    return _working_folder_path(path, param_name, scope_engine.working_folder), None


def _value(value: Any, scope_engine: ScopeResolutionEngine, context: Optional[RunContext], leave: tuple = ()) -> Any:
    value = scope_engine.interpolate(value, leave=leave)
    return context.fill_in(value) if context is not None else value


def resolve_step(step: JobStep, handler_cls: Any, scope_engine: ScopeResolutionEngine, db: Session,
                 context: Optional[RunContext] = None, loops: Sequence[LoopFolder] = (),
                 label: Optional[str] = None) -> ResolvedStep:
    """
    Checks a step's parameters against its step type, interpolates them, resolves
    its file locations, and converts the values for the handler. Raises ValueError,
    naming the step, if anything is wrong.

    handler_cls may be None where the step type has no handler on this machine;
    the parameters are then interpolated but not checked.
    context: the run so far, to fill in %{...}; None before the run, which leaves them.
    loops: the folders of the For Each File loops around the step, innermost last.
    label: how to name the step in a problem, e.g. "Step 3.1 ('Copy')"; by default by its StepOrder.
    """
    raw = {p.ParamName: p.ParamValue for p in step.parameters}
    resolved = ResolvedStep()
    declared = handler_cls.parameters() if handler_cls else None
    path_params = handler_cls.path_params() if handler_cls else {}

    try:
        if declared is not None:
            problems = check_parameters(declared, raw)
            if problems:
                raise ValueError(" ".join(problems))

        for param_name, role in path_params.items():
            endpoint_name = raw.pop(f"{param_name}Endpoint", None)
            raw_path = raw.pop(param_name, None)

            endpoint_id = None
            if endpoint_name:
                endpoint, path = _endpoint_path(db, context.fill_in(endpoint_name) if context else endpoint_name,
                                                param_name, role, handler_cls, scope_engine)
                endpoint_id = endpoint.id
                resolved.params[param_name] = path
            elif raw_path:
                resolved.params[param_name], endpoint_id = _raw_location(
                    raw_path, param_name, scope_engine, context, loops)
            if endpoint_id is not None:
                if role == "source":
                    resolved.source_endpoint_id = endpoint_id
                else:
                    resolved.dest_endpoint_id = endpoint_id

        per_file = {p.name for p in declared or () if p.file_placeholders}
        for name, value in raw.items():
            if name in per_file:
                check_mask(value or "")
                resolved.params[name] = _value(value, scope_engine, context, leave=("FILE",))
            else:
                resolved.params[name] = _value(value, scope_engine, context)

        if declared is not None:
            resolved.params = normalize_parameters(declared, resolved.params)

    except ValueError as e:
        name = label or f"Step {step.StepOrder} ('{step.Title}')"
        raise ValueError(f"{name}: {e}") from e

    return resolved


def preview_step(step: JobStep, handler_cls: Any, scope_engine: ScopeResolutionEngine, db: Session) -> Dict[str, tuple]:
    """
    What each of a step's parameters resolves to, one at a time, for showing beside
    the fields of a form: {parameter name: (resolved text, None) or (None, error)}.
    Unlike resolve_step, a problem with one parameter does not stop the others.
    A location appears under its parameter name ("Source") however the step gave it.
    """
    raw = {p.ParamName: p.ParamValue for p in step.parameters}
    declared = handler_cls.parameters() if handler_cls else ()
    path_params = handler_cls.path_params() if handler_cls else {}
    per_file = {p.name for p in declared if p.file_placeholders}
    preview: Dict[str, tuple] = {}

    for param_name, role in path_params.items():
        endpoint_name = raw.pop(f"{param_name}Endpoint", None)
        raw_path = raw.pop(param_name, None)
        try:
            if endpoint_name and raw_path:
                raise ValueError(f"Set either '{param_name}' or '{param_name}Endpoint', not both.")
            if endpoint_name:
                preview[param_name] = (_endpoint_path(db, endpoint_name, param_name, role, handler_cls, scope_engine)[1], None)
            elif raw_path:
                preview[param_name] = (_raw_location(raw_path, param_name, scope_engine, None, ())[0], None)
        except ValueError as e:
            preview[param_name] = (None, str(e))

    for name, value in raw.items():
        try:
            if name in per_file:
                check_mask(value or "")
                preview[name] = (scope_engine.interpolate(value, leave=("FILE",)), None)
            else:
                preview[name] = (scope_engine.interpolate(value), None)
        except ValueError as e:
            preview[name] = (None, str(e))
    return preview

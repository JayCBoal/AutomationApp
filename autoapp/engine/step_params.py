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
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models import Endpoint, JobStep
from engine.scope_engine import ScopeResolutionEngine


@dataclass
class ResolvedStep:
    params: Dict[str, Any] = field(default_factory=dict)
    source_endpoint_id: Optional[int] = None
    dest_endpoint_id: Optional[int] = None


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


def resolve_step(step: JobStep, handler_cls: Any, scope_engine: ScopeResolutionEngine, db: Session) -> ResolvedStep:
    """Interpolates a step's parameters and resolves its file locations."""
    raw = {p.ParamName: p.ParamValue for p in step.parameters}
    resolved = ResolvedStep()

    try:
        for param_name, role in getattr(handler_cls, "PATH_PARAMS", {}).items():
            endpoint_name = raw.pop(f"{param_name}Endpoint", None)
            raw_path = raw.pop(param_name, None)

            if endpoint_name and raw_path:
                raise ValueError(f"Set either '{param_name}' or '{param_name}Endpoint', not both.")

            if endpoint_name:
                endpoint, path = _endpoint_path(db, endpoint_name, param_name, role, handler_cls, scope_engine)
                if role == "source":
                    resolved.source_endpoint_id = endpoint.id
                else:
                    resolved.dest_endpoint_id = endpoint.id
                resolved.params[param_name] = path
            elif raw_path:
                resolved.params[param_name] = _working_folder_path(
                    scope_engine.interpolate(raw_path), param_name, scope_engine.working_folder
                )

        for name, value in raw.items():
            resolved.params[name] = scope_engine.interpolate(value)

    except ValueError as e:
        raise ValueError(f"Step {step.StepOrder} ('{step.Title}'): {e}") from e

    return resolved

"""
The values a job's run used, kept so a Resume can use them as they were (docs/WORKFLOWS_PHASE7.md, step 2b).

A value is named by a key: a variable's name (`Region` for ${Region}), a scope and a name (`JOB.Region` for
${JOB.Region}) or an environment variable (`ENV:Region` for ${ENV:Region}). What a key stood for is its final
text, with any placeholders inside it filled in. A value that holds a secret is kept by name only, and a
Resume always reads it again.

The control file holds them in a `values` record (engine/control_file.py), written once the job has been
checked and its steps resolved, since only then are all the placeholders the job uses known.
"""
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from core.models import Variable, WorkflowItemVariable
from engine import job_log
from engine.scope_engine import ScopeResolutionEngine

SCOPE_KEY = re.compile(r"^(SYS|APP|ENTITY|JOB|TAG|WORKFLOW|USE)\.(.+)$")


def placeholder(key: str) -> str:
    """The placeholder a key stands for."""
    return "${" + key + "}"


def secret_values(db: Session) -> List[str]:
    """The values of AutoApp's secret variables, for a process that has not told the job log of them."""
    secrets = [value for (value,) in db.query(Variable.VarValue).filter(Variable.IsSecret.is_(True))]
    return secrets + [value for (value,) in db.query(WorkflowItemVariable.VarValue)
                      .filter(WorkflowItemVariable.IsSecret.is_(True))]


def snapshot(engine: ScopeResolutionEngine, secrets: Optional[List[str]] = None) -> Dict[str, dict]:
    """
    Every value the engine's placeholders resolved so far, as {"value": text}, or {"secret": True} where it holds
    a secret: one the job log was told of, or among secrets.
    """
    values: Dict[str, dict] = {}
    for key in list(engine.used):
        try:
            text = engine.interpolate(placeholder(key), leave=("FILE",))
        except ValueError:
            continue                # a value the job could not use anyway; the job will say so
        secret = any(s and s in text for s in secrets) if secrets is not None else job_log.mask(text) != text
        values[key] = {"secret": True} if secret else {"value": text}
    return values


def pins(stored: Dict[str, dict], edits: Optional[Dict[str, str]] = None, keep: bool = True,
         drop: Optional[List[str]] = None) -> Dict[str, str]:
    """
    What a Resume pins: the stored values (unless it refreshes), with the operator's edits over them.
    drop: names of the workflow's or a use's variables that changed; the job's stored copy of each is let go,
    so it reads the changed value (precedence still decides which level wins).
    """
    dropped = {key for name in drop or [] for key in (name, f"WORKFLOW.{name}", f"USE.{name}")}
    pinned = {key: entry["value"] for key, entry in stored.items() if keep and "value" in entry and key not in dropped}
    pinned.update(edits or {})
    return pinned


def edit_problems(stored: Dict[str, dict], edits: Dict[str, str]) -> List[str]:
    """Why these edits cannot be made, in words: a name that was not used, or a secret."""
    problems = []
    for key in edits:
        entry = stored.get(key)
        if entry is None:
            problems.append(f"{key} was not used by the earlier attempt, so there is no value to edit.")
        elif "secret" in entry:
            problems.append(f"{key} is a secret. It is always read when the job runs, and cannot be edited here.")
    return problems


@dataclass
class Change:
    key: str
    was: str
    now: str


def changes(stored: Dict[str, dict], current: Dict[str, dict]) -> List[Change]:
    """The values that read differently now than the earlier attempt had them. Secrets are not compared."""
    found = []
    for key, entry in stored.items():
        now = current.get(key)
        if "value" in entry and now is not None and "value" in now and now["value"] != entry["value"]:
            found.append(Change(key, entry["value"], now["value"]))
    return found

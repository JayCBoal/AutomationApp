"""
What parameters a step type takes, and checking a step's parameters against them.

Each handler declares its parameters once, as a list of Param. Everything else
is driven from that list: the catalog tables the job editor reads
(app/catalog.py), the check made before a job runs, and the conversion of the
stored text into the values a handler works with.

Each handler declares what it leaves behind for later steps the same way, as a
list of Output: what %{StepName.Output} can read once it has run (docs/FLOW_CONTROL.md).

A LOCATION parameter such as "Source" names a place files are read from or
written to. A step fills it in one of two ways, under two names:

    Source          a path inside the job's working folder
    SourceEndpoint  the name of a registered endpoint
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

STRING, BOOLEAN, INTEGER, CHOICE, LOCATION = "STRING", "BOOLEAN", "INTEGER", "CHOICE", "LOCATION"
TEXT = "TEXT"       # a STRING that may run to several lines, such as a SQL statement
SOURCE, DEST = "SOURCE", "DEST"
ENDPOINT_SUFFIX = "Endpoint"

_TRUE, _FALSE = ("true", "yes", "y", "1"), ("false", "no", "n", "0")

# The kinds of value an output holds, so a condition comparing text with a number can be pointed out
NUMBER = "NUMBER"


# What a failed step knew about its own effect, so a later attempt can pick up (docs/WORKFLOWS_PHASE7.md, proposal 3)
NOT_DONE = "NOT_DONE"           # it changed nothing, so it is safe to run again
PARTLY_DONE = "PARTLY_DONE"     # it did part of its work and knows which part, so a later attempt can do the rest
UNKNOWN = "UNKNOWN"             # it is not known whether it changed anything; an operator decides


@dataclass(frozen=True)
class WhatItKnew:
    """What a failed step knew about its effect: one of the three answers, and why, in plain words."""
    answer: str
    why: str = ""
    cannot_finish: bool = False     # partly done, but a later attempt cannot do the rest by itself

    @property
    def operator_decides(self) -> bool:
        """Whether an operator must choose what happens to this step, and no automatic Resume may."""
        return self.answer == UNKNOWN or self.cannot_finish


def holds_run_value(value: Any) -> bool:
    """Whether a stored value has a %{...}, which only the run can fill in."""
    return isinstance(value, str) and "%{" in value


@dataclass(frozen=True)
class Param:
    name: str
    data_type: str = STRING
    description: str = ""
    required: bool = False
    default: Optional[str] = None           # written as it would be typed into the job editor
    location_role: Optional[str] = None     # SOURCE or DEST, for a LOCATION
    choices: Tuple[str, ...] = ()           # the allowed values, for a CHOICE
    file_placeholders: bool = False         # may hold ${FILE:...}, which the handler fills in for each file

    @property
    def endpoint_name(self) -> Optional[str]:
        """The name under which a LOCATION is given as an endpoint, e.g. SourceEndpoint."""
        return self.name + ENDPOINT_SUFFIX if self.data_type == LOCATION else None


@dataclass(frozen=True)
class Output:
    """Something a step leaves behind for later steps, read as %{StepName.Name}."""
    name: str
    data_type: str = STRING                 # STRING or NUMBER
    description: str = ""


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _convert(param: Param, value: Any) -> Any:
    """Turns stored text into the value a handler works with. Raises ValueError if it does not fit the type."""
    if param.data_type == BOOLEAN:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError(f"'{param.name}' must be True or False, not '{value}'.")

    if param.data_type == INTEGER:
        try:
            return int(str(value).strip())
        except ValueError:
            raise ValueError(f"'{param.name}' must be a whole number, not '{value}'.") from None

    if param.data_type == CHOICE:
        for choice in param.choices:
            if str(value).strip().lower() == choice.lower():
                return choice
        raise ValueError(f"'{param.name}' must be one of {', '.join(param.choices)}, not '{value}'.")

    return value


def check_parameters(params: Sequence[Param], stored: Dict[str, Any]) -> List[str]:
    """
    Checks a step's parameters as stored in the job, before any placeholder is
    resolved. Returns one message per problem; an empty list means none.

    A value containing a ${...} placeholder, or a %{...} value from the run, cannot be
    type-checked until the job runs, so only its presence is checked here.
    """
    problems: List[str] = []
    accepted = [p.name for p in params] + [p.endpoint_name for p in params if p.endpoint_name]

    for name in stored:
        if name not in accepted:
            problems.append(f"Unknown parameter '{name}'. This step type accepts: {', '.join(accepted)}.")

    for param in params:
        value = stored.get(param.name)
        if param.data_type == LOCATION:
            endpoint = stored.get(param.endpoint_name)
            if not _is_blank(value) and not _is_blank(endpoint):
                problems.append(f"Set either '{param.name}' or '{param.endpoint_name}', not both.")
            elif param.required and _is_blank(value) and _is_blank(endpoint):
                problems.append(
                    f"'{param.name}' is required: set '{param.name}' (a path inside the working folder) "
                    f"or '{param.endpoint_name}' (a registered endpoint)."
                )
            continue

        if _is_blank(value):
            if param.required:
                problems.append(f"'{param.name}' is required.")
        elif "${" not in str(value) and not holds_run_value(value):
            try:
                _convert(param, value)
            except ValueError as e:
                problems.append(str(e))
    return problems


def normalize_parameters(params: Sequence[Param], resolved: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turns a step's resolved parameters into what its handler receives: defaults
    filled in, text converted to True/False and numbers. By this point each
    LOCATION is a path under its own name, whichever way the step gave it.
    A value still holding a %{...} (checked before the run) is left as text.
    Raises ValueError listing every problem.
    """
    problems: List[str] = []
    known = {p.name for p in params}
    for name in resolved:
        if name not in known:
            problems.append(f"Unknown parameter '{name}'. This step type accepts: {', '.join(sorted(known))}.")

    values: Dict[str, Any] = {}
    for param in params:
        value = resolved.get(param.name)
        if _is_blank(value):
            if param.required:
                problems.append(f"'{param.name}' is required.")
                continue
            value = param.default
            if value is None:
                continue                    # optional, not set, no default: left out
        if holds_run_value(value):
            values[param.name] = value
            continue
        try:
            values[param.name] = _convert(param, value)
        except ValueError as e:
            problems.append(str(e))

    if problems:
        raise ValueError(" ".join(problems))
    return values

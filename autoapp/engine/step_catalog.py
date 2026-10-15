"""
What parameters a step type takes, and checking a step's parameters against them.

Each handler declares its parameters once, as a list of Param. Everything else
is driven from that list: the catalog tables the job editor reads
(app/catalog.py), the check made before a job runs, and the conversion of the
stored text into the values a handler works with.

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

    A value containing a ${...} placeholder cannot be type-checked until the job
    runs, so only its presence is checked here.
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
        elif "${" not in str(value):
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
        try:
            values[param.name] = _convert(param, value)
        except ValueError as e:
            problems.append(str(e))

    if problems:
        raise ValueError(" ".join(problems))
    return values

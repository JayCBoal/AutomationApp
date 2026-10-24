"""
Conditions in a workflow (docs/WORKFLOWS_PHASE4.md): a job's Custom rule, and the workflow's
Succeeds when. They are written in flow control's language (engine/conditions.py), over
%{Name.Output}, where Name is a job in the workflow, and ${...} variables.

Every job in a workflow has the same outputs (OUTPUTS). Until it ends, all of them are unknown
(NULL), so a Custom rule can be decided while some of its jobs still run: true starts the job,
false means it can never start, unknown waits.

A job's prerequisites can also be outside its workflow (docs/WORKFLOWS_PHASE5.md). Each gets a
name of its own, which may hold dots (MONTH_END.Extract): another workflow's job has the same
outputs, as %{MONTH_END.Extract.Status}; files at an endpoint have FileCount and Bytes; and
%{Now.Time}, %{Now.Date} and %{Now.Weekday} are the time. `outside` below is {name: kind}.

Succeeded, Failed and Ended mean exactly what a prerequisite's Outcomes mean: Bypassed counts as
succeeded with return code 0, and Ended includes Not run.
"""
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core import conditions
from core.run_context import shown_time

NUMBER, STRING = conditions.NUMBER, conditions.STRING
FINAL = ("SUCCESS", "FAILED", "NOT_RUN", "DISABLED", "BYPASSED", "SKIPPED")

# Each output: (kind, what it is), in the order the condition box lists them
OUTPUTS: Dict[str, Tuple[str, str]] = {
    "Succeeded": (NUMBER, "True if it succeeded (Bypassed counts as succeeded)"),
    "Failed": (NUMBER, "True if it failed"),
    "Ended": (NUMBER, "True once it has ended in any way, Not run included"),
    "NotRun": (NUMBER, "True if it did not run: its prerequisites could not be met, or it was cancelled"),
    "Skipped": (NUMBER, "True if a Reaction skipped it"),
    "Disabled": (NUMBER, "True if it was disabled, or disabled here to stop"),
    "Bypassed": (NUMBER, "True if it was disabled here to pass through"),
    "Status": (STRING, "SUCCESS, FAILED, NOT_RUN, DISABLED, BYPASSED or SKIPPED"),
    "ReturnCode": (NUMBER, "Its return code: 0 unless a step set one; 1 if it failed"),
    "Reason": (STRING, "Why it ended as it did, such as KILLED or CANCELLED; empty if it succeeded"),
    "FileCount": (NUMBER, "How many files it delivered (wrote to a destination)"),
    "Bytes": (NUMBER, "The size of the files it delivered, added up"),
    "StartTime": (STRING, "When it started, as 2026-10-18 14:03:07, in local time"),
    "EndTime": (STRING, "When it ended, as 2026-10-18 14:03:07, in local time"),
    "DurationMs": (NUMBER, "How long it ran, in milliseconds"),
}

NOW_OUTPUTS = {"Time": "The time of day as 14:05 (24 hours, local time)",
               "Date": "Today's date as 2026-10-19",
               "Weekday": "The day of the week: Monday to Sunday"}
FILE_OUTPUTS = {"FileCount": "How many files match now", "Bytes": "Their size added up"}

# The outputs that are True or False (1 or 0): the builder offers "is true" and "is false" for them
BOOLEANS = ("Succeeded", "Failed", "Ended", "NotRun", "Skipped", "Disabled", "Bypassed")

_REF = re.compile(r"^%\{([^.}]*)(?:\.([^}]*))?\}$")


def split_ref(ref: str, known: Sequence[str] = ()) -> Tuple[str, Optional[str]]:
    """
    %{Extract.FileCount} as ("Extract", "FileCount"); %{Extract} as ("Extract", None). known: names that
    may hold dots, which are tried first, longest first: %{MONTH_END.Extract.Status} is ("MONTH_END.Extract", "Status").
    """
    match = _REF.match(ref)
    if not match:
        return ref, None
    inner = ref[2:-1]
    for name in sorted(known, key=len, reverse=True):
        if inner == name:
            return name, None
        if inner.startswith(name + "."):
            return name, inner[len(name) + 1:] or None
    return match.group(1), match.group(2) or None


def named_jobs(text: str, outside: Sequence[str] = ()) -> List[str]:
    """
    The jobs of the workflow a condition names, in order, once each; the outside targets in outside and
    the time (Now) are not jobs. Raises ValueError for unclosed quotes or braces.
    """
    names = []
    for ref in conditions.references(text):
        if ref.startswith("%{"):
            name, _ = split_ref(ref, outside)
            if name not in names and name not in outside and name != "Now":
                names.append(name)
    return names


def item_values(name: str, status: str, code: Optional[int], reason: Optional[str], file_count: Optional[int],
                size: Optional[int], started: Optional[datetime], ended: Optional[datetime]) -> Dict[str, Any]:
    """Every output of the job named name, as %{name.Output}: all unknown (None) until it has ended."""
    if status not in FINAL:
        return {f"%{{{name}.{output}}}": None for output in OUTPUTS}
    bypassed = status == "BYPASSED"
    values = {
        "Succeeded": status in ("SUCCESS", "BYPASSED"), "Failed": status == "FAILED", "Ended": True,
        "NotRun": status == "NOT_RUN", "Skipped": status == "SKIPPED", "Disabled": status == "DISABLED",
        "Bypassed": bypassed, "Status": status, "ReturnCode": 0 if bypassed else code, "Reason": reason,
        "FileCount": file_count, "Bytes": size,
        "StartTime": _local(started), "EndTime": _local(ended),
        "DurationMs": int((ended - started).total_seconds() * 1000) if started and ended else None,
    }
    return {f"%{{{name}.{output}}}": (int(value) if isinstance(value, bool) else value) for output, value in values.items()}


def _local(moment: Optional[datetime]) -> Optional[str]:
    """A run's time (kept in UTC) as this machine's local time, as a step's StartTime is shown."""
    return shown_time(moment.replace(tzinfo=timezone.utc).astimezone()) if moment else None


def endpoint_values(name: str, file_count: Optional[int], size: Optional[int]) -> Dict[str, Any]:
    """The outputs of files at an endpoint named name, unknown (None) until it holds."""
    return {f"%{{{name}.FileCount}}": file_count, f"%{{{name}.Bytes}}": size}


def reference_problem(ref: str, names: Sequence[str],
                      outside: Optional[Dict[str, str]] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    What is wrong with %{Name.Output} in a workflow whose jobs are names, if anything; and its kind.
    outside: the targets outside the workflow that the job's own prerequisites give names, as {name: kind}.
    """
    outside = outside or {}
    name, output = split_ref(ref, list(outside) + [n for n in names if "." in n])
    if name == "Now":
        if output not in NOW_OUTPUTS:
            return f"{ref}: the time has {', '.join(NOW_OUTPUTS)}, as %{{Now.Time}}.", None
        return None, conditions.STRING
    if name in outside:
        return _outside_problem(ref, name, output, outside[name])
    if name not in names:
        return f"{ref}: no job in this workflow is named {name}.", None
    if output and "." in output and output.split(".")[0] not in OUTPUTS:
        return f"{ref}: nothing inside '{name}' is named '{output.split('.')[0]}'. Only jobs embedded in a workflow can be reached by a path.", None
    if not output:
        return f"{ref} is a job, not a value: write %{{{name}.Succeeded}}, %{{{name}.Status}} or another of its outputs.", None
    if output not in OUTPUTS:
        return f"{ref}: a job has no output '{output}'. It has {', '.join(OUTPUTS)}.", None
    return None, OUTPUTS[output][0]


def _outside_problem(ref: str, name: str, output: Optional[str], kind: str) -> Tuple[Optional[str], Optional[str]]:
    if kind == "ENDPOINT":
        if output not in FILE_OUTPUTS:
            return f"{ref}: files at an endpoint have {' and '.join(FILE_OUTPUTS)}, as %{{{name}.FileCount}}.", None
        return None, conditions.NUMBER
    if kind == "TIME":
        return f"{ref}: a time has no values to read. Write the time test itself, as %{{Now.Time}} BETWEEN '06:00' AND '18:00'.", None
    if not output:
        return f"{ref} is a job, not a value: write %{{{name}.Succeeded}}, %{{{name}.Status}} or another of its outputs.", None
    if output not in OUTPUTS:
        return f"{ref}: a job has no output '{output}'. It has {', '.join(OUTPUTS)}.", None
    return None, OUTPUTS[output][0]


def check(text: str, names: Sequence[str], variable: Optional[Callable[[str], str]] = None,
          outside: Optional[Dict[str, str]] = None) -> Tuple[List[str], List[str]]:
    """
    Checks a workflow condition: that it is valid, and each %{Name.Output} names a job in the
    workflow and one of its outputs. variable gives a ${...} its value, raising ValueError if it
    has none; left out, variables are not looked at. Returns (problems, warnings).
    """
    return conditions.check(text, variable or (lambda ref: ref), lambda ref: reference_problem(ref, names, outside))


def rename(text: Optional[str], renames: Dict[str, str]) -> Optional[str]:
    """The condition with each %{Old...} renamed %{New...}, all at once, so two names can swap."""
    if not text or not renames:
        return text
    pattern = re.compile(r"%\{(" + "|".join(re.escape(old) for old in renames) + r")(?=[.}])")
    return pattern.sub(lambda match: "%{" + renames[match.group(1)], text)

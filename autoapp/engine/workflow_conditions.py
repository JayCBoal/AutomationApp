"""
Conditions in a workflow (docs/WORKFLOWS_PHASE4.md): a job's Custom rule, and the workflow's
Succeeds when. They are written in flow control's language (engine/conditions.py), over
%{Name.Output}, where Name is a job in the workflow, and ${...} variables.

Every job in a workflow has the same outputs (OUTPUTS). Until it ends, all of them are unknown
(NULL), so a Custom rule can be decided while some of its jobs still run: true starts the job,
false means it can never start, unknown waits.

Succeeded, Failed and Ended mean exactly what a prerequisite's Outcomes mean: Bypassed counts as
succeeded with return code 0, and Ended includes Not run.
"""
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from engine import conditions
from engine.run_context import shown_time

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

# The outputs that are True or False (1 or 0): the builder offers "is true" and "is false" for them
BOOLEANS = ("Succeeded", "Failed", "Ended", "NotRun", "Skipped", "Disabled", "Bypassed")

_REF = re.compile(r"^%\{([^.}]*)(?:\.([^}]*))?\}$")


def split_ref(ref: str) -> Tuple[str, Optional[str]]:
    """%{Extract.FileCount} as ("Extract", "FileCount"); %{Extract} as ("Extract", None)."""
    match = _REF.match(ref)
    return (match.group(1), match.group(2) or None) if match else (ref, None)


def named_jobs(text: str) -> List[str]:
    """The jobs a condition names, in order, once each. Raises ValueError for unclosed quotes or braces."""
    names = []
    for ref in conditions.references(text):
        if ref.startswith("%{"):
            name, _ = split_ref(ref)
            if name not in names:
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


def reference_problem(ref: str, names: Sequence[str]) -> Tuple[Optional[str], Optional[str]]:
    """What is wrong with %{Name.Output} in a workflow whose jobs are names, if anything; and its kind."""
    name, output = split_ref(ref)
    if name not in names:
        return f"{ref}: no job in this workflow is named {name}.", None
    if not output:
        return f"{ref} is a job, not a value: write %{{{name}.Succeeded}}, %{{{name}.Status}} or another of its outputs.", None
    if output not in OUTPUTS:
        return f"{ref}: a job has no output '{output}'. It has {', '.join(OUTPUTS)}.", None
    return None, OUTPUTS[output][0]


def check(text: str, names: Sequence[str], variable: Optional[Callable[[str], str]] = None) -> Tuple[List[str], List[str]]:
    """
    Checks a workflow condition: that it is valid, and each %{Name.Output} names a job in the
    workflow and one of its outputs. variable gives a ${...} its value, raising ValueError if it
    has none; left out, variables are not looked at. Returns (problems, warnings).
    """
    return conditions.check(text, variable or (lambda ref: ref), lambda ref: reference_problem(ref, names))


def rename(text: Optional[str], renames: Dict[str, str]) -> Optional[str]:
    """The condition with each %{Old...} renamed %{New...}, all at once, so two names can swap."""
    if not text or not renames:
        return text
    pattern = re.compile(r"%\{(" + "|".join(re.escape(old) for old in renames) + r")(?=[.}])")
    return pattern.sub(lambda match: "%{" + renames[match.group(1)], text)

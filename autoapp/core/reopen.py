"""
Reopening a workflow run (docs/WORKFLOWS_PHASE7.md, step 3): what Resume and Restart from beginning do
with each item of a run that has ended. The server's plan (engine/reopen_tree.py) and the workflow runner
both ask here, so what the dialog says is what the run does.

    UNTOUCHED  the item stays as it ended
    PICK_UP    a failed job or frame goes on from its own record: a job in a new attempt that resumes from the
               earlier one's control file, a frame as its own run reopened
    FRESH      the item is looked at again from scratch, as a new attempt
    ROUTE      a frame on the way to the item chosen: reopened, and only what leads to the item changes

scope is the path of the one item chosen (a failed job or frame inside a run), or None for the whole run.

Advanced (step 6) names an action for each item instead: items maps a path to RESUME, RESTART, BYPASS or DONT_RUN.
An item named RESUME or RESTART is picked up or started again; BYPASS ends it Bypassed (it counts as succeeded, so
what waits for it goes on) and DONT_RUN ends it Skipped (so what waits for its success does not run), neither running
it. A frame that holds an item named is reopened on the way, and the rest stays as it ended.
"""
from typing import Dict, Optional

RESUME, RESTART, ADVANCED = "resume", "restart", "advanced"
BYPASS, DONT_RUN = "bypass", "dont_run"             # an item's action in Advanced, and the action the runner takes
PASS_OVER = (BYPASS, DONT_RUN)
RUN_AGAIN, COUNT_AS_DONE = "run_again", "count_done"

UNTOUCHED, PICK_UP, FRESH, ROUTE = "untouched", "pick_up", "fresh", "route"

# Statuses of an item that has not run, or did not get to
NOT_FINISHED = ("PENDING", "WAITING", "NOT_RUN")


def is_on_the_way(path: str, scope: Optional[str]) -> bool:
    """Whether the item at path is a frame that holds the item chosen."""
    return scope is not None and scope.startswith(path + "/")


def holds_item(path: str, items: Optional[Dict[str, str]]) -> bool:
    """Whether the item at path is a frame that holds an item Advanced named."""
    return bool(items) and any(chosen.startswith(path + "/") for chosen in items)


def action_for(status: str, has_record: bool, path: str, kind: str, scope: Optional[str],
               items: Optional[Dict[str, str]] = None) -> str:
    """What reopening the run does to the item at path, which ended with status; has_record: it has a run of its own."""
    if items is not None:
        return _named_action(has_record, path, items)
    if is_on_the_way(path, scope):
        return ROUTE
    if scope is not None and path != scope:
        return UNTOUCHED
    if scope is not None:                               # the item chosen: only a failed one can be
        return _again(kind, has_record) if status == "FAILED" else UNTOUCHED
    if kind == RESTART:
        return FRESH
    if status == "FAILED":
        return _again(kind, has_record)
    return FRESH if status in NOT_FINISHED else UNTOUCHED


def _named_action(has_record: bool, path: str, items: Dict[str, str]) -> str:
    """Advanced: the item named is picked up (if it left a record), started again, bypassed or not run; a frame that holds one is opened on the way."""
    if path in items:
        if items[path] in PASS_OVER:
            return items[path]
        return PICK_UP if items[path] == RESUME and has_record else FRESH
    return ROUTE if holds_item(path, items) else UNTOUCHED


def _again(kind: str, has_record: bool) -> str:
    """A failed item: a resume goes on from its record, if it left one; a restart starts over."""
    return PICK_UP if kind == RESUME and has_record else FRESH

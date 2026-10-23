"""
Advanced rerun of a workflow run (docs/WORKFLOWS_PHASE7.md, step 6): what to do with each item, chosen one by one or
by a shortcut that fills the list in.

    from   the jobs chosen and everything that waits for them, directly or not
    only   just the jobs chosen; what waits for them is left as it ended, and may be out of date

Each item named is picked up from where it failed (resume), started again from the beginning (restart), bypassed (it
counts as succeeded without running) or not run (Skipped). A shortcut gives a failed item the action asked for when it
can have it, and restarts all the others: only a failed item has a record to pick up from. Bypass or Don't run on the
job chosen, with "from", lets what waits for it go on, or not. The rest of the run stays as it ended, except the
items at the top of the workflow that did not run: they have not ended, only not had their turn, so each is run again
when its waits are met (like Resume) unless the operator says "leave" for it, or the shortcut is "only".
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from engine import reopen
from engine.reopen_tree import TreePlan, downstream

FROM, ONLY = "from", "only"
LEAVE = "leave"         # an item that did not run, left as it is: not an action, it only stops the default
ACTIONS = (reopen.RESUME, reopen.RESTART) + reopen.PASS_OVER


def named_items(db: Session, plan: TreePlan, shortcut: Optional[str], chosen: List[str], chosen_as: str,
                explicit: Dict[str, str]) -> Tuple[Dict[str, str], Optional[str]]:
    """What to do with each item, by path, and a refusal in words when the request does not make sense."""
    if shortcut not in (None, FROM, ONLY):
        return {}, "Choose 'from' (the jobs and what waits for them) or 'only' (just the jobs chosen)."
    if chosen_as not in ACTIONS:
        return {}, "Choose whether the jobs chosen are resumed, restarted, bypassed or not run."
    wrong = [path for path, what in explicit.items() if what not in ACTIONS and what != LEAVE]
    if wrong:
        return {}, f"For '{wrong[0]}', choose resume, restart, bypass or dont_run."
    items = dict(explicit)
    items.update(_asked_for(plan, chosen, chosen_as))
    left = {path for path, what in items.items() if what == LEAVE}
    items = {path: what for path, what in items.items() if what != LEAVE}
    problem = _inside_each_other(items)
    if problem:
        return {}, problem
    if shortcut == FROM:
        items.update(_following(db, plan, list(items), chosen_as))
    if not items:
        return {}, "Choose at least one item to run again."
    if shortcut != ONLY:
        items.update(_waiting_their_turn(plan, items, left))
    return items, None


def _waiting_their_turn(plan: TreePlan, items: Dict[str, str], left: set) -> Dict[str, str]:
    """The top-level items that did not run and were not named or left alone: each starts again, as it would on a Resume."""
    return {item.path: reopen.RESTART for item in plan.choices
            if item.depth == 0 and item.status == "NOT_RUN" and item.path not in items and item.path not in left
            and not any(path.startswith(item.path + "/") for path in items)}


def waits_problem(tree: TreePlan, items: Dict[str, str], ignore: Dict[str, List[str]]) -> Optional[str]:
    """Why the prerequisites to ignore cannot be, in words: the job does not run again, has no such wait, or starts by a Custom rule."""
    known = {item.path: item for item in tree.choices}
    problems = []
    for path, names in ignore.items():
        why = _wait_problem(known.get(path), items.get(path), names)
        if why:
            problems.append(f"'{path}': {why}")
    return " ".join(problems) or None


def _wait_problem(item, action: Optional[str], names: List[str]) -> Optional[str]:
    if item is None:
        return "it is not an item of this run."
    if action is None or action in reopen.PASS_OVER:
        return "it is not run again, so there is no wait to ignore."
    if item.custom_rule:
        return "it starts by a Custom rule, so a single wait cannot be ignored."
    missing = [name for name in names if name not in item.waits]
    if missing:
        return f"it does not wait for {_quoted(missing)}."
    return None


def _quoted(names: List[str]) -> str:
    return ", ".join(f"'{name}'" for name in names)


def _asked_for(plan: TreePlan, chosen: List[str], chosen_as: str) -> Dict[str, str]:
    return {path: _action(plan, path, chosen_as) for path in chosen}


def _action(plan: TreePlan, path: str, chosen_as: str) -> str:
    """What the item chosen gets: Resume when asked and it can be picked up, Bypass or Don't run when asked; otherwise it starts again."""
    if chosen_as in reopen.PASS_OVER:
        return chosen_as
    known = {item.path: item for item in plan.choices}.get(path)
    return reopen.RESUME if chosen_as == reopen.RESUME and known is not None and known.can_resume else reopen.RESTART


def _inside_each_other(items: Dict[str, str]) -> Optional[str]:
    for path in items:
        outer = next((other for other in items if path.startswith(other + "/")), None)
        if outer:
            return f"'{outer}' and '{path}' inside it are both chosen. Choose the workflow, or the job inside it."
    return None


def _following(db: Session, plan: TreePlan, chosen: List[str], chosen_as: str) -> Dict[str, str]:
    """What waits for the items chosen, except what is already inside a chosen workflow."""
    after = reopen.RESTART if chosen_as in reopen.PASS_OVER else chosen_as     # what follows runs; it is not itself passed over
    items = {path: _action(plan, path, after) for path in downstream(db, plan.top, chosen)}
    return {path: what for path, what in items.items() if not any(path.startswith(c + "/") for c in chosen)}

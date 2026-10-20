"""
What a workflow is made of: the jobs it uses (its items) and the prerequisites between
them. A workflow is a Job of type WORKFLOW (docs/WORKFLOWS.md); job_store saves what all
jobs share and calls apply_items for a workflow's items.

Rules:
  - Items are saved whole, in outline order. An item keeps its identity (its id) when it is
    changed, so later run records stay linked to it; one left out of a save is deleted.
  - Each item has a name unique within its workflow, made from its job's key if not given.
  - A prerequisite names another item of the same workflow. There are no loops: a job never
    ends up waiting, directly or not, for itself. A workflow never uses itself, directly or
    through another workflow.
  - Disable here is empty, STOP or PASS_THROUGH. A use's own Reactions are kept only when it
    overrides its job's; they follow app/reaction_store.py's rules.
  - A Custom rule (join CUSTOM; docs/WORKFLOWS_PHASE4.md) is a condition over the jobs it names,
    which become its prerequisites (test RULE), so nothing else has to read the rule to see
    what waits for what. A rule may name no job at all, and test only variables.
  - Renaming a job renames it in the rules that name it, and in the completion rules.
  - Completion rules: Succeeds when (a condition over any of its jobs) and Return code from (one
    of its jobs, by name). Empty means the default.
"""
import re
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app import outside_store, reaction_store
from app.workflow_errors import WorkflowError
from app.models import Job, WorkflowItem, WorkflowItemVariable, WorkflowPrerequisite
from app.schemas import PrerequisiteSave, WorkflowItemOut, WorkflowItemSave
from engine import return_codes, workflow_conditions, workflow_vars

TEST_WORDS = {"SUCCESS": "succeeded", "FAILED": "failed", "ENDED": "ended", "RC": "gave return codes",
              "RULE": "is named in its rule"}


def default_item_name(job_key: str) -> str:
    """An item's name made from its job's key: dots and anything else a name cannot hold become underscores."""
    name = re.sub(r"[^A-Za-z0-9_-]", "_", job_key)
    return name if name[:1].isalnum() else f"J{name}"


def describe_items(job: Job) -> List[WorkflowItemOut]:
    return [
        WorkflowItemOut(
            id=item.id, name=item.ItemName, job_key=item.job.JobKey, job_type=item.job.JobType, join=item.JoinRule,
            rule=item.StartRule if item.JoinRule == "CUSTOM" else None,
            prerequisites=outside_store.describe_all(item.prerequisites), on_unmet=item.OnUnmet,
            needed_by=outside_store.needed_by(item),
            disabled_here=item.DisabledHere, job_active=bool(item.job.IsActive),
            reactions_overridden=bool(item.ReactionsOverridden),
            reactions=reaction_store.describe(item.reactions) if item.ReactionsOverridden else [],
            job_reactions=reaction_store.describe(item.job.reactions),
            variables=_describe_variables(item.variables))
        for item in job.items
    ]


def _describe_variables(variables):
    from app.job_store import describe_variables
    return describe_variables(variables)


def describe_prerequisite(target: str, test: str, codes: Optional[str]) -> str:
    """In words, as the audit log and the outline say it: "Extract succeeded", "Load gave return codes 0-4"."""
    return f"{target} {TEST_WORDS.get(test, test.lower())}" + (f" {codes}" if test == "RC" else "")


# ---------- Checking what was submitted ----------

def _names(submitted: List[WorkflowItemSave]) -> List[str]:
    """Each item's name: as given, or made from its job key."""
    return [(s.name or "").strip() or default_item_name(s.job_key.strip()) for s in submitted]


def _check_names(names: List[str]) -> None:
    seen: Set[str] = set()
    for name in names:
        if not WorkflowItem.NAME_PATTERN.match(name):
            raise WorkflowError(f"'{name}' cannot be the name of a job in a workflow. Use letters, digits, '_' and '-', "
                                f"starting with a letter or digit.")
        if name == "Now":
            raise WorkflowError("'Now' cannot be the name of a job in a workflow: %{Now.Time} is the time of day. "
                                "Give the job another name.")
        if name in seen:
            raise WorkflowError(f"Two jobs in the workflow are both named '{name}'. Give one of them another name.")
        seen.add(name)


def renames(workflow: Job, submitted: List[WorkflowItemSave]) -> Dict[str, str]:
    """
    The jobs renamed by this save, old name to new, to carry into the conditions that name them.
    A name still used in the workflow after the save is left out: a page that renamed the job in
    its rules already (or swapped two names) has rules naming what it means.
    """
    current = {item.id: item.ItemName for item in workflow.items}
    names = _names(submitted)
    found = {current[s.id]: name for name, s in zip(names, submitted) if s.id in current and current[s.id] != name}
    return {old: new for old, new in found.items() if old not in names}


def with_rules_applied(submitted: List[WorkflowItemSave], renamed: Dict[str, str]) -> List[WorkflowItemSave]:
    """Each item with a Custom rule, its rule renamed and its prerequisites the jobs the rule names."""
    result = []
    for name, item in zip(_names(submitted), submitted):
        if item.join != "CUSTOM":
            result.append(item.model_copy(update={"rule": None}))
            continue
        rule = (workflow_conditions.rename(item.rule, renamed) or "").strip()
        if not rule:
            raise WorkflowError(f"'{name}' starts by a Custom rule, but the rule is empty. Write the rule, "
                                f"or choose another Start rule.")
        outside = [p for p in item.prerequisites if outside_store.is_outside(p)]
        try:
            named = workflow_conditions.named_jobs(rule, [p.target for p in outside])
        except ValueError as e:
            raise WorkflowError(f"'{name}': its Custom rule: {e}")
        result.append(item.model_copy(update={"rule": rule, "prerequisites": outside + [
            PrerequisiteSave(target=target, test=WorkflowPrerequisite.RULE) for target in named]}))
    return result


def _check_rules(names: List[str], submitted: List[WorkflowItemSave]) -> None:
    for name, item in zip(names, submitted):
        if item.join != "CUSTOM":
            continue
        problems, _ = workflow_conditions.check(item.rule, names, outside=outside_store.outside_names(item.prerequisites))
        if problems:
            raise WorkflowError(f"'{name}': its Custom rule: {problems[0]}")


def _check_prerequisites(names: List[str], submitted: List[WorkflowItemSave]) -> None:
    for name, item in zip(names, submitted):
        if item.join not in WorkflowItem.JOIN_RULES:
            raise WorkflowError(f"'{name}': its join must be ALL, ANY or CUSTOM, not '{item.join}'.")
        for p in outside_store.inside(item.prerequisites):
            if item.join == "CUSTOM":
                if p.target == name:
                    raise WorkflowError(f"'{name}': its Custom rule names '{name}' itself. A job cannot wait for itself.")
                continue                    # a job the rule names: the rule's check says what is wrong with it
            if p.target not in names:
                raise WorkflowError(f"'{name}' waits for '{p.target}', which is not a job in this workflow.")
            if p.target == name:
                raise WorkflowError(f"'{name}' cannot wait for itself.")
            if p.test not in WorkflowPrerequisite.TESTS:
                raise WorkflowError(f"'{name}' waits for '{p.target}' with the test '{p.test}'. "
                                    f"The test must be SUCCESS, FAILED, ENDED or RC.")
            if p.test == "RC" and return_codes.problem(p.return_codes):
                raise WorkflowError(f"'{name}' waits for return codes of '{p.target}': {return_codes.problem(p.return_codes)}")


def find_loop(waits_for: Dict[str, List[str]]) -> Optional[List[str]]:
    """A chain of names that comes back to its start (a waits for b, which waits for a), or None."""
    state: Dict[str, str] = {}

    def visit(name: str, path: List[str]) -> Optional[List[str]]:
        state[name] = "visiting"
        for target in waits_for.get(name, []):
            if state.get(target) == "visiting":
                return path[path.index(target):] + [target] if target in path else [name, target]
            if target not in state:
                found = visit(target, path + [target])
                if found:
                    return found
        state[name] = "done"
        return None

    for start in waits_for:
        if start not in state:
            found = visit(start, [start])
            if found:
                return found
    return None


def _upstream(name: str, waits_for: Dict[str, List[str]]) -> Set[str]:
    """Every job name waits for, directly or not."""
    found: Set[str] = set()
    queue = list(waits_for.get(name, []))
    while queue:
        target = queue.pop()
        if target not in found:
            found.add(target)
            queue += waits_for.get(target, [])
    return found


def _check_uses(db: Session, workflow: Job, names: List[str], submitted: List[WorkflowItemSave]) -> None:
    """Disable here, and each use's own Reactions."""
    waits_for = {name: [p.target for p in outside_store.inside(item.prerequisites)] for name, item in zip(names, submitted)}
    for name, item in zip(names, submitted):
        if item.disabled_here not in (None, "") + WorkflowItem.DISABLED_HERE:
            raise WorkflowError(f"'{name}': Disable here must be STOP or PASS_THROUGH, not '{item.disabled_here}'.")
        if item.reactions_overridden:
            try:
                reaction_store.check(db, f"'{name}'", item.reactions, workflow, _upstream(name, waits_for), names, name)
            except reaction_store.ReactionError as e:
                raise WorkflowError(str(e))


def _check_no_loops(names: List[str], submitted: List[WorkflowItemSave]) -> None:
    loop = find_loop({name: [p.target for p in outside_store.inside(item.prerequisites)]
                      for name, item in zip(names, submitted)})
    if loop:
        chain = ", which waits for ".join(f"'{n}'" for n in loop)
        raise WorkflowError(f"The prerequisites go round in a loop: {chain}. None of them could ever start. "
                            "To run jobs again, a Rerun from… Reaction will repeat them, up to a limit (not built yet).")


def _jobs_used(db: Session, submitted: List[WorkflowItemSave], names: List[str]) -> Dict[str, Job]:
    jobs = {}
    for name, item in zip(names, submitted):
        key = item.job_key.strip()
        job = db.query(Job).filter(Job.JobKey == key).first()
        if not job:
            raise WorkflowError(f"'{name}' runs the job '{key}', which does not exist.")
        jobs[name] = job
    return jobs


def uses(workflow: Job, target_id: int) -> bool:
    """Whether the workflow uses the job target_id, directly or through workflows it uses."""
    return workflow.JobType == "WORKFLOW" and _uses(None, workflow, target_id, {workflow.MasterObject_id})


def _uses(db: Session, workflow: Job, target_id: int, seen: Set[int]) -> bool:
    """Whether the workflow uses the job target_id, directly or through workflows it uses."""
    for item in workflow.items:
        if item.Job_MasterObject_id == target_id:
            return True
        inner = item.job
        if inner.JobType == "WORKFLOW" and inner.MasterObject_id not in seen:
            seen.add(inner.MasterObject_id)
            if _uses(db, inner, target_id, seen):
                return True
    return False


def _check_not_itself(db: Session, workflow: Job, jobs: Dict[str, Job]) -> None:
    for name, job in jobs.items():
        if job.MasterObject_id == workflow.MasterObject_id:
            raise WorkflowError(f"'{name}' runs this workflow itself. A workflow cannot use itself.")
        if job.JobType == "WORKFLOW" and _uses(db, job, workflow.MasterObject_id, {job.MasterObject_id}):
            raise WorkflowError(f"'{name}' runs the workflow '{job.JobKey}', which uses this one. "
                                f"A workflow cannot use itself, even through another.")


# ---------- Saving ----------

def apply_items(db: Session, workflow: Job, submitted: List[WorkflowItemSave], creating: bool,
                renamed: Optional[Dict[str, str]] = None) -> List[str]:
    """
    Makes the workflow's items and prerequisites match those submitted. renamed: the jobs this save
    renames (renames()), carried into the Custom rules. Returns what changed, in words.
    """
    names = _names(submitted)
    _check_names(names)
    submitted = [s.model_copy(update={"prerequisites": outside_store.with_names(s.prerequisites, names)}) for s in submitted]
    submitted = with_rules_applied(submitted, renamed or {})
    _check_outside(db, workflow, names, submitted)
    _check_prerequisites(names, submitted)
    _check_rules(names, submitted)
    _check_no_loops(names, submitted)
    jobs = _jobs_used(db, submitted, names)
    _check_not_itself(db, workflow, jobs)
    _check_uses(db, workflow, names, submitted)
    outside_store.check_no_loops_between_workflows(db, workflow, names, submitted)

    current = {item.id: item for item in workflow.items}
    for s in submitted:
        if s.id is not None and s.id not in current:
            raise WorkflowError(f"Item id {s.id} does not belong to workflow '{workflow.JobKey}'.")
    submitted_ids = [s.id for s in submitted if s.id is not None]
    old_order = [item.id for item in sorted(current.values(), key=lambda i: i.ItemOrder) if item.id in submitted_ids]
    changes: List[str] = []
    kept = _apply_item_rows(workflow, submitted, names, jobs, current, creating, changes)
    _remove_left_out(workflow, current, kept, changes)
    db.flush()                          # every item has its id before prerequisites point at it
    by_name = {item.ItemName: item for item in workflow.items}
    for name, s in zip(names, submitted):
        if _apply_prerequisites(db, by_name[name], s, by_name) and not creating and s.id is not None:
            changes.append(f"Changed what '{name}' waits for.")
        changed = _apply_use(db, by_name[name], s, by_name)
        if changed and not creating and s.id is not None:
            changes.append(f"Changed '{name}': {', '.join(changed)}.")
    if not creating and old_order != submitted_ids:
        changes.append("Reordered the jobs.")
    return changes


def _apply_item_rows(workflow, submitted, names, jobs, current, creating, changes) -> Set[int]:
    kept: Set[int] = set()
    for position, (name, s) in enumerate(zip(names, submitted), start=1):
        job = jobs[name]
        if s.on_unmet not in WorkflowItem.ON_UNMET:
            raise WorkflowError(f"'{name}': when it cannot start it must be NOT_RUN or FAIL, not '{s.on_unmet}'.")
        if s.id is None:
            workflow.items.append(WorkflowItem(ItemName=name, job=job, JoinRule=s.join, StartRule=s.rule,
                                               ItemOrder=position, OnUnmet=s.on_unmet))
            if not creating:
                changes.append(f"Added '{name}' (job '{job.JobKey}').")
            continue
        item = current[s.id]
        kept.add(item.id)
        what = []
        if item.ItemName != name:
            what.append(f"renamed from '{item.ItemName}'")
        if item.Job_MasterObject_id != job.MasterObject_id:
            what.append(f"now runs '{job.JobKey}'")
        if item.JoinRule != s.join:
            what.append(f"starts when {'any' if s.join == 'ANY' else 'all'} of its prerequisites hold" if s.join != "CUSTOM"
                        else "starts by a Custom rule")
        elif s.join == "CUSTOM" and (item.StartRule or "") != s.rule:
            what.append(f"its Custom rule is now: {s.rule}")
        if item.OnUnmet != s.on_unmet:
            what.append("it fails when it cannot start" if s.on_unmet == "FAIL" else "it does not run when it cannot start")
            item.OnUnmet = s.on_unmet
        item.ItemName, item.job, item.JoinRule, item.ItemOrder = name, job, s.join, position
        item.StartRule = s.rule
        if what:
            changes.append(f"Changed '{name}': {', '.join(what)}.")
    return kept


def _remove_left_out(workflow: Job, current: dict, kept: Set[int], changes: List[str]) -> None:
    for item_id, item in current.items():
        if item_id not in kept:
            waiting = outside_store.waiting_for_use(item)
            if waiting:
                raise WorkflowError(f"'{item.ItemName}' cannot be taken out: {', '.join(waiting)} "
                                    f"wait{'s' if len(waiting) == 1 else ''} for it. Change what they wait for first.")
            changes.append(f"Removed '{item.ItemName}'.")
            workflow.items.remove(item)


def _check_outside(db: Session, workflow: Job, names: List[str], submitted: List[WorkflowItemSave]) -> None:
    for name, item in zip(names, submitted):
        outside_store.check(db, workflow, name, item.prerequisites, names, item.join == "CUSTOM")


def _apply_prerequisites(db: Session, item: WorkflowItem, submitted: WorkflowItemSave,
                         by_name: Dict[str, WorkflowItem]) -> bool:
    """Makes the item's prerequisites match those submitted. Returns whether they changed."""
    wanted = outside_store.wanted(submitted.prerequisites, submitted.join == "CUSTOM")
    have = outside_store.describe_all(item.prerequisites)
    if [outside_store.signature(p) for p in wanted] == [outside_store.signature(p) for p in have]:
        return False
    item.prerequisites.clear()
    rows = [outside_store.build_row(db, p, by_name) for p in wanted]
    for row, p in zip(rows, wanted):
        outside_store.point_at_target(db, row, p)
    item.prerequisites.extend(rows)
    db.flush()
    outside_store.link_wait_from(rows, wanted)
    return True


def _apply_use(db: Session, item: WorkflowItem, submitted: WorkflowItemSave, by_name: Dict[str, WorkflowItem]) -> List[str]:
    """Disable here and the use's own Reactions. Returns what changed, in words."""
    changed = []
    disabled = submitted.disabled_here or None
    if disabled != item.DisabledHere:
        changed.append({None: "enabled here", "STOP": "disabled here (stop)",
                        "PASS_THROUGH": "disabled here (pass through)"}[disabled])
        item.DisabledHere = disabled
    if bool(submitted.reactions_overridden) != bool(item.ReactionsOverridden):
        changed.append("its own Reactions replace its job's" if submitted.reactions_overridden
                       else "uses its job's Reactions again")
        item.ReactionsOverridden = bool(submitted.reactions_overridden)
    wanted = submitted.reactions if submitted.reactions_overridden else []
    if item.id is None:
        db.flush()
    if reaction_store.apply(db, item.reactions, wanted, {"Item_id": item.id}, by_name) and item.ReactionsOverridden \
            and "its own Reactions replace its job's" not in changed:
        changed.append("changed its Reactions")
    if submitted.variables is not None:
        changed += _apply_use_variables(item, submitted.variables)
    return changed


def _apply_use_variables(item: WorkflowItem, submitted: list) -> List[str]:
    """The use's own variables, as the job's are kept; what changed, in words, naming no values."""
    from app.job_store import JobStoreError, apply_variables
    try:
        said = apply_variables(item, submitted, False, model=WorkflowItemVariable)
    except JobStoreError as e:
        raise WorkflowError(f"'{item.ItemName}': {e}")
    # "Added variable Region." becomes "added its variable Region", to join the use's other changes
    return [_first_lower(line.rstrip(".").replace(" variable", " its variable", 1)) for line in said]


def _first_lower(text: str) -> str:
    return text[:1].lower() + text[1:]


def apply_completion(workflow: Job, succeeds_when: Optional[str], return_code_from: Optional[str], creating: bool,
                     renamed: Optional[Dict[str, str]] = None) -> List[str]:
    """The workflow's completion rules, checked against its jobs as saved. Returns what changed, in words."""
    renamed = renamed or {}
    names = [item.ItemName for item in workflow.items]
    rule = (workflow_conditions.rename(succeeds_when, renamed) or "").strip() or None
    source = (return_code_from or "").strip() or None
    source = renamed.get(source, source)
    if rule:
        problems, _ = workflow_conditions.check(rule, names)
        if problems:
            raise WorkflowError(f"Succeeds when: {problems[0]}")
    if source and source not in names:
        raise WorkflowError(f"The workflow's return code comes from '{source}', which is not a job in this workflow.")
    changes = []
    if rule != workflow.SucceedsWhen:
        changes.append(f"Succeeds when is now: {rule}." if rule else "Succeeds when is back to the default.")
    if source != workflow.ReturnCodeFrom:
        changes.append(f"The return code now comes from '{source}'." if source else "The return code is back to the default.")
    workflow.SucceedsWhen, workflow.ReturnCodeFrom = rule, source
    return [] if creating else changes


# ---------- Checking before a run, and who uses what ----------

def workflow_problems(db: Session, workflow: Job, warnings: Optional[List[str]] = None,
                      seen: Optional[Set[int]] = None) -> List[str]:
    """
    What would stop the workflow from starting, in plain words: only what is wrong with it as a whole.
    A job in it that is disabled, or would fail its own pre-run check, does not stop it: when its turn
    comes it ends Disabled, or fails, and what needs it to succeed does not run. Given a list, warnings
    gets those jobs, so the check can say so before the run. Runs nothing.
    """
    from app.routers.jobs import job_problems
    seen = (seen or set()) | {workflow.MasterObject_id}
    problems = []
    if not workflow.IsActive:
        problems.append(f"Workflow '{workflow.JobKey}' is disabled.")
    if not workflow.items:
        problems.append(f"Workflow '{workflow.JobKey}' has no jobs in it yet. Add the jobs it should run.")
    problems += _variable_problems(db, workflow)
    problems += _outside_problems(workflow, warnings)
    if warnings is None:
        return problems
    checked: Dict[int, List[str]] = {}
    for item in workflow.items:
        job = item.job
        if job.MasterObject_id in seen:
            continue
        if not job.IsActive:
            warnings.append(f"'{item.ItemName}' is disabled: it will end Disabled, and what needs it to succeed will not run.")
            continue
        # A job is checked once for each use, which may set variables of its own
        if item.id not in checked:
            checked[item.id] = (workflow_problems(db, job, [], seen) if job.JobType == "WORKFLOW"
                                else job_problems(db, job, workflow=workflow_vars.for_check(db, workflow, item)))
        for problem in checked[item.id][:1]:     # the first is enough to say it would fail
            warnings.append(f"'{item.ItemName}' would fail: {problem}")
    return problems


def _outside_problems(workflow: Job, warnings: Optional[List[str]]) -> List[str]:
    """What is wrong with the files a job waits for (they must be on this server); an unlimited wait is a warning."""
    problems = []
    for item in workflow.items:
        for p in item.prerequisites:
            if p.Kind == "ENDPOINT" and p.endpoint is not None and p.endpoint.site is not None:
                problems.append(f"'{item.ItemName}' waits for files at the endpoint '{p.endpoint.Name}', which is on Site "
                                f"'{p.endpoint.site.Name}'. Only files on this server can be waited for yet.")
            if warnings is not None and p.Kind != "JOB" and p.WaitMode == "NONE":
                warnings.append(f"'{item.ItemName}' waits for '{p.TargetName}' with no limit: if it never happens, "
                                f"the workflow waits for ever.")
    return problems


def _variable_problems(db: Session, workflow: Job) -> List[str]:
    """Each ${...} in the workflow's conditions that has no value, said once. They are filled in as a run starts."""
    texts = [(f"'{item.ItemName}': its Custom rule", item.StartRule) for item in workflow.items
             if item.JoinRule == "CUSTOM" and item.StartRule]
    if workflow.SucceedsWhen:
        texts.append(("Succeeds when", workflow.SucceedsWhen))
    refs = [(where, ref) for where, text in texts for ref in _safe_references(text) if ref.startswith("${")]
    if not refs:
        return []
    from engine.scope_engine import ScopeResolutionEngine
    engine = ScopeResolutionEngine(db=db, job_id=workflow.MasterObject_id, instance_id="CHECK")
    engine.build_context()
    problems = []
    for where, ref in refs:
        try:
            engine.interpolate(ref)
        except ValueError as e:
            problems.append(f"{where}: {e}")
    return problems


def _safe_references(text: str) -> List[str]:
    try:
        return workflow_conditions.conditions.references(text)
    except ValueError:
        return []                   # an unclosed quote is refused when saved


def workflows_using(db: Session, job: Job) -> List[str]:
    """The keys of the workflows that use the job, in name order."""
    rows = (db.query(Job.JobKey).join(WorkflowItem, WorkflowItem.Workflow_MasterObject_id == Job.MasterObject_id)
            .filter(WorkflowItem.Job_MasterObject_id == job.MasterObject_id).distinct())
    return sorted(key for (key,) in rows)

"""
Checks a whole job before any of it runs.

Every active step, in every branch and loop, is checked against its step type and
has its parameters and file locations resolved. Problems in any step are found up
front, so a job never moves files in step 1 only to discover a typing mistake in
step 3, or in an Else branch that rarely runs.

What only the run can know, a %{...} value, is checked as far as it can be: that it
names a step or a loop's file, and something that step or file has.

Used by the runner before it starts, and by the API to check a job on request.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models import Job, JobStep
from engine import conditions, step_tree
from engine.handlers import get_handler
from engine.handlers.flow import CONDITIONAL, structure_problems, top_level_problems
from engine.run_context import FILE_PROPERTIES, references
from engine.scope_engine import ScopeResolutionEngine
from engine.step_params import ResolvedStep, resolve_step


@dataclass
class PreparedStep:
    step: JobStep
    handler_cls: Any
    resolved: ResolvedStep
    number: str = ""
    name: str = ""                          # how messages name it: Step 3.1 ('Copy')
    children: List["PreparedStep"] = field(default_factory=list)

    @property
    def code(self) -> str:
        return self.step.step_type.HandlerClass


class _Checker:
    """Walks a job's steps once, collecting problems, warnings and the steps ready to run."""

    def __init__(self, db: Session, steps: List[JobStep], scope_engine: ScopeResolutionEngine):
        self.db, self.scope_engine = db, scope_engine
        self.problems: List[str] = []
        self.warnings: List[str] = []
        # Every step's outputs, by StepName: names may repeat, so all the step types using one count
        self.outputs: Dict[str, Set[str]] = {}
        self.output_types: Dict[Tuple[str, str], str] = {}
        for step in steps:
            self._learn_outputs(step)

    def _learn_outputs(self, step: JobStep) -> None:
        if not step.StepName:
            return
        try:
            declared = get_handler(step.step_type.HandlerClass).outputs()
        except ValueError:
            declared = ()
        names = self.outputs.setdefault(step.StepName, set())
        for output in declared:
            names.add(output.name)
            self.output_types[(step.StepName, output.name)] = output.data_type

    def reference_problem(self, name: str, prop: Optional[str], files: Tuple[str, ...]) -> Tuple[Optional[str], Optional[str]]:
        """What is wrong with %{name.prop} where the loops around offer files, if anything; and its kind."""
        shown = f"%{{{name}.{prop}}}" if prop else f"%{{{name}}}"
        if name in files:
            if not prop:
                return f"{shown} is a file, not a value: write %{{{name}.Name}}, %{{{name}.FullName}} or another of " \
                       f"{', '.join(FILE_PROPERTIES)}.", None
            if prop not in FILE_PROPERTIES:
                return f"{shown}: a file has no '{prop}'. It has {', '.join(FILE_PROPERTIES)}.", None
            return None, FILE_PROPERTIES[prop]
        if name in self.outputs:
            if not prop:
                return f"{shown} is a step, not a value: write %{{{name}.Status}} or another of its outputs.", None
            if prop not in self.outputs[name]:
                return f"{shown}: the step {name} has no output '{prop}'. It has " \
                       f"{', '.join(sorted(self.outputs[name]))}.", None
            return None, self.output_types[(name, prop)]
        return f"{shown}: no step is named {name}, and no For Each File loop around this step calls its file " \
               f"{name}.", None

    def check_references(self, node: step_tree.Node, files: Tuple[str, ...]) -> None:
        for parameter in node.step.parameters:
            for name, prop in references(parameter.ParamValue):
                problem, _ = self.reference_problem(name, prop or None, files)
                if problem:
                    self.problems.append(f"{node.name}: {problem}")

    def check_condition(self, node: step_tree.Node, files: Tuple[str, ...]) -> None:
        text = next((p.ParamValue for p in node.step.parameters if p.ParamName == "Condition"), None)
        if not text or not text.strip():
            return                          # a missing condition is reported as a missing parameter

        def run_value_type(ref: str):
            (name, prop), = references(ref)
            return self.reference_problem(name, prop or None, files)

        def variable(ref: str) -> str:
            # A variable that cannot be filled in is reported when the step's parameters are resolved
            try:
                return self.scope_engine.interpolate(ref)
            except ValueError:
                return ref
        problems, warnings = conditions.check(text, variable, run_value_type)
        # A %{...} problem is already reported, once, by check_references
        self.problems += [f"{node.name}: {p}" for p in problems if not p.startswith("%{")]
        self.warnings += [f"{node.name}: {w}" for w in warnings]

    def loop_file_name(self, node: step_tree.Node, resolved: ResolvedStep) -> Optional[str]:
        """What a For Each File loop calls its file, if that is a usable name."""
        item = str(resolved.params.get("ItemName") or "File")
        if not JobStep.NAME_PATTERN.match(item):
            self.problems.append(f"{node.name}: '{item}' cannot name the file: use letters, digits and "
                                 f"underscores, starting with a letter.")
            return None
        if item in self.outputs:
            self.problems.append(f"{node.name}: a step is already named {item}, so the loop's file needs another "
                                 f"name, so that %{{{item}...}} means one thing.")
        return item

    def prepare(self, node: step_tree.Node, files: Tuple[str, ...]) -> Optional[PreparedStep]:
        """The step ready to run, with the steps inside it; None if it cannot be."""
        for problem in structure_problems(node.code, [c.code for c in node.children], self._is_block(node)):
            self.problems.append(f"{node.name} {problem}")
        try:
            handler_cls = get_handler(node.code)
        except ValueError as e:
            self.problems.append(f"{node.name}: {e}")
            return None
        self.check_references(node, files)
        if node.code in CONDITIONAL:
            self.check_condition(node, files)
        try:
            resolved = resolve_step(node.step, handler_cls, self.scope_engine, self.db, label=node.name)
        except ValueError as e:
            self.problems.append(str(e))        # resolve_step names the step itself
            return None
        inside = files
        if node.code == "FOR_EACH_FILE":
            item = self.loop_file_name(node, resolved)
            inside = files + ((item,) if item else ())
        prepared = PreparedStep(node.step, handler_cls, resolved, node.number, node.name)
        prepared.children = self.prepare_all(node.children, inside)
        return prepared

    def prepare_all(self, nodes: List[step_tree.Node], files: Tuple[str, ...]) -> List[PreparedStep]:
        ready = (self.prepare(node, files) for node in nodes if node.step.IsActive or node.is_branch)
        return [p for p in ready if p is not None]

    @staticmethod
    def _is_block(node: step_tree.Node) -> bool:
        try:
            return get_handler(node.code).BLOCK
        except ValueError:
            return bool(node.children)          # unknown type: reported anyway; do not pile on


def prepare_job(db: Session, job: Job, scope_engine: ScopeResolutionEngine,
                warnings: Optional[List[str]] = None) -> Tuple[List[PreparedStep], List[str]]:
    """
    Returns the job's active top-level steps, ready to run in order, each holding the
    steps inside it; and a list of problems. If the list of problems is not empty the
    job must not be run. Things worth knowing that do not stop it go into warnings.
    """
    steps = db.query(JobStep).filter(JobStep.job_id == job.MasterObject_id).all()
    if not any(s.IsActive for s in steps if s.ParentStep_id is None):
        return [], [f"Job '{job.JobKey}' has no active steps."]

    tree = step_tree.build(steps)
    checker = _Checker(db, steps, scope_engine)
    checker.problems += top_level_problems([node.code for node in tree])
    prepared = checker.prepare_all(tree, ())
    if warnings is not None:
        warnings += checker.warnings
    return prepared, checker.problems


def describe_problems(problems: List[str]) -> str:
    """One problem as it is; several as a counted list."""
    if len(problems) == 1:
        return problems[0]
    return f"{len(problems)} problems were found before the job started:\n" + "\n".join(f"  - {p}" for p in problems)

"""
A job's steps as a tree, numbered as the editor and the job log show them.

Top-level steps are 1, 2, 3; the steps inside step 3 are 3.1, 3.2. An If's Then,
ElseIf and Else take no number of their own: the steps of all its branches are
numbered in one run, so an If at 3 holds 3.1 (Then), 3.2 (ElseIf), 3.3 (Else).
"""
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional

from core.models import JobStep
from core.handlers.flow import BRANCHES


@dataclass
class Node:
    step: JobStep
    number: str                 # "3.1"; a branch has its If's number
    children: List["Node"] = field(default_factory=list)

    @property
    def code(self) -> str:
        return self.step.step_type.HandlerClass

    @property
    def is_branch(self) -> bool:
        return self.code in BRANCHES

    @property
    def name(self) -> str:
        """How a message names the step: Step 3.1 ('Copy'); for a branch, Step 3 ('If late'), its Else."""
        if self.is_branch:
            return f"Step {self.number}, its {self.step.step_type.TypeName}"
        title = f" ('{self.step.Title}')" if self.step.Title else ""
        return f"Step {self.number}{title}"


def _by_parent(steps: Iterable[JobStep]) -> Dict[Optional[int], List[JobStep]]:
    grouped: Dict[Optional[int], List[JobStep]] = {}
    for step in steps:
        grouped.setdefault(step.ParentStep_id, []).append(step)
    for siblings in grouped.values():
        siblings.sort(key=lambda s: (s.StepOrder or 0, s.id or 0))
    return grouped


def build(steps: Iterable[JobStep]) -> List[Node]:
    """The top-level steps, each holding the steps inside it, all numbered."""
    grouped = _by_parent(steps)

    def nodes(parent_id: Optional[int], prefix: str, counter: List[int], parent_number: str) -> List[Node]:
        found = []
        for step in grouped.get(parent_id, []):
            if step.step_type.HandlerClass in BRANCHES:
                # A branch keeps its If's number and goes on with its count
                node = Node(step, parent_number)
                node.children = nodes(step.id, prefix, counter, parent_number)
            else:
                counter[0] += 1
                number = f"{prefix}.{counter[0]}" if prefix else str(counter[0])
                node = Node(step, number)
                node.children = nodes(step.id, number, [0], number)
            found.append(node)
        return found

    return nodes(None, "", [0], "")


def walk(nodes: List[Node]) -> Iterator[Node]:
    """Every node, each before the steps inside it, in the order the job lists them."""
    for node in nodes:
        yield node
        yield from walk(node.children)


def in_order(steps: Iterable[JobStep]) -> List[JobStep]:
    """A job's steps in the order the job lists them, each block before the steps inside it."""
    return [node.step for node in walk(build(steps))]

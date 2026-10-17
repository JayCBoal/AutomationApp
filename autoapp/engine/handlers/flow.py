"""
The flow control step types: If, ElseIf, Then, Else, For Each File and While (see docs/FLOW_CONTROL.md).

They hold other steps and decide which run, and how often. They are declared here like
any step type, so the catalog, the editor's form and the pre-run check treat them alike;
the runner (engine/executor.py) does their work, as it is about running other steps.
"""
from typing import List, Sequence

from engine.handlers.base_handler import BaseHandler
from engine.step_catalog import BOOLEAN, INTEGER, LOCATION, NUMBER, SOURCE, STRING, TEXT, Output, Param

CONDITION_HELP = ("When the steps run, written like a SQL WHERE clause: %{Check_files.Status} = 'SUCCESS' "
                  "AND %{Check_files.FileCount} > 0. Text goes in quotes.")


class BlockStep(BaseHandler):
    """A step that holds other steps. The runner does its work."""
    BLOCK = True

    def execute_step(self, resolved_params):
        raise NotImplementedError(f"{self.NAME} is run by the runner itself.")


class IfStep(BlockStep):
    CODE = "IF"
    NAME = "If"
    DESCRIPTION = "Runs one set of steps or another, depending on a condition"
    PARAMETERS = (Param("Condition", TEXT, required=True, description=CONDITION_HELP),)


class ElseIfStep(BlockStep):
    CODE = "ELSEIF"
    NAME = "Else If"
    DESCRIPTION = "Inside an If: another condition, tried when the ones before it do not hold"
    HIDDEN = True
    PARAMETERS = (Param("Condition", TEXT, required=True, description=CONDITION_HELP),)


class ThenStep(BlockStep):
    CODE = "THEN"
    NAME = "Then"
    DESCRIPTION = "The steps that run when the condition holds"
    HIDDEN = True


class ElseStep(BlockStep):
    CODE = "ELSE"
    NAME = "Else"
    DESCRIPTION = "The steps that run when no condition holds"
    HIDDEN = True


class ForEachFileStep(BlockStep):
    CODE = "FOR_EACH_FILE"
    NAME = "For Each File"
    DESCRIPTION = "Runs its steps once for each file at a location"
    PARAMETERS = (
        Param("Source", LOCATION, location_role=SOURCE, required=True,
              description="The files to go through. A pattern such as *.csv matches several."),
        Param("ItemName", STRING, default="File",
              description="What the steps inside call the current file, as in %{File.Name} or %{File.FullName}"),
        Param("AllowNoFiles", BOOLEAN, default="True",
              description="Succeed, doing nothing, when no files match. Otherwise the step fails."),
    )
    OUTPUTS = (Output("FileCount", NUMBER, "How many files the loop went through"),)


class WhileStep(BlockStep):
    CODE = "WHILE"
    NAME = "While"
    DESCRIPTION = "Runs its steps again and again while a condition holds"
    PARAMETERS = (
        Param("Condition", TEXT, required=True, description=CONDITION_HELP),
        Param("MaxIterations", INTEGER, required=True, default="100",
              description="The most passes it may make. Going past this fails the step."),
        Param("WaitSeconds", INTEGER, default="0", description="How long to wait before each pass after the first"),
    )
    OUTPUTS = (Output("Passes", NUMBER, "How many passes it has made"),)


FLOW_HANDLERS = [IfStep, ElseIfStep, ThenStep, ElseStep, ForEachFileStep, WhileStep]

# Step types that exist only as parts of an If
BRANCHES = {"THEN", "ELSEIF", "ELSE"}
CONDITIONAL = {"IF", "ELSEIF", "WHILE"}


def structure_problems(code: str, child_codes: Sequence[str], is_block: bool) -> List[str]:
    """
    What is wrong with the steps directly inside a step of this type, in words to put
    after the step's name. Nothing for a step that holds what it should.
    """
    if not is_block:
        return [f"holds {len(child_codes)} step(s), but only If, For Each File and While can hold steps."] \
            if child_codes else []
    if code == "IF":
        return _if_problems(list(child_codes))
    if code == "ELSEIF":
        return [] if list(child_codes) == ["THEN"] else ["must hold one Then and nothing else."]
    misplaced = sorted({c for c in child_codes if c in BRANCHES})
    return [f"cannot hold {BRANCH_NAMES[name]}: only an If can." for name in misplaced]


BRANCH_NAMES = {"THEN": "a Then", "ELSEIF": "an ElseIf", "ELSE": "an Else"}


def top_level_problems(codes: Sequence[str]) -> List[str]:
    """A Then, ElseIf or Else standing on its own, outside an If."""
    return [f"{BRANCH_NAMES[c][0].upper()}{BRANCH_NAMES[c][1:]} can only be part of an If."
            for c in sorted({c for c in codes if c in BRANCHES})]


def _if_problems(codes: List[str]) -> List[str]:
    """An If holds one Then, then any number of ElseIf, then at most one Else, and nothing else."""
    if not codes or codes[0] != "THEN" or codes.count("THEN") != 1:
        return ["must start with one Then, holding the steps that run when its condition holds."]
    rest = codes[1:]
    if any(c not in ("ELSEIF", "ELSE") for c in rest):
        return ["can hold only its Then, ElseIf and Else; put other steps inside one of them."]
    if rest.count("ELSE") > 1 or ("ELSE" in rest and rest[-1] != "ELSE"):
        return ["can have one Else, and it must come last."]
    return []

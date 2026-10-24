"""
Advanced rerun of a job on its own (docs/WORKFLOWS_PHASE7.md, step 6d): the job's top-level steps and what the failed
attempt finished of each, and the operator's two choices about them.

    from_step   start at this step: the steps before it count as done, and it and every step after it run again,
                finished or not. Choosing a step after the failed one passes over the steps between.
    skip_steps  these steps are not run; their %{Name.Status} reads SKIPPED and they have no outputs.

Only top-level steps can be chosen. An If, For Each File or While is one unit: starting at it runs it fresh, skipping
it skips all of it.
"""
from typing import List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.models import Job, JobStep
from engine import step_tree
from engine.control_file import ControlRecord

# Step types that copy, delete, zip or unzip files: run again, they do it again
FILE_STEP_TYPES = {"COPY_FILES", "DELETE_FILES", "ZIP_FILES", "UNZIP_FILES"}
DONE, RUN, SKIPPED = "done", "run", "skipped"


class StepChoice(BaseModel):
    number: str = Field(..., description="The step's number in the job, e.g. 3")
    title: str
    type_name: str
    block: bool = Field(False, description="An If, For Each File or While: it runs, or is skipped, as one unit")
    file_step: bool = Field(False, description="It is, or holds, a step that copies, deletes, zips or unzips files")
    state: str = Field(..., description="What the attempt did with it: finished, failed (where it stopped) or not_run")
    why: Optional[str] = Field(None, description="For a failed step whose effect is not known: why, in words")
    gets: str = Field("", description="What the choices give it: done (as it was), run, or skipped")
    runs_again: bool = Field(False, description="It finished, and the choices run it again")


def steps_for(db: Session, job_key: str, record: ControlRecord) -> List[StepChoice]:
    """The job's active top-level steps as it is now, each with what the attempt finished of it."""
    job = db.query(Job).filter(Job.JobKey == job_key).first()
    if job is None:
        return []
    nodes = step_tree.build(db.query(JobStep).filter(JobStep.job_id == job.MasterObject_id).all())
    failure = record.open_failure()
    found = []
    for node in (n for n in nodes if n.step.IsActive):
        state = record.top_level_state(node.number)
        why = failure.get("why") if state == "failed" and failure.get("operator_decides") else None
        found.append(StepChoice(number=node.number, title=node.step.Title or "", type_name=node.step.step_type.TypeName,
                                block=bool(node.children), file_step=_holds_file_step(node), state=state, why=why))
    return found


def _holds_file_step(node: step_tree.Node) -> bool:
    return any(n.code in FILE_STEP_TYPES for n in step_tree.walk([node]))


def choice_problem(steps: List[StepChoice], from_step: Optional[str], skip_steps: List[str]) -> Optional[str]:
    """Why the choices make no sense, in words, or None."""
    by_number = {s.number: s for s in steps}
    for number in ([from_step] if from_step else []) + list(skip_steps):
        if number not in by_number:
            return f"The job has no step {number} (it has steps {', '.join(by_number)}). Choose one of those."
    for number in skip_steps:
        step = by_number[number]
        if step.state == "finished" and (from_step is None or int(number) < int(from_step)):
            return f"Step {number} '{step.title}' has already finished, so it cannot be skipped."
    return None


def apply_choices(steps: List[StepChoice], from_step: Optional[str], skip_steps: List[str]) -> None:
    """Fills in what each step gets from the choices, as the runner will give it (engine/executor.py)."""
    for step in steps:
        if step.number in skip_steps:
            step.gets = SKIPPED
        elif from_step is not None and int(step.number) < int(from_step):
            step.gets = DONE if step.state == "finished" else SKIPPED
        else:
            step.gets = DONE if step.state == "finished" and from_step is None else RUN
        step.runs_again = step.state == "finished" and step.gets == RUN


def failed_step_is_passed_over(steps: List[StepChoice]) -> bool:
    """Whether the step the attempt failed in does not run again, so what it might have changed needs no decision."""
    return any(s.state == "failed" and s.gets == SKIPPED for s in steps)


def words(steps: List[StepChoice], from_step: Optional[str], skip_steps: List[str]) -> List[str]:
    """What the choices do, as the Restarts list and the Audit Log say it."""
    by_number = {s.number: s for s in steps}
    said = [f"Started at step {from_step} '{by_number[from_step].title}'."] if from_step else []
    passed = [s for s in steps if s.gets == SKIPPED and s.number not in skip_steps and from_step]
    said += [f"Passed over step {s.number} '{s.title}', which had not finished." for s in passed]
    return said + [f"Skipped step {n} '{by_number[n].title}'." for n in skip_steps]


def summary(attempt: int, steps: List[StepChoice], from_step: Optional[str], skip_steps: List[str]) -> str:
    """A sentence for the plan: where the run picks up, what it passes over, and what it does again that had finished."""
    by_number = {s.number: s for s in steps}
    text = f"Advanced rerun of attempt {attempt}"
    if from_step:
        text += (f": it starts at step {from_step} '{by_number[from_step].title}'; the steps before it count as done, "
                 f"and it and every step after it run again")
    again = [s for s in steps if s.runs_again]
    if again:
        text += (". Run again though they finished: " + ", ".join(f"step {s.number} '{s.title}'" for s in again)
                 + (". Those that copy, delete, zip or unzip files do it again" if any(s.file_step for s in again) else ""))
    if skip_steps:
        text += ". Skipped: " + ", ".join(f"step {n} '{by_number[n].title}'" for n in skip_steps)
    return text + "."

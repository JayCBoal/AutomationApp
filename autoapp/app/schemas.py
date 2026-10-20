from datetime import date, datetime
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# --- Job Init Schemas ---
class JobInitRequest(BaseModel):
    job_key: str = Field(..., description="JobKey of the target Job")
    instance_id: str = Field(..., description="Unique execution instance identifier")
    run_count: Optional[int] = Field(1, description="Execution run attempt counter")
    wla_scheduler_id: Optional[str] = Field("LOCAL_DEV", description="Triggering scheduler ID")
    

class JobStepPayloadSchema(BaseModel):
    step_number: int
    step_type: str
    handler_class: str
    title: str
    parameters: Dict[str, Any]
    source_endpoint_id: Optional[int] = None
    dest_endpoint_id: Optional[int] = None


class JobInitResponse(BaseModel):
    status: str
    execution_instance_id: str
    job_id: int
    working_folder: str
    variables: Dict[str, Any]
    steps: List[JobStepPayloadSchema]


# --- Endpoint Schemas ---
class EndpointOut(BaseModel):
    """A registered place files come from or go to."""
    name: str
    application: Optional[str] = None
    site: Optional[str] = Field(None, description="Set if the endpoint is on a remote server")
    entity: Optional[str] = Field(None, description="The outside party that owns the site")
    path: str = Field(..., description="As registered: placeholders unresolved")
    filename_pattern: str
    description: Optional[str] = None


class EndpointCreate(BaseModel):
    name: str = Field(..., max_length=100, description="Letters, digits, hyphens, underscores and full stops")
    application: Optional[str] = Field(None, description="Name of the application whose files these are")
    site: Optional[str] = Field(None, description="Name of the site, if the endpoint is on a remote server")
    path: str = Field(..., max_length=256, description="The folder. May contain placeholders such as ${APP.Root}")
    filename_pattern: str = Field("*", max_length=128, description="Which files a step collects from here")
    description: Optional[str] = Field(None, max_length=256)
    tags: Optional[List[str]] = Field(None, description="Paths of the tags it carries, e.g. Finance/Reporting")


# --- Step Catalog Schemas ---
class StepParameterOut(BaseModel):
    name: str
    data_type: str = Field(..., description="STRING, TEXT (several lines), BOOLEAN, INTEGER, CHOICE or LOCATION")
    required: bool
    default: Optional[str] = None
    description: Optional[str] = None
    display_order: int
    location_role: Optional[str] = Field(None, description="For a LOCATION: SOURCE or DEST")
    endpoint_parameter: Optional[str] = Field(
        None, description="For a LOCATION: the name under which it is given as a registered endpoint")
    allowed_values: Optional[List[str]] = Field(None, description="For a CHOICE")


class StepOutputOut(BaseModel):
    name: str = Field(..., description="Read by later steps as %{StepName.<name>}")
    data_type: str = Field(..., description="STRING or NUMBER")
    description: Optional[str] = None


class StepTypeOut(BaseModel):
    code: str = Field(..., description="Stored on each step; never changes")
    name: str
    description: Optional[str] = None
    active: bool
    has_handler: bool = Field(..., description="False if this server has no code to run the step type")
    block: bool = Field(False, description="True for a step that holds other steps: If, For Each File, While")
    hidden: bool = Field(False, description="True for a part of an If (Then, ElseIf, Else), never chosen on its own")
    parameters: List[StepParameterOut]
    outputs: List[StepOutputOut] = Field(default_factory=list, description="What later steps can read once it has run")


class LastRun(BaseModel):
    status: str
    started: Optional[datetime] = None
    ended: Optional[datetime] = None
    instance_id: str
    run_number: int
    error: Optional[str] = None


class JobSummary(BaseModel):
    """One row of the job search."""
    job_key: str
    description: Optional[str] = None
    active: bool
    job_type: str = "STEPS"
    item_count: int = Field(0, description="For a workflow: how many jobs it uses")
    step_count: int = Field(..., description="Steps that are enabled")
    disabled_step_count: int
    endpoints: List[str] = Field(..., description="Names of the endpoints the job's steps read from or write to")
    ready: bool = Field(..., description="True if the pre-run check finds no problems, so the job would run")
    problem_count: int = Field(..., description="How many problems the pre-run check finds")
    last_run: Optional[LastRun] = Field(None, description="The most recent run AutoApp has a record of")
    tags: List[str] = Field(default_factory=list, description="Paths of the tags the job carries")
    modified: Optional[datetime] = None
    modified_by: Optional[str] = None


class VariableOut(BaseModel):
    name: str
    value: Optional[str] = Field(None, description="Always null for a secret variable: a secret can be set, never read back")
    secret: bool = False
    description: Optional[str] = None


class InheritedVariableOut(BaseModel):
    """A variable an object gets from its tags."""
    name: str
    value: Optional[str] = Field(None, description="******** for a secret")
    secret: bool = False
    source: str = Field(..., description="Path of the tag that defines it: one the object carries, or its parent")
    description: Optional[str] = None
    overridden: bool = Field(False, description="The object's own variable of this name wins over it")


class VariableSave(BaseModel):
    name: str = Field(..., max_length=100)
    value: Optional[str] = Field(
        None, description="For a secret variable that already exists, null or blank keeps the value it has")
    secret: bool = False
    description: Optional[str] = None


class JobStepOut(BaseModel):
    id: int
    order: int = Field(..., description="Its position among the steps of the block it is in, or of the job")
    number: str = Field("", description="As the job log shows it: 3.1 for the first step inside step 3. "
                                         "A Then, ElseIf or Else has its If's number")
    title: Optional[str] = None
    name: Optional[str] = Field(None, description="Its StepName, by which later steps read its outputs: %{Name.Status}")
    active: bool
    on_failure: str = Field("FAIL_JOB", description="FAIL_JOB, CONTINUE or END_SUCCESS")
    step_type: str = Field(..., description="The step type's code; see /api/v1/step-types")
    step_type_name: str
    parameters: Dict[str, Optional[str]] = Field(
        ..., description="As stored: placeholders unresolved, a location under its path or its Endpoint name")
    children: List["JobStepOut"] = Field(default_factory=list, description="The steps inside it, in order")


class PrerequisiteOut(BaseModel):
    """What a workflow's job waits for: another of the workflow's jobs, or something outside the workflow."""
    kind: str = Field("JOB", description=(
        "JOB (a job of this workflow), OTHER_JOB (a job, or a whole workflow, elsewhere), ENDPOINT (files) or TIME"))
    target: str = Field(..., description=(
        "Its name in the workflow: a job's name; for something outside, the name conditions use (MONTH_END.Extract)"))
    test: str = Field("SUCCESS", description="SUCCESS, FAILED, ENDED (whatever happened) or RC (one of return_codes)")
    return_codes: Optional[str] = Field(None, description="For RC: the codes, as 0, 4 or 0-4")
    workflow: Optional[str] = Field(None, description="OTHER_JOB: the key of the other workflow")
    job: Optional[str] = Field(None, description="OTHER_JOB: the job in it, by its name there; empty: the whole workflow")
    look_back_hours: Optional[int] = Field(None, description="OTHER_JOB: only a run that ended within this many hours counts")
    only_after_start: bool = Field(False, description="OTHER_JOB: only a run started after this workflow's run started counts")
    endpoint: Optional[str] = Field(None, description="ENDPOINT: the endpoint's name")
    file_pattern: Optional[str] = Field(None, description="ENDPOINT: the files, if not the endpoint's own pattern")
    min_age_seconds: Optional[int] = Field(None, description="ENDPOINT: every file must have been left alone this long")
    time_condition: Optional[str] = Field(None, description="TIME: a condition over %{Now.Time}, %{Now.Date}, %{Now.Weekday}")
    wait_mode: str = Field("DEFAULT", description=(
        "How long to wait for something outside: DEFAULT (the system setting), NONE (no limit), MINUTES or UNTIL (a time)"))
    wait_minutes: Optional[int] = None
    wait_until: Optional[str] = Field(None, description="For UNTIL: a clock time, as 02:00")
    wait_from: str = Field("OTHERS", description=(
        "When the minutes start: OTHERS (the job's other prerequisites have held), FIRST (the first of them), "
        "CHOSEN (wait_from_target) or RUN_START"))
    wait_from_target: Optional[str] = Field(None, description="For CHOSEN: the name of another prerequisite of the job")
    required: bool = Field(True, description="False: after its limit the job goes on without it (it needs a limit)")


class ReactionActionIO(BaseModel):
    """One thing a Reaction does (docs/WORKFLOWS_PHASE3.md)."""
    action: str = Field(..., description=(
        "COUNT_AS_SUCCEEDED, COUNT_AS_FAILED, RERUN, RERUN_FROM, SKIP, SKIP_BRANCH or KILL_WORKFLOW "
        "(What happens next); START_WORKFLOW (Also)"))
    max_times: Optional[int] = Field(None, description="RERUN and RERUN_FROM: at most this many times in a run")
    wait_seconds: Optional[int] = Field(None, description="RERUN and RERUN_FROM: how long to wait first")
    target: Optional[str] = Field(None, max_length=100, description="RERUN_FROM and SKIP: a job in the workflow, by its name there")
    workflow: Optional[str] = Field(None, max_length=320, description="START_WORKFLOW: the workflow's key")


class ReactionIO(BaseModel):
    """What happens after a job ends, chosen by how it ended."""
    section: str = Field("NEXT", description="NEXT (What happens next: the first that holds decides) or ALSO "
                                             "(every one that holds fires)")
    when: str = Field("FAILED", description="SUCCESS, FAILED, ENDED or RC (one of return_codes)")
    return_codes: Optional[str] = Field(None, max_length=100, description="For RC: the codes, as 0, 4 or 0-4")
    actions: List[ReactionActionIO] = Field(default_factory=list)


class NeededByOut(BaseModel):
    """A job in another workflow that waits for a job of this one."""
    workflow: str
    job: str


class WorkflowItemOut(BaseModel):
    """One job a workflow uses, under its name in the workflow."""
    id: int
    name: str
    job_key: str = Field(..., description="The job it runs")
    job_type: str = Field(..., description="STEPS or WORKFLOW: the type of the job it runs")
    join: str = Field("ALL", description=(
        "ALL: it starts when all its prerequisites hold; ANY: when any one does; CUSTOM: when its rule does"))
    rule: Optional[str] = Field(None, description="With CUSTOM: its Custom rule, a condition over the jobs it names")
    prerequisites: List[PrerequisiteOut] = Field(default_factory=list, description=(
        "With CUSTOM, the jobs its rule names, each with the test RULE"))
    disabled_here: Optional[str] = Field(None, description="STOP or PASS_THROUGH: disabled in this workflow only")
    job_active: bool = Field(True, description="Whether the job it runs is enabled")
    reactions_overridden: bool = Field(False, description="True: reactions below replace the job's own")
    reactions: List[ReactionIO] = Field(default_factory=list, description="This use's own, when it overrides the job's")
    job_reactions: List[ReactionIO] = Field(default_factory=list, description="The job's own Reactions, as it has them")
    variables: List[VariableOut] = Field(default_factory=list, description=(
        "This use's own variables, over the job's own; a secret's value is always null"))
    on_unmet: str = Field("NOT_RUN", description=(
        "When it cannot start (a prerequisite can never hold, or ran out of patience): NOT_RUN or FAIL"))
    needed_by: List["NeededByOut"] = Field(default_factory=list, description=(
        "Jobs in other workflows that wait for this one"))
    embedded: bool = Field(False, description="The job it runs is embedded in this workflow, and belongs to it")
    contents: Optional["JobDetail"] = Field(None, description="With embedded: the embedded job as the page edits it")


class JobDetail(BaseModel):
    """One job with its steps and their parameters, as the job editor shows it."""
    job_key: str
    job_type: str = Field("STEPS", description="STEPS (a job made of steps) or WORKFLOW (made of other jobs)")
    description: Optional[str] = None
    active: bool
    success_return_codes: Optional[str] = Field(None, description="The return codes that mean success; empty means 0")
    created: Optional[datetime] = None
    created_by: Optional[str] = None
    modified: Optional[datetime] = None
    modified_by: Optional[str] = None
    steps: List[JobStepOut]
    variables: List[VariableOut] = Field(default_factory=list, description="The job's own variables, in name order")
    tags: List[str] = Field(default_factory=list, description="Paths of the tags the job carries")
    inherited_variables: List[InheritedVariableOut] = Field(
        default_factory=list, description="What the job's tags give it, in name order")
    items: List[WorkflowItemOut] = Field(default_factory=list, description="A workflow's jobs, in outline order")
    succeeds_when: Optional[str] = Field(None, description=(
        "A workflow's completion rule: it succeeds when this condition holds. Empty: unless a failure went unhandled"))
    return_code_from: Optional[str] = Field(None, description=(
        "A workflow's completion rule: it ends with this job's return code. Empty: 0 if it succeeded, 1 if not"))
    used_in: List[str] = Field(default_factory=list, description="The workflows that use it, in name order")
    reactions: List[ReactionIO] = Field(default_factory=list, description="What happens after it ends, in order")
    owner: Optional[str] = Field(None, description="The workflow this job is embedded in; empty for a job of its own")
    needed_by: List[NeededByOut] = Field(default_factory=list, description=(
        "A workflow: the jobs in other workflows that wait for it as a whole, or for a job in it"))


class PrerequisiteSave(BaseModel):
    kind: str = Field("JOB", description="JOB, OTHER_JOB, ENDPOINT or TIME")
    target: str = Field("", max_length=100, description=(
        "A job: the name, in the workflow, of the job it waits for. Something outside: the name conditions use for it; "
        "left out, it is made from what it waits for"))
    test: str = Field("SUCCESS", description="SUCCESS, FAILED, ENDED or RC (a job, or a workflow elsewhere)")
    return_codes: Optional[str] = Field(None, max_length=100, description="For RC: the codes, as 0, 4 or 0-4")
    workflow: Optional[str] = Field(None, max_length=320, description="OTHER_JOB: the key of the other workflow")
    job: Optional[str] = Field(None, max_length=100, description="OTHER_JOB: its job there; empty: the whole workflow")
    look_back_hours: Optional[int] = Field(None, ge=1, description="OTHER_JOB: only a run that ended within this long counts")
    only_after_start: bool = False
    endpoint: Optional[str] = Field(None, max_length=100, description="ENDPOINT: the endpoint's name")
    file_pattern: Optional[str] = Field(None, max_length=256)
    min_age_seconds: Optional[int] = Field(None, ge=0)
    time_condition: Optional[str] = Field(None, description="TIME: for example %{Now.Time} BETWEEN '06:00' AND '18:00'")
    wait_mode: str = Field("DEFAULT", description="DEFAULT, NONE, MINUTES or UNTIL")
    wait_minutes: Optional[int] = Field(None, ge=1)
    wait_until: Optional[str] = Field(None, max_length=5, description="For UNTIL: a clock time, as 02:00")
    wait_from: str = Field("OTHERS", description="OTHERS, FIRST, CHOSEN or RUN_START")
    wait_from_target: Optional[str] = Field(None, max_length=100)
    required: bool = True


class WorkflowItemSave(BaseModel):
    id: Optional[int] = Field(None, description="The item's id when changing an existing one; leave out for a new one")
    name: Optional[str] = Field(None, max_length=100, description=(
        "Its name in the workflow: letters, digits, '_' and '-'. Left out, it is made from the job key"))
    job_key: str = Field("", max_length=320, description="The job it runs. Left out for an embedded one")
    embedded: Optional["EmbeddedJobSave"] = Field(None, description=(
        "The job or workflow this item runs, embedded in the workflow: it belongs to it, is hidden from the lists and "
        "is saved with it. Its key is made from the owner's and the item's name"))
    join: str = Field("ALL", description="ALL, ANY or CUSTOM")
    rule: Optional[str] = Field(None, description=(
        "With CUSTOM: a condition over %{Name.Output} and ${...}; the jobs it names become its prerequisites"))
    prerequisites: List[PrerequisiteSave] = Field(default_factory=list, description="Ignored with CUSTOM")
    disabled_here: Optional[str] = Field(None, description="Empty, STOP (it ends Disabled) or PASS_THROUGH (Bypassed)")
    reactions_overridden: bool = Field(False, description="True: reactions replace the job's own, even when empty")
    reactions: List[ReactionIO] = Field(default_factory=list, description="Kept only when reactions_overridden")
    variables: Optional[List[VariableSave]] = Field(None, description=(
        "This use's own variables, over the job's own. Left out, they stay as they are; "
        "for a secret that exists, a null or blank value keeps it"))
    on_unmet: str = Field("NOT_RUN", description="NOT_RUN (it ends Not run) or FAIL (it ends Failed) when it cannot start")


class JobStepSave(BaseModel):
    id: Optional[int] = Field(None, description="The step's id when changing an existing step; leave out for a new one")
    title: Optional[str] = Field(None, max_length=150)
    name: Optional[str] = Field(None, max_length=64, description=(
        "Its StepName: letters, digits and underscores, starting with a letter. Left out, it is made from the title"))
    active: bool = True
    on_failure: str = Field("FAIL_JOB", description="FAIL_JOB, CONTINUE or END_SUCCESS")
    step_type: str = Field(..., description="A step type code from /api/v1/step-types")
    parameters: Dict[str, Optional[str]] = Field(
        default_factory=dict, description="Blank values are not stored, so the step type's default applies")
    children: List["JobStepSave"] = Field(default_factory=list, description=(
        "The steps inside it, for an If (its Then, ElseIf and Else), an ElseIf (its Then), a Then, an Else, "
        "a For Each File or a While. A step moved in or out of a block keeps its id"))


class JobSave(BaseModel):
    """A whole job as the editor submits it. The steps run in the order given."""
    job_key: str = Field(..., max_length=320)
    job_type: str = Field("STEPS", description="STEPS or WORKFLOW. It cannot be changed once the job is created")
    description: Optional[str] = None
    active: bool = True
    success_return_codes: Optional[str] = Field(None, max_length=100, description="Empty means 0")
    steps: List[JobStepSave] = Field(default_factory=list)
    items: List[WorkflowItemSave] = Field(default_factory=list, description="A workflow's jobs, in outline order")
    succeeds_when: Optional[str] = Field(None, description="A workflow: when it succeeds, as a condition; empty for the default")
    return_code_from: Optional[str] = Field(None, max_length=100, description=(
        "A workflow: the job, by its name in it, whose return code it ends with; empty for 0 or 1"))
    variables: Optional[List[VariableSave]] = Field(
        None, description="The job's own variables. Leave out to keep them as they are; send a list to replace them")
    tags: Optional[List[str]] = Field(
        None, description="Paths of the tags the job carries. Leave out to keep them as they are")
    reactions: Optional[List[ReactionIO]] = Field(
        None, description="What happens after it ends. Leave out to keep them as they are; send a list to replace them")
    move_working_folder: bool = Field(False, description=(
        "With a new job_key: move the job's working folder to the new key's name. Ignored when the folder is not on "
        "this server's disk"))


class MakeShared(BaseModel):
    """Frees an embedded job from the workflow it belongs to."""
    job_key: str = Field(..., max_length=320, description="Its key as a job of its own; its present key keeps it as it is")
    move_working_folder: bool = Field(False, description="With a different key: move the working folder to the new key's name")


class RenameFacts(BaseModel):
    """What renaming a job would leave behind, for the warning shown before a rename."""
    run_count: int
    running: bool = Field(..., description="The job is running, so a rename is refused")
    working_folder: Optional[str] = Field(None, description="The working folder on this server's disk, if it exists")
    can_move_folder: bool = Field(..., description="The folder can be moved with the job")
    needs_warning: bool = Field(..., description="The job has run history or a working folder")


class EmbeddedJobSave(JobSave):
    """A job or workflow embedded in a workflow, as its item sends it: a job with no key of its own to give."""
    job_key: str = Field("", max_length=320)


class JobSaveResult(BaseModel):
    """The job as saved, and what the pre-run check makes of it. A job is saved even if the check finds problems."""
    job: JobDetail
    valid: bool
    problems: List[str]
    changes: List[str] = Field(..., description="What this save changed, as recorded in the audit log")


class FieldPreview(BaseModel):
    resolved: Optional[str] = Field(None, description="What the value becomes when the job runs")
    error: Optional[str] = Field(None, description="Why it cannot be resolved, if it cannot")
    warnings: List[str] = Field(default_factory=list, description=(
        "Worth knowing but not stopping the job, such as a condition comparing text with a number"))


class JobPreview(BaseModel):
    """What a job, as submitted but not saved, would resolve to and whether it would run."""
    valid: bool
    checked_as: Optional[str] = Field(None, description=(
        "Set when it was checked as a workflow runs it (workflow and use given): which workflow and use"))
    problems: List[str]
    warnings: List[str] = Field(default_factory=list, description=(
        "Things worth knowing that do not stop the job, such as two tags disagreeing about a variable it does not use"))
    tags: List[str] = Field(default_factory=list, description="Paths of the tags as submitted")
    inherited_variables: List[InheritedVariableOut] = Field(default_factory=list)
    steps: List[Dict[str, FieldPreview]] = Field(
        ..., description="For each step submitted, in order, each block before the steps inside it: "
                         "each parameter by name. A location appears under its parameter name however the step gave it")


class JobCheckResult(BaseModel):
    job_key: str
    valid: bool
    checked_as: Optional[str] = Field(None, description=(
        "Set when it was checked as a workflow runs it (workflow and use given): which workflow and use"))
    problems: List[str]
    warnings: List[str] = Field(default_factory=list, description="Such as the scheduler's parameters not being readable")


# --- Telemetry Schemas ---
# The records a runner writes to its spool file and posts to /api/v1/telemetry/records.
# Field names match the spool file, so a spool line can be posted unchanged.
# Lengths match the columns the values are stored in, so an over-long value is
# refused with a clear message on every database.
class RunStartRecord(BaseModel):
    Record: Literal["RUN_START"]
    RunID: str = Field(..., min_length=1, max_length=36, description="Generated by the runner for each execution")
    Seq: int
    JobKey: str = Field(..., max_length=320)
    InstanceID: str = Field(..., max_length=64, description="The scheduler's ID for this job instance")
    RunNumber: int = 1
    Scheduler: Optional[str] = Field(None, max_length=100)
    BusinessDate: Optional[date] = Field(None, description="The date the run is for, if the scheduler gave one")
    Host: Optional[str] = Field(None, max_length=255)
    LogFile: Optional[str] = Field(None, max_length=500, description=(
        "Where the run's job log is, within the host's log folder: <YYYY-MM-DD>/<RunID>.log"))
    StartedAtUtc: datetime
    ParentRunID: Optional[str] = Field(None, max_length=36, description="The workflow run this job run is part of")
    WorkflowPath: Optional[str] = Field(None, max_length=1000, description="Its place in that workflow: Transform/Stage")
    Attempt: int = 1
    ProcessID: Optional[int] = Field(None, description="The runner's process on Host, so the run can be killed")


class OperationRecord(BaseModel):
    Record: Literal["OPERATION"]
    RunID: str
    Seq: int
    StepID: Optional[int] = None
    StepOrder: Optional[int] = None
    StepNumber: Optional[str] = Field(None, max_length=50, description="e.g. 3.1 for the first step inside step 3")
    Iteration: Optional[str] = Field(None, max_length=50, description="The loops' passes: 2, or 2.3 in nested loops")
    OpType: str = Field(..., max_length=50)
    Status: str = Field(..., max_length=20)
    SourcePath: Optional[str] = None
    SourceFilename: Optional[str] = Field(None, max_length=255)
    SourceSize: Optional[int] = None
    SourceEndpointID: Optional[int] = None
    DestPath: Optional[str] = None
    DestFilename: Optional[str] = Field(None, max_length=255)
    DestSize: Optional[int] = None
    DestEndpointID: Optional[int] = None
    Checksum: Optional[str] = Field(None, max_length=64)
    Details: Optional[Dict[str, Any]] = None
    Error: Optional[str] = None
    StartedAtUtc: Optional[datetime] = None
    EndedAtUtc: datetime


class RunEndRecord(BaseModel):
    Record: Literal["RUN_END"]
    RunID: str
    Seq: int
    Status: str = Field(..., max_length=20)
    Error: Optional[str] = None
    ReturnCode: Optional[int] = Field(None, description="The job's return code: 0 unless a step set one")
    Reason: Optional[str] = Field(None, max_length=40, description="Why it failed: ERROR, RETURN_CODE or KILLED")
    StatusBeforeOverride: Optional[str] = Field(None, max_length=20, description=(
        "What it ended as before a Reaction counted it as succeeded or failed"))
    FileCount: Optional[int] = Field(None, description="How many files the run delivered (wrote to a destination)")
    Bytes: Optional[int] = Field(None, description="The size of the files it delivered, added up")
    EndedAtUtc: datetime


class ReactionRecord(BaseModel):
    """A Reaction's action that fired after a job run on its own ended, or was passed over at its limit."""
    Record: Literal["REACTION"]
    RunID: str
    Seq: int
    Action: str = Field(..., max_length=30)
    Result: str = Field(..., max_length=20, description="TOOK_EFFECT or LIMIT_REACHED")
    Message: Optional[str] = None
    ReactionActionID: Optional[int] = None
    AtUtc: datetime


class LogRecord(BaseModel):
    """
    Lines of the job log, as runners sent them before logs were kept as files (2026-10-17).
    Still accepted, so an old spool file loads, but the lines are not kept.
    """
    Record: Literal["LOG"]
    RunID: str
    Seq: int
    Lines: List[str]


TelemetryRecord = Annotated[Union[RunStartRecord, OperationRecord, LogRecord, RunEndRecord, ReactionRecord],
                            Field(discriminator="Record")]


class TelemetryBatch(BaseModel):
    records: List[TelemetryRecord]


class TelemetryIngestResult(BaseModel):
    runs_started: int
    runs_ended: int
    operations_added: int
    duplicates_skipped: int


# --- Operations Log & File Trace Schemas ---
class FileLocation(BaseModel):
    """One side of an operation. Endpoint is null for a location inside the job's working folder."""
    endpoint: Optional[str] = None
    application: Optional[str] = None
    entity: Optional[str] = None
    site: Optional[str] = None
    path: Optional[str] = None
    filename: Optional[str] = None
    size: Optional[int] = None


class OperationOut(BaseModel):
    id: int
    op_type: str
    status: str
    source: FileLocation
    dest: FileLocation
    checksum: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started: Optional[datetime] = None
    ended: Optional[datetime] = None
    job_key: str
    instance_id: str
    run_number: int
    scheduler: Optional[str] = None
    run_id: str
    step_order: Optional[int] = None
    step_number: Optional[str] = Field(None, description="The step's number, e.g. 3.1 inside step 3")
    iteration: Optional[str] = Field(None, description="Which pass of the loops around the step: 2, or 2.3 when nested")


class TraceHop(OperationOut):
    # The operation that put the file where this one found it; null for the first hop
    follows: Optional[int] = None


class FileTrace(BaseModel):
    filename: Optional[str]
    hops: List[TraceHop]


JobStepOut.model_rebuild()
WorkflowItemSave.model_rebuild()
WorkflowItemOut.model_rebuild()
JobDetail.model_rebuild()
JobStepSave.model_rebuild()

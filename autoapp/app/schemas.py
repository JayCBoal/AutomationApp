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


class StepTypeOut(BaseModel):
    code: str = Field(..., description="Stored on each step; never changes")
    name: str
    description: Optional[str] = None
    active: bool
    has_handler: bool = Field(..., description="False if this server has no code to run the step type")
    parameters: List[StepParameterOut]


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
    step_count: int = Field(..., description="Steps that are enabled")
    disabled_step_count: int
    endpoints: List[str] = Field(..., description="Names of the endpoints the job's steps read from or write to")
    ready: bool = Field(..., description="True if the pre-run check finds no problems, so the job would run")
    problem_count: int = Field(..., description="How many problems the pre-run check finds")
    last_run: Optional[LastRun] = Field(None, description="The most recent run RunMyFiles has a record of")
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
    order: int
    title: Optional[str] = None
    active: bool
    step_type: str = Field(..., description="The step type's code; see /api/v1/step-types")
    step_type_name: str
    parameters: Dict[str, Optional[str]] = Field(
        ..., description="As stored: placeholders unresolved, a location under its path or its Endpoint name")


class JobDetail(BaseModel):
    """One job with its steps and their parameters, as the job editor shows it."""
    job_key: str
    description: Optional[str] = None
    active: bool
    created: Optional[datetime] = None
    created_by: Optional[str] = None
    modified: Optional[datetime] = None
    modified_by: Optional[str] = None
    steps: List[JobStepOut]
    variables: List[VariableOut] = Field(default_factory=list, description="The job's own variables, in name order")
    tags: List[str] = Field(default_factory=list, description="Paths of the tags the job carries")
    inherited_variables: List[InheritedVariableOut] = Field(
        default_factory=list, description="What the job's tags give it, in name order")


class JobStepSave(BaseModel):
    id: Optional[int] = Field(None, description="The step's id when changing an existing step; leave out for a new one")
    title: Optional[str] = Field(None, max_length=150)
    active: bool = True
    step_type: str = Field(..., description="A step type code from /api/v1/step-types")
    parameters: Dict[str, Optional[str]] = Field(
        default_factory=dict, description="Blank values are not stored, so the step type's default applies")


class JobSave(BaseModel):
    """A whole job as the editor submits it. The steps run in the order given."""
    job_key: str = Field(..., max_length=320)
    description: Optional[str] = None
    active: bool = True
    steps: List[JobStepSave] = Field(default_factory=list)
    variables: Optional[List[VariableSave]] = Field(
        None, description="The job's own variables. Leave out to keep them as they are; send a list to replace them")
    tags: Optional[List[str]] = Field(
        None, description="Paths of the tags the job carries. Leave out to keep them as they are")


class JobSaveResult(BaseModel):
    """The job as saved, and what the pre-run check makes of it. A job is saved even if the check finds problems."""
    job: JobDetail
    valid: bool
    problems: List[str]
    changes: List[str] = Field(..., description="What this save changed, as recorded in the audit log")


class FieldPreview(BaseModel):
    resolved: Optional[str] = Field(None, description="What the value becomes when the job runs")
    error: Optional[str] = Field(None, description="Why it cannot be resolved, if it cannot")


class JobPreview(BaseModel):
    """What a job, as submitted but not saved, would resolve to and whether it would run."""
    valid: bool
    problems: List[str]
    warnings: List[str] = Field(default_factory=list, description=(
        "Things worth knowing that do not stop the job, such as two tags disagreeing about a variable it does not use"))
    tags: List[str] = Field(default_factory=list, description="Paths of the tags as submitted")
    inherited_variables: List[InheritedVariableOut] = Field(default_factory=list)
    steps: List[Dict[str, FieldPreview]] = Field(
        ..., description="For each step submitted, in order: each parameter by name. "
                         "A location appears under its parameter name however the step gave it")


class JobCheckResult(BaseModel):
    job_key: str
    valid: bool
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
    StartedAtUtc: datetime


class OperationRecord(BaseModel):
    Record: Literal["OPERATION"]
    RunID: str
    Seq: int
    StepID: Optional[int] = None
    StepOrder: Optional[int] = None
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
    EndedAtUtc: datetime


class LogRecord(BaseModel):
    """Lines of the job log, as the runner printed them, secrets already masked."""
    Record: Literal["LOG"]
    RunID: str
    Seq: int
    Lines: List[str]


TelemetryRecord = Annotated[Union[RunStartRecord, OperationRecord, LogRecord, RunEndRecord],
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


class TraceHop(OperationOut):
    # The operation that put the file where this one found it; null for the first hop
    follows: Optional[int] = None


class FileTrace(BaseModel):
    filename: Optional[str]
    hops: List[TraceHop]

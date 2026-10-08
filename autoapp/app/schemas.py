from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


# --- Job Init Schemas ---
class JobInitRequest(BaseModel):
    job_name: str = Field(..., description="Name or unique key of the target Job")
    instance_id: str = Field(..., description="Unique execution instance identifier")
    process_name: Optional[str] = Field(None, description="Optional parent Process name override")
    run_count: Optional[int] = Field(1, description="Execution run attempt counter")
    wla_scheduler_id: Optional[str] = Field("LOCAL_DEV", description="Triggering scheduler ID")
    

class JobStepPayloadSchema(BaseModel):
    step_number: int
    step_type: str
    handler_class: str
    title: str
    parameters: Dict[str, Any]


class JobInitResponse(BaseModel):
    status: str
    execution_instance_id: str
    job_id: int
    process_id: int
    working_folder: str
    variables: Dict[str, Any]
    steps: List[JobStepPayloadSchema]


# --- Telemetry Schemas ---
class OpsTelemetryItem(BaseModel):
    execution_instance_id: str
    step_number: int
    op_type: str
    op_status: str
    bytes_transferred: Optional[int] = 0
    source_uri: Optional[str] = None
    destination_uri: Optional[str] = None
    details: Optional[str] = None


class BatchOpsTelemetryRequest(BaseModel):
    events: List[OpsTelemetryItem]


class AuditTelemetryItem(BaseModel):
    execution_instance_id: str
    step_number: Optional[int] = None
    log_level: str
    message: str
    source_component: str
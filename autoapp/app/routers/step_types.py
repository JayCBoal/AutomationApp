import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import StepType
from app.schemas import StepParameterOut, StepTypeOut
from engine.handlers import HANDLER_REGISTRY
from engine.step_catalog import ENDPOINT_SUFFIX, LOCATION

router = APIRouter(prefix="/api/v1/step-types", tags=["Step Catalog"])


def _describe(step_type: StepType) -> StepTypeOut:
    return StepTypeOut(
        code=step_type.HandlerClass,
        name=step_type.TypeName,
        description=step_type.Description,
        active=bool(step_type.IsActive),
        has_handler=step_type.HandlerClass in HANDLER_REGISTRY,
        parameters=[
            StepParameterOut(
                name=d.ParamName,
                data_type=d.DataType,
                required=bool(d.IsRequired),
                default=d.DefaultValue,
                description=d.Description,
                display_order=d.DisplayOrder,
                location_role=d.LocationRole,
                endpoint_parameter=d.ParamName + ENDPOINT_SUFFIX if d.DataType == LOCATION else None,
                allowed_values=json.loads(d.AllowedValues) if d.AllowedValues else None,
            )
            for d in step_type.definitions
        ],
    )


@router.get("", response_model=List[StepTypeOut])
def list_step_types(db: Session = Depends(get_db)):
    """
    The step catalog: every step type and the parameters it takes, in the order a
    form should show them. This is what a job editor builds its step forms from.
    """
    return [_describe(step_type) for step_type in db.query(StepType).order_by(StepType.TypeName).all()]


@router.get("/{code}", response_model=StepTypeOut)
def get_step_type(code: str, db: Session = Depends(get_db)):
    step_type = db.query(StepType).filter(StepType.HandlerClass == code).first()
    if not step_type:
        raise HTTPException(status_code=404, detail=f"No step type with code '{code}' exists.")
    return _describe(step_type)

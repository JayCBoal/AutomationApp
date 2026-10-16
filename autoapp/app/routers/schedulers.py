"""
Reading a scheduler's jobs through its connector (app/connectors):

    GET /api/v1/schedulers/{name}/jobs/{wla_job}    one of the WLA's jobs, with its parameters

Registering and changing schedulers is in app/routers/registry.py and definitions.py.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.connectors import ConnectorError, WlaJob, connector_for
from app.database import get_db
from app.models import Scheduler

router = APIRouter(prefix="/api/v1/schedulers", tags=["Schedulers"])


class WlaParameterOut(BaseModel):
    name: str
    value: Optional[str] = Field(None, description="Null for a secret: the scheduler does not give it out")
    secret: bool


class WlaJobOut(BaseModel):
    scheduler: str
    name: str
    description: Optional[str] = None
    parameters: List[WlaParameterOut]


def read_wla_job(db: Session, scheduler_name: str, wla_job: str) -> WlaJob:
    """A WLA job, read through its scheduler's connector. Raises ConnectorError, or 404 for an unknown scheduler."""
    scheduler = db.query(Scheduler).filter(Scheduler.Name == scheduler_name).first()
    if scheduler is None:
        raise HTTPException(404, f"There is no scheduler named '{scheduler_name}'.")
    return connector_for(scheduler).job(wla_job)


@router.get("/{name}/jobs/{wla_job:path}", response_model=WlaJobOut)
def get_wla_job(name: str, wla_job: str, db: Session = Depends(get_db)):
    """
    One of the scheduler's own jobs, as its API gives it: chiefly its parameters,
    which it sets in the environment when it runs the job. Secret values are not given.
    """
    try:
        job = read_wla_job(db, name, wla_job)
    except ConnectorError as e:
        raise HTTPException(502, str(e))
    return WlaJobOut(scheduler=name, name=job.name, description=job.description,
                     parameters=[WlaParameterOut(name=p.name, value=None if p.secret else p.value, secret=p.secret)
                                 for p in job.parameters])

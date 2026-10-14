import json
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Application, Audit, Endpoint, Site
from app.schemas import EndpointCreate, EndpointOut

router = APIRouter(prefix="/api/v1/endpoints", tags=["Endpoints"])

MAX_RESULTS = 500

# A step refers to an endpoint by its name, so the name is kept to characters that are safe anywhere
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# Recorded as who made a change. There are no user accounts yet.
EDITOR_NAME = "web interface"


def describe(endpoint: Endpoint) -> EndpointOut:
    return EndpointOut(
        name=endpoint.Name,
        application=endpoint.application.Name if endpoint.application else None,
        site=endpoint.site.Name if endpoint.site else None,
        entity=endpoint.site.entity.Name if endpoint.site and endpoint.site.entity else None,
        path=endpoint.Path,
        filename_pattern=endpoint.FilenamePattern,
        description=endpoint.Description,
    )


@router.get("", response_model=List[EndpointOut])
def list_endpoints(
    name: Optional[str] = Query(None, description="Part of an endpoint name"),
    limit: int = Query(MAX_RESULTS, ge=1, le=MAX_RESULTS),
    db: Session = Depends(get_db),
):
    """The registered endpoints, in name order. This is what the job editor offers for a step's file locations."""
    query = db.query(Endpoint)
    if name:
        query = query.filter(Endpoint.Name.ilike(f"%{name}%"))
    return [describe(e) for e in query.order_by(func.lower(Endpoint.Name), Endpoint.Name).limit(limit)]


@router.post("", response_model=EndpointOut, status_code=status.HTTP_201_CREATED)
def create_endpoint(payload: EndpointCreate, db: Session = Depends(get_db)):
    """Registers a place files come from or go to, so that job steps can refer to it by name."""
    name = payload.name.strip()
    if not NAME_PATTERN.match(name):
        raise HTTPException(422, f"Invalid endpoint name '{payload.name}': use letters, digits, '-', '_' and '.', "
                                 f"starting with a letter or digit.")
    if db.query(Endpoint.id).filter(Endpoint.Name == name).first():
        raise HTTPException(409, f"An endpoint named '{name}' is already registered.")
    path, pattern = payload.path.strip(), payload.filename_pattern.strip()
    if not path:
        raise HTTPException(422, "An endpoint needs a path.")
    if not pattern:
        raise HTTPException(422, "An endpoint needs a filename pattern. Use * for every file.")

    application = site = None
    if payload.application and payload.application.strip():
        application = db.query(Application).filter(Application.Name == payload.application.strip()).first()
        if not application:
            raise HTTPException(422, f"There is no application named '{payload.application.strip()}'.")
    if payload.site and payload.site.strip():
        site = db.query(Site).filter(Site.Name == payload.site.strip()).first()
        if not site:
            raise HTTPException(422, f"There is no site named '{payload.site.strip()}'.")

    endpoint = Endpoint(
        Name=name, Path=path, FilenamePattern=pattern,
        Description=(payload.description or "").strip() or None,
        Application_MasterObject_id=application.MasterObject_id if application else None,
        Site_MasterObject_id=site.MasterObject_id if site else None,
        ModifiedBy=EDITOR_NAME,
    )
    db.add(endpoint)
    db.add(Audit(Action="ENDPOINT_CREATED", PerformedBy=EDITOR_NAME,
                 Details=json.dumps({"endpoint": name, "changes": [f"Registered endpoint '{name}'."]})))
    db.commit()
    db.refresh(endpoint)
    return describe(endpoint)

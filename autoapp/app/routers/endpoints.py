from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Endpoint
from app.schemas import EndpointOut

router = APIRouter(prefix="/api/v1/endpoints", tags=["Endpoints"])

MAX_RESULTS = 500


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
    return [
        EndpointOut(
            name=endpoint.Name,
            application=endpoint.application.Name if endpoint.application else None,
            site=endpoint.site.Name if endpoint.site else None,
            entity=endpoint.site.entity.Name if endpoint.site and endpoint.site.entity else None,
            path=endpoint.Path,
            filename_pattern=endpoint.FilenamePattern,
            description=endpoint.Description,
        )
        for endpoint in query.order_by(func.lower(Endpoint.Name), Endpoint.Name).limit(limit)
    ]

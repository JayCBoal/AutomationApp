from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Application, Endpoint, Entity, Job, JobRun, Scheduler, Site, Tag
from engine.tag_vars import tag_path

router = APIRouter(prefix="/api/v1/lookups", tags=["Lookups"])


class LookupEntry(BaseModel):
    value: str
    label: Optional[str] = None     # shown beside the value, to tell entries apart


@router.get("", response_model=Dict[str, List[LookupEntry]])
def get_lookups(db: Session = Depends(get_db)):
    """
    The names a page offers in its drop-downs, wherever a box refers to something
    registered elsewhere: an endpoint, an application, an entity, a site, a job, a
    scheduler, a tag. Each list is in name order.
    """
    def in_order(query, name_column):
        return query.order_by(func.lower(name_column), name_column).all()

    def endpoint_label(endpoint):
        owner = " · ".join(filter(None, [
            endpoint.application.Name if endpoint.application else None,
            endpoint.site.entity.Name if endpoint.site and endpoint.site.entity else None,
            endpoint.site.Name if endpoint.site else None,
        ]))
        return "  —  ".join(filter(None, [owner, f"{endpoint.Path}/{endpoint.FilenamePattern}"]))

    schedulers = (
        db.query(JobRun.SchedulerName).filter(JobRun.SchedulerName.isnot(None)).distinct()
        .order_by(JobRun.SchedulerName).all()
    )
    return {
        "endpoints": [LookupEntry(value=e.Name, label=endpoint_label(e)) for e in in_order(db.query(Endpoint), Endpoint.Name)],
        "applications": [LookupEntry(value=a.Name, label=a.Description) for a in in_order(db.query(Application), Application.Name)],
        "entities": [LookupEntry(value=e.Name, label=e.Description) for e in in_order(db.query(Entity), Entity.Name)],
        "sites": [LookupEntry(value=s.Name, label=" · ".join(filter(None, [s.entity.Name if s.entity else None, s.Host])))
                  for s in in_order(db.query(Site), Site.Name)],
        "jobs": [LookupEntry(value=j.JobKey, label=j.Description) for j in in_order(db.query(Job), Job.JobKey)],
        # Registered schedulers, and any other name a run has given
        "schedulers": sorted(
            [LookupEntry(value=s.Name, label=s.Technology) for s in db.query(Scheduler)]
            + [LookupEntry(value=name) for (name,) in schedulers
               if not db.query(Scheduler.MasterObject_id).filter(Scheduler.Name == name).first()],
            key=lambda entry: (entry.value.lower(), entry.value)),
        # A tag is named by its path; listed in path order, so each sits under its parent
        "tags": [LookupEntry(value=path, label=tag.Description)
                 for path, tag in sorted(((tag_path(t), t) for t in db.query(Tag)), key=lambda pt: (pt[0].lower(), pt[0]))],
    }

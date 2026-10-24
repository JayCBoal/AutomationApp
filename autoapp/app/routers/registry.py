"""
Registering applications, entities, sites and tags.

Each has a create route, used by the detail pages' "New" button and by the
"New..." links in the web interface, which let something be registered at the
moment it is first needed. Searching, changing and removing them is in
app/routers/definitions.py.
"""
import json
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import get_db
from app import tag_store
from app.job_store import JobStoreError, apply_variables
from core.models import Application, Audit, Entity, Scheduler, Site, Tag
from app.schemas import VariableSave
from core.tag_vars import shown, tag_path

# These names are referred to from elsewhere, so they are kept to characters that are safe anywhere
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# Recorded as who made a change. There are no user accounts yet.
EDITOR_NAME = "web interface"


def clean_name(kind: str, name: str, model, db: Session) -> str:
    """The name, trimmed. Raises 422 if it is not usable and 409 if it is taken."""
    name = name.strip()
    if not NAME_PATTERN.match(name):
        raise HTTPException(422, f"Invalid {kind} name '{name}': use letters, digits, '-', '_' and '.', "
                                 f"starting with a letter or digit.")
    if db.query(model).filter(model.Name == name).first():
        article = "An" if kind[0] in "aeiou" else "A"
        raise HTTPException(409, f"{article} {kind} named '{name}' is already registered.")
    return name


def required(kind: str, label: str, value: Optional[str]) -> str:
    value = (value or "").strip()
    if not value:
        article = "An" if kind[0] in "aeiou" else "A"
        raise HTTPException(422, f"{article} {kind} needs {label}.")
    return value


def record(db: Session, obj, kind: str, name: str, variables: Optional[List[VariableSave]] = None,
           tags: Optional[List[str]] = None) -> None:
    db.add(obj)
    db.flush()
    try:
        if variables:
            apply_variables(obj, variables, creating=True)
        if tags:
            tag_store.apply_tags(db, obj, tags)
    except JobStoreError as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.add(Audit(MasterObject_id=obj.MasterObject_id, Action=f"{kind.upper()}_CREATED", PerformedBy=EDITOR_NAME,
                 Details=json.dumps({kind: name, "changes": [f"Registered {kind} '{name}'."]})))
    db.commit()
    db.refresh(obj)


# --- Applications ---------------------------------------------------------------------------------

applications = APIRouter(prefix="/api/v1/applications", tags=["Applications"])


class ApplicationCreate(BaseModel):
    name: str = Field(..., max_length=100)
    abbr: str = Field(..., max_length=10, description="A short form of the name, unique among applications")
    description: Optional[str] = None
    active: bool = True
    variables: Optional[List[VariableSave]] = None
    tags: Optional[List[str]] = Field(None, description="Paths of the tags it carries, e.g. Finance/Reporting")


class ApplicationOut(BaseModel):
    name: str
    abbr: str
    description: Optional[str] = None


@applications.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create_application(payload: ApplicationCreate, db: Session = Depends(get_db)):
    """Registers an application: a system that produces or consumes files."""
    name = clean_name("application", payload.name, Application, db)
    abbr = required("application", "an abbreviation", payload.abbr)
    if db.query(Application).filter(Application.Abbr == abbr).first():
        raise HTTPException(409, f"The abbreviation '{abbr}' is already used by another application.")
    application = Application(Name=name, Abbr=abbr, Description=(payload.description or "").strip() or None,
                              IsActive=payload.active, CreatedBy=EDITOR_NAME)
    record(db, application, "application", name, payload.variables, payload.tags)
    return ApplicationOut(name=application.Name, abbr=application.Abbr, description=application.Description)


# --- Entities -------------------------------------------------------------------------------------

entities = APIRouter(prefix="/api/v1/entities", tags=["Entities"])


class EntityCreate(BaseModel):
    name: str = Field(..., max_length=64)
    abbr: str = Field(..., max_length=10)
    description: Optional[str] = Field(None, max_length=256)
    active: bool = True
    variables: Optional[List[VariableSave]] = None
    tags: Optional[List[str]] = Field(None, description="Paths of the tags it carries, e.g. Finance/Reporting")


class EntityOut(BaseModel):
    name: str
    abbr: str
    description: Optional[str] = None


@entities.post("", response_model=EntityOut, status_code=status.HTTP_201_CREATED)
def create_entity(payload: EntityCreate, db: Session = Depends(get_db)):
    """Registers an entity: an outside party, such as a vendor, client or partner."""
    name = clean_name("entity", payload.name, Entity, db)
    abbr = required("entity", "an abbreviation", payload.abbr)
    entity = Entity(Name=name, Abbr=abbr, Description=(payload.description or "").strip() or None,
                    IsActive=payload.active, CreatedBy=EDITOR_NAME)
    record(db, entity, "entity", name, payload.variables, payload.tags)
    return EntityOut(name=entity.Name, abbr=entity.Abbr, description=entity.Description)


# --- Sites ----------------------------------------------------------------------------------------

sites = APIRouter(prefix="/api/v1/sites", tags=["Sites"])


class SiteCreate(BaseModel):
    name: str = Field(..., max_length=64)
    entity: Optional[str] = Field(None, description="Name of the entity whose server this is")
    host: str = Field(..., max_length=128)
    port: int = Field(22, ge=1, le=65535)
    protocol: str = Field("SFTP", max_length=16)
    description: Optional[str] = Field(None, max_length=256)
    active: bool = True
    variables: Optional[List[VariableSave]] = None
    tags: Optional[List[str]] = Field(None, description="Paths of the tags it carries, e.g. Finance/Reporting")


class SiteOut(BaseModel):
    name: str
    entity: Optional[str] = None
    host: str
    port: int
    protocol: str
    description: Optional[str] = None


@sites.post("", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
def create_site(payload: SiteCreate, db: Session = Depends(get_db)):
    """Registers a site: a server, usually an outside party's, that files are sent to or fetched from."""
    name = clean_name("site", payload.name, Site, db)
    host = required("site", "a host", payload.host)
    protocol = required("site", "a protocol", payload.protocol).upper()
    entity = None
    if payload.entity and payload.entity.strip():
        entity = db.query(Entity).filter(Entity.Name == payload.entity.strip()).first()
        if not entity:
            raise HTTPException(422, f"There is no entity named '{payload.entity.strip()}'.")
    site = Site(Name=name, Host=host, Port=payload.port, Protocol=protocol,
                Description=(payload.description or "").strip() or None,
                Entity_MasterObject_id=entity.MasterObject_id if entity else None,
                IsActive=payload.active, CreatedBy=EDITOR_NAME)
    record(db, site, "site", name, payload.variables, payload.tags)
    return SiteOut(name=site.Name, entity=entity.Name if entity else None, host=site.Host, port=site.Port,
                   protocol=site.Protocol, description=site.Description)


# --- Schedulers -----------------------------------------------------------------------------------

schedulers = APIRouter(prefix="/api/v1/schedulers", tags=["Schedulers"])


class SchedulerCreate(BaseModel):
    name: str = Field(..., max_length=100, description="What the runner's --scheduler calls it, e.g. RMJ_PROD")
    technology: str = Field("OTHER", description=", ".join(Scheduler.TECHNOLOGIES))
    api_url: Optional[str] = Field(None, max_length=512, description="Where AutoApp reaches it")
    description: Optional[str] = None
    active: bool = True
    variables: Optional[List[VariableSave]] = None
    tags: Optional[List[str]] = Field(None, description="Paths of the tags it carries")


class SchedulerOut(BaseModel):
    name: str
    technology: str
    api_url: Optional[str] = None
    description: Optional[str] = None


@schedulers.post("", response_model=SchedulerOut, status_code=status.HTTP_201_CREATED)
def create_scheduler(payload: SchedulerCreate, db: Session = Depends(get_db)):
    """Registers a scheduler: a workload automation product that runs AutoApp jobs."""
    name = clean_name("scheduler", payload.name, Scheduler, db)
    technology = next((t for t in Scheduler.TECHNOLOGIES if t.lower() == (payload.technology or "").strip().lower()), None)
    if technology is None:
        raise HTTPException(422, f"The technology must be one of {', '.join(Scheduler.TECHNOLOGIES)}, "
                                 f"not '{payload.technology}'.")
    scheduler = Scheduler(Name=name, Technology=technology, ApiUrl=(payload.api_url or "").strip() or None,
                          Description=(payload.description or "").strip() or None, IsActive=payload.active,
                          CreatedBy=EDITOR_NAME)
    record(db, scheduler, "scheduler", name, payload.variables, payload.tags)
    return SchedulerOut(name=scheduler.Name, technology=scheduler.Technology, api_url=scheduler.ApiUrl,
                        description=scheduler.Description)


# --- Tags -----------------------------------------------------------------------------------------

tags = APIRouter(prefix="/api/v1/tags", tags=["Tags"])


class TagCreate(BaseModel):
    name: str = Field(..., max_length=100)
    parent: Optional[str] = Field(None, description="Path of the tag it sits under, e.g. Finance")
    description: Optional[str] = None
    variables: Optional[List[VariableSave]] = None


class TagOut(BaseModel):
    name: str
    path: str = Field(..., description="How the tag is named elsewhere: its parents' names and its own, e.g. Finance/Reporting")
    parent: Optional[str] = None
    description: Optional[str] = None


@tags.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(payload: TagCreate, db: Session = Depends(get_db)):
    """Registers a tag: a label anything can carry, whose variables it then has."""
    try:
        parent_path = tag_store.normal_path(payload.parent or "")
        parent = tag_store.find(db, parent_path) if parent_path else None
        name = tag_store.check_name(db, None, payload.name, parent)
    except JobStoreError as e:
        raise HTTPException(e.status, str(e))
    tag = Tag(Name=name, Parent_MasterObject_id=parent.MasterObject_id if parent else None,
              Description=(payload.description or "").strip() or None, CreatedBy=EDITOR_NAME)
    db.add(tag)
    tag.parent = parent         # so its path is known before it is saved
    record(db, tag, "tag", tag_path(tag), payload.variables)
    return TagOut(name=tag.Name, path=tag_path(tag), parent=tag_path(parent) if parent else None,
                  description=tag.Description)


class TagVariable(BaseModel):
    name: str
    value: Optional[str] = Field(None, description="******** for a secret")
    secret: bool
    source: str = Field(..., description="Path of the tag that defines it: one of those asked about, or a parent")
    description: Optional[str] = None
    overridden: bool = Field(False, description="The object's own variable of this name wins over it")


class TagConflict(BaseModel):
    name: str
    tags: List[str]
    message: str


class TagVariables(BaseModel):
    variables: List[TagVariable]
    conflicts: List[TagConflict]


tag_variables = APIRouter(prefix="/api/v1/tag-variables", tags=["Tags"])


@tag_variables.get("", response_model=TagVariables)
def get_tag_variables(tag: List[str] = Query(..., description="A tag's path; give it once for each tag"),
                      own: List[str] = Query([], description="Names of the object's own variables, which win"),
                      db: Session = Depends(get_db)):
    """
    What a set of tags gives together: each variable and the tag it comes from,
    and the variables they disagree about. A page asks this before a tag is added,
    with the tags already there and the one being considered. Secrets are masked.
    """
    try:
        return tag_store.variables_view(db, tag, own)
    except JobStoreError as e:
        raise HTTPException(e.status, str(e))

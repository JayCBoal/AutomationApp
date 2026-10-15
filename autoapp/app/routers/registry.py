"""
Registering the things endpoints belong to: applications, entities and sites.

Each has a create route, used by the "New..." links in the web interface, which
let something be registered at the moment it is first needed. Their search and
detail pages, and changing or removing them, come later.
"""
import json
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.job_store import JobStoreError, apply_variables
from app.models import Application, Audit, Entity, Site
from app.schemas import VariableSave

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


def record(db: Session, obj, kind: str, name: str, variables: Optional[List[VariableSave]] = None) -> None:
    db.add(obj)
    db.flush()
    if variables:
        try:
            apply_variables(obj, variables, creating=True)
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
    record(db, application, "application", name, payload.variables)
    return ApplicationOut(name=application.Name, abbr=application.Abbr, description=application.Description)


# --- Entities -------------------------------------------------------------------------------------

entities = APIRouter(prefix="/api/v1/entities", tags=["Entities"])


class EntityCreate(BaseModel):
    name: str = Field(..., max_length=64)
    abbr: str = Field(..., max_length=10)
    description: Optional[str] = Field(None, max_length=256)
    active: bool = True
    variables: Optional[List[VariableSave]] = None


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
    record(db, entity, "entity", name, payload.variables)
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
    record(db, site, "site", name, payload.variables)
    return SiteOut(name=site.Name, entity=entity.Name if entity else None, host=site.Host, port=site.Port,
                   protocol=site.Protocol, description=site.Description)

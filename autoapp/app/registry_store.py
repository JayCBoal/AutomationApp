"""
Searching, viewing, changing and removing applications, entities, sites and endpoints.

The four work the same way, so they share one implementation, driven by a short
description of each kind: its fields, which of them name another kind, and
whether it can hold variables. The routes are in app/routers/definitions.py;
registering a new one is in app/routers/registry.py and app/routers/endpoints.py.

Rules:
  - A name can be changed. An endpoint is referred to by name from job steps, so
    renaming one updates those steps too.
  - Something still in use cannot be deleted: an application or site that an
    endpoint belongs to, an entity that owns a site, an endpoint that a job step names.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.job_store import JobStoreError, apply_variables
from app.models import Application, Audit, Endpoint, Entity, JobStep, JobStepParameter, Site, utcnow
from engine.step_catalog import ENDPOINT_SUFFIX

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
MAX_RESULTS = 500


@dataclass
class Field:
    name: str                       # as the API calls it
    column: Optional[str] = None    # the model attribute holding it, for a plain value
    refers_to: Optional[str] = None  # for a field that names another kind: that kind's key
    ref_column: Optional[str] = None  # ... and the foreign key attribute that holds the link
    required: bool = False
    kind: str = "text"              # text, int or bool
    derived: bool = False           # shown, but not set directly (an endpoint's entity comes from its site)


@dataclass
class Kind:
    key: str                        # "endpoints"
    singular: str                   # "endpoint"
    model: Any
    fields: List[Field]
    variables: bool = False
    audit_prefix: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def article(self) -> str:
        return "An" if self.singular[0] in "aeiou" else "A"


KINDS: Dict[str, Kind] = {
    "applications": Kind("applications", "application", Application, [
        Field("name", "Name", required=True),
        Field("abbr", "Abbr", required=True),
        Field("description", "Description"),
        Field("active", "IsActive", kind="bool"),
    ], variables=True),
    "entities": Kind("entities", "entity", Entity, [
        Field("name", "Name", required=True),
        Field("abbr", "Abbr", required=True),
        Field("description", "Description"),
        Field("active", "IsActive", kind="bool"),
    ], variables=True),
    "sites": Kind("sites", "site", Site, [
        Field("name", "Name", required=True),
        Field("entity", refers_to="entities", ref_column="Entity_MasterObject_id"),
        Field("host", "Host", required=True),
        Field("port", "Port", required=True, kind="int"),
        Field("protocol", "Protocol", required=True),
        Field("description", "Description"),
        Field("active", "IsActive", kind="bool"),
    ], variables=True),
    "endpoints": Kind("endpoints", "endpoint", Endpoint, [
        Field("name", "Name", required=True),
        Field("application", refers_to="applications", ref_column="Application_MasterObject_id"),
        Field("site", refers_to="sites", ref_column="Site_MasterObject_id"),
        Field("entity", derived=True),
        Field("path", "Path", required=True),
        Field("filename_pattern", "FilenamePattern", required=True),
        Field("description", "Description"),
    ]),
}


def kind_of(key: str) -> Kind:
    if key not in KINDS:
        raise JobStoreError(f"There is no kind of definition called '{key}'.", status=404)
    return KINDS[key]


def _key_of(obj):
    """The value a foreign key holds for this object."""
    return getattr(obj, "MasterObject_id", None) or getattr(obj, "id")


def _ref(db: Session, kind_key: str, name: str):
    kind = KINDS[kind_key]
    return db.query(kind.model).filter(kind.model.Name == name).first()


def describe(kind: Kind, obj, db: Optional[Session] = None) -> Dict[str, Any]:
    """An object as the API returns it. With a session, also its variables and what uses it."""
    out: Dict[str, Any] = {}
    for f in kind.fields:
        if f.derived:
            site = getattr(obj, "site", None)
            out[f.name] = site.entity.Name if site is not None and site.entity is not None else None
        elif f.refers_to:
            linked_id = getattr(obj, f.ref_column)
            linked = db.get(KINDS[f.refers_to].model, linked_id) if (db is not None and linked_id) else None
            if linked is None and linked_id:
                linked = getattr(obj, f.name, None)
            out[f.name] = linked.Name if linked is not None else None
        else:
            value = getattr(obj, f.column)
            out[f.name] = bool(value) if f.kind == "bool" else value
    out["modified"] = getattr(obj, "ModifiedDateTime", None) or getattr(obj, "CreatedDateTime", None)
    out["modified_by"] = getattr(obj, "ModifiedBy", None) or getattr(obj, "CreatedBy", None)
    if db is not None:
        if kind.variables:
            out["variables"] = [
                {"name": v.VarName, "value": None if v.IsSecret else v.VarValue, "secret": bool(v.IsSecret),
                 "description": v.Description}
                for v in sorted(obj.variables, key=lambda v: (v.VarName.lower(), v.VarName))
            ]
        out["used_by"] = used_by(db, kind, obj)
    return out


def used_by(db: Session, kind: Kind, obj) -> List[Dict[str, str]]:
    """What refers to this object: [{"kind": "endpoints", "name": "LEGAL_EXTRACTS"}, ...], in name order."""
    if kind.key == "endpoints":
        rows = (
            db.query(JobStep.job_id).join(JobStepParameter, JobStepParameter.job_step_id == JobStep.id)
            .filter(JobStepParameter.ParamName.like(f"%{ENDPOINT_SUFFIX}"), JobStepParameter.ParamValue == obj.Name)
            .distinct().all()
        )
        from app.models import Job
        keys = sorted({db.get(Job, job_id).JobKey for (job_id,) in rows}, key=str.lower)
        return [{"kind": "jobs", "name": key} for key in keys]
    if kind.key in ("applications", "sites"):
        column = Endpoint.Application_MasterObject_id if kind.key == "applications" else Endpoint.Site_MasterObject_id
        names = [e.Name for e in db.query(Endpoint).filter(column == obj.MasterObject_id)]
        return [{"kind": "endpoints", "name": n} for n in sorted(names, key=str.lower)]
    if kind.key == "entities":
        names = [s.Name for s in db.query(Site).filter(Site.Entity_MasterObject_id == obj.MasterObject_id)]
        return [{"kind": "sites", "name": n} for n in sorted(names, key=str.lower)]
    return []


def find(db: Session, kind: Kind, name: str):
    obj = db.query(kind.model).filter(kind.model.Name == name).first()
    if obj is None:
        raise JobStoreError(f"No {kind.singular} named '{name}' exists.", status=404)
    return obj


def search(db: Session, kind: Kind, criteria: Dict[str, str], limit: int = MAX_RESULTS) -> List[Dict[str, Any]]:
    """Text criteria ignore case and match anywhere; 'active' is true or false."""
    model = kind.model
    query = db.query(model)
    for f in kind.fields:
        value = (criteria.get(f.name) or "").strip()
        if not value:
            continue
        if f.kind == "bool":
            query = query.filter(getattr(model, f.column).is_(value.lower() in ("true", "1", "yes")))
        elif f.derived:                                   # an endpoint's entity, through its site
            site_table, entity_table = Site.__table__.alias(), Entity.__table__.alias()
            query = query.join(site_table, site_table.c.MasterObject_id == model.Site_MasterObject_id) \
                .join(entity_table, entity_table.c.MasterObject_id == site_table.c.Entity_MasterObject_id) \
                .filter(entity_table.c.Name.ilike(f"%{value}%"))
        elif f.refers_to:
            target = KINDS[f.refers_to].model.__table__.alias()
            query = query.join(target, target.c.MasterObject_id == getattr(model, f.ref_column)) \
                .filter(target.c.Name.ilike(f"%{value}%"))
        elif f.kind == "int":
            query = query.filter(getattr(model, f.column) == int(value)) if value.isdigit() else query.filter(False)
        else:
            query = query.filter(getattr(model, f.column).ilike(f"%{value}%"))
    rows = query.order_by(func.lower(model.Name), model.Name).limit(max(1, min(limit, MAX_RESULTS))).all()
    return [describe(kind, obj, None) | {"used_by_count": len(used_by(db, kind, obj))} for obj in rows]


def _audit(db: Session, kind: Kind, obj, action: str, who: str, name: str, changes: List[str]) -> None:
    db.add(Audit(MasterObject_id=getattr(obj, "MasterObject_id", None) if obj is not None else None,
                 Action=f"{kind.singular.upper()}_{action}", PerformedBy=who,
                 Details=json.dumps({kind.singular: name, "changes": changes})))


def update(db: Session, kind: Kind, name: str, payload: Dict[str, Any], who: str):
    """Changes an object: its fields, its name and its variables. Returns (object, changes)."""
    obj = find(db, kind, name)
    changes: List[str] = []
    old_name = obj.Name

    for f in kind.fields:
        if f.derived or f.name not in payload:
            continue
        value = payload[f.name]
        if f.kind == "bool":
            new = bool(value)
            if new != bool(getattr(obj, f.column)):
                setattr(obj, f.column, new)
                changes.append(("Activated" if new else "Deactivated") + f" the {kind.singular}.")
            continue
        text = "" if value is None else str(value).strip()
        if f.required and not text:
            raise JobStoreError(f"{kind.article()} {kind.singular} needs {'a' if f.name[0] not in 'aeiou' else 'an'} "
                                f"{f.name.replace('_', ' ')}.")
        if f.refers_to:
            target = _ref(db, f.refers_to, text) if text else None
            if text and target is None:
                raise JobStoreError(f"There is no {KINDS[f.refers_to].singular} named '{text}'.")
            new_id = _key_of(target) if target is not None else None
            if new_id != getattr(obj, f.ref_column):
                setattr(obj, f.ref_column, new_id)
                changes.append(f"Changed the {f.name}.")
            continue
        if f.kind == "int":
            try:
                number = int(text)
            except ValueError:
                raise JobStoreError(f"The {f.name} must be a whole number, not '{text}'.")
            if not 1 <= number <= 65535:
                raise JobStoreError(f"The {f.name} must be between 1 and 65535.")
            if number != getattr(obj, f.column):
                setattr(obj, f.column, number)
                changes.append(f"Changed the {f.name}.")
            continue
        if f.name == "name" and text != obj.Name:
            if not NAME_PATTERN.match(text):
                raise JobStoreError(f"Invalid {kind.singular} name '{text}': use letters, digits, '-', '_' and '.', "
                                    f"starting with a letter or digit.")
            if db.query(kind.model).filter(kind.model.Name == text).first():
                raise JobStoreError(f"{kind.article()} {kind.singular} named '{text}' is already registered.", status=409)
            changes.append(f"Renamed from '{obj.Name}' to '{text}'.")
            obj.Name = text
            continue
        if f.name == "abbr" and kind.key == "applications" and text != obj.Abbr:
            if db.query(Application).filter(Application.Abbr == text).first():
                raise JobStoreError(f"The abbreviation '{text}' is already used by another application.", status=409)
        stored = text or None
        if f.name == "protocol":
            stored = text.upper()
        if stored != getattr(obj, f.column):
            setattr(obj, f.column, stored)
            changes.append(f"Changed the {f.name.replace('_', ' ')}.")

    # A job step names an endpoint, so a renamed endpoint takes its steps with it
    if kind.key == "endpoints" and obj.Name != old_name:
        steps = (
            db.query(JobStepParameter)
            .filter(JobStepParameter.ParamName.like(f"%{ENDPOINT_SUFFIX}"), JobStepParameter.ParamValue == old_name).all()
        )
        for parameter in steps:
            parameter.ParamValue = obj.Name
        if steps:
            changes.append(f"Updated {len(steps)} job step{'' if len(steps) == 1 else 's'} that named it.")

    if kind.variables and payload.get("variables") is not None:
        from app.schemas import VariableSave
        changes += apply_variables(obj, [VariableSave(**v) for v in payload["variables"]], creating=False)

    if changes:
        if hasattr(obj, "ModifiedDateTime"):
            obj.ModifiedDateTime = utcnow()
            obj.ModifiedBy = who
        _audit(db, kind, obj, "UPDATED", who, obj.Name, changes)
    db.commit()
    db.refresh(obj)
    return obj, changes


def delete(db: Session, kind: Kind, name: str, who: str) -> None:
    obj = find(db, kind, name)
    users = used_by(db, kind, obj)
    if users:
        listed = ", ".join(u["name"] for u in users[:5]) + (" and others" if len(users) > 5 else "")
        what = {"jobs": "job", "endpoints": "endpoint", "sites": "site"}[users[0]["kind"]]
        raise JobStoreError(
            f"{kind.singular.capitalize()} '{name}' cannot be deleted while {len(users)} "
            f"{what}{'' if len(users) == 1 else 's'} use{'s' if len(users) == 1 else ''} it: {listed}. "
            f"Change {'it' if len(users) == 1 else 'them'} first.", status=409)
    _audit(db, kind, None, "DELETED", who, name, [f"Deleted {kind.singular} '{name}'."])
    db.delete(obj)
    db.commit()

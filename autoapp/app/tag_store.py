"""
Tags on the things that carry them, and the rules for changing tags.

Any master object can carry tags (a tag's place in the hierarchy is its parent,
so a tag does not carry tags itself). The rules are in docs/TO-DO.md, decision 3:
  - A tag is named by its path, "Finance/Reporting"; names are unique under one parent.
  - A tag cannot be its own ancestor.
  - A tag with child tags, or that something carries, cannot be deleted.
  - Renaming or moving a tag updates the ${TAG:path.Var} references to it.
"""
from typing import Dict, Iterable, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.job_store import JobStoreError
from app.models import Job, JobStepParameter, MasterObject, Tag, TagAssignment, Variable
from engine import tag_vars
from engine.tag_vars import SEPARATOR, tag_path

MASK = "********"

# The API's name for each kind of master object, and how to name one
KIND_OF_TYPE = {"APPLICATION": "applications", "ENTITY": "entities", "SITE": "sites", "ENDPOINT": "endpoints",
                "JOB": "jobs", "TAG": "tags"}


class TagError(JobStoreError):
    """A tag change that cannot be made. status is the HTTP status to answer with."""


def normal_path(text: str) -> str:
    """'Finance / Reporting' and 'Finance/Reporting' are the same path."""
    return SEPARATOR.join(part.strip() for part in (text or "").split(SEPARATOR) if part.strip())


def name_of(obj) -> str:
    if isinstance(obj, Tag):
        return tag_path(obj)
    return getattr(obj, "JobKey", None) or getattr(obj, "Name", None) or str(obj.id)


def paths_on(obj) -> List[str]:
    """The paths of the tags an object carries, in order."""
    return sorted((tag_path(a.tag) for a in obj.tag_assignments), key=lambda p: (p.lower(), p))


def find(db: Session, path: str) -> Tag:
    tag = tag_vars.find_by_path(db, normal_path(path))
    if tag is None:
        raise TagError(f"There is no tag '{tag_vars.shown(normal_path(path))}'.", status=404)
    return tag


def descendants(tag) -> List[Tag]:
    """Every tag under this one, at any depth."""
    found, waiting = [], list(tag.children)
    while waiting:
        child = waiting.pop()
        if child in found:
            continue
        found.append(child)
        waiting.extend(child.children)
    return found


def matching_ids(db: Session, text: str) -> List[int]:
    """
    For a search's Tag box: the tags whose path contains the text (any case), and
    every tag under them, so that searching for a parent finds what carries its children.
    """
    wanted = normal_path(text).lower()
    found = set()
    for tag in db.query(Tag).all():
        if wanted in tag_path(tag).lower():
            found.add(tag.MasterObject_id)
            found.update(t.MasterObject_id for t in descendants(tag))
    return sorted(found)


def carrying(db: Session, text: str):
    """A filter for a query of master objects: those carrying a tag the text matches, or one under it."""
    ids = matching_ids(db, text)
    return MasterObject.id.in_(
        db.query(TagAssignment.Target_MasterObject_id).filter(TagAssignment.Tag_MasterObject_id.in_(ids or [-1])))


def apply_tags(db: Session, obj, submitted: Optional[Iterable[str]]) -> List[str]:
    """
    Makes the tags an object carries match the paths submitted (None leaves them as
    they are). Returns what changed, in words.
    """
    if submitted is None:
        return []
    if isinstance(obj, Tag):
        raise TagError("A tag does not carry tags. Give it a parent instead.")
    wanted: Dict[str, Tag] = {}
    for text in submitted:
        path = normal_path(text)
        if not path:
            continue
        wanted[tag_path(find(db, path))] = find(db, path)
    have = {tag_path(a.tag): a for a in obj.tag_assignments}
    added = sorted(set(wanted) - set(have), key=str.lower)
    removed = sorted(set(have) - set(wanted), key=str.lower)
    for path in added:
        obj.tag_assignments.append(TagAssignment(Tag_MasterObject_id=wanted[path].MasterObject_id))
    for path in removed:
        obj.tag_assignments.remove(have[path])
    changes = []
    if added:
        changes.append(f"Added tag{'' if len(added) == 1 else 's'} {', '.join(tag_vars.shown(p) for p in added)}.")
    if removed:
        changes.append(f"Removed tag{'' if len(removed) == 1 else 's'} {', '.join(tag_vars.shown(p) for p in removed)}.")
    return changes


def check_name(db: Session, tag: Optional[Tag], name: str, parent: Optional[Tag]) -> str:
    """A usable name, free under this parent. Raises TagError otherwise."""
    name = (name or "").strip()
    if not Tag.NAME_PATTERN.match(name):
        raise TagError(f"Invalid tag name '{name}': use letters, digits, '-' and '_', starting with a letter or digit. "
                       f"A tag is named in a value as ${{TAG:Parent/Child.Variable}}, so '/' and '.' cannot be used.")
    parent_id = parent.MasterObject_id if parent else None
    query = db.query(Tag).filter(Tag.Name == name)
    query = query.filter(Tag.Parent_MasterObject_id.is_(None)) if parent_id is None \
        else query.filter(Tag.Parent_MasterObject_id == parent_id)
    clash = query.first()
    if clash is not None and (tag is None or clash.MasterObject_id != tag.MasterObject_id):
        where = f"under {tag_vars.shown(tag_path(parent))}" if parent else "at the top level"
        raise TagError(f"There is already a tag '{name}' {where}.", status=409)
    return name


def check_parent(tag: Tag, parent: Optional[Tag]) -> None:
    """A tag cannot sit under itself or under a tag that is under it."""
    if parent is None:
        return
    if parent.MasterObject_id == tag.MasterObject_id or parent in descendants(tag):
        raise TagError(f"'{tag_vars.shown(tag_path(parent))}' is {'this tag' if parent is tag else 'under this tag'}, "
                       f"so it cannot be its parent.")


def rename_references(db: Session, old_path: str, new_path: str) -> int:
    """
    After a tag is renamed or moved: rewrites ${TAG:old...} in job step values and
    variable values, for the tag and everything under it. Returns how many values changed.
    """
    if old_path == new_path:
        return 0
    prefixes = [("${TAG:" + old_path + ".", "${TAG:" + new_path + "."),
                ("${TAG:" + old_path + SEPARATOR, "${TAG:" + new_path + SEPARATOR)]
    changed = 0
    for model, column in ((JobStepParameter, "ParamValue"), (Variable, "VarValue")):
        rows = db.query(model).filter(or_(*[getattr(model, column).contains(old) for old, _ in prefixes])).all()
        for row in rows:
            value = getattr(row, column)
            for old, new in prefixes:
                value = value.replace(old, new)
            if value != getattr(row, column):
                setattr(row, column, value)
                changed += 1
    return changed


def carriers(db: Session, tag: Tag) -> List[Dict[str, str]]:
    """What carries a tag: [{"kind": "jobs", "name": "DEV-LOAD"}, ...], by kind and name."""
    rows = (db.query(MasterObject).join(TagAssignment, TagAssignment.Target_MasterObject_id == MasterObject.id)
            .filter(TagAssignment.Tag_MasterObject_id == tag.MasterObject_id).all())
    found = [{"kind": KIND_OF_TYPE.get(obj.ObjectType, obj.ObjectType.lower()), "name": name_of(obj)} for obj in rows]
    return sorted(found, key=lambda u: (u["kind"], u["name"].lower()))


def variables_view(db: Session, paths: Iterable[str], own: Iterable[str] = ()) -> Dict:
    """
    What a set of tags gives, for a page to show before a tag is added: each variable
    with where it comes from (secrets masked), and the variables the tags disagree
    about that the object's own variables (own) do not settle.
    """
    tags = [find(db, path) for path in dict.fromkeys(normal_path(p) for p in paths if normal_path(p))]
    combined = tag_vars.combine(tags)
    own = set(own)
    return {
        "variables": [
            {"name": name, "value": MASK if given.secret else given.value, "secret": given.secret,
             "source": given.source, "description": given.description, "overridden": name in own}
            for name, given in sorted(combined.values.items(), key=lambda item: (item[0].lower(), item[0]))
        ],
        "conflicts": [
            {"name": name, "tags": [attached for _, attached in c.sources], "message": c.message()}
            for name, c in sorted(combined.conflicts.items()) if name not in own
        ],
    }


def inherited_by_tag(tag: Tag) -> List[Dict]:
    """The variables a tag inherits from its ancestors and does not override, for its detail page."""
    path = tag_path(tag)
    return [
        {"name": name, "value": MASK if given.secret else given.value, "secret": given.secret,
         "source": given.source, "description": given.description}
        for name, given in sorted(tag_vars.variables_of(tag).items(), key=lambda item: (item[0].lower(), item[0]))
        if given.source != path
    ]


def job_tag_warnings(db: Session, job: Job) -> List[str]:
    """Conflicts among a job's tags that the job does not use (a used one is a problem, reported elsewhere)."""
    combined = tag_vars.inherited(db, job.MasterObject_id)
    own = {v.VarName for v in job.variables}
    return [c.message() for name, c in sorted(combined.conflicts.items()) if name not in own]

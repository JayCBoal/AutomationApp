"""
The variables an object gets from its tags.

A tag's variables act as if they were on the object it is attached to, just
below that object's own. A tag inherits its ancestors' variables, and its own
override theirs. When two of an object's tags give one variable different
values, that variable is in conflict: nothing is chosen, and using it is an
error (see ScopeResolutionEngine). The same value from two tags is not a
conflict, nor is one ancestor reached through two tags.

A tag is named by its path from the top: "Finance/Reporting". Pages show it
as "Finance / Reporting".
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

SEPARATOR = "/"


def tag_path(tag) -> str:
    """The tag's path from the top, e.g. 'Finance/Reporting'."""
    return SEPARATOR.join(t.Name for t in chain(tag))


def shown(path: str) -> str:
    return path.replace(SEPARATOR, f" {SEPARATOR} ")


def chain(tag) -> List:
    """The tag and its ancestors, from the top down. Stops at a loop rather than going round it."""
    found, seen, current = [], set(), tag
    while current is not None and current.MasterObject_id not in seen:
        seen.add(current.MasterObject_id)
        found.append(current)
        current = current.parent
    return list(reversed(found))


def find_by_path(db: Session, path: str):
    """The tag a path names, or None."""
    from core.models import Tag
    parent_id, tag = None, None
    for name in [part.strip() for part in path.split(SEPARATOR)]:
        query = db.query(Tag).filter(Tag.Name == name)
        query = (query.filter(Tag.Parent_MasterObject_id.is_(None)) if parent_id is None
                 else query.filter(Tag.Parent_MasterObject_id == parent_id))
        tag = query.first()
        if tag is None:
            return None
        parent_id = tag.MasterObject_id
    return tag


@dataclass
class Given:
    """One variable as a tag gives it."""
    value: Optional[str]
    secret: bool
    source: str             # the path of the tag that defines it: the tag itself or an ancestor
    description: Optional[str] = None


def variables_of(tag) -> Dict[str, Given]:
    """A tag's variables, with those it inherits; its own override its ancestors'."""
    merged: Dict[str, Given] = {}
    for t in chain(tag):
        path = tag_path(t)
        for v in t.variables:
            merged[v.VarName] = Given(v.VarValue, bool(v.IsSecret), path, v.Description)
    return merged


@dataclass
class Conflict:
    name: str
    sources: List[Tuple[str, str]]       # (path of the tag that defines it, path of the tag attached), one per value

    def message(self, advice: str = "Give it a value of its own here, or remove one of the tags.") -> str:
        tags = " and ".join(shown(attached) + ("" if source == attached else f" (from {shown(source)})")
                            for source, attached in self.sources)
        return f"Variable '{self.name}' is given different values by tags {tags}. {advice}"


@dataclass
class Inherited:
    """What an object gets from all its tags together."""
    values: Dict[str, Given] = field(default_factory=dict)
    conflicts: Dict[str, Conflict] = field(default_factory=dict)
    tags: List = field(default_factory=list)               # the tags attached, by path

    def plain(self) -> Dict[str, Optional[str]]:
        return {name: given.value for name, given in self.values.items()}


def tags_on(db: Session, master_object_id: Optional[int]) -> List:
    """The tags attached to an object, in path order."""
    from core.models import Tag, TagAssignment
    if not master_object_id:
        return []
    tags = (db.query(Tag).join(TagAssignment, TagAssignment.Tag_MasterObject_id == Tag.MasterObject_id)
            .filter(TagAssignment.Target_MasterObject_id == master_object_id).all())
    return sorted(tags, key=lambda t: (tag_path(t).lower(), tag_path(t)))


def combine(tags: List) -> Inherited:
    """The variables a set of tags gives together, and the ones they disagree on."""
    result = Inherited(tags=list(tags))
    offered: Dict[str, Dict[Optional[str], List[Tuple[str, str, Given]]]] = {}
    for tag in tags:
        attached = tag_path(tag)
        for name, given in variables_of(tag).items():
            offered.setdefault(name, {}).setdefault(given.value, []).append((given.source, attached, given))
    for name, by_value in offered.items():
        if len(by_value) == 1:
            [(_, _, given)] = list(by_value.values())[0][:1]
            result.values[name] = given
        else:
            result.conflicts[name] = Conflict(name, [(source, attached) for givers in by_value.values()
                                                     for source, attached, _ in givers[:1]])
    return result


def inherited(db: Session, master_object_id: Optional[int]) -> Inherited:
    return combine(tags_on(db, master_object_id))


def reachable(tags: List) -> Dict[str, object]:
    """Every tag a ${TAG:path.Var} may name: the tags attached and their ancestors, by path."""
    found = {}
    for tag in tags:
        for t in chain(tag):
            found[tag_path(t)] = t
    return found

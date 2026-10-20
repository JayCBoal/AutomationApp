"""
System-wide settings.

Each setting is declared here once: its name, what kind of value it takes, its
default and what it means. The Settings table holds only the values someone has
changed from the default, so a new setting needs no change to the database, and
a setting with no row has its default.

Settings are not variables: nothing reads them through ${...}.

    current(db, "VariablePrecedence")   ->  ["ENV", "SYS", "ENTITY", "APP", "ENDPOINT", "TAG", "WORKFLOW", "JOB", "USE"]

An order is stored, and given by the API, lowest priority first: the order the
levels are merged in. The Settings page shows it the other way round.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

ORDER = "ORDER"         # every one of the choices, each once, in an order of the user's choosing
CHOICE = "CHOICE"       # one of the choices


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str
    default: str
    title: str
    description: str
    choices: Tuple[str, ...] = ()
    labels: Tuple[Tuple[str, str], ...] = ()     # what each choice means, for the Settings page


SETTINGS: Dict[str, Setting] = {s.key: s for s in [
    Setting(
        "VariablePrecedence", ORDER,
        default="ENV,SYS,ENTITY,APP,ENDPOINT,TAG,WORKFLOW,JOB,USE",
        title="Variable precedence",
        description="Where a ${Name} is looked for. When two of these define the same variable, the one with "
                    "the higher priority wins. The tags on an application, entity, endpoint or workflow always "
                    "count just below that object's own variables. Workflow and This use apply only to a job "
                    "run in a workflow.",
        choices=("ENV", "SYS", "ENTITY", "APP", "ENDPOINT", "TAG", "WORKFLOW", "JOB", "USE"),
        labels=(("ENV", "The environment the runner starts in, where a scheduler puts the job's own variables"),
                ("SYS", "System values"), ("ENTITY", "The endpoint's entity"),
                ("APP", "The endpoint's application"), ("ENDPOINT", "The endpoint's tags"),
                ("TAG", "The job's tags"),
                ("WORKFLOW", "The workflow the job runs in: its own variables, then its tags'"),
                ("JOB", "The job's own variables"),
                ("USE", "This use of the job in a workflow: the variables set on it there")),
    ),
    Setting(
        "LogRetentionDays", CHOICE,
        default="30",
        title="Keep job logs for",
        description="How long a run's job log is kept, in days after the run ended. Each log is a file on the "
                    "host that ran the job; older ones are removed from there once a day, and the run's log "
                    "page then says when. The run's record and its operations are kept whatever this says.",
        choices=("7", "14", "30", "90", "365", "FOREVER"),
        labels=(("7", "A week"), ("14", "Two weeks"), ("30", "30 days"), ("90", "90 days"), ("365", "A year"),
                ("FOREVER", "Never remove them")),
    ),
    Setting(
        "OutsideWaitHours", CHOICE,
        default="24",
        title="Default wait for outside prerequisites",
        description="How long a job in a workflow waits for a prerequisite outside its workflow (a job in another "
                    "workflow, files, a time) when the prerequisite sets no limit of its own, counted as the "
                    "prerequisite says: by default, from when the job's other prerequisites have held. When "
                    "it runs out, the job's choice decides: it does not run, or it fails.",
        choices=("1", "2", "4", "8", "12", "24", "48", "72", "168"),
        labels=(("1", "1 hour"), ("2", "2 hours"), ("4", "4 hours"), ("8", "8 hours"), ("12", "12 hours"),
                ("24", "24 hours"), ("48", "2 days"), ("72", "3 days"), ("168", "A week")),
    ),
]}


def setting(key: str) -> Setting:
    if key not in SETTINGS:
        raise KeyError(f"There is no setting called '{key}'.")
    return SETTINGS[key]


def parse(key: str, text: str) -> Any:
    """Turns stored or submitted text into the setting's value. Raises ValueError if it does not fit."""
    s = setting(key)
    if s.kind == ORDER:
        items = [item.strip().upper() for item in str(text).split(",") if item.strip()]
        missing = [c for c in s.choices if c not in items]
        unknown = [i for i in items if i not in s.choices]
        repeated = sorted({i for i in items if items.count(i) > 1})
        problems = []
        if unknown:
            problems.append(f"not one of the choices: {', '.join(unknown)}")
        if missing:
            problems.append(f"missing: {', '.join(missing)}")
        if repeated:
            problems.append(f"given more than once: {', '.join(repeated)}")
        if problems:
            raise ValueError(f"{s.title} must list each of {', '.join(s.choices)} once ({'; '.join(problems)}).")
        return items
    if s.kind == CHOICE:
        for choice in s.choices:
            if str(text).strip().lower() == choice.lower():
                return choice
        raise ValueError(f"{s.title} must be one of {', '.join(s.choices)}, not '{text}'.")
    return text


def stored_text(key: str, value: Any) -> str:
    """The text a setting's value is stored as."""
    return ",".join(value) if setting(key).kind == ORDER else str(value)


def stored(db: Session) -> Dict[str, str]:
    from app.models import SettingValue
    return {row.SettingKey: row.SettingValue for row in db.query(SettingValue)}


def current(db: Optional[Session], key: str) -> Any:
    """A setting's value: the one stored, or the default. A stored value that no longer fits gives the default."""
    s = setting(key)
    text = stored(db).get(key) if db is not None else None
    if text is not None:
        if s.kind == ORDER:
            text = ",".join(_with_new_choices(s, [item.strip().upper() for item in text.split(",") if item.strip()]))
        try:
            return parse(key, text)
        except ValueError:
            pass
    return parse(key, s.default)


def _with_new_choices(s: Setting, items: List[str]) -> List[str]:
    """
    An order saved before a choice existed keeps its order, and the new choice goes in just above
    the highest-ranked choice the default puts below it: WORKFLOW above TAG, USE above everything,
    and ENV, with nothing below it, at the lowest priority.
    """
    default = s.default.split(",")
    for choice in s.choices:
        if choice in items:
            continue
        below = [items.index(c) for c in default[:default.index(choice)] if c in items] if choice in default else []
        place = max(below) + 1 if below else 0
        items = items[:place] + [choice] + items[place:]
    return items


def describe_all(db: Session) -> List[Dict[str, Any]]:
    """Every setting with its current value, for the Settings page."""
    saved = stored(db)
    out = []
    for s in SETTINGS.values():
        out.append({
            "key": s.key, "kind": s.kind, "title": s.title, "description": s.description,
            "choices": list(s.choices), "labels": dict(s.labels),
            "default": parse(s.key, s.default), "value": current(db, s.key), "changed": s.key in saved,
        })
    return out

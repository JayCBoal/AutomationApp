"""
System-wide settings (declared in core/settings.py):

    GET  /api/v1/settings          every setting, with its value and default
    PUT  /api/v1/settings/{key}    change one; {"value": ...}. The default's value puts it back to the default

Every change is recorded in the audit log.
"""
import json
from typing import Any, Dict, List, Union

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from core.models import Audit, SettingValue, utcnow
from core import settings

router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])

EDITOR_NAME = "web interface"


@router.get("")
def list_settings(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return settings.describe_all(db)


@router.put("/{key}")
def change_setting(key: str, value: Union[str, List[str]] = Body(..., embed=True),
                   db: Session = Depends(get_db)) -> Dict[str, Any]:
    if key not in settings.SETTINGS:
        raise HTTPException(404, f"There is no setting called '{key}'.")
    declared = settings.setting(key)
    try:
        parsed = settings.parse(key, ",".join(value) if isinstance(value, list) else value)
    except ValueError as e:
        raise HTTPException(422, str(e))

    before = settings.current(db, key)
    row = db.get(SettingValue, key)
    if parsed == settings.parse(key, declared.default):
        if row is not None:
            db.delete(row)                  # back to the default, so a later change of default applies here too
    elif row is None:
        db.add(SettingValue(SettingKey=key, SettingValue=settings.stored_text(key, parsed), UpdatedBy=EDITOR_NAME))
    else:
        row.SettingValue, row.UpdatedDateTime, row.UpdatedBy = settings.stored_text(key, parsed), utcnow(), EDITOR_NAME

    changes = []
    if parsed != before:
        changes = [f"Changed {declared.title} from {settings.stored_text(key, before)} "
                   f"to {settings.stored_text(key, parsed)}."]
        db.add(Audit(MasterObject_id=None, Action="SETTING_CHANGED", PerformedBy=EDITOR_NAME,
                     Details=json.dumps({"setting": key, "changes": changes})))
    db.commit()
    return {"setting": next(s for s in settings.describe_all(db) if s["key"] == key), "changes": changes}

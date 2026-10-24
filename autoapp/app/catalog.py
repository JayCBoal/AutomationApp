#!/usr/bin/env python3
"""
The step catalog: which step types exist and what parameters each takes.

The handlers in engine/handlers are the source of this information. This
module copies it into the StepTypes and StepDefinitions tables, where the job
editor and anything else that reads the API can get at it.

It runs each time the API server starts, and can be run by hand:

    python3 -m app.catalog
"""
import json
from typing import Dict

from sqlalchemy.orm import Session

from core.models import StepDefinition, StepType
from core.handlers import HANDLERS


def sync_catalog(db: Session) -> Dict[str, int]:
    """
    Makes the catalog tables match the handlers: adds and updates step types and
    their parameter definitions, and removes definitions a handler no longer
    declares. A step type in the table with no handler is left alone.
    """
    counts = {"step_types": 0, "parameters": 0}
    for handler in HANDLERS:
        step_type = db.query(StepType).filter(StepType.HandlerClass == handler.CODE).first()
        if not step_type:
            step_type = StepType(HandlerClass=handler.CODE)
            db.add(step_type)
        step_type.TypeName = handler.NAME
        step_type.Description = handler.DESCRIPTION
        db.flush()
        counts["step_types"] += 1

        existing = {d.ParamName: d for d in db.query(StepDefinition).filter(StepDefinition.StepType_id == step_type.id)}
        for order, param in enumerate(handler.parameters(), start=1):
            definition = existing.pop(param.name, None)
            if not definition:
                definition = StepDefinition(StepType_id=step_type.id, ParamName=param.name)
                db.add(definition)
            definition.DataType = param.data_type
            definition.IsRequired = param.required
            definition.DefaultValue = param.default
            definition.Description = param.description
            definition.DisplayOrder = order
            definition.LocationRole = param.location_role
            definition.AllowedValues = json.dumps(list(param.choices)) if param.choices else None
            counts["parameters"] += 1
        for removed in existing.values():
            db.delete(removed)

    db.commit()
    return counts


def main():
    from core.database import DATABASE_URL, SessionLocal

    db = SessionLocal()
    try:
        counts = sync_catalog(db)
    finally:
        db.close()
    print(f"Step catalog in {DATABASE_URL}: {counts['step_types']} step type(s), {counts['parameters']} parameter(s).")


if __name__ == "__main__":
    main()

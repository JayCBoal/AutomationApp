#!/usr/bin/env python3
"""
Regenerates docs/DB_SCHEMA.md and docs/PYTHON_MODEL.md from autoapp/app/models.py.

    python3 docs/generate_diagrams.py

Run it after changing the models. The diagrams are Mermaid; GitHub renders
them in the browser, and VS Code does with a Mermaid preview extension.
"""
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DOCS_DIR.parent / "autoapp"))

from sqlalchemy import inspect
from sqlalchemy.orm import RelationshipDirection

from app.models import Base, MasterObject

# How the tables are grouped into detail diagrams
TABLE_GROUPS = {
    "Domain registry": ["MasterObjects", "Applications", "Entities", "Sites", "Credentials", "Tags",
                        "Variables", "TagAssignments"],
    "Jobs and steps": ["Jobs", "JobSteps", "JobStepParameters", "StepTypes", "StepDefinitions"],
    "Endpoints, runs, operations, audits and settings": ["Endpoints", "JobRuns", "JobRunLogs", "Operations", "Audits", "Settings"],
}

TYPE_NAMES = {"Integer": "int", "String": "string", "Text": "text", "Boolean": "bool",
              "DateTime": "datetime", "Enum": "enum", "BigInteger": "bigint"}

GENERATED_NOTE = ("_Generated from `autoapp/app/models.py` by `docs/generate_diagrams.py`. "
                  "Do not edit by hand; change the models and run the script._")


def type_name(column):
    name = TYPE_NAMES.get(type(column.type).__name__, type(column.type).__name__.lower())
    length = getattr(column.type, "length", None) if name == "string" else None
    return f"{name}({length})" if length else name


def is_unique(table, column):
    if column.unique:
        return True
    return any(list(c.columns) == [column] for c in table.constraints
               if type(c).__name__ == "UniqueConstraint")


# --------------------------------------------------------------------------
# Database schema (tables, columns, foreign keys)
# --------------------------------------------------------------------------

def er_relationships(tables, only=None):
    """One line per foreign key. `only` limits output to keys that touch those tables."""
    lines = []
    for table in tables:
        for column in table.columns:
            for fk in column.foreign_keys:
                parent = fk.column.table.name
                if only is not None and table.name not in only:
                    continue
                if column.primary_key:
                    cardinality = "||--o|"      # shared primary key: at most one child row
                elif column.nullable:
                    cardinality = "|o--o{"      # optional parent
                else:
                    cardinality = "||--o{"      # required parent
                lines.append(f'    {parent} {cardinality} {table.name} : "{column.name}"')
    return lines


def er_entity(table):
    lines = [f"    {table.name} {{"]
    for column in table.columns:
        keys = []
        if column.primary_key:
            keys.append("PK")
        if column.foreign_keys:
            keys.append("FK")
        if not column.primary_key and is_unique(table, column):
            keys.append("UK")
        notes = []
        if not column.nullable and not column.primary_key:
            notes.append("required")
        if type(column.type).__name__ == "Enum":
            notes.append("one of: " + ", ".join(column.type.enums))
        parts = [type_name(column), column.name]
        if keys:
            parts.append(", ".join(keys))
        if notes:
            parts.append('"' + "; ".join(notes) + '"')
        lines.append("        " + " ".join(parts))
    lines.append("    }")
    return lines


def composite_unique_constraints(tables):
    rows = []
    for table in tables:
        for constraint in table.constraints:
            if type(constraint).__name__ == "UniqueConstraint" and len(constraint.columns) > 1:
                rows.append(f"| `{table.name}` | {', '.join(f'`{c.name}`' for c in constraint.columns)} |")
    return rows


def build_db_schema():
    tables = list(Base.metadata.sorted_tables)
    by_name = {t.name: t for t in tables}
    grouped = {name for names in TABLE_GROUPS.values() for name in names}
    missing = set(by_name) - grouped
    if missing:
        raise SystemExit(f"Add these tables to TABLE_GROUPS in {Path(__file__).name}: {sorted(missing)}")

    out = ["# Database Schema", "", GENERATED_NOTE, "",
           "This is the schema the Python models create. The MariaDB script `SQL/Create_Tables.sql` is "
           "generated from the same models by `SQL/generate_ddl.py`.", "",
           "## Reading the diagrams", "",
           "- `PK` primary key, `FK` foreign key, `UK` unique.",
           "- A line ending in a crow's foot is the \"many\" side. The label is the foreign key column.",
           "- `Applications`, `Entities`, `Sites`, `Credentials`, `Tags`, `Jobs` and `Endpoints` each share "
           "their primary key with one row in `MasterObjects`.", "",
           "## Overview", "", "All tables and how they connect.", "",
           "```mermaid", "erDiagram"]
    out += er_relationships(tables)
    out += ["```", ""]

    for title, names in TABLE_GROUPS.items():
        out += [f"## {title}", "", "```mermaid", "erDiagram"]
        for name in names:
            out += er_entity(by_name[name])
        out += er_relationships(tables, only=set(names))
        out += ["```", ""]

    constraints = composite_unique_constraints(tables)
    if constraints:
        out += ["## Multi-column unique constraints", "",
                "| Table | Columns that must be unique together |", "| :--- | :--- |"] + constraints + [""]
    return "\n".join(out)


# --------------------------------------------------------------------------
# Python model (classes, attributes, inheritance, relationships)
# --------------------------------------------------------------------------

def class_block(mapper, own_only=True):
    lines = [f"    class {mapper.class_.__name__} {{"]
    for attr in mapper.column_attrs:
        column = attr.columns[0]
        if own_only and mapper.inherits is not None and column.table is not mapper.local_table:
            continue
        lines.append(f"        +{type_name(column)} {attr.key}")
    lines.append("    }")
    return lines


def association_lines(mappers):
    lines = []
    for mapper in mappers:
        for rel in mapper.relationships:
            if rel.parent is not mapper:          # inherited; drawn on the class that defines it
                continue
            source, target = mapper.class_.__name__, rel.mapper.class_.__name__
            if rel.direction is RelationshipDirection.ONETOMANY:
                lines.append(f'    {source} "1" --> "*" {target} : {rel.key}')
            elif rel.direction is RelationshipDirection.MANYTOONE and not rel._reverse_property:
                lines.append(f'    {source} "*" --> "0..1" {target} : {rel.key}')
    return lines


def name_differences(mappers):
    rows = []
    for mapper in mappers:
        for attr in mapper.column_attrs:
            column = attr.columns[0]
            if column.table is mapper.local_table and attr.key != column.name:
                rows.append(f"| `{mapper.class_.__name__}` | `{attr.key}` | `{column.table.name}.{column.name}` |")
    return rows


MODULE_DIAGRAM = '''```mermaid
flowchart TD
    scheduler([WLA scheduler]) -->|"--job-key, --instance-id"| runner
    browser([Web browser]) -->|HTTP| ui

    subgraph engine [autoapp/engine]
        runner[runner.py<br/>runs a job's steps in order]
        scope[scope_engine.py<br/>resolves placeholders]
        datemask[date_mask.py<br/>date masks]
        renamemask[rename_mask.py<br/>rename masks]
        params[step_params.py<br/>working-folder rule and Endpoint lookup]
        stepcat[step_catalog.py<br/>parameter declarations, checking, conversion]
        preflight[preflight.py<br/>checks a whole job before it runs]
        registry[handlers/__init__.py<br/>step type to handler]
        base[handlers/base_handler.py<br/>timing, step logging, one record per file]
        joblog[job_log.py<br/>the job log and its levels]
        file[handlers/file_handler.py<br/>COPY_FILES]
        telemetry[telemetry_client.py<br/>writes the spool file]
        delivery[spool_delivery.py<br/>posts spool records to the API]
    end

    subgraph app [autoapp/app]
        models[models.py<br/>ORM classes]
        database[database.py<br/>engine and sessions]
        schemas[schemas.py<br/>API request and response shapes]
        jobs[routers/jobs.py<br/>POST /api/v1/jobs/init]
        variables[routers/variables.py]
        telemetry_api[routers/telemetry.py<br/>POST /api/v1/telemetry/records]
        ingest[telemetry_ingest.py<br/>loads records into JobRuns and Operations]
        operations_api[routers/operations.py<br/>operations log and file trace routes]
        trace[trace.py<br/>search and file trace]
        main[main.py<br/>FastAPI app]
        catalog[catalog.py<br/>publishes the step catalog to the database]
        steptypes_api[routers/step_types.py<br/>GET /api/v1/step-types]
        ui[ui/<br/>web pages: HTML, CSS, JavaScript]
    end

    runner --> scope
    runner --> preflight
    preflight --> params
    preflight --> registry
    params --> stepcat
    base --> stepcat
    runner --> telemetry
    runner --> database
    params --> scope
    scope --> datemask
    params --> renamemask
    file --> renamemask
    registry --> file
    file --> base
    base --> telemetry
    base --> joblog
    runner --> joblog
    file --> joblog
    telemetry --> delivery
    scope --> models
    params --> models
    database --> models

    main --> jobs
    main --> variables
    main --> telemetry_api
    main --> catalog
    main --> steptypes_api
    catalog --> registry
    catalog --> models
    steptypes_api --> models
    jobs --> preflight
    main -->|serves| ui
    ui -->|"HTTP, in the browser"| operations_api
    main --> operations_api
    jobs --> scope
    jobs --> params
    jobs --> registry
    jobs --> schemas
    variables --> scope
    telemetry_api --> ingest
    telemetry_api --> schemas
    ingest --> models
    operations_api --> trace
    trace --> models
    trace --> schemas

    telemetry --> spool[(spool .jsonl files)]
    delivery -->|HTTP| telemetry_api
    database --> db[(AutoApp database)]
```'''


def build_python_model():
    mappers = sorted(Base.registry.mappers, key=lambda m: m.class_.__name__)
    master = inspect(MasterObject)
    subtypes = [m for m in mappers if m.inherits is master]
    others = [m for m in mappers if m is not master and m.inherits is None]

    out = ["# Python Model", "", GENERATED_NOTE, "",
           "Two views: the ORM classes in `autoapp/app/models.py`, and how the Python modules depend "
           "on each other. The module diagram is written by hand inside the generator script.", "",
           "## ORM classes: inheritance", "",
           "The domain classes inherit from `MasterObject`. Each subclass shows only the "
           "attributes it adds; it also has everything `MasterObject` has.", "",
           "```mermaid", "classDiagram", "    direction TB"]
    out += class_block(master)
    for mapper in subtypes:
        out += class_block(mapper)
        out.append(f"    MasterObject <|-- {mapper.class_.__name__}")
    out += ["```", "",
            "## ORM classes: supporting classes and relationships", "",
            "An arrow is a relationship attribute you can follow in code: `job.steps` is the list of a "
            "job's `JobStep` objects. The label is the attribute name.", "",
            "```mermaid", "classDiagram", "    direction LR"]
    for mapper in others:
        out += class_block(mapper)
    out += association_lines(mappers)
    out += ["```", "",
            "Relationships created in the other direction (for example `job_step.job`) "
            "exist too but are not drawn.", ""]

    rows = name_differences(mappers)
    if rows:
        out += ["## Where the Python name differs from the column name", "",
                "Use the Python name in code and the column name in SQL.", "",
                "| Class | Python attribute | Database column |", "| :--- | :--- | :--- |"] + rows + [""]

    out += ["## Modules", "",
            "An arrow means \"uses\".", "", MODULE_DIAGRAM, ""]
    return "\n".join(out)


def main():
    for filename, content in (("DB_SCHEMA.md", build_db_schema()), ("PYTHON_MODEL.md", build_python_model())):
        (DOCS_DIR / filename).write_text(content)
        print(f"Wrote docs/{filename}")


if __name__ == "__main__":
    main()

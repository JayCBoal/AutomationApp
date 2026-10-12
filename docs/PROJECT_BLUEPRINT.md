# AutoApp Blueprint

How AutoApp works. Each section says what is **built** (in the code and covered by tests) and what is **planned** (designed but not implemented). Last reviewed 2026-10-11.

## 1. Execution flow

```
+--------------------------------------------------------------+
|  WLA scheduler (Control-M, AutoSys, ActiveBatch, cron, ...)  |
|  Owns schedules, dependencies, SLAs.                         |
+------------------------------+-------------------------------+
                               |  runs on an agent:
                               |  runner --job-key K --instance-id I
                               v
+--------------------------------------------------------------+
|  AutoApp runner (engine/runner.py)                           |
|  1. Finds the job by JobKey.                                 |
|  2. Builds the variable scope for the job.                   |
|  3. For each active step, in StepOrder:                      |
|       resolves parameters and file locations,                |
|       dispatches to the handler for the step type,           |
|       writes an operation record to the spool.               |
|  4. Exits 0 (success) or 1 (failure).                        |
+---------------+------------------------------+---------------+
                |                              |
                v                              v
+-------------------------------+   +--------------------------+
|  AutoApp database             |   |  Telemetry spool         |
|  jobs, steps, variables,      |   |  one .jsonl file per run |
|  endpoints, operations        |   |  (to be loaded into the  |
+-------------------------------+   |  Operations table)       |
                                    +--------------------------+
```

**Built**

- The runner as drawn above. A failing step stops the job. A job with no active steps, an unknown job key or an unknown step type fails with a clear message.
- The runner reads the database directly, through SQLAlchemy.

**Planned**

- Pull model: the runner fetches its payload over HTTPS from `POST /api/v1/jobs/init` instead of connecting to the database. The endpoint exists; the runner does not use it yet.
- Push model for isolated network zones: the scheduler fetches the payload and passes it to the agent.
- Restart controls from the 2024 prototype (start at step, stop after step, skip steps) and per-step success, warning and failure return codes.

## 2. Data model

Defined in `autoapp/app/models.py`. Diagrams: [DB_SCHEMA.md](DB_SCHEMA.md) and [PYTHON_MODEL.md](PYTHON_MODEL.md). Development uses SQLite; `DATABASE_URL` selects another database (MariaDB is the intended production target).

### MasterObjects supertype

`Applications`, `Entities`, `Sites`, `Credentials`, `Tags` and `Jobs` each share their primary key with a row in `MasterObjects` (joined-table inheritance). This gives every domain object one global ID, so `Variables` and `TagAssignments` can attach to any of them.

| Object | Meaning |
| :--- | :--- |
| Application | An internal system that produces or consumes files |
| Entity | An external counterparty: client, vendor, partner |
| Site | A technical location (host, port, protocol) belonging to an Entity |
| Credential | A secret used to reach a site or system |
| Job | The unit a scheduler runs; an ordered list of steps |
| Tag | A label, with its own variables, that can be attached to any object |

Jobs are deliberately **not** linked to an Application or Entity. A job may touch several of each. The relationship is expressed through the endpoints its steps use, and (planned) through tags.

### Jobs and JobKey

The job is the core unit, as it is in every scheduler: the set of steps that run together in one place. There is no level above it. Grouping related jobs, and deciding the order they run in, is the scheduler's business. (A `Processes` level existed until 2026-10-11; see the change log.)

`Jobs.JobKey` is the job's unique name. It is human-readable, independent of environment, and what the scheduler passes. The numeric primary key differs between databases and is never used outside AutoApp. Because the key also names the job's working folder, it is limited to letters, digits, `-`, `_` and `.`.

### Steps

- `StepTypes`: the catalog of step types. `Code` selects the handler.
- `StepDefinitions`: the parameters each step type accepts.
- `JobSteps`: a job's steps, with `StepOrder`, `StepTitle` and `IsActive`.
- `JobStepParameters`: name and value pairs for a step.

**Planned:** validating a step's parameters against `StepDefinitions` (required parameters, defaults). Today the definitions are not consulted.

### Endpoints

`Endpoints` is the register of places where files enter or leave AutoApp's control. It replaced the prototype's `Sources` and `Deliveries` tables. Each endpoint has:

- `Name`: unique; job steps reference it by this name.
- `Application`: the internal system it belongs to, if any.
- `Site`: the technical location it lives on, if any. The site's Entity is the endpoint's entity.
- `Path` and `FilenamePattern`: where, and which files. Both may contain placeholders.

An endpoint has no direction. The same folder can be a destination for one job and a source for the next; direction comes from which side of a step uses it.

### Operations and Audits

`Operations` holds one row per operation performed, including `SourceEndpoint_id` and `DestEndpoint_id`. `Audits` holds job-level events.

**Planned:** nothing writes to these tables yet. See section 6.

### Known inconsistency

The MariaDB DDL in `SQL/` and the SQL seed script disagree with the models in several places. The models are the working definition.

## 3. Variables and placeholders

Step parameters, endpoint paths and variable values may contain `${...}` placeholders. `engine/scope_engine.py` resolves them.

**Built**

| Syntax | Resolves to |
| :--- | :--- |
| `${Name}` | The variable `Name`, searched through the cascade below |
| `${JOB.Name}` | The variable on the job, specifically |
| `${APP.Name}`, `${ENTITY.Name}` | Inside an endpoint only: the variable on that endpoint's Application, or its Site's Entity |
| `${APP:LEGAL_APP.Name}`, `${ENTITY:JAYCO.Name}` | The variable on a named Application or Entity, from anywhere |
| `${SYS:YYYYMMDD}`, `${SYS:INSTANCE_ID}`, `${SYS:TIMESTAMP}`, `${SYS:WORKING_FOLDER}` | Values supplied by the runner |

- Cascade order, lowest priority first: `SYS`, `ENTITY`, `APP`, `TAG`, `JOB`. A higher level overrides a lower one of the same name.
- A variable's value may contain placeholders; they are resolved too, up to 10 levels deep. A circular reference is an error.
- A placeholder that cannot be resolved is an error naming the placeholder. Nothing runs with a literal `${...}` in a path.

**Planned**

- `TAG` scope: variables inherited from tags attached to a job, including tag hierarchies. This is also how related jobs will share variables. The models do not yet expose tag assignments to the engine.
- `STEP` scope: variables set on an individual step.

## 4. File locations

The rule: **a location outside the job's working folder must be a registered endpoint.**

**Built** (`engine/step_params.py`)

- Each job has its own working folder: `<working root>/<JobKey>`. No other job can use it, so a file passed from one job to another goes through an endpoint, which also records the handoff. The working root comes from `--working-root` or the `AUTOAPP_WORKING_ROOT` environment variable.
- Each side of a file step is given one of two ways:
  - `Source` / `Dest`: a raw path. It must be inside the working folder; a relative path is taken relative to it. Anything else is rejected.
  - `SourceEndpoint` / `DestEndpoint`: the name of an endpoint.
  - Setting both for the same side is an error.
- An endpoint's `Path` and `FilenamePattern` are resolved in the endpoint's own context, so `${APP.x}` means that endpoint's application. A source endpoint resolves to `Path/FilenamePattern`; a destination endpoint resolves to `Path`.
- The operation record for the step carries the IDs of the endpoints used. A hop inside the working folder carries none.

This is what makes a file trace possible: an operation that reads from an endpoint is a file entering, one that writes to an endpoint is a file leaving, and the endpoint says which application or entity that was.

**Planned**

- Endpoints on remote sites. They can be registered, but the only handler today works on local paths and rejects them.
- Checking delivered files against the destination endpoint's `FilenamePattern`, and rename masks on delivery.

## 5. Step handlers

**Built**

- `engine/handlers/base_handler.py`: the common wrapper. It times the step, writes the operation record, and writes an audit record on failure.
- `engine/handlers/file_handler.py`: step type `COPY_FILES` (alias `FILE_OP`). Local copy or move with wildcard matching and optional folder creation.
- `engine/handlers/__init__.py`: the registry mapping step type codes to handlers.

**Planned**

- Delete files, SQL execution, SFTP transfer, REST call, send email. The prototype had most of these as plain functions.

## 6. Telemetry

**Built** (`engine/telemetry_client.py`)

- The runner writes every operation and audit event as one JSON line to a spool file unique to the run.
- The file is named `.jsonl.tmp` while the job is running and renamed to `.jsonl` when it finishes, so a loader never picks up a half-written file.
- Writing locally means logging adds no network delay to the job and survives a database or network outage.

**Planned**

- A loader that reads completed spool files into `Operations` and `Audits`.
- Telemetry API routes (`/api/v1/telemetry/ops`, `/ops/batch`, `/audit`). The routes exist in the code but do not work: they use column names the models do not have.
- A file trace query across operations and endpoints.

## 7. REST API

FastAPI application in `autoapp/app/`.

| Route | State |
| :--- | :--- |
| `GET /health` | Built |
| `POST /api/v1/jobs/init` | Built; tested by calling the route function, not over HTTP |
| `GET /api/v1/variables/resolve` | Built; untested |
| `POST /api/v1/telemetry/...` | Present but broken |

**Planned:** authentication, CRUD routes for the web interface, HTTP-level tests.

## 8. Security

Nothing in this section is built.

- `Credentials.SecretData` is stored as plain text.
- `/jobs/init` returns every variable, including those flagged `IsSecret`.
- The API has no authentication.

**Planned:** encryption at rest, connectors to an external secrets vault, API authentication, and withholding secret values from API responses.

## 9. Asynchronous processes

Nothing in this section is built in the rewrite. The 2024 prototype tracked external tasks in `AsyncParentInstances` and `AsyncInstances` with a polling job; the tables exist in the DDL only.

## 10. User interfaces

Not started.

**Planned:** AutoApp is meant to be used from inside a scheduling product, with its own web interface as a second option. Both are clients of the REST API, so the CRUD API is the prerequisite for either.

## 11. Testing

- Tests are in `autoapp/tests/` and run with `python3 -m pytest`.
- Each test builds its own temporary SQLite database and temporary folders. No test touches the working directory or a shared database.
- Tests run the real code. AutoApp's own components are not mocked. The runner tests launch the runner as a separate process, as a scheduler would.
- A new test is checked by breaking the code it covers and confirming the test fails.
- `demo/run_demo.py` is not a test. It asserts nothing; it runs a sample job and shows what happened.

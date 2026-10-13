# AutoApp Blueprint

How AutoApp works. Each section says what is **built** (in the code and covered by tests) and what is **planned** (designed but not implemented). Last reviewed 2026-10-12.

## 1. Execution flow

```
+--------------------------------------------------------------+
|  WLA scheduler (Control-M, AutoSys, ActiveBatch, cron, ...)  |
|  Owns schedules, dependencies, SLAs.                         |
+------------------------------+-------------------------------+
                               |  runs on an agent:
                               |  runner --job-key K --instance-id I
                               |         [--run-number N] [--scheduler S]
                               v
+--------------------------------------------------------------+
|  AutoApp runner (engine/runner.py)                           |
|  1. Finds the job by JobKey.                                 |
|  2. Builds the variable scope for the job.                   |
|  3. For each active step, in StepOrder:                      |
|       resolves parameters and file locations,                |
|       dispatches to the handler for the step type,           |
|       writes one record per file to the spool,               |
|       posts the new records to the API.                      |
|  4. Exits 0 (success) or 1 (failure).                        |
+---------------+------------------------------+---------------+
                | reads                        | writes, then posts
                v                              v
+-------------------------------+   +--------------------------+
|  AutoApp database             |   |  Telemetry spool         |
|  jobs, steps, variables,      |<--|  one .jsonl file per run |
|  endpoints, runs, operations  |   |  delivered via the API   |
+-------------------------------+   +--------------------------+
```

**Built**

- The runner as drawn above. A failing step stops the job. A disabled job, a job with no active steps, an unknown job key or an unknown step type fails with a clear message. Disabled steps are skipped.
- Every run is recorded, including one that fails before touching a file.
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

### Runs and operations

**Built**

- `JobRuns`: one row per execution of a job. The scheduler stays the authority on scheduling; this is AutoApp's side of the run. It holds:
  - `RunID`, generated by the runner each time it starts, so every execution is distinct.
  - `SchedulerInstanceID`, the ID the scheduler passed.
  - `RunNumber`, for schedulers that keep one instance ID across restarts or cyclic runs (Control-M's run count, ActiveBatch's restart count). Defaults to 1.
  - `SchedulerName`, optional, for sites with more than one scheduler.
  - `JobKey`, start and end time, status and the error message.
- `Operations`: a register of what steps actually did. It points at its `JobRuns` row.
  - For a file step, one row per file: a source side and a destination side (endpoint if registered, path, filename, size), the operation type, status, error, times, and an optional SHA-256 checksum.
  - For a step that handles no files (SQL, REST call, email, once those step types exist), one row per action, with the file columns empty and what was done in `Details` (JSON). The handler call for this exists; no step type uses it yet.
  - A step that finds nothing to do writes no row. By default it fails, so the run's error message records what it looked for.

### Audits

`Audits` is for changes to definitions: who changed which job, endpoint or variable, and when. It is not used for job runs.

**Planned:** nothing writes to `Audits` yet. It will be written by the CRUD API.

### Source of truth

The Python models in `autoapp/app/models.py` are the definition of the schema.

**Built**

- `SQL/Create_Tables.sql`, the MariaDB table script, is generated from the models by `SQL/generate_ddl.py`.
- Column defaults are declared in the database as well as in the code, so a row inserted with plain SQL gets the same defaults as one inserted through AutoApp.
- `SQL/Seed_Sample_Data.sql` is a small working set of sample definitions in plain SQL. A test loads it and runs its jobs.
- `autoapp/create_dev_db.py` builds a local SQLite database from the models and the sample data.

- Runs on MariaDB (tested on 11.8) as well as SQLite. Two things are spelled out for MariaDB, where its defaults would give wrong answers:
  - Run and operation times are stored to the microsecond. A plain `DATETIME` there keeps whole seconds, and the trace orders operations by time.
  - Every table compares text exactly (collation `utf8mb4_bin`). MariaDB ignores case by default.
- **Names, paths and filenames are case-sensitive on every database.** `DEV-LOAD` and `dev-load` are two jobs; `Report.csv` and `report.csv` are two files. This applies to job keys, endpoint, application, entity, site and tag names, and variable and parameter names.
- Searches ignore case: the operations log lower-cases both sides itself.

**Planned**

- Two job keys that differ only by case get two working folders. That is fine on Linux; on an agent whose file system ignores case (Windows, macOS) they would share one.
- Sorting in the web interface: with exact comparison the database sorts capitals before lower-case letters, so pages that list names should sort them without regard to case themselves.
- Migrations (Alembic), so a schema change can be applied to a database that already holds data. Today the table script drops and recreates everything.

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

- `engine/handlers/base_handler.py`: the common wrapper. It times the step, logs it (see section 6), and gives handlers one call for recording a file they handled.
- `engine/handlers/file_handler.py`: step type `COPY_FILES` (alias `FILE_OP`). Local copy or move with wildcard matching and optional folder creation.
  - Each file is recorded separately, whether it succeeded or failed.
  - The size is measured at the source and at the destination; a difference fails the step.
  - `Checksum=True` records the file's SHA-256 and verifies the copy against it.
  - A step that finds no files fails unless `AllowNoFiles=True`.
- `engine/handlers/__init__.py`: the registry mapping step type codes to handlers.

**Planned**

- Delete files, SQL execution, SFTP transfer, REST call, send email. The prototype had most of these as plain functions.

## 6. The job log

What the runner prints while a job runs, for the scheduler to capture against that run.

**Built** (`engine/job_log.py`)

- Four levels, set with the runner's `--log-level` (or `AUTOAPP_LOG_LEVEL`):

  | Level | What is logged |
  | :--- | :--- |
  | `DEBUG` | Everything below, plus internal detail for troubleshooting |
  | `DETAIL` (default) | Each step's parameters, as written and as resolved, and every action it took, such as each file copied |
  | `SUMMARY` | One line per step saying what it did, plus warnings |
  | `SILENT` | Errors only |

- A step can set its own level with a `LogLevel` parameter, quieter or more detailed than the job's.
- This applies to every step type. The common wrapper logs the parameters and the closing line; a handler logs each action and returns a one-line account of the step.
- A file step that matches no files fails, and the error names the pattern it searched for. With `AllowNoFiles=True` it logs a warning and succeeds instead.
- Errors go to stderr, everything else to stdout.
- Values of variables marked secret are replaced with `********` wherever they would appear in the log.

**Planned**

- Secret values are masked in the log only. A secret used in a path would still appear in the operations record; see section 9.

## 7. Telemetry and the file trace

**Built**

- **Spool** (`engine/telemetry_client.py`). The runner writes one JSON line per record to a spool file unique to the run: `RUN_START`, one `OPERATION` per file, and `RUN_END`.
  - The file is named `.jsonl.tmp` while the job is running and renamed to `.jsonl` when it finishes.
  - Writing locally first means a job never fails, waits or loses its record because the API or database is unreachable.
- **Delivery through the API.** If the runner is given an API address (`--api-url` or `AUTOAPP_API_URL`), it posts the new records after each step and at the end of the run. A spool file whose records all arrived is moved to a `delivered` subfolder.
  - After one failed post the runner stops trying for that run and leaves the file in the spool.
  - `python3 -m engine.spool_delivery --spool-dir D [--api-url U]` sends whatever was left behind. Without an API address it loads the database directly, which suits a development machine.
- **Loading** (`app/telemetry_ingest.py`, route `POST /api/v1/telemetry/records`). Records are validated and stored in `JobRuns` and `Operations`. Loading is safe to repeat: a run is identified by its `RunID` and an operation by its position in the run, and anything already stored is skipped. A batch containing a bad record is refused whole.
- **Operations log** (`GET /api/v1/operations`). Search by source or destination endpoint, path and filename; by application, entity or site on either side; and by job key, instance ID, operation type, status and time range. Newest first, at most 500 rows.
- **File trace** (`app/trace.py`, route `GET /api/v1/operations/{id}/trace`). Starting from any operation, returns the whole route of that file. Operations are linked by location: one that read a file from a path follows the one that last wrote that file to that path. This:
  - crosses steps and jobs;
  - follows a file through a rename;
  - branches when a file is copied to two places;
  - keeps a recurring filename apart by time: a read belongs to the most recent write before it, and stops at the next write to the same place or at the operation that moved the file away;
  - shows a failed operation as the last hop, with its error;
  - leaves out operations that have no file: they are in the log, and each one's trace is only itself.

**Planned**

- Paths are compared as text, which is correct while everything runs on one machine. Locations on remote sites, or working folders on different agents, need the site or host added to the comparison.
- A retention rule for `Operations`, which grows by one row per file.
- Picking up spool files left as `.jsonl.tmp` by a run that was killed.

## 8. REST API

FastAPI application in `autoapp/app/`. The interactive description of every route is served at `/docs` when the API is running.

| Route | State |
| :--- | :--- |
| `GET /health` | Built |
| `POST /api/v1/jobs/init` | Built; tested by calling the route function, not over HTTP |
| `GET /api/v1/variables/resolve` | Built; untested |
| `POST /api/v1/telemetry/records` | Built; tested over HTTP |
| `GET /api/v1/operations` | Built; tested over HTTP |
| `GET /api/v1/operations/{id}/trace` | Built; tested over HTTP |
| `GET /ui/...` and `/` | The web interface's files; `/` redirects to it |

**Planned:** authentication, CRUD routes for the web interface.

## 9. Security

Nothing in this section is built.

- `Credentials.SecretData` is stored as plain text.
- `/jobs/init` returns every variable, including those flagged `IsSecret`.
- The API has no authentication.

**Planned:** encryption at rest, connectors to an external secrets vault, API authentication, and withholding secret values from API responses.

## 10. Asynchronous processes

Nothing in this section is built in the rewrite. The 2024 prototype tracked external tasks in `AsyncParentInstances` and `AsyncInstances` with a polling job; the tables exist in the DDL only.

## 11. User interfaces

**Built** (`autoapp/ui/`)

- The web interface is static pages: HTML, one stylesheet and plain JavaScript, with no build step. The API server serves them at `/ui/`, and they read everything through the REST API, never the database.
- One small library, Alpine.js, fills the pages from data. A copy is kept in `ui/vendor/`, so the pages need no internet connection.
- `common.js` holds what every page shares: the header and navigation bar, the theme switch, calling the API, formatting, and CSV export.
- Dark theme by default, with a light theme one click away. The choice is remembered in the browser.
- **Operations Log** page:
  - Search criteria grouped as in the 2024 mockup: when and what, source, destination, automation, and application, entity or site on either side.
  - One row per operation, with a source block and a destination block.
  - A **Trace** link opens the file's whole route, with branches indented.
  - **Export as CSV** exports the rows on screen with every field.
  - A search, or an open trace, can be bookmarked: the criteria are kept in the page address.
  - Times are shown, and date criteria entered, in the viewer's time zone. The API works in UTC.
- **Main Index** page, linking to every page. Pages not built yet are shown greyed out.

**Planned**

- Every other page in [UI_VISION.md](UI_VISION.md). The pages that edit definitions need the CRUD API first.
- AutoApp is meant to be used from inside a scheduling product, with this web interface as a second option. Both are clients of the same REST API.

## 12. Testing

- Tests are in `autoapp/tests/` and run with `python3 -m pytest` (177 tests: about a minute on SQLite, two on MariaDB).
- Each test builds its own temporary SQLite database and temporary folders. No test touches the working directory or a shared database.
- The same suite runs against MariaDB when `AUTOAPP_TEST_DATABASE_URL` names a test database. Its tables are built once per run from `SQL/Create_Tables.sql`, the script an installation would use, and emptied before each test.
- Tests run the real code. AutoApp's own components are not mocked. The runner tests launch the runner as a separate process, as a scheduler would.
- API tests go through real HTTP requests. The delivery tests start a real API server in its own process.
- The web interface is tested in a real browser (headless Chromium, driven by Playwright) against a real server: the tests click, type and read what is on screen.
- The only things replaced in tests are at the edge of the system: the file copy (to imitate a transfer cut short) and the network call (to see what the runner would send).
- A new test is checked by breaking the code it covers and confirming the test fails.
- `demo/run_demo.py` is not a test. It asserts nothing; it runs a sample job and shows what happened.

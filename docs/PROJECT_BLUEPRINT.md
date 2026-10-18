# RunMyFiles Blueprint

How RunMyFiles works. Each section says what is **built** (in the code and covered by tests) and what is **planned** (designed but not implemented). Last reviewed 2026-10-12.

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
|  RunMyFiles runner (engine/runner.py)                           |
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
|  RunMyFiles database             |   |  Telemetry spool         |
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

`Applications`, `Entities`, `Sites`, `Credentials`, `Tags`, `Jobs` and `Endpoints` each share their primary key with a row in `MasterObjects` (joined-table inheritance). This gives every domain object one global ID, so `Variables` and `TagAssignments` can attach to any of them.

| Object | Meaning |
| :--- | :--- |
| Application | An internal system that produces or consumes files |
| Entity | An external counterparty: client, vendor, partner |
| Site | A technical location (host, port, protocol) belonging to an Entity |
| Credential | A secret used to reach a site or system |
| Job | The unit a scheduler runs; an ordered list of steps |
| Tag | A label, with its own variables, that can be attached to any object. A tag can sit under a parent tag |

Jobs are deliberately **not** linked to an Application or Entity. A job may touch several of each. The relationship is expressed through the endpoints its steps use, and through tags.

### Schedulers

**Built**

- `Schedulers`: a workload automation product that runs RunMyFiles jobs. One RunMyFiles can serve several: each run records the scheduler that started it (the runner's `--scheduler`) and the business date it gave, if any (`JobRuns.BusinessDate`).
- A scheduler has a name, a technology (`RUNMYJOBS`, `ACTIVEBATCH`, `CONTROL_M`, `TIDAL`, `CRON`, `STANDIN`, `OTHER`), an API address, a description and an active flag. The credential RunMyFiles would use for its API is kept as a secret variable on it.
- The sample data registers `AutoApp UI`, the name the Run Job page runs jobs under.

- **Connectors** (`app/connectors/`), one per technology, read from the scheduler through its own API, with its `ApiToken`. So far they read a WLA job's parameters, for the job editor and the pre-run check. The first is for the Stand-in Scheduler ([demo/scheduler_standin](../demo/scheduler_standin/README.md)); see [INTEGRATION.md](INTEGRATION.md).

**Planned:** connectors for RunMyJobs, ActiveBatch, Control-M and Tidal (TO-DO decision 7).

### Tags

**Built**

- `Tags`: a name, a description and an optional parent (`Parent_MasterObject_id`), nested to any depth. Names are unique under one parent, not across all tags, so a tag is named by its path: `Finance/Reporting`, shown as `Finance / Reporting`. A name holds letters, digits, `-` and `_`; not `/` or `.`, which the path and `${TAG:...}` use.
- `TagAssignments`: a tag carried by any master object except another tag (a tag's place is its parent).
- A tag cannot be its own ancestor. A tag with child tags, or that something carries, cannot be deleted; the database refuses it too.
- Renaming or moving a tag rewrites the `${TAG:path.Var}` references to it, and to the tags under it, in step values and variable values.
- A parent tag is worth having when it carries variables its children share, or simply to make a child's name clear: `Environment / TEST` and `Purpose / TEST` are different tags.
- The `Category` column of the earlier design was dropped: nothing used it, and parent tags do the same job.

**Planned**

- An optional per-job setting saying which tag wins a conflict.
- A parent marked "pick one", so that nothing carries two of its children.

### Settings

**Built**

- System-wide settings are declared in `engine/settings.py`: a name, a type, a default, the allowed values and a description. The `Settings` table holds only the values changed from the default. Every change is audited.
- `VariablePrecedence` is the one setting so far (section 3).
- Settings are not variables: nothing reads them through `${...}`.

### Jobs and JobKey

The job is the core unit, as it is in every scheduler: anything that runs. `Jobs.JobType` says what it is made of: `STEPS`, the steps that run together in one place, or `WORKFLOW`, other jobs with dependencies between them (below). Since AutoApp became a demonstrator of scheduler features (2026-10-16), deciding the order jobs run in is AutoApp's business too. (A `Processes` level existed until 2026-10-11; see the change log.)

What every job shares lives in `Jobs`: its key, description, whether it is enabled, its type, `SuccessReturnCodes` (the return codes that mean it succeeded: `0`, `0, 4` or `0-4`; empty means 0), and `Owner_MasterObject_id`, the workflow an embedded job belongs to (empty until embedded jobs are built). What belongs to one type lives in that type's tables.

### Workflows

A workflow is a job of type `WORKFLOW` (the design: [WORKFLOWS.md](WORKFLOWS.md); Phase 1: [WORKFLOWS_PHASE1.md](WORKFLOWS_PHASE1.md); Phase 3, Reactions: [WORKFLOWS_PHASE3.md](WORKFLOWS_PHASE3.md)).

**Built**

- `WorkflowItems`: each job a workflow uses, under a name of its own in it (letters, digits, `_` and `-`; unique within the workflow), so the same job can be used more than once. A name left out is made from the job's key. `JoinRule` is `ALL` (it starts when all its prerequisites hold) or `ANY`; `ItemOrder` is its place in the outline, which does not affect when it runs.
- `WorkflowPrerequisites`: what an item waits for: another item of the workflow, and a test: `SUCCESS` (the default), `FAILED`, `ENDED` (whatever happened, Not run included) or `RC` (one of `ReturnCodes`). `Condition`, for conditions written in SQL, is for a later phase.
- Saving checks: names unique, no job waiting for itself, no loops ("'A', which waits for 'C', which waits for 'B', which waits for 'A'"), every job used exists, and a workflow never uses itself, even through another. A job a workflow uses cannot be deleted. A job's type cannot be changed once it is created.
- A workflow's pre-run check is its own (disabled, empty) and its jobs' (the first problem of each job that would not run).
- Running: `engine/workflow_runner.py`, started by `engine.runner` when the job is a workflow, so a scheduler and the Run Job page start it as they start any job. It works on the database directly. It reads the workflow once, at the start; then, about every second, it starts each job whose prerequisites hold (each in a job runner of its own, as the scheduler "AutoApp workflow"), marks Not run each job whose prerequisites can never hold (which can cascade), ends Disabled a disabled job when its turn comes, and records each job's state in `WorkflowRunItems`. It ends Failed if a failure went unhandled, that is a job failed and nothing that waits for it ran (Reason `JOB_FAILED`), or if jobs were cancelled (`CANCELLED`); otherwise Succeeded, so a failure path that ran leaves it green. A job runner whose records did not arrive through the API has its spool loaded straight into the database.
- Cancel (`POST /api/v1/runs/{run_id}/cancel`): starts nothing more; the jobs running finish; those not started are Not run (Reason `CANCELLED`).

- The workflow page (Phase 2: [WORKFLOWS_PHASE2.md](WORKFLOWS_PHASE2.md)): Diagram | Outline. The diagram is `ui/js/workflow_diagram.js`: elkjs (`ui/vendor/elk-0.12.0.bundled.js`) lays the boxes and lines out, and it draws them as SVG; it knows nothing of the server, and is handed what to draw by `ui/js/workflow.js`. `ui/mockup_workflow.html` still shows the whole design, with what later phases add.
- Job History is a tree: `GET /api/v1/runs?tree=true` leaves out runs whose workflow run is listed too; `parent=` lists the runs inside one.
- **Reactions** (Phase 3): what happens after a job ends, chosen by how it ended. `Reactions` belong to a job (`Job_MasterObject_id`) or to one use of it in a workflow (`Item_id`, when `WorkflowItems.ReactionsOverridden`: the use's list then replaces the job's, even when empty). `Section` `NEXT` (What happens next: in order, the first that holds decides) or `ALSO` (every one that holds fires); the When is `WhenTest` (`SUCCESS`, `FAILED`, `ENDED`, `RC` with `WhenReturnCodes`). `ReactionActions`: `COUNT_AS_SUCCEEDED`, `COUNT_AS_FAILED`, `RERUN` and `RERUN_FROM` (`MaxTimes`, `WaitSeconds`, `TargetItem_id`), `SKIP` (`TargetItem_id`), `SKIP_BRANCH`, `KILL_WORKFLOW`; and under Also `START_WORKFLOW` (`TargetJob_MasterObject_id`). Rerun from, Skip, Skip the rest of the branch and Kill the workflow only on a use.
  - Saving checks them (`app/reaction_store.py`); `engine/reactions.py` judges them; the workflow runner carries them out for a job in a workflow, the job runner for a job (or workflow) run on its own. Each entry is judged on what really happened; once a rerun has used up its limit, the next entry that holds decides. "The rest of the branch" is what waits for the job, directly or not, except what waits for the outcome it had (a failure path, a clean-up) and what follows that.
  - A Count as keeps the run's own outcome in `StatusBeforeOverride`. Each action that fired, or was passed over at its limit, is a `ReactionEvents` row (job runners send theirs as `REACTION` spool records). A killed job's Reactions do not apply.
- **Disable here** (`WorkflowItems.DisabledHere`): `STOP` ends the job Disabled; `PASS_THROUGH` ends it Bypassed (Reason `DISABLED_PASS_THROUGH`), which prerequisites treat as succeeded with return code 0.
- **Kill**: `POST /api/v1/runs/{run_id}/kill`. A job's runner is sent SIGTERM (its `ProcessID`, on this machine only) and ends Failed, `KILLED`, with no return code. A workflow's run gets `KillRequestedDateTime`; its runner kills its running jobs (down through workflows inside) and cancels the rest (Kill and Cancel). The workflow runner records each job's process on its `WorkflowRunItems` row as it starts it, so `POST /api/v1/runs/{run_id}/items/{path}/kill` works before the job's own records arrive.

**Planned**: the later phases in WORKFLOWS.md (conditions, outside dependencies, embedded workflows, restarts, time-based Reactions).

`Jobs.JobKey` is the job's unique name. It is human-readable, independent of environment, and what the scheduler passes. The numeric primary key differs between databases and is never used outside RunMyFiles. Because the key also names the job's working folder, it is limited to letters, digits, `-`, `_` and `.`.

### Steps

- `StepTypes`: the catalog of step types. `Code` selects the handler.
- `StepDefinitions`: the parameters each step type takes: name, type, whether required, default, description, display order, and for a file location whether it is a source or a destination.
- `JobSteps`: a job's steps, with `StepOrder`, `StepTitle` and `IsActive`.
- `JobStepParameters`: name and value pairs for a step.

### The step catalog

**Built**

- **Declared once, in the code.** Each handler lists its parameters (`engine/step_catalog.py`). Parameter types are `STRING`, `BOOLEAN`, `INTEGER`, `CHOICE` and `LOCATION`.
- **Published to the database.** `app/catalog.py` copies the declarations into `StepTypes` and `StepDefinitions`. It runs each time the API server starts, and by hand with `python3 -m app.catalog`.
- **Served by the API.** `GET /api/v1/step-types` returns every step type with its parameters in form order. This is what the job editor will build its step forms from.
- **Every job is checked before it runs** (`engine/preflight.py`). All active steps are checked and resolved before the first one starts, and every problem is reported at once:
  - a parameter the step type does not have;
  - a required parameter missing;
  - a location given both as a path and as an endpoint;
  - a value of the wrong type, such as `Move=perhaps`, including one that came from a placeholder;
  - an unknown endpoint, an unresolved placeholder, a path outside the working folder, an unknown step type.
- **A job can be checked without running it:** `GET /api/v1/jobs/{job_key}/check` returns the same list of problems.
- Handlers receive converted values (`True`, not the text `"True"`) with defaults filled in.

**Planned**

- A parameter that depends on another, such as one that only applies when `Move` is on.
- Hiding a step type from the editor with `StepTypes.IsActive`. The column exists; nothing reads it yet.

### Endpoints

`Endpoints` is the register of places where files enter or leave RunMyFiles' control. It replaced the prototype's `Sources` and `Deliveries` tables. Each endpoint has:

- `Name`: unique; job steps reference it by this name.
- `Application`: the internal system it belongs to, if any.
- `Site`: the technical location it lives on, if any. The site's Entity is the endpoint's entity.
- `Path` and `FilenamePattern`: where, and which files. Both may contain placeholders.

An endpoint has no direction. The same folder can be a destination for one job and a source for the next; direction comes from which side of a step uses it.

### Runs and operations

**Built**

- `JobRuns`: one row per execution of a job. The scheduler stays the authority on scheduling; this is RunMyFiles' side of the run. It holds:
  - `RunID`, generated by the runner each time it starts, so every execution is distinct.
  - `SchedulerInstanceID`, the ID the scheduler passed.
  - `RunNumber`, for schedulers that keep one instance ID across restarts or cyclic runs (Control-M's run count, ActiveBatch's restart count). Defaults to 1.
  - `SchedulerName`, optional, for sites with more than one scheduler.
  - `JobKey`, start and end time, status and the error message.
  - `ReturnCode` (0 unless a step set one) and `Reason`: why it ended as it did (`ERROR`, `RETURN_CODE`, `JOB_FAILED`, `CANCELLED`).
  - `JobType`, and for a run inside a workflow run: `ParentRun_id`, `WorkflowPath` (its place in the workflow) and `Attempt`. A workflow's own run is a `JobRuns` row too.
- `WorkflowRunItems`: one row per job of a workflow run, with its state (`PENDING`, `WAITING`, `RUNNING`, `SUCCESS`, `FAILED`, `NOT_RUN`, `DISABLED`, `BYPASSED`, `SKIPPED`), Reason, return code, `StatusBeforeOverride`, attempt, the `ProcessID` of its runner and its latest job run. A job that never started has no job run, so this is where the run says so.
- `ReactionEvents`: each Reaction's action that fired after a job ended, or was passed over at its limit (`TOOK_EFFECT` or `LIMIT_REACHED`), with the job run it was judged on and, in a workflow, the workflow run and path.
- `Operations`: a register of what steps actually did. It points at its `JobRuns` row.
  - For a file step, one row per file: a source side and a destination side (endpoint if registered, path, filename, size), the operation type, status, error, times, and an optional SHA-256 checksum.
  - A step that only looks at a file (`CHECK`) or removes it (`DELETE`) fills in the source side only.
  - For a step that handles no files (a SQL statement now; a REST call or an email later), one row per action, with the file columns empty and what was done in `Details` (JSON). A query that wrote a CSV is one row, `SQL_EXPORT`, with the file as its destination and the statement in `Details`.
  - A step that finds nothing to do writes no row. By default it fails, so the run's error message records what it looked for.

### Audits

`Audits` is for changes to definitions: who changed which job, endpoint or variable, and when. It is not used for job runs.

**Built:** creating, changing and deleting a job each write an audit row saying in words what changed (`app/job_store.py`). There are no user accounts yet, so every change is recorded as made by "web interface".

Registering an endpoint, application, entity or site writes one too.

Changing or deleting an application, entity, site or endpoint writes one as well, and the Audit Log page shows them.

### Source of truth

The Python models in `autoapp/app/models.py` are the definition of the schema.

**Built**

- `SQL/Create_Tables.sql`, the MariaDB table script, is generated from the models by `SQL/generate_ddl.py`.
- Column defaults are declared in the database as well as in the code, so a row inserted with plain SQL gets the same defaults as one inserted through RunMyFiles.
- `SQL/Seed_Sample_Data.sql` is a small working set of sample definitions in plain SQL. A test loads it and runs its jobs.
- `autoapp/create_dev_db.py` builds a local SQLite database from the models and the sample data.

- Runs on MariaDB (tested on 11.8) as well as SQLite. On SQLite, RunMyFiles switches on foreign-key enforcement, which SQLite leaves off by default, so that deleting a step removes its parameters there as it does on MariaDB. Two things are spelled out for MariaDB, where its defaults would give wrong answers:
  - Run and operation times are stored to the microsecond. A plain `DATETIME` there keeps whole seconds, and the trace orders operations by time.
  - Every table compares text exactly (collation `utf8mb4_bin`). MariaDB ignores case by default.
- **Names, paths and filenames are case-sensitive on every database.** `DEV-LOAD` and `dev-load` are two jobs; `Report.csv` and `report.csv` are two files. This applies to job keys, endpoint, application, entity, site and tag names, and variable and parameter names.
- Searches ignore case: the operations log lower-cases both sides itself.

**Planned**

- Two job keys that differ only by case get two working folders. That is fine on Linux; on an agent whose file system ignores case (Windows, macOS) they would share one.
- Sorting in the web interface: with exact comparison the database sorts capitals before lower-case letters, so pages that list names should sort them without regard to case themselves.
- Migrations (Alembic), so a schema change can be applied to a database that already holds data. Today the table script drops and recreates everything. Until then, the server at least names what an older database is missing (`app/schema_check.py`), in its log at startup and in the error a page shows.

## 3. Variables and placeholders

Step parameters, endpoint paths and variable values may contain `${...}` placeholders. `engine/scope_engine.py` resolves them.

**Built**

| Syntax | Resolves to |
| :--- | :--- |
| `${Name}` | The variable `Name`, searched through the cascade below |
| `${JOB.Name}` | The variable on the job, specifically |
| `${APP.Name}`, `${ENTITY.Name}` | Inside an endpoint only: the variable on that endpoint's Application, or its Site's Entity |
| `${APP:LEGAL_APP.Name}`, `${ENTITY:JAYCO.Name}` | The variable on a named Application or Entity, from anywhere, including what its tags give it |
| `${ENV:Name}` | An environment variable of the runner's process, which is where a scheduler puts a job's own variables. On the server (the editor's preview and the pre-run check) it is left for the run to fill in, as the scheduler's environment is not known there |
| `${BUSINESS_DATE:yyyyMMdd}` | The date the run is for, from the runner's `--business-date` (Control-M's order date), with the same masks as `${DATE:...}`. Without one, the date the run started |
| `${TAG:Finance/Reporting.Name}` | The variable as that tag gives it. Only a tag the job carries, or a parent of one. This also picks one side of a conflict |
| `${DATE:yyyyMMdd}`, `${DATE:yyyy-MM-dd_HHmmss}`, ... | The moment the run started, in the format the mask gives. See "Date masks" below |
| `${SYS:INSTANCE_ID}`, `${SYS:TIMESTAMP}`, `${SYS:WORKING_FOLDER}` | Values supplied by the runner. `${SYS:YYYYMMDD}` also still works; `${DATE:yyyyMMdd}` is the form to use |
| `${FILE:NAME}`, `${FILE:STEM}`, `${FILE:EXT}` | Parts of a file's own name. Only in a rename mask; see section 5 |

- Cascade order, lowest priority first, by default: `ENV`, `SYS`, `ENTITY`, `APP`, `ENDPOINT`, `TAG`, `JOB`. A higher level overrides a lower one of the same name. The order is the `VariablePrecedence` setting, changed on the Settings page.
  - `ENTITY`, `APP` and `ENDPOINT` apply only while an endpoint's path and pattern are being filled in.
  - `TAG` is what the job's tags give it; `ENDPOINT` is what the endpoint's tags give it.
  - `ENV` is the runner's environment, so a plain `${Name}` finds a variable the scheduler set when nothing in RunMyFiles defines it. On the server there is no such environment, so a plain name found nowhere else is reported there as unresolved; write `${ENV:Name}` for a value that only the scheduler gives. Planned: RunMyFiles reading the WLA job's parameters from the scheduler (TO-DO decision 7), so the editor knows them too.
  - A precedence saved before a level existed keeps its order, with the new level at the lowest priority.
- **Tags.** A tag's variables act as if they were on whatever carries it, just below that object's own. So a job's tags feed the job; an application's or entity's tags feed wherever that object's variables reach. A tag inherits its parents' variables, and its own override theirs.
- **Conflicts.** When two of an object's tags give one variable different values, nothing is chosen. Using that variable is an error, unless the object gives it a value of its own or a higher level does; a conflict does not fall back to a lower level's value. A conflict on a variable the job does not use is a warning in the job editor. The same value from two tags is not a conflict, nor is one parent reached through two tags. Error messages name the tags, never the values.
- A variable's value may contain placeholders; they are resolved too, up to 10 levels deep. A circular reference is an error.
- A placeholder that cannot be resolved is an error naming the placeholder. Nothing runs with a literal `${...}` in a path.

**Planned**

- Naming a tag the job does not carry in `${TAG:...}`, perhaps as a system-wide setting. Decided against for now: the dependency would be hidden from the tag's "used by" list (see TO-DO decision 3).
- `STEP` scope: variables set on an individual step.

### How a preview is made

**Built**

- `POST /api/v1/jobs/preview` takes a job exactly as the editor would save it. The server makes the changes inside a database transaction, works out what each step's parameters resolve to with the same code the runner uses, and then rolls the transaction back. The preview therefore cannot disagree with what a real run would do, and nothing is saved by asking.
- Each parameter is resolved on its own, so a mistake in one field does not hide the others.

### Date masks

**Built** (`engine/date_mask.py`)

- `${DATE:mask}` gives the moment the run started, in the format the mask describes. Every date placeholder in a run shows the same moment.
- The mask letters are the ones .NET uses, as the 2024 prototype did, because their case tells months from minutes:

  | Letters | Meaning | Example |
  | :--- | :--- | :--- |
  | `yyyy`, `yy` | Year | 2026, 26 |
  | `MMMM`, `MMM`, `MM`, `M` | Month (capital M) | October, Oct, 10, 10 |
  | `dddd`, `ddd`, `dd`, `d` | Day | Tuesday, Tue, 06, 6 |
  | `HH`, `H` | Hour, 24-hour clock | 14, 14 |
  | `hh`, `h`, `tt` | Hour, 12-hour clock, and AM or PM | 02, 2, PM |
  | `mm`, `m` | Minute (small m) | 05, 5 |
  | `ss`, `s`, `fff` | Second, and milliseconds | 09, 9, 042 |

- Punctuation, digits and spaces are copied as they are. Text in single quotes is copied as it is: `yyyyMMdd'T'HHmm`.
- Any other letter is an error. A mask in the wrong case, such as `YYYYMMDD`, is refused before the job starts, not turned into the wrong text.

**Planned**

- A business date: running a job "as of" a date the scheduler supplies (Control-M's order date, for example) instead of today. The prototype called this `UseDate`.

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
- `engine/handlers/file_handler.py`: step type `COPY_FILES`. Local copy or move with wildcard matching and optional folder creation.
  - Each file is recorded separately, whether it succeeded or failed.
  - The size is measured at the source and at the destination; a difference fails the step.
  - `Checksum=True` records the file's SHA-256 and verifies the copy against it.
  - A step that finds no files fails unless `AllowNoFiles=True`.
  - `Dest` may name a new filename only when one file is taken. Several files aimed at one filename fail the step before anything is copied.
  - `RenameMask` gives each file a new name on the way: `${FILE:STEM}_${DATE:yyyyMMdd}${FILE:EXT}` turns `Legal_Batch_1.csv` into `Legal_Batch_1_20261013.csv`. `${FILE:NAME}` is the file's own name, `${FILE:STEM}` its name without the extension, `${FILE:EXT}` its extension with the full stop. It works whether the destination is a folder or an endpoint. A mask that would give two files the same name fails the step before anything is copied, and a mistake in a mask is found before the job starts.
  - A step parameter can be declared as holding per-file placeholders. Those are left for the handler to fill in for each file; anywhere else, `${FILE:...}` is an unresolved placeholder.
- `engine/handlers/set_return_code.py`: step type `SET_RETURN_CODE` (Set Return Code): sets the job's return code to `ReturnCode` and carries on; the last one run wins. `Message` goes to the job log beside it. Operation type `SET_RETURN_CODE`, one row per step.
- `engine/handlers/simulate.py`: step type `SIMULATE` (Simulate), for building and trying workflows before the real jobs exist. It writes the `Messages` it is given to the job log at `MessageLevel`, takes `WaitSeconds`, sets the job's return code to `ReturnCode`, and with `Fail` fails with `FailMessage`. Operation type `SIMULATE`, one row per step.
- A step can set the job's return code (`job_return_code` on its handler; Simulate does). The last one set counts; otherwise it is 0, or 1 when a step failed. The job succeeded if its steps did and the code is one of its Success return codes; if not, it fails with Reason `RETURN_CODE`. The runner's exit code stays 0 or 1 (docs/INTEGRATION.md); the code is recorded with the run.
- `engine/handlers/file_tools.py`: four more file steps. Each records every file it handles, and each fails when it finds nothing unless `AllowNoFiles=True` (Check Files counts instead).
  - `DELETE_FILES` (Delete Files): removes the matching files, or with `OlderThanDays` only those last changed more than that many days ago. Operation type `DELETE`.
  - `CHECK_FILES` (Check Files): fails the job unless the files look right: at least `MinCount` (default 1) and at most `MaxCount`, none empty unless `AllowEmpty`, none older than `MaxAgeHours`. It lists every problem at once and touches nothing. Operation type `CHECK`.
  - `ZIP_FILES` (Zip Files): packs the matching files into one archive. `Dest` is the archive's name, or a folder or endpoint with `ArchiveName`. The archive is written under a temporary name, checked, then renamed, so nothing sees half of one; an archive of the same name is replaced only with `Overwrite`. `Move` removes the originals once they are safely in it. Operation type `ZIP`, or `ZIP_MOVE`, one row per file with the archive as its destination.
  - `UNZIP_FILES` (Unzip Files): takes every file out of the matching archives into the `Dest` folder, keeping their folders. Every name is checked before anything is taken out: one that would land outside the folder (`../`, or a full path) refuses the whole archive. A file already there is replaced only with `Overwrite`. Operation type `UNZIP`, one row per file taken out, with the archive as its source.
- `engine/handlers/sql_handler.py`: step type `RUN_SQL` (Run SQL). Runs one statement against the database a connection URL names (`Database`), normally kept in a secret variable.
  - A query's rows can be written to `ResultFile` as CSV, with a line of column names unless `IncludeHeader=False`. The file is written under a temporary name and renamed when complete.
  - Changes are rolled back unless `Commit=True`, so a statement can be tried safely; the job log says so when it rolled back changes.
  - The statement is sent as written, so `:` and `%` in it mean nothing to RunMyFiles; `${...}` placeholders are filled in first.
  - The database's password never appears in the job log, the operation record or an error message, whether or not the URL came from a secret.
  - Any database SQLAlchemy has a driver for will do. The project installs the MariaDB/MySQL driver; SQLite needs none.
- A parameter of type `TEXT` is a string that may run to several lines. The job editor shows it as a box that grows to fit, in a fixed-width font. Run SQL's `Statement` is one.
- `engine/handlers/__init__.py`: the list of handlers. Adding one there adds its step type to the catalog.

**Planned**

- SFTP transfer, REST call, send email. The prototype had these as plain functions.
- A Connections table for databases and servers (see TO-DO). Until then a database is a URL in a secret variable.

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

- **Spool** (`engine/telemetry_client.py`). The runner writes one JSON line per record to a spool file unique to the run: `RUN_START`, one `OPERATION` per file, and `RUN_END`. `RUN_START` says where the job log is (below).
- **Job logs kept with each run, as files on the host that ran it.** Every line the runner prints is also written, secret values already masked, to `<log root>/<host>/<YYYY-MM-DD>/<RunID>.log` (`engine/log_files.py`; the log root is `AUTOAPP_LOG_ROOT`, by default `autoapp/logs`), line by line as it goes. The run's record keeps only where: its `Host` and `LogFile`. The server reads a log by asking that host's agent for it (`app/log_agent.py`), as a WLA reads job output through its agents; AutoApp has no agents, so a stand-in reads the host's folder on this machine. A run still going shows its log so far.
- **Old logs are removed** after the Settings page's "Keep job logs for" (30 days by default; a week to a year, or never), at server startup and then once a day. The run's record keeps when (`LogRemovedDateTime`), and its log page says so. Runs and their operations are kept.
  - The file is named `.jsonl.tmp` while the job is running and renamed to `.jsonl` when it finishes.
  - Writing locally first means a job never fails, waits or loses its record because the API or database is unreachable.
- **Delivery through the API.** If the runner is given an API address (`--api-url` or `AUTOAPP_API_URL`), it posts the new records after each step and at the end of the run. A spool file whose records all arrived is moved to a `delivered` subfolder.
  - After one failed post the runner stops trying for that run and leaves the file in the spool.
  - `python3 -m engine.spool_delivery --spool-dir D [--api-url U]` sends whatever was left behind. Without an API address it loads the database directly, which suits a development machine.
- **Loading** (`app/telemetry_ingest.py`, route `POST /api/v1/telemetry/records`). Records are validated and stored in `JobRuns` and `Operations`. Loading is safe to repeat: a run is identified by its `RunID` and an operation by its position in the run, and anything already stored is skipped. A batch containing a bad record is refused whole.
- **Operations log** (`GET /api/v1/operations`). Search each side by endpoint, application, entity, site, path and filename; and by job key, instance ID, scheduler, operation type, status and time range. Newest first, at most 500 rows.
- **File trace** (`app/trace.py`, route `GET /api/v1/operations/{id}/trace`). Starting from any operation, returns the whole route of that file. Operations are linked by location: one that read a file from a path follows the one that last wrote that file to that path. This:
  - crosses steps and jobs;
  - follows a file through a rename;
  - branches when a file is copied to two places;
  - keeps a recurring filename apart by time: a read belongs to the most recent write before it, and stops at the next write to the same place or at the operation that moved the file away;
  - shows a failed operation as the last hop, with its error;
  - follows a file into an archive and out again. The archive's own journey is part of the route of every file in it, and each file's route carries on from the unzip that took that file out. A trace started from the archive itself shows it from where it was made, with every file taken out of it;
  - ends at a delete;
  - starts a CSV made by a query at the query (`SQL_EXPORT`);
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
| `GET /api/v1/step-types`, `/step-types/{code}` | Built; tested over HTTP |
| `GET /api/v1/jobs` | The job search, including whether each job would run. Built; tested over HTTP |
| `GET /api/v1/jobs/{job_key}` | One job with its steps and parameters. Built; tested over HTTP |
| `POST /api/v1/jobs`, `PUT` and `DELETE /api/v1/jobs/{job_key}` | Create, save and delete a job, including its variables. Built; tested over HTTP |
| `POST /api/v1/jobs/preview` | What an unsaved job would resolve to, and whether it would run. Saves nothing. Built; tested over HTTP |
| `GET /api/v1/endpoints`, `POST /api/v1/endpoints` | List the registered endpoints; register a new one. Built; tested over HTTP |
| `GET /api/v1/lookups` | The names offered in drop-downs. Built; tested over HTTP |
| `GET`, `PUT`, `DELETE /api/v1/{applications,entities,sites,endpoints,tags}[/{name}]` | Search, view, change and remove them, and the tags they carry. A tag's name is its path: `/api/v1/tags/Finance/Reporting`. Every search takes `tag`, which includes child tags. Built; tested over HTTP |
| `POST /api/v1/tags` | Register a tag, under a parent if wanted. Built; tested over HTTP |
| `POST /api/v1/schedulers`, and `GET`, `PUT`, `DELETE /api/v1/schedulers[/{name}]` | Register, search, view, change and remove schedulers. Built; tested over HTTP |
| `GET /api/v1/tag-variables?tag=...&tag=...&own=...` | What a set of tags gives together and where each variable comes from, and their conflicts; secrets masked. The pages ask it before a tag is added. Built; tested over HTTP |
| `GET /api/v1/settings`, `PUT /api/v1/settings/{key}` | The system-wide settings. Built; tested over HTTP |
| `GET /api/v1/runs`, `GET /api/v1/audits` | Job History and the Audit Log. Built; tested over HTTP |
| `GET /api/v1/runs/{run_id}` | One run, with its job log as far as it has arrived. Built; tested over HTTP |
| `POST /api/v1/launches`, `GET /api/v1/launches/{id}` | Run a job now: the server starts the real runner as a separate process, as a scheduler would, and says when it has finished. Built; tested over HTTP |
| `POST /api/v1/applications`, `/entities`, `/sites` | Register an application, entity or site. Built; tested over HTTP |
| `GET /api/v1/jobs/{job_key}/check` | Built; tested over HTTP |
| `GET /api/v1/jobs/{job_key}/summary` | A job described for a scheduler to show in its own interface. Built; tested over HTTP |
| `GET /api/v1/schedulers/{name}/jobs/{wla_job}` | A WLA job's parameters, read through its connector. Built; tested over HTTP |
| `GET /ui/...` and `/` | The web interface's files; `/` redirects to it |

**Planned:** authentication, CRUD routes for the web interface.

## 9. Security

Nothing in this section is built, apart from keeping secret values out of the pages, the job log and the operation records.

- Anyone who can reach the web interface can run any job from the Run Job page.

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
- `common.js` holds what every page shares: the header and navigation bar, the theme switch, calling the API, formatting, CSV export, the behaviour common to every search page (criteria, the results summary, keeping a search in the page address), and drop-downs: a box marked `data-lookup="endpoints"` is given a list of the registered endpoints, and likewise for applications, entities, sites, jobs and schedulers.
- Dark theme by default, with a light theme one click away. The choice is remembered in the browser.
- **Operations Log** page:
  - Search criteria grouped as in the 2024 mockup: when and what; source and destination, each with endpoint, application, entity, site, path and filename; and automation, with job, instance ID and scheduler.
  - One row per operation, with a source block and a destination block.
  - A **Trace** link opens the file's whole route, with branches indented.
  - **Export as CSV** exports the rows on screen with every field.
  - A search, or an open trace, can be bookmarked: the criteria are kept in the page address.
  - Times are shown, and date criteria entered, in the viewer's time zone. The API works in UTC.
- **Jobs & Workflows** page (`jobs.html`, once Job Search):
  - Search by job key, description, type (job or workflow), enabled or disabled, and an endpoint the job uses. A Type column says which each is.
  - Each row shows the job's steps, the endpoints it uses and how its most recent run went, with the error if it failed.
  - Every job found is put through the pre-run check. A job that would run says **Ready to run** in green. One that would not has a bold red **Check** link, which checks the job again and lists every problem. A disabled job says **Disabled** in grey. Nothing is run.
  - The job key, and a **View** link, open the job's detail page.
  - **Operations** opens the Operations Log for that job.
- **Job Detail** page, which is the job editor:
  - A selector to find and open a job; the job's key, description, enabled flag and history; the command a scheduler would run it with; and whether it would run, with any problems listed.
  - Its steps in order, collapsed to one line each (`LEGAL_EXTRACTS -> incoming`), expandable one at a time or all at once.
  - Each step's form is drawn from the step catalog, not written into the page: a tick box for true or false, a list for a choice, and for a file location the choice between an endpoint and a working-folder path. A parameter the step leaves out shows its default, marked as such.
  - A parameter that the step type does not have is pointed out, and can be removed.
  - The page arrives locked. **Edit** unlocks it; **Save** is enabled once something has changed and saves the whole job in one request; **Cancel** puts everything back.
  - Steps can be added, removed, reordered with arrows, retitled and enabled or disabled. A true-or-false parameter can be put back to its default, so the step stops storing a value of its own.
  - After a save the page says what changed and re-runs the pre-run check. A job is saved even if the check finds problems, which are then listed.
  - **New job** starts a blank job. Renaming a job asks for confirmation first, because the scheduler and the working folder use its key. **Delete job** works for a job that has never run; one with run history must be disabled instead.
  - A file location's endpoint box offers the registered endpoints as a drop-down, narrowed by what is typed, each with its application and path. A name that is not registered is pointed out as it is typed.
  - **New...** beside an endpoint box opens a window to register an endpoint without leaving the page: name, application, site, path, filename pattern and description. The endpoint is created at once, independently of saving the job, and is put into the box it was opened from.
  - **Variables panel:** the job's own variables, each with a name, value, secret flag and description. They are saved with the job. A secret's value is never sent to the page: its box is blank, and leaving it blank keeps the value it has.
  - **Live preview:** as the form is edited, each file location shows where it really is, and any value with a placeholder shows what it resolves to, or why it cannot be. "Would it run?" follows the form too, before anything is saved. Secret values are masked.
  - A placeholder naming a variable the job does not have offers **Add variable ...**, which adds it to the panel ready for its value.
  - That window's Application and Site boxes have a **New...** of their own, and the New site window has one for its Entity. All five windows (endpoint, application, site, entity, tag) are one mechanism in `common.js` (`createInPlace`), driven by a short description of each form, so a later page gets them by asking.
  - **Tags panel**, as on the detail pages below. Its "What its tags give" table also stops **Add variable ...** being offered for a variable a tag provides. A conflict among the job's tags on a variable it does not use is shown as a warning under "Would it run?"; one it uses is a problem.
- **Application, Entity, Site, Endpoint, Tag and Scheduler** pages: one search page and one detail page serve all six (`search.html?kind=sites`, `detail.html?kind=sites&name=...`; a tag is named by its path, `detail.html?kind=tags&name=Finance/Reporting`), drawn from a short description of each kind in `definitions.js`.
  - Search by any field; each row says how much uses it. Every search page except the tags' own has a **Tag** box, which finds what carries a tag whose path contains the text, or any tag under it, and a Tags column.
  - **New** opens the detail page blank and unlocked, so a new one is created with its variables and its active flag in one go. The small "New..." windows remain for registering something from inside another form.
  - The detail page arrives locked; Edit, Save and Cancel work as on the job editor. Fields that name another kind have its drop-down and a **New...** link.
  - **Used by** lists what refers to it, as links. Something still in use cannot be deleted, and the page says what uses it.
  - Applications, entities and sites have a Variables panel. An application's `Root`, which its endpoints' paths use, is set here.
  - An endpoint links to the files taken from it and delivered to it on the Operations Log. Renaming an endpoint renames it in every job step that names it.
  - **Tags panel** (everything but a tag): the tags it carries, as links, and a table of what they give it and from which tag, with secrets masked and a struck-out value where its own variable wins. While editing, a tag is chosen from a drop-down (or made with **New...**); before it is added, the panel shows the variables it would give and any conflict it would bring with the tags already there. The panel is one piece of markup and code in `common.js` (`fillTagPanels`, `tagEditing`), shared with the job editor.
  - A scheduler's page says how many runs it has started, linking to them in Job History, and its technology is chosen from a list.
  - A tag's page shows its parent, the variables it inherits from its parents and from which one, and, under Used by, its child tags and what carries it.
- **Job History** page: every run, newest first, with its status, error, timing, the scheduler's identifiers, a link to the files it handled, and a **Log** link to its job log.
- **Job Log** page (`log.html?run=...`): one run's job log as the runner printed it, with errors and warnings picked out, and the run's status, times and a link to its operations. A run still going is followed until it ends.
- **Run Job** page: runs a job now, as a scheduler would, for trying jobs out without one. Find a job with the Job Search page's criteria and **Choose** it, or type its key (it shows whether it would run), an instance ID (one is made from the time if left blank, e.g. `UI-20261015-183012`) and a log level, and **Run**. The server starts the real runner as a separate process, with "AutoApp UI" as its scheduler; the page shows the command, follows the run and shows its log as each step ends, then the outcome and exit code. The job editor has a **Run** button that opens this page with the job chosen. A business date can be given, as Control-M would.
  - The server remembers its launches only until it restarts; the runs themselves are in Job History as usual.
  - The runner it starts keeps its spool in `autoapp/spool`, or where `AUTOAPP_SPOOL_DIR` says.
- **Audit Log** page: every change to a definition or a setting, newest first, saying in words what changed, with a link to the thing changed if it still exists.
- **Settings** page: each system-wide setting with what it means, drawn from the declarations in `engine/settings.py`. The variable precedence is a list put in order with arrows. Each setting is saved on its own, can be undone, or put back to its default.
- **Main Index** page, linking to every page, in three sections: Definitions, Records of what happened, and Administration (Settings).
- **Embedded mode:** any page opened with `embed=1` in its address shows a thin bar instead of the header and navigation, for a scheduler to show inside its own interface. Its links stay embedded; `theme=` matches the host's look. The job editor then shows only its own job, and tells the window that opened it when it is ready, has saved (with the job key, whether it would run, and what changed), was cancelled or deleted. `job.html?new&key=...` starts a new job with a suggested key. The addresses and messages a WLA plug-in may rely on are in [INTEGRATION.md](INTEGRATION.md), and `tests/test_ui_embedded.py` keeps them working.

**Planned**

- Every other page in [UI_VISION.md](UI_VISION.md). The pages that edit definitions need the CRUD API first.
- RunMyFiles is meant to be used from inside a scheduling product, with this web interface as a second option. Both are clients of the same REST API.

## 12. Testing

- Tests are in `autoapp/tests/` and run with `python3 -m pytest` (about 700 tests: about six minutes on SQLite, eight on MariaDB). On the development machine, `autoapp_tests` (from `dev_env.sh`) runs both at once, in about eight minutes; each run has its own temporary folder.
- Each test builds its own temporary SQLite database and temporary folders. No test touches the working directory or a shared database.
- The same suite runs against MariaDB when `AUTOAPP_TEST_DATABASE_URL` names a test database. Its tables are built once per run from `SQL/Create_Tables.sql`, the script an installation would use, and emptied before each test.
- Tests run the real code. RunMyFiles' own components are not mocked. The runner tests launch the runner as a separate process, as a scheduler would.
- API tests go through real HTTP requests. The delivery tests start a real API server in its own process.
- The web interface is tested in a real browser (headless Chromium, driven by Playwright) against a real server: the tests click, type and read what is on screen.
- The only things replaced in tests are at the edge of the system: the file copy (to imitate a transfer cut short) and the network call (to see what the runner would send).
- A new test is checked by breaking the code it covers and confirming the test fails.
- `demo/run_demo.py` is not a test. It asserts nothing; it runs a sample job and shows what happened.

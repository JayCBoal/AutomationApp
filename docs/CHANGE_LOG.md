# Change Log

Notable structural, schema and design changes to AutoApp, newest first. Line-by-line history is in git.

---

## 2026-10-12

### Run history and per-file operations

- **Added:** `JobRuns`, one row per execution of a job: AutoApp's run ID, the scheduler's instance ID, a run number, an optional scheduler name, status, error and times.
- **Changed:** `Operations` is one row per thing a step did, not one per step. For a file step that is one row per file, with a source and a destination side (endpoint, path, filename, size). A step that handles no files (SQL, REST call, email) will leave the file columns empty and describe what it did in `Details`. Each row points at its run. `SourceURI`, `DestinationURI`, `BytesTransferred` and `ExecutionInstanceID` are gone.
- **Changed:** `Audits` now records changes to definitions (`Action`, `PerformedBy`, `Details`). It no longer holds job start and end events, which are the run row's job.
- **Added:** `IsActive` on `Entities` and `Sites`.
- **Added:** runner options `--run-number` and `--scheduler`.
- **Changed:** the runner refuses a disabled job. Previously only disabled steps were honoured.
- **Rationale:**
  - A trace needs one row per file. The spool nested the files inside one record per step, and the table had room for one source and one destination per row, so the two never agreed.
  - Schedulers differ in how they number runs. ActiveBatch and RunMyJobs issue a new ID per run; Control-M keeps one ID for the day and counts runs. Storing AutoApp's own run ID plus what the scheduler passed covers both.
  - The scheduler already tracks job lifecycle, so AutoApp keeps only a thin run row: enough to group a run's file operations and to record a failure that happened before any file moved.

### Telemetry: one path, through the API

- **Changed:** the spool is always written first and then delivered through the API. The API is no longer a separate "live" path with the spool as a different-format fallback.
- **Added:** `POST /api/v1/telemetry/records`, which accepts spool records as they are and is safe to call twice with the same records.
- **Removed:** `POST /api/v1/telemetry/ops`, `/ops/batch` and `/audit`, which referred to columns that did not exist.
- **Added:** `engine/spool_delivery.py`, the command that sends spool files left behind.
- **Added:** runner option `--api-url`. The runner posts after each step; a failed post never affects the job.
- **Rationale:** two paths need two record formats, and they had already drifted apart. One path means the same records whether they arrive immediately or a day later.

### Operations log and file trace

- **Added:** `GET /api/v1/operations` (search) and `GET /api/v1/operations/{id}/trace` (a file's whole route).
- **Added:** the trace links operations by location and time. See the blueprint, section 7.

### File handler

- **Added:** each file's size is measured at source and destination; a difference fails the step.
- **Added:** `Checksum` step parameter, which records and verifies a SHA-256.
- **Changed:** a folder whose name matches the source pattern is skipped instead of failing the step.

### Job log

- **Added:** `engine/job_log.py`, with four levels: `DEBUG`, `DETAIL` (default), `SUMMARY` and `SILENT`. Set with the runner's `--log-level`, or for one step with a `LogLevel` parameter.
- **Changed:** at the default level every step logs its parameters as written and as resolved, each action it took, and a closing line with the outcome. Before, a step logged one line with its title.
- **Changed:** errors go to stderr and everything else to stdout. Before, everything went to stderr.
- **Added:** values of secret variables are masked in the log.
- **Rationale:** carries forward the 2024 prototype's logging, where the job log said what each step did and a step could be made quiet.

### No files matched

- **Changed:** a file step whose source matches no files now fails. Before, it succeeded with a warning.
- **Added:** `AllowNoFiles` step parameter (default `False`). When `True`, the step logs a warning and succeeds.
- **Rationale:** in batch work, finding nothing usually means something upstream is late or broken. Succeeding quietly hides that until someone downstream misses the file; failing puts it in front of the scheduler. Steps that legitimately find nothing, such as a sweep of an often-empty folder, opt in.

### Schema source of truth

- **Decided:** the Python models define the schema.
- **Changed:** the MariaDB table script is now generated from the models (`SQL/generate_ddl.py` writes `SQL/Create_Tables.sql`). It replaces the hand-written `Drop_Recreate_&_Repopulate_Tables.sql`, which had drifted from the models.
- **Removed:** `AsyncParentInstances` and `AsyncInstances` from the table script. They had no model; they return when asynchronous processes are rebuilt.
- **Changed:** column defaults (`IsActive`, `CreatedBy`, `StepOrder` and others) are declared in the database as well as in the code. Before, a row inserted with plain SQL had no `IsActive` value and was treated as disabled.
- **Changed:** `SQL/Seed_Sample_Data.sql` replaces `Seed_MasterObjects_Data.sql`, which named columns that did not exist. The new one is plain SQL that runs on MariaDB and SQLite, and a test runs its jobs.
- **Added:** `autoapp/create_dev_db.py`, which builds a development database with the sample data.

### Environment

- **Changed:** development moved to Python 3.13 in a project-local `.venv`. The test HTTP client is `httpx2`.

---

## 2026-10-11

### Repository cleanup

- Moved the 2024 prototype (`modules/`, `scripts/`, `env/`, legacy SQL and the legacy database dump) out of the repository. It is kept alongside as reference material.
- Added `.gitignore`. Stopped tracking compiled Python files and the local SQLite database.
- Moved the project documents into `docs/`.
- Restored `engine/handlers/base_handler.py` and `engine/telemetry_client.py` to their last committed versions, after uncommitted edits had removed the handler's `run()` wrapper and the spooler's atomic rename.
- Removed tests that mocked the components under test, could not fail, or referenced code that did not exist.

### Runner rewritten

- `engine/runner.py` runs a job's real `JobSteps` rows in `StepOrder`, stops at the first failing step, and exits `0` or `1`.
- Removed `engine/resolver.py`. The scope engine is the only place placeholders are resolved.

### JobKey

- **Added:** `Jobs.JobKey`, a unique string independent of environment. Initially `<process name>--<job name>`; see "Removed the Process level" below.
- **Changed:** the runner takes `--job-key`; `/api/v1/jobs/init` takes `job_key`. Lookups by numeric ID or by job name are gone.
- **Rationale:** the numeric ID differs between databases, and job names are not unique across processes. A scheduler needs one stable identifier.

### Variable resolution

- **Added:** placeholders inside variable values are resolved, up to 10 levels deep. Circular references raise an error.
- **Changed:** a placeholder that cannot be resolved is an error. Previously it was left in the text, which produced folders literally named `${ArchiveFolder}`.
- **Changed:** `ENTITY` and `APP` scopes belong to an endpoint, not to a job. They resolve only when interpolating an endpoint's own `Path` and `FilenamePattern`.

### Endpoints as the file register

- **Added:** `Endpoints.Name`, unique. Job steps reference endpoints by name.
- **Removed:** `Endpoints.EndpointType` (`SOURCE` / `DELIVERY`). Direction comes from which side of a step uses the endpoint.
- **Removed:** the direct `Entity` column on `Endpoints` in the DDL. An endpoint's entity is reached through its site.
- **Added:** `Operations.SourceEndpoint_id` and `Operations.DestEndpoint_id`; the same IDs are written to the telemetry spool.
- **Added:** the working-folder rule. Each side of a file step is either a raw path inside the job's working folder (`Source`, `Dest`) or a named endpoint (`SourceEndpoint`, `DestEndpoint`).
- **Added:** the working folder, available as `${SYS:WORKING_FOLDER}`.
- **Rationale:** endpoints exist to record where files enter and leave. Requiring every outside location to be registered, and recording the endpoint on each operation, makes a file's route a database join instead of an after-the-fact match on path text.

### Removed the Process level

- **Removed:** the `Processes` table and model, `Jobs.Process_MasterObject_id`, `Jobs.Name`, `Jobs.ExecutionOrder`, the `PROC` variable scope and the `${PROC.x}` syntax.
- **Changed:** `JobKey` is now simply the job's unique name, no longer `<process name>--<job name>`. It is restricted to characters that are safe in a folder name.
- **Changed:** the working folder is `<working root>/<JobKey>`, private to one job. It was `<working root>/<process name>`, shared by a process's jobs.
- **Rationale:** every scheduler treats the job as the core unit of work. The process level came from an earlier environment, where it grouped the jobs that one piece of work had to be split into because they ran on different execution queues. Grouping and ordering jobs is the scheduler's role, so AutoApp does not need its own version of it.
- **Consequences:** a file handed from one job to another must pass through a registered endpoint. Variables shared by several jobs will come from tags, once tags are built.

### Testing

- Added a pytest suite covering the scope engine, step parameter resolution, file handler, telemetry spooler, runner and `/jobs/init`.
- Added `demo/run_demo.py`.

---

## 2026-10-06

### Consolidated file transfer definitions into `Endpoints`

- **Removed:** `Sources` and `Deliveries` tables.
- **Added:** `Endpoints` table with `EndpointType` (`SOURCE`, `DELIVERY`), linking a site, an entity and an application to a `Path` and `FilenamePattern`.
- **Rationale:** removes duplication between two near-identical tables.
- **Superseded 2026-10-11:** the type and the direct entity link were removed.

### Re-anchored `Entities` to `Sites`

- **Added:** `Sites.Entity_MasterObject_id`.
- **Rationale:** entities are external counterparties (vendors, clients, partners). Technical locations such as SFTP servers belong to them.

### Decoupled `Processes` and `Jobs` from fixed entities

- **Removed:** `Application_id` and `Entity_id` from `Processes`.
- **Rationale:** a workflow can cross several applications and partners.

### Polymorphic supertype registry (`MasterObjects`)

- **Added:** `MasterObjects` as the base of `Applications`, `Entities`, `Sites`, `Credentials`, `Tags`, `Processes` and `Jobs`. Each uses `MasterObject_id` as both primary key and foreign key to `MasterObjects(id)`.
- **Added:** `Variables` and `TagAssignments` attach to any `MasterObject_id`, with cascade delete.

### Execution and log tables

- **Changed:** simplified `Operations`, `Audits`, `AsyncParentInstances` and `AsyncInstances`. High-volume log tables use plain auto-incrementing keys and stay outside the `MasterObjects` registry.

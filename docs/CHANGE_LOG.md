# Change Log

Notable structural, schema and design changes to AutoApp, newest first. Line-by-line history is in git.

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

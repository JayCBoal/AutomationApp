# To-Do

Draft of 2026-10-11. The order under "Work queue" is a proposal; the items under "Decisions needed" are waiting on a choice.

## Decisions needed

1. **Sharing between related jobs.** With the process level removed, each job stands alone. Two things it used to provide need a replacement, if they are wanted:
   - Variables shared by several jobs. Proposal: tags (see decision 5).
   - A way to see several jobs as one piece of work in the file trace. Proposal: a tag, or a correlation ID supplied by the scheduler.

2. **How the runner gets its payload.** The design says agents pull over HTTPS from `/api/v1/jobs/init` and never connect to the database. The runner currently connects to the database directly. Options: switch the runner to the API now; support both; or leave direct access until the API has authentication.

3. **Telemetry direction.** Built: always write to a local spool, load into the database afterwards. Previously under review: post each event to the API as it happens and use the spool only as a fallback when the API is unreachable. Pick one as the primary path.

4. **Source of truth for the schema.** The models, the MariaDB DDL and the SQL seed script disagree. Proposal: the models are the source of truth, the DDL is generated from them, and a migration tool (Alembic) manages changes from here on.

5. **Tag rules.** When two tags on the same job define the same variable, is that an error, or does a precedence rule pick one? Do tags have a parent and child hierarchy?

6. **Working folder.** Currently `<working root>/<JobKey>`, private to the job and reused by every run of it. Confirm, or make it per run. Also decide whether archive folders live inside it or are registered endpoints.

7. **Destination endpoints.** Should a delivery be checked against the destination endpoint's `FilenamePattern`? Should endpoints carry a rename mask, as the prototype's `Deliveries` table did?

8. **No files matched.** A copy step whose pattern matches nothing currently succeeds. Should that be success, a warning, or a failure, and should the step be able to choose?

9. **Prototype features.** Which of these carry forward: start at step, stop after step, skip steps; per-step success, warning and failure return codes; job history; date masks with a "use date" override?

10. **What "inside the scheduler" means first.** The goal is for AutoApp to be used from within a scheduling product. Decide the first integration target and its shape: for example, job definitions edited in the scheduler's interface through AutoApp's API, results written back to the scheduler's job log, and single sign-on. This raises the priority of the CRUD API relative to a standalone web interface.

11. **Repository housekeeping.**
    - Merge `cleanup/post-gemini` into `main` and push.
    - `/home/jayboal` is itself a git repository pointing at `JayCBoal.github.io`.
    - `AutomationApp/_gemini_debris/` and the zip files in `PriorArt/CodeRepo/backup/` can be deleted once no longer wanted.

## Work queue

Ordered toward a demonstration: a job built in the job editor, run by a scheduler, and traced file by file. The job editor and the file trace are the two things to show.

### Next: make the trace real

1. **Load the spool into the database.**
   - Loader that reads completed `.jsonl` files into `Operations` and `Audits`, including endpoint IDs.
   - Fix the three telemetry API routes, which use column names the models do not have.
   - Install `httpx` and add tests that call the API over HTTP.

2. **File trace.** Given a filename or an instance ID, list the operations that touched the file and the endpoints, applications and entities involved.

3. **Align the schema.** Depends on decision 4.
   - Regenerate the DDL from the models.
   - Replace `SQL/Seed_MasterObjects_Data.sql`, which does not run against the current DDL.
   - Add a script that creates a development database with sample data. The old one was removed; `demo/run_demo.py` contains a working example of seeding.

### Then: the job editor

4. **Step catalog and validation.** The editor is driven by the catalog: choosing a step type shows that type's parameters as form fields. Populate `StepTypes` and `StepDefinitions` for each handler, mark which parameters are file locations, and check a step's parameters against the definitions (required present, defaults applied, unknown rejected).

5. **CRUD API.** Create, read, update and delete for jobs, steps, step parameters, variables, endpoints, applications, entities and sites. Both the web interface and any scheduler integration are clients of this.

6. **Job editor (web interface).** Specified in [UI_VISION.md](UI_VISION.md).
   - Build a job as an ordered list of steps chosen from the catalog.
   - Endpoint picker: a file step chooses an existing endpoint or creates one in place.
   - Variable editor on any object, with a preview of what each placeholder resolves to.
   - Run history and file trace views.

### Then: breadth

7. **More step handlers.** Each one also adds a catalog entry, so it appears in the editor.
   - Delete files
   - SQL execution
   - SFTP transfer (this is what makes endpoints on remote sites usable)
   - REST call
   - Send email

8. **Tags.** Depends on decision 5. Expose tag assignments in the models, add the `TAG` scope to the variable cascade.

9. **Runner controls.** Depends on decision 9.

10. **Scheduler integration.** Depends on decision 10.

### Later

11. **Runner uses the API.** Depends on decision 2.

12. **Security.** Encrypt `Credentials.SecretData`; stop returning `IsSecret` variables; API authentication; vault connectors. Needed before anyone other than the author uses it.

13. **Asynchronous processes.** Port the prototype's async instance tracking and polling.

14. **Dependency declaration.** Move dependencies from `requirements.txt` into `pyproject.toml` and make the project installable.

## Done

See [CHANGE_LOG.md](CHANGE_LOG.md).

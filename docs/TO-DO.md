# To-Do

Updated 2026-10-12. The order under "Work queue" is a proposal; the items under "Decisions needed" are waiting on a choice.

## Decisions needed

1. **Sharing between related jobs.** With the process level removed, each job stands alone. Two things it used to provide need a replacement, if they are wanted:
   - Variables shared by several jobs. Proposal: tags (see decision 3).
   - A way to see several jobs as one piece of work. The file trace already follows a file from job to job, so this is only about grouping jobs for display. Proposal: a tag.

2. **How the runner gets its payload.** The design says agents pull over HTTPS from `/api/v1/jobs/init` and never connect to the database. The runner currently connects to the database directly. Options: switch the runner to the API now; support both; or leave direct access until the API has authentication.

3. **Tag rules.** When two tags on the same job define the same variable, is that an error, or does a precedence rule pick one? Do tags have a parent and child hierarchy?

4. **Working folder.** Currently `<working root>/<JobKey>`, private to the job and reused by every run of it. Confirm, or make it per run. Also decide whether archive folders live inside it or are registered endpoints.

5. **Destination endpoints.** Should a delivery be checked against the destination endpoint's `FilenamePattern`? Should endpoints carry a rename mask, as the prototype's `Deliveries` table did?

6. **Prototype features.** Which of these carry forward: start at step, stop after step, skip steps; per-step success, warning and failure return codes; job history; date masks with a "use date" override?

7. **What "inside the scheduler" means first.** The goal is for AutoApp to be used from within a scheduling product. Decide the first integration target and its shape: for example, job definitions edited in the scheduler's interface through AutoApp's API, results written back to the scheduler's job log, and single sign-on. This raises the priority of the CRUD API relative to a standalone web interface.

8. **Repository housekeeping.** `AutomationApp/_gemini_debris/` and the zip files in `PriorArt/CodeRepo/backup/` can be deleted once no longer wanted.

9. **Front end.** Confirm plain static pages (HTML and a small script library, no build step) that call the REST API. See [UI_VISION.md](UI_VISION.md).

10. **Leftovers from removing the process level.** Confirm that dropping `Jobs.Name` and `Jobs.ExecutionOrder`, and the mockup's Severity field, is acceptable.

Decided and removed from this list: telemetry direction (spool first, delivered through the API), the schema's source of truth (the Python models), what a file step does when nothing matches (fails unless `AllowNoFiles` is set), and upper and lower case in names (case-sensitive everywhere). See [CHANGE_LOG.md](CHANGE_LOG.md).

## Work queue

Ordered toward a demonstration: a job built in the job editor, run by a scheduler, and traced file by file. The job editor and the file trace are the two things to show.

### Next: first page

1. **Operations Log page.** The first page of the web interface: a read-only search over `GET /api/v1/operations`, with a Trace link. Depends on decision 9.

2. **Migrations.** Adopt Alembic so that later schema changes are applied to an existing database instead of rebuilding it.

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

8. **Tags.** Depends on decision 3. Expose tag assignments in the models, add the `TAG` scope to the variable cascade.

9. **Runner controls.** Depends on decision 6.

10. **Scheduler integration.** Depends on decision 7.

### Later

- **Trace across machines.** The trace compares paths as text. Add the site or host to the comparison once steps reach remote sites or agents on more than one machine.
- **Skip the rest when nothing was collected.** If a job's first step is allowed to find nothing, every later step that reads the same folder needs `AllowNoFiles` too. A step option to end the job successfully at that point would be tidier.
- **Delete step default.** When the delete step type is built, decide whether finding nothing to delete should succeed by default.
- **Retention.** A purge rule for `Operations`, which grows by one row per file.
- **Killed runs.** Pick up spool files left as `.jsonl.tmp` by a run that did not end normally, and mark the run accordingly.

11. **Runner uses the API.** Depends on decision 2.

12. **Security.** Encrypt `Credentials.SecretData`; stop returning `IsSecret` variables; API authentication; vault connectors. Needed before anyone other than the author uses it.

13. **Asynchronous processes.** Port the prototype's async instance tracking and polling.

14. **Dependency declaration.** Move dependencies from `requirements.txt` into `pyproject.toml` and make the project installable.

## Done

See [CHANGE_LOG.md](CHANGE_LOG.md).

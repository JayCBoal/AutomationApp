# To-Do

Updated 2026-10-13. The order under "Work queue" is a proposal; the items under "Decisions needed" are waiting on a choice.

## Decisions needed

1. **Sharing between related jobs.** With the process level removed, each job stands alone. Two things it used to provide need a replacement, if they are wanted:
   - Variables shared by several jobs. Proposal: tags (see decision 3).
   - A way to see several jobs as one piece of work. The file trace already follows a file from job to job, so this is only about grouping jobs for display. Proposal: a tag.

2. **How the runner gets its payload.** The design says agents pull over HTTPS from `/api/v1/jobs/init` and never connect to the database. The runner currently connects to the database directly. Options: switch the runner to the API now; support both; or leave direct access until the API has authentication.

3. **Tag rules.** When two tags on the same job define the same variable, is that an error, or does a precedence rule pick one? Do tags have a parent and child hierarchy?

4. **Working folder.** Currently `<working root>/<JobKey>`, private to the job and reused by every run of it. Confirm, or make it per run. Also decide whether archive folders live inside it or are registered endpoints.

5. **Destination endpoints.** Should a delivery be checked against the destination endpoint's `FilenamePattern`, including after a rename mask has been applied?

6. **Prototype features.** Which of these carry forward: start at step, stop after step, skip steps; per-step success, warning and failure return codes; and a "use date" (business date) for date masks, which today always show the moment the run started?

7. **What "inside the scheduler" means first.** The goal is for AutoApp to be used from within a scheduling product. Decide the first integration target and its shape: for example, job definitions edited in the scheduler's interface through AutoApp's API, results written back to the scheduler's job log, and single sign-on. This raises the priority of the CRUD API relative to a standalone web interface.

8. **Repository housekeeping.** `AutomationApp/_gemini_debris/` and the zip files in `PriorArt/CodeRepo/backup/` can be deleted once no longer wanted.

9. **Leftovers from removing the process level.** Confirm that dropping `Jobs.Name` and `Jobs.ExecutionOrder`, and the mockup's Severity field, is acceptable.

Decided and removed from this list: telemetry direction (spool first, delivered through the API), the schema's source of truth (the Python models), what a file step does when nothing matches (fails unless `AllowNoFiles` is set), upper and lower case in names (case-sensitive everywhere), and the front end (static pages calling the API). See [CHANGE_LOG.md](CHANGE_LOG.md).

## Work queue

Ordered toward a demonstration: a job built in the job editor, run by a scheduler, and traced file by file. The job editor and the file trace are the two things to show.

### Next: the other pages

The job editor is built: viewing, editing, creating and deleting a job; endpoints chosen from a drop-down or registered in place; the job's variables; and a live preview. Specified in [UI_VISION.md](UI_VISION.md).

1. **Endpoint, Application, Entity and Site pages.** Search and detail pages for each, in the pattern of the Job pages, with routes to change and remove them. They can be registered today but not changed.

2. **Job History and Audit Log pages.** Read-only search pages in the pattern of the Operations Log. Job History needs a `GET /api/v1/runs` route. The audit rows are already being written.

### Then: breadth

3. **More step handlers.** Each one also adds a catalog entry, so it appears in the editor.
   - Delete files
   - SQL execution
   - SFTP transfer (this is what makes endpoints on remote sites usable)
   - REST call
   - Send email

4. **Tags.** Depends on decision 3. Expose tag assignments in the models, add the `TAG` scope to the variable cascade.

5. **Runner controls.** Depends on decision 6.

6. **Scheduler integration.** Depends on decision 7.

### Later

- **Variables on applications, entities and sites.** The job editor shows and edits a job's own variables. An application's `Root`, which an endpoint's path uses, can so far only be set in the database. It belongs on those pages.
- **Which variables a job can see.** A view listing every variable in reach of a job and where each comes from. Worth building once tags add a second source.

- **Changing and removing endpoints, applications, entities and sites.** Each can be registered from a "New..." window but not yet changed or removed. That comes with their own pages.

- **A placeholder in a tick-box parameter.** A true-or-false parameter stored as `${...}` is shown as text and can be edited, but the editor offers no way to switch a tick box to a placeholder. Add a "use a variable" switch.
- **Duplicate a job**, to start a new job from an existing one.
- **Who made a change.** Audit rows say "web interface" until there are user accounts.

- **Job search speed.** The search checks every job it returns, which is fine for hundreds of jobs. If it becomes slow with thousands, check only the page of results on screen.


- **Migrations.** Adopt Alembic once there is a database whose data must survive a schema change.

- **Trace across machines.** The trace compares paths as text. Add the site or host to the comparison once steps reach remote sites or agents on more than one machine.
- **Skip the rest when nothing was collected.** If a job's first step is allowed to find nothing, every later step that reads the same folder needs `AllowNoFiles` too. A step option to end the job successfully at that point would be tidier.
- **Delete step default.** When the delete step type is built, decide whether finding nothing to delete should succeed by default.
- **Retention.** A purge rule for `Operations`, which grows by one row per file.
- **Killed runs.** Pick up spool files left as `.jsonl.tmp` by a run that did not end normally, and mark the run accordingly.

7. **Runner uses the API.** Depends on decision 2.

8. **Security.** Encrypt `Credentials.SecretData`; stop returning `IsSecret` variables; API authentication; vault connectors. Needed before anyone other than the author uses it.

9. **Asynchronous processes.** Port the prototype's async instance tracking and polling.

10. **Dependency declaration.** Move dependencies from `requirements.txt` into `pyproject.toml` and make the project installable.

## Done

See [CHANGE_LOG.md](CHANGE_LOG.md).

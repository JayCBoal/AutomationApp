# To-Do

Updated 2026-10-13. The order under "Work queue" is a proposal; the items under "Decisions needed" are waiting on a choice.

## Decisions needed

1. **Sharing between related jobs.** With the process level removed, each job stands alone. Two things it used to provide need a replacement, if they are wanted:
   - Variables shared by several jobs. Proposal: tags (see decision 3).
   - A way to see several jobs as one piece of work. The file trace already follows a file from job to job, so this is only about grouping jobs for display. Proposal: a tag.

2. **How the runner gets its payload.** The design says agents pull over HTTPS from `/api/v1/jobs/init` and never connect to the database. The runner currently connects to the database directly. Options: switch the runner to the API now; support both; or leave direct access until the API has authentication.

3. **Tag rules.** Partly decided 2026-10-14:
   - **Hierarchy: decided.** A tag can have a parent, nested to any depth, and inherits its ancestors' variables. To confirm when building: a tag's own variable overrides one of the same name from its ancestors, as a job's overrides the cascade.
   - **Conflicts: decided for now.** When two tags on the same job (or two separate branches of tags) define the same variable, the pre-run check reports it as an error. No precedence rule.
   - **Open:** possibly later an optional setting on the job saying which tag wins. To come back to.

4. **Working folder.** Currently `<working root>/<JobKey>`, private to the job and reused by every run of it. Confirm, or make it per run. Also decide whether archive folders live inside it or are registered endpoints.

5. **Destination endpoints.** Should a delivery be checked against the destination endpoint's `FilenamePattern`, including after a rename mask has been applied?

6. **Prototype features.** Which of these carry forward: start at step, stop after step, skip steps; per-step success, warning and failure return codes; and a "use date" (business date) for date masks, which today always show the moment the run started?

7. **What "inside the scheduler" means first.** The goal is for AutoApp to be used from within a scheduling product. Decide the first integration target and its shape: for example, job definitions edited in the scheduler's interface through AutoApp's API, results written back to the scheduler's job log, and single sign-on. This raises the priority of the CRUD API relative to a standalone web interface.

8. **Repository housekeeping.** `AutomationApp/_gemini_debris/` and the zip files in `PriorArt/CodeRepo/backup/` can be deleted once no longer wanted.

9. **Leftovers from removing the process level.** Confirm that dropping `Jobs.Name` and `Jobs.ExecutionOrder`, and the mockup's Severity field, is acceptable.

Decided and removed from this list: telemetry direction (spool first, delivered through the API), the schema's source of truth (the Python models), what a file step does when nothing matches (fails unless `AllowNoFiles` is set), upper and lower case in names (case-sensitive everywhere), and the front end (static pages calling the API). See [CHANGE_LOG.md](CHANGE_LOG.md).

## Work queue

Ordered toward a demonstration: a job built in the job editor, run by a scheduler, and traced file by file. The job editor and the file trace are the two things to show.

### Next: more step types, for a fuller demonstration

Every page of the web interface is built. See [UI_VISION.md](UI_VISION.md) for what remains proposed.

1. **More step handlers.** Each one also adds a catalog entry, so it appears in the editor.
   - Delete files
   - SQL execution
   - SFTP transfer (this is what makes endpoints on remote sites usable)
   - REST call
   - Send email

### Then: tags

2. **Tags.** The rules are in decision 3. Tags are master objects already (`Tags`, with `TagAssignments` linking a tag to any master object); what is missing is the editing, the pages, and the `TAG` level in the variable cascade.
   - A job can share variables with other jobs through a tag, which replaces what the old process level gave.
   - Jobs, endpoints and the rest can be grouped and searched by tag.

### Then: breadth


3. **Runner controls.** Depends on decision 6.

4. **Scheduler integration.** Depends on decision 7.

### Later

- **Exact differences in the audit log.** Each audit row records who changed what, as sentences ("Changed step 2 ('Archive'): parameters."), but not the values before and after. Store a before-and-after list with each row (each field; each step's parameters; steps added, removed or moved; variables, except that a secret variable says only that it changed), and add "Show details" on the Audit Log page. Applies to changes made from then on.

- **Which variables a job can see.** A view listing every variable in reach of a job and where each comes from. Worth building once tags add a second source.


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

5. **Runner uses the API.** Depends on decision 2.

6. **Security.** Encrypt `Credentials.SecretData`; stop returning `IsSecret` variables; API authentication; vault connectors. Needed before anyone other than the author uses it.

7. **Asynchronous processes.** Port the prototype's async instance tracking and polling.

8. **Dependency declaration.** Move dependencies from `requirements.txt` into `pyproject.toml` and make the project installable.

## Done

See [CHANGE_LOG.md](CHANGE_LOG.md).

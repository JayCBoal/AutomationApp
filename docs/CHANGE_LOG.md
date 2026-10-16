# Change Log

Notable structural, schema and design changes to AutoApp, newest first. Line-by-line history is in git.

---

## 2026-10-16

### Headers that stay put, and tags' variables under Variables

- **Changed:** the page header and navigation stay at the top of the window while a page scrolls. On the Job Detail page and the other detail pages, the object's own header (its name and its Edit, Submit and other buttons) stays just under it.
- **Changed:** the Operations Log's search criteria scroll away with the page, and **Hide criteria** folds them to one line saying what is being searched for. The page remembers the choice for each viewer, and starts folded when a scheduler opens it.
- **Changed:** what an object's tags give it is listed in its Variables section, as "From its tags", instead of in the Tags section. On the Job Detail page the order follows priority: the job's own, then its tags', then the scheduler's. An endpoint, which has no variables of its own, gets a Variables section when its tags give it some. The preview of what a tag would give, before it is added, stays in the Tags section.
- **Changed:** the Unzip Files step's job log says "Unzipped 'name' from 'archive'" (was "Took 'name' out of 'archive'").
- **Changed:** the Stand-in Scheduler's window around RunMyFiles' pages has the stand-in's red bar and name, so the message there ("Saved in RunMyFiles: ready to run.") is clearly the stand-in's. The stand-in also keeps that message on its own page after the window closes.

## 2026-10-15

### AutoApp is now RunMyFiles

- **Changed:** the product's name, wherever people read it: the web interface, the Stand-in Scheduler's pages, the job log, messages, and the documentation. Entries below this one keep the old name, as they were written.
- **Kept:** the code's own names: the `autoapp` folder and Python package, the `AUTOAPP_...` environment variables, the database names, the JavaScript namespace `AutoApp`, and the `source: "AutoApp"` field of the messages to a WLA (part of the documented contract in [INTEGRATION.md](INTEGRATION.md)).
- **Changed:** the Run Job page runs jobs as the scheduler "RunMyFiles UI" (was "AutoApp UI").

### A RunMyJobs draft

- **Added:** [integrations/runmyjobs](../integrations/runmyjobs/README.md), from RunMyJobs' public documentation and untried:
  - a BASH job definition that runs the runner with the job's parameters in its environment;
  - an Extension Point adding an AutoApp tab to AutoApp job definitions, holding AutoApp's editor and passing its messages on to RunMyJobs;
  - an Extension Point opening AutoApp's files and log for a run.
- **Added:** the `RUNMYJOBS` connector, reading a job definition's parameters through the Inbound REST extension, written to Redwood's published specification and tested against a stand-in of it.
- **Added:** `log.html?job_key=...&instance_id=...`, a run's log found by the scheduler's own instance ID.
- **Changed:** [WLA_RESEARCH.md](WLA_RESEARCH.md) with what the RunMyJobs 2025.4 documentation and the Inbound REST specification say.

### An AutoApp job shown in the WLA's own screens

- **Added:** `GET /api/v1/jobs/{key}/summary`: a job described for a WLA to show: whether it would run and why not, its steps in a line each, its endpoints and tags, its latest run (or the one `instance_id=` names) and links to AutoApp's pages. It takes `scheduler=` and `wla_job=`.
- **Added:** `ui/summary.html`, the same as a small card, for a WLA that shows a page in a panel.
- **Added:** the Stand-in Scheduler's "In AutoApp" panel: the summary, asked by its server as a WLA plug-in would, with the last run's log a click away.

### The Stand-in Scheduler, and AutoApp reading a WLA job's parameters

- **Added:** [demo/scheduler_standin](../demo/scheduler_standin/README.md), a small WLA of its own, separate from AutoApp. It has job definitions with parameters, runs AutoApp jobs by starting the runner as an OS job, opens AutoApp's job editor and Operations Log embedded, and has an API.
- **Added:** connectors (`app/connectors/`), one per WLA technology, reading through the WLA's API; the first is for the stand-in (`STANDIN`). `GET /api/v1/schedulers/{name}/jobs/{wla_job}` gives a WLA job's parameters.
- **Added:** the job editor, opened with `scheduler=...&wla_job=...`, shows that WLA job's parameters under Variables ("From the scheduler", secrets masked), and its preview and pre-run check use them. `GET /api/v1/jobs/{key}/check` takes the same, and gives warnings.
- **Added:** the runner's `--mask-env` (or `AUTOAPP_MASK_ENV`): environment variables whose values are masked in the job log, for a WLA's secret parameters.
- **Added to the sample data:** the scheduler `STANDIN` at `http://localhost:8100`, with its token as the secret variable `ApiToken`.

### Pages a scheduler can show inside its own interface

- **Added:** embedded mode. With `embed=1` in its address, any page shows a thin bar ("Open in AutoApp") instead of the header and navigation, and its links stay embedded. `theme=light|dark` matches the host's look, and `host=<origin>` limits who receives its messages.
- **Added:** the job editor's messages to the window that opened it: `ready`, `saved`, `cancelled` and `deleted`, with the job key and, on a save, whether the job would run and what changed. Embedded, it shows only its own job, and a delete or a cancelled new job stays in place for the WLA to decide what comes next.
- **Added:** `job.html?new&key=...`, a new job with the key a WLA suggests.
- **Added:** [INTEGRATION.md](INTEGRATION.md): the runner's command line for a WLA, the addresses a WLA plug-in may rely on, embedded mode and the messages. `tests/test_ui_embedded.py` opens each address in a stand-in host page.

### What a run knows about its scheduler

- **Added:** the runner's `--business-date` (YYYY-MM-DD or YYYYMMDD), for schedulers that have one, such as Control-M's order date. Steps use it as `${BUSINESS_DATE:yyyyMMdd}`; without it, that is the date the run started. It is kept with the run (`JobRuns.BusinessDate`) and shown in Job History. The Run Job page can give one.
- **Added:** the environment as a variable level, `ENV`, at the lowest priority, and `${ENV:Name}` to name an environment variable. Schedulers put a job's own variables in the environment of the process they start, so AutoApp sees them without the scheduler passing them. On the server, where the scheduler's environment is unknown, `${ENV:...}` is left for the run rather than reported.
- **Added:** Scheduler as a master object (`Schedulers`): name, technology, API address, a secret variable for its credential. Search and detail pages; it can carry tags.
- **Decided:** AutoApp will read a WLA job's parameters from the scheduler (pull), with a connector per technology, rather than the WLA pushing them. It needs least from the WLA plug-in, and the connectors can be written and tested here. See TO-DO decision 7.
- **Migration:** `MasterObjects.ObjectType` gains `SCHEDULER`; add the `Schedulers` table and `JobRuns.BusinessDate`. `autoapp_dev` has them.

### Running jobs from the web interface, and keeping job logs

- **Added:** the job log is kept with each run. The runner sends its lines, secrets already masked, as `LOG` records after the run starts, after each step and at the end; they are stored in the new `JobRunLogs` table. `GET /api/v1/runs/{run_id}` gives a run with its log.
- **Added:** a Job Log page, and a Log link on every row of Job History. Runs from before this change have no log.
- **Added:** the Run Job page and `POST /api/v1/launches`. The server starts the real runner as a separate process, as a scheduler would, with "AutoApp UI" as its scheduler, and the page follows the run's log as it goes. The job editor has a Run button.
- **Added:** the runner's `--run-id`, used by the Run Job page so it can follow the run it started. A scheduler leaves it out.
- **Changed:** the runner sends its records as soon as the run starts, not only after the first step, so a run shows as running at once.
- **Decided:** scheduler integration is put off, as there is no WLA software to try it against. The user's thoughts on it are recorded in TO-DO decision 7.
- **Migration:** add the `JobRunLogs` table (see `SQL/Create_Tables.sql`). `autoapp_dev` has it.

### Tags

- **Changed:** `Tags` has a parent (`Parent_MasterObject_id`), nested to any depth, and `Name` in place of `TagName`. Names are unique under one parent, so a tag is named by its path, `Finance/Reporting`. `Category` is dropped.
- **Added:** tag variables in the variable lookup (`engine/tag_vars.py`, `engine/scope_engine.py`). A tag's variables act as if they were on whatever carries it, just below its own; a tag inherits its parents'. A job's tags feed the job; an application's, entity's or endpoint's tags feed that endpoint's path and pattern.
- **Added:** conflicts. Two tags on one object giving one variable different values: an error if the variable is used (and nothing higher settles it), a warning in the job editor if not. Messages name the tags, not the values.
- **Added:** `${TAG:Finance/Reporting.Var}`, limited to the job's tags and their parents.
- **Added:** the `Settings` table and `engine/settings.py`; the first setting is `VariablePrecedence`, by default `SYS, ENTITY, APP, ENDPOINT, TAG, JOB`.
- **Added:** tags in the API: `/api/v1/tags` (search, view, register, change, move, delete), a `tags` list on every other kind and on jobs, a `tag` criterion on every search, `GET /api/v1/tag-variables`, and `/api/v1/settings`. Renaming or moving a tag rewrites the `${TAG:...}` references to it.
- **Added:** Tag Search and Tag Detail pages; a Tags panel on every other detail page and the job editor, which shows a tag's variables and any conflict before it is added; a Tag box and a Tags column on every search page; the Settings page.
- **Changed:** the sample data's tags: `Environment / DEV`, `Legal`, and `Finance / Reporting`, whose parent's `ReportRetentionDays` the finance job now uses.
- **Migration:** `autoapp_dev` was changed in place (backup in `demo/output/autoapp_dev_before_tags.sql`). Another database needs the `Tags` columns changed and the `Settings` table added, or rebuilding.

---

## 2026-10-14

### More step types: Delete, Check, Zip, Unzip and Run SQL

- **Added:** step types `DELETE_FILES`, `CHECK_FILES`, `ZIP_FILES`, `UNZIP_FILES` (`engine/handlers/file_tools.py`) and `RUN_SQL` (`engine/handlers/sql_handler.py`). See the blueprint, section 5.
- **Added:** operation types `DELETE`, `CHECK`, `ZIP`, `ZIP_MOVE`, `UNZIP`, `SQL` and `SQL_EXPORT`. A check or a delete has no destination side; the operations log says "Left where it was" or "Deleted" there, and the source of a query's CSV is shown as the database, without its password.
- **Changed:** the file trace ends a route at a delete, treats the files one step zipped into one archive as one write of it, and follows each file out of the archive through its own unzip.
- **Added:** parameter type `TEXT`, a string of several lines, shown in the job editor as a growing box.
- **Decided:** Delete Files, like the other file steps, fails when nothing matches unless `AllowNoFiles=True`. This settles the open "delete step default" item.
- **Decided:** Run SQL rolls back unless `Commit=True`, and the database's password is hidden everywhere it could appear. A Connections table is left for later; for the demo a database is a URL in a secret variable.
- **Added:** `SQL/Sample_Sales_Data.sql`, a portable sample sales database (customers, invoices, invoice lines, payments). `create_dev_db.py` builds it as SQLite at `/tmp/autoapp_sample/sales.db`. On MariaDB it is `autoapp_sales`.
- **Added to the sample data:** application `FINANCE_APP`, endpoint `FINANCE_APP_INBOX`, a secret variable `SalesDbUrl` on `BILLING_APP`, and two jobs:
  - `DEV-BILLING-INVOICE_EXPORT`: exports open invoices and payments to CSV, checks there are two, and zips them to finance.
  - `DEV-FINANCE-LOAD_REPORTS`: picks up the archive, unpacks it, checks the reports, keeps the archive and removes archives over 30 days old.
- **Migration:** none for the schema. `autoapp_dev` was given the new sample rows in place, with `SalesDbUrl` pointing at `autoapp_sales`.

### Endpoints are master objects

- **Changed:** `Endpoints` is a subtype of `MasterObjects`, like applications, entities, sites, credentials, tags and jobs. Its key is `MasterObject_id`; `Operations.SourceEndpoint_id` and `DestEndpoint_id` refer to it.
- **Rationale:** an endpoint is a definition like the others. As a master object it has a created date and who created it, its audit rows link to it, and it can hold variables and tags once those are wired up for it.
- **Checked:** no other table should be a master object. Steps, parameters, variables and tag assignments belong to something else; the step catalog comes from the code; runs, operations and audits are records.
- **Migration:** a database built before this needs rebuilding. `autoapp_dev` was migrated in place, keeping its data.

### The rest of the web interface

- **Added:** search and detail pages for applications, entities, sites and endpoints. One page of each kind serves all four, drawn from a description of each in `definitions.js`.
- **Added:** `GET`, `PUT` and `DELETE` on `/api/v1/applications`, `/entities`, `/sites` and `/endpoints`, sharing one implementation in `app/registry_store.py`.
- **Decided:** something still in use cannot be deleted: an application or site an endpoint belongs to, an entity that owns a site, an endpoint a job step names. History is not "use": an endpoint that only past operations mention can be deleted, and those operations keep its path.
- **Decided:** renaming an endpoint renames it in every job step that names it.
- **Added:** the Job History page (`GET /api/v1/runs`) and the Audit Log page (`GET /api/v1/audits`).
- **Decided:** a "New" button opens the full detail page, blank, rather than a small window, so variables and the active flag can be set at the same time. The small windows are kept for registering something from within another form.
- Every page in the navigation is now built.

---

## 2026-10-13

### Job Detail page, first slice: viewing a job

- **Added:** `GET /api/v1/jobs/{job_key}`, one job with all its steps and their parameters as stored.
- **Added:** the Job Detail page. It shows a job and its steps, with each step's form drawn from the step catalog. Nothing on it can be changed yet.
- **Changed:** on the Job Search page the job key links to the Job Detail page, there is a View link, and a disabled job shows "Disabled" in grey with no Check link.

### Job editor, fourth slice: variables and preview

- **Added:** a job's own variables in `GET`, `POST` and `PUT /api/v1/jobs`, and a Variables panel in the job editor.
- **Added:** `POST /api/v1/jobs/preview`, and a live preview in the editor: where each file location really is, what each value with a placeholder resolves to, and whether the job as it is on screen would run.
- **Added:** "Add variable ..." beside a value that names a variable the job does not have.
- **Decided:** a secret variable's value is never sent to the page. The page shows a blank box, and a blank box on save keeps the value there is.
- **Decided:** a variable's name is letters, digits and underscores, starting with a letter or underscore, so that `${Name}` can never be mistaken for one of the scoped forms such as `${SYS:...}` or `${APP.Name}`.
- **Decided:** the audit log names the variables a save changed, never their values.
- **Rationale for the preview's design:** it applies the save inside a transaction, resolves with the runner's own code, and rolls back. A separate "preview" calculation would sooner or later disagree with the real one.

### Job editor, third slice: registering an endpoint in place

- **Added:** `POST /api/v1/endpoints`, which registers an endpoint and writes an audit row.
- **Added:** a "New..." link beside each endpoint box in the job editor, opening a form to register an endpoint without leaving the page. The new endpoint is put into the box it was opened from.
- **Decided:** the endpoint is created when its form is submitted, not when the job is saved. An endpoint is a definition in its own right, shared by any job that names it.
- **Decided:** an endpoint's name follows the same rule as a job key: letters, digits, hyphens, underscores and full stops.
- **Added:** `POST /api/v1/applications`, `/entities` and `/sites`, each writing an audit row.
- **Added:** "New..." on the Application and Site boxes of the New endpoint window, and on the Entity box of the New site window. One mechanism in `common.js` draws all four windows, and they open from one another.
- **Decided:** as a rule for the whole interface, a box for choosing something to use can register a new one on the spot.

### Rename masks and date masks

- **Added:** `RenameMask` on the copy step, with `${FILE:NAME}`, `${FILE:STEM}` and `${FILE:EXT}`. It is a parameter of its own, not the filename part of `Dest` as in the prototype, so it works when the destination is an endpoint.
- **Added:** `${DATE:mask}`, with .NET-style mask letters as in the prototype: `${DATE:yyyyMMdd_HHmmss}`.
- **Changed:** the samples use `${DATE:yyyyMMdd}`. `${SYS:YYYYMMDD}` still works, but it was never a mask, only a fixed name, and there was no way to ask for any other format.
- **Rationale:** capital `MM` for months and small `mm` for minutes is the only way one mask can hold both. A mask in the wrong case is refused, because guessing would put the wrong date in a filename.

### Job editor, second slice: editing and saving

- **Added:** `POST /api/v1/jobs`, `PUT /api/v1/jobs/{job_key}` and `DELETE /api/v1/jobs/{job_key}`. A job is saved whole, with its steps in the order they run.
- **Added:** the Job Detail page can be unlocked with Edit and saved with Submit. Steps can be added, removed, reordered, retitled and enabled or disabled; parameters are edited through the forms drawn from the step catalog.
- **Added:** New job, renaming with a warning, and Delete job.
- **Added:** every create, change and delete of a job writes a row to `Audits` saying what changed.
- **Decided:** a job is saved even if the pre-run check finds problems with it. The problems are shown after the save, and the job will not run until they are fixed. Refusing the save would stop someone saving half-finished work.
- **Decided:** a step keeps its identity when it is edited or moved, so the operations it has recorded stay linked to it. Removing a step keeps its operations, without the link.
- **Changed:** SQLite now enforces foreign keys. Before, deleting a step on SQLite left its parameters behind, where MariaDB removed them.

### Endpoint drop-down, and Operations Log criteria

- **Added:** `GET /api/v1/endpoints`. In the job editor, each endpoint box offers the registered endpoints as a drop-down, narrowed by what is typed.
- **Decided:** every box that names something registered elsewhere (an endpoint, application, entity, site, job or scheduler) offers a drop-down of what there is. Added to the search boxes on the Operations Log and Job Search, through one mechanism in `common.js` and one route, `GET /api/v1/lookups`.
- **Changed:** on the Operations Log, Application, Entity and Site are searched on the source and the destination separately, in those boxes, not "on either side".
- **Added:** Scheduler as a search criterion on the Operations Log, shown on each row and each hop of a trace.
- **Fixed:** a copy step whose `Dest` named a single file, but whose source matched several, copied each file over the last and recorded them all as delivered. It now fails before copying anything.
- **Added:** when the server refuses a request it does not know, the page says the server may need restarting.

### An out-of-date database explains itself

- **Added:** when the server starts, and whenever a database error occurs, the database's tables are compared with what this version expects. Anything missing is named in the server log and in the error the page shows.
- **Rationale:** a development database built before the step catalog columns existed answered "Internal Server Error" on the Job Detail page, with nothing to say why.

### Job Search page

- **Added:** `GET /api/v1/jobs`, the job search, returning each job with its step counts, the endpoints it uses and its most recent run.
- **Added:** the Job Search page, with a Check link that runs the pre-run check on a job and an Operations link to that job's operations.
- **Added:** the search puts every job it returns through the pre-run check. A job that would run shows "Ready to run" in green; one that would not has a bold red "Check" link that lists what is wrong.
- **Changed:** the behaviour every search page shares moved into `common.js`, and the Operations Log now uses it.
- **Decided:** no Step Types page. Step types are seen in the job editor.
- **Decided, for the job editor:** one Submit saves the whole job; a JobKey can be renamed, with a warning; a job with run history is disabled, not deleted; when two people edit the same job, the last save wins.

### Step catalog and checking

- **Added:** each handler declares its parameters in the code: name, type, required, default and description.
- **Added:** `StepDefinitions.DisplayOrder`, `LocationRole` and `AllowedValues`.
- **Added:** `app/catalog.py`, which copies the declarations into the catalog tables when the API server starts.
- **Added:** `GET /api/v1/step-types` (the catalog) and `GET /api/v1/jobs/{job_key}/check` (check a job without running it).
- **Changed:** a job is checked as a whole before its first step runs, and every problem is reported at once. Before, a mistake in step 3 was found only after steps 1 and 2 had moved files.
- **Changed:** a parameter name the step type does not have is now an error. Before, a misspelt name such as `Mvoe` was silently ignored, so the step ran as a copy.
- **Changed:** a value of the wrong type, such as `Move=perhaps`, is now an error. Before, anything other than true, 1 or yes was quietly treated as false.
- **Changed:** handlers receive converted values with defaults filled in. `/api/v1/jobs/init` returns the same.
- **Removed:** the `FILE_OP` alias for `COPY_FILES`, and the parameter definitions from the sample data script, which the code now supplies.
- **Rationale:** the job editor needs to know what form to draw for each step type, and one declaration should drive the form, the check and the handler, so they cannot disagree.

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

### Web interface: first pages

- **Decided:** the web interface is static pages (HTML, CSS, plain JavaScript and the small Alpine.js library) that call the REST API, with no build step.
- **Added:** `autoapp/ui/`, served by the API server at `/ui/`: the Main Index and the Operations Log, with the file trace and CSV export.
- **Added:** dark theme by default, light theme as an option.
- **Added:** search criteria on `GET /api/v1/operations`: source and destination endpoint, path and filename separately; application, entity and site on either side; operation type.
- **Added:** browser tests, which drive the page in headless Chromium against a real server.
- **Changed:** the telemetry route refuses a value that is too long for its column, with a message naming the field. Before, SQLite stored it and MariaDB failed with a database error.
- **Rationale:** static pages need nothing compiled, can be opened and edited directly, and depend only on the API, so they would survive the back end being ported to another language.

### MariaDB

- **Verified:** `SQL/Create_Tables.sql` and `SQL/Seed_Sample_Data.sql` run on MariaDB 11.8, and the whole test suite passes against it.
- **Added:** the tests run against a server database when `AUTOAPP_TEST_DATABASE_URL` is set. The tables are built from `SQL/Create_Tables.sql`.
- **Changed:** run and operation times are `DATETIME(6)` on MariaDB. With whole seconds, the trace put operations from different runs in the wrong order when their spool files were loaded out of sequence.
- **Changed:** `Operations` paths and filenames use an exact (case-sensitive) comparison on MariaDB. With its default, the trace treated `Legal_Batch_A.csv` and `Legal_Batch_a.csv` as one file.
- **Added:** `pymysql`, the MariaDB driver, to the requirements.
- **Changed:** `create_dev_db.py` sends the sample data script to the database exactly as written.

### Names are case-sensitive

- **Decided:** names are case-sensitive on every database, as in RunMyJobs. `DEV-LOAD` and `dev-load` are different job keys.
- **Changed:** every table uses the `utf8mb4_bin` collation on MariaDB, declared once in the models. Before, MariaDB ignored case in names while SQLite and the variable resolver did not, so the same job definitions behaved differently depending on the database.
- **Changed:** this replaces the per-column setting added for `Operations` paths and filenames earlier the same day.
- **Unchanged:** searching the operations log ignores case.

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

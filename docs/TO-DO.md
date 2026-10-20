# To-Do

Updated 2026-10-13. The order under "Work queue" is a proposal; the items under "Decisions needed" are waiting on a choice. Long-term features (security and permissions, credentials, alerting, hosting) are in [ROADMAP.md](ROADMAP.md).

## Decisions needed

1. **Sharing between related jobs.** With the process level removed, each job stands alone. Two things it used to provide need a replacement, if they are wanted:
   - Variables shared by several jobs: tags, built 2026-10-15 (decision 3).
   - A way to see several jobs as one piece of work. The file trace already follows a file from job to job, so this is only about grouping jobs for display. A tag, and Job Search's Tag box, now do this; still open is whether a page showing such a group together is wanted.

2. **How the runner gets its payload.** (Also, 2026-10-18: a job runner with no API to report to keeps its records, its process ID included, in its spool file until they are delivered, so until then its run is not in the database and cannot be killed from the page. Jobs in a workflow do not have this gap: the workflow runner records each job's process as it starts it.) The design says agents pull over HTTPS from `/api/v1/jobs/init` and never connect to the database. The runner currently connects to the database directly. Options: switch the runner to the API now; support both; or leave direct access until the API has authentication.

3. **Tag rules.** Decided 2026-10-14 and built 2026-10-15, unless marked open:
   - **What can be tagged:** any master object.
   - **What a tag gives:** its variables act as if they were on the tagged object, just below that object's own. A job's tags feed the job; an application's or entity's tags feed wherever that object's variables reach (an endpoint's path and pattern); an endpoint's tags feed the endpoint.
   - **Hierarchy:** a tag can have a parent, nested to any depth, and inherits its ancestors' variables. A tag's own variable overrides one of the same name from its ancestors.
   - **Names:** unique under one parent, not across all tags. A tag is always shown with its path, e.g. `Environment / TEST`. A parent tag earns its place by carrying variables its children share, or simply by making a child's name clear (`Environment / TEST` and `Purpose / TEST` are different tags). Names cannot contain `/`.
   - **Category column:** dropped. Nothing used it; parent tags do the same job.
   - **Precedence:** by default system values, then application and entity, then tags, then the job's own variables. The order is a system-wide setting (see the Settings table, below).
   - **Conflicts:** when two tags give the same variable different values, and the object does not define it itself, it is an error before the job runs if the job uses the variable, and a warning in the editor if it does not. The same value from two tags is not a conflict, nor is one tag reached through two paths.
   - **Explicit references:** `${TAG:path.Var}` may name only a tag the job carries, or an ancestor of one. *To reconsider later:* allowing any tag, as a system-wide setting, with the tag's "used by" list showing jobs that name it.
   - **Changes:** a tag cannot be made its own ancestor; a tag with child tags or assignments cannot be deleted; adding or removing a tag is audited on the object.
   - **Pages:** tag search and detail pages; a tags box on every detail page whose picker shows the tag's own and inherited variables (secrets masked) and warns of conflicts before it is added; a Tag filter on every search page that includes child tags; inherited variables shown in a job's variables panel with where each comes from.
   - **Open:** an optional setting on the job saying which tag wins. Later: a parent marked "pick one", so a job cannot carry two of its children (e.g. both `Environment / DEV` and `Environment / PROD`).
   - **Settings table:** settings are declared in the code (name, type, default, allowed values, description), like the step catalog; the `Settings` table holds only the values changed from the default (`SettingKey`, `SettingValue`, when and by whom), and every change is audited. A Settings page is drawn from the declarations. Settings are not variables and cannot be read with `${...}`.

4. **Working folder.** Currently `<working root>/<JobKey>`, private to the job and reused by every run of it. **Decided 2026-10-19 (D116): it stays named by the key**; renaming warns and can move the folder. Still open: make it per run? Also decide whether archive folders live inside it or are registered endpoints.

5. **Destination endpoints.** Should a delivery be checked against the destination endpoint's `FilenamePattern`, including after a rename mask has been applied?

6. **Prototype features.** Which of these carry forward: start at step, stop after step, skip steps; per-step success, warning and failure return codes; and a "use date" (business date) for date masks, which today always show the moment the run started?

7. **What "inside the scheduler" means first.** The goal is for RunMyFiles to be used from within a scheduling product. Decide the first integration target and its shape: for example, job definitions edited in the scheduler's interface through RunMyFiles' API, results written back to the scheduler's job log, and single sign-on. This raises the priority of the CRUD API relative to a standalone web interface.
   - **Picked up again (2026-10-15).** Redwood owns RunMyJobs, ActiveBatch and Tidal, so dev or demo tenants may be possible. RunMyJobs' extensibility is ExtensionPoints, plug-ins written in RedwoodScript; any work on one has to come from the public documentation.
   - **Plan, in order:**
     1. Run context. *Built 2026-10-15:* `--business-date` and `${BUSINESS_DATE:...}`, the environment as the lowest variable level and `${ENV:Name}`, and Scheduler as a master object.
     2. An embedded mode for the pages a WLA opens, and the addresses a WLA plug-in may rely on, written down and tested. *Built 2026-10-15:* see [INTEGRATION.md](INTEGRATION.md).
     3. Pull: the editor, opened from a WLA job, reads that job's parameters from the scheduler through a connector, shows them read-only in its Variables panel ("from the scheduler", secrets masked), and the pre-run check uses them. At run time, parameters the WLA marks secret are masked in the job log. *Built 2026-10-15.*
     4. A scheduler stand-in: a separate small app with its own look, API and database, standing in for a WLA, with the first connector. *Built 2026-10-15:* [demo/scheduler_standin](../demo/scheduler_standin/README.md).
     5. The other direction: a RunMyFiles job shown in the WLA's own screens. *Built 2026-10-15:* `GET /api/v1/jobs/{key}/summary` and `ui/summary.html`, shown by the stand-in.
     6. Research from public documentation, in [WLA_RESEARCH.md](WLA_RESEARCH.md) (2026-10-15): RunMyJobs Extension Points can add a RunMyFiles tab to job definitions' edit pages and act before a save; its Inbound REST extension reads job definitions. Control-M's Automation API reads job definitions with their variables. Each has a list of what to confirm on a real system.
     7. A RunMyJobs draft, from its public documentation (2026-10-15): [integrations/runmyjobs](../integrations/runmyjobs/README.md), with the BASH job definition that runs the runner, an Extension Point adding a RunMyFiles tab to job definitions, one opening RunMyFiles' files and log for a run, and RunMyFiles' `RUNMYJOBS` connector. Untried; what to confirm is listed there.
     8. Next: a connector for a real WLA, once there is one to try it against (a RunMyJobs, ActiveBatch or Tidal dev tenant), and a WLA plug-in (for RunMyJobs, an ExtensionPoint) that opens RunMyFiles' pages.
   - **Decided:** what the scheduler gives a run: the business date (optional, for Control-M), its job name, its instance ID, the restart count, and which scheduler it is (name and technology). The job's own variables come through the environment, as ActiveBatch, Control-M and RunMyJobs all set them there for an OS job; the runner does not need to tell them apart from the rest of the environment.
   - **Requirement:** RunMyFiles should gather everything the source WLA job has and be able to map all of it. Control-M must be order-date aware.
   - **Decided:** pull, not push. Reading the WLA job's parameters through the scheduler's API needs least from the WLA plug-in (only to open RunMyFiles' page with the job's identifier), and the connectors live in RunMyFiles, where they can be built and tested. The costs: RunMyFiles needs network access to each WLA, and holds a credential for each.
   - **The user's thoughts so far (2026-10-15), for when this comes back:**
     - In the WLA's own job editor, creating or editing a job of the RunMyFiles type (whatever it ends up being called) opens RunMyFiles' Job Detail page.
     - Ideally the integration goes both ways, so that the RunMyFiles job's attributes are visible in the host WLA's interface. Whether that is feasible is not known yet.
     - Most other pages only need to be reachable from the standalone RunMyFiles interface, as they are used less often.
     - The exception is the Operations Log, seen as RunMyFiles' stand-out feature: reaching it from inside the host WLA's interface is a must.

8. **Repository housekeeping.** `AutomationApp/_gemini_debris/` and the zip files in `PriorArt/CodeRepo/backup/` can be deleted once no longer wanted.

9. **Leftovers from removing the process level.** Confirm that dropping `Jobs.Name` and `Jobs.ExecutionOrder`, and the mockup's Severity field, is acceptable.

Decided and removed from this list: telemetry direction (spool first, delivered through the API), the schema's source of truth (the Python models), what a file step does when nothing matches (fails unless `AllowNoFiles` is set), upper and lower case in names (case-sensitive everywhere), and the front end (static pages calling the API). See [CHANGE_LOG.md](CHANGE_LOG.md).

10. **Telemetry: Job History apart from the operations audit trail** (the owner, 2026-10-18; important, not a workflow topic).
    - **The principle:** "Telemetry must be recorded, but it must not harm the job's core purpose or performance." The operations log is an audit trail, asynchronous by design (as first agreed, before the work came from Gemini): it need not be real-time, and every second counts where jobs are many and short. Job History (a run's start, end, status, return code, process ID) is core scheduling-engine data, which schedulers, workflows and Reactions act on.
    - **How it works now (found 2026-10-18):** one pipeline carries both. The runner writes every record to its spool file, then posts the new ones through the API after each step and at the end, waiting up to 5 seconds each time for the server to commit them, so a slow or unreachable server holds a job up. A run's end reaches Job History only in the same batch as its operations. Without an API, `engine.spool_delivery` and the workflow runner (`_load_spool`, when a job's end has not arrived) load spool files into the database themselves. Nothing runs the sweep periodically.
    - **Direction:** Job History reported promptly on a small path of its own; operations sent in the background or by a periodic sweep, never holding up a step; the runner never writes the database itself, since in production it runs on the scheduler's agent hosts; the workflow runner learns a job's outcome from Job History alone.
    - **For workflows:** not needed to finish the phases (the demonstrator runs everything on one machine), but no workflow feature may depend on the operations records. Phase 4's `FileCount` and `Bytes` come with the job's own end report; Phase 4b's Operations object and For Each File over an upstream job's files are to be reconsidered ([WORKFLOWS_PHASE4.md](WORKFLOWS_PHASE4.md)).
    - **Related:** decision 2 (the runner using the API), "Killed runs" below, and agents. Handed to the roadmap planning session for [ROADMAP.md](ROADMAP.md) (2026-10-18).

## Work queue

Ordered toward a demonstration: a job built in the job editor, run by a scheduler, and traced file by file. The job editor and the file trace are the two things to show.

### Where things stand (2026-10-16)

- **The demonstration is ready.** `demo/demo.py setup` and `start` build and run a clean demo, and [demo/DEMO.md](../demo/DEMO.md) is the 30-minute walkthrough.
- **The presenter deck:**
  - a Slides artifact, private until shared: https://claude.ai/artifact/KnzHsGAV14Btnwpo3RxqWL;
  - an offline copy, `demo/output/RunMyFiles_presenter_deck.html`, rebuilt from `demo/output/deck_build/`.
  - A trimmed version without speaker notes is still to make, for Product Management after the pitch.
- **The pitch statements** are in a Claude Doc, "RunMyFiles pitch statements".
- **The name** "RunMyFiles" holds until something better comes along. "Waypoint" is the alternative, and needs a trademark search.
- **Next for the integration:** confirm the RunMyJobs draft on a dev tenant (its TO CONFIRM list is in [integrations/runmyjobs/README.md](../integrations/runmyjobs/README.md)). A Control-M connector is now possible from BMC's sample formats.
- **SFTP** (item 1 below) has a plan:
  - an in-process asyncssh SFTP server for the tests;
  - a "partner bank" SFTP script for the demo.
  - It needs `asyncssh` or `paramiko` installed: ask first.

### Next: more step types, for a fuller demonstration

Every page of the web interface is built. See [UI_VISION.md](UI_VISION.md) for what remains proposed.

- **Check Files: minimum age and waiting** (decided 2026-10-17). New parameters: `MinAgeSeconds` (only files unchanged for at least this long count; empty for any age), `WaitMinutes` (keep checking for up to this long before failing; empty for no wait, as now) and `CheckEverySeconds` (default 30). The job log says what it is waiting for ("2 of 3 files are old enough; checking again in 30 seconds") and why it stopped. The same minimum age serves workflow prerequisites on endpoints ([WORKFLOWS.md](WORKFLOWS.md)). A While around Check Files can wait already; this makes the common case simple.

1. **More step handlers.** Each one also adds a catalog entry, so it appears in the editor. Delete, Check, Zip, Unzip and Run SQL are built; still to come:
   - SFTP transfer (this is what makes endpoints on remote sites usable)
   - REST call
   - Send email

### Next: the scheduler integration

2. **Scheduler integration.** Decision 7 holds the plan and the user's thoughts; [INTEGRATION.md](INTEGRATION.md) what a WLA plug-in can rely on. Steps 1 to 4 are built: run context, embedded mode and the documented addresses, reading a WLA job's parameters, and the Stand-in Scheduler. Next is a real WLA, when one is available.

### Done: flow control (2026-10-17, from RunMyFiles)

Designed with the owner and built in RunMyFiles on 2026-10-16, then brought over: [FLOW_CONTROL.md](FLOW_CONTROL.md). If/Else If/Else, For Each File and While; step outputs read as `%{StepName.Output}`; conditions written as a SQL `WHERE` clause; On failure; the sample export job uses them. Next, when wanted:

- **A general For Each:** over the rows of a Run SQL step's result, or a list of values, with SQL row outputs to feed it.
- **Break and Continue** steps inside loops.
- **The presenter deck** still describes the export job's four steps; the walkthrough in DEMO.md is up to date.
- **`POST /api/v1/jobs/init`** (the runner's payload, decision 2) still lists steps flat, without their nesting. It is used by nothing yet; it needs the tree when the runner switches to the API.

### Then: workflows

- **A workflow object type:** a set of jobs with dependencies between them, designed and run in AutoApp. It answers the RunMyJobs job-chain shortcomings listed in [PROJECT_GOALS.md](PROJECT_GOALS.md) goal 2. Being designed: the starting point, decisions and open questions are in [WORKFLOWS.md](WORKFLOWS.md).

- **Reactions for every job, not only in workflows** (raised 2026-10-17): reacting to a job not started or not ended by a time, or running longer than a threshold, as well as to how it ended; one user-friendly mechanism in place of an SLA feature separate from job statuses, as RunMyJobs has. Designed with workflows in [WORKFLOWS.md](WORKFLOWS.md) (Reactions); a job that runs on its own needs it too.

### Then: breadth

3. **Runner controls.** Depends on decision 6.

### Later

- **AutoApp as a SaaS application** (the owner, 2026-10-18; long-term, not a workflow topic). It would fit RunMyJobs better, and may change the billing question (WORKFLOWS.md, "Jobs may still run on their own"). Builds on API authentication and the rest of item 6 (Security), and on runners using the API (decision 2). The plan, in three steps (a hosted demo first, true SaaS last): [HOSTING.md](HOSTING.md).

- **Exact differences in the audit log.** Each audit row records who changed what, as sentences ("Changed step 2 ('Archive'): parameters."), but not the values before and after. Store a before-and-after list with each row (each field; each step's parameters; steps added, removed or moved; variables, except that a secret variable says only that it changed), and add "Show details" on the Audit Log page. Applies to changes made from then on.

- **Which variables a job can see.** A view listing every variable in reach of a job and where each comes from. The Job Detail page's Variables section now lists the job's own variables, its tags' and the scheduler's, in that order. Still missing: the application, entity and site variables its endpoints bring, and the order setting applied to all of them.


- **A placeholder in a tick-box parameter.** A true-or-false parameter stored as `${...}` is shown as text and can be edited, but the editor offers no way to switch a tick box to a placeholder. Add a "use a variable" switch.
- **Duplicate a job**, to start a new job from an existing one.
- **Who made a change.** Audit rows say "web interface" until there are user accounts.

- **Job search speed.** The search checks every job it returns, which is fine for hundreds of jobs. If it becomes slow with thousands, check only the page of results on screen.


- **Migrations.** Adopt Alembic once there is a database whose data must survive a schema change.

- **Trace across machines.** The trace compares paths as text. Add the site or host to the comparison once steps reach remote sites or agents on more than one machine.
- **Skip the rest when nothing was collected.** If a job's first step is allowed to find nothing, every later step that reads the same folder needs `AllowNoFiles` too. A step option to end the job successfully at that point would be tidier.
- **Connections.** A table of registered databases and servers (type, host, port, database, a credential), named by a step instead of a connection URL in a secret variable. Needed for a production-ready application; for the demo, Run SQL's `Database` is a URL in a secret variable.
- **Run SQL: more than one statement, and bound values.** One statement per step for now, with values put in by `${...}` placeholders. A script of several statements, or values passed safely as bound parameters, would come with the Connections work.
- **Retention.** A purge rule for `Operations`, which grows by one row per file.
- **From workflows Phase 3 (2026-10-18), not needed for workflows:**
  - **A Script step:** a script in one of several languages (Bash, CMD, PowerShell, Python…), its exit code the job's return code, making the step library user-extensible. Needs: which languages, where it runs, limits on what it may do on the host.
  - **A Reaction's When as an expression**, combining a return code with other outputs (`%{Load.ReturnCode} IN (4, 8) AND %{Load.FileCount} = 0`), in flow control's condition language.
  - **Hold for an operator** as a Reaction: pauses the workflow at a job; a first version needs only **Release**.
- **From workflows Phase 4 (2026-10-18):**
  - **Resizable panes elsewhere** (the owner: basic, and turns out to be needed). The workflow page's job pane can be resized by dragging its edge; others could follow where content is cramped: the diagram's height, the job editor's step list, the Operations Log's columns.
  - **Kill recorded as an error under load.** Once, in a full SQLite run, a job killed through the API was recorded Failed, `ERROR` instead of `KILLED` (test_reactions_api, Kill and Cancel); it passed when run again. Probably the kill arriving before the job runner had set up its handler for it. Worth a look before Kill is shown off.
  - **Explain for a step's condition in the job editor**, against a past run's values, if wanted: the job log already says what each condition used.
- **Killed runs.** Pick up spool files left as `.jsonl.tmp` by a run that did not end normally, and mark the run accordingly.

5. **Runner uses the API.** Depends on decision 2.

6. **Security.** Encrypt `Credentials.SecretData`; stop returning `IsSecret` variables; API authentication; vault connectors. Needed before anyone other than the author uses it.

7. **Asynchronous processes.** Port the prototype's async instance tracking and polling.

8. **Dependency declaration.** Move dependencies from `requirements.txt` into `pyproject.toml` and make the project installable.

9. **Loops across workflows.** A "Rerun workflow" Reaction with a required limit, so workflow A can run again after workflow B finishes, at most N times. Prerequisites between workflows may not form a cycle (D104); this is the way to repeat across them. Raised in Phase 5 planning, 2026-10-19.

10. **A flaky test: `test_kill_and_cancel_on_a_workflow_and_kill_on_one_of_its_jobs`** (tests/test_reactions_api.py). On SQLite it fails about half the time when run on its own (the job ends `ERROR` instead of `KILLED`), on the code before workflow variables too (5 failures in 12 runs there, 6 in 12 after); it mostly passes inside the full suite. A race between the kill and the job's start. Found 2026-10-19.
11. **A workflow waited for as a whole shows no "Needed by".** A job in another workflow that waits for a whole workflow (not one of its jobs) is not listed on that workflow's page or drawn on its diagram; only waits for one of its jobs are (Phase 5, D80). Found 2026-10-19.

## Done

See [CHANGE_LOG.md](CHANGE_LOG.md).

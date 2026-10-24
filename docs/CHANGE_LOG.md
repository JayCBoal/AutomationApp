# Change Log

Notable structural, schema and design changes to AutoApp, newest first. Line-by-line history is in git.

---

## 2026-10-24

### Runner separation, Phase A: the `core` package

Plan: [RUNNER_SEPARATION.md](RUNNER_SEPARATION.md). No behaviour changes: pages, API responses and the database are as before.

- **Changed:** a third package, `autoapp/core`, holds what the server and the runners share: the tables and database setup (`models.py`, `database.py`, moved from `app`), the step handlers, step catalog, variables, conditions, reopen rules, the job log and control file, the telemetry client and spool transport (`core/spool.py`), the alert outbox, and the pre-run check (`core/pre_run_check.py`, with `job_problems` and `workflow_problems`, moved out of the jobs router and the workflow store). Picking up an earlier attempt (`core/earlier_attempt.py`) moved out of the runner.
- **Rule:** `core` imports neither `app` nor `engine`; `app` and `engine` never import each other. `tests/test_package_boundaries.py` checks it.
- **One exception, to go in Phase B:** the delivery command's no-API path (`engine/spool_delivery.py`) still loads records through `app.telemetry_ingest`.
- **Changed:** the docs that name modules (CLAUDE.md layout, the module diagram in PYTHON_MODEL.md, PROJECT_BLUEPRINT.md) use the new paths. Older history entries keep the paths they had.
- **Not changed:** `python3 -m engine.runner` and `python3 -m engine.spool_delivery` start as before, so INTEGRATION.md is untouched.

## 2026-10-23

### Workflows summary

- **Added (docs):** [WORKFLOWS_SUMMARY.md](WORKFLOWS_SUMMARY.md): what Phases 1 to 8 built, and a tour of the sample workflows for someone seeing them for the first time. Linked from WORKFLOWS.md.

### Workflows, Phase 8: time-based Reactions, Mark as late and Notify

Plan: [WORKFLOWS_PHASE8.md](WORKFLOWS_PHASE8.md). Decisions D178 to D184 in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md).

- **Added (Reactions):** the Whens *has not started by*, *has not ended by*, *runs longer than* and *within N minutes of being ready*, given as a time of day, a length, or a percentage over the job's recent average; the actions *Mark as late* and *Notify*. The workflow runner judges them for items and for a job on its own through its telemetry; each fires once per run and starts again when a run is reopened.
- **Added (Late flag):** runs and workflow items carry Late, with when, why and the job that caused it; Job History has a Late column and filter; the workflow run, its diagram and a job's log page show the Late tag and how each deadline was worked out.
- **Added (Alerts):** an Alerts page (who is told, subject and message, Send a test), Alert Deliveries (the outbox: Pending, Sent or Failed with the reason), and mail settings. Mail goes by SMTP from a task in the server, three tries a minute apart, so no job waits for a mail server. The test mail server is `mail_sink` in `dev_env.sh` (mail on 8025, page on 8026).
- **Added (database):** migration `migrate_late_alerts.py` (tables Alerts, AlertRecipients, AlertDeliveries, MailSettings; Late columns; time columns on Reactions); `autoapp_dev` migrated.
- **Added (sample):** `DEV-LATE_SAMPLE` in the seed and in `autoapp_dev` (backup `demo/output/autoapp_dev_before_late_sample.sql`), with the alert `DEV-LATE_ALERT`.
- **Fixed:** the link in an alert's message pointed at a page that does not take a run; it now opens the run's log, or a workflow's own page. The telemetry writer now takes a lock, as two threads write to it.
- **Not yet:** the Send email step and the wider Alerting design (ROADMAP.md); working days; a dead workflow runner firing nothing (hosting).

## 2026-10-22

### Workflows, Phase 7, step 7: the restarts sample and loose ends

Plan: [WORKFLOWS_PHASE7.md](WORKFLOWS_PHASE7.md). Decisions D174 to D176 in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md).

- **Added (sample):** `DEV-RESTARTS_SAMPLE` in the seed and in `autoapp_dev` (backup `demo/output/autoapp_dev_before_restarts_sample.sql`): Load, Post (the two earlier samples as shared jobs), Reconcile (an embedded workflow whose Balance fails once and whose Reaction resumes it), Notify and Report. A rehearsed walk-through is in the seed comment. Tests: `tests/test_restarts_sample.py`.
- **Added (Simulate):** `FailUntilAttempt`, so a step can fail on the first attempt only; steps are now given their job's attempt number.
- **Changed (pages):** a workflow run that Succeeded shows *Rerun ▸* with *Advanced…* only (D176); the values heading reads "The values the items restarted here use" in Advanced.
- **Changed (Advanced):** items at the top of the workflow that did not run now run when their waits are met, with a *Leave Not run* choice (D177), so bypassing a failed job carries the run on.
- **Changed (diagram):** the ×2 and the Reactions icon (the circular arrow) sit at the right of a box's first line instead of in a row above it, so a box with only these is no taller.
- **Moved:** the snapshot of resolved `${...}` values (D160) is TO-DO 19, not part of Phase 7.

### Workflows, Phase 7, step 6: Advanced… on the Rerun panel

Plan: [WORKFLOWS_PHASE7.md](WORKFLOWS_PHASE7.md). Decisions D161 to D173 in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md).

- **Added (pages):** *Advanced…* beside Resume and Restart from beginning. For a workflow run: every item with Leave / Resume / Restart / Bypass / Don't run, or the shortcuts *From the jobs chosen, and everything that waits for them* and *Only the jobs chosen* (with a warning that what follows may be out of date), a tick to ignore a wait for this restart only, and *Start the automatic retry counts again from zero*. For a job on its own: *Start here* and *Skip* on each top-level step, with a warning when a step that copies or deletes files will do it again. The panel says what the run will do before *Run* is pressed; the `${...}` values list is the one Resume uses.
- **Added (API):** `GET rerun-plan` takes `items`, `ignore` and `reset_counts` (JSON) so the panel can preview an item-by-item choice.
- **Changed (records):** the Restarts list and the Audit Log say "Bypassed 'Post'." and "Did not run 'Report'.".
- **Not yet:** Advanced on a Succeeded run is accepted by the API (D161) but the Rerun button appears only on a Failed run. *(Done in step 7, below.)*

### Workflows, Phase 7, step 5a: a Reaction resumes a workflow

Plan: [WORKFLOWS_PHASE7.md](WORKFLOWS_PHASE7.md). Decisions D156 to D158 in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md).

- **Changed (Reactions):** *Resume from failure* on a workflow, run on its own or a frame inside another, picks up the jobs that failed and starts those that did not run; it was always a Restart before (D148 replaced in part). It is passed over, with the reason, if any one job cannot be picked up, and the next Reaction that holds decides.
- **Changed (code):** the reopen plan moved from `app/rerun_tree.py` to `engine/reopen_tree.py`, with `automatic_problem` for Reactions.
- **Fixed (job log):** a rerun in the same process no longer writes lines to the log files of earlier attempts; a workflow's own Reaction messages now appear in its log.
- **Changed (pages):** the Reactions box help text no longer says a workflow is always run again.

---

## 2026-10-21

### Workflows, Phase 7, step 5: the records of a rerun

Plan: [WORKFLOWS_PHASE7.md](WORKFLOWS_PHASE7.md). Decisions D152 to D155 in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md).

- **Schema:** a new table, `RunRestarts` (`SQL/migrate_restarts.py` adds it; nothing existing changes).
- **Changed (control file):** a job's control file is removed when the run Succeeded and no Reaction changed that, together with the file of the attempt it picked up. A job inside a workflow that a workflow Reaction counts as failed has no file to resume from: Resume says so and offers Restart.
- **Changed (job log):** "Picking up run ..." is now "Resumed from attempt 1: steps 1 to 3 had finished; step 4 runs again." and, for a Restart, "Restarted from the beginning (attempt 2); attempt 1 failed."
- **Added (records):** each Resume or Restart asked for in the web interface writes a restart record and an Audit Log row (`JOB_RESUMED`, `JOB_RESTARTED`). `GET /api/v1/runs/{id}` gains `restarts` (the operator's and the Reactions' reruns, merged), and the run lists gain `restarts_count` and `restarts_words`.
- **Added (pages):** a *Restarts* box and "Restarted N times" on the Run Job, log and workflow run pages. Job History reads "Restarted ×N" in place of "attempt N", with the how as a hover.

---

## 2026-10-19

### Workflows, Phase 6: embedded and shared workflows (frames)

Plan: [WORKFLOWS_PHASE6.md](WORKFLOWS_PHASE6.md). Decisions D116 to D135 in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md) (D7 and D91 are now built). The rename warning below was its step 0.

- **Schema:** none. The owner column of a job and the run items' path were already there; an embedded job's key is made from names (`MONTH_END.Transform.Enrich`) and follows renames until the job has run.
- **Added (embedding):** a workflow can hold jobs and workflows of its own, to any depth, saved together in one Save: *+ New job here*, *+ New workflow here* and *+ Use an existing job here* in the editor, at the top and inside any frame. An embedded job belongs to its workflow: it is not on the Jobs & Workflows page or the search pages (the workflow's own editor shows it), is deleted with its item or its workflow, and its page says which workflow it belongs to. A check anywhere in the tree that fails saves nothing.
- **Added (frames on the diagram):** an embedded workflow is drawn as a frame around its jobs, folded to one box (▾ ▸ or a double-click) with a summary, with lines across frame borders. In a run each frame shows its state and what is inside it ("2 running, 1 failed"), and the Outline nests. A workflow of its own that is used as a job is one box that opens inline, read only (a lock on each job; a click opens its page).
- **Added (waiting across frames):** a job inside a frame can wait for any job in the same tree, in this run and never an earlier one; a wait whose job ended otherwise ends at once as not run. The frame as a whole waits like any item and gates everything inside. A loop through frames is refused, naming the path.
- **Added (conditions and variables):** `%{Transform.Enrich.Status}` reads a job inside a frame; a workflow's variables reach every job inside its frames, the nearest workflow winning, then a use's own.
- **Added (Find):** looks through the workflow, its frames and every workflow of its own it uses, to any depth, showing the path of each match and opening the way to it.
- **Added (Make shared, Use an embedded copy):** an embedded job or workflow can be given a key of its own and listed (keeping its key keeps its working folder), and a shared one can be copied into the workflow so a use can differ. Both audited; secret values are copied without going through a page.
- **Added (Needed by):** a workflow's page lists the jobs elsewhere that wait for it as a whole, or for a job in it (TO-DO 11).
- **API:** `embedded` on a workflow item (an embedded job or workflow, saved with the workflow), `POST /api/v1/jobs/{key}/make-shared`, `POST /api/v1/jobs/{workflow}/items/{item}/embedded-copy`, `owner` and `needed_by` on a job, `inside` and `frame_run_id` on the items of a run. Nothing changes for callers that do not send them.
- **Sample:** `DEV-FRAMES_SAMPLE` (seed section 10, also loaded into `autoapp_dev`).
- **Measured:** a tree ten levels deep with thirty frames ran in about 11 seconds.
- **Not done:** the arrowhead a little way into a folded frame; editing a frame's own Reactions and completion rules on the page (they are kept as saved); a line dragged between frames before the workflow is saved; the mockup was not updated. See WORKFLOWS_PHASE6.md.

### Renaming a job: a warning that says what it leaves behind (Workflows Phase 6, step 0)

Decision D116 in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md). Working folders stay named by the job's key.

- **Added:** renaming a job or workflow that has run history or a working folder on this server now opens a warning: Job History keeps the old key on past runs, scheduler definitions using the old key must change, and the files in the old working folder stay where they are. A tickbox, *Move the working folder with it*, moves the folder to the new key's name when it is on this server's disk and the job is not running. A job with neither history nor folder renames with the earlier confirmation, as before.
- **Added:** a rename is refused while the job is running. Moving the folder is refused, and nothing is renamed, when a folder with the new name already exists. A move is audited ("Moved the working folder with the job.").
- **API:** `GET /api/v1/jobs/{key}/rename-facts` (run count, running, folder, whether it can move); `move_working_folder` on the job save. Nothing changes for callers that do not send it.

### Workflows, Phase 5: outside dependencies

Plan: [WORKFLOWS_PHASE5.md](WORKFLOWS_PHASE5.md). Decisions D99 to D115 in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md) (D16 to D20 and D80 are now built).

- **Schema:** a prerequisite has a kind (`JOB`, `OTHER_JOB`, `ENDPOINT`, `TIME`) and, for the outside ones, the target, patience (`WaitMode`, `WaitMinutes`, `WaitUntil`, `WaitFrom`, `Required`) and limits; a job has `OnUnmet`; `WorkflowPrerequisiteChecks` keeps what each outside prerequisite found, for each attempt. `SQL/migrate_outside_dependencies.py` brings a Phase 4 database up to date, keeping its data. Back up first.
- **Added (waiting):** a job can wait for a job, or a whole workflow, elsewhere (its current or latest run, with optional limits: ended within N hours, started after this run did), for files at an endpoint on this server (at least one matches, each left alone for a minimum age), and for the time (`%{Now.Time}`, `%{Now.Date}`, `%{Now.Weekday}`; `IN WINDOW '18:00' TO '06:00'` for a window across midnight).
- **Added (patience):** each of them waits the system default (24 hours; Settings: *Default wait for outside prerequisites*), a number of minutes, until a time, or with no limit (which warns), counted from when the job's other prerequisites held, the first of them, a chosen one, or the start of the run. *Required* ones make the job Not run (or Failed, as the job's new *If it can't start* says, Reason `TIMED_OUT`); *optional* ones are given up after their limit and the job goes on without them.
- **Added (conditions):** a Custom rule can name the outside things the job waits for (`%{MONTH_END.Extract.Status}`, `%{INBOUND_ORDERS.FileCount}`) and the time; the condition box offers them, and the builder shows `BETWEEN` and windows (marking "next day").
- **Added (seeing them):** dashed boxes at the edges of the diagram for what a job waits for outside (job, files, clock or calendar) and, on the other side, the jobs elsewhere that wait for it (*Needed by*); a click opens that workflow; the Outline says the same in words. A run shows what each job is waiting for and until when, and afterwards what it found: the run it used and whether it held, ran out of patience or was given up (`GET /api/v1/runs/{id}` gains `outside_waits` and each item's `waiting_for`).
- **Added (checks):** saving refuses an unknown workflow, job, endpoint or empty time condition, a clash of names, a limitless optional wait, a loop between workflows (the message names the path), taking out a job others wait for, and deleting a workflow or endpoint others wait for. The pre-run check fails for files on another Site and warns of waits with no limit.
- **Added (diagram options):** external things are shaded and tagged (amber **EXTERNAL** for jobs and workflows elsewhere, blue **FILES** or **TIME** for what runs nothing). The toolbar's *Show external references* (on) and *Show non-executable dependencies* (off) fold each group into icons in the header of the boxes they apply to; both are remembered in the browser (D115).
- **Added (sample):** `DEV-OUTSIDE_UPSTREAM` and `DEV-OUTSIDE_SAMPLE` (seed section 9).
- **Changed (API):** a workflow job's prerequisites in `/api/v1/jobs` gain `kind` and the fields above (additive); `/api/v1/conditions/check` takes `outside`; new `/api/v1/conditions/outside-outputs`.
- **Not built:** Hold for an operator; remote endpoints; Check Files' own minimum age (only the shared test, `engine/file_age.py`).


### Workflows, Phase 4 (the rest): workflow variables

Plan: [WORKFLOWS_PHASE4.md](WORKFLOWS_PHASE4.md), "The rest of Phase 4". Decisions D91 and D92 in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md) (they replace D53's switch on each workflow).

- **Schema:** a use's own variables (`WorkflowItemVariables`); the values a workflow run fixed as it started (`JobRuns.WorkflowVariables`, a secret kept by name only). `SQL/migrate_workflow_variables.py` brings a Phase 4 database up to date, keeping its data. Back up first.
- **Added:** a workflow's variables, and those its tags give, reach every job it runs. A use of a job can set variables for that use only. Values are filled in once, as the run starts; a secret's value is never stored on the run, each job reads it as it starts. A tag clash on the workflow fails the job that uses the variable, with a message saying where to settle it.
- **Added (Settings):** the Variable precedence setting gains two levels, *Workflow* (just below the job's own) and *This use* (the highest). An order saved before keeps its order and gets them in those places.
- **Added (pages):** the workflow page has Variables and Tags sections (below the jobs, so the diagram stays high on the page), and each job in the outline or beside the diagram has **Variables for this use**.
- **Added (steps view):** a job used in a workflow shows its steps read only, in the diagram's pane and in the outline, with each `${Name}` in them marked with its value and where it comes from (this use, the job, the workflow, a tag), following what is on screen. **Open job ↗** opens the job in a new tab; saving it there does not touch the workflow.
- **Added (job opened from a workflow):** the workflow page's links to a job carry the workflow and the use, and the job page checks the job (and its live preview) as that workflow runs it, with its variables and the use's, saying so; **Check it on its own** shows the independent check. `GET /api/v1/jobs/{key}/check` and `POST /api/v1/jobs/preview` take optional `workflow` and `use`, and answer `checked_as`.
- **Added (checks):** the pre-run check judges each job with its workflow's and its use's values, so a job that relies on a workflow variable is no longer flagged as failing.
- **Added (sample):** `DEV-VARIABLES_SAMPLE`: one job used twice, one use taking the workflow's Region and Currency, the other setting its own; the Finance tag gives both.
- **Deferred:** the Operations object and For Each File over an upstream job's files (D42), handed to the roadmap.

---

## 2026-10-18

### Workflows, Phase 4: conditions

Plan: [WORKFLOWS_PHASE4.md](WORKFLOWS_PHASE4.md).

- **Schema:** a workflow's job's Custom rule (`WorkflowItems.StartRule`, with `JoinRule` `CUSTOM`; the jobs it names are its prerequisites, test `RULE`); a workflow's completion rules (`Jobs.SucceedsWhen`, `Jobs.ReturnCodeFrom`); the files a run delivered (`JobRuns.FileCount`, `JobRuns.Bytes`); the decisions conditions made in a run (`ConditionChecks`). `SQL/migrate_conditions.py` brings a Phase 3 database up to date, keeping its data; `autoapp_dev` was migrated (backup: `demo/output/autoapp_dev_before_conditions.sql`).
- **Added (engine):** every job in a workflow has outputs a condition reads as `%{Load.Succeeded}`: `Succeeded`, `Failed`, `Ended`, `NotRun`, `Skipped`, `Disabled`, `Bypassed`, `Status`, `ReturnCode`, `Reason`, `FileCount`, `Bytes`, `StartTime`, `EndTime`, `DurationMs`. Until a job ends they are unknown.
- **Added (engine):** **Custom rule** on a job's Start rule: a condition over the jobs it names and variables, offered whether the job waits for several jobs, one or none. It holds as soon as it is true, with the jobs still running counting as unknown, and the job ends Not run as soon as it is false. A rule using IS NULL, coalesce or the like waits until its jobs have ended.
- **Added (engine):** a workflow's **completion rules**: *It succeeds* unless a failure went unhandled (as before) or when a condition holds; *Its return code* 0 or 1 (as before) or the one a chosen job ended with.
- **Added (engine):** a job reports the files it delivered and their size with its end (`FileCount`, `Bytes`), counted as it goes, not from the operations audit trail; Job History has them, and a workflow's are its jobs' added up.
- **Added (pages):** the **condition box**, on the workflow page (Custom rule, Succeeds when) and for an If, Else If or While in the job editor: **Builder | Text**, the builder made of groups (*Match all / any of the following*) nested to any depth, each written in brackets; **Names and outputs**, each inserted by a click; in a workflow, problems and warnings as you type, and **Explain** with a chosen past run, part by part (holds, does not hold, unknown).
- **Added (pages):** switching a job to Custom rule starts the rule from what it waited for; switching back makes it wait for the jobs its rule named. Renaming a job renames it in the rules. A run says whether each Custom rule held and Succeeds when held, part by part with the values used, and what each other job waited for, each held or not.
- **Changed (pages):** the panel beside the diagram is wider and opens only while a job is selected (**Hide Job pane ×**, or a click on the empty canvas, hides it), and is resized by dragging its left edge; while editing, jobs changed since the last save are outlined and marked with a pencil.
- **Added (diagram):** a job with a Custom rule carries a `{x}` marker that shows its rule; lines from the jobs it names are dotted. Dragging a line to such a job adds the job to its rule.
- **Added (sample):** `DEV-CONDITIONS_SAMPLE` in the seed data and `autoapp_dev`: Post starts by a rule over a file count and two outcomes, a fallback runs only if the rates failed, a rule on the workflow's variable `Region`, and Succeeds when Post succeeded.
- **Handed to the roadmap planning session:** Set Return Code becoming Set Return Values, and Job History apart from the operations audit trail (also TO-DO decision 10).

### Workflows, Phase 3: return codes and Reactions

Plan: [WORKFLOWS_PHASE3.md](WORKFLOWS_PHASE3.md).

- **Schema:** Reactions and their actions (`Reactions`, `ReactionActions`), on a job or on one use of it in a workflow; the record of Reactions that fired (`ReactionEvents`); on a workflow's job, Disable here (`DisabledHere`) and whether it overrides its job's Reactions (`ReactionsOverridden`); on runs, the status before a Reaction counted it otherwise (`StatusBeforeOverride`), the runner's `ProcessID` and a Kill request. `SQL/migrate_reactions.py` brings a Phase 2 database up to date, keeping its data; `autoapp_dev` was migrated (backup: `demo/output/autoapp_dev_before_reactions.sql`).
- **Added (engine):** **Reactions** are carried out when a job ends: by the workflow runner for a job in a workflow, before anything that waits for it is looked at; by the job runner for a job run on its own. Of *What happens next*, the first entry that holds decides; every *Also* entry that holds fires. Each is judged on what really happened, not on an earlier Count as.
  - **Count as succeeded / failed:** the run keeps what it ended as on its own (`StatusBeforeOverride`), to show both.
  - **Rerun this job**, after a wait, at most N times; **Rerun from…** a chosen job and every job between it and this one. Each rerun is a new attempt in the same run (on its own: a new run, same instance ID, next attempt). Once a rerun has used up its limit, the next entry that holds decides ("rerun twice, then count as succeeded").
  - **Skip…** a chosen job, or **the rest of the branch**: what has not started ends Skipped.
  - **Kill the workflow**; **Start a workflow** (a run of its own, scheduler "AutoApp reaction").
  - Every action that fired, or was passed over at its limit, is in the job log and in `ReactionEvents`. A killed job's Reactions do not apply: someone stopped it.
- **Added (engine):** **Kill.** A job runner told to stop ends Failed, Reason `KILLED`, with no return code; a runner killed before it could record anything is recorded so by the workflow. A workflow's **Kill and Cancel** kills its running jobs, down through workflows inside it, and cancels the rest; it ends Failed, `KILLED`. Each runner records its process ID; the workflow runner records each job's as it starts it.
- **Added (engine):** **Disable here** on a job in a workflow: *Stop here* ends it Disabled; *Pass through* ends it **Bypassed** (Reason `DISABLED_PASS_THROUGH`), which counts as succeeded with return code 0.
- **Added (pages):** a **Reactions** box, the same on the job page and the workflow page: **What happens next** (in order, ▲▼) and **Also**, each entry a When (it succeeds, fails, ends, or a return code) and what it does; the choices offered are only those that fit (a job's own: Count as, Rerun this job; a use: also Rerun from…, Skip…, Skip the rest of the branch, Kill the workflow; Also: Start a workflow). Locked, each reads as a sentence ("When its return code is 8: rerun this job, at most 2 times.").
- **Added (pages):** on the workflow page, each job shows its job's Reactions, marked "from the job"; **Override here** gives the use its own, starting from a copy; **Use the job's again** drops them. **Here it** runs / is disabled: stop here / is disabled: pass through. The workflow's own Reactions are in a panel of their own.
- **Added (pages):** a run shows "Succeeded (counted; it failed)", attempts, Bypassed and Skipped, and the **Reactions that fired**. **Kill and Cancel** on a running workflow; **Kill** on a running job in it (outline and diagram), on the Run Job page and on a run's log page. Job History shows "(counted; …)" and attempts.
- **Added (diagram):** markers for Reactions, disabled here (stop) and pass through; Bypassed (dashed, an arrow through) and Skipped (grey stripes) boxes, in a run and, for Disable here, in the editor; **Rerun from…** drawn as a dash-dot ↺ arc back to the job it reruns from. The key says what each means.
- **Changed:** **Jobs & Workflows** says "*N* found", as it lists workflows too.
- **Added (sample):** `DEV-REACTIONS_SAMPLE` in the seed data and `autoapp_dev` (backup first: `demo/output/autoapp_dev_before_reactions_sample.sql`): a feed rerun twice then carried on without, return code 4 from a Set Return Code step counted as succeeded, a Rerun from… loop with its limit then Skip the rest of the branch, and a job disabled here to pass through.
- **Added:** the **Set Return Code** step type. It sets the job's return code and the job carries on; if several run, the last one wins. Inside an If, a job chooses its own code. Its **Message** is written to the job log beside the code ("Return code set to 4: No files arrived"). When the job ends, its Success return codes decide whether the code means Succeeded or Failed, as for Simulate.

## 2026-10-17

### Workflows, Phase 2: the diagram

- **Added:** the workflow page shows a workflow as a **diagram** as well as the outline, with a **Diagram | Outline** switch. The page opens in whichever view was used last, in that browser. Plan: [WORKFLOWS_PHASE2.md](WORKFLOWS_PHASE2.md).
  - Laid out automatically, left to right or **top to bottom**; each column keeps the outline's order. Full names, wrapped, never cut short. Zoom in and out, and **Fit** to the window.
  - Lines are coloured *and* styled by their test: succeeded green, failed red dashed, ended solid in the text colour, return codes purple and labelled (`RC 0-4`). **ANY** marks a job that needs only one of its lines. Pointing at a line says what it means ("Load waits until Extract succeeded").
  - Markers on a box: the job used is a workflow; the job used is disabled. A **Key**, folded away, says what lines, states and markers mean.
  - Selecting a box shows that job beside the diagram, as the outline shows it; selecting a line shows the job that waits, with that prerequisite marked.
  - **Find** highlights the jobs whose names contain the text, and lists them; choosing one selects it and brings it into view.
- **Added:** editing on the diagram. While editing, dragging from one box to another makes the second wait for the first to succeed; the job beside the diagram is edited as in the outline (its test, its other prerequisites, its job and name, Remove this job). Pointing at a line shows a small **×** on it that removes it; a selected line is also removed with **Delete**. **+ Add a job** adds a box and selects it. Changes are saved with Save, as before, and switching between Diagram and Outline keeps them.
- **Added:** a run on the diagram: each box in its state (Succeeded, Failed, Running with a moving stripe, Waiting, Not run, Disabled), live while the run goes; selecting a box shows its state, times and log.
  - The lines are the workflow's as last saved, not necessarily as it was when the run started.
- **Changed:** **Job History** is a tree. A workflow run is one row, folded, saying how many runs are inside it (**▸ 2 runs inside**); unfolding it lists them under it. A run found by the search whose workflow run isn't found too (searching for a job's key, say) is a row of its own, linking to its workflow run, as before. **Within run** opens the run asked for unfolded. The 500-row limit counts the rows at the top.
- **Added (API):** `GET /api/v1/runs` takes `tree=true` (leave out runs whose workflow run is listed too) and `parent=<run ID>` (the runs directly inside a workflow run), and each run says its `child_count`. Without them it answers as before.

### Jobs & Workflows; Administration; Save; a job's prerequisites

- **Changed:** the server tells browsers to check for a newer copy of every page, script and stylesheet each time, so a change shows without a hard refresh.

- **Changed:** **Submit** is now **Save** on every page that has it (the job, workflow and detail pages). "Submit" reads as "submit to run" to anyone who uses a scheduler.
- **Changed:** on the workflow page, while editing, a job's prerequisites sit in a box labelled **Prerequisites**: each with its **Job in this workflow** and **Outcome**, **+ Wait for another job**, then the **Start rule**: *When all prerequisites are satisfied* or *When any prerequisite is satisfied*, greyed out until the job waits for two jobs or more. A third, *Custom rule*, is shown greyed out until conditions are built (Phase 4). **Remove this job** is below the box.

- **Changed:** **Job Search** is now **Jobs & Workflows**, one page for both, with a **Type** column (Job or Workflow) and its Type filter. The separate **Workflows** link in the navigation bar is gone; it opened the same page.
- **Changed:** the Main Index has an **Administration** section, holding Settings, apart from the records of what happened.

### Workflows: a handled failure no longer fails the workflow

- **Changed:** a workflow fails only if a failure went unhandled: a job failed and nothing that waits for it ran, or jobs were cancelled. A failure path that ran (the sample's Alert finance) leaves the workflow Succeeded, and its log says which failures were handled. A job that is Not run because something before it failed does not count against the workflow; the failure before it does. Design: [WORKFLOWS.md](WORKFLOWS.md), "When a workflow succeeds".
- **Changed:** the workflow page's **Cancel run** is now **Cancel what hasn't started**, which is what it did.

### Job logs are files on the host that ran the job

- **Changed:** a run's job log is no longer stored in the database. The runner writes it, line by line, to `<log root>/<host>/<YYYY-MM-DD>/<RunID>.log`; the run's record keeps only where it is (`JobRuns.LogFile`, with `Host`). The server reads it through that host's agent, as a WLA reads job output; AutoApp has no agents, so a stand-in reads the host's folder on this machine. Pages show logs as before, and a run still going shows its log so far.
- **Added:** the setting **Keep job logs for** (Settings page; 30 days by default, or a week to a year, or never). Older logs are removed at server startup and once a day; the run's log page then says when. A log missing from its host is also said so.
- **Added:** the Settings page shows settings that are a choice from a list.
- **Changed:** the runner no longer sends `LOG` records; one in an old spool file is still accepted, and its lines are not kept.
- **Changed (docs/INTEGRATION.md):** the job log is also kept as a file, under `AUTOAPP_LOG_ROOT`. Nothing a scheduler does changes.
- **Migration:** `SQL/migrate_log_files.py` adds `JobRuns.LogFile` and `JobRuns.LogRemovedDateTime`, writes each run's existing log to its file, and drops the `JobRunLogs` table (the owner approved dropping it). Run it with `AUTOAPP_LOG_ROOT` set as the server has it.

### Workflows: disabled jobs no longer stop a workflow

- **Changed:** a workflow that uses a disabled job still runs. When the disabled job's turn comes it ends **Disabled** without running; the jobs that need it to succeed are Not run ("it waits for 'Off' to succeed, and 'Off' is disabled"), and jobs that wait only for it to end still run. Before, the whole workflow refused to start.
- **Changed:** a job in a workflow that would fail its own pre-run check no longer stops the workflow either: it fails when its turn comes, with its own reason. Only a disabled or empty workflow refuses to start.
- **Added:** the workflow's check, on its page and on Run Job, lists such jobs as warnings in advance.
- **Added:** disabling a job that workflows use asks first, naming the workflows and saying what will happen in each. Every job's details now list the workflows that use it (`used_in`).
- **Changed:** the message refusing prerequisites that go round in a loop says none of those jobs could ever start, and that repeating jobs will be done with a Rerun from… Reaction.
- **Design** ([WORKFLOWS.md](WORKFLOWS.md)): when a workflow succeeds by default (a failure fails it only if nothing that waits for it ran), completion rules, Kill, Cancel and Hold on a workflow, and loops as repeat links with a limit.

### Run Job: finding a job with the Job Search criteria

- **Added:** the Run Job page has the Job Search page's criteria (job key, description, type, status, endpoint, tag) and lists the jobs found, each with its status, contents, tags and last run. **Choose** picks one to run. The criteria and the job chosen are kept in the page address, so a reload keeps both. Typing a job key still works as before.

### Workflows, Phase 1: jobs that run other jobs

The design is in [WORKFLOWS.md](WORKFLOWS.md), this phase's plan in [WORKFLOWS_PHASE1.md](WORKFLOWS_PHASE1.md).

- **Added:** workflows. A workflow is a job of type WORKFLOW, made of other jobs (each under a name of its own in it) and the prerequisites between them: a job starts when the jobs it waits for have succeeded, failed, ended whatever happened, or given chosen return codes; all of them by default, or any one. Everything else runs in parallel.
- **Added:** the workflow page (`workflow.html`), in the Outline view: add jobs, say what each waits for, save, Run, and watch the run, each job with its state and its log. **Cancel run** starts nothing more; the jobs running finish. The job page sends a workflow there. **Workflows** in the navigation bar, a Type filter and **New workflow** on Job Search.
- **Added:** running a workflow (`engine/workflow_runner.py`). A workflow is started like any job, by its key, from the Run Job page or a scheduler. A job whose prerequisites can never hold is Not run, saying why ("it waits for 'Load' to succeed, and 'Load' failed"), and that cascades. The workflow fails if any of its jobs failed.
- **Added:** Job History shows workflow runs and the job runs inside them: Type and Within run filters, a link from a workflow run to "this run and its jobs", and from each job run to its workflow run. Every run now shows its return code.
- **Added:** the **Simulate** step type, for trying workflows before the real jobs exist: it writes given lines to the job log, waits, and ends with a chosen return code, or fails on purpose.
- **Added:** **Success return codes** on every job (`0` unless set; `0, 4` or `0-4`). A step can set the job's return code (Simulate does); a job whose code is not a success code fails, with Reason `RETURN_CODE`. The runner's exit code stays 0 or 1; the return code is recorded with the run.
- **Added:** the sample workflow `DEV-MONTH_END_SAMPLE` in the seed data: the four sample jobs, then a ledger check (return code 4), a failure path and a return-code branch, made of Simulate stand-ins.
- **Changed:** a job used by a workflow cannot be deleted until it is taken out of it. A job's type cannot be changed.
- **Migration:** `SQL/migrate_workflows.py` adds `Jobs.JobType`, `Jobs.Owner_MasterObject_id` and `Jobs.SuccessReturnCodes`; `JobRuns.ReturnCode`, `Reason`, `JobType`, `ParentRun_id`, `WorkflowPath`, `Attempt` and `CancelRequestedDateTime`; and the tables `WorkflowItems`, `WorkflowPrerequisites` and `WorkflowRunItems`. Existing jobs become STEPS jobs, and finished runs get the return code their status implies. It keeps all data and can be run again safely.

### Flow control: If, For Each File, While, step outputs and On failure

Brought over from RunMyFiles, where it was designed with the owner and built on 2026-10-16 (its commit e68675c), after the fork. The design is in [FLOW_CONTROL.md](FLOW_CONTROL.md).

- **Added:** steps that hold steps. **If** holds a Then, any number of Else If and at most one Else; **For Each File** runs its steps once per file at a location; **While** repeats them while a condition holds, up to `MaxIterations` (default 100), waiting `WaitSeconds` between passes. Then, Else If and Else are step types of their own, never offered on their own in the editor.
- **Added:** steps are numbered as a tree, 3, 3.1, 3.2, in the editor, the job log and the Operations Log. An If's branches share one count.
- **Added:** conditions written as a SQL `WHERE` clause, worked out by SQLite in a database that holds nothing and may only compute: `%{Check_files.Status} = 'SUCCESS' AND %{File.Size} > ${MinBytes}`. A value inside quotes is filled in as text, any quote in it doubled; outside quotes it is passed to SQLite separately, so no value can change what a condition means. A variable whose value reads as a number counts as a number.
- **Added:** `%{...}`, values from the run itself, filled in as each step starts, in any parameter and in conditions: a step's outputs by its StepName (`%{Check_files.FileCount}`), and inside a For Each File the file (`%{File.Name}`, `%{File.FullName}`, `%{File.Size}` and more). Every step has `Status`, `ReturnCode`, `ErrorMessage`, `StartTime`, `EndTime` and `DurationMs`; each step type declares its own besides (`FileCount` for the file steps, `Bytes` for Copy Files, `ArchiveName` for Zip Files, `Passes` for While). A step that has not run is `SKIPPED`.
- **Added:** inside a For Each File, a step may take the loop's file as its location even when the loop reads from an endpoint outside the working folder; its operations are recorded against that endpoint, so the trace follows the file.
- **Added:** **StepName** on every step: how later steps refer to it. The editor makes it from the title as the title is typed (spaces become underscores) until it is changed by hand; a saved step's name never changes by itself. Names may repeat: the step that ran last wins.
- **Added:** **On failure** on every step: *Fail the job* (the default, as before), *Continue*, or *End the job with success*.
- **Added:** the pre-run check covers every branch and loop: the shape of each If, every condition (that it is valid, and that each `%{...}` names a step or a loop's file, and something it has), and the loop's file name. A condition comparing a number with text is pointed out in the editor, under the condition, and in the job's warnings.
- **Added:** in the editor, block steps show the steps inside them indented, with **+ Add step here**, **+ Add Else If** and **+ Add Else**, and ◀ ▶ to move a step out of its block or into the block above. Changing a block's type keeps the steps inside it.
- **Added:** `GET /api/v1/step-types` says of each type whether it holds steps (`block`), whether it is only part of an If (`hidden`), and its `outputs`. A job's steps (`GET /api/v1/jobs/{key}`) have `number`, `name`, `on_failure` and `children`; a save takes `name`, `on_failure` and `children` the same way, and a step moved in or out of a block keeps its id. The preview's fields have `warnings`. A job without blocks reads and saves as before.
- **Added:** the Operations Log's step column shows the step's number and, inside a loop, its pass; the CSV download has a Pass column. The trace keeps a loop's passes apart.
- **Changed:** the sample `DEV-BILLING-INVOICE_EXPORT` uses flow control. Its check goes on when it fails; step 4, an If on the check, keeps a copy of each export (a For Each File) and sends the batch to finance, or else holds the exports back and fails saying why. When all is well, finance gets the same archive as before. [DEMO.md](../demo/DEMO.md) says so.
- **Fixed:** the preview of a saved step whose type was changed checked it as its old type.
- **Migration:** `JobSteps` gains `ParentStep_id`, `StepName` and `OnFailure`, and `Operations` gains `StepNumber` and `Iteration`. `SQL/migrate_flow_control.py` adds them to an existing SQLite or MariaDB database, keeping its data, and names each step from its title; it can be run again safely. Nothing is dropped or renamed.

## 2026-10-16

### RunMyFiles is AutoApp again

- **Changed:** AutoApp's role. The product was forked into its own project, RunMyFiles. AutoApp remains as a testbed and demonstrator for scheduler features worth having in RunMyJobs, starting with workflows (see [PROJECT_GOALS.md](PROJECT_GOALS.md)).
- **Changed:** the name people read is AutoApp again: the web interface, the Stand-in Scheduler's pages, messages, the job log and README.md. Some documentation from before the fork still says RunMyFiles.
- **Changed:** the Run Job page runs jobs as the scheduler "AutoApp UI" again (was "RunMyFiles UI"). The sample data names it so too.

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

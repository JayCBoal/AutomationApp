# Workflows, Phase 7: restarts

The seventh phase of [WORKFLOWS.md](WORKFLOWS.md) ("Implementation in phases"): **a failed run can be picked up where it stopped, or restarted in whole or in part, from one Rerun ▸ menu, and every choice is on record.** It answers the restart half of shortcoming 2 ([PROJECT_GOALS.md](PROJECT_GOALS.md) goal 2): in RunMyJobs a failed chain is restarted by hand, step by step, with nothing saying what the failed step had already done.

Status: **PLAN AGREED 2026-10-20; nothing is built.** Every question was answered by the owner (see "Settled by the owner"); proposals 1 to 13 stand as written. Decisions are D136 to D142 in WORKFLOW_DECISIONS.md. The plan is for a separate building session.

## Starting point

Already built, and what this phase uses:

- **Attempts.** Every job run in a workflow carries an attempt number, and a workflow item remembers its latest attempt and job run. Job History shows every attempt. A Reaction's *Rerun this job* and *Rerun from…* already start new attempts inside the same workflow run (D74), counted per run with "at most N times" (D61).
- **Values fixed at the start.** A workflow run stores its `${...}` values as it starts (D91, D134), a secret by name only. Resume was the reason for fixing them (D57, D91).
- **Frames are runs of their own** (D116 onward): each frame is a child workflow run, so a Failed frame has its own record to pick up.
- **Run records.** Every item of a workflow run has a status and a Reason; the Job History tree, the job log file on the host, and the Audit Log exist. Kill and Cancel exist on runs.
- **Spool.** The runner writes every operation to a spool file as it goes. This is the operations audit trail, not a record Resume may rely on (see proposal 1).

Designed, not built: the Rerun ▸ menu; Resume; Restart from beginning; Advanced…; the three-way account of what a failed step knew (D76); flow control state that survives a failure; net result across attempts (D43); the operator's manual rerun and "Reset automatic retry counts" (D61).

## What Phase 7 includes, and what it leaves out

- **In (proposed), part 1, the core:**
  - **Rerun ▸ Resume / Restart from beginning**, on a workflow run (the whole run, a frame inside it, or a failed job inside it) and on a job's run on its own.
  - **The control file:** what a job's run keeps, as it goes, so a later attempt can pick up (proposal 1).
  - **What a failed step knew:** each step type says *not done*, *partly done and known*, or *unknown* (proposal 3), and Resume deals with each.
  - **Flow control state:** an If keeps its branch, a For Each File keeps its list of files and the passes done, a While keeps its pass count (proposal 4).
  - **Net result across attempts** (D43): resumed attempts add up for `FileCount` and `Bytes`; a restart counts the latest only.
  - **A run that has ended can be reopened:** the same run record goes back to Running, a new runner process picks it up (proposal 5).
  - **Records of every choice:** on the run (shown on its page and in Job History) and in the Audit Log.
- **In (proposed), part 2, Advanced…:**
  - from a chosen job, or from a chosen step in a job on its own;
  - only chosen jobs;
  - mark as done (Bypassed, Reason `MARKED_DONE`);
  - ignore a prerequisite for this run;
  - skip chosen jobs or steps;
  - different `${...}` values, with a warning;
  - reset automatic retry counts.
- **Out:**
  - **Hold at…** (pause before a chosen job). It needs the "Hold for an operator" state that was moved to TO-DO in Phase 3; both go together later.
  - **Mark as late, Notify and the time-based Reactions:** Phase 8.
  - **A step type that cannot say what it knew** gets the safe answer (proposal 3), not a new design. New step types added later must say, as part of being complete (CLAUDE.md's list gains one line).
  - **Resuming on a different host** than the failed attempt ran on (proposal 2).
  - **Restart from a scheduler.** A scheduler still starts a top-level job or workflow by its key; INTEGRATION.md is not touched. The restart count the scheduler passes in is unchanged.
  - **Restart from an outside event** (a scheduled automatic restart of a whole run) belongs with scheduling in the roadmap.
  - **Loops across workflows** ("Rerun workflow" Reaction, TO-DO 9): not a restart of a past run.

## Proposals to settle with the owner

1. **The control file is its own small file, not the operations spool and not the database.**
   - *Why it is a problem:* the design says "the spool, read back" ([WORKFLOWS.md](WORKFLOWS.md), Restarts). But the telemetry principle (TO-DO 10, D40) says nothing the workflow acts on may depend on operations records, which are an audit trail sent in the background and may arrive late, or never. A Resume that relied on them would break the first time telemetry was made asynchronous.
   - *Proposal:* the runner keeps a **control file** for each job run, a small file written on its own host as the job goes, beside its job log, and written before the next step starts so a killed runner leaves it right. It is not sent anywhere. It holds only what Resume needs: the job's resolved `${...}` values (secrets by name only), the steps finished and the outputs later steps read (`%{Name.Output}`), the return code and file counts so far, flow control state (proposal 4), and for a failed step what it knew (proposal 3). The runner still never writes the database, so this fits the hosting plan: on an agent host the record is a file on that host.
   - **Why not the spool, which is also a local file** (the owner asked, 2026-10-20): the spool holds operations only (which file went where). Resume also needs the resolved values, step outputs, the branch an If took, the For Each list, the return code so far and what the failed step knew; and the spool's life (delivery marks, sweeps, its format) belongs to the telemetry redesign, which must be free to change it. The control file is written with the spool's existing append-and-flush code, so there is no second writer; the small overlap (a file step notes "done" in both) is the price of independence.
   - **A killed runner** (the owner's question): Kill already sends SIGTERM and the runner catches it. In this phase a step in flight also writes what it knew as it stops: Run SQL killed before its commit has been rolled back, so it is *not done*; a file step notes the file it was on; a step stopped in the middle of a commit stays *unknown*. A hard kill (`kill -9`) or a host crash cannot be caught, so the record is also written before and after each step and after each file; the step in flight then counts as unknown or partly done.
   - *Considered:* reading the spool back (breaks the principle); sending the record with the job's end report (a killed runner sends no end report, which is the very case Resume is for); a new database table written by the runner (the runner must not write the database).
2. **Resume runs on the host the failed attempt ran on.** The record is a file there. If the job now would run elsewhere, or the file is gone (removed with the job log, when it is older than the Settings page's limit), Resume says so in plain words and offers Restart from beginning. In the demonstrator everything runs on one machine, so this shows only when the file has been removed. A control file is kept as long as its job log, and removed with it.
3. **What a failed step knew: three answers, decided by the step type.**
   - *Not done* (safe to run again), *partly done and known* (file steps skip files the record shows done; a file in progress is checked at its destination by size, and by checksum where recorded, and redone if it does not match), or *unknown*.
   - **Each step type declares it** in its handler, as part of the catalog entry: Run SQL (could not connect, or the server rejected the statement and rolled back: not done; connection lost after sending, above all in the commit: unknown; DDL in MariaDB commits by itself, so a failure after it is unknown); the file steps (partly done and known); Check Files, Set Return Code, Simulate (not done); Zip and Unzip (partly done: the partial archive or output is removed on failure and the step run again).
   - **A step type that does not say counts as unknown**, never as not done: a safe default, and it makes a new step type's author think.
   - **Unknown does not hold the run.** The Rerun ▸ dialog names the step and says why ("Run SQL 'Load': the connection dropped while committing, so it is not known whether the rows were saved"), and the operator chooses for that step: *Run it again*, *Count it as done*, or *Restart the job from the beginning*. Resume cannot be chosen without one. This avoids a new "waiting for an operator" state, which is TO-DO's Hold for an operator.
   - **The status is called "Failed (effect unknown)"** (the owner's wording, 2026-10-20), on the run, in the dialog, in the log and in Job History. The dialog says it plainly: "It is not known whether this step changed anything before it failed."
   - **An automatic Resume does not fire after "Failed (effect unknown)"** (the owner, 2026-10-20, option a): the job stays Failed, and its log and the run's Reaction record say why. **An automatic Restart from the beginning still runs**, as it does today: choosing a restart accepts that the job's work is done again. Nothing existing changes, since existing Reactions stay Restart (proposal 13). Because a step that does not say counts as unknown, the step types are classified first (step 0), before this rule is switched on.
4. **Flow control state is kept in the control file, per step, by its place in the job.**
   - An **If** whose branch had begun keeps that branch; the condition is not asked again. One that had not begun is asked again.
   - A **For Each File** keeps its list of files from attempt 1 (as matched then), and skips the passes that finished. The pass that failed runs again for its step (by proposal 3).
   - A **While** picks up at its pass count; its `MaxIterations` counts across attempts.
   - `%{Name.Output}` values of finished steps come back from the record, so a later step reads what it read before.
   - `%{Now...}` is the current time, as the design says; the business date, `${...}` and the fixed workflow variables are the first attempt's.
5. **A run that has ended is reopened, not copied** (D74). Reopening a workflow run (or a frame's):
   - sets its record back to Running and clears its end; its start time stays the first one, its page says "Restarted 2 times" and lists them;
   - starts a new workflow-runner process on the same run record, which reads the run's items instead of planning them afresh, and its stored variables instead of fixing them again;
   - rebuilds the "at most N times" counts from the Reaction records of the run (so a manual rerun does not reset them, D61);
   - can be chosen when the run has ended Failed, or Succeeded (Advanced only), or been Cancelled; not while it runs (Kill it first).
   - **If the workflow was edited since the run:** Resume and Advanced are allowed only when every item of the run still exists under its path; otherwise they say which, and offer Restart from beginning. (The simple rule; a smarter merge can come later.)
   - Reactions that were used up stay used up; a frame item and a shared workflow reopen as their own runs in turn (proposal 8).
6. **Resume on a workflow run** (the Rerun ▸ menu's first choice): it reruns the items that ended Failed or Not run, leaving Succeeded, Bypassed, Skipped and Disabled as they are.
   - A Failed job resumes from its own record (proposals 1 to 4).
   - A Not run item is looked at again from scratch; its prerequisites are asked again against the run as it now is.
   - A Killed job (Failed, Reason `KILLED`) resumes like any failure; its record says what it had finished.
   - A Failed frame, or shared workflow, is resumed the same way, down through its own items (proposal 8).
   - Items that ended Cancelled (Not run, Reason `CANCELLED`) start after the cancel is lifted: a reopened run is no longer cancelled.
7. **Restart from beginning**: every item reset, from scratch, passed down the same way; every control file of the run is set aside (kept for the log, not used). Only the latest attempt counts for downstream results (D43).
8. **Frames and shared workflows.**
   - A frame reopens as a child workflow run of its own, with its own record and the same run id, so Job History shows its attempts as for any item.
   - Resume at the top passes down: each Failed frame is reopened and resumes; a frame that ended Not run or never started is simply started as usual.
   - Rerun ▸ is also on a frame's own run and on a job inside, so an operator can restart just that frame, as Phase 6 deferred.
   - A rerun of a frame does not reset what the rest of the tree already decided: items outside it that already ended stay as they are, and anything that waits for the frame sees it Running again (it ends Not run if it has already been given up on; *Advanced → from a chosen job* is the way to include it).
9. **Net result across attempts** (D43): the item's `FileCount` and `Bytes` after a Resume are the attempts added up; after a Restart or a Reaction's rerun, the latest only. Downstream reads `%{Extract.FileCount}` in the workflow run as the net result; every attempt remains in Job History. A Reaction's *Rerun this job* gets two options, **Restart from the beginning** and **Resume from failure** (the owner, 2026-10-20; proposal 13); both start a new attempt, so this rule gives each its net result.
10. **Advanced…** (part 2). One dialog with the choices from the design, each applied to the chosen jobs and recorded:
    - **From a chosen job:** it and everything downstream, each as *Resume* or *Restart from beginning* (a job Succeeded before can only restart). Upstream stays as it is.
    - **Only chosen jobs**, with the warning that downstream results may be out of date.
    - **Mark as done:** a failed or waiting job ends Bypassed, Reason `MARKED_DONE`, and what waits for it goes on.
    - **Ignore a prerequisite for this run:** the line is drawn crossed out on the run, the wait is recorded as released by an operator, and the chosen job starts when its other prerequisites hold. This is Control-M's "add the condition by hand", done openly.
    - **Skip chosen jobs:** as the Skip Reaction does.
    - **Different `${...}` values**, with a warning that the run no longer used the values it started with; the changed ones are recorded by name (a secret by name only, never a value).
    - **Reset automatic retry counts:** the Reaction counts of the run start from zero (D61); recorded so the counts rebuild correctly when a run is reopened again.
    - **A job's run on its own**: from a chosen step, skip a step, different values.
11. **Every choice is recorded**, in two places: on the run (a *Restarts* list: number, when, what was chosen, which items it touched, any values that changed by name) and in the Audit Log, "by web interface" until accounts exist (TO-DO "Who made a change"). The Audit Log's note that it is for definitions is widened to "and the restart choices made on runs". The job log of each restarted item says "Resumed from attempt 1: steps 1 to 3 had finished; step 4 runs again."
12. **Where it lives in the pages.**
    - **Run page** (`run.html`): a **Rerun ▸** button where Kill and Cancel are, shown when the run has ended or has failed items. Resume first; Restart from beginning second; Advanced… third.
    - **Job History**: the same on a run's row; a restarted run shows "Restarted ×2".
    - **A job's page, Run Job page and a job-on-its-own run**: Rerun ▸ on a failed run of a job started on its own.
    - **API:** one call, `POST /api/v1/runs/{run_id}/rerun`, with the kind (resume, restart) and the Advanced choices; a call to ask first what Resume would do (which items, which steps, any unknown ones to decide) so the dialog can say it before anything starts.
    - **The diagram** marks an item with more than one attempt (a small ×2); a reopened run shows live as any run does.
13. **A Reaction's *Rerun this job* has two options** (the owner, 2026-10-20): *Restart from the beginning* (as built) and *Resume from failure*, since a job of steps is AutoApp's standard job.
    - Existing Reactions become *Restart from the beginning*, so nothing changes for them; a new one defaults to **Resume from failure** (the owner, 2026-10-20: a job of steps is the standard job, and it is the safer choice after "Failed (effect unknown)").
    - The editor's Reaction row and its help text show the choice; the run page, job log and Reaction record say which was used.
    - A Resume by Reaction follows the same rules as the operator's (proposals 3, 4, 9); after "Failed (effect unknown)" it does not fire (proposal 3). *Rerun from…* stays a restart of the chain.
    - It needs a place to store the choice on the Reaction's action and a migration that works on SQLite and MariaDB and keeps `autoapp_dev`'s data.

## The steps (proposed)

Part 1:

0. **Classify the step types** (proposal 3): the three answers on every step type's catalog entry, the "does not say counts as unknown" default, a test that every step type in the catalog has an answer. Merged before the rest because it changes nothing visible by itself.
1. **The control file** (proposals 1, 2, 4): written by the runner as it goes; read back by a run asked to resume; a killed runner leaves it right; removed with the job log. Executor changes for If, For Each File and While; tests with failures forced at each kind of step, both for a runner that failed and one killed.
2. **Resume inside a job on its own**: Rerun ▸ on a failed job run, Resume and Restart, the dialog that names unknown steps and takes the choice, net result across attempts (proposal 9). This is the smallest slice that shows Resume working.
3. **Reopening a workflow run** (proposals 5, 6, 7, 8): the runner picking up an existing run record; Resume, Restart from beginning and the rule for an edited workflow; frames and shared workflows passed down; the Reaction counts rebuilt.
3a. **The Reaction's two options** (proposal 13): the stored choice and migration, the editor row and help, the workflow runner and the job runner carrying out Resume from failure, the rule for an unknown failure (once settled) switched on, tests on both databases.
4. **Pages and API** (proposal 12): Rerun ▸ on the run page, Job History and a job's own run; the "what would Resume do" call and its dialog; the Restarts list on a run; the ×2 marker on the diagram.
5. **Records** (proposal 11): the run's Restarts list, the Audit Log rows, the job-log lines.

Part 2:

6. **Advanced…** (proposal 10): the dialog and each choice, one at a time with its test: from a chosen job, only chosen jobs, mark as done, ignore a prerequisite, skip, different values, reset counts.
7. **Sample, docs and tests.** CHANGE_LOG; WORKFLOWS.md (Phase 7 marked built, the restart sections tidied); the decision register (D43, D61, D74 to D76 to Built; new decisions); INTEGRATION.md unchanged; TO-DO tidied; CLAUDE.md gets the line about restart behaviour for new step types. Both suites side by side.

## The sample (proposed): `DEV-RESTARTS_SAMPLE`

A workflow shaped to show each choice, loaded into the seed and into `autoapp_dev`:

- **Load**: a job of steps that copies five files one by one (For Each File) and fails at the fourth when told to. Resume skips the three finished and does the rest; the net `FileCount` is five.
- **Post**: a Run SQL step that fails "after sending", so it is unknown: the dialog asks, and each of the three answers can be shown.
- **Reconcile**: waits for Load and Post; it ends Not run when they fail, and Resume starts it.
- **Report**: waits for a job in another frame, to show a frame being resumed on its own.
- Each failure is switched by a variable (`FAIL_AT`), so the same sample can be run to succeed, to fail, and to be resumed; the Simulate step does the failing.

## Risks

- **The old and the new don't both stay true.** Automatic Resume is new, and stops after "Failed (effect unknown)"; existing Reactions are unchanged (proposal 3). The classification comes first (step 0) so this can be tested before it is switched on.
- **Reopening an ended run** is the likeliest place for a subtle bug: a finished run's records (end time, status, Reason, `StatusBeforeOverride`, counts, the checks Explain keeps) were written assuming they are final. Each must be reset or kept on purpose; a test reopens a run in each end state (Failed, Cancelled, Killed, Succeeded) and compares the result with a fresh run of the same items.
- **A half-done step.** Proposal 3 depends on each handler telling the truth about what it knew. The sample and tests force each case; the owner decides the wording of what the dialog says.
- **The control file and the job log** share a life but are different files; a Resume on a job whose log is gone is the case to test.
- **An edited workflow** (proposal 5) is refused in the simple way. If operators meet that often, a merge rule is the next step; it is not in this phase.
- **Frames:** a rerun of one frame while the rest of the tree has moved on (proposal 8) is a rule the owner should see in the diagram before it is final.

## Settled by the owner (2026-10-20)

1. **The control file is its own file** (proposal 1), not the spool. Asked whether the spool, also a local file, makes this reinventing the wheel; answered in proposal 1.
2. **Unknown steps: the operator is asked in a dialog when they choose Resume**, with no waiting state (proposal 3).
4. **A Reaction's Rerun has two options**, Restart from the beginning and Resume from failure (proposal 13).
5. **Two parts**, Advanced… second.
6. **Reopening is refused for an edited workflow** unless every item still exists (proposal 5). Handling this properly is a roadmap item the owner is adding.
7. **Hold at… is left out**, with Hold for an operator.
8. **A Succeeded run is reopened by Advanced only** (proposal 5).
9. **"Failed (effect unknown)"** is the name of a failure where it is not known whether the step changed anything (proposal 3).
10. **A new Reaction's Rerun defaults to Resume from failure**; existing Reactions stay Restart from the beginning (proposal 13).
11. **Option (a):** only an automatic Resume stops after "Failed (effect unknown)"; an automatic Restart still runs (proposal 3).

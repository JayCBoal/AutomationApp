# Workflows, Phase 1: the plan

The MVP of [WORKFLOWS.md](WORKFLOWS.md) ("Implementation in phases"): **a workflow of jobs with dependencies runs, and you can see what happened.** It answers the first RunMyJobs shortcoming (flexible dependencies) and lays the foundations the later phases build on.

Status: **proposed 2026-10-17, not yet reviewed by the owner.** The decisions needed are at the end.

## What Phase 1 includes, and what it leaves out

- **In:** workflows made of existing (shared) jobs; prerequisites between them (Succeeded, Failed, Ended, return codes; All or Any); running a workflow by hand; Not run cascading; a final status and `Reason`; the Outline view for editing and for watching a run; run records linked to Job History.
- **Out, for later phases:** embedded jobs and workflows (6), Reactions (3), outside dependencies (5), SQL conditions (4), restarts (7), the diagram (2), Find (2 and 6), Disable here (3), time-based Reactions (8).
- **The model is built for the full design from the start:** names unique within a workflow, a path for every job, attempts on job runs, and columns for nesting and conditions, so later phases add behaviour without reshaping data.

## The steps

Each step is committed and tested on its own.

### 1. Model and migration

- **Workflows**, a new kind of definition beside jobs (a `MasterObject` of type `WORKFLOW`), with a `WorkflowKey` following the same rules as a job key. Like jobs, they get variables, tags and the Audit Log.
- **Workflow items:** each job used in a workflow: its name (unique within the workflow), the job it uses, its join rule (All or Any), and its place in the outline. Columns for embedded items and nesting exist now and stay empty until Phase 6.
- **Prerequisites:** the waiting item, the item it waits for, and the test: Succeeded, Failed, Ended, or return codes (`0-4`, `0, 4`). A column for a SQL condition exists now and stays empty until Phase 4.
- **Workflow runs:** status, `Reason`, start and end, and one row per item for its state in the run (not started, waiting, running, succeeded, failed, not run), so the run shows jobs that never started without making job runs for them.
- **Job runs gain** their workflow run, their path in it, and their attempt (1 for now).
- A migration script that keeps existing data (SQLite and MariaDB); the DDL and diagrams regenerated; the schema check updated; `autoapp_dev` backed up and migrated.

### 2. Saving workflows (API)

- Create, read, save and delete, recorded in the Audit Log.
- Checks on saving, each with a plain message: names unique within the workflow; no job waiting on itself; **no loops** ("Stage waits for Validate, which waits for Stage" is refused, naming the loop); every job used must exist.

### 3. The workflow runner

- `python3 -m engine.workflow_runner --workflow-key ... --run-id ...`, started by the server as the Run Job page starts the job runner.
- It reads the definition once, at the start: editing a workflow does not change a run already going.
- Each second: start every job whose prerequisites hold, with the job runner, as a scheduler would (scheduler name "AutoApp workflow"); mark Not run whatever can never run, cascading; record each item's state.
- It ends when every item has a final status: Failed if any job failed, otherwise Succeeded.

### 4. Pages

- A **Workflows** search page, in the navigation bar.
- A **workflow page** in the Outline view: add a job (its name defaults to the job key), set prerequisites (pick a job and a test), All or Any, save, delete, **Run**; its recent runs listed.
- A **workflow run page**: the same outline with live states, each job linking to its job log.
- **Job History** gains a Workflow column and filter.

### 5. Sample data and docs

- A sample workflow made from the existing sample jobs, in the seed data, so the dev database and the demo have one.
- CHANGE_LOG, PROJECT_BLUEPRINT, and tests at every step, including UI tests for editing and for a run.

## Decisions needed

1. **How the workflow runner reaches the data.** Recommended: it reads and writes the database directly, as the server does. It runs beside the server, not on an agent, so it does not need the API layer the job runner uses. Job runners still report through the API, as now.
2. **Job History.** Recommended: a Workflow column and filter, with each workflow's runs listed on its own page. The alternative, one merged list with workflow runs as expandable rows, is nicer but more work, and better done once the diagram exists.
3. **A Cancel button in Phase 1.** Cancel belongs to Phase 3, but testing the MVP will need a way to stop a workflow. Recommended: include a minimal "Cancel: start nothing more" now.
4. **The test workflow.** Is a sample made from the existing jobs enough, or is there a specific shape to prove first (a fan-out and join, a failure path)?
5. **Prerequisites that aren't satisfied** (proposed in [WORKFLOWS.md](WORKFLOWS.md)): Phase 1 needs only "can never hold: Not run, cascading", already decided. Waiting limits, optional prerequisites and "can't start" choices arrive with outside dependencies (Phase 5), unless wanted sooner.

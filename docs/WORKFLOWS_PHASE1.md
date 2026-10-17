# Workflows, Phase 1: the plan

The MVP of [WORKFLOWS.md](WORKFLOWS.md) ("Implementation in phases"): **a workflow of jobs with dependencies runs, and you can see what happened.** It answers the first RunMyJobs shortcoming (flexible dependencies) and lays the foundations the later phases build on.

Status: **reviewed with the owner 2026-10-17; one proposal open (below).**

## What Phase 1 includes, and what it leaves out

- **In:** workflows (a kind of Job) made of existing jobs; prerequisites between them (Succeeded, Failed, Ended, return codes; All or Any); running a workflow by hand; Not run cascading; a final status and `Reason`; a minimal Cancel; the Outline view for editing and for watching a run; one Job History for job and workflow runs.
- **Proposed for Phase 1 as well:** the Simulate step type, a step setting the job's return code, and Success return codes on a job (see the open proposal).
- **Out, for later phases:** embedded jobs and workflows (6), Reactions (3), outside dependencies and the rest of "prerequisites that aren't satisfied" (5), SQL conditions (4), restarts (7), the diagram (2), Find (2 and 6), Disable here (3), time-based Reactions (8).
- **The model is built for the full design from the start:** names unique within a workflow, a path for every job, attempts on job runs, an owner column for embedded jobs, a column for conditions, so later phases add behaviour without reshaping data.

## Decided

- **A workflow is a kind of Job** (`JobType` *steps* or *workflow*): a common core in Jobs, type-specific content beside it (steps in JobSteps; items and prerequisites in their own tables). Pages and runners choose by type. See WORKFLOWS.md.
- **The workflow runner works on the database directly**, beside the server (the server's own "virtual queue", in ActiveBatch terms). Job runners still report through the API, as now.
- **One Job History:** a workflow's run is a job run; its job runs are listed as rows of their own with a **Parent run** column linking to it, and a filter for "this run and its children". It becomes a tree once the outline and diagram can show it.
- **A minimal Cancel:** "start nothing more"; running jobs finish. The full Cancel and Kill come with Reactions (Phase 3).
- **The sample:** a workflow made from the existing sample jobs, plus Simulate jobs if agreed, to show a fan-out and join, a failure path and a return-code branch.

## The steps

Each step is committed and tested on its own.

### 1. Model and migration

- **Jobs** gain `JobType` (`STEPS` for every existing job, or `WORKFLOW`), `OwnerJob_id` (the workflow an embedded job belongs to; empty until Phase 6) and, if agreed, `SuccessReturnCodes` (`0` unless set).
- **Workflow items:** each job a workflow uses: its name (unique within the workflow), the job it uses, its join rule (All or Any), and its place in the outline.
- **Prerequisites:** the waiting item, the item it waits for, and the test: Succeeded, Failed, Ended, or return codes (`0-4`, `0, 4`). A column for a SQL condition exists now, empty until Phase 4.
- **Job runs gain** `JobType`, `ParentRun_id` (the workflow run a job run belongs to), their path in it, their attempt (1 for now), their return code and `Reason`.
- **Workflow run items:** one row per item of a workflow run, for its state (not started, waiting, running, succeeded, failed, not run, cancelled), so a run shows jobs that never started without making job runs for them.
- A migration script that keeps existing data (SQLite and MariaDB); the DDL and diagrams regenerated; the schema check updated; `autoapp_dev` backed up and migrated.

### 2. Saving workflows (API)

- A workflow is created, read, saved and deleted like a job, recorded in the Audit Log; saving one checks: names unique within it; no job waiting on itself; **no loops** ("Stage waits for Validate, which waits for Stage" is refused, naming the loop); every job used exists; a workflow does not use itself, directly or through another.

### 3. The workflow runner

- `python3 -m engine.workflow_runner --job-key ... --run-id ...`, started by the server as the Run Job page starts the job runner. Starting a job whose type is workflow starts this instead, so the Run Job page and a scheduler can start a workflow by its key.
- It reads the definition once, at the start: editing a workflow does not change a run already going.
- Each second: start every job whose prerequisites hold, with the job runner (scheduler name "AutoApp workflow"), its run pointing to the workflow's; mark Not run whatever can never run, cascading; record each item's state; after a Cancel, start nothing more and mark what has not started Not run (Reason `CANCELLED`).
- It ends when every item has a final status: Failed if any job failed, otherwise Succeeded.

### 4. Pages

- **Jobs** lists workflows too, with a Type column and filter; **New workflow** beside New job.
- A **workflow page** (the job page, choosing by type) in the Outline view: add a job (its name defaults to the job key), set prerequisites (pick a job and a test), All or Any, save, delete, **Run**, **Cancel** while it runs; its recent runs listed.
- A **workflow run** view: the same outline with live states, each job linking to its job log.
- **Job History**: workflow runs and job runs together, with Type and Parent run columns and the "this run and its children" filter.

### 5. Sample data and docs

- The sample workflow in the seed data, so the dev database and the demo have one.
- CHANGE_LOG, PROJECT_BLUEPRINT, and tests at every step, including UI tests for editing and for a run.

## Proposed, to settle

- **Simulate and return codes in Phase 1.** The Simulate step type (logs given lines, waits a given time, exits with a given return code, optionally fails with a message) lets workflows be built and tested without real jobs. With it, two small pieces of Phase 3 would move into Phase 1, so return-code prerequisites can be shown working: a step can set the job's return code (Simulate does), and Success return codes on a job (`0` unless set; a code on the list means Succeeded). A new step type comes with everything CLAUDE.md asks of one (help, preview, operation records, masking, tests).

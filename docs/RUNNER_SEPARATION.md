# Separating the server and the runner

Drafted 2026-10-23. Phase A (the `core` package) is built (2026-10-24; see below for what differed from the plan); Phases B and C wait on the owner decisions in Open questions 2, 3 and 6.

## Aim

The job runner never touches the database. It talks to the server only through the API. The workflow runner is scheduler logic and stays on the server side, with database access through a shared `core` package.

Why now (owner, 2026-10-23): this is how the runner should have been built, and each new feature that reads or writes run records directly makes the later change harder.

## Two runners, two answers

| | Where it runs in production | Database access |
|---|---|---|
| Job runner (`engine/runner.py`, one process per job run) | The scheduler's agent hosts | None. API only. |
| Workflow runner (`engine/workflow_runner.py`, one process per workflow run) | Server side, beside the database | Yes, through `core`. |

The workflow runner decides sequencing, checks prerequisites, applies Reactions and creates run records. That is the scheduler's job. It starts jobs on agents; it is not one of them. (Today it starts them as local processes. Dispatching to a remote agent is the agents work in HOSTING.md, not part of this plan.)

## What the code looks like today (counted 2026-10-23, branch workflows-phase8)

- `engine` has 38 modules plus `handlers/`; `app` has 29 plus `routers/` and `connectors/`; about 13,200 lines in all.
- **engine imports app** in 16 modules, but almost always only `app.models` (14 modules) and `app.database` (2). The exceptions:
  - `workflow_runner` and `workflow_clock` import `app.alert_outbox` (addresses, to queue Notify mail);
  - `workflow_runner` imports `app.workflow_store.workflow_problems`;
  - `spool_delivery` imports `app.telemetry_ingest.ingest_records`.
- **app imports engine** in 24 modules, from 25 different engine modules. The most used: `scope_engine` (6 app files), `handlers`, `tag_vars`, `return_codes` (4 each), then `step_catalog`, `frames`, `step_tree`, `conditions`, `workflow_conditions`, `workflow_vars`, `control_file`, `reopen`, `reopen_tree` (3 each). `app.routers.history` even imports `engine.runner.find_earlier_attempt`.
- **engine modules the server never imports** (so they stay in `engine`): `date_mask`, `executor`, `file_age`, `job_clock`, `outside_state`, `rename_mask`, `reopen_counts`, `run_context`, `spool_delivery`, `telemetry_client`, `workflow_runner`.
- **Tests:** 78 test files import `app.models` or `app.database`; 32 import `engine`. Module paths also appear as strings in `app/routers/launches.py` (how runs are started), `create_dev_db.py`, `demo/run_demo.py`, the Stand-in Scheduler, README.md and a few docs.
- The job runner's direct database use is small and visible (`runner.py`: look up the job, read and write its run, read secrets for masking), but it also reaches the database indirectly through variable resolution (`scope_engine`, `tag_vars`, `step_params`, `preflight`, `run_values`). That indirect part is the real work of Phase B.

## Phase A: the `core` package (no behaviour change)

**Goal:** `app` and `engine` import `core`; neither imports the other.

**Moves into `core`:**
1. `app/models.py`, `app/database.py`.
2. The 25 engine modules the server uses, each checked first: if only the runner really uses it, it stays and the server's import is the thing to question.
3. Pieces that cross the line the other way, decided one by one:
   - `app.alert_outbox.addresses` and `app.workflow_store.workflow_problems` (used by the workflow runner): into `core`, or the workflow runner is treated as server-side and may import `app` services. See Open question 1.
   - `app.telemetry_ingest.ingest_records` (used by `engine.spool_delivery`): the database-writing half is server-side; `spool_delivery`'s direct-load path goes away in Phase B.
4. `engine.runner.find_earlier_attempt`: moves out of the runner into `core` (a server page should not import the runner).

**Rules after the split:** `core` imports neither package. `app` and `engine` never import each other. A test (a few lines scanning imports) enforces it so it cannot drift back.

**Mechanics:** do it in small steps, one module group at a time, full tests between groups. `git mv` so history follows. Update: CLAUDE.md layout, `dev_env.sh`/`pyproject.toml` (so `core` is importable; this touches TO-DO 8), `SQL/generate_ddl.py`, `docs/generate_diagrams.py`, `create_dev_db.py`, `launches.py` (module path used to start runners), `demo/`, the Stand-in Scheduler, README and the docs that name modules. Subprocess start strings (`-m engine.runner`) stay valid because the runner stays in `engine`.

**What differed from the plan (found while doing it):** the step handlers had to move too, because the server uses them for the catalog and validation and the pre-run check calls them; that pulled in the telemetry client and the spool transport (now `core/spool.py`). `job_problems` and `workflow_problems` had to move because the workflow runner called a router function. `workflow_clock` and `alert_outbox` moved with the Notify code. One exception remains: `engine/spool_delivery.py` loads records through `app.telemetry_ingest` when no API is set; Phase B removes that path.

**Done when:** import rule test passes; `autoapp_tests` green on both databases; demo setup and start work; no change in any page or API response.

**Needs from the owner:** nothing beyond approval of the plan. No model or schema change; no INTEGRATION.md change.

## Phase B: the job runner uses the API

**Goal:** `engine/runner.py` and what it imports do not import SQLAlchemy models, `core.database`, or anything that opens a database session. Decisions R1 to R5 in [RUNNER_SEPARATION_DECISIONS.md](RUNNER_SEPARATION_DECISIONS.md) shape it.

**The steps, in order:**
1. **Runtime flag on variables (R2).** A column (off by default, on for secrets), a migration for both databases, a tick box in the editor, the rule for a normal variable that refers to a Runtime one, and a warning in the editor. Built first because the payload depends on it.
2. **Split `scope_engine`** into layering (works out the winning value for each name, on the server) and interpolation (fills in placeholders, in the runner). Behaviour unchanged; tests first.
3. **Agents and tokens (R4).** The Agents table, a default `local` agent, run assignment, and a check on the init and Runtime-fetch calls.
4. **Run at submission (R1).** The run record is created when a run is submitted, in a state meaning "not started". Init finds it by instance ID, or creates it when there is none.
5. **The payload (R2, R3).** `POST /api/v1/jobs/init` returns the job, its full step tree (today flat, used by nothing), the layered values, the names of the Runtime variables, the secrets to mask in logs, a version and a "valid until" time.
6. **Runtime fetch (R2).** One call, before step 1: the run ID and the names; the server returns the values and records what it gave.
7. **Job History on a small path of its own.** Start, process ID, end, status, return code, and the outputs a workflow needs (`FileCount`, `Bytes`), reported promptly and retried. Operations stay in the spool and go in the background or by a periodic sweep, never holding up a step. The direct database load in `engine/spool_delivery.py` goes, and with it the last known exception in the boundary test.
8. **The runner without the database.** Remove its imports of models and database; a test fails if they come back.

**Failure rules (R3):**
- Server unreachable at start: the job does not start; the runner exits with a clear message.
- Server unreachable mid-run: the job keeps running. The end report is written to the spool first, always, and sent when the server is back.
- Reporting never makes a step wait more than a short, bounded time (replacing today's 5-second wait on every batch).
- A run whose end report never arrives stays as it does today. Marking it Unknown and reconnecting when the agent returns arrives with Queues and Agents (R9, last section).

**Tests:** the runner tests move from direct database setup to a running test server. Expect a slower suite; measure and report.

**INTEGRATION.md:** the runner's command line and the way a scheduler passes an instance ID do not change (R1). Anything that does change what an external scheduler must do needs the owner's approval first.

**Done when:** an import check shows the job runner and everything it loads is database-free; the demo runs jobs and workflows end to end; the failure rules have tests; the suite is green on both databases.

## Phase C: the workflow runner settles on the server side

Smaller, and partly done by Phase A: it imports `core`, not `app`. Remaining: decide how it starts jobs (still local processes; the later agents work replaces that), and make sure it learns each job's outcome from Job History alone (never the operations table), as the telemetry principle says. Most of this already holds; Phase C is a check plus tests.

## Decisions and open questions

Decided: see [RUNNER_SEPARATION_DECISIONS.md](RUNNER_SEPARATION_DECISIONS.md), R1 to R7. R8 and R9 settle agent assignment and the status of a run that has not started; R8's Queue design, the payload snapshot, the active-runs table and the Unknown status are separate items (roadmap inbox). Still open: sequencing against the rest of the roadmap.

## How we test

The full suite takes about 40 minutes and blocks code changes while it runs, so it is not run after every step (owner and Claude, 2026-10-24).

1. **Every step:** the test files for the area touched, `tests/test_package_boundaries.py`, and an import check of `app`, `engine` and the scripts in `SQL/` and `demo/`.
2. **Every commit:** a quick tier, the whole suite except the slow browser (UI) tests, run in the background while documents and designs are worked on. The split is set after the next full run is timed with `--durations`.
3. **The full suite (both databases):** at the end of each sub-project and before any merge; after risky steps (a schema migration, an API change the pages use, a mass move of files); and whenever the owner is about to step away, so the result is waiting next time.

Commits stay small, one per step, so a failure can be traced to the step that caused it. A failure in a known flaky test (TO-DO 10; the MariaDB "record has changed" error seen once on 2026-10-24) is rerun on its own before it is treated as real.

## Order of work

1. Plan agreed (this document). Done.
2. Phase A, the `core` package. Done and merged to `main` 2026-10-24.
3. Phase B steps 1 to 3: the Runtime flag, the `scope_engine` split, agents and tokens. A full suite run at the end of step 3.
4. A short design session on the run tables: active runs and a read-only Job History, the "Created" status, the payload snapshot, how Queues and Agents attach (roadmap inbox).
5. Phase B steps 4 to 8 on the agreed run model. A full suite run at the end.
6. Phase C check.
7. Then Queues and Agents, then Monitoring.

## Not in this plan

Agents on other hosts and dispatch to them; full API authentication, encryption of stored secrets and vault connectors; moving the `Operations` table off the critical path beyond what Phase B needs; the lifecycle audit table (it follows from Open question 2 but is its own item).

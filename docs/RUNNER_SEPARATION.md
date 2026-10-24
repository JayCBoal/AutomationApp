# Separating the server and the runner

Drafted 2026-10-23. Phase A (the `core` package) is under way; Phases B and C wait on the owner decisions in Open questions 2, 3 and 6.

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

**Done when:** import rule test passes; `autoapp_tests` green on both databases; demo setup and start work; no change in any page or API response.

**Needs from the owner:** nothing beyond approval of the plan. No model or schema change; no INTEGRATION.md change.

## Phase B: the job runner uses the API

**Goal:** `engine/runner.py` and what it imports (handlers, step_params, etc.) do not import SQLAlchemy models, `core.database`, or anything that opens a database session.

**The API surface the runner needs (to be designed in detail):**
1. **Init:** `POST /api/v1/jobs/init` returns the job, its full step tree (today it lists steps flat and nothing uses it), and the variable context. The run record is created here, or at submission (Open question 2), and the run id comes back.
2. **Start and end of run (Job History)** on a small path of its own: start, process ID, end, status, return code, outputs the workflow needs (`FileCount`, `Bytes`). Prompt, small, retried. This is the telemetry direction (D40, TO-DO 10).
3. **Operations** (the audit trail) stay in the spool and go in the background or by a periodic sweep, never holding up a step. `engine/spool_delivery.py`'s direct database load is removed.
4. **Secrets for log masking:** delivered with the init payload (names and values, over HTTPS, in memory only), instead of the runner reading every secret from the database.
5. **Kill and cancel:** the runner already sees these through its process; confirm nothing reads the database for them.

**Variable resolution** is the main design question (Open question 3).

**Authentication:** a shared token per agent or per installation, sent as a header, checked on `/api/v1/jobs/*` and the run-reporting endpoints. Full API authentication stays in TO-DO 6; this is the smallest version the runner needs. Tokens never appear in logs.

**Failure rules (to confirm):**
- Server unreachable at start: the job does not start; the runner exits with a clear message and the scheduler sees the failure to start. (A job cannot start without its payload.)
- Server unreachable mid-run: the job keeps running; start/end reports and operations wait in the spool and are retried; the end report is written to the spool first, always.
- Reporting must never make a step wait more than a short bounded time (replaces today's 5-second wait on every batch).
- A run whose end report never arrives is picked up by a sweep and marked, as in TO-DO "Killed runs".

**Tests:** runner tests move from direct database setup to a running test server (the existing `conftest.py` already starts subprocess runners; it would start a server too). Expect the suite to get slower; measure and report.

**INTEGRATION.md:** the runner's command line and the way a scheduler passes an instance ID should not change. If the init payload or run-creation point changes what an external scheduler must do, that is a contract change and needs the owner's approval before it is made.

**Done when:** an import check shows the job runner and everything it loads is database-free; the demo runs jobs and workflows end to end; the failure rules above have tests; the suite is green on both databases.

## Phase C: the workflow runner settles on the server side

Smaller, and partly done by Phase A: it imports `core`, not `app`. Remaining: decide how it starts jobs (still local processes; the later agents work replaces that), and make sure it learns each job's outcome from Job History alone (never the operations table), as the telemetry principle says. Most of this already holds; Phase C is a check plus tests.

## Open questions (owner decisions, with my lean)

1. **May the workflow runner import server code (`app`), or must everything it shares be in `core`?** Lean: shared logic goes in `core`; the workflow runner may call small server services only through `core`. Keeps the rule simple (no cross-imports at all).
2. **Who creates the run record, and when?** Today the runner, when it starts. Alternative: the server, at submission (a "Submitted" state), which also serves the lifecycle audits item. Lean: server, at submission, in Phase B. For an external scheduler this needs the owner's approval (INTEGRATION.md).
3. **Who resolves `${...}`?** (a) The server resolves everything and sends the runner a finished payload (simplest runner; secrets travel in the payload; Resume still reuses the control file's values). (b) The runner receives raw definitions plus variable layers and resolves locally (keeps `scope_engine` in the runner; more data over the wire). Lean: (a), because it removes the runner's biggest indirect database use and matches how WLAs hand an agent a prepared job.
4. **Secrets in the payload.** Allowed over HTTPS to an authenticated runner, never written to the spool or logs unmasked. Needs encryption at rest (TO-DO 6) before production; fine for the demonstrator.
5. **Authentication for the runner:** shared token now; per-agent identity later.
6. **Start when the server is down:** fail to start (lean), or run from a cached payload. Cached payloads add staleness questions. Lean: fail to start.
7. **Where decisions are recorded:** a new "Runner separation" section in the decision register, numbered from the next free D number.

## Order of work

1. Plan agreed (this document).
2. After the Workflows final commit, merge and push: new branch from `main`.
3. Phase A in small steps, tests green after each group.
4. Phase B plan refined (API shapes, payload, failure rules) and agreed before any build.
5. Phase B in steps: init payload; Job History path; spool delivery without the database; runner without models; tests on a live server.
6. Phase C check.

## Not in this plan

Agents on other hosts and dispatch to them; full API authentication, encryption of stored secrets and vault connectors; moving the `Operations` table off the critical path beyond what Phase B needs; the lifecycle audit table (it follows from Open question 2 but is its own item).

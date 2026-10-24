# Runner separation: decisions

Decisions about separating the server and the runner, with the reason for each and what else was considered. The plan is [RUNNER_SEPARATION.md](RUNNER_SEPARATION.md). Workflow decisions stay in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md). A decision that is replaced stays here, marked Replaced, pointing to what replaced it. Before changing behaviour that one of these covers, read its reason.

Numbered R1, R2 and so on. All decided with the owner on 2026-10-24 unless marked.

## R1. The server creates the run record at submission

- **Decided:** the run record exists from the moment a run is submitted (by a person, a schedule or a workflow), in a state that says it has not started. The runner's init call finds it by instance ID and starts it.
- **If there is none** (a scheduler that starts the runner with `--job-key` and `--instance-id` and never told AutoApp), init creates it, as the runner does today. Existing callers keep working; INTEGRATION.md does not change for them.
- **Why:** the run exists to be audited, held, released and queued before it starts, and the next-run scheduling model presubmits runs. It also gives the lifecycle audits (roadmap inbox, 2026-10-23) somewhere to start from.
- **Considered:** the runner creating it at start (today). Nothing changes for schedulers, but there is nothing to record before the run starts.

## R2. The server does the layering; the runner interpolates; variables can be marked Runtime

- **Decided:**
  - The server works out which value wins across all the variable layers (precedence, tags, workflow levels, conflicts) and sends the runner a finished set of values in its payload. The runner does not import the layering code and does not read the database.
  - The runner still fills in `${...}` and `%{...}` in step parameters, because some of it exists only on the host or during the run (`${ENV:...}`, step outputs, date masks, loop values).
  - A variable can be marked **Runtime**. Others are resolved when the run is submitted and frozen. A Runtime variable is left out of the payload, listed by name, and fetched from the server.
  - The fetch is **one call, made once, before step 1**, for all the run's Runtime variables. The runner sends the run ID and the names; the server works out the scope from the run. Nothing is fetched mid-run, so a running job never depends on the server. Resume reuses the stored values, as it does now.
  - **Secrets default to Runtime.**
  - A normal variable whose value refers to a Runtime one is left partly resolved by the server; the runner finishes it after the fetch. The editor flags it.
  - When the same name is set in several layers, the winning value's flag decides.
  - The server records what it hands out. That is the source for the payload snapshot (operations, not audit; roadmap inbox) and for any later audit of run values (TO-DO 19).
- **Why:** with next-run scheduling a run can wait hours between submission and start; Runtime lets a variable that must be current stay current, and keeps rotated secrets out of anything stored ahead of time. Doing the layering on the server takes the database off the runner and shows tag conflicts at submission instead of at the start of a run. The Runtime flag is how RunMyJobs and ActiveBatch do it.
- **Considered:**
  - The runner resolving everything (the original design, to spare the scheduler): it needs every layer and every secret in scope sent to it, and the runner needs the layering code and database access.
  - The runner asking the server for each variable as it needs it: chatty, and puts the server in the middle of a running job.
  - Refusing, at save time, a normal variable that refers to a Runtime one: simpler, but a restriction users would meet without good reason.
- **Effects:** a new column on variables (off by default, on for secrets) with a migration for both databases; a tick box in the variable editor; `scope_engine` split into layering (server side, `core`) and interpolation (shared).

## R3. Pull at start; the payload is built to be cached later

- **Decided:** in Phase B the runner pulls its payload when it starts. If the server cannot be reached, the job does not start, with a message saying so. The payload is complete, versioned, and carries a "valid until" time, so that holding upcoming runs on the agent host can be added later, as part of the scheduling build.
- **Why:** keeping upcoming runs on the agent is the real way to ride out a server outage, but it brings staleness (a job disabled or edited after it was presubmitted), secrets stored on the host, and duplicate starts. Those belong with the scheduling model, which is not built yet. A job that has Runtime variables cannot start from a cached payload when the server is down; one that has none can.
- **Considered:** a cached payload now. Deferred, not rejected: the owner's view is that it is the obvious choice once presubmission exists.

## R4. A token for each agent, in its minimal form

- **Decided:** an Agents table (name, host, hashed token) with a default `local` agent. Each run is assigned to an agent. An agent can fetch only the payload and Runtime values of runs assigned to it. Tokens are shown once when issued and never logged.
- **Why:** once secrets travel in payloads, a shared token would let any holder fetch any run's secrets. The one-machine setup can still test it, with two agents on the same host and a check that one is refused the other's run. It is the first piece of the Security item.
- **Considered:** a single shared token for now. Cheaper, but it has to be replaced as soon as secrets are in the payload.

## R5. Secrets may travel in the payload

- **Decided:** over HTTPS, to an authenticated agent, held in memory, never written to the spool or to logs unmasked. Secrets default to Runtime (R2), so none sits in a payload stored ahead of time. Encryption of stored secrets stays in the Security item.
- **Why:** the runner needs the value to use it. The exposure is no greater than reading it from the database, and the agent no longer holds database credentials.

## R6. Shared code lives in `core`

- **Decided:** anything both the server and a runner use lives in `core`, which imports neither. `app` and `engine` never import each other. `tests/test_package_boundaries.py` enforces it, with a short list of known exceptions that each have a plan to go.
- **Why:** it is the rule that makes the server and the runner separable. A list of exceptions that can only shrink keeps it honest.
- **Found while building Phase A:** the step handlers, the telemetry client and the pre-run check had to move to `core` as well (the server uses the handlers for the catalog and validation, and a router function was being called by the workflow runner).

## R7. These decisions have their own file

- **Decided:** here, not in WORKFLOW_DECISIONS.md, which is for decisions about building the Workflows feature.

## R8. A run's agent comes from an explicit Queue, not from a Site or an Endpoint

- **Decided (owner, 2026-10-24):** a Queue object is assigned explicitly. A base Queue belongs to an agent on a host; Queues can be nested for load balancing. Phase B only needs a default Queue for the `local` agent, so every run has an agent (R4). Queues themselves are a separate design (roadmap inbox).
- **Not tied to a Site:** a Site is a remote (S)FTP site, not a place an agent runs. **Not tied to an Endpoint:** a landscape would normally keep endpoints on shared storage (NAS shares), so they do not belong to one agent.
- **Check, when Queues are built:** if a job's Queue is on Agent A and a step names an Endpoint on local storage of Host B, warn or refuse.
- **Why:** the host a job runs on is an operations decision, separate from where its files are.

## R9. The status of a run that has not started is "Created"

- **Decided (owner, 2026-10-24):** "Created", not "Submitted", which means different things in different workload automation products.
- **Phase B:** the run record R1 creates carries this status in the existing run table. Splitting runs into a table of active and recent runs, with Job History as a read-only archive, is a separate design and not part of this plan (roadmap inbox).

## Moved out of this plan (owner, 2026-10-24)

- The snapshot of a run's payload, for operations rather than audit: not runner separation. It needs aggressive, system-configurable archiving and purging, and secrets left out. Roadmap inbox.
- The split between a table of active and recent runs and a read-only Job History: not runner separation, but it shapes where R1's run records live and what Monitoring reads. Roadmap inbox.
- A run's status when its agent is unreachable ("Unknown", then a reconnect to the job when the connection returns): arrives with Queues and Agents. Phase B does not add a sweep for runs whose end report never arrives; until then such a run stays as it is today.


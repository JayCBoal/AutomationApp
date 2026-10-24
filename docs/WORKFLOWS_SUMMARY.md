# Workflows: what was built, and how to see it

A summary of Workflows Phases 1 to 8 (2026-10-17 to 2026-10-23), with a tour for someone seeing it for the first time. The design is in [WORKFLOWS.md](WORKFLOWS.md); each phase has its own plan (`WORKFLOWS_PHASE1.md` to `WORKFLOWS_PHASE8.md`); every decision and its reason is in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md) (D1 to D184).

## What a workflow is

A workflow is a set of jobs with dependencies between them, designed in AutoApp and run by AutoApp. It answers six shortcomings of RunMyJobs job chains (see [PROJECT_GOALS.md](PROJECT_GOALS.md)). AutoApp plays the scheduler here, so the design is the point; the Simulate step stands in for real work.

## What each phase added

| Phase | What it added | Shortcoming answered |
| :--- | :--- | :--- |
| 1. The MVP | Workflows of jobs with prerequisites (Succeeded, Failed, Ended, return codes; All or Any); a workflow runner; Not run cascading; a final status and its reason; run records in Job History; the Outline view and a live run | 1. Flexible dependencies |
| 2. The diagram | Diagram and Outline views, coloured and styled lines, markers, run states shown live | 5. A compact, complete picture |
| 3. Return codes and Reactions | What happens after a job ends: Count as succeeded or failed, Rerun, Rerun from…, Skip…, Skip the rest of a branch, Kill the workflow, Start a workflow; Set Return Code step; Disable here | 2. Granular decisions downstream |
| 4. Conditions | Prerequisites written as readable rules over a job's outputs (`%{Load.FileCount}`), with help, validation, a builder and Explain; Succeeds when; workflow variables and tags | 3. Conditions people can read and write |
| 5. Outside dependencies | Waiting on a job in another workflow, on files at an endpoint, on a time window or date; optional prerequisites that time out; their markers; Needed by | 4. Every dependency visible |
| 6. Embedded and shared workflows | Jobs and workflows embedded in a workflow (kept out of the lists, named under their parent), shared jobs, workflows used as boxes, frames, deep Find | 6. Structure that stays with its parent |
| 7. Restarts | The Rerun menu: Resume from where a job failed (not done, partly done, effect unknown), Restart, Bypass, Don't run, Ignore a prerequisite, From a chosen job; Advanced… item by item; a Reaction that resumes a job or a whole frame; a Restarts list on the run | Restarting part-way through |
| 8. Time-based Reactions | Whens *has not started by*, *has not ended by*, *runs longer than* (a time of day, a length, or a percentage over the job's recent average), *within N minutes of being ready*; Mark as late (a Late flag, not a status); Notify through alerts and an outbox sent by SMTP | The SLA reach of RunMyJobs, made friendlier |

Behind these: a decision register with the reason for each choice, a migration for each change to the models (`autoapp_dev` kept its data), a CHANGE_LOG entry per step, and tests on both SQLite and MariaDB.

## Seeing it in action

### Set up

1. In a terminal, from `~/projects/AutomationApp/CodeRepo`: `source dev_env.sh`, then `autoapp_server`. Open `http://localhost:8000`.
2. In a second terminal, `source dev_env.sh` and `mail_sink` (only needed for the last sample). Its page is `http://localhost:8026`.
3. The sample workflows below are in `autoapp_dev` already. On a fresh database, load `SQL/Seed_Sample_Data.sql`. Each sample's full walk-through is the comment above it in that file.
4. Open the Workflows list. Each sample is named `DEV-…_SAMPLE`. Open one, switch between **Diagram** and **Outline**, and use **Run**. Results appear in **Job History**, where a workflow run has its job runs under it.

### A tour, in the order the phases built them

1. **Dependencies, the diagram and a live run (Phases 1 and 2): `DEV-MONTH_END_SAMPLE`.** Open it and look at the diagram: two pairs of jobs side by side, a ledger check that waits for both loads, a clean-up that runs whatever happened. Run it and watch the boxes change state. Afterwards open the run in Job History and click through a job run to its log.
2. **Reactions (Phase 3): `DEV-REACTIONS_SAMPLE`.** Run it. The rates feed times out (return code 8), reruns twice, then is counted as succeeded so the workflow carries on. Load_rows ends with code 4, which this use counts as succeeded. Validate fails, reruns from Stage once, then the rest of its branch is skipped. Archive is disabled here and passes through. On each job, open the Reactions box to see the rules, and in the run, the Reactions that fired.
3. **Conditions (Phase 4): `DEV-CONDITIONS_SAMPLE`.** Open the Post item's prerequisite: a rule in readable form (files delivered, and either the rates or the fallback rates are in). Use the builder and the validation, then **Explain** on the run to see which parts held. Fallback_rates doesn't run because Rates succeeded.
4. **Variables (Phase 4): `DEV-VARIABLES_SAMPLE`.** One job is used twice: Summary_EU takes the workflow's values, Summary_US overrides Region and Currency for its own use. Each writes what it got to its log.
5. **Outside dependencies (Phase 5): `DEV-OUTSIDE_UPSTREAM` and `DEV-OUTSIDE_SAMPLE`.** Run UPSTREAM first and put `orders_001.csv` in the billing application's `orders_in` folder. In DEV-OUTSIDE_SAMPLE, Load waits for UPSTREAM's Extract, for orders files left alone for 60 seconds, and for the 06:00 to 22:00 window. Report has an optional wait for a Sunday that times out after a minute and is shown as such.
6. **Frames (Phase 6): `DEV-FRAMES_SAMPLE`.** A month end made of embedded workflows drawn as frames (Extract with US and EU, Transform), a shared job (FX_rates), a workflow used as a box that opens read-only inline, and a line from outside a frame. Embedded items don't appear in the jobs list. Try Find.
7. **Resume (Phase 7): `DEV-RESUME_SAMPLE` and `DEV-UNKNOWN_SAMPLE`.** Run DEV-RESUME_SAMPLE from the Run Job page: it copies five files and fails at the empty fourth. Put something in `restart_4.csv`, then **Rerun ▸ Resume**: the three finished files aren't copied again and the net count is five. DEV-UNKNOWN_SAMPLE fails with "effect unknown"; Resume asks whether to run the step again or count it as done.
8. **Every restart choice (Phase 7): `DEV-RESTARTS_SAMPLE`.** Run it (Load fails). Fix `restart_4.csv`, Resume; Post fails "effect unknown", so choose Count it as done. Reconcile's Balance fails once and the frame's own Reaction resumes it (×2 on the diagram, "by a Reaction" in the Restarts list). Then try **Advanced…** with Don't run on Notify and Ignore a prerequisite on Report, or **From a chosen job**.
9. **Late and Notify (Phase 8): `DEV-LATE_SAMPLE`.** With `mail_sink` running, Run it (about three minutes).
   - At 1 minute Extract is marked **Late**. Look for the Late tag on the run and diagram, the Late column and filter in Job History, and the clock lines ("due by … the next … after the run started").
   - At 2 minutes Transform is marked Late too, but its Notify is skipped, because Extract was already late. The run's Reactions list says so.
   - Open **Administration, Alert Deliveries**: one message, Sent. Open `http://localhost:8026`: the message arrived.
   - On **Alerts**, try **Send a test**, edit the message (it can use `${...}` values and the run's facts) or change a time and run again.

### What to look for as you go

- **Nothing is hidden.** Every dependency, outside or inside, is drawn; every Reaction that fired is listed on the run; Explain says why a condition or a clock came out as it did.
- **Restarts keep a record.** The Restarts list and the Audit Log say who chose what.
- **Late is a flag, not a status.** A late job still Succeeds or Fails; the flag records the missed deadline and its cause.
- **A job never waits for mail.** Notify only adds a row to the outbox; a sender in the server delivers it and retries.

## Not built

These were left out on purpose and are in [TO-DO.md](TO-DO.md) or [ROADMAP.md](ROADMAP.md): the Send email step and the full Alerting design; Hold for an operator; a When written as an expression; Set Return Values; the Operations object and For Each File over an upstream job's files; a snapshot of the resolved values of a run; loops; working-day logic for deadlines; scheduling.

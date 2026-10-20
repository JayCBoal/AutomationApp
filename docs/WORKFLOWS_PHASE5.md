# Workflows, Phase 5: outside dependencies

The fifth phase of [WORKFLOWS.md](WORKFLOWS.md) ("Implementation in phases"): **a job can wait for things outside its workflow, and you can see every one of them.** It answers shortcoming 4 ([PROJECT_GOALS.md](PROJECT_GOALS.md) goal 2): in RunMyJobs a Wait Event in one chain depending on a Raise Event in another is invisible, so nobody can see what a job is really waiting for.

Status: **built (2026-10-19), on branch `workflows-phase5`; awaiting the owner's review.** All ten proposals were agreed with the owner 2026-10-19 (decisions D99 to D105); what was settled while building is D106 to D115.

## Starting point

Already built, and what this phase uses:

- Prerequisites between jobs of one workflow (`WorkflowPrerequisites`: the job's use, the target use, the test, return codes); the Start rule All, Any or Custom; a prerequisite that can never hold makes the job Not run, cascading (D15).
- Custom rules, and the rule that **the jobs a rule names become stored prerequisite rows** (test `RULE`), so every dependency can be drawn (Phase 4, proposal 6).
- The workflow runner polls the database beside the server (D22); `readiness()` is the one place that says whether a job may start.
- Job outputs read as `%{Name.Output}`; unknown (`NULL`) until the job ends.

Designed, not built (decisions D16 to D20, D80): patience on each prerequisite and the consequence on the job; outside targets; which run of another workflow counts; endpoints with a minimum age; time as a built-in value; the markers and Needed by.

## What Phase 5 includes, and what it leaves out

- **In (proposed):**
  - **Targets outside the workflow.** A prerequisite's target is one of: a job in this workflow (as now); **a job in another workflow, or a whole workflow** (its final status); **an endpoint** (files at a path and pattern); **a time condition** (`%{Now.Time}`, `%{Now.Date}`, `%{Now.Weekday}`).
  - **Which run of another workflow counts** (D18): the run executing now, else the most recent completed one. Optional limits, off by default: only if that run ended within N hours; only a run started after this workflow's run started.
  - **Endpoints** (D19): outputs `FileCount` and `Bytes`; a file pattern and a **minimum age** (every file unchanged for N seconds). Local endpoints only. The age test is one shared function, also used by Check Files when its minimum age is built.
  - **Time** (D20): a prerequisite whose condition is on `%{Now...}`; it waits until the condition holds.
  - **Patience and consequence** (D16). On each prerequisite: wait with no limit, up to N minutes, or until a time; and *required* or *optional*. On the job: what "can't start" means, **Not run** (default, cascading) or **Fail** (Failed, Reason `PREREQUISITES_NOT_MET` or `TIMED_OUT`). **Hold for an operator is not in** (it depends on Hold, D58, not built).
  - **Conditions name outside targets** (D17): a target gets a name made from it (`MONTH_END.Extract`, `INBOUND_ORDERS`), editable where two clash; a Custom rule may name only the workflow's own jobs and the targets of the job's own prerequisites; the condition box's help and validation offer them.
  - **Seeing them** (D80): outside targets as dashed boxes at the edge of the diagram, both ways (what this waits for; what waits for this, **Needed by**), with the live state of the outside job in a run; icons for the ones without a source (clock, calendar, `{x}`); the same in the Outline. Clicking an outside box opens that workflow.
  - **A record of what was waited for**: for each outside prerequisite, which run it used and what it found, shown by Explain and in the workflow's log.
  - **Sample, docs and tests:** `DEV-OUTSIDE_SAMPLE`: two workflows, one waiting for a job of the other, a file endpoint with a minimum age, a time window, and an optional prerequisite that times out.
- **Out:**
  - Hold for an operator (needs D58).
  - SFTP and other remote endpoints (until they exist).
  - Embedded workflows and paths into them (Phase 6).
  - What an unlimited outside wait means when there is no daily cycle to end it (needs scheduling: WORKFLOWS.md, "Later").
  - Check Files' own `MinAgeSeconds` / `WaitMinutes` parameters (TO-DO): only the shared age function is built here, per the phase-scope rule.
  - A loop across workflows (a Rerun-workflow Reaction with a limit): TO-DO.
  - Time-based Reactions (Phase 8): they are side effects (notify, mark late), not a prerequisite's patience.

## Proposals to settle with the owner

1. **A prerequisite gets a kind.** `Kind` is JOB (this workflow), OTHER_JOB, ENDPOINT or TIME. OTHER_JOB reuses `TargetItem_id`, which already points at a use and so can point into another workflow. New columns: the endpoint, the file pattern, the minimum age, the time condition, the target's name, the patience (`WaitMinutes`, `WaitUntil`, `Required`, and which prerequisite the clock starts after), and the two look-back limits. On the job's use: `OnUnmet` (NOT_RUN or FAIL). *Agreed.*
2. **When does "up to N minutes" start?** *Agreed (D99).* A choice on the prerequisite: (1) after the job's other prerequisites have held (default); (2) after the first of them holds; (3) after a chosen prerequisite holds; (4) from the start of the workflow run. "Until 02:00" is a clock time and needs no start. The job's waiting message says what it waits for and until when ("waiting for MONTH_END.Extract, until 03:00").
3. **Default wait.** *Agreed (D100).* 24 hours, a system setting ("Default wait for outside prerequisites"), shown on each prerequisite as "Default (24 h)". "No limit" is a deliberate choice and saving it warns. When the limit runs out, the job's `OnUnmet` decides (Not run, or Failed with `TIMED_OUT`).
4. **Optional prerequisites.** *Agreed (D101).* Waited for up to its limit, then dropped from the job's check; the others still decide, and if none are left the job starts. It must have a limit. In a Custom rule its outputs are unknown (`NULL`). The run and the log say it was skipped.
5. **An endpoint prerequisite holds when at least one file matches the pattern and every matching file is old enough.** Anything finer (a count, a size) is a Custom rule over `%{INBOUND.FileCount}`. *Agreed.*
6. **Time window.** `%{Now.Time} BETWEEN '06:00' AND '18:00'` holds while the window is open and waits while it is shut; it is never "impossible", because tomorrow comes. The patience limit is what ends the wait. Server local time, as the other times are. *Agreed (D103).* A window that spans midnight is written `%{Now.Time} IN WINDOW '18:00' TO '06:00'` (after 18:00 or before 06:00 when the end is earlier than the start). `IN WINDOW` is AutoApp's own syntax, not SQL: it is translated into plain comparisons before the condition is worked out, and the help text says so. The builder shows it as "time is between 18:00 and 06:00 (next day)". The plain `OR` form also works.
7. **Loops between workflows.** A waits for B and B waits for A would wait forever. Saving refuses a cycle that runs through other workflows, naming the path. (A cycle inside one workflow is already refused.) *Agreed (D104):* no cycles of prerequisites, within a workflow or between workflows; the message points to Rerun from… A loop across workflows (a "Rerun workflow" Reaction with a limit) is not in this phase: TO-DO.
8. **The other workflow's use is followed by identity, not name**, as renames are (decisions 12 and 17). Renaming a job updates every workflow waiting for it. **Deleting a use that other workflows wait for is refused**, naming them, rather than silently dropping their prerequisites (the foreign key would cascade). *Agreed.*
9. **A whole workflow as a target** (its final status) as well as a job in it. *Agreed (D102):* structural sub-workflows need it, and it is cheap, since a workflow's run is a job run.
10. **The runner stays one process per workflow run** and reads the other workflows' run records, never their files. It does not depend on the operations log (telemetry principle). File checks for endpoints are done by the workflow runner on the server's own disks, so Phase 5 supports local endpoints only. *Agreed (D105).* Where a file prerequisite is checked is the endpoint, as the endpoint says. If agents or queues come, the endpoint reference gains a "checked on" field (ActiveBatch's file constraint names a queue); no column now.

## The steps (proposed)

1. **Model and migration:** the prerequisite kind and its columns; `OnUnmet`; a table of what each outside prerequisite found, per attempt (the run used, the answer, the time); `migrate_outside_dependencies.py`; the default-wait system setting; `autoapp_dev` migrated with a backup in `demo/output/`.
2. **The engine:** a resolver for "current or latest run of that job" (and the look-back limits); the endpoint file check (shared age function); `%{Now...}`; patience clocks and `OnUnmet`; `readiness()` takes all four kinds and says WAIT, HOLDS, NEVER or TIMED_OUT; Custom rules with outside names; the record of what was found.
3. **Checks on save:** an unknown outside target, a name clash, a cycle through other workflows, deleting a use others wait for; warnings for waits with no limit and for endpoints that are not local.
4. **Pages:** the prerequisite editor gets "What it waits for" (this workflow's job, another workflow's job, files, time), patience and required/optional; `OnUnmet` on the job pane; the condition box offers the outside names.
5. **Diagram and outline:** dashed outside boxes both ways, Needed by, clock/calendar icons, live state in a run, click to open.
6. **Sample, docs and tests:** the sample above; CHANGE_LOG, WORKFLOWS.md (Phase 5 marked built), the decision register (D16 to D20 and D80 to Built); engine tests (current-or-latest run, stale limits, minimum age, patience and `OnUnmet`, optional timeouts, cycles, rename and delete); UI tests for the editor and markers. Both suites (SQLite and MariaDB) side by side.

## Decided while building

- **D106** an outside prerequisite is never "impossible": a failed job elsewhere is waited out, and patience ends the wait.
- **D107** `%{Now.Time}` is `HH:MM` (minutes), local time; `BETWEEN` and `IN WINDOW` include both ends.
- **D108** one that holds is looked at again every pass; one that ran out of patience stays so for that attempt.
- **D109** in a Custom rule, a required one that ran out of patience ends the job; an optional one gives unknown values.
- **D110** `OnUnmet` covers both causes; the Reason says which (`PREREQUISITES_NOT_MET`, `TIMED_OUT`).
- **D111** the loop check between workflows is between jobs; a whole workflow waits for all its jobs.
- **D112** what each one found is kept per attempt (`WorkflowPrerequisiteChecks`), and shown on the run.
- **D113** outside names for conditions, with dots allowed; `Now` is reserved.
- **D114** nothing others wait for can be removed from under them; files must be on this server.
- **D115** outside things are shaded (amber for jobs and workflows elsewhere, tagged EXTERNAL; blue for files and times, tagged FILES or TIME), and two toolbar options hide each group as header icons: *Show external references* (on by default) and *Show non-executable dependencies* (off by default). The mockup page was not updated.
- The sample is `DEV-OUTSIDE_UPSTREAM` and `DEV-OUTSIDE_SAMPLE` (two workflows, in the seed's section 9); `autoapp_dev` has the new schema (`SQL/migrate_outside_dependencies.py`) but not the sample.
- **Not built, as planned:** Hold for an operator; remote endpoints; Check Files' own `MinAgeSeconds` and `WaitMinutes` (only the shared age test, `engine/file_age.py`); a loop across workflows (TO-DO 9); time-based Reactions.
- **Left for a later look (TO-DO):** a workflow that others wait for as a whole shows no "Needed by" on its own page.

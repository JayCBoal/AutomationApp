# Workflows, Phase 8: time-based Reactions and Notify

The eighth phase of [WORKFLOWS.md](WORKFLOWS.md) ("Implementation in phases"): **a job or workflow can react to the clock as well as to how it ended: it did not start by a time, did not end by a time, or is running longer than it should. It can be marked late, and people can be told.** It answers the SLA half of shortcoming 2 ([PROJECT_GOALS.md](PROJECT_GOALS.md) goal 2): in RunMyJobs an SLA is a separate feature, wholly apart from job statuses and very complex. Here it is one more kind of *When* in the Reactions list that already exists (D68).

Status: **PLAN AGREED 2026-10-23, all questions answered (F: all three parts of proposal 13).** **Steps 1 (model and migration), 2 (the clock rules, `engine/clock_rules.py`), 3 (the workflow runner watches, `engine/workflow_clock.py`), 4 (the job runner watches, `engine/job_clock.py`) and 5 (alerts, built; full suites pending) , 6 (pages and API) and 7 (the sample `DEV-LATE_SAMPLE` and the docs) built 2026-10-23; the full suites are the last stop before the merge.** The owner's answers to questions A to E are under "Settled by the owner". Decisions are D178 to D183 in WORKFLOW_DECISIONS.md.

## Starting point

Already built, and what this phase uses:

- **Reactions** (Phase 3, 7): a list on a job or on one use of it, in two sections, *What happens next* (first match decides) and *Also* (every match fires). Every When so far is judged once, when the job ends (success, failure, ended, return code). `engine/reactions.py` only judges; the job runner (a job on its own) or the workflow runner (a job in a workflow) carries the result out. Each action that fires, or hit its limit, is a `ReactionEvent` row.
- **The workflow runner** is a process that already looks at every item once a second (`POLL_SECONDS`), reads and writes the database, and knows when each item started. A workflow run has its start time. A timer costs it one comparison per item per pass.
- **A job run on its own** is carried out by the job runner, which on a real agent host never writes the database; it sends records through the spool and telemetry (the telemetry principle, TO-DO 10, D40).
- **Side effects** today: *Start a workflow*. *Mark as late* and *Notify* were designed in WORKFLOWS.md ("Reactions") and left for this phase.
- **Job History** (start, end, duration, status, reason, return code) is the data "longer than usual" compares with.
- **Nothing sends messages yet.** No mail code, no alert object, no Send email step (TO-DO "More step handlers"). Python's built-in mail-sending module (`smtplib`) is enough to send; no package is needed.

## What Phase 8 includes, and what it leaves out

- **In:**
  - **Three new kinds of When**, in the same editor: *it has not started by…*, *it has not ended by…*, *it runs longer than…* (proposals 1 to 4).
  - **Mark as late**: a flag on the run, not a status; shown on the diagram, in Job History, searchable (proposal 5).
  - **Notify**: a side effect that names an *alert*, a small object saying who is told, by email, and what it says (proposals 6 to 8). Available on **every** kind of When, so "failed: notify ops" works too.
  - **Explain** and the run view show each deadline worked out, and what fired (proposal 10).
  - A sample that runs late on purpose (proposal 12).
- **Out (to TO-DO or the roadmap):**
  - **Deciding actions on a time (Kill the job when it runs too long, Count as failed, Rerun).** Time-based Whens take side effects only. A job that hangs is already handled by a prerequisite's patience (D99) for the waiting half; a *Kill when too long* is a separate, small addition later.
  - **"Not started by" for a job on its own.** Nothing exists to watch before a run starts. That needs scheduling to say when a start was expected ([SCHEDULING.md](SCHEDULING.md)). Offered only inside a workflow.
  - **Alerts linked to a tag, application or workflow; acknowledging, escalating, holding repeats back; Teams or webhooks.** These are the roadmap's Alerting design ([ROADMAP.md](ROADMAP.md)). This phase builds the smallest alert that makes Notify real, shaped so those can follow.
  - **The Send email step.** It will share the mail-sending code built here but is a step type, built with the other step handlers.
  - **Conditions that test lateness** (`%{A.Late}`). Late is a record for people, not something a workflow acts on, which also keeps it clear of the telemetry principle.
  - **A watchdog for a dead workflow runner.** If the process watching dies, nothing fires. Runner supervision belongs to hosting.
  - **Working-day calendars.** "By 03:00" is clock time; "by 03:00 on a working day" waits for scheduling's calendars.

## Proposals to settle with the owner

1. **Three Whens, one list.** In the Reactions editor the When gains:
   - *It has not started by…* (a job in a workflow);
   - *It has not ended by…* (a job in a workflow, a workflow, or a job on its own);
   - *It runs longer than…* (any job or workflow).
   - Each is judged while the run is going on, not at its end. The existing four (succeeded, failed, ended, return code) are unchanged.
   - *Recommended.*

2. **How a time is given.**
   - *Not started by* and *not ended by*: a **time of day** ("03:00"), or **relative** ("within 2 hours of the workflow starting"). For a job on its own, relative means from its own start.
   - *Runs longer than*: a **fixed length** ("90 minutes"), or **compared with its own history** ("50% over its average of the last 10 runs", proposal 4). Always from this attempt's own start.
   - *Recommended.*

3. **A time of day means its next occurrence after the run started** (question A). The run starts at 23:00 and "not ended by 03:00" means 03:00 tomorrow; a run starting at 01:00 means 03:00 today.
   - This replaces the earlier note in WORKFLOWS.md ("the day the run started"), which would make the 23:00 run late the moment it begins. It matches D103's way of reading windows that cross midnight, and the rule that a run is not tied to "today" (WORKFLOWS.md, "Which run of another workflow counts").
   - Server local time, as time-window prerequisites use.
   - The editor shows the result for the next run ("works out to 03:00 tomorrow if started now") so the owner of a job sees what it means.

4. **"Longer than usual" is worked out once, when the item starts, from Job History.**
   - Uses the job's **successful** runs, the last N (default 10), the time from its start to its end, not time spent waiting. Killed, failed and reopened runs are left out.
   - Needs **at least 3** such runs. With fewer, the entry cannot apply and the job log says so ("only 1 earlier run; 'longer than usual' not judged"). No guessing.
   - The limit is fixed at the start and written to the job log ("limit 1h12m: 50% over the 48m average of the last 10 runs"). The timer needs no database after that, which is what lets the job runner on an agent host use it.
   - *Recommended.*

5. **Mark as late is a flag with a time and a reason, not a status.**
   - A run can be late for several reasons; the flag keeps the first, and each firing is a `ReactionEvent` row as every Reaction action is.
   - The flag stays after the job catches up: *late* means a deadline was missed, the record the roadmap wants, not "late right now".
   - Where it shows: a Late marker on the diagram box and in the run's side panel; a Late column and filter in Job History; the run page lists what fired.
   - A job that never started still carries it (it lives on the workflow run's item for that job, as well as on the job run once there is one). The exact place is settled in step 1.
   - *Recommended.*

6. **Notify names an alert, and an alert is a small object** (question B):
   - **Name, recipients (email addresses), subject, message.** The message can use the same `%{...}` and `${...}` values a step can, plus the run's facts: job, workflow, outcome, why it fired, deadline, a link to the run.
   - Kept on an **Alerts page** in Administration, with a "used by" list (which jobs and workflows name it), as ROADMAP.md's direction says.
   - Each alert has a **Send a test** button.
   - Not here: groups (tag, application), acknowledging, escalating, other channels.

7. **Sending goes through an outbox, so no job waits for a mail server.**
   - Notify does not send. It adds a row to an **Alert deliveries** list (Pending). A sender inside the server picks rows up, sends, and records Sent or Failed with the reason; it retries a few times.
   - Why: the telemetry principle (a record must never slow a job), and runners on agent hosts should not need access to a mail server.
   - A workflow runner adds the row itself. A job on its own sends it with its telemetry, so it can arrive late; nothing else depends on it.
   - The sender and its failure are visible: an **Alert deliveries** page lists every message, to whom, when, and the result.
   - *Recommended.*

8. **Mail settings, and a small mail server of our own to test with** (owner's idea, 2026-10-23; question B).
   - Settings for the mail server (host, port, sender address, and a login kept as a secret the way other secrets are).
   - **A small receive-only mail server, a development tool** beside the Stand-in Scheduler (`mail_sink`, port 8025). It speaks enough SMTP to accept a message (the stock Python tool for this was removed in Python 3.12, so it is written with the standard socket library, about 100 lines, no package to install), saves each message as a file, and lists them on a small page. It never forwards anything.
   - The sender always sends by SMTP, so the real path is tested end to end. In development the setting points at the sink. There is no second "write to a folder" path to keep in step.
   - Not tested by this: a real server's login and encryption. The code is Python's own `smtplib`; a real server is tried once when one is available.
   - The mail-sending code is one module the Send email step can use later.

9. **Each timed entry fires once.** At most once per workflow run for each item and entry (once per attempt for *runs longer than*). A rerun attempt starts its own *longer than* clock; *not started by* and *not ended by* are about the run and are not re-armed.
   - A reopened run (Phase 7) does not fire entries that already fired (the events say so), and does not fire clock deadlines that passed while it was ended: the log says "deadline 03:00 passed before the run was reopened; not judged".

10. **Explain and the run view show the clock.**
    - The run page and the item's side panel show "due by 03:00 (in 42 minutes)" for a waiting or running item with a timed entry, and a fired entry as "fired 03:00: marked late, alert 'Ops' queued".
    - Explain on a timed entry says how its time was worked out, and why it did or did not fire.

11. **Where the clock is watched.**
    - **Workflow runner:** in its existing pass, for its items and for the workflow's own entries. Accurate to the poll (1 second).
    - **Job on its own:** a timer inside the job runner that only fires side effects (no decisions, so nothing it does can change how the job ends). Its records leave through the spool like every other.
    - The watcher never decides anything about the run, so a missed or late firing cannot change a result.

12. **A sample, in the seed and `autoapp_dev`:** `DEV-LATE_SAMPLE`, a workflow with a Simulate job that runs longer than its limit (marked late, an alert queued), another that is not started by its relative deadline because a prerequisite is slow, and a "failed: notify" entry. The messages arrive at the test mail server. One workflow has a late upstream job and a due-at-03:00 downstream job, to show the cause named. Loaded into `autoapp_dev` too (project rule).

13. **A delayed job must not make everything after it look like a separate fault** (the owner's point on question A). Job X is due at 03:00 but waits for U, which is late; X's "not started by 03:00" would fire, and Ops would hear about X as well as U. Three small pieces, **recommended together** (question F):
    - **The reason names the cause.** When a timed entry fires on a job that was still waiting for a job in the same workflow, the late flag, the event and the alert say so: "'X' not started by 03:00: waiting for 'U', which has been running since 01:10." The workflow runner already knows what X waits for.
    - **"Skip the alert if a job it waited for was late".** A tick on a Notify (default off): X is still marked late, with its cause, but the alert is not sent, because U's own entry already told people. Mark as late is never skipped.
    - **A third way to give a time: "within N minutes of being ready"**, counted from the moment the job's own prerequisites were met. It catches X stuck after U finished, whatever the clock says, and does not move when U is late.

## Settled by the owner (2026-10-23)

- **A.** Yes: a time of day means its next occurrence after the run started (proposal 3). The delay scenario is proposal 13. **D178.**
- **B.** Build the small mail server for testing (proposal 8); Notify as proposed otherwise. The roadmap's Operator Messages are a second path, separate from alerts (below). **D179.**
- **C.** *Not started by* inside workflows only, until scheduling exists. **D180.**
- **D.** Time Whens take side effects only. **D181.**
- **E.** Longer than usual as proposed (proposal 4). **D182.**

**Operator Messages (ROADMAP.md, "People in the loop") stay out of this phase.** They are for something a person must answer (a sign-off, a Hold for an operator), shown in a pane and as a run waiting for a person, and they need Hold first. An alert only tells. The two will meet later: an alert can announce an operator message, and a time-based Reaction could raise one. Nothing built here stands in the way: Notify's record of each delivery keeps the run it came from.

## Questions for the owner (as asked, now answered; F is open)

- **A. (answered)** Clock times (proposal 3): next occurrence after the run started, replacing "the day the run started". Agree?
- **B. (answered)** How much Notify (proposals 6 to 8): the smallest real version (an alert with recipients and a message, an outbox with a sender, mail settings, a saved-messages mode), or only a record of "alert X would be sent" until the Send email step and the Alerting design exist? Recommended the first: Notify that sends nothing shows little, and the pieces are small. The roadmap session should agree the alert object before it is built ([ROADMAP.md](ROADMAP.md), Alerting, "agree on Notify before it is built").
- **F. (answered: all three)** The three pieces of proposal 13: the cause named, "skip the alert if a job it waited for was late", and "within N minutes of being ready". All three, some, or none?
- **C. (answered)** Standalone jobs (what is out): *not started by* inside workflows only. Agree?
- **D. (answered)** Side effects only on time Whens, no *Kill when too long* yet. Agree?
- **E. (answered)** Longer than usual (proposal 4): successful runs only, at least 3, last 10 by default, fixed at the start. Agree?

## The steps (proposed)

Each step is built and tested before the next; the full suites run at the stops marked.

1. **Model and migration. (Built.** Settled in the build: the Late flag lives on `JobRuns` and `WorkflowRunItems` as `LateDateTime`, `LateReason`, `LateCause`; `WorkflowRunItems.ReadyDateTime` holds when an item's prerequisites were met; the time Whens are in `Reaction.TIME_TESTS`, not yet in `TESTS`, so the API refuses them until the runner can judge them; the login for mail is a Credential. `migrate_late_alerts.py`. `ReactionEvents.JobRun_id` is now optional (owner's choice, 2026-10-23): an event for an item that never started has no job run, and belongs to the workflow run by `WorkflowRun_id` and the item's path.**) Time Whens on a Reaction (kind, clock time or length, relative-to, percent and run count); Mark as late and Notify as actions; the Late flag on runs and workflow items; Alerts, Alert recipients, Alert deliveries; mail settings, and the cause of a late flag. `autoapp_dev` migrated (backup first).
2. **The clock rules. (Built.)** A pure module: work out a deadline from a time of day or a length and the run's start; work out "longer than usual" from a list of durations; judge a timed entry at a given moment. Tested with a made-up clock, including the midnight case and too-little-history.
3. **The workflow runner watches. (Built.** `engine/workflow_clock.py`, called once a pass by the workflow runner. Settled in the build: a job still waiting is watched for *not started by* only until it starts, and for *not ended by* until it ends; a job that ends Not run, Skipped and so on is no longer watched; an event for a job that has no run record yet (no API, or not arrived) belongs to the workflow run and the item's path; *Ready* is stamped the first time a job's prerequisites hold and cleared when a reopening resets it; a late flag set while running is copied to the job's run record when it ends; Notify is recorded as "not carried out" until step 5. Tests: `test_workflow_clock.py`, with `tests/fast_runner.py` (a clock 600 times faster, and a way to start it hours later).**) Fires Mark as late and side effects for timed entries on items and on the workflow itself; once-only; reopen behaviour. *Stop: workflow and reopen tests.*
4. **The job runner watches** a job on its own (*not ended by*, *runs longer than*), side effects only, through the spool. Tested for not slowing a job. **(Built.** `engine/job_clock.py`: a thread started as the steps begin and stopped before the run's end is recorded. Settled in the build: the spool writer was not safe for two writers, so the telemetry client now takes a lock around each record and each delivery (the risk below, handled in the writer itself). The history for *longer than usual* is read before the thread starts; the thread never reads the database. What fires leaves as a `REACTION` record, which carries a `LateReason` for Mark as late; the server sets the run's Late flag from it, keeping the first reason. Every attempt of a job rerun on its own is a run of its own and gets its own deadlines. *Within N minutes of being ready* does not apply to a job on its own and is logged as not judged. Notify is recorded as "not carried out" until step 5. Tests: `test_job_clock.py`.**)
5. **Alerts. (Built.** `app/alert_outbox.py` (queues a message, fills in `${...}` and the run's facts as `%{Alert.Job}`, `Workflow`, `Outcome`, `Why`, `Deadline`, `Link`, `Time`; `queue_test` is Send a test), `app/mail_sender.py` (SMTP by `smtplib`, 3 tries a minute apart, SENT or FAILED with the reason; a task in the server, off when `AUTOAPP_MAIL_SENDER=off`, which the tests set), `demo/mail_sink/sink.py` (SMTP on 8025, page on 8026, `mail_sink` in dev_env.sh). Settled in the build: the workflow runner queues the row itself; a job on its own reports Notify as a `REACTION` record and the server queues the row when it arrives (once, however often it is delivered); Notify now also works on the ordinary Whens (succeeded, failed, ended, return code) under Also; the mail login is the credential's name as user and its secret as password; the link uses `AUTOAPP_PUBLIC_URL` (default http://localhost:8000). The Send a test button and the pages are step 6. Tests: `test_alerts.py`.** *Stop: full suites.*
6. **Pages and API. (Built.** The Reactions API (`reaction_store.py`) saves and checks the time Whens, Mark as late and Notify, and the time Whens moved from `TIME_TESTS` into what it accepts. Settled in the build: a time When sits under Also only; *has not started by* and *within N minutes of being ready* are refused outside a workflow, with the reason; Mark as late is refused on an ordinary When; Notify must name an alert that exists; a history When saves 10 runs when none is given. `app/alert_store.py` and `routers/alerts.py`: `/api/v1/alerts` (list, add, change, delete, refused while a Reaction names it; **Send a test** is `POST .../test`), `/api/v1/alert-deliveries` and `/api/v1/mail-settings` (the mail settings had no way to be set until now; they are a section of the Alerts page). Runs and items carry `late`, `late_since`, `late_reason`, `late_cause`; `GET /api/v1/runs?late=true|false`; `app/run_clock.py` works the times of a run still going out again for `clock` (on the run, and on each waiting or running item): "Not ended by: due by 03:00 (in 42 minutes); the next 03:00 after the run started at 01:10", left out once the entry has fired. Pages: the Reactions box (When list, how the time is given, what a time of day works out to, Mark as late, Notify with the alert and the skip tick), `alerts.html`, `alert_deliveries.html` (both in Administration), a Late column and filter in Job History, a Late tag and the clock lines in the workflow run (header, outline, side panel; "Late" in the diagram box's second line) and in a job run's log page, which now also lists the Reactions that fired. Explain for a timed entry is the clock line (how the time was worked out) together with the fired entry's message in the side panel; no separate Explain box. Also fixed: the link in an alert's message (`%{Alert.Link}`) pointed at a page that does not take a run, and now opens the run's log, or a workflow's own page. Tests: `test_alerts_api.py`, `test_late_api.py`, `test_ui_time_reactions.py`, `test_ui_alerts.py`, `test_ui_late_run.py`.**)
7. **The sample and the docs. (Built.** `DEV-LATE_SAMPLE` in the seed and in `autoapp_dev` (backup `demo/output/autoapp_dev_before_late_sample.sql`), with the alert `DEV-LATE_ALERT` and mail settings pointing at the test mail server; test `test_late_sample.py`.**)** `DEV-LATE_SAMPLE`; WORKFLOWS.md, ROADMAP.md notes (through the inbox), decisions, CHANGE_LOG. *Stop: full suites, then merge.*

## Risks

- **A timer thread in the job runner sharing the spool with the job.** If the spool writer is not safe for two writers, a timed record could corrupt a job's records. Step 4 checks this first and, if needed, passes the timed records through the writer's own queue.
- **Time is wall-clock.** A server clock change or a DST night can move a deadline by an hour; the log shows the worked-out time so it can be seen. No working-day logic here.
- **A dead workflow runner fires nothing.** Out of scope (hosting).
- **The test mail server proves the sending path, not a real server's login or encryption.**
- **Mail is slow and flaky by nature.** The outbox keeps it away from jobs; the Failed result and retries are visible rather than silent.
- **Late in two places** (workflow item, job run) can drift. One is the source and the other is copied when the job run is recorded; tested.

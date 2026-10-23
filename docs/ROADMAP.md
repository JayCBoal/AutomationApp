# Roadmap

AutoApp's long-term features, beyond workflows. Each item is something RunMyJobs does badly, and the direction AutoApp would take to show a better way. Started 2026-10-18 from discussions with the owner.

- Items here are ideas and directions, not designs. Each one gets a design session when its turn comes, as workflows did.
- When an item starts, its shortcomings become a goal in [PROJECT_GOALS.md](PROJECT_GOALS.md) and its design gets its own page.
- Smaller follow-ups and open decisions stay in [TO-DO.md](TO-DO.md).
- The order below is the order the items were raised. Their priority is not set yet.

## In progress

- **Workflows.** Goal 2 in PROJECT_GOALS.md; the design is in [WORKFLOWS.md](WORKFLOWS.md).

## Features

### Security and permissions

- **In RunMyJobs:** the model is very flexible but monstrously complex to set up and to understand.
- **Direction:** keep the flexibility and make the model far simpler. It covers who may see, change, run or administer what, and how to tell why someone can or can't.
- **Starts with:** the owner's list of what is wrong with the RunMyJobs model.
- **Builds on:** user accounts ([HOSTING.md](HOSTING.md), item 1), which arrive with every account allowed everything.

### Credentials

- **In RunMyJobs:** credentials are kept centrally, which is good. But a job never names its credential: the credential is found at run time by matching the job's Run As User against the stored credentials. Which job uses which credential can't be seen, only worked out.
- **Direction:** the ActiveBatch way.
  - A credential is an object, and whatever uses it names it explicitly: a job, a step or a connection.
  - Each credential's "used by" list shows everything that would be affected by changing or removing it.
  - AutoApp already has a `Credentials` table, but nothing refers to it yet. Run SQL takes its database as a URL in a secret variable.
- **What matching does better than explicit links** (discussed 2026-10-18). Little, for credentials:
  - *Keeping job authors away from secrets:* no advantage. A credential object has its own security, so an author can be allowed to use it without seeing it (a "use but not read" right, for the permissions design).
  - *Moving jobs between environments:* a tie, provided links name the credential rather than an internal id. Then PROD needs a credential of the same name, as RunMyJobs needs one for the same user.
  - *Fixing a job without editing it:* narrow. A password change touches no job in either model. Only when a needed credential doesn't exist yet does matching let you fix the job without touching it.
  - *The right password on each host:* the one real advantage. One job that runs on several servers gets each server's credential automatically.
- **Keeping that advantage, and environment differences:**
  - A credential linked at the site or endpoint level, or holding a value per site, covers one job on many hosts.
  - A variable can pick the credential, for example `${DB_CREDENTIAL}` from the `Environment / TEST` tag, so one job definition runs as different users in different environments with no copy of the job.
  - The link stays explicit either way, and the job resolves its credential once at the start of each run, not through a search.
- **Goes with:**
  - the Connections item in TO-DO.md (a registered database or server names its credential);
  - encrypting the stored secrets (TO-DO item 6, Security);
  - vault connectors, later (TO-DO item 6).

### Alerting

- **In RunMyJobs:** alerts are kept centrally, which is good. But they are matched by pattern, not linked. Every time any job changes state, the whole alerts table is searched for alerts that match. With finely customised alerting in a busy system, those searches slow everything down and delay runs.
- **Direction:** the ActiveBatch way.
  - An alert is an object: who is told, by what channel (email first; Teams or a webhook later), and what the message says.
  - A job or workflow names the alerts it uses and for which outcomes. When a run changes state, AutoApp looks only at that run's own links. No search across all alerts.
  - Each alert's "used by" list shows who would hear about what.
- **What matching does better than per-job links** (discussed 2026-10-18). Here the advantages are real:
  - *Coverage by default:* a rule covers jobs that don't exist yet. With per-job links, a new job nobody linked fails without telling anyone, the worst way for alerting to fail.
  - *Rules across many jobs:* "every PROD failure outside business hours" is one rule, not thousands of links.
  - *Alerting changes without job changes:* when the link lives on the job, adding or retiring alerting means editing jobs, each under change control. A matching rule sits outside them.
  - Matching's costs are the search on every state change and not being able to see why an alert did or didn't fire. The search is how RunMyJobs implements matching, not a necessity: which rules apply changes only when a job or rule changes.
- **Keeping those advantages without matching:**
  - Link alerts to groups as well as to single jobs: a tag, an application, a workflow. The link is explicit and visible, and a new job carrying the tag is covered from the start. Tags already give inheritance.
  - Work out what applies when a job, tag or alert is saved and store it, so a state change only looks up what's stored.
  - A job's page lists the alerts that apply and the path each came through ("from tag Environment / PROD"), like the "Which variables a job can see" item in TO-DO.md.
  - Warn about jobs with no alerting path, such as a PROD job nothing covers. Explicit links can show what isn't covered; matching can't.
  - Whether a group's alert list belongs to the jobs' owners or to operations decides whether alerting changes need job edits. A question for the permissions design.
- **Fits with workflows:** alerting goes through **Reactions**, built in Workflows Phase 3 ([WORKFLOWS.md](WORKFLOWS.md), "Reactions to outcomes").
  - A Reaction has two sections: **What happens next** (the first that holds wins) and **Also** (every one that holds fires). **Notify** is a side effect, so it goes under Also, and it names an alert object.
  - Notify itself is planned for Workflows Phase 8, with the time-based Reactions such as "not started by 03:00".
  - Reactions are stored on the job definition, and a workflow can override them for its use of the job. That is per-job linking, with the coverage gap above. **Reactions inherited from a tag** (or an application) would close the gap. That belongs to the alerting design, not to a workflow phase.
  - This page and the Workflows work should agree on Notify before it is built.
- **To decide:**
  - which groups can carry alerts or Reactions: a workflow, a tag, an application; and how they combine with a job's own;
  - acknowledging an alert, escalating it, and holding repeats back;
  - what the alert shows: the job, the outcome, a link to the run and its Operations Log.
- **Builds on:** a way to send messages (the Send email step planned in TO-DO.md).

### Scheduling: one model, and an explanation

- **All discussion around scheduling is tracked in [SCHEDULING.md](SCHEDULING.md).**
- **In RunMyJobs:** Time Windows and Advanced Schedules (once Submit Frames) are powerful and flexible, but complex.
  - It is often hard to work out how to build a particular schedule.
  - It is hard to understand how a given combination behaves. The UI shows the resulting dates but not how it got to them.
  - The two overlap: some parts of a schedule can be modelled in either one.
- **Direction:** one simpler model that loses none of the flexibility, and an explanation for every date.
  - **Calendars** stay as the shared object: working days, holidays, fiscal periods.
  - **A schedule** is a list of plain rules that name calendars. For example: "06:00 on every working day of FinanceCal; when that is a holiday, the next working day".
  - **Why this date:** for any date in the preview, the rule that produced it, the calendar days it used, and any date it moved from. For a date that doesn't appear, the rule that ruled it out. This is the same idea as conditions' Explain in workflows.
  - The schedule reads back in plain words in the editor.
- **What the separation may be for:** a time window is used for more than starting jobs. It also sets when a queue is open, when a job started by a dependency may start, and blackout periods. A reusable "period" may still earn its place, but as one kind of object inside a single model, not as a second model beside the first.
- **Starts with:** the owner's examples of schedules that are hard to build or to read in RunMyJobs.

### Events and triggers

- **In RunMyJobs:** the Event object is how one chain depends on another: a Raise Event in one, a Wait Event in another.
- **In AutoApp:** a workflow depends directly on another workflow or job, with no object in the middle. That answers most of what Events are used for.
- **What an event-like mechanism might still add**, to discuss:
  - *A signal from outside:* another system says "the data is ready" through the API, without knowing which workflows wait for it. That could be a trigger rather than an object.
  - *A latch:* the signal is raised before anything waits for it, stays raised until cleared, and is shown as raised or not.
  - *Fan-in from things that aren't jobs:* a file arriving, an operator's action, an API call.
  - If these are wanted, they can likely be triggers and dependencies on a named signal, without RunMyJobs' separate Event definitions (agreed 2026-10-18).
- **Two models to reconcile, or not:** RunMyJobs' Events and Control-M's Conditions are close cousins, with two key differences.
  - *Dates:* a Control-M condition usually carries an Order Date, on both the Add side and the Wait or Delete side. A RunMyJobs event has no date.
  - *Raising twice:* in Control-M, adding a condition that is already there for that Order Date has no effect, unless it was deleted in between. In RunMyJobs, every Raise Event creates a new event.
  - *A model that holds both* (proposed): a signal has a name and, optionally, a business date. Its state for each name and date is raised or cleared, so raising it again changes nothing (Control-M). Every raise and clear is kept in its history, with who or what did it (RunMyJobs' record of each raise, as history rather than state). A waiter waits for the signal for its own business date, or for any date.
  - *Is it worth it?* Mainly for migrations from Control-M, where date-keyed conditions are a core pattern that RunMyJobs' Events can't express directly. AutoApp already has a business date in the run context (`${BUSINESS_DATE}`). Cheap once signals exist.
  - *A question this raises for workflows:* "which run of another workflow counts" ([WORKFLOWS.md](WORKFLOWS.md)) rejected "today's run" because it breaks workflows that cross midnight. A business date doesn't change at midnight, so "the run with the same business date" could be an option there too. For the Workflows design to decide.
- **File events:** wanted, since AutoApp's headline features are template-driven file handling and the file trace. The workflow design already has prerequisites on endpoints, using Check Files' minimum age. RunMyJobs' File Events are fine, so this is not a demonstrator focus.

### People in the loop (Operator Messages)

- **In RunMyJobs:** Operator Messages are a good idea, clumsily done.
  - They have a page of their own. Job-related messages also appear under their jobs on the monitoring page, but few shops would watch the messages page instead of monitoring, so operators watch both.
  - They make a lot of noise, and it isn't clear how to suppress the useless messages without suppressing the important ones.
- **What they add that monitoring can't** (discussed 2026-10-18): very little, except a person's *reply*, and who is asked to give it. A sign-off, a manual task, a choice only a person can make. Everything else is already visible in monitoring: a failed run is a failed run.
- **Direction:** no separate page. A **pane on the monitoring screen** for what needs someone, and the waiting itself shown as a run's state.
  - *A run waiting for a person* has a status that says so, with the reply buttons on the run itself. The replies are Reactions' decisions (Release, Rerun, Skip, Kill), so a reply does exactly what the same choice does anywhere else.
  - *What creates an item:* only something designed to wait for a person (the Hold for an operator Reaction in TO-DO.md, an approval), never every error by default. Information with no reply needed goes to alerting or the log, not the pane.
  - *Keeping the noise down:*
    - The same cause, repeated, is one item with a count.
    - An item closes by itself once its situation is resolved, for example when the run is rerun and succeeds.
  - *What each user sees:* items assigned to them or their group (from the permissions design), and filters and saved views: by tag, application, workflow, and "assigned to me".
  - *Audit:* who replied, when, and with what. An alert can announce an item (from Alerting).
- **Starts with:** the owner's examples of RunMyJobs messages that are noise and ones that matter.

### Change history: readable, and recorded where the change was made

- **In RunMyJobs, the audit trail:** entries are hard to read, at least for working out exactly what changed.
- **In RunMyJobs, changes that spread:** a change to a job definition (sometimes or always, unclear) is also recorded as a change to every chain that calls it.
  - It adds audit records that change nothing.
  - It updates the chain's modified date and modifier, so migration customers ask "why did you change this chain?"
  - It makes it very hard to find chains that really changed.
  - Defended as technically correct: a change to a job is in effect a change to every workflow that runs it. True, but in practice it takes away much more value than it adds.
- **Direction for the audit:**
  - Each audit row stores the change as structured data: each field's value before and after; steps added, removed or moved; each step's parameters. This builds on "Exact differences in the audit log" in TO-DO.md.
  - The Audit Log page shows it as plain sentences with the changes highlighted.
  - The same data lets a change be rolled back without keeping full copies of earlier versions: undo the changes in reverse order, from the current version back.
  - Secrets: an audit row says only that a secret changed, never its value. Rolling back a secret could still work, without the audit holding it:
    - *Encrypted in the audit row* works, but puts secrets in the audit: kept longer, read and exported by more people than the credentials themselves, and part of every key change. It would also break the project rule that audits never record variable values.
    - *Proposed instead:* the secret store keeps earlier versions of each secret, as vaults do, and the audit row names the version. Rollback restores that version. Secrets stay in one protected place, and old versions are purged under their own retention rule.
- **Direction for spreading changes:** a change is recorded only on the object that changed.
  - This is already true in AutoApp: saving a job changes only that job's record; a workflow refers to the job, not to a copy of it. Keep it as a rule.
  - What the "technically correct" view wants can be shown rather than recorded. A workflow's page and search could show "jobs it uses that changed since …", worked out from the jobs' own history. The workflow's own modified date and audit stay its own.
- **Goes with,** later: versions, comparing two versions, promotion from DEV to PROD.

### Scripting and extending AutoApp (RedwoodScript)

- **In RunMyJobs:** RedwoodScript is very powerful and flexible, but it is Java underneath and compiled, so arguably not a true scripting language.
- **What it does well:**
  - Errors are caught when a script is saved, not at 2 a.m. when it runs.
  - It has full access to RunMyJobs' own objects and API, inside the server's transactions.
  - Java's libraries and speed.
- **What it costs:**
  - It is verbose, and the language isn't what operations people know (Bash, PowerShell, Python).
  - It needs an edit, compile and fix cycle, with little help for debugging.
  - It runs inside the server, so a bad script can affect everything.
  - It is a second language beside REL for expressions.
- **One distinction to keep in mind:** RedwoodScript does two different jobs. It is a job's payload (do some work), and it extends the scheduler itself (triggers, actions, extension points).
- **Direction:**
  - **Payloads** in languages people already know, on the machine that runs the job: the Script step in TO-DO.md.
  - **Checking on save:** a syntax check at save time where the language allows it, keeping RedwoodScript's best feature.
  - **Extending AutoApp** from outside, through its API and calls to a webhook on events, not code running inside the server.
  - **Expressions** stay in one language: flow control's SQL `WHERE`-clause conditions.
- **To discuss:** whether anything needs code running inside the server; whether the Script step needs the API from inside a script (a small client library).

### Return values from a job

- **The idea** (the owner, 2026-10-18; first noted under Workflows Phase 4, then moved here because nothing in the workflow phases depends on it): **Set Return Code becomes Set Return Values.**
  - It still sets the job's return code, and can also set named values of the job's own (`RowsRejected`, `BatchId`), which join its outputs.
  - On its own, a job shows them with its run in Job History.
  - In a workflow, jobs downstream read them as `%{Load.RowsRejected}`, in conditions and in their steps' parameters.
- **In RunMyJobs:** for the owner to describe.
- **Builds on:** Workflows Phase 4's `%{Name.Output}` paths to other jobs, and flow control's outputs ([FLOW_CONTROL.md](FLOW_CONTROL.md)).

### A job's Operations object downstream

- **In RunMyJobs:** handing data from one job to the next in a workflow is limited. AutoApp workflows today pass only totals downstream (`FileCount`, `Bytes`, return codes).
- **The idea** (the owner, 2026-10-17; raised again 2026-10-19; WORKFLOWS.md, "A job's operations as an object downstream"):
  - a job's operations (file, endpoints, bytes, status) readable downstream as a table in conditions, e.g. `EXISTS (SELECT 1 FROM Extract.Operations WHERE DestEndpoint = 'FINANCE_IN' AND Status = 'SUCCESS')`, so a condition can ask about particular files rather than totals;
  - a downstream job's For Each File looping over the files an upstream job delivered, rather than what matches a pattern, with the trace linking the handoff;
  - a limit on a huge number of files, like While's `MaxIterations`.
- **Direction:** the Operations *object* the job runner already builds for each run (what it sends to the telemetry API) travels downstream with the job's own end report, the core record.
  - It never reads the Operations *table*, which is filled in after the fact and must stay off the critical path (see Telemetry that never slows a job; D40).
  - The owner's point: the table is not real-time, but the object is what already feeds the telemetry endpoint, so it only needs to be made accessible downstream.
- **Builds on:** Workflows Phase 4 (job outputs, conditions); the telemetry split; Return values from a job, which covers named values a job sets itself, where this covers the files themselves.
- **Status in the workflow docs:** D42 in WORKFLOW_DECISIONS.md, *Deferred*: a later workflow enhancement, not needed by Phases 5 to 8. Decision 18 in WORKFLOWS_PHASE4.md.

### Telemetry that never slows a job

- **Not a RunMyJobs shortcoming:** AutoApp's own architecture. Raised by the owner on 2026-10-18: "this is a big deal and I don't want it to get lost". Full details and the current state: [TO-DO.md](TO-DO.md), decision 10.
- **The principle:** "Telemetry must be recorded, but it must not harm the job's core purpose or performance."
  - The operations log is an audit trail, asynchronous by design (as first agreed). It need not be real-time, and every second counts where jobs are many and short.
  - Job History (start, end, status, return code, process ID) is core scheduling data, which schedulers, workflows and Reactions act on.
- **Today one pipeline carries both:**
  - The runner writes every record to its spool file, then posts them through the API after each step and at the end. Each time, it waits up to 5 seconds for the server to save them, so a slow server holds a job up.
  - A run's end reaches Job History only in the same batch as its operations.
  - Without an API, the spool delivery and the workflow runner load spool files into the database themselves. Nothing runs that sweep regularly.
- **Direction:**
  - Job History reported promptly, on a small path of its own.
  - Operations records sent in the background or by a periodic sweep, never holding up a step.
  - Runners never write to the database, since in production they run on the scheduler's agent hosts.
  - The workflow runner learns outcomes from Job History alone.
- **Needed before:** agents, and hosting ([HOSTING.md](HOSTING.md)), where the server is no longer on the runner's machine. Not needed to finish the workflow phases.

### Hosting in the cloud

- **Why:** a demo the owner can open from anywhere and show colleagues, and the way to a RunMyJobs integration later.
- **Plan:** [HOSTING.md](HOSTING.md).

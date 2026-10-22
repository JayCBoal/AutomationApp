# Workflows: design

The design record for AutoApp's workflows, built up in design sessions with the owner. What a workflow is for, and the RunMyJobs shortcomings it answers, are in [PROJECT_GOALS.md](PROJECT_GOALS.md) goal 2. This page holds everything else: the starting point, what is decided, what is proposed, and the open questions.

Status: **Phases 1 to 4 are built and merged (Phase 4's Operations object and For Each File over an upstream job's files were deferred, D42); Phase 5 (outside dependencies) is built and merged (2026-10-19); Phase 6 (embedded and shared workflows) is built (2026-10-20; WORKFLOWS_PHASE6.md, D116 to D135).** The design topics below are all settled.

**Every decision, with its reason, is in [WORKFLOW_DECISIONS.md](WORKFLOW_DECISIONS.md)**: look there first for "why does it work like this?".

## Agenda

1. The objects and their names. *Done.*
2. Dependencies: join rules, branches not taken, final statuses, disabled jobs. *Done.*
3. Conditions: what they can test, and the language or builder (shortcoming 3). *Done.*
4. Reactions to outcomes: return codes, rerunning upstream (shortcoming 2). *Done.*
5. Restarts and bypassing. *Done.*
6. The diagram and editor: cross-workflow links, density, full names (shortcomings 4 and 5). *Done.*
7. Run records: Job History, the Operations Log, the trace. *Core in Phase 1, planned with it.*
8. The first slice to build: the smallest thing that shows the idea. *Decided: phases, above.*

## Starting point: ActiveBatch's model

The owner found it intuitive. A place to start, not to copy as-is.

- A Plan is an executable container: everything in it runs in parallel unless dependencies say otherwise.
- Job Triggers "push" from JobA to JobB: JobA ending starts JobB.
- Job Constraints "look back" from JobB to JobA: JobB checks them when it is ready to run.
- Sub-Plans, which belong to their parent.
- Other constraints in any combination on any job, such as date and time (linked to a Schedule or Calendar object, or not).
- An expression, in the same C-like language as its Jobs Library, combining a job's constraints. Not great, but far easier to write than REL.
- AutoApp's design must not look *obviously* copied from ActiveBatch. At the least, it gives its objects its own names.

## Decided

### The model is a graph, not steps (2026-10-16)

- Everything in a workflow runs in parallel unless dependencies say otherwise.
- The stepwise model of RunMyJobs chains has no real advantage beyond an easy layout and an easy-to-explain barrier. Restarts work as well in a graph: from the point of failure (the failed job and whatever below it has not run), from a chosen job (it and everything downstream), or bypassing a job fixed by hand (marked done so what depends on it goes ahead).
- Each step boundary adds dependencies nobody asked for, which is where the workarounds of shortcoming 1 and the structural sub-chains of shortcoming 6 come from.
- "All of these, then those" is still expressible, by an embedded workflow (below) that others depend on as a whole. A RunMyJobs chain then imports directly, each step becoming an embedded workflow.

### One kind of dependency: look-back (2026-10-17)

- A job checks its dependencies when it is ready to start. There is no separate "push" between jobs.
- Why: in practice push means nothing different from look-back.
  - ActiveBatch has both because its Job Triggers define the batch (everything triggered from a first job, whose instance ID is the batch ID), which lets a workflow exist outside any Plan. With a Workflow object in the model, that is not needed.
  - ActiveBatch also creates JobB's instance only when JobA's trigger fires, so fewer instances sit waiting. AutoApp gets the same clarity from its run model instead: a workflow run shows each job's state without making a run record for jobs that have not started.
  - Control-M's conditions are a hybrid (JobA adds a condition, JobB waits for it), neither better nor worse in principle.
- Push survives only in Reactions (below), such as rerunning part of a workflow.

### Starting a workflow (2026-10-17)

- By hand, from its page. How workflows are initiated is not what is being demonstrated.
- Scheduling in AutoApp may come later (see Later).

### Names

- **Job** stays Job, as in every WLA.
- **Workflow** is the container. AutoApp does not use ActiveBatch's names (Plan, Trigger, Constraint), so the design is not obviously copied.
- **Prerequisite:** what a job waits for before it starts. People will say "prereq"; the formal name stays Prerequisite.

### What a workflow holds: embedded or shared (2026-10-17)

- A job or workflow **created inside** a workflow is *embedded*: it belongs to that workflow, has no existence of its own, and is never listed or reported on its own. An embedded workflow is what RunMyJobs' structural sub-chains should have been (shortcoming 6).
- A job or workflow **defined elsewhere** can be *used* in a workflow: it is *shared*. Each use has its own name (full length, unique in the workflow) and can override the definition's variables, so the same definition can run several times in one workflow, with or without different values.
- There is no separate Reference object (as ActiveBatch has), and no new noun for a use on screen: everything on the diagram is a job or a workflow, marked as the workflow's own or shared. The editor offers "New job here" and "Use an existing job…".
- Still open: job keys for embedded jobs, and moving between embedded and shared (see the open questions).

### Prerequisites (2026-10-17)

- An embedded workflow can carry prerequisites as a whole ("Transform waits for the extracts"): they gate everything inside it, and its lines go to its frame. A job inside can also have its own, even to something outside the frame (only Enrich waits for the FX rates); its line then goes into the frame to it. The diagram draws whichever was defined (2026-10-17).
- One concept for what a job waits for: on another job in the same workflow it is drawn as an arrow; on something outside the workflow (a job in another workflow, a file, a value) it is drawn as a marked link, never hidden (shortcoming 4).

### Reactions (2026-10-17)

- What happens after a job ends, chosen by its outcome, such as a specific return code (shortcoming 2). Examples: rerun from a chosen job at most N times, stop the workflow, skip the rest of a branch.
- The difference from a Prerequisite: a Prerequisite is a gate *before* a job starts; a Reaction is an action *after* it ends. Reactions are the only "push" in the model. Their details are topic 4.

### Dependencies (2026-10-17)

- A prerequisite tests, by default, that the other job **succeeded**. It can test instead for any final status (so that, for example, Skipped has an explicit handler), for "ended" (any final status), or for specific return codes.
- A job's prerequisites must **all** hold by default; *any* is the alternative. Anything finer is an expression (topic 3).
- A prerequisite that can never hold makes the job **Not run** ("its prerequisites can't be met"), cascading downstream. Jobs are not left waiting.
  - Why: Control-M can leave such a job waiting because its New Day Process cleans up yesterday's jobs, and an operator can add the missing condition by hand to release it. In AutoApp the workflow run is the scope: cascading lets a run end cleanly, and "release it anyway" becomes bypassing or restarting part of the run (topic 5).
- A prerequisite outside the workflow cannot be known impossible: it waits, with an optional time limit.
- The workflow ends when every job has a final status.
- Each kind of job that did not run (Not run, Skipped, Disabled, Bypassed) has its own visual cue (how: topic 6).

### Final statuses (2026-10-17)

- *Succeeded*; *Failed*;
- *Skipped*: skipped on purpose by a Reaction;
- *Not run*: its prerequisites can't be met;
- *Disabled*: disabled as a hard stop, so what needs it to succeed is Not run;
- *Bypassed*: treated as succeeded without running (disabled as a pass-through, or marked done by hand).

### Disabled jobs (2026-10-17)

- ActiveBatch made a disabled job a hard stop, and added Soft Disable (a pass-through) later. AutoApp offers both from the start.
- Disabling a job *in a workflow* affects only that use of it: "stop here" (Disabled) or "pass through" (Bypassed). The workflow editor offers this on the job itself ("Disable here"), separately from disabling the definition, which is done on the job's own page.
- Disabling a *shared definition* means it can run nowhere: a hard stop, shown on each workflow's diagram as disabled elsewhere.
- Whenever a shared job is disabled, from a workflow that uses it or on its own page, the user is warned which workflows use it and what will happen in each.
- The workflows still run: a disabled job does not stop one from starting. Only what is wrong with the workflow as a whole does (it is disabled itself, or empty). A job in it that would fail its own pre-run check fails when its turn comes, with its reason, as it would on its own; the workflow's check lists both kinds in advance as warnings. (Built in Phase 1, with the warning, 2026-10-17.)

### Names of jobs in a workflow (2026-10-17)

- Every job or workflow in a workflow has a name unique within it; conditions refer to it by that name.
- An embedded job's name is its own. A used job takes its definition's name by default; only a second use of the same definition needs a name of its own (`Extract`, `Extract_EU`), which the editor suggests.
- Unlike flow control's StepNames, these never repeat: jobs in a workflow can run at the same time, so "the later one wins" means nothing.

### Conditions: flow control's language (2026-10-17)

- Workflows use the condition language of flow control ([FLOW_CONTROL.md](FLOW_CONTROL.md)): a SQL `WHERE` clause over `%{Name.Output}` values, worked out by SQLite in a database that may only compute. One language for steps and workflows.
- Why it answers shortcoming 3: SQL is documented everywhere and widely known; flow control already checks conditions before a run and logs the values each one used, which "Explain" against a past run can grow from.
- A job's `Status` is one of the final statuses: `SUCCESS`, `FAILED`, `SKIPPED`, `NOT_RUN`, `DISABLED`, `BYPASSED` (the first three as for steps).
- Every job in a workflow has the outputs `Status` and `ReturnCode`.
- A builder that writes the SQL is still wanted for people who would rather not.

### A job's operations as an object downstream (2026-10-17)

The owner's idea, starting from the JSON records a run sends for its operation log.

- The shape is a tree (workflow → child workflow → job → step → operations), addressed by dotted paths: `%{Extract.FileCount}`, `%{MONTH_END.Extract_EU.FileCount}`, `%{MONTH_END.FileCount}` (the workflow's total).
- Every node has the same small outputs, `Status`, `ReturnCode`, `FileCount`, `Bytes`, worked out when each job ends; a parent's are sums of its children's.
- The operations under any node are a table, readable in a condition as `Extract.Operations` or `MONTH_END.Operations`, each row with its Job path, plain column names and endpoints by name: `EXISTS (SELECT 1 FROM Extract.Operations WHERE DestEndpoint = 'FINANCE_IN' AND Status = 'SUCCESS')`.
- A downstream job's For Each File can loop over the files an upstream job delivered, rather than what matches a pattern; the trace links the handoff.
- Nothing is copied between jobs: the object is a reference (this workflow run, this path), and only a condition that asks for `Operations` reads rows, from the database, under the node it names. A For Each over a huge number of files gets a limit, like While's `MaxIterations`.

### Restarting: net result, resume, and the Rerun menu (2026-10-17)

- **Downstream sees a job's net result** in the workflow run. Example: Extract fails after delivering 3 of 5 files.
  - *Resumed:* the attempts add up. Attempt 2 delivers the other 2, and `%{Extract.FileCount}` is 5.
  - *Restarted from the beginning:* only the latest attempt counts. It delivers all 5, and `%{Extract.FileCount}` is 5.
  - Every attempt stays in Job History and the trace.
- **Resuming a failed job where it left off** (the owner's idea from the original prototype, a structured control file): when a job fails in its own work, the engine has a record of exactly what it has done so far, and Resume picks up from there.
  - AutoApp's runs already spool their operations as structured JSON as they go, which is most of that record: a resume skips the steps that finished, and in a For Each File the files already handled.
  - To work out (topic 5): reusing the first attempt's resolved values (a business date, a timestamp in a file name); a half-done step (a file copied but not recorded, a SQL step partly committed), perhaps with steps declaring that they cannot be resumed and must run again in full; flow control state (which branch an If took, which pass a loop was on); and a runner that was killed, whose spool is left as `.jsonl.tmp` (TO-DO "Killed runs").
- **In the UI, Resume is the first choice, not a hidden default.** Jobs and workflows alike have a **Rerun ▸** menu: **Resume**, **Restart from beginning**, **Advanced…** (the other restart options, topic 5).

### Reactions (topic 4, 2026-10-17)

What a cancelled or killed job ends as: see Reason, below.

- **A list on a job or a workflow.** Each entry is a *When* (an event, with a condition in flow control's language about the job: `%{Load.ReturnCode} IN (4, 8)`) and one or more actions.
- **Kinds of When**, all in the one list and editor; to the user one mechanism, though the code paths differ:
  - *it ends*: status, return code, outputs, Operations; checked once, at the end;
  - *it hasn't started by…* and *it hasn't ended by…*: a time of day, or relative ("within 2 hours of the workflow starting"); a watcher with a timer;
  - *it runs longer than…*: a fixed time, or compared with its own Job History ("50% over its average of the last 10 runs").
  - This replaces a separate SLA mechanism. RunMyJobs' SLAs are wholly separate from job statuses and very complex; the owner wants the same reach, made user-friendly. Absolute times mean the day the run started until AutoApp has scheduling.
- **Actions**, offered only where they fit the kind of When:
  - *decisions*, changing what happens next:
    - Count as succeeded / Count as failed: an override, shown as both ("Succeeded (return code 4)"), not a seventh status;
    - Rerun this job: Resume or Restart from beginning, after a wait, at most N times;
    - Rerun from…: a chosen upstream job and everything between it and this one, at most N times;
    - Skip…: chosen jobs, or the rest of a branch;
    - Kill the workflow (see "Kill, Cancel and Hold", below);
    - Cancel the job (one not yet started will not start) and Kill the job (ends it while running);
    - Hold for an operator: pauses the workflow until someone chooses what next (Control-M's "leave it waiting", on purpose and visible);
  - *side effects*, changing nothing in the run: Notify; Mark as late (a flag, not a status, shown on the diagram and in Job History and searchable: the record of a missed deadline); Start a workflow (the one push in the model, drawn as an outside link).
- **How entries combine:** every entry is judged against a snapshot of what actually happened, so no entry's actions change what a later one sees. Of the matching entries, only the first one's decisions take effect; every matching entry's side effects fire.
  - Why: a job has one fate, but any number of people can hear about it. Example: A "failed: notify ops", B "return code 8: rerun, at most twice", C "failed: cancel the workflow". On a failure with code 8, ops are notified and the job reruns; C applies when the code is not 8, or once B's reruns are used up. With every match firing (Control-M's On-Do, in order, where an earlier Do can change how a later On evaluates) the rerun and the cancel would compete; with first match only, the notify would have to be copied into B.
  - In the editor (decided), two sections make the rule visible: **What happens next** (ordered; the first that holds wins, like If/ElseIf) and **Also** (every one that holds fires).
- Each rerun's N counts per workflow run; when it is used up, the next matching decision applies ("rerun twice, then hold").
- A workflow's own Reactions and completion rules decide its final status; by default, see "When a workflow succeeds", below.
- "Explain" shows which entries matched and which actions took effect.
- Steps' On failure is expected to become Reactions too, one mechanism for both.

### Success return codes (2026-10-17)

- Every job has **Success return codes**, `0` unless set; lists and ranges (`0, 4`, `0-4`). A code on the list means Succeeded, and is not an override.
- A use of a shared job in a workflow can override its definition's, as it can its variables.
- It becomes meaningful once a step can run a program and pass its return code on; today a job's code is 0 or 1.

### One editor experience (2026-10-17)

- The job editor and the workflow editor should be essentially the same UX: the properties panel, variables, the condition editor with Explain, the Reactions editor and the Rerun ▸ menu are shared. The canvas: both editors have the same Diagram | Outline switch (topic 6); for a job's steps an outline is easier to read in some cases.

### Reason, not Cancelled and Killed statuses (2026-10-17)

- Statuses stay six. Every job has a standard `Reason` output beside `Status`: `KILLED`, `TIMED_OUT`, `ERROR` (Failed); `CANCELLED`, `PREREQUISITES_NOT_MET` (Not run); `DISABLED_PASS_THROUGH`, `MARKED_DONE` (Bypassed).
  - For separate Cancelled and Killed statuses, as in RunMyJobs: triage at a glance (it broke, or someone stopped it); failure rates that leave deliberate kills out; a killed process has no meaningful return code; migration maps one to one.
  - Against: two more cases in every prerequisite, "ended" test, Reaction and default, almost always "same as Failed" or "same as Not run"; they are kinds of Failed and Not run; their main use in RunMyJobs, standing in for return codes in Status Handlers, goes away when return codes are handled directly.
  - `Reason` keeps the advantages: conditions test it (`%{Extract.Status} = 'FAILED' AND %{Extract.Reason} = 'KILLED'`), Job History filters on it, reports can leave kills out, the diagram marks it, and an RMJ Killed handler translates into that condition. It also names which of their two meanings Not run and Bypassed have.

### Where prerequisites live, and outside targets (2026-10-17)

- **Prerequisites exist only in workflows**, on a job's use there (or an embedded job), never on a job's definition.
  - The principle: what a job *is* belongs on its definition (its steps, Success return codes, Reactions to its own outcome and timing); how it *fits in* belongs on its use in a workflow. Prerequisites on a definition would give every workflow using it waits not visible where one looks (shortcoming 4 again).
  - A standalone job that must wait for something is a one-job workflow (which should be cheap to make), or uses flow control inside it (a While around a Check Files step).
  - Constraints that really belong to the job itself ("never during the database's maintenance window") are closer to resources or blackout windows: a separate idea, for later.
- **A prerequisite's target can be outside the workflow** (a job in another workflow, an endpoint, a time window), defined on the prerequisite itself. There is no separate object for outside links; a list of them, if shown, is built from the prerequisites.
- **Conditions name prerequisite targets.** A target gets a name made from it (`MONTH_END.Extract`, `INBOUND_ORDERS`), editable where two clash: `%{MONTH_END.Extract.Status} = 'SUCCESS'`. A condition may name only the workflow's own jobs and the targets of the job's own prerequisites; anything else is an error as it is written. So every outside reference is a prerequisite, and every prerequisite can be drawn.

### Which run of another workflow counts (2026-10-17)

- By default its **current or latest run**: the run executing now if there is one (a prerequisite on a job in it that has not run yet waits; yesterday's success does not count), otherwise its most recent completed run. This is ActiveBatch's "Exact active", under a name that says what it means.
- Not "today's run": that breaks workflows that cross midnight.
- Optional limits, off by default, against a stale success: only if that run ended within the last N hours; only a run started after this workflow's run started.

### Topic 3's other targets and tools (2026-10-17)

- **An endpoint as a target** has the outputs `FileCount` and `Bytes` (what matches its path and pattern now) and `Files` (a table, like Operations). Its prerequisite can ask for a **minimum age** (every file unchanged for at least N seconds), so a job does not start on a file still arriving; it waits, with its time limit. Local endpoints only, until SFTP exists.
  - Minimum age replaces the `Stable` first proposed: one check of each file's modified time, the partner of Check Files' `MaxAgeHours`, and the same concept as Check Files' minimum age (TO-DO), sharing its code. In a job, Check Files holds the job until its files are ready; in a workflow, the prerequisite keeps the job from starting.
- **Workflow variables:** as in flow control, `${...}` is fixed when the run starts and `%{...}` comes from the run. A workflow has `${...}` variables of its own, inherited by what is embedded in it.
  - Precedence, highest first: a use's overrides, the job's own, the workflow's, tags, the scheduler's.
  - One setting on the workflow, **Tags before workflow variables** (off by default), swaps the two scopes whose order is debatable; a full reorder would make "where did this value come from" hard to answer. The Variables panel says where each value came from.
  - Values fixed at the start are also what Resume needs.
- **Time windows:** a built-in `%{Now...}` (`Time`, `Date`, `Weekday`): `%{Now.Time} BETWEEN '06:00' AND '18:00'`; as a prerequisite it waits until the window opens.
- **The builder:** rows of name → output → comparison → value, joined by AND or OR, with grouping, writing the SQL live beneath; text is always one switch away, and back only while the text is in a shape the builder can show (otherwise "edited as text").
- **Explain:** against a past run (each value as it was, each part held or not, the result) and now (current values, in the editor), growing from what flow control already logs.

### Restarts (topic 5, 2026-10-17)

- **A rerun is a new attempt within the same workflow run**, not a new run, so the history stays together and the net-result rule applies.
- **Rerun ▸ on a workflow run:**
  - *Resume:* reruns the jobs that ended Failed or Not run (Failed ones resume from their record; Not run ones are looked at again from scratch); Succeeded, Bypassed, Skipped and Disabled jobs stay as they are;
    - Resume is passed down: each Failed job resumes from its own record (a job whose failure is unknown holds for an operator at that step), and a Failed embedded or shared workflow is resumed the same way, down through its own jobs. Not run jobs simply run; Killed ones (Failed, Reason `KILLED`) resume like any failure.
  - *Restart from beginning:* every job reset, from scratch, passed down the same way;
  - *Advanced…:* from a chosen job (it and everything downstream, choosing Resume or Restart from beginning for each job chosen); only chosen jobs (with a warning that downstream results may be out of date); mark as done (Bypassed, Reason `MARKED_DONE`, on a failed or waiting job); ignore a prerequisite for this run (Control-M's "add the condition by hand", done openly); skip chosen jobs; with different `${...}` values (with a warning); hold at… (pause before a chosen job, to look before it runs); reset automatic retry counts (below).
  - Every choice is recorded in the Audit Log, with who made it.
- **Rerun ▸ on a job on its own:** the same, with steps in place of jobs (from a chosen step, with different values, skip a step).
- **A manual rerun does not reset the Reactions' "at most N times" counts.** Operators often rerun without fixing anything; a reset would allow N more automatic retries against a system still broken. An operator who has fixed the cause chooses *Reset automatic retry counts* in Advanced….
- **How Resume works inside a job:**
  - it reuses the first attempt's resolved `${...}` values, stored with the run; secrets are read again, never stored; `%{Now...}` is the current time;
  - **every failed step reports whether what it did is known**, worked out by its handler from the error it caught: *not done* (safe to run again), *partly done and known* (file steps skip the files their records show done; a file in progress is checked at its destination by size, and checksum where recorded, and redone if it does not match), or *unknown* (Resume holds for an operator at that step, and the job log says why).
    - Example, Run SQL (one statement in a transaction, committed at the end only if `Commit` is on): could not connect, or the server rejected the statement (rolled back): not done. The connection dropped or timed out after sending, above all during the commit: unknown. In MariaDB and MySQL, DDL (`CREATE`, `ALTER`, `DROP`) commits on its own, so a failure after it is unknown.
    - Reactions' automatic reruns obey the same rule: an unknown failure is not retried; the job holds instead and says why.
  - flow control: an If whose branch had begun keeps that branch; a For Each File reuses attempt 1's list of files (to be recorded) and skips the passes done; a While picks up at its pass;
  - **the record is a control file, removed when the run Succeeds** (with the file of the attempt it picked up), and every Resume or Restart an operator asks for is kept in a Restarts list on the run, joined by the Reactions' reruns, and in the Audit Log (Phase 7, step 5; D152 to D155);
  - the run's spool, written as it goes, is the record for a killed runner and a failure of the code alike (the owner's control file is "the spool, read back"); when the last operation is not known to have finished, it counts as unknown or partly done, as above.

### The diagram and the editor (topic 6, 2026-10-17)

To be judged again in practice once built, above all the outside dependencies.

- **Layout:** left to right by default (columns are the levels of the graph; parallel jobs stack down a column), top to bottom as a choice for portrait screens. Laid out automatically; no dragging (pinning perhaps later).
  - Each column keeps the order the jobs have in the definition (the outline's order), so folding a frame or other changes do not reshuffle it, at some cost in compactness (decided 2026-10-17, after the mockup).
- **Full names, always:** a box wraps its name onto as many lines as needed, so one long name does not widen its whole column. Never truncated.
- **A box in the editor** shows what kind of thing it is: embedded or shared, job or workflow; disabled here or elsewhere; has Reactions. Everything else is in the side panel on selection, the same panel as the job editor. It has no status: statuses are for runs.
- **Every kind of dependency is visible:**
  - ones with a source are a box joined by a line: a job in the workflow (an arrow), a job or workflow elsewhere (a dashed box at the edge), an endpoint (a file box);
  - ones without a source are icons on the job's box: a clock (a time window), a calendar (a date), `{x}` (a test on a variable). Each shows its exact condition on pointing at it.
- **Lines are coloured, not labelled**, each colour with its own line style too, for colour-blind users (red against green is the commonest form):
  - Succeeded (the default; Bypassed counts as succeeded): green, solid;
  - Failed: red, dashed;
  - Ended (any final status): black, solid;
  - return codes: blue, labelled (`RC 4`, `RC 0-4`);
  - any other status, or a combination: grey, labelled.
  - *Any* rather than all is marked where arrows enter a job.
  - Reactions have a look of their own, since dashed means Failed: Rerun from… is a dash-dot line in the muted colour, back upstream, its label marked ↺ (decided 2026-10-17, after the mockup).
  - Pointing at any line says what it means ("Transform waits until Extract_US succeeded"); so does pointing at a marker (decided 2026-10-17, after the mockup).
- **Embedded workflows** are a frame around their jobs; a frame shows ▾ to fold it and a folded one ▸ to unfold it, both at top-left (a double-click unfolds too); folded, it is one box with a summary, and a line that really ends inside it carries its arrowhead a little way into the box (one that starts inside begins with a dot inside it), so it is plain that it reaches something within ("Extract: 12 jobs"; in a run "2 running, 1 failed"). **Shared** ones are a single box, opening read-only.
- **Outside dependencies, both ways** (shortcoming 4); selecting one opens the same side panel as a job, marked *Outside this workflow*: what this workflow waits for as dashed boxes at the left edge (`⇢ MONTH_END / Extract`, linking there); what waits for this workflow as dashed boxes at the right edge (`Needed by ⇢ BILLING / Load`); Start a workflow Reactions as right-edge stubs.
- **In a run**, boxes use the lines' colours and patterns: Succeeded green; Failed red; Running blue with a moving stripe; Waiting on a prerequisite an amber outline (the side panel says which); not started yet plain; Held a pause marker; Not run hollow grey; Skipped grey stripes; Disabled crossed out; Bypassed a dashed outline with an arrow through; late a red clock. Rerun ▸ on every box.
- **Editing:** + Job (New job here, Use an existing job…); drag from box to box to make a prerequisite, select a line to change its test; Disable here and Rerun ▸ on each box's menu.
- **The key** (what lines, states and markers mean) is folded away by default: once learnt it only takes room, and pointing at things explains them.
- **Diagram | Outline**, the same switch and words in the job editor and the workflow editor. The outline is an indented list (embedded workflows nested, prerequisites under each job), for very large workflows and screen readers.
- **Find:** matches as AutoApp's search pages do (case ignored, anywhere in the name), and looks everywhere: direct children, inside embedded workflows and inside shared ones, however deep. Results list their path (`MONTH_END / Extract / Stage_EU`). On the diagram, matches are highlighted, a collapsed frame says how many it holds ("2 matches inside"), and *Show matches* opens every frame on the way to them; shared workflows open inline for this, read-only and visibly distinct. Zoom and fit too.
- **Layout engine:** elkjs (Eclipse Layout Kernel), vendored like Alpine, for positions only; AutoApp draws the SVG. Its licence is the Eclipse Public License 2.0: free, nothing to buy, and no obligation on AutoApp unless elkjs's own code were changed and distributed. Chosen over dagre (MIT), which handles nested frames poorly. The owner cares about the UX, not the means, provided nothing needs a paid licence.

### Implementation in phases (2026-10-17)

- Each phase a working, demonstrable AutoApp built on the last, with tests, a migration and a CHANGE_LOG entry.
- Principles: the model is built for the full design from the start (names unique in a workflow, a path for every job, attempts on job runs), even where screens come later; the first screens use the Outline view, so the diagram can follow its mockup.
- **Phase 1, the MVP** (shortcoming 1): "a workflow of jobs with dependencies runs, and you can see what happened."
  - model: Workflows; uses of existing jobs, each with its unique name; prerequisites between them (Succeeded, Failed, Ended, return codes; All or Any);
  - a workflow runner, a separate process like the job runner, started from the workflow's page: starts each job once its prerequisites hold, as the Run Job page starts the runner; parallel unless prerequisites say otherwise; Not run cascading; a final status; `Reason`;
  - run records (the core of topic 7): Workflow Runs; each job run knows its workflow run, path and attempt; Job History shows workflow runs with their job runs under them, and a job run links to its workflow; the Operations Log and the trace work unchanged, as they follow job runs;
  - screens: a Workflows list (like the other search pages); a workflow page editing in Outline view (add a job, set its prerequisites); Run; the outline showing the run live;
  - not in Phase 1: embedded jobs, Reactions, outside dependencies, restarts, the diagram, Find.
- **Phase 2, the diagram** (shortcoming 5): first a clickable mockup (a static page with a sample workflow: embedded workflows, outside dependencies both ways, a run in progress) to judge the look by eye; then elkjs, Diagram | Outline, coloured and styled lines, markers, run states.
- **Phase 3, return codes and Reactions** (shortcoming 2): a Set Return Code step; Reactions on a job's end, a simple outcome choice (What happens next and Also; Count as; Rerun this job and Rerun from… with limits; Skip…; Kill the workflow; Start a workflow), on the job with overrides on a use; Kill on any running job (Kill and Cancel on a workflow); Disable here (stop or pass through). Plan: [WORKFLOWS_PHASE3.md](WORKFLOWS_PHASE3.md). Hold for an operator and a When written as an expression moved to TO-DO (2026-10-18).
- **Phase 4, conditions** (shortcoming 3): prerequisites in flow control's SQL language with `%{...}` paths; the Operations object downstream, with For Each File over an upstream job's files; the builder; Explain; workflow variables.
  - Split (2026-10-18): Phase 4 built job outputs (`%{Load.Succeeded}`, `FileCount` and the rest), Custom rules, Succeeds when and Return code from, and the condition box (help, validation, the builder, Explain). Plan: [WORKFLOWS_PHASE4.md](WORKFLOWS_PHASE4.md). The rest of Phase 4 (planned 2026-10-19, same plan): workflow variables, a workflow's tags feeding its jobs too, the order through the system-wide Variable precedence setting. The Operations object and For Each File over an upstream job's files are deferred to a later workflow enhancement: the telemetry principle rules out the Operations table, not the object (D42).
  - **Set Return Code becomes Set Return Values**, the owner's idea (2026-10-18), was noted here, then handed the same day to the roadmap planning session, for [ROADMAP.md](ROADMAP.md): nothing in the workflow phases depends on it. It still sets the job's return code, and can also set named values of the job's own (`RowsRejected`, `BatchId`) that join its outputs, so jobs downstream read them as `%{Load.RowsRejected}` in conditions and steps.
- **Phase 5, outside dependencies** (shortcoming 4): prerequisites on jobs in other workflows (current or latest run), on endpoints (minimum age, sharing code with the Check Files change), on time windows and dates; their markers; Needed by. **Built 2026-10-19.** Plan: [WORKFLOWS_PHASE5.md](WORKFLOWS_PHASE5.md); decisions D99 to D115.
- **Phase 6, embedded and shared workflows** (shortcoming 6): embedded jobs and workflows, workflows used in workflows, frames, deep Find. **Built 2026-10-20.** Plan: [WORKFLOWS_PHASE6.md](WORKFLOWS_PHASE6.md); decisions D116 to D135.
- **Phase 7, restarts:** the Rerun ▸ menu; Resume from a control file (not done, partly done, effect unknown); flow control state; the Reaction's Restart or Resume; Advanced…. **Planned 2026-10-20.** Plan: [WORKFLOWS_PHASE7.md](WORKFLOWS_PHASE7.md); decisions D136 to D142.
- **Phase 8, time-based Reactions** (the SLA reach): not started by, not ended by, runs longer than; Mark as late; Notify (needs a way to notify, such as the Send email step in TO-DO).
- The order follows the shortcomings' priority, except that the diagram comes second (every later phase has something to show on it), and restarts and time-based Reactions, the deepest engine work and the least needed to show the design, come last.
- The owner may change the order of Phases 3 to 8 later.
- Each phase is planned in detail just before it is built. The mockup was made alongside planning Phase 1: `autoapp/ui/mockup_workflow.html` (open it from the running server at `/ui/mockup_workflow.html`; it is not in the navigation bar).
- Phase 1's plan: [WORKFLOWS_PHASE1.md](WORKFLOWS_PHASE1.md).
- Phase 2's plan: [WORKFLOWS_PHASE2.md](WORKFLOWS_PHASE2.md).


### Prerequisites that aren't satisfied (2026-10-17)

- Already decided before: one that can never hold makes the job Not run, cascading; one outside the workflow waits, with an optional limit. The rest, in two levels:
- *on each prerequisite*, how long to wait and whether it is required: wait with no limit (the default inside a workflow), up to N minutes, or until a time ("until 02:00"); if it isn't met in time, **required** (the default: the job can't start) or **optional** (go ahead without it: "use today's FX rates if they arrive by 02:00, otherwise carry on");
- *on the job*, what "can't start" means: **Not run** (the default, cascading), **Fail** (Failed, Reason `PREREQUISITES_NOT_MET` or `TIMED_OUT`, so failure paths and Reactions take over), or **Hold for an operator**.
- Why two levels: patience belongs to each thing waited for (the file has until 02:00, the other workflow until 03:00); the consequence belongs to the job, which has one fate however it failed to start, as with Reactions' decisions. A time-based Reaction ("not started by 03:00") sits beside this as a side effect (notify, mark as late), not deciding the job's fate.
- Built with outside dependencies (Phase 5, 2026-10-19), except Hold for an operator.

### A workflow is a kind of Job (2026-10-17)

- Every executable object is a Job, with a `JobType`: *steps* (as now) or *workflow*. A workflow is not a separate kind of definition. RunMyJobs makes chains a kind of job definition too, clumsily; ActiveBatch makes Plans a separate object.
- What it gives: one set of keys, used the same way (a workflow is used in a workflow like a job, and a scheduler could start one by its key); everything common written once (description, variables, tags, the Audit Log, search, Reactions, Success return codes, Disable, Rerun ▸); a workflow's run *is* a job run, each child run pointing to its parent run; embedded objects are jobs owned by a workflow (a parent column), hidden from lists.
- How it avoids the clumsiness: a common core in Jobs, and type-specific content beside it, never forced into one shape: steps for a steps job (JobSteps, as now), items and prerequisites for a workflow (their own tables). Pages and runners choose by type: a workflow's page shows the outline or diagram, never an empty steps editor; its run goes to the workflow runner; it has no working folder.
- **No other job types for now.** "What kind of work" is a step type (handlers, help, preview, outputs, operation records and masking already exist for those), and a job of one step costs nothing. Job types differ only in structure.
- **The Simulate step type** (the owner's idea from testing RunMyJobs chains with a configurable dummy job): logs given lines, waits a given time, exits with a given return code, optionally fails with a given message. For building and testing workflows without real jobs.

### Jobs may still run on their own (2026-10-18)

- Putting jobs in workflows is the advice, not a rule. ActiveBatch called it best practice without enforcing it; RunMyJobs bills a chain's run like a job's, which pushes people to odd chain structures and workarounds for dependencies.
- Why not a rule:
  - building and testing a job means running it by itself (Run Job), and wrapping it in a workflow first is ceremony;
  - schedulers start jobs by key ([INTEGRATION.md](INTEGRATION.md), the Stand-in Scheduler, the RunMyJobs draft), a contract not to break;
  - RunMyJobs has jobs on their own, so the rule would not carry over to it.
- What AutoApp shows instead: a workflow costs no more than a job, and a one-job workflow is cheap to make, so dependencies go where they belong because nothing pushes them elsewhere.
- **Reactions apply wherever the job runs.** Only those with nothing to act on outside a workflow are left out on its own: Rerun from… (needs an upstream job), Skip… (other jobs or a branch), Kill the workflow. These live only on a use, and would even if every job ran in a workflow: a job is used in many workflows, so its own list cannot name a job in one of them; and what a job *is* goes on the job, how it *fits in* on its use.

### Where workflows run (2026-10-17)

- The workflow runner works on the database directly, beside the server, not on an agent. In ActiveBatch terms, workflows run on the server's own virtual queue, the natural home if queues ever come.

### When a workflow succeeds (2026-10-17)

- **By default, a workflow succeeds unless a failure went unhandled.** The owner's framing: it succeeds if all of its jobs that nothing waits for succeeded, so a handled failure does not fail it. Refined so that a failure cut off by Not run still counts:
  - a failed job fails the workflow unless something that waits for it ran anyway (its prerequisite on that job held);
  - a job nothing waits for must not fail;
  - Not run, Skipped, Disabled and Bypassed jobs do not count against it, except a job Not run because it was cancelled (Reason `CANCELLED`): that counts as unhandled, so a workflow someone cancelled part of does not end green unless its completion rules say so.
- Examples: in the sample, a failed ledger check is handled because Alert finance ran, so the workflow's outcome is Alert finance's. In A → B (B waits for A to succeed), A fails and B is Not run: nothing ran because of A's failure, so the workflow fails. With Any, a failure a waiter could do without counts as handled.
- Built in Phase 1 (2026-10-17), replacing "any failed job fails the workflow".
- **Completion rules**, set on a workflow when the default is not wanted:
  - *Ends when:* all its jobs have ended (the default), or chosen jobs have ended; the rest are then left to finish on their own, or killed.
  - *Succeeds when:* the default above, or chosen jobs succeeded, or a condition (flow control's language).
  - *Return code:* 0 or 1 (the default), a chosen job's, or mapped from conditions.
  - With Reactions (Phase 3); conditions need Phase 4.
  - Built in Phase 4 (2026-10-18): *Succeeds when* the default or a condition, and *Return code* the default or a chosen job's. *Ends when* waits.

### Kill, Cancel and Hold on a workflow (2026-10-17)

- **Cancel** and **Hold** are for what has not started: a cancelled job or workflow ends Not run, Reason `CANCELLED`; a held one waits for an operator.
- **A running workflow** offers two actions, down through the workflows inside it:
  - **Kill:** kills its jobs that are running (Failed, `KILLED`) and cancels those not yet started (Not run, `CANCELLED`);
  - **Cancel what hasn't started:** cancels those not yet started; the jobs running finish.
- Either way the jobs keep their own statuses and reasons, and the workflow's status follows its completion rules, or the default ("When a workflow succeeds", where cancelled jobs count as unhandled). Its `Reason` says it was killed or cancelled.
- The rule underneath: never started is Not run; started and stopped on purpose is Failed, with a Reason saying how.
- Phase 1 has **Cancel what hasn't started** (the workflow ends Failed, `CANCELLED`). Kill comes in Phase 3.

### Loops (2026-10-17)

- A loop is allowed in a workflow, with a required maximum number of runs. It is not made of prerequisites: A waiting for B while B waits for A can never start, so saving still refuses that, and its message points to the way to repeat jobs.
- A loop is a repeat link, "after B, go back to A", with a condition and at most N runs, each pass a new attempt: the Reaction "Rerun from…", drawn as the dash-dot ↺ line.

## Proposed, to settle

## Open questions, by topic

- **Reactions on a use** (raised 2026-10-17): whether a use can add Reactions of its own to its definition's (proposed: yes, the use's looked at first).
- **Diagram and editor (6):** how a job's steps (with If and loops) are drawn as a diagram.
- **Run records (7):**
  - how a workflow's runs appear in Job History, the Operations Log and the trace (perhaps a parent run with each job's run as a child);
  - showing each job's state in a workflow run without a run record for jobs that have not started;
  - job keys for embedded jobs (a key names the job's working folder; perhaps `MONTH_END.Extract`);
  - whether embedded jobs are left out of Job History's lists, or shown under their workflow.
- **Embedded and shared:** making an embedded job shared when a second workflow wants it, and a shared one into an embedded copy.
- **The first slice (8):** what to build first to show the idea.

## Later

- Scheduling in AutoApp, perhaps improving on RunMyJobs' Time Window and Submit Frame pair.
- Constraints that belong to a job itself, such as blackout windows or resources ("never during the database's maintenance window").
- With scheduling: what an outside prerequisite with no time limit means when there is no daily cycle (like Control-M's New Day Process) to end its wait.

# Workflows: design

The design record for AutoApp's workflows, built up in design sessions with the owner. What a workflow is for, and the RunMyJobs shortcomings it answers, are in [PROJECT_GOALS.md](PROJECT_GOALS.md) goal 2. This page holds everything else: the starting point, what is decided, what is proposed, and the open questions.

Status: **being designed. Nothing is built.** On 2026-10-17 the session finished topic 2 of the agenda, most of topic 3, and the core of restarting (topic 5); it went on to topic 4.

## Agenda

1. The objects and their names. *Done.*
2. Dependencies: join rules, branches not taken, final statuses, disabled jobs. *Done.*
3. Conditions: what they can test, and the language or builder (shortcoming 3). *Language and outputs decided; what else to test, the builder and Explain open.*
4. Reactions to outcomes: return codes, rerunning upstream (shortcoming 2). *Proposed, widened to time and duration; five questions open.*
5. Restarts and bypassing. *Net result, Resume and the Rerun menu decided.*
6. The diagram and editor: cross-workflow links, density, full names (shortcomings 4 and 5).
7. Run records: Job History, the Operations Log, the trace.
8. The first slice to build: the smallest thing that shows the idea.

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

## Proposed, to settle

- **Reactions, topic 4** (proposed 2026-10-17; widened the same day at the owner's request):
  - a list on a job or a workflow; each entry is *When* (an event, with a condition in flow control's language about the job: `%{Load.ReturnCode} IN (4, 8)`) and *Then* (one or more actions);
  - **kinds of When**, all in the one list and editor; to the user one mechanism, though the code paths differ:
    - *it ends*: status, return code, outputs, Operations; checked once, at the end;
    - *it hasn't started by…* and *it hasn't ended by…*: a time of day, or relative ("within 2 hours of the workflow starting"); a watcher with a timer;
    - *it runs longer than…*: a fixed time, or compared with its own Job History ("50% over its average of the last 10 runs");
    - this replaces a separate SLA mechanism. RunMyJobs' SLAs are wholly separate from job statuses and very complex; the owner wants the same reach, made user-friendly. Absolute times mean the day the run started until AutoApp has scheduling;
  - **actions**, offered only where they fit the kind of When:
    - *decisions*, changing what happens next: Count as succeeded / failed (the real code and the counted status shown side by side), Rerun this job (Resume or Restart from beginning, after a wait, at most N times), Rerun from… (a chosen upstream job and everything between it and this one, at most N times), Skip… (chosen jobs, or the rest of a branch), Stop the workflow (as failed or succeeded; jobs not started are Not run), Hold for an operator (Control-M's "leave it waiting", on purpose and visible), Cancel the job;
    - *side effects*, changing nothing in the run: Notify, Mark as late (a flag, not a status, shown on the diagram and in Job History and searchable: the record of a missed deadline), Start a workflow (the one push in the model, drawn as an outside link);
  - **how entries combine** (a hybrid of first match and Control-M's On-Do): every entry is judged against a snapshot of what actually happened, so no entry's actions change what a later one sees; of the matching entries' decisions, only the first takes effect (the editor warns of one that can never apply); every matching side effect fires. Control-M instead fires every matching On in order, and an earlier Do can change how a later On evaluates;
  - each rerun's N counts per workflow run; when it is used up, the next matching decision applies ("rerun twice, then hold");
  - a workflow's own Reactions decide its final status; by default a workflow with a Failed job is Failed;
  - "Explain" shows which entries matched and which actions took effect.
  - Questions for the owner:
    1. the hybrid, or strict On-Do order (does sequential evaluation do something in practice that would be missed);
    2. the kinds of When: anything missing ("a step reached", "a file arrived");
    3. an overridden status shown as both ("Succeeded (return code 4)") rather than a seventh status;
    4. Stop the workflow while jobs run: let them finish or cancel them (proposed: a choice on the action, "let them finish" first);
    5. whether steps' On failure should become Reactions too, one mechanism for both.

## Open questions, by topic

- **Conditions (3):** what else a condition can test: files present for an endpoint (perhaps `files('INBOUND_ORDERS')`), workflow variables, a time window, a job in another workflow; the builder; "Explain" against a past run.
- **Reactions (4):** see the proposal above; also, for an outside prerequisite that times out, whether the job counts as failed or not run.
- **Restarts (5):** each job's attempts kept, so a restart resets only the jobs chosen; restarting from the point of failure, from a chosen job, or bypassing one; what Advanced… offers; the open points of resuming (above).
- **Diagram and editor (6):**
  - how prerequisites outside the workflow (like RunMyJobs' Wait and Raise Events) are drawn (shortcoming 4);
  - a dense diagram that shows full names (shortcoming 5);
  - how embedded and shared jobs are told apart.
- **Run records (7):**
  - how a workflow's runs appear in Job History, the Operations Log and the trace (perhaps a parent run with each job's run as a child);
  - showing each job's state in a workflow run without a run record for jobs that have not started;
  - job keys for embedded jobs (a key names the job's working folder; perhaps `MONTH_END.Extract`);
  - whether embedded jobs are left out of Job History's lists, or shown under their workflow.
- **Embedded and shared:** making an embedded job shared when a second workflow wants it, and a shared one into an embedded copy.
- **The first slice (8):** what to build first to show the idea.

## Later

- Scheduling in AutoApp, perhaps improving on RunMyJobs' Time Window and Submit Frame pair.
- With scheduling: what an outside prerequisite with no time limit means when there is no daily cycle (like Control-M's New Day Process) to end its wait.

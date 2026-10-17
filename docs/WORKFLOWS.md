# Workflows: design

The design record for AutoApp's workflows, built up in design sessions with the owner. What a workflow is for, and the RunMyJobs shortcomings it answers, are in [PROJECT_GOALS.md](PROJECT_GOALS.md) goal 2. This page holds everything else: the starting point, what is decided, what is proposed, and the open questions.

Status: **being designed. Nothing is built.** The session reached topic 2 of the agenda on 2026-10-17.

## Agenda

1. The objects and their names. *Done.*
2. Dependencies: join rules, branches not taken. *Proposed; three questions open.*
3. Conditions: what they can test, and the language or builder (shortcoming 3).
4. Reactions to outcomes: return codes, rerunning upstream (shortcoming 2).
5. Restarts and bypassing.
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

## Proposed, to settle

- **Topic 2, dependencies** (proposed 2026-10-17):
  - a prerequisite tests, by default, that the other job succeeded; or that it ended, failed, or gave specific return codes;
  - a job's prerequisites combine as *all* by default, or *any*; anything finer is an expression (topic 3);
  - a prerequisite that can never hold (the other job failed, or was itself not run) makes the job "Not run: its prerequisites can't be met", cascading downstream; a prerequisite testing "ended" counts a job not run as ended, so clean-up jobs still run;
  - a prerequisite outside the workflow cannot be known impossible: it waits, with an optional time limit;
  - the workflow ends when every job has succeeded, failed or not run.
  - Questions for the owner:
    1. are *all* and "succeeded" the right defaults;
    2. is cascading "not run" right, rather than jobs left waiting as in RunMyJobs and Control-M;
    3. should a job not run because its prerequisites can't be met look different from one skipped on purpose by a Reaction.

## Open questions, by topic

- **Conditions (3):**
  - what prerequisites and Reactions can test: status, specific return codes and ranges, files present, a value from an earlier job, a time window;
  - a typed language or a builder with a readable text form; how a condition is validated as it is written, and evaluated against a past run to see why it came out as it did (shortcoming 3).
- **Reactions (4):**
  - "go back upstream and rerun" as an action rather than an arrow (a graph has no cycles), with a limit on how many times;
  - when a workflow with a failed job counts as failed;
  - for an outside prerequisite that times out: whether the job counts as failed or not run.
- **Restarts (5):** each job's attempts kept, so a restart resets only the jobs chosen; restarting from the point of failure, from a chosen job, or bypassing one.
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

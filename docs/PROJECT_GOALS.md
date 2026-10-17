# Project Goals

## Vision

AutoApp is a testbed and demonstrator for scheduler features the owner would like to see in RunMyJobs (Redwood). Each feature is built far enough to show how it would look and behave, and to check that it behaves as intended.

AutoApp began as the product now called RunMyFiles. On 2026-10-16 that product was forked into its own project (`~/projects/RunMyFiles`), and the two share nothing. RunMyFiles leaves sequencing to the scheduler; AutoApp plays the scheduler, so sequencing is exactly what it demonstrates.

These are goals. For what is actually built, see [PROJECT_BLUEPRINT.md](PROJECT_BLUEPRINT.md).

## Goals

### 1. Show a better design, not a product

- The point of each feature is its design: the model, the editor, and how it reads on screen. A feature is finished when it shows the idea convincingly.
- AutoApp runs what it designs only as far as needed to prove the design behaves as intended. Execution is a means of validation, not an end.
- With no real WLA to integrate with, AutoApp runs its own workflows itself.

### 2. Workflows: the first feature

A workflow is a set of jobs with dependencies between them, designed in AutoApp and run by it. It answers these shortcomings of RunMyJobs job chains, in priority order:

1. **Flexible dependencies.** A chain's stepwise model fits many workflows badly and forces workarounds for complex dependencies, especially in migrations from other products. Workflows express dependencies directly between jobs.
2. **Granular decisions downstream.** Status handlers act only on a job's status (Completed, Error and so on). Workflows can act on more, such as specific return codes, including going back upstream to rerun part or all of the flow.
3. **Conditions people can read and write.** Precondition expressions in REL are hard to read, harder to write, poorly documented, have no helpers in the UI, and cannot be validated or debugged. Workflow conditions come with help, validation and a way to see why they evaluated as they did.
4. **Every dependency visible.** A Wait Event in one chain that depends on a Raise Event in another is invisible in RunMyJobs' UI. Workflows show cross-workflow dependencies on screen.
5. **A compact, complete picture.** RunMyJobs' chain diagrams waste space yet still hide crucial information, such as cross-chain dependencies and call names truncated well before the 80-character limit. Workflow diagrams are dense and show full names.
6. **Structure that stays with its parent.** Sub-chains created only to model dependency structure get generic system names, are not linked to their parent, and turn up in queries and reports. Any grouping inside a workflow belongs to it, is named for it, and stays out of lists of jobs and workflows.

Restarting part-way through (at the point of failure, from a chosen job, or bypassing a job fixed by hand) is part of the design too.

### 3. Build on what exists

- AutoApp's jobs, steps, endpoints, variables, Job History, the Operations Log and the trace are already built. Workflows reuse them rather than replacing them.
- The Stand-in Scheduler (`demo/scheduler_standin`) remains available to launch runs.

### 4. Easy to show

- A feature can be demonstrated from a clean setup in a few minutes, with sample data that shows its point.
- What is on screen uses plain words, as a WLA operator would.

## Non-goals

- Production use. Security hardening, scale and operational robustness matter only as far as a demonstration needs them.
- Integration with a real WLA product.
- Keeping step with RunMyFiles. A feature proved here may be ported there, but AutoApp is not required to stay compatible with it.

# Workflows, Phase 3: return codes and Reactions

The third phase of [WORKFLOWS.md](WORKFLOWS.md) ("Implementation in phases"): **a job's outcome decides what happens next, beyond "go on" or "stop".** It answers shortcoming 2 (reacting to return codes, rerunning upstream), and adds Kill and Disable here.

Status: **agreed with the owner 2026-10-18; built 2026-10-18 (steps 0 to 6), waiting for the owner's review.**

## Starting point

Already built, in Phase 1:

- Success return codes on a job (`0` unless set); a step setting the job's return code (Simulate does); prerequisites testing return codes.
- Disabling a job's definition: a hard stop in every workflow that uses it (Disabled), with the warning naming those workflows.
- Cancel what hasn't started on a running workflow (the workflow ends Failed, `CANCELLED`).
- Attempts on job runs and on workflow run items (always 1 so far), so reruns need no new shape.

## What Phase 3 includes, and what it leaves out

- **In (proposed):**
  - **Reactions on a job's end** (*it ends* only), edited in a Reactions box shared by the job page and the workflow page:
    - **What happens next** (ordered, the first that holds wins) and **Also** (every one that holds fires);
    - decisions: **Count as succeeded**, **Count as failed**, **Rerun this job** (after a wait, at most N times), **Rerun from…** (a chosen upstream job and everything between, at most N times), **Skip…** (chosen jobs, or the rest of the branch), **Kill the workflow**;
    - side effect: **Start a workflow**.
  - **Overrides shown as both:** "Succeeded (return code 4)", in the outline, the diagram, Job History and the log.
  - **Kill** on any running job; on a workflow, **Kill and Cancel** (kills what runs, cancels what hasn't started); Failed, `KILLED`.
  - **Disable here** on a job in a workflow: **Stop here** (Disabled) or **Pass through** (Bypassed, `DISABLED_PASS_THROUGH`).
  - **On the diagram:** the "has Reactions" marker on a box; Rerun from… as the dash-dot ↺ line; Start a workflow as a right-edge stub; the Disabled-here and Bypassed looks; a Rerun's attempts on the box ("attempt 2 of 3").
  - **"Explain" for Reactions** in its simplest form: the job log and the run view say which entries matched and which actions took effect.
  - **The Set Return Code step:** sets the job's return code and carries on; the last one run wins (inside an If, a job chooses its own code). Complete as CLAUDE.md asks of a step type.
  - Carried from Phase 2: Jobs & Workflows says "*N* found".
- **Out, in TO-DO:** a When written as an expression; Hold for an operator; a Script step.
- **Out, for later phases:** Reactions' Explain against a past run (4); time-based Whens, Mark as late, Notify (8); Resume, so Rerun this job always restarts from the beginning (7); a workflow's completion rules (with conditions, 4); steps' On failure becoming Reactions (later, one mechanism for both).

## The steps (proposed)

0. **The Set Return Code step,** complete as CLAUDE.md asks of a step type.
1. **Model and migration:** Reactions (on a job definition, and on a use that overrides them): order, section (Next or Also), the When, the actions and their settings; counts of automatic reruns per run; `OverrideStatus` beside a run's `Status`; `DisabledHere` on a workflow item; the runner's process id on job runs, for Kill.
2. **The engine:** when a job ends, its Reactions are judged (by the job runner for a job on its own, by the workflow runner in a workflow), against a snapshot; applies the first matching decision and every side effect; reruns as new attempts; Skip, Kill; counts and their limits ("rerun twice, then count as failed"); every choice in the job log and the Audit Log.
3. **Kill and Disable here:** Kill on the workflow run and on a job run; the job runner ends Failed, `KILLED` when told to stop; Disable here in the runner and on both pages.
4. **The Reactions box:** on the job page and the workflow page's side panel, the two sections, drag to reorder, each action's settings, offered only where they fit.
5. **The run and the diagram:** overrides, attempts, the new markers and lines; Job History showing attempts and overrides.
6. **Sample, docs and tests:** a sample workflow using each Reaction (a return-code rerun, a Count as, a Rerun from… loop with its limit, a Set Return Code inside an If); CHANGE_LOG, PROJECT_BLUEPRINT, WORKFLOWS.md; engine tests for every action and for how entries combine; UI tests for the box, Kill and Disable here.

## Decided with the owner (2026-10-18)

1. **A Set Return Code step**, not a Run Program step: it sets the job's return code and the job carries on; the last one run wins. A Script step (Bash, Python, PowerShell…), making the step library user-extensible, is a good idea for later (TO-DO).
2. **Reactions are job-level settings, which a use can override.** A use shows its job's Reactions, greyed and marked "from the job"; **Override here** copies them into the use to edit, and from then on the use's list is the whole list (no merging, so "which one fires" has one answer). Rerun from… and Skip… name other jobs, so only a use offers them.
3. **The When is a simple outcome choice**, like a prerequisite's Outcome (Succeeded, Failed, Ended, return codes, any status), with no Custom option on screen. A When written as an expression is for later (TO-DO), not needed for workflows.
4. **No Hold for an operator.** It came up while settling what Cancel and Kill mean, and workflows don't need it; it is in TO-DO, where a first version needs only **Release**.

5. **Reactions apply wherever the job runs**, on its own or in a workflow. On its own, the job runner acts on them (Count as, Rerun this job, Start a workflow); in a workflow, the workflow runner does. Rerun from…, Skip… and Kill the workflow exist only on a use.
6. **Kill is offered on any running job**: on its own, within a workflow run, or a workflow. On a workflow it kills the jobs running in it and cancels those not started; its button says **Kill and Cancel**. A single job's says **Kill**. Failed, `KILLED`.

## Decided while building (2026-10-18), for the owner's review

7. **The rest of the branch** is what waits for the job, directly or not, **except** the jobs that wait for the outcome it actually had (a failure path, a clean-up waiting for it to end) and what follows them: those still run. Found with the sample: skipping everything downstream also skipped its clean-up, and the failure then counted as unhandled.
8. **A killed job's Reactions do not apply**: someone stopped it on purpose, so an automatic rerun would undo that. A job killed by Kill the workflow, or by Kill and Cancel, likewise.
9. **Bypassed counts as succeeded with return code 0** for prerequisites, so a test for return codes `0` or `0-4` holds too.
10. **Kill works on this machine only**: the server signals the runner's process. A job on another host says so; that waits for agents.
11. **Start a workflow** is shown as the Reactions marker on the box, with the words on pointing at it, not yet as a right-edge stub.
12. **A workflow's own Reactions**: a workflow is a job, so it has them too, on its page; Rerun this job reruns the whole workflow, as a new run (the next attempt).
13. **Reactions that fired** are listed with the run, folded, and on each job's panel in the diagram.
14. **The process ID reaches the database at once whenever there is an API**: the runner's first record carries it. Without one (a scheduler not passing `--api-url`, or the tests), a job on its own is not killable from the page until its records are delivered (TO-DO, decision 2); a job in a workflow always is, since the workflow runner records it.

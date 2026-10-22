# Workflow decisions

Every decision behind how AutoApp's workflows work, in one place, each with **why**: the problem it solves or the trap it avoids. Before changing one, read its why: it may name the trouble the change would bring back.

- **Status:** *Built* (and when), *Designed* (agreed, not built yet; the phase that builds it), *Replaced* (kept, pointing to what replaced it, so the history stays), *Moved out* (taken out of the workflow track, and where it went).
- **Source:** where the decision was first written down, with the detail: [WORKFLOWS.md](WORKFLOWS.md) (the design record) and the phase plans ([1](WORKFLOWS_PHASE1.md), [2](WORKFLOWS_PHASE2.md), [3](WORKFLOWS_PHASE3.md), [4](WORKFLOWS_PHASE4.md), [5](WORKFLOWS_PHASE5.md)).
- Where no reason was recorded at the time, the entry says **Reason not recorded**, rather than one being made up afterwards. Those are worth confirming with the owner.
- New decisions are added here as they are made, with their reason; numbers are never reused.

Compiled 2026-10-18, from the design record and Phases 1 to 4.

---

## The model

**D1. A workflow is a graph, not steps.** Everything in a workflow runs in parallel unless prerequisites say otherwise.
- *Why:* RunMyJobs' stepwise chains have no real advantage beyond an easy layout and an easy-to-explain barrier, and each step boundary adds dependencies nobody asked for, which is where the dependency workarounds (shortcoming 1) and the structural sub-chains (shortcoming 6) come from. Restarts work as well in a graph. "All of these, then those" is still expressible with an embedded workflow (D7), so a RunMyJobs chain still imports directly.
- *Considered:* steps, as RunMyJobs chains.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "The model is a graph".

**D2. One kind of dependency: look-back.** A job checks its prerequisites when it is ready to start; there is no separate "push" from one job to the next.
- *Why:* in practice push means nothing different. ActiveBatch has both because its triggers define the batch and let a workflow exist outside any Plan, which AutoApp's Workflow object makes unnecessary; and it creates a job's instance only when the trigger fires, a clarity AutoApp gets from its run model instead (D24). Push survives only in Reactions, such as Rerun from.
- *Considered:* ActiveBatch's Triggers beside Constraints; Control-M's conditions (a hybrid, neither better nor worse).
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "One kind of dependency".

**D3. A workflow is a kind of Job** (`JobType` STEPS or WORKFLOW), not a separate kind of definition: a common core in Jobs, type-specific content beside it (steps in JobSteps; items and prerequisites in their own tables); pages and runners choose by type.
- *Why:* one set of keys used the same way (a scheduler starts a workflow by its key, as a job); everything common written once (variables, tags, Audit Log, search, Reactions, Success return codes, Disable); a workflow's run *is* a job run. The common core with type-specific tables avoids RunMyJobs' clumsiness of forcing a chain into a job definition's shape.
- *Considered:* a separate object (ActiveBatch's Plans); one shape for everything (RunMyJobs).
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "A workflow is a kind of Job".

**D4. No job types other than steps and workflow.** "What kind of work" is a step type.
- *Why:* step types already have handlers, help, preview, outputs, operation records and masking; a job of one step costs nothing. Job types differ only in structure.
- *Status:* Built. *Source:* WORKFLOWS.md, "A workflow is a kind of Job".

**D5. Names: Job, Workflow, Prerequisite.** Not ActiveBatch's Plan, Trigger, Constraint.
- *Why:* Job is what every WLA says; AutoApp's design must not look obviously copied from ActiveBatch, so its objects have their own names.
- *Status:* Built. *Source:* WORKFLOWS.md, "Names" and "Starting point".

**D6. Every job in a workflow has a name unique within it**, letters, digits, `_` and `-`; a used job takes its definition's name by default; only a second use of the same job needs another (`Extract`, `Extract_EU`).
- *Why:* conditions refer to jobs by that name (`%{Extract.Succeeded}`), so it must say one thing. Unlike flow control's StepNames, names never repeat: jobs in a workflow run at the same time, so "the later one wins" means nothing.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "Names of jobs in a workflow".

**D7. A workflow holds jobs embedded (its own) or shared (used from elsewhere)**; no separate Reference object, no new noun for a use on screen.
- *Why:* an embedded workflow is what RunMyJobs' structural sub-chains should have been: it belongs to its parent and stays out of the Jobs & Workflows page and the search pages (shortcoming 6); the editor of its workflow shows it. Shared jobs let one definition run several times with different values. Everything on the diagram is a job or a workflow, so there is nothing new to learn.
- *Considered:* ActiveBatch's Reference objects.
- *Status:* Built (Phase 1: shared jobs; Phase 6, 2026-10-20: embedded jobs and workflows, D116 to D135). *Source:* WORKFLOWS.md, "What a workflow holds".

**D8. The model was built for the full design from the start**: unique names, a path for every job, attempts on job runs, an owner column for embedded jobs, a column for conditions.
- *Why:* later phases then add behaviour without reshaping data, and without migrations that move existing records around.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS_PHASE1.md.

**D9. Jobs may still run on their own.** Putting jobs in workflows is advice, not a rule.
- *Why:* building and testing a job means running it by itself; schedulers start jobs by key (INTEGRATION.md is a contract); RunMyJobs has standalone jobs, so the rule would not carry over. AutoApp shows instead that a workflow costs no more than a job, so dependencies go where they belong because nothing pushes them elsewhere (RunMyJobs bills a chain's run like a job's, which pushes people to odd structures).
- *Status:* Built. *Source:* WORKFLOWS.md, "Jobs may still run on their own".

**D10. The Simulate step type**: logs lines, waits, exits with a given return code, optionally fails. Brought forward to Phase 1.
- *Why:* the owner's practice from testing RunMyJobs chains with a configurable dummy job: workflows can be built and tested without real jobs, and return-code prerequisites shown working.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md; WORKFLOWS_PHASE1.md.

**D11. Success return codes on every job** (`0` unless set; lists and ranges). A code on the list means Succeeded, not an override.
- *Why:* return codes are the language between a job and what follows it (shortcoming 2); which codes mean success belongs to the job.
- *Status:* Built (Phase 1); a use overriding its job's codes is Designed. *Source:* WORKFLOWS.md, "Success return codes".

## Prerequisites and starting

**D12. Prerequisites exist only in workflows**, on a job's use there, never on a job's definition.
- *Why:* what a job *is* belongs on its definition; how it *fits in* belongs on its use. Prerequisites on a definition would give every workflow using it waits not visible where one looks (shortcoming 4 again). A standalone job that must wait is a one-job workflow, or uses flow control inside it.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "Where prerequisites live".

**D13. A prerequisite tests, by default, that the other job succeeded**; or failed, ended (any final status, Not run included), or gave chosen return codes.
- *Why:* success is what most waits mean; "ended" lets clean-up jobs run whatever happened, Not run included; return codes carry outcomes finer than pass or fail.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "Dependencies".

**D14. A job's prerequisites must all hold by default; Any is the alternative; anything finer is a Custom rule** (D46).
- *Why:* All and Any cover the common cases in words anyone reads; a condition language covers the rest without a third fixed option.
- *Status:* Built (All and Any in Phase 1; Custom rule in Phase 4). *Source:* WORKFLOWS.md, "Dependencies".

**D15. A prerequisite that can never hold makes the job Not run** (Reason `PREREQUISITES_NOT_MET`), cascading to what needed it to succeed. Jobs are not left waiting.
- *Why:* Control-M can leave such a job waiting because its New Day Process cleans up yesterday's jobs, and an operator can add the missing condition by hand. In AutoApp the workflow run is the scope: cascading lets a run end cleanly, and "release it anyway" becomes bypassing or restarting part of the run (D61).
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "Dependencies".

**D16. Patience on each prerequisite, the consequence on the job.** Each prerequisite can wait with no limit (the default inside a workflow), up to N minutes, or until a time, and be required or optional; the job says what "can't start" means: Not run (default), Fail (`PREREQUISITES_NOT_MET` or `TIMED_OUT`), or Hold.
- *Why:* patience belongs to each thing waited for (the file has until 02:00, the other workflow until 03:00); the consequence belongs to the job, which has one fate however it failed to start. A time-based Reaction ("not started by 03:00") sits beside this as a side effect, not deciding the job's fate.
- *Status:* Built (Phase 5, 2026-10-19), except Hold for an operator, which depends on D58. Patience and what "can't start" means are D99 to D101 and D110. *Source:* WORKFLOWS.md, "Prerequisites that aren't satisfied".

**D17. A prerequisite's target can be outside the workflow** (a job in another workflow, an endpoint, a time window), defined on the prerequisite; conditions may name only the workflow's own jobs and the targets of the job's own prerequisites.
- *Why:* every outside reference is then a prerequisite, and every prerequisite can be drawn: nothing a job waits for is hidden (shortcoming 4, RunMyJobs' invisible Wait Events).
- *Status:* Built (Phase 5, 2026-10-19; the names conditions use for them are D113). *Source:* WORKFLOWS.md, "Where prerequisites live, and outside targets".

**D18. Another workflow's job counts by its current or latest run**: the run executing now, else the most recent completed; optional limits against a stale success.
- *Why:* "today's run" breaks workflows that cross midnight; yesterday's success must not satisfy a wait while today's run is going. This is ActiveBatch's "Exact active", under a name that says what it means.
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS.md, "Which run of another workflow counts".

**D19. An endpoint as a target**, with a minimum age (every file unchanged for N seconds), sharing code with Check Files' minimum age.
- *Why:* a job must not start on a file still arriving; one check of modified times is simpler than the "Stable" first proposed, and is the same concept as in Check Files.
- *Considered:* a `Stable` test.
- *Status:* Built (Phase 5, 2026-10-19): the age test is one shared function (`engine/file_age.py`); Check Files' own `MinAgeSeconds` parameter is still a TO-DO item. *Source:* WORKFLOWS.md, "Topic 3's other targets".

**D20. Time windows as a built-in value**, `%{Now.Time}`, `%{Now.Date}`, `%{Now.Weekday}`; as a prerequisite, it waits until the window opens.
- *Why:* "not before 02:00" is a condition like any other, in the same language, rather than a separate kind of object.
- *Status:* Built (Phase 5, 2026-10-19; the details are D107). *Source:* WORKFLOWS.md, "Topic 3's other targets".

**D21. Starting a workflow: by hand, from its page** (or by a scheduler, by key, like any job).
- *Why:* how workflows are initiated is not what AutoApp demonstrates; scheduling may come later.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "Starting a workflow".

**D99. When an outside prerequisite's "up to N minutes" starts is a choice on the prerequisite:** (1) after the job's other prerequisites have held (the default); (2) after the first of them holds; (3) after a chosen prerequisite holds; (4) from the start of the workflow run. "Until a time" is a clock time and needs none.
- *Why:* counting from the workflow's start alone would time out a job sitting behind a long upstream job; the right start differs by case, and the four are the natural anchors (all, first, a chosen one, the run). The owner, 2026-10-19, made the third "a chosen prerequisite" rather than the fourth option proposed ("after a chosen job ends"), as it fits the others and reads better.
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, proposal 2; refines D16.

**D100. An outside prerequisite waits at most 24 hours by default**, a system setting ("Default wait for outside prerequisites"), shown on each prerequisite as "Default (24 h)"; "No limit" is a deliberate choice, and saving a prerequisite with none warns.
- *Why:* AutoApp has no daily cycle to end a stale wait (Control-M's New Day Process does), so an unlimited wait could hang forever; a limit that is visible and editable is not hidden magic.
- *Considered:* no limit by default (the owner was not sure an indefinite wait is better than an arbitrary default).
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, proposal 3; the owner, 2026-10-19.

**D101. An optional prerequisite is waited for up to its limit, then dropped from the job's check; the job's other prerequisites still decide.** It needs a limit (without one it would be the same as required). If nothing else is left, the job starts. In a Custom rule, its outputs are unknown (`NULL`).
- *Why:* the owner's reading: "wait N minutes, then run without it if the others are satisfied". Counting it as *held* instead (the first proposal) would start a job with the Start rule Any at once when the optional wait timed out, even if none of its other prerequisites held.
- *Considered:* counting a timed-out optional prerequisite as held.
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, proposal 4; the owner, 2026-10-19.

**D102. A prerequisite's target can also be a whole workflow** (its final status), not only a job in it.
- *Why:* "wait for the nightly load" is the common wish, and sub-workflows (structural ones) could not work otherwise. Cheap, because a workflow is a kind of job (D3) and its run is a job run.
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, proposal 9; the owner, 2026-10-19.

**D103. A time window that spans midnight is written `%{Now.Time} IN WINDOW '18:00' TO '06:00'`**: after the start, or before the end when the end is earlier. It is AutoApp's own syntax, translated to plain comparisons before the condition is worked out; the builder shows it in words.
- *Why:* `BETWEEN` cannot wrap past midnight and the `OR` form is easy to get wrong (a `23:59` end leaves a gap). A mainframe scheduler's times past 24 hours (`99:00` for 4d3h) made users do the arithmetic.
- *Considered:* the `OR` form alone (still works); times beyond 24:00.
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, proposal 6; the owner, 2026-10-19.

**D104. Prerequisites may not form a cycle, within a workflow or between workflows**; the message points to Rerun from… (D39). A cross-workflow loop (a Rerun-workflow Reaction with a limit) is a TO-DO item.
- *Why:* neither job of a prerequisite cycle can ever make its first start, so no exit could fire (D39).
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, proposal 7; the owner, 2026-10-19.

**D105. An endpoint prerequisite checks the files where the endpoint says; no queue or agent field yet.** If agents or queues come, the endpoint reference gains a "checked on" field, as ActiveBatch's file constraint names a queue.
- *Why:* AutoApp has neither queues nor agents; the owner thought ActiveBatch's way worked well, so the place for it is kept free.
- *Status:* Built (Phase 5, 2026-10-19; local endpoints only: files on another Site make the pre-run check fail). *Source:* WORKFLOWS_PHASE5.md, proposal 10; the owner, 2026-10-19.

**D106. A prerequisite outside the workflow is never "impossible": a job elsewhere that failed is waited out, not given up on.**
- *Why:* inside a workflow a job's final status settles the matter (D15); elsewhere the other workflow may run again, and the run that counts is its current or latest (D18). Patience (D16, D99, D100) is what ends the wait, so a stale failure cannot hang a job for ever, and a late success is not missed.
- *Considered:* treating a failed job elsewhere as Never, as inside. It would make the job Not run at once, before the other workflow's rerun could help.
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, "Decided while building".

**D107. `%{Now.Time}` is the time of day as `HH:MM` (24 hours), `%{Now.Date}` as `2026-10-19` and `%{Now.Weekday}` as `Monday`, all the server's local time; `BETWEEN` and `IN WINDOW` include both ends.**
- *Why:* minute resolution is what `BETWEEN '06:00' AND '18:00'` means to anyone; seconds would leave 18:00:30 outside a window that "ends at 18:00". Other times in AutoApp are local too.
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, "Decided while building".

**D108. A prerequisite that holds is looked at again every pass; one that has run out of patience stays so for that attempt of the job.**
- *Why:* a time window must be able to close again, and a file can be taken away, so "held once" is not "holds". But a timeout that could flip back would let a job start after it had been declared Not run. A rerun of the job starts the patience afresh.
- *Considered:* keeping a prerequisite held once it has held, as inside a workflow (a job's final status does not change).
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, "Decided while building".

**D109. In a Custom rule, a required outside prerequisite that runs out of patience ends the job whatever the rule says; an optional one makes its values unknown.**
- *Why:* "required" means the job cannot start without it (D16), which a rule like `A OR B` must not undo by accident. Unknown values are how an optional prerequisite is dropped (D101).
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, "Decided while building".

**D110. A job that cannot start ends Not run or Failed, as the job says (`OnUnmet`), with the Reason `PREREQUISITES_NOT_MET` (a prerequisite inside the workflow can never hold) or `TIMED_OUT` (a required one outside ran out of patience).**
- *Why:* the two causes are different to whoever reads the run, and the consequence belongs to the job whatever the cause (D16). Hold for an operator is not offered (D58, not built).
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, "Decided while building".

**D111. The check for loops between workflows is made between jobs, with a whole workflow counting as waiting for all its jobs.**
- *Why:* two workflows can wait for each other without a loop (A's first job waits for B's first, B's second waits for A's second); refusing every pair would forbid ordinary hand-offs. The message names the path of jobs.
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, "Decided while building".

**D112. What each outside prerequisite found is kept for every attempt of the job** (`WorkflowPrerequisiteChecks`): waiting, held, ran out of patience, given up (optional) or not needed (the job started without it), the run of the other workflow used, how it stood when last looked at, and a message. A run's page shows it live, and the job log says it too.
- *Why:* shortcoming 4 is about not being able to see what a job is really waiting for; the answer has to be there afterwards as well. It reads the database, never the operations log (the telemetry principle).
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, "Decided while building".

**D113. Something outside gets a name that conditions use** (`MONTH_END.Extract`, `INBOUND_ORDERS`, `Time`): made from what it is, editable, unique among the job's own prerequisites, never the name of a job in the workflow, and never `Now`. A name may hold dots, so `%{MONTH_END.Extract.Status}` is read against the names known first.
- *Why:* D17 lets a Custom rule name the targets of the job's own prerequisites; a name that was a job's key would clash, and dots keep the workflow and job visible in the name.
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, "Decided while building".

**D114. Nothing that others wait for can be removed from under them**: a job other workflows wait for cannot be taken out of its workflow, a workflow they wait for cannot be deleted, an endpoint a workflow waits for cannot be deleted (each message names who waits). Files must be on this server: a prerequisite on an endpoint at a Site makes the pre-run check fail.
- *Why:* decision 8 of the plan: the foreign key would otherwise cascade and silently drop the prerequisite, and the job would start without what it waited for. Remote endpoints wait for the SFTP step type (D105).
- *Status:* Built (Phase 5, 2026-10-19). *Source:* WORKFLOWS_PHASE5.md, "Decided while building".

**D115. Outside things are shaded and tagged so they cannot be mistaken for jobs of the workflow, and each of the two groups can be hidden.**
- Jobs and workflows elsewhere, and the jobs elsewhere that wait for a job here ("Needed by"), are dashed boxes with a flat amber tint, tagged **EXTERNAL** beside the icon in the upper-left corner. Files and times, which run nothing, are dashed boxes with a flat blue tint, tagged **FILES** or **TIME**. The tint is one flat colour, dark in the dark theme and light in the light one, so the words keep their contrast.
- Two options in the diagram toolbar, remembered in the browser: **Show external references** (on by default) and **Show non-executable dependencies** (off by default). A group switched off is not drawn as boxes and lines: each thing becomes a small icon in the header of the box it applies to, with its wording on pointing at it. They apply to a run's diagram too.
- *Why:* the owner, 2026-10-19, on seeing the first version: it was not obvious that the box was outside the workflow (the plan's boxes were dashed but otherwise looked like jobs, and drifted from the mockup, which draws them unfilled); hatching was hard on the eyes and hurt the contrast; a complex workflow would be extremely cluttered by a box for every file and time, so those are off by default, while jobs elsewhere are what shortcoming 4 is about and stay on.
- *Considered:* hatched shading (rejected for contrast); one switch for everything (rejected: the owner wants the two groups apart); showing the boxes only on selection.
- *Status:* Built (Phase 5, 2026-10-19), refining D80. The mockup page (D88) still draws the first look. *Source:* WORKFLOWS_PHASE5.md, "Decided while building".

## Running

**D22. The workflow runner works on the database directly**, beside the server, not on an agent; job runners report through the API as before.
- *Why:* in ActiveBatch terms, workflows run on the server's own virtual queue, the natural home if queues ever come; the workflow runner is scheduling-engine work, not payload.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "Where workflows run"; WORKFLOWS_PHASE1.md.

**D23. A run reads the workflow once, at its start.**
- *Why:* editing a workflow must not change a run already going.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS_PHASE1.md.

**D24. One Job History.** A workflow's run is a job run; its jobs' runs point to it; Workflow Run Items record each job's state, so jobs that never started show without job runs of their own.
- *Why:* one place to look, one search; a run shows every job's state without making records for jobs that never ran (the clarity ActiveBatch gets from creating instances only when triggered).
- *Status:* Built (Phase 1). *Source:* WORKFLOWS_PHASE1.md.

**D25. Job History is a tree**: workflow runs folded by default with a count; a search for a job's runs still finds them, shown with their workflow; paging counts top-level rows.
- *Why:* a flat list with a Parent column buries the shape; folding keeps busy histories readable; a workflow is never split across pages. **Reason for folding by default not recorded beyond readability.**
- *Status:* Built (Phase 2, owner's decisions 2 and 7). *Source:* WORKFLOWS_PHASE2.md.

**D26. The final statuses are six**: Succeeded, Failed, Skipped (on purpose, by a Reaction), Not run (prerequisites can't be met), Disabled (hard stop), Bypassed (treated as succeeded without running).
- *Why:* each kind of job that did not run means something different to whoever reads the run, and each has its own look on the diagram.
- *Status:* Built (Phases 1 and 3). *Source:* WORKFLOWS.md, "Final statuses".

**D27. Reason, not Cancelled and Killed statuses.** A standard `Reason` beside `Status`: `KILLED`, `TIMED_OUT`, `ERROR` (Failed); `CANCELLED`, `PREREQUISITES_NOT_MET` (Not run); `DISABLED_PASS_THROUGH`, `MARKED_DONE` (Bypassed).
- *Why:* separate statuses would add two cases to every prerequisite, "ended" test, Reaction and default, almost always "same as Failed" or "same as Not run". Their main use in RunMyJobs, standing in for return codes in Status Handlers, goes away when return codes are handled directly. `Reason` keeps the advantages: conditions test it, Job History filters on it, reports leave kills out, the diagram marks it.
- *Considered:* RunMyJobs' Cancelled and Killed statuses (for: triage at a glance, failure rates without deliberate kills, one-to-one migration).
- *Status:* Built (Phases 1 and 3). *Source:* WORKFLOWS.md, "Reason, not Cancelled and Killed statuses".

**D28. Never started is Not run; started and stopped on purpose is Failed**, with a Reason saying how.
- *Why:* the rule underneath Cancel and Kill: the status says whether the job ran; the Reason says why it stopped.
- *Status:* Built (Phases 1 and 3). *Source:* WORKFLOWS.md, "Kill, Cancel and Hold".

**D29. By default, a workflow succeeds unless a failure went unhandled**: a failed job fails it unless something that waits for it ran anyway; a job nothing waits for must not fail; Not run, Skipped, Disabled and Bypassed jobs do not count, except a job cancelled.
- *Why:* the owner's framing: a handled failure (a failure path that did its job) must not turn the workflow red. Refined so that a failure cut off by Not run still counts (A fails, B waiting for its success is Not run: nothing handled it). A cancelled job counts as unhandled so a workflow someone cancelled part of does not end green.
- *Status:* Built (Phase 1). Replaces D30. *Source:* WORKFLOWS.md, "When a workflow succeeds".

**D30. ~~Any failed job fails the workflow.~~**
- *Status:* Replaced by D29 (Phase 1, 2026-10-17): it made every failure path pointless, since the workflow failed anyway.

**D31. Completion rules**: *Succeeds when* (the default, or a condition) and *Return code* (0 or 1, or a chosen job's). *Ends when* waits.
- *Why:* some workflows need a different definition of success than D29, and a scheduler reading the workflow's return code may want a particular job's. *Ends when* needs more than conditions (leaving jobs running or killing them), so it waits.
- *Status:* Built (Phase 4); *Ends when* Designed, no phase yet. *Source:* WORKFLOWS.md, "When a workflow succeeds"; WORKFLOWS_PHASE4.md, decision 4.

**D32. Kill or Cancel with Succeeds when**: the rule still decides Succeeded or Failed, and the Reason says the workflow was killed or cancelled. Return code from a job that has none falls back to 0 or 1.
- *Why:* the design says a workflow's status follows its completion rules whatever happened; the Reason keeps the fact that someone stopped it. A job that did not run has no return code to give.
- *Status:* Built (Phase 4, decision 11). *Source:* WORKFLOWS_PHASE4.md.

**D33. Disabled jobs: both a hard stop and a pass-through**, from the start. Disabling the definition is a hard stop everywhere; disabling a use in one workflow (Disable here) is Stop here (Disabled) or Pass through (Bypassed).
- *Why:* ActiveBatch made disabling a hard stop and had to add Soft Disable later; both are needed. Disable here affects only that workflow, so the job itself stays usable elsewhere.
- *Status:* Built (Phases 1 and 3). *Source:* WORKFLOWS.md, "Disabled jobs".

**D34. Disabling a job warns which workflows use it, and the workflows still run.** A disabled job ends Disabled when its turn comes; only what is wrong with the workflow as a whole (disabled, empty) stops it starting.
- *Why:* disabling one job should not silently stop every workflow that uses it, nor surprise anyone; the warning says what will happen in each.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "Disabled jobs".

**D35. Bypassed counts as succeeded with return code 0** for prerequisites and conditions.
- *Why:* a pass-through means "carry on as if it worked", so a test for return codes `0` or `0-4` holds too.
- *Status:* Built (Phase 3, decision 9). *Source:* WORKFLOWS_PHASE3.md.

**D36. Cancel what hasn't started; Kill and Cancel.** Cancel starts nothing more and lets running jobs finish; Kill kills what runs and cancels the rest, down through workflows inside; the button says **Kill and Cancel**. Kill is offered on any running job, alone or in a workflow.
- *Why:* operators need both "stop adding work" and "stop now"; the button names both effects so nobody is surprised.
- *Status:* Built (Cancel in Phase 1; Kill in Phase 3, decision 6). *Source:* WORKFLOWS.md, "Kill, Cancel and Hold"; WORKFLOWS_PHASE3.md.

**D37. Kill works on this machine only** for now: the server signals the runner's process.
- *Why:* there are no agents yet; a job on another host says so rather than pretending.
- *Status:* Built (Phase 3, decision 10). *Source:* WORKFLOWS_PHASE3.md.

**D38. The process ID reaches the database at once whenever there is an API**; in a workflow the workflow runner records each job's process as it starts it.
- *Why:* Kill needs the process ID, and must not wait for a job's records to arrive.
- *Status:* Built (Phase 3, decision 14). Without an API, a job on its own is not killable from the page until its records are delivered (TO-DO decision 2). *Source:* WORKFLOWS_PHASE3.md.

**D39. Loops are a Reaction (Rerun from…) with a required limit**, never made of prerequisites; saving refuses prerequisites that go round in a loop, and its message points to Rerun from.
- *Why:* A waiting for B while B waits for A can never start; a repeat is a different thing ("after B, go back to A"), and an unlimited one never ends.
- *Status:* Built (Phase 3). *Source:* WORKFLOWS.md, "Loops".

## Telemetry and run data

**D40. Workflow decisions never depend on the operations audit trail.** A job's `FileCount` and `Bytes` come with its own end report, counted by the job runner as it goes.
- *Why:* the owner's principle: "Telemetry must be recorded, but it must not harm the job's core purpose or performance." The operations log is an audit trail, asynchronous by design; Job History is core scheduling-engine data. In production runners sit on agent hosts, so nothing downstream may wait on audit records arriving.
- *Status:* Built for FileCount and Bytes (Phase 4). The current shared pipeline is TO-DO decision 10, handed to the roadmap planning session. *Source:* WORKFLOWS_PHASE4.md, decision 1; TO-DO decision 10.

**D41. FileCount and Bytes are the files a job delivered**: each file written to a destination, counted once per destination (three files zipped into one archive count as one).
- *Why:* "delivered" is what downstream jobs care about; a check or a delete delivers nothing; counting by destination avoids counting one archive several times.
- *Status:* Built (Phase 4, decision 7). *Source:* WORKFLOWS_PHASE4.md.

**D42. A job's operations as an object downstream** (`Extract.Operations` in conditions) and **For Each File over an upstream job's files.**
- *Why (original):* the owner's idea: conditions could ask about particular files, and the trace could link the handoff, without copying anything between jobs.
- *Status:* Deferred (2026-10-19), a later workflow enhancement, not dropped. D40 rules out reading the Operations *table*, filled in after the fact; the Operations *object* (the records a job run builds and sends to the telemetry API) is already in hand and could travel downstream with the job's own end report (the owner's correction: an earlier session had wrongly read the principle as ruling out the object too). Deferred because it does not make the workflow model sturdier, no later phase needs it, and return codes cover the common case. Handed to the roadmap (2026-10-19). *Source:* WORKFLOWS.md, "A job's operations as an object downstream"; WORKFLOWS_PHASE4.md, decision 18.

**D43. Downstream sees a job's net result**: resumed attempts add up; restarted from the beginning, only the latest counts; every attempt stays in Job History.
- *Why:* what follows needs the job's actual outcome, not one attempt's.
- *Status:* Designed (Phase 7). *Source:* WORKFLOWS.md, "Restarting".

## Conditions

**D44. One condition language for steps and workflows**: a SQL WHERE clause over `%{Name.Output}` and `${...}`, worked out by SQLite in a database that may only compute.
- *Why:* shortcoming 3 is RunMyJobs' REL: hard to read and write, poorly documented, unvalidated. SQL is documented everywhere and widely known; flow control already checks conditions before a run and logs their values, which Explain grows from. A database that may only compute means a condition cannot read or change anything.
- *Status:* Built (flow control 2026-10-16; workflows Phase 4). *Source:* WORKFLOWS.md, "Conditions".

**D45. Every job in a workflow has the same outputs**: Succeeded, Failed, Ended, NotRun, Skipped, Disabled, Bypassed (true or false), Status, ReturnCode, Reason, FileCount, Bytes, StartTime, EndTime, DurationMs; all unknown until it ends. The shorthands mean exactly what a prerequisite's Outcomes mean.
- *Why:* rules read naturally (`%{A.Succeeded} OR %{C.Failed}`) instead of string comparisons; "unknown until it ends" is what lets a rule decide early (D47). `%{A.Ended}` exists because `%{A.Status} IS NOT NULL` would be false, not unknown, while A runs. The rarer shorthands were added because they cost little (the owner).
- *Status:* Built (Phase 4). *Source:* WORKFLOWS_PHASE4.md.

**D46. Custom rule**: a job's Start rule can be a condition, over the jobs it names and variables; offered whether the job waits for several jobs, one or none.
- *Why:* All and Any cannot say "(A and B) or C", or test a file count or a variable. One job or none: testing a variable (`${Region} = 'EU'`) makes the case, and a file count comes with it (the owner).
- *Considered:* not offering it with fewer than two jobs (Phase 2's choice, D52), since return codes cover the common case.
- *Status:* Built (Phase 4, decisions 3 and 6). *Source:* WORKFLOWS_PHASE4.md.

**D47. A Custom rule holds as soon as it is true**, and the job is Not run as soon as it is false; a job still running counts as unknown, and unknown waits. A rule using IS NULL, coalesce, CASE or the like waits until all its jobs have ended.
- *Why:* that is how the rule reads: "A or B" holds once either is (the owner). SQL's three-valued logic gives it for free (TRUE OR unknown is true; FALSE AND unknown is false). The listed constructs turn unknown into an answer, so with them an early answer could be wrong.
- *Considered:* working the rule out only once all its jobs have ended: simple, but never starts early.
- *Status:* Built (Phase 4, decision 2). *Source:* WORKFLOWS_PHASE4.md.

**D48. The jobs a Custom rule names are the jobs it waits for**, stored as prerequisite rows (test RULE) when it is saved.
- *Why:* no separate list to keep in step with the rule; the diagram draws exactly what the rule depends on. Storing the rows keeps the advantage of explicit prerequisites the owner pointed out: nothing else has to parse text to see a relationship.
- *Status:* Built (Phase 4, decision 6). *Source:* WORKFLOWS_PHASE4.md.

**D49. A failed job named in a Custom rule counts as handled if the job with the rule ran**; for Skip the rest of the branch, a job with a Custom rule is treated like one waiting for its jobs to end.
- *Why:* consistent with D29 for prerequisites; and the rule, not the branch, decides whether that job runs.
- *Status:* Built (Phase 4, decision 8). *Source:* WORKFLOWS_PHASE4.md.

**D50. Renaming a job renames it in the rules that name it**, on the page at once, and on the server for API callers, except a name still used after the save.
- *Why:* a rename must not break rules; the exception stops a page that renamed already, or swapped two names, from being renamed twice.
- *Status:* Built (Phase 4, decision 12). *Source:* WORKFLOWS_PHASE4.md.

**D51. `${...}` in a workflow's conditions are the workflow's** (its own, then its tags' and the scheduler's), fixed when the run starts; one with no value stops the workflow in the pre-run check.
- *Why:* as in flow control, `${...}` is fixed at the start and `%{...}` comes from the run; values fixed at the start are also what Resume needs. A missing value is better found before the run than as a silent false.
- *Status:* Built (Phase 4, decision 13). *Source:* WORKFLOWS_PHASE4.md.

**D52. ~~Start rule greyed out until a job waits for two jobs or more; Custom rule greyed out until built.~~**
- *Status:* Replaced by D46 (Phase 4): All and Any stay greyed out with fewer than two jobs, as they mean the same there; Custom rule is always offered.

**D53. ~~Workflow variables~~**: a workflow's own `${...}`, inherited by what is embedded in it; precedence a use's overrides, the job's own, the workflow's, tags, the scheduler's; ~~one setting swaps tags and workflow variables~~.
- *Why:* the order between tags and workflow variables is debatable, so one switch covers it; a full reorder would make "where did this value come from" hard to answer.
- *Status:* Replaced by D91 and D92 (2026-10-19): the variables and their order stand; the per-workflow switch gave way to the system-wide Variable precedence setting, built since. *Source:* WORKFLOWS.md, "Topic 3's other targets".

**D91. Workflow variables**: a workflow's `${...}` reach every job it runs, fixed once when the run starts; a use can override a variable for that use only; a secret is kept on the run as a reference, never as its value. Through workflows used in workflows with Phase 6.
- *Why:* the owner: "a must". Fixed at the start so every job in the run sees the same values, which Resume (Phase 7) also needs; overrides on a use because a job is used in many workflows.
- *Status:* Agreed, the rest of Phase 4. *Source:* WORKFLOWS_PHASE4.md, decision 19; replaces D53. Through workflows in workflows: D123 (Phase 6, built 2026-10-20; each frame fixes its own as it starts, D134).

**D92. A workflow's tags feed its jobs, and the order is the system-wide Variable precedence setting**: highest first, the use's override, the job's own, the workflow's own, the workflow's tags, the job's tags, then endpoint, application, entity, system values and the scheduler. The setting gains *Workflow* and *This use*.
- *Why:* tags already work this way on every other object (just below the object's own); where the workflow and a job's tags disagree, the workflow sets the context (a workflow tagged `Environment / TEST` runs its jobs as TEST). One order everywhere, rather than a switch on each workflow, keeps "where did this value come from" predictable, the concern behind D53's switch.
- *Considered:* the job's tags above the workflow's (the workflow only filling gaps); D53's per-workflow switch.
- *Status:* Built (the rest of Phase 4). *Source:* WORKFLOWS_PHASE4.md, decisions 20 and 21; the owner, 2026-10-19.

**D93. Variables and Tags sit below the jobs on the workflow page.**
- *Why:* put above the jobs, they pushed the diagram below the fold, and the diagram is the page's point.
- *Status:* Built (WORKFLOWS_PHASE4.md, decision 22); approved by the owner 2026-10-19.

**D94. Where a workflow variable's value came from is shown in the job log and on the workflow page**, not on the job page.
- *Why:* a job on its own belongs to no workflow, so its page has no workflow level to name; the log names the variables each job got from its workflow and its use, never their values.
- *Status:* Built (decision 23); approved by the owner 2026-10-19. Added the same day: the workflow page's steps view shows it for each `${Name}` in a job's steps (D97).

**D97. A job used in a workflow shows its steps read only beside its use, each `${Name}` marked with its value and where it comes from**, in the Diagram's pane and the Outline; and **Open job ↗** opens the job in a new tab.
- *Why:* the owner asked how to see where workflow variables are used without leaving for the job editor. A job is stored on its own and a workflow only points at it, so editing it in another tab cannot disturb the workflow's unsaved changes; the new tab is the way to change the steps, and the pane only reads them.
- *Considered:* editing steps inside the workflow page (a second step editor, against D90's tight scope); opening the job in the same tab (loses unsaved workflow changes).
- *Status:* Built (WORKFLOWS_PHASE4.md, decisions 27 and 28); approved by the owner 2026-10-19.

**D98. A job opened from a workflow is checked as that workflow runs it, with a switch to check it on its own.**
- *Why:* the pre-run check on the job page knew nothing of the workflow, so a job that relies on a workflow's variable warned there although it would run fine in its workflow (the owner saw it on both jobs of the sample). Checking in context tells the truth about the case the user came from; the switch keeps the independent check one click away, since the job can also run alone.
- *Considered:* checking only on its own (what warned); including unsaved workflow edits (the page would have to send the whole workflow; the check uses the workflow as last saved and says so).
- *Status:* Built (WORKFLOWS_PHASE4.md, decision 29); approved by the owner 2026-10-19.

**D95. A workflow's value is filled in as the run starts, in the workflow's own context**; one needing something only a job has is kept as written for the job to fill in.
- *Why:* every job in the run then sees the same value, which Resume (Phase 7) needs; but a workflow cannot know a job's own variables.
- *Status:* Built (decision 24); approved by the owner 2026-10-19.

**D96. The pre-run check judges each use, not each job**, with its workflow's and its use's values.
- *Why:* two uses of one job can set different variables, so one may pass where the other fails.
- *Status:* Built (decision 26); approved by the owner 2026-10-19.

**D54. The condition box: one component wherever a condition is written** (Custom rule, Succeeds when, If, Else If, While): Builder or Text, Names and outputs, checking as you type, Explain.
- *Why:* shortcoming 3 asks for help, validation and a way to see why a condition came out as it did; one box means one thing to learn in the job editor and the workflow editor alike ("One editor experience").
- *Status:* Built (Phase 4). *Source:* WORKFLOWS.md, "One editor experience"; WORKFLOWS_PHASE4.md.

**D55. The builder: nested groups, each "Match all (AND) / any (OR) of the following"**, holding conditions and groups to any depth; a group inside another starts as the other of all and any and is written in brackets; anything it cannot show (IS NULL, IN, BETWEEN, functions) is edited as text.
- *Why:* what is shown must be how it is evaluated. All and Any are the Start rule's own words, so the builder reads like the rest of the page.
- *Considered and replaced:* the first version (a joiner on each row, groups one level deep, one joiner between all groups), which the owner found hard to read: the second group's joiner could not be chosen and groups could not nest.
- *Status:* Built (Phase 4, decision 16, reworked after review). *Source:* WORKFLOWS_PHASE4.md.

**D56. Explain**: on each run, every Custom rule and Succeeds when part by part with the values it used, and what each other job waited for; in the editor, against a chosen past run. Not in the job editor.
- *Why:* "a way to see why it evaluated as it did" is half of shortcoming 3. A job has no past values to explain a step's condition with in the editor; its log already says what each condition used.
- *Status:* Built (Phase 4, decisions 9 and 10); Explain in the job editor is in TO-DO. *Source:* WORKFLOWS_PHASE4.md.

**D57. Times in conditions are local time**, as a step's are.
- *Why:* the same output must read the same in a step and in a workflow.
- *Status:* Built (Phase 4, decision 15). *Source:* WORKFLOWS_PHASE4.md.

## Reactions

**D58. Reactions: what happens after a job ends, chosen by how it ended**: Count as succeeded or failed, Rerun this job, Rerun from…, Skip…, Skip the rest of the branch, Kill the workflow, Start a workflow.
- *Why:* shortcoming 2: reacting to return codes and rerunning upstream. A Prerequisite is a gate before a job starts; a Reaction is an action after it ends, and the only push in the model.
- *Status:* Built (Phase 3). *Source:* WORKFLOWS.md, "Reactions"; WORKFLOWS_PHASE3.md.

**D59. Two sections: What happens next (the first that holds decides) and Also (every one that holds fires)**; every entry is judged on what actually happened.
- *Why:* a job has one fate, but any number of people can hear about it. With every match firing (Control-M's On-Do) a rerun and a cancel would compete; with first match only, a notify would have to be copied into every entry. Judging on a snapshot means no entry's actions change what a later one sees.
- *Considered:* Control-M's On-Do in order.
- *Status:* Built (Phase 3). *Source:* WORKFLOWS.md, "Reactions (topic 4)".

**D60. Count as is an override, shown as both** ("Succeeded (counted; it failed)"), not a seventh status.
- *Why:* the truth of what happened stays visible next to the decision to carry on.
- *Status:* Built (Phase 3). *Source:* WORKFLOWS.md, "Reactions (topic 4)".

**D61. A rerun's limit counts per workflow run; when used up, the next entry that holds decides**; a manual rerun does not reset the count.
- *Why:* "rerun twice, then count as failed" needs the fall-through. Operators often rerun without fixing anything; a reset would allow N more automatic retries against a system still broken; one who has fixed the cause resets the count on purpose.
- *Status:* Built (count and fall-through, Phase 3); manual rerun and reset Designed (Phase 7). *Source:* WORKFLOWS.md, "Reactions (topic 4)" and "Restarts".

**D62. Reactions are job-level, and a use can override them**: Override here copies them into the use, and from then on the use's list is the whole list, with no merging.
- *Why:* "which one fires" must have one answer. Rerun from… and Skip… name other jobs in one workflow, so only a use offers them; what a job *is* goes on the job, how it fits in on its use.
- *Considered:* a use adding its own entries to its job's (the earlier open question).
- *Status:* Built (Phase 3, decision 2). *Source:* WORKFLOWS_PHASE3.md.

**D63. Reactions apply wherever the job runs**: the job runner carries them out for a job on its own, the workflow runner in a workflow. A workflow's own Reactions apply to it as a job; its Rerun this job is a new run.
- *Why:* a job's reaction to its own outcome belongs to the job (D12's principle), and jobs may run on their own (D9).
- *Status:* Built (Phase 3, decisions 5 and 12). *Source:* WORKFLOWS_PHASE3.md.

**D64. A Reaction's When is a simple outcome choice** (succeeded, failed, ended, return codes), with no expression.
- *Why:* workflows need no more; a When written as a condition was moved to TO-DO to keep the phase tight.
- *Status:* Built (Phase 3, decision 3). Replaces the design's "a condition in flow control's language about the job" (WORKFLOWS.md, topic 4). *Source:* WORKFLOWS_PHASE3.md.

**D65. A killed job's Reactions do not apply.**
- *Why:* someone stopped it on purpose; an automatic rerun would undo that.
- *Status:* Built (Phase 3, decision 8). *Source:* WORKFLOWS_PHASE3.md.

**D66. The rest of the branch** is what waits for the job, directly or not, except the jobs that wait for the outcome it actually had (a failure path, a clean-up) and what follows them.
- *Why:* found with the sample: skipping everything downstream also skipped the clean-up, and the failure then counted as unhandled.
- *Status:* Built (Phase 3, decision 7). *Source:* WORKFLOWS_PHASE3.md.

**D67. A Set Return Code step**, not a Run Program step: it sets the job's return code and the job carries on; the last one run wins.
- *Why:* lets a job choose its own code (inside an If) so return-code Reactions and prerequisites can be shown; running programs is a bigger feature (a Script step, in TO-DO).
- *Status:* Built (Phase 3, decision 1). *Source:* WORKFLOWS_PHASE3.md.

**D68. Time-based Reactions replace a separate SLA mechanism**: not started by, not ended by, runs longer than; Mark as late; Notify.
- *Why:* RunMyJobs' SLAs are wholly separate from job statuses and very complex; the owner wants the same reach, made user-friendly, in the one Reactions list.
- *Status:* Designed (Phase 8; confirmed 2026-10-18). *Source:* WORKFLOWS.md, "Reactions (topic 4)".

**D69. Steps' On failure is expected to become Reactions**, one mechanism for both.
- *Why:* **Reason not recorded beyond "one mechanism".**
- *Status:* Designed, no phase. *Source:* WORKFLOWS.md.

## Embedded and shared workflows (Phase 6)

**D116. Working folders stay named by the job's key; renaming a job that has history warns, and can move the folder.**
- A top-level job with run history or a folder on the server's disk gets a plain-words warning on rename: scheduler definitions using the old key must change, past runs keep the old key, files in the old folder are not moved. A tickbox *Move the working folder with it* is offered only when the folder is on the server's own disk and the job is not running; a rename is refused while it runs. Audited. Built first (step 0), as a change outside workflows.
- *Why:* the owner has met this trouble before and never had the chance to build the fix in. Folders by key can be read by an operator and survive a scheduler migration.
- *Considered:* folders named by Job Id (owner's first idea; rejected: opaque to an operator, and the Id differs between databases, so a migration breaks it); renaming the folder automatically (rejected: a job's folder may be on several hosts, a run may be using it, and a move that fails halfway leaves the job pointing at nothing).
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D117. An embedded job's key is made from names and follows renames until the job has first run.**
- The key is the owner's key, a dot, the item's name (`MONTH_END.Transform.Enrich` when nested). It follows renames of the item and of its owners until that job has run, then it is frozen, decided job by job. A scheduler never uses an embedded key. Keys over the 320-character limit are refused on save, naming the item to shorten.
- *Why:* a job needs a unique key (it names the working folder, and runs and logs show it), but nobody should have to invent one for a job that belongs to a workflow. Once it has run, files sit in its folder, so the key stops moving.
- *Considered:* a key fixed at creation and never changed (rejected: the key drifts from the name for no reason before anything has run); folders by Job Id (see D116).
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D118. An embedded item is an ordinary item whose job has an owner; no new table.**
- Removing the item, or its workflow, deletes the embedded job and everything inside it; a shared job is never deleted that way.
- *Why:* every property of a job (steps, variables, Reactions, success return codes) then works on an embedded one without new machinery, which is D3 again.
- *Considered:* a separate embedded-item table (rejected: it would duplicate everything a job has).
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D119. Each frame (embedded workflow) is a child workflow run of its own, with its own instance id.**
- The mechanism shared workflows already use. A job inside a frame that waits for something outside it looks the item up in the enclosing runs of the same top-level run.
- *Why:* a frame has its own status, Reactions, Disable here, Kill, Success return codes and place in Job History, as the design wants (D3, D7).
- *Considered:* flattening the tree into one graph at run time (rejected: simpler lines, but a frame would have no status of its own).
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D120. The workflow and everything embedded in it are edited as one form and saved with one Save, all or nothing.**
- The checks (names, prerequisites, cycles) run over the whole tree.
- *Why:* the diagram shows one thing; saving a frame alone could break its parent (a cycle) and would make the changed-since-last-save markers confusing.
- *Considered:* a Save per frame.
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D121. Names are unique within their own workflow only; conditions reach into embedded items by path, and into a shared workflow by its outputs only.**
- `%{Extract.Status}` for a neighbour, `%{Transform.Stage.Status}` down into a frame. A shared workflow offers `Status`, `ReturnCode`, `FileCount` and `Bytes`, not its inner jobs.
- *Why:* two frames can each hold a `Stage` (D6 stands). Another workflow's inside can change without this one being opened, so a path into it could break a workflow nobody touched.
- *Considered:* names unique across the whole tree (rejected: forces long names for no gain).
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D122. A job inside a frame may wait for any item in the same top-level tree; cycles are refused across the tree, and the wait is on this run, never the latest.**
- The frame as a whole has prerequisites and a Start rule like any item and gates everything inside. A job inside a frame is waited for from outside by its path, not its short name. A test for "this run, not yesterday's" comes first.
- *Why:* "all of these, then those" is the point of embedded workflows (WORKFLOWS.md); and a rerun that quietly waits on yesterday's result would defeat it.
- *Considered:* waits only within a frame (rejected: the design draws a line from outside into the frame).
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D123. A workflow's variables reach everything inside it, embedded or shared; the nearest workflow wins, then a use's override.**
- Fixed when the top-level run starts. A shared workflow gets its parent's values only while it runs there. A secret goes down by reference, never as a value.
- *Why:* completes D91; fixed values are what Resume (Phase 7) needs.
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D124. Disable here, Success return codes and completion rules apply to a frame as to any item, for everything inside it.**
- Disable here (stop) ends the frame Disabled and what is inside Not run; pass through ends it Bypassed.
- *Why:* a frame is a job (D3), so nothing new to learn.
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D125. Reactions inside a frame name items of that frame only; "Kill the workflow" kills the frame and nothing above it.**
- The frame ends Failed, `KILLED`, which its parent treats like any failed item. A Reaction on the frame's own item works as on any job. An operator can still Kill the top-level run by hand.
- *Why:* the owner, 2026-10-19: just the frame. A Reaction that reached across frames could not be drawn or explained simply.
- *Considered:* a separate "kill the top-level workflow" Reaction (not wanted).
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D126. Embedded items stay out of the Jobs & Workflows page, the search pages and the pickers (not out of the workflow editor, where they are shown in their workflow); their changes are in the parent's Audit Log; tags go on top-level jobs and workflows only.**
- A workflow's tags feed everything inside it (D92). Job History gains the frame level.
- *Why:* no clutter, which was shortcoming 6; tagging each embedded item as well would make inheritance confusing.
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D127. An embedded job or workflow can be made shared, and a shared one used as an embedded copy.**
- *Make shared* gives it a key the owner chooses (refused if taken), clears its owner and lists it; the item now uses it, folder unchanged. *Use an embedded copy* duplicates a shared job or workflow, everything inside included; later changes to the original do not reach the copy. Neither merges back. Both audited.
- *Why:* a second workflow will want a job that began as embedded, and a use sometimes needs to differ. The owner, 2026-10-19: a small addition, so in this phase.
- *Considered:* leaving it to TO-DO (the owner chose to include it).
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D128. No limit on nesting depth, and no warning for it.**
- Depth is tested instead: a deep, wide sample is measured for speed (every frame is a runner process that polls).
- *Why:* the owner, 2026-10-19: production chains in RunMyJobs go well past five levels, so a warning would only be ignored; depth follows the work.
- *Considered:* a warning past five levels (rejected).
- *Status:* Built (Phase 6, 2026-10-20; agreed 2026-10-19). *Source:* WORKFLOWS_PHASE6.md.

**D129. An embedded job made of steps is edited on its own page, which saves just that job; embedded workflows are edited from the workflow they are in.**
- The workflow page holds the whole tree of embedded workflows as one form (D120), and shows an embedded job's steps read only beside its item. A job of steps already saved is left out of the Save, so it stays as it is; a new one is made without steps, and its page opens once the workflow is saved. The job's own page cannot rename it (its key follows the names, D117) or delete it, and says which workflow it belongs to.
- *Why:* the step editor is a page of its own, large, and nothing else on the workflow page needs it. One Save still covers every workflow, item, prerequisite and variable of the tree, which is what D120 protects: a check across frames never meets half a change.
- *Considered:* steps edited inside the workflow page (a second copy of the whole job editor in a pane; not now).
- *Status:* Built (Phase 6, 2026-10-20), a departure from D120 for the steps of embedded jobs only.

**D130. A wait on a job elsewhere in the same tree is answered in this run, and ends as "can't hold" once the job has ended otherwise.**
- Such a prerequisite is an ordinary "job in another workflow" one that names a workflow of the same tree (`MONTH_END`, `MONTH_END.Extract`). When the run starts it looks for the job in the runs of that tree only, never an earlier or a later run of the same workflow (D122). If the job ended and the wait cannot hold, the job that waits ends Not run (or Failed, as its *If it can't start* says) at once, instead of waiting out its patience, which is only for what can still change (files, a clock, another workflow's run).
- *Gap:* a job waiting for a job in a frame that never starts (the frame was Disabled here, or never reached) waits out its patience, the system default, then ends as timed out.
- *Status:* Built (Phase 6, 2026-10-20).

**D131. Make shared may keep the key it has.**
- The key given is the owner's choice (D127); keeping the present one (`MONTH_END.Extract`) leaves the job and its working folder exactly where they are. A different key takes the rename warning and the optional folder move of D116, and is refused while the job runs.
- *Why:* D127 said "folder unchanged", which is only true when the key is; this makes the way to do that plain.
- *Status:* Built (Phase 6, 2026-10-20).

**D132. A workflow of its own opens inline on the diagram, read only; Find looks inside everything.**
- Used as a job it is one box, with an arrow that opens it into a dashed frame, read only, with a lock on each of its jobs; a click on one opens that workflow's own page. Find looks through this workflow, its frames and every workflow of their own it uses, to any depth, and says where each match is (`Reporting / Summary_EU`); a folded frame or box says "2 matches inside", and a result opens the way to its match.
- *Why:* D121: another workflow's inside can change without this one being opened, so it is read, not edited, here.
- *Status:* Built (Phase 6, 2026-10-20).

**D133. Loops are looked for through frames too.**
- A frame ends after everything inside it, and nothing inside starts before the frame does, so a job inside a frame cannot wait for something that waits for the frame to end. The check runs over the whole tree on every Save and names the path.
- *Status:* Built (Phase 6, 2026-10-20).

**D134. Each frame fixes its variables as its own run starts.**
- D123 said all values are fixed when the top-level run starts. Each frame is a run of its own (D119) and fixes its workflow's variables when it starts, then passes the nearest value down: the result is the same unless a definition is edited while the run is going, which a run already half done would show.
- *Status:* Built (Phase 6, 2026-10-20), a small departure from the wording of D123.

**D135. A frame Disabled here leaves no run records for what is inside it.**
- D124 said what is inside ends Not run. A frame that does not start has no run of its own, so nothing inside has a record; its own item ends Disabled (stop) or Bypassed (pass through), which is what a reader of the run sees.
- *Status:* Built (Phase 6, 2026-10-20), a departure from the wording of D124.

## Moved out of the workflow track

**D70. Hold for an operator.** *Why moved:* it came up while settling Cancel and Kill; workflows don't need it (the owner: "outside the scope of Workflow work"). A first version needs only Release. *Status:* Moved out, to TO-DO (Phase 3, decision 4).

**D71. A Reaction's When as an expression.** *Why moved:* not needed for workflows (D64). *Status:* Moved out, to TO-DO.

**D72. A Script step** (Bash, Python, PowerShell…). *Why moved:* a good idea that makes the step library user-extensible, but not a workflow need. *Status:* Moved out, to TO-DO.

**D73. Set Return Values** (Set Return Code also setting named values read downstream). *Why moved:* nothing in the workflow phases depends on it. *Status:* Moved out, handed to the roadmap planning session (2026-10-18).

## Restarts

**D74. A rerun is a new attempt within the same workflow run**, not a new run.
- *Why:* the history stays together, and the net-result rule (D43) applies.
- *Status:* Built for Reactions' reruns (Phase 3); the Rerun ▸ menu Designed (Phase 7). *Source:* WORKFLOWS.md, "Restarts".

**D75. Rerun ▸: Resume first, then Restart from beginning, then Advanced…**, on jobs and workflows alike.
- *Why:* Resume (the owner's idea from the original prototype's control file) is what an operator usually wants, so it is the first choice, not a hidden default. Advanced holds the rest: from a chosen job, mark done, ignore a prerequisite (Control-M's "add the condition by hand", done openly), with different values, reset retry counts; each choice in the Audit Log.
- *Status:* Designed (Phase 7). *Source:* WORKFLOWS.md, "Restarting" and "Restarts".

**D76. Every failed step reports whether what it did is known**: not done, partly done and known, or unknown; Resume holds for an operator at an unknown step, and automatic reruns do not retry it.
- *Why:* resuming blindly could repeat a payment or a partly committed SQL change; the handler knows from the error it caught.
- *Status:* Designed (Phase 7). *Source:* WORKFLOWS.md, "Restarts".

## The diagram and the editor

**D77. Layout left to right by default, top to bottom as a choice; laid out automatically; each column in outline order.**
- *Why:* columns are the graph's levels and parallel jobs stack; top to bottom suits portrait screens. Keeping outline order means folding or editing does not reshuffle the picture, at some cost in compactness (decided after the mockup).
- *Status:* Built (Phase 2). *Source:* WORKFLOWS.md, "The diagram and the editor".

**D78. Full names, always**: a box wraps its name; never truncated.
- *Why:* shortcoming 5: RunMyJobs truncates call names well before their 80-character limit.
- *Status:* Built (Phase 2). *Source:* WORKFLOWS.md.

**D79. Lines are coloured and styled by their test, not labelled** (Succeeded green solid, Failed red dashed, Ended solid, return codes labelled); Any marked where lines enter; a Custom rule's lines dotted and muted, with `{x}` on the box.
- *Why:* each colour has its own line style for colour-blind users (red against green is the commonest form); labels on every line would crowd the picture; pointing at a line says what it means.
- *Status:* Built (Phases 2 and 4). *Source:* WORKFLOWS.md; WORKFLOWS_PHASE4.md, decision 14.

**D80. Every kind of dependency is visible**: outside ones as dashed boxes at the edges, both ways (what this waits for; what waits for this, "Needed by"); ones without a source as icons (clock, calendar, `{x}`).
- *Why:* shortcoming 4: a Wait Event in one RunMyJobs chain depending on a Raise Event in another is invisible.
- *Status:* Built (`{x}` in Phase 4; the rest in Phase 5, 2026-10-19). A workflow waited for as a whole is not drawn on the diagram of the workflow waited for: its page lists no "Needed by" for it (a TO-DO item). How they look, and hiding them, is D115. *Source:* WORKFLOWS.md.

**D81. Layout engine: elkjs**, vendored; AutoApp draws the SVG.
- *Why:* free (Eclipse Public License 2.0, no obligation unless its code is changed and distributed); handles nested frames, which embedded workflows need. The owner cares about the UX, provided nothing needs a paid licence.
- *Considered:* dagre (MIT), which handles nested frames poorly.
- *Status:* Built (Phase 2). *Source:* WORKFLOWS.md.

**D82. Diagram | Outline, the same switch in the job editor and the workflow editor**; the page opens in the view last used, in that browser.
- *Why:* the outline serves very large workflows and screen readers; remembering the view respects each person's habit. **Reason for remembering per browser rather than per account not recorded** (there are no accounts yet).
- *Status:* Built in the workflow editor (Phase 2); the job editor's diagram is open. *Source:* WORKFLOWS.md; WORKFLOWS_PHASE2.md, decision 4.

**D83. Editing on the diagram**: drag from box to box for a prerequisite (it starts as Succeeded); a × on a line removes it; Delete removes a selected line; edits saved with Save, as in the outline, kept across the switch.
- *Why:* one save for both views, so nothing is half saved; the × sits a fixed distance before the arrowhead so it is found the same way on every line. Dragging to a job with a Custom rule adds the job to its rule; a rule's own lines have no ×, as the rule is changed in its box.
- *Status:* Built (Phases 2 and 4). *Source:* WORKFLOWS_PHASE2.md, decisions 1, 5, 6, 12; WORKFLOWS_PHASE4.md, decision 14.

**D84. The job pane**: wider (560 px, resizable by its edge, remembered), shown only while a job is selected (Hide Job pane ×, or a click on the empty canvas); jobs changed since the last save outlined with a pencil marker, compared by identity so a rename marks only that job.
- *Why:* the owner's review: rule rows must fit; a pane that is always open takes room from the diagram; once the pane can be closed, unsaved changes must be visible on the diagram itself. "Close" alone could be misread.
- *Status:* Built (Phase 4, decision 17). *Source:* WORKFLOWS_PHASE4.md.

**D85. The key is folded away by default.**
- *Why:* once learnt it only takes room, and pointing at things explains them.
- *Status:* Built (Phase 2). *Source:* WORKFLOWS.md.

**D86. Jobs & Workflows is one page; Submit is Save everywhere; Administration has its own section on the Main Index; pages are never cached stale.**
- *Why:* a workflow is a job (D3), so one list; "Submit" reads as "submit to run" to anyone who uses a scheduler; Settings is not a record of what happened; changes must show without a hard refresh. **Reason for the Administration section beyond grouping not recorded.**
- *Status:* Built (Phase 2, owner's review, decisions 8 to 10 and 13). *Source:* WORKFLOWS_PHASE2.md.

**D87. A job's prerequisites sit in their own Prerequisites box**, each "Job in this workflow" and "Outcome", the Start rule under them, Remove this job below.
- *Why:* the owner's review: what a job waits for, and how those combine, read as one thing.
- *Status:* Built (Phase 2, decision 11; the Start rule's options changed by D46). *Source:* WORKFLOWS_PHASE2.md.

**D88. The mockup page is kept** (`ui/mockup_workflow.html`) as the picture of the full design; revisit if the real page drifts from it.
- *Why:* later phases (frames, outside dependencies) are drawn there before they are built.
- *Status:* Kept (Phase 2, decision 3). *Source:* WORKFLOWS_PHASE2.md.

## Restarts, planned in Phase 7

**D136. Resume reads a control file of its own, never the operations spool or the database.** The runner keeps it on its host as the job goes, written before and after each step and after each file; a killed job's steps write what they knew as it stops.
- *Why:* the telemetry principle (D40): nothing the workflow acts on may depend on operations records, which are an audit trail sent in the background; the runner never writes the database. The spool holds operations only, and its life belongs to the telemetry redesign.
- *Considered:* reading the spool back (the original design); sending the record with the job's end report (a killed runner sends none); a database table written by the runner.
- *Status:* Designed (Phase 7). *Source:* WORKFLOWS_PHASE7.md, proposal 1; the owner, 2026-10-20.

**D137. Each step type says what a failed step knew: not done, partly done and known, or effect unknown; one that does not say counts as unknown.**
- *Why:* D76. The safe default makes a new step type's author decide.
- *Status:* Designed (Phase 7). *Source:* WORKFLOWS_PHASE7.md, proposal 3.

**D138. "Failed (effect unknown)" does not hold the run; the Resume dialog asks the operator.** They choose per step: run it again, count it as done, or restart the job.
- *Why:* the owner, 2026-10-20: the dialog is unmissable, since it comes when Resume is chosen; a waiting state would be Hold for an operator, which is a later feature. The label is the owner's wording; "unknown failure" did not say what was unknown.
- *Status:* Designed (Phase 7). *Source:* WORKFLOWS_PHASE7.md, proposal 3.

**D139. A Reaction's Rerun this job has two options, Restart from the beginning and Resume from failure; new ones default to Resume, existing ones stay Restart.** An automatic Resume does not fire after "Failed (effect unknown)"; an automatic Restart still does.
- *Why:* the owner: a job of steps is AutoApp's standard job. The default after an unknown effect is the careful one. A restart is chosen knowing the work is done again, so it is left as built.
- *Considered:* both stop (the original design; changes the existing Rerun); neither stops.
- *Status:* Designed (Phase 7). *Source:* WORKFLOWS_PHASE7.md, proposals 3 and 13.

**D140. A run that has ended is reopened, on the same record, by a new runner process;** refused when the workflow was edited and an item of the run no longer exists. A Succeeded run is reopened by Advanced only.
- *Why:* D74. The simple rule for an edited workflow: the owner is adding a roadmap item for doing it properly.
- *Status:* Designed (Phase 7). *Source:* WORKFLOWS_PHASE7.md, proposal 5.

**D141. Phase 7 is built in two parts: Rerun ▸ with Resume and Restart first, Advanced… second; Hold at… is left out.**
- *Why:* part 1 shows the whole idea (as Phase 4 was split); Hold needs Hold for an operator (D90).
- *Status:* Designed (Phase 7). *Source:* WORKFLOWS_PHASE7.md.

**D142. Every restart choice is recorded on the run and in the Audit Log** ("web interface" until accounts), with the changed `${...}` names and never values.
- *Why:* D75; secrets never reach records.
- *Status:* Designed (Phase 7). *Source:* WORKFLOWS_PHASE7.md, proposal 11.

**D143. Reopening picks up the run's own record; only a frame that goes on is reopened too.** A failed frame is reopened as its own run (same run ID, its first start kept) and goes on inside; a failed job gets a new attempt that resumes from its control file. A *Restart* of the whole run reopens the top run only: every item starts again as a new attempt, a frame as a new run.
- *Why:* proposals 5 to 8. A restart means the earlier attempt's work is done again, so there is nothing to reopen below the top.
- *Status:* Built (Phase 7, step 3). *Source:* WORKFLOWS_PHASE7.md, "Built so far".

**D144. A failed job or frame inside a workflow is rerun by reopening the run at the top, changing only the frames on the way and the item chosen.** What else already ended stays as it is, including what was Not run because of the failure. The item must have Failed; a run that Succeeded is refused (D140).
- *Why:* the top run is the runner of the whole tree, and it is what a waiting job looks at. Leaving the rest alone is proposal 8; *Advanced → from a chosen job* is the way to include it.
- *Status:* Built (Phase 7, step 3). *Source:* WORKFLOWS_PHASE7.md, proposal 8.

**D145. A run's `${...}` values used in its conditions are kept on the run with its other fixed variables** (`WorkflowVariables`, key `conditions`), so a reopened run uses the first attempt's. A run from before this reads them again.
- *Why:* proposal 4; Resume was the reason for fixing values (D57, D91).
- *Status:* Built (Phase 7, step 3). *Source:* WORKFLOWS_PHASE7.md.

**D146. Resume of a workflow is refused as a whole when a failed job's record of how far it got cannot be used** (removed, or on another host), naming the jobs; Restart is offered. A failed item that never had a run of its own starts from the beginning.
- *Why:* starting such a job over silently could repeat work already done; the standalone job is treated the same way (D136).
- *Considered:* restarting only those jobs and resuming the rest.
- *Status:* Built (Phase 7, step 3). *Source:* WORKFLOWS_PHASE7.md.

## How the work is done

**D89. Phases, each a working, demonstrable AutoApp**, in the order of the shortcomings' priority, except the diagram second and restarts and time-based Reactions last; each planned in detail with the owner just before it is built.
- *Why:* every later phase has something to show on the diagram; restarts and time-based Reactions are the deepest engine work and the least needed to show the design. Planning just in time uses what the earlier phases taught.
- *Status:* In force; the owner may reorder Phases 5 to 8. *Source:* WORKFLOWS.md, "Implementation in phases".

**D90. Each phase includes only what workflows need**; side ideas go to TO-DO, long-term features to the roadmap planning session.
- *Why:* the owner, 2026-10-18: operational features (Hold, expression Whens) "feel like outside the scope of Workflow work". Keeping phases tight keeps them reviewable.
- *Status:* In force. *Source:* WORKFLOWS_PHASE3.md; the owner.

**D147. A Reaction's Rerun this job is stored as RESTART or RESUME on its action (`ReactionActions.RerunMode`); existing ones are RESTART, a new one saved without a choice is RESUME.** The API reads an empty value as RESTART, so a database not yet migrated behaves as before.
- *Why:* the owner's choice (proposal 13): nothing that ran before runs differently; a job of steps is the standard job, so a new Reaction resumes.
- *Considered:* a separate action name (RERUN_RESUME); rejected because the limit, the wait and the "at most N times" count are the same thing, and the Reaction record would split one rule in two.
- *Status:* Built (Phase 7, step 3a). *Source:* WORKFLOWS_PHASE7.md, proposal 13.

**D148. A Resume by Reaction that cannot be carried out is passed over, like a rerun at its limit, and the next entry that holds decides.** It is recorded as NOT_FIRED, with the reason, in the Reaction record, the job log and the run page. It is passed over when: a step failed and could not say what it changed (or cannot finish by itself); every step had finished and the job failed on its return code (nothing to pick up); or the record of how far the run got is gone or on another host. A workflow is always run again from the beginning, whatever the choice says.
- *Why:* "stays failed" for an unknown failure must not be undone by an automatic retry, yet "rerun twice, then count as failed" should still work; treating it as used up gives both. Restart stays a choice for anyone who accepts the work being done again.
- *Considered:* stopping all Reactions for that job (the job could not then be counted as succeeded by a later entry); firing a Restart instead (silently repeats work).
- *Status:* Built (Phase 7, step 3a). *Source:* WORKFLOWS_PHASE7.md, proposal 13 and settled item 3.

**D149. A workflow's Resume offers Use as they were / Refresh / Edit for its `${...}` values, one list for each level that can be edited.** The lists are the workflow's variables (the run at the top and each frame that is reopened), each use's variables, and what each resumed job read from its own levels (job, application, system and so on). Restart has no values choice: everything is read again.
- *Why:* the owner's choice (step 4b). A value from the workflow or its use is shown once, where it is set, so one edit reaches every job that runs again; precedence still decides which level wins.
- *Considered:* one flat list per job (the same value repeated and edited in many places); a separate dialog for conditions (conditions already decided stay as decided, and those not yet decided use the new values, which the dialog says).
- *Status:* Built (Phase 7, step 4b). *Source:* WORKFLOWS_PHASE7.md, step 4b.

**D150. Refresh and Edit reach only the jobs that run now; the dialog names the jobs that already Succeeded and keep the values they ran with.** When a workflow or use value is refreshed and changed, or edited, every succeeded job is named. A Restart applies every value to every job.
- *Why:* a succeeded job is not run again, and its control file is removed on success (step 5), so the run cannot say which succeeded job used a changed value. Naming them all is honest and cannot miss one.
- *Status:* Built (Phase 7, step 4b). *Source:* WORKFLOWS_PHASE7.md, step 4b.

**D151. Edited values are checked before the run reopens, and each edit is recorded as `JOB_RESUMED_WITH_EDITS` in the Audit Log, one row for each edited job and one for each workflow or frame whose own or use variables were edited.** A secret cannot be edited and never appears in a row. Refresh or Edit with a Restart is refused (422).
- *Why:* D142; an edit that changes what a job does is something the operator may have to explain later, by name, without exposing a secret.
- *Status:* Built (Phase 7, step 4b). *Source:* WORKFLOWS_PHASE7.md, step 4b.

**D152. A job's control file is removed when its run Succeeded and no Reaction changed that outcome, and the file of the attempt it picked up goes with it.** A failed, killed or Reaction-overridden run keeps its file; a Restart leaves earlier attempts' files where they are until their logs are removed. Removal never fails a run.
- *Why:* a control file is only for picking up a run that did not finish; once the run Succeeded there is nothing to pick up, and the job logs keep the history. The new file holds copies of the earlier attempt's records, so the earlier one is no longer needed.
- *Known edge, accepted:* a job inside a workflow that Succeeded and which a *workflow* Reaction then counts as failed has already lost its file (the job runner cannot know). Resume of it says in plain words that there is no record to pick up from and offers Restart from the beginning. *Considered:* leaving removal to the workflow runner after the item's Reactions are settled; rejected because it needs a second place that removes files.
- *Status:* Built (Phase 7, step 5-1). *Source:* WORKFLOWS_PHASE7.md, step 5.

**D153. Each Resume or Restart an operator asks for is recorded in a new table, `RunRestarts`, written by the API when the request is made, and in the Audit Log as `JOB_RESUMED` or `JOB_RESTARTED`.** One row of each for each request, under the job key of the run reopened, "by web interface". The row holds the earlier attempt it went on from, the items touched with what each got, the choices made on steps of unknown effect, whether values were refreshed, and the edits by name with old and new value (never a secret). The `JOB_RESUMED_WITH_EDITS` rows stay as they were. A refused request writes nothing.
- *Why:* the runner never writes the database (D40), and nothing a workflow acts on may depend on telemetry; the API already knows the request and the plan when it starts the runner. `RunID` is text, not a link, so the record survives like the job log does.
- *Considered:* the runner writing the record (breaks D40); only the Audit Log (it is for definitions, hard to list by run); recording in the spool (telemetry may arrive late or never).
- *Status:* Built (Phase 7, step 5-2). *Source:* WORKFLOWS_PHASE7.md, step 5.

**D154. A Reaction's rerun is not copied into `RunRestarts`; the run's Restarts list merges the Reaction events in when it is read, labelled "a Reaction".** For a job on its own the list is that of the whole chain of attempts, so the latest attempt's page shows all of them; a job inside a workflow has no list of its own, its workflow's run carries it.
- *Why:* a Reaction rerun is already on record as a Reaction event with the attempt it judged; a second copy could disagree with it. The owner sees every time a run was run again, not only the manual ones.
- *Considered:* operator choices only (a run that was retried twice by a Reaction would look as if it had run once more).
- *Status:* Built (Phase 7, step 5-2), on the planning session's proposed default. *Source:* WORKFLOWS_PHASE7.md, step 5.

**D155. Job History says "Restarted ×N" where it said "attempt N", with the how in the hover ("Resumed by you, then restarted by a Reaction").** N is the attempts before this one for a job, and the restarts listed for a reopened workflow run. The run pages say "Restarted N times" and carry the Restarts box.
- *Why:* the owner asked for this wording (step 4a note); "attempt N" says nothing about how the run came to be run again.
- *Status:* Built (Phase 7, step 5-3), on the planning session's proposed default. *Source:* WORKFLOWS_PHASE7.md, step 5.

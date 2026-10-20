# Workflow decisions

Every decision behind how AutoApp's workflows work, in one place, each with **why**: the problem it solves or the trap it avoids. Before changing one, read its why: it may name the trouble the change would bring back.

- **Status:** *Built* (and when), *Designed* (agreed, not built yet; the phase that builds it), *Replaced* (kept, pointing to what replaced it, so the history stays), *Moved out* (taken out of the workflow track, and where it went).
- **Source:** where the decision was first written down, with the detail: [WORKFLOWS.md](WORKFLOWS.md) (the design record) and the phase plans ([1](WORKFLOWS_PHASE1.md), [2](WORKFLOWS_PHASE2.md), [3](WORKFLOWS_PHASE3.md), [4](WORKFLOWS_PHASE4.md)).
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
- *Why:* an embedded workflow is what RunMyJobs' structural sub-chains should have been: it belongs to its parent and stays out of lists (shortcoming 6). Shared jobs let one definition run several times with different values. Everything on the diagram is a job or a workflow, so there is nothing new to learn.
- *Considered:* ActiveBatch's Reference objects.
- *Status:* Designed (Phase 6); Phase 1 to 4 workflows use shared jobs only. *Source:* WORKFLOWS.md, "What a workflow holds".

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
- *Status:* Designed (Phase 5, with outside dependencies; the owner confirmed 2026-10-18 it stays there). Hold depends on D58. *Source:* WORKFLOWS.md, "Prerequisites that aren't satisfied".

**D17. A prerequisite's target can be outside the workflow** (a job in another workflow, an endpoint, a time window), defined on the prerequisite; conditions may name only the workflow's own jobs and the targets of the job's own prerequisites.
- *Why:* every outside reference is then a prerequisite, and every prerequisite can be drawn: nothing a job waits for is hidden (shortcoming 4, RunMyJobs' invisible Wait Events).
- *Status:* Designed (Phase 5). *Source:* WORKFLOWS.md, "Where prerequisites live, and outside targets".

**D18. Another workflow's job counts by its current or latest run**: the run executing now, else the most recent completed; optional limits against a stale success.
- *Why:* "today's run" breaks workflows that cross midnight; yesterday's success must not satisfy a wait while today's run is going. This is ActiveBatch's "Exact active", under a name that says what it means.
- *Status:* Designed (Phase 5). *Source:* WORKFLOWS.md, "Which run of another workflow counts".

**D19. An endpoint as a target**, with a minimum age (every file unchanged for N seconds), sharing code with Check Files' minimum age.
- *Why:* a job must not start on a file still arriving; one check of modified times is simpler than the "Stable" first proposed, and is the same concept as in Check Files.
- *Considered:* a `Stable` test.
- *Status:* Designed (Phase 5). *Source:* WORKFLOWS.md, "Topic 3's other targets".

**D20. Time windows as a built-in value**, `%{Now.Time}`, `%{Now.Date}`, `%{Now.Weekday}`; as a prerequisite, it waits until the window opens.
- *Why:* "not before 02:00" is a condition like any other, in the same language, rather than a separate kind of object.
- *Status:* Designed (Phase 5; confirmed 2026-10-18). *Source:* WORKFLOWS.md, "Topic 3's other targets".

**D21. Starting a workflow: by hand, from its page** (or by a scheduler, by key, like any job).
- *Why:* how workflows are initiated is not what AutoApp demonstrates; scheduling may come later.
- *Status:* Built (Phase 1). *Source:* WORKFLOWS.md, "Starting a workflow".

**D99. When an outside prerequisite's "up to N minutes" starts is a choice on the prerequisite:** (1) after the job's other prerequisites have held (the default); (2) after the first of them holds; (3) after a chosen prerequisite holds; (4) from the start of the workflow run. "Until a time" is a clock time and needs none.
- *Why:* counting from the workflow's start alone would time out a job sitting behind a long upstream job; the right start differs by case, and the four are the natural anchors (all, first, a chosen one, the run). The owner, 2026-10-19, made the third "a chosen prerequisite" rather than the fourth option proposed ("after a chosen job ends"), as it fits the others and reads better.
- *Status:* Designed (Phase 5). *Source:* WORKFLOWS_PHASE5.md, proposal 2; refines D16.

**D100. An outside prerequisite waits at most 24 hours by default**, a system setting ("Default wait for outside prerequisites"), shown on each prerequisite as "Default (24 h)"; "No limit" is a deliberate choice, and saving a prerequisite with none warns.
- *Why:* AutoApp has no daily cycle to end a stale wait (Control-M's New Day Process does), so an unlimited wait could hang forever; a limit that is visible and editable is not hidden magic.
- *Considered:* no limit by default (the owner was not sure an indefinite wait is better than an arbitrary default).
- *Status:* Designed (Phase 5). *Source:* WORKFLOWS_PHASE5.md, proposal 3; the owner, 2026-10-19.

**D101. An optional prerequisite is waited for up to its limit, then dropped from the job's check; the job's other prerequisites still decide.** It needs a limit (without one it would be the same as required). If nothing else is left, the job starts. In a Custom rule, its outputs are unknown (`NULL`).
- *Why:* the owner's reading: "wait N minutes, then run without it if the others are satisfied". Counting it as *held* instead (the first proposal) would start a job with the Start rule Any at once when the optional wait timed out, even if none of its other prerequisites held.
- *Considered:* counting a timed-out optional prerequisite as held.
- *Status:* Designed (Phase 5). *Source:* WORKFLOWS_PHASE5.md, proposal 4; the owner, 2026-10-19.

**D102. A prerequisite's target can also be a whole workflow** (its final status), not only a job in it.
- *Why:* "wait for the nightly load" is the common wish, and sub-workflows (structural ones) could not work otherwise. Cheap, because a workflow is a kind of job (D3) and its run is a job run.
- *Status:* Designed (Phase 5). *Source:* WORKFLOWS_PHASE5.md, proposal 9; the owner, 2026-10-19.

**D103. A time window that spans midnight is written `%{Now.Time} IN WINDOW '18:00' TO '06:00'`**: after the start, or before the end when the end is earlier. It is AutoApp's own syntax, translated to plain comparisons before the condition is worked out; the builder shows it in words.
- *Why:* `BETWEEN` cannot wrap past midnight and the `OR` form is easy to get wrong (a `23:59` end leaves a gap). A mainframe scheduler's times past 24 hours (`99:00` for 4d3h) made users do the arithmetic.
- *Considered:* the `OR` form alone (still works); times beyond 24:00.
- *Status:* Designed (Phase 5). *Source:* WORKFLOWS_PHASE5.md, proposal 6; the owner, 2026-10-19.

**D104. Prerequisites may not form a cycle, within a workflow or between workflows**; the message points to Rerun from… (D39). A cross-workflow loop (a Rerun-workflow Reaction with a limit) is a TO-DO item.
- *Why:* neither job of a prerequisite cycle can ever make its first start, so no exit could fire (D39).
- *Status:* Designed (Phase 5). *Source:* WORKFLOWS_PHASE5.md, proposal 7; the owner, 2026-10-19.

**D105. An endpoint prerequisite checks the files where the endpoint says; no queue or agent field yet.** If agents or queues come, the endpoint reference gains a "checked on" field, as ActiveBatch's file constraint names a queue.
- *Why:* AutoApp has neither queues nor agents; the owner thought ActiveBatch's way worked well, so the place for it is kept free.
- *Status:* Designed (Phase 5, local endpoints only). *Source:* WORKFLOWS_PHASE5.md, proposal 10; the owner, 2026-10-19.

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
- *Status:* Agreed, the rest of Phase 4. *Source:* WORKFLOWS_PHASE4.md, decision 19; replaces D53.

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
- *Status:* `{x}` Built (Phase 4); the rest Designed (Phase 5). *Source:* WORKFLOWS.md.

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

## How the work is done

**D89. Phases, each a working, demonstrable AutoApp**, in the order of the shortcomings' priority, except the diagram second and restarts and time-based Reactions last; each planned in detail with the owner just before it is built.
- *Why:* every later phase has something to show on the diagram; restarts and time-based Reactions are the deepest engine work and the least needed to show the design. Planning just in time uses what the earlier phases taught.
- *Status:* In force; the owner may reorder Phases 5 to 8. *Source:* WORKFLOWS.md, "Implementation in phases".

**D90. Each phase includes only what workflows need**; side ideas go to TO-DO, long-term features to the roadmap planning session.
- *Why:* the owner, 2026-10-18: operational features (Hold, expression Whens) "feel like outside the scope of Workflow work". Keeping phases tight keeps them reviewable.
- *Status:* In force. *Source:* WORKFLOWS_PHASE3.md; the owner.

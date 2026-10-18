# Workflows, Phase 4: conditions

The fourth phase of [WORKFLOWS.md](WORKFLOWS.md) ("Implementation in phases"): **conditions people can read and write.** It answers shortcoming 3 ([PROJECT_GOALS.md](PROJECT_GOALS.md) goal 2): RunMyJobs' precondition expressions are hard to read, harder to write, poorly documented, have no helpers in the UI, and cannot be validated or debugged. Workflow conditions come with help, validation and a way to see why they evaluated as they did.

Status: **draft, 2026-10-18; agreed with the owner 2026-10-18; being built.**

## Starting point

Already built:

- Flow control's condition language ([FLOW_CONTROL.md](FLOW_CONTROL.md)): a SQL `WHERE` clause over `%{Name.Output}` and `${...}`, checked before a run, worked out by SQLite in a database that may only compute, and logged with the values it used. If, ElseIf and While use it inside a job.
- Prerequisites between jobs in a workflow: Succeeded, Failed, Ended or return codes; the Start rule *All* or *Any*. *Custom rule* is on screen, greyed out (Phase 2). The model already has a `Condition` column on each prerequisite, unused.
- Names of jobs in a workflow are unique within it and already in the form a path needs (`Alert_finance`).
- The Set Return Code step (Phase 3), so a job can choose its own return code; Reactions, with the ones that fired listed with the run.

## What Phase 4 includes, and what it leaves out

- **In (proposed):**
  - **Outputs of a job in a workflow**, read downstream as `%{Extract.Status}`: `Status`, `ReturnCode`, `Reason`, `FileCount`, `Bytes` (totals of its steps' own, reported by the job with its end, not counted from the operations audit trail), `StartTime`, `EndTime`, `DurationMs`; worked out when each job ends. Also `Succeeded`, `Failed` and `Ended`, meaning exactly what a prerequisite's Outcomes mean (Bypassed counts as succeeded; Ended includes Not run), so a rule reads `(%{A.Succeeded} AND %{B.Succeeded}) OR %{C.Failed}`; likewise `NotRun`, `Skipped`, `Disabled` and `Bypassed` for the rarer statuses (the owner, 2026-10-18). Until a job ends, all its outputs are unknown (SQL's `NULL`); so are `FileCount` and `Bytes` of a job killed or crashed before reporting its end. A workflow's own `FileCount` and `Bytes` are the sums of its jobs'.
  - **Custom rule** on a job's Start rule: a condition over the jobs it names, or only over variables, so it is offered whether the job waits for several jobs, one or none.
  - **A workflow's completion rules**, held back from Phase 3: *Succeeds when* the default or a condition; *Return code* the default or a chosen job's.
  - **The condition box**, one component wherever a condition is written (Custom rule, Succeeds when, and flow control's If, ElseIf and While):
    - **help:** the names and outputs that can be used, to pick from, each with a line saying what it is;
    - **validation as you type:** an unknown name or output, a job not waited for, a text compared with a number, a condition that is not valid SQL, each pointed out where it is;
    - **the builder:** rows of name → output → comparison → value, joined by AND or OR, with grouping, writing the SQL live beneath; text one switch away, and back only while the text is in a shape the builder can show (otherwise "edited as text");
    - **Explain now:** the condition worked out with the values as they would be (for a workflow, a chosen past run's).
  - **Explain against a past run:** on a job in a workflow run (outline, diagram panel, Job History), each condition with each value as it was, each part held or not, and the result. Also Reactions' Explain against a past run, held back from Phase 3: which entries matched, from what is already recorded.
  - **On the diagram:** a job with a Custom rule draws its incoming lines in one neutral style, the rule shown on pointing at the `{x}` marker on its box.
- **Out, to a following phase (proposed: Phase 4b, "handing data downstream"):**
  - the **Operations object**: `Extract.Operations` as a table in conditions, to reconsider: it would make workflow decisions depend on the operations audit trail, asynchronous by design (TO-DO decision 10);
  - **For Each File over an upstream job's files**, and the trace linking the handoff, to reconsider likewise: the list of files would have to come with the job's own report;
  - **workflow variables**: `${...}` of the workflow's own, inherited by its jobs, a use's overrides, and the **Tags before workflow variables** setting.
- **Out, to [ROADMAP.md](ROADMAP.md):** Set Return Code becoming Set Return Values (named values of a job's own, read downstream). Nothing in the workflow phases depends on it.
- **Out, already in later phases:** `%{Now...}` and time windows (5, with outside dependencies); paths into embedded workflows such as `%{MONTH_END.Extract_EU.FileCount}` (6); completion rules' *Ends when* (later, with the Kill it needs: TO-DO).

## The steps (proposed)

1. **Model and migration:** a job run's outputs (name, value), written when it ends; the Custom rule on an item (`JoinRule` `CUSTOM`, its condition); a workflow's completion rules; every condition's values and result recorded with the run, for Explain.
2. **The engine:** outputs reported by each job with its end; Custom rule in the workflow runner (decision 2, below), a rule naming no job worked out when the workflow starts; completion rules; each condition logged with its values in the workflow's log.
3. **Checks before a run and on save:** a condition naming a job or output that does not exist, or a job not waited for, is refused on save with the reason; type mismatches are warned of, as in flow control.
4. **The condition box:** help, validation, the builder, Explain now; on the workflow page (Custom rule, Succeeds when) and in the job editor (If, ElseIf, While).
5. **Explain against a past run,** and the diagram's `{x}` marker and neutral lines.
6. **Sample, docs and tests:** a sample workflow using a Custom rule over two jobs' outcomes and a file count, and a Succeeds when; CHANGE_LOG, PROJECT_BLUEPRINT, FLOW_CONTROL.md, WORKFLOWS.md; engine tests for outputs, Custom rule (holds, never holds, waits) and completion rules; UI tests for the box, the builder's round trip with text, and Explain.

## Settled with the owner (2026-10-18), and still to discuss

1. **Split the phase:** conditions in Phase 4, as above; the Operations object, For Each File over upstream files and workflow variables in a Phase 4b straight after. Why: shortcoming 3 is about reading, writing, validating and explaining conditions; the other three hand data downstream, and are each sizeable engine work. The data a condition most needs (Status, ReturnCode, FileCount, Bytes) is in Phase 4. **Agreed.** The Operations object: every job run already records each file operation (file, endpoints, bytes, status), which the Operations Log and the trace show; `FileCount` and `Bytes` are totals over those records. The table would let a condition ask about particular files rather than totals (`EXISTS (SELECT 1 FROM Extract.Operations WHERE DestEndpoint = 'FINANCE_IN' AND Status = 'SUCCESS')`).
   - The owner's principle (2026-10-18): "Telemetry must be recorded, but it must not harm the job's core purpose or performance." The operations log is an audit trail, asynchronous by design; Job History is core. Today one pipeline carries both, synchronously after each step; that is recorded in TO-DO (decision 10) and ROADMAP.md, and not needed to finish the workflow phases. What it means for them: no workflow decision may depend on operations records, so `FileCount` and `Bytes` come with the job's own end report, and 4b's Operations object and For Each File over upstream files are to be reconsidered.
   - The owner's view: where a job's outcome matters downstream, the job should say so with return codes. The Operations object's worth is weighed when 4b is planned.
2. **A Custom rule holds as soon as it is true**, as it reads: "A or B" holds once either is. It is worked out each time one of its jobs ends, a job still running counting as unknown (SQL's `NULL`), and SQL's own logic does the rest: `TRUE OR unknown` is true, `FALSE AND unknown` is false. True starts the job, false makes it Not run (it can never hold), unknown waits. `IS NULL`, `coalesce`/`ifnull` and `CASE` turn unknown into an answer, so a rule using them on a job's outputs is worked out only once all its jobs have ended (or the check refuses it). "Ended" is tested with `%{A.Ended}`, not `%{A.Status} IS NOT NULL`, which is false, not unknown, while A runs. **Agreed.**
3. **Custom rule with one prerequisite, or none: offered.** Testing a variable (`${Region} = 'EU'`) makes the case, with no job named at all; a file count (`%{Extract.FileCount} > 0`) comes with it. *All* and *Any* are greyed out unless the job waits for two jobs or more. **Agreed.**
4. **Completion rules, smallest version:** *Succeeds when* (the default, or a condition over any job in the workflow) and *Return code* (0 or 1, or a chosen job's). *Ends when* waits, since leaving jobs running or killing them needs more than conditions. **Agreed.**
5. ~~Set Return Values' values reach downstream steps' parameters.~~ Dropped with Set Return Values, which moved to ROADMAP.md.
6. **The jobs a Custom rule names are the jobs it waits for.** Under Custom rule there is no separate prerequisites list to fill in. On save, the rule is read once and the jobs it names are stored as prerequisite rows, as now, kept in step with it; the diagram, the runner and the checks use the rows and never parse text (the owner's point: explicit prerequisites need no parsing to see a relationship). Renaming a job updates the rules that name it. **Agreed.**

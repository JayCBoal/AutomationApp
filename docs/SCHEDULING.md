# Scheduling

How AutoApp starts jobs and workflows by itself, on dates and times, and how a user can see why a date was chosen. This is the planning page for the roadmap item "Scheduling: one model, and an explanation" ([ROADMAP.md](ROADMAP.md)).

Status: **PLANNING STARTED 2026-10-21; nothing decided beyond what is marked Decided, nothing built.**

## Where AutoApp stands today

- AutoApp has no scheduler of its own. Jobs are started by an outside scheduler (by job key), by the Run Job page, or by a workflow.
- The workflow runner polls about once a second for what it can start. Nothing owns "what is due next".
- Workflows already have time conditions: the built-in `%{Now.Time}`, `%{Now.Date}` and `%{Now.Weekday}`, and outside prerequisites on time windows and dates (Phase 5, D99 to D115). A prerequisite on a time window waits until it opens.
- A run can carry a business date (`JobRuns.BusinessDate`, `--business-date`).
- AutoApp is a demonstrator of scheduler features wanted in RunMyJobs, so scheduling here is meant to show a better design, not to replace a production scheduler.

## What RunMyJobs does, and the complaint

- Time Windows and Advanced Schedules (once Submit Frames) are powerful and flexible, but complex.
- It is often hard to work out how to build a particular schedule.
- It is hard to understand how a combination behaves. The UI shows the resulting dates but not how it got to them.
- The two overlap: some parts of a schedule can be modelled in either.
- A job definition carries no time windows or submit frames; they apply only when it is submitted. So a Control-M job "Monday to Friday at 08:00" has no native form, and there is no native mass scheduling.

## Direction (from the roadmap)

- **One simpler model that loses none of the flexibility, and an explanation for every date.**
- **Calendars** stay as the shared object: working days, holidays, fiscal periods.
- **A schedule** is a list of plain rules that name calendars. For example: "06:00 on every working day of FinanceCal; when that is a holiday, the next working day".
- **Why this date:** for any date in the preview, the rule that produced it, the calendar days it used, and any date it moved from. For a date that does not appear, the rule that ruled it out. This is the same idea as Explain on workflow conditions.
- The schedule reads back in plain words in the editor.
- **What the separation may be for.** A time window is used for more than starting jobs: when a queue is open, when a job started by a dependency may start, blackout periods. A reusable "period" may still earn its place, but as one kind of object inside a single model, not a second model beside the first.
- **Starts with:** the owner's examples of schedules that are hard to build or to read in RunMyJobs. The owner has none handy (2026-10-21), so the model is designed from the direction above and tested against examples as they turn up.

## Topics to settle

### 1. The engine model (first decision)

- *Real-time* (ActiveBatch): the scheduler works out each job's next start as it goes.
- *Next-run* (RunMyJobs): the next occurrences are worked out ahead of time, so a burst of jobs due together is mostly pre-processed. **Owner's lean.**
- *New Day* (Control-M): a daily batch of the day's jobs is built at a set time. Not seriously considered.
- Wanted: next-run as the main model, with a real-time style available for special cases. The named case is recurrence where a job must run every X minutes regardless of the prior instance.
- **Decided 2026-10-21:** next-run is the default model. Real-time recurrence is an option, not a second engine. New Day is not built (its reason to exist is a daily cut-over for a batch-date world that AutoApp can express with a business date on a run).
- **What real-time recurrence costs** (discussed 2026-10-21):
  - A cadence tied to the clock ("every 5 minutes from 08:00 to 18:00") can be computed ahead and needs nothing special.
  - Only an interval measured from the previous run's start or end, or an exit on an event, is truly dynamic. Its next occurrence is not known until the previous run starts or ends.
  - Preview and "Why this date" cannot list future dates for it, only say how the next one is worked out.
  - It forces the overlap policy (topic 4), since runs may be alive together.
  - After downtime, only the last run is known, so what was missed has to be worked out.
  - A look-ahead limit is needed for short cadences.
  - **Proposed containment:** the engine holds only the next occurrence of a dynamic rule and computes the following one when the previous run starts or ends. One engine, one queue of due occurrences; only how the next occurrence is produced differs.

### 2. Objects, and where a schedule attaches

- **Reading of the roadmap note** (2026-10-21): RunMyJobs has two overlapping reusable time objects, the Time Window (when something is allowed or open) and the Advanced Schedule (when to submit). The owner's objection is the overlap, not that there are two objects.
- **Direction, following ActiveBatch (proposed 2026-10-21, in the owner's definitions; supersedes the roadmap's "calendars are the shared object"):** two reusable objects with a clear division of purpose and no overlap.
  - A **calendar** is a list of dates, or rules that calculate dates, on which schedules may operate. It has no times and **no polarity of its own**: the link between a calendar and a schedule says whether it is used for inclusion or exclusion. The same Holidays calendar can exclude on a schedule for every business day and include on one for non-business days. A calendar is meaningless without a schedule.
  - A **schedule** defines a recurrence pattern, and that is all. The pattern may be one date and time and never again, or "every 30 seconds between 06:00 and 18:00 every third Tuesday". A schedule may be used with or without a calendar.
  - In short: a schedule generates occurrences and a calendar filters them. A job or plan may also use a calendar with a schedule for inclusion or exclusion.
  - The definitions are not set in stone; the owner is open to feedback.
- **Calendar rules versus schedule rules.** Calendar rules are at most yearly: "3rd Monday in January" (Presidents Day) is a calendar rule. "3rd Monday of every month" repeats more often, so it is a schedule rule. The kinds of calendar rule (fixed date, nth weekday of a named month, relative to Easter, other holiday calendars) are left for later.
- **When a date is not allowed by the calendars** (the owner, 2026-10-21; ActiveBatch has the first three): drop it; move it to the *next* allowed date; move it to the *previous* allowed date; or move it to the *nearest* allowed date (Christmas on a Saturday closes the Friday before; on a Sunday, the Monday after).
  - *Ties* for nearest (a mid-week date has the day before and the day after equally near) need an explicit rule, for example prefer the earlier or the later.
  - *Collisions*: a moved date may land on a date that already has an occurrence. Proposed: a schedule runs once per date unless its pattern says otherwise, so duplicates collapse into one and the explanation says so.
  - *Where the setting lives* (proposed, not agreed): one "when a date isn't allowed" setting on the schedule, not one per calendar link, because the nearest allowed date has to be worked out against all the calendars together.
- **Several calendars on one schedule** (proposed 2026-10-21, replaces the earlier union rule; the owner remembers ActiveBatch using a union and has not rechecked): each linked calendar is a filter applied to the dates the schedule's pattern produces, independently, so order does not matter.
  - A calendar linked for **exclusion** removes its dates.
  - A calendar linked for **inclusion** removes every date that is not in it (the inverse of its set).
  - So a date survives only if it is in every inclusion calendar and in no exclusion calendar. No special case is needed for a schedule with no inclusion calendar: nothing is removed.
  - "Either" is expressed with several schedules on a job, which combine as a union; "both" is several calendars on one schedule.
  - The "when a date isn't allowed" setting works against the dates that survive. Whether a calendar can be built from other calendars (weekdays minus holidays) is open.
- **The one place the two could overlap.** Calendar rules describe a standing fact about dates (a holiday); schedule rules describe what should happen on them. The yearly line above, and names and UI design, are meant to keep them apart.
- **Time zones: out of scope** (owner, 2026-10-21). AutoApp follows RunMyJobs' behaviour and designs nothing of its own. When building, look at what RunMyJobs actually does.
- **Calendars in conditions:** open. Whether a workflow condition can ask "is today a business day of FinanceCal". It would give calendars a use outside schedules.
- **Open: inline schedules.** Can a job carry a one-off schedule that is not a named object, or must every schedule be named? A "save as shared" step could cover reuse.
- **Open/closed periods** (queue hours, blackouts, when a dependency may start): proposed to defer. Workflow prerequisites already express "only between 06:00 and 18:00" in conditions, and a whole-day blackout is a negative calendar. Revisit if AutoApp gets queues.
- The objects: calendar, schedule, rule, occurrence (and possibly period). Names and fields to design.
- **Wanted: schedules attached to the job definition**, so a definition carries its own schedule, with an **override** when it is submitted.
- **To settle:** what an override replaces: the whole schedule, or adds and removes occurrences.
- **Wanted: a sweep.** A system job looks through the definitions for jobs that should be scheduled but are not, and raises an operator message if it finds any. Ties to Operator Messages (ROADMAP.md, People in the loop).
- **Decided 2026-10-21, "eligible":** the job is enabled and has scheduling objects attached such that, if submitted with them, it would run at least once in the future. The sweep reports eligible jobs that are not currently scheduled.
- **Deferred by the owner until scheduling is next taken up:** how imported Control-M or RunMyJobs jobs arrive with their schedules.

### 3. Recurrence with its own exit

- A recurrence mechanism with an exit condition: "run every X minutes until Y happens".
- Y could be a time of day, the job ending with a particular return code, or whatever else is wanted.
- Related, already in the docs: workflow prerequisites may not form a cycle (D104), and repeating across workflows is the TO-DO "Rerun workflow" Reaction with a required limit (TO-DO.md, Loops across workflows). **The two should be designed together so there is one way to say "repeat, and when to stop".**
- **To settle:**
  - whether Y can reuse the condition language workflows already have (`%{Job.ReturnCode}`, `%{Now.Time}`, D20 and D45);
  - whether a cap on runs or a latest end time is required, so a recurrence cannot run forever (as the Rerun Reaction's limit is);
  - whether X counts from the start or the end of the previous run;
  - what happens if a run is still going when the next is due (see Overlap below).

**Recurrence scenarios (owner's list, 2026-10-21) and what they reduce to**

- The scenarios:
  1. A rigid every-X-minutes cadence: (a) run every cycle regardless of the previous instance; (b) run the next future pre-calculated occurrence once the previous instance has completed.
  2. X minutes after the *start* of the previous instance: (a) run the next even if the previous is still running; (b) delay the next until the previous completes.
  3. X minutes after the *completion* of the previous instance.
- **Two independent settings.** *What the next occurrence is measured from:* the clock grid, the previous run's start, or the previous run's completion. *What happens if the previous run is still going when the next is due:* Allow, Skip, or Delay.
- **Allow and Skip are about occurrences; Delay is not.** A schedule only produces times. "Wait until the previous run finishes" is a condition on starting a run (a constraint such as "no instance of this job already running", or a prerequisite on the job's own previous instance), not part of a schedule. So 2b is 2a plus that start constraint, and the constraint is not a recurrence feature.
- **Valid combinations** (the editor offers only these):

  | Anchor | Allow | Skip | Delay |
  |---|---|---|---|
  | Clock grid | 1a | 1b | not offered |
  | Previous start | 2a | not offered | 2b |
  | Previous completion | cannot overlap | cannot overlap | cannot overlap |

  - Delay on a clock grid would run the missed slots late, off the grid and back to back, so it is not offered.
  - Skip on a start anchor has no grid to skip to: after a dropped occurrence nothing is left to measure from and the recurrence would stop, so it is not offered.
- **Decided 2026-10-21:** "start" of the previous run means the start of its execution (not when it was due or submitted).
- **Delay by a dynamic prerequisite** (proposed 2026-10-21, not yet agreed): when instance N starts, the engine creates the next occurrence, due at start + X, carrying a prerequisite "instance N has completed". The prerequisite is on the occurrence, not on the job definition, so the earlier decision against prerequisites on standalone jobs stands. The same mechanism serves Delay on any schedule.
  - Whether the prerequisite requires "succeeded" (the next occurrence becomes Not run after a failure) or "completed, any outcome" gives the failure setting under Open below.
  - To check: Phase 5 outside prerequisites point at a job's current or latest run, and this one needs a specific run; D104 (no cycles) must be worded for definitions, as this case is run to run; the waiting occurrence must be visible to operators, who can hold or skip it.
- **Engine consequence.** 1a and 1b are next-run: the grid is computed ahead and can be previewed and explained. For 1b, at completion the engine drops the slots now in the past and takes the next future one. Only 2a, 2b and 3 are dynamic: the next occurrence is computed when the previous run starts (2a, 2b) or ends (3).
- **Open:**
  - The origin of a clock grid: the schedule's own start (proposed, so it cannot drift) or the first actual run.
  - Whether the recurrence continues after a failed or cancelled run (the exit condition above), and whether a Phase 7 restart counts as a completion.

### 4. Runtime behaviour (gaps noted 2026-10-21; none discussed yet)

- **Time zones and DST.** Out of scope; follow RunMyJobs (see topic 2).
- **Missed runs.** If the scheduler was down at 06:00: catch up, skip, or ask. Possibly a per-schedule setting.
- **Overlap.** When the previous run is still going when the next is due. For a recurrence, see the valid combinations in topic 3: Allow or Skip are choices on the occurrence; waiting (Delay) is a start constraint, not a schedule feature. Allow and Skip apply to any schedule, not only recurrence (a daily job can overrun into the next day). Still to settle: whether the start constraint is a job setting or a prerequisite on the job's own previous instance.
- **Where the loop runs.** Its own process, and what owns "what is due next". Links to [HOSTING.md](HOSTING.md).
- **Relation to the Phase 5 time-window and date prerequisites.** Both are time conditions; the "one model" argument may apply to them too. WORKFLOWS.md also asks what an outside prerequisite with no time limit means when there is no daily cycle to end its wait.
- **Business date.** How a scheduled occurrence gets one.
- **Manual handling of an occurrence.** Hold, skip, or run now.

### 5. Explanation and the sweep

- "Why this date" and the plain-words read-back (Direction above).
- The eligibility sweep and its operator message (topic 2).

## Suggested order of discussion

1. ~~The owner's examples of hard schedules~~ (none available; skipped).
2. ~~The engine model (topic 1)~~ (decided).
3. The objects and attachment (topic 2).
4. Recurrence and exit, with Rerun (topic 3).
5. Runtime behaviour (topic 4).
6. Explanation and the sweep (topic 5).

## Decisions so far

- 2026-10-21: "eligible" defined as above (topic 2).
- 2026-10-21: next-run is the default engine model; real-time recurrence is an option within it (topic 1).
- Nothing else is decided.

## Sources

- ROADMAP.md, "Scheduling: one model, and an explanation".
- The Roadmap inbox entries of 2026-10-21 ("Recurrence with built-in exit logic" and "Scheduling: engine model, and schedules attached to definitions").
- WORKFLOWS.md (Time windows, Phase 5, Later), WORKFLOW_DECISIONS.md (D20, D45, D104), TO-DO.md (Loops across workflows).

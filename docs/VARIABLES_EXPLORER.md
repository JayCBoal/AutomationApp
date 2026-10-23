# Variables Explorer

A way to see, for any job or workflow, **every variable in its reach, where each value comes from, which one wins and why.** It answers the part of RunMyJobs' variable model that AutoApp's flexibility makes harder, not easier: the same variable can arrive by several paths, and nothing says which path won.

Status: **PLAN DRAFTED 2026-10-21 from a discussion with the owner; not built.** Two open points are marked **Open**. Nothing here is a Workflows phase; the workflow sessions are not affected. The name comes from ActiveBatch's Variables Explorer pane, which does a similar job.

## Why

- **In RunMyJobs** there is no variable inheritance. A chain's parameters reach a child job only after each is mapped to a job variable by hand. Rigid, but a value's path is always one hop.
- **In AutoApp** a variable can reach a job through the job itself, its use in a workflow, the workflow, the workflow's tags, the job's tags and system values, in an order set by the system-wide Variable precedence setting (D92). That flexibility is the point, and it makes "where did this value come from" a real question.
- The explorer is the answer. The model stays flexible; the user can see why it gave what it did.

## Starting point

Already built, and what this plan uses:

- **The scope engine** (`engine/scope_engine.py`) resolves a job's variables in the precedence order, finds tag conflicts, and resolves placeholders on demand, up to 10 levels deep, with a circular reference an error.
- **`GET /api/v1/variables/resolve`** returns the merged result for a job: the winners only, with no source and no losers.
- **Tag conflicts:** two tags on one object giving one name different values are an error if the variable is used and nothing higher settles it, a warning in the job editor if not. `${TAG:path.Name}` picks one side inside a single text.
- **A workflow job's pane** shows each `${Name}` in a step with its value and where it comes from (WORKFLOWS_PHASE4.md, decision 27). The explorer should reuse that idea, so the two do not drift apart.
- **The Variables sections** on Details pages list an object's own variables, a job's tags' and the scheduler's. Today the Tags panel only strikes out the losers.
- **Run values for Resume** (`engine/run_values.py`, Workflows Phase 7) keep what a run's placeholders resolved to, in the run's control file. That is for resuming, not audit.

## What it includes, and what it leaves out

- **In:**
  - an explanation engine that returns every candidate for each name, not just the winner;
  - a Variables Explorer on the job page, then in a workflow job's pane, then a lighter version of the same view on every other Details page;
  - a per-name pick to resolve a tag conflict;
  - the "references this job uses" list;
  - a per-endpoint explanation of a path and pattern;
  - a stored display order for variables (its own phase).
- **Out:**
  - The **audit of the values a run used and of the definition's state.** On the roadmap inbox (2026-10-21). The engine is designed so it can later answer "what did this run use?" from stored values.
  - Whether applications and entities should carry variables at all. Tabled (see "Tabled").
  - Anything that changes which value wins. The precedence rules stay as they are.

## Decisions

1. **One explanation, many views.** The engine returns a list of candidates per name (level, source object, value, secret flag, won or not, the conflict if any). Every view reads that one result, so no page works out precedence for itself.
   - *Why:* the job page, the workflow pane and the other Details pages would otherwise each compute "who wins" and drift apart. D92 chose one order everywhere for the same reason.
   - *Considered:* each page asking the existing `/resolve` and diffing; rejected, since it cannot show losers.

2. **Levels are data.** The explorer reads the Variable precedence setting and the levels the engine has; no level is named in a page. A level the setting does not give a job is not shown.
   - *Why:* a later decision to drop or add a level (see "Tabled") then costs the explorer nothing.

3. **The explorer shows job-level levels only:** the use's override, the job, the workflow, the workflow's tags, the job's tags and system values. Endpoint, application and entity values apply only while an endpoint's path and pattern are filled in (a comment in the scope engine says so), so they belong to the step that uses the endpoint, not to the job (owner, 2026-10-21).
   - *Why:* showing them as job-level candidates would suggest a step's `${Name}` could take them, which it cannot.
   - *Instead:* a per-endpoint explanation (build step 5) and the "references used" list (decision 4).

4. **"References this job uses."** An explicit reference such as `${APP:Finance.Region}` reaches a value from anywhere. The explorer lists each explicit reference in the job's steps, resolved, with its source object as a link.
   - *Why:* it is the one way an application's or entity's variable reaches a job, so a job's page that left it out would hide real inputs.

5. **A tag conflict is resolved by a per-name pick** (owner, 2026-10-21). On a conflict, the explorer shows each side and the user chooses which tag wins for that name, on that object. The pick is stored, audited, and shown as "chosen by pick".
   - *Why:* a conflict stays an error until someone decides, so no value wins silently. A pick, unlike overriding the name on the job, copies nothing, so it cannot go stale when the tag's value changes. It is the object-level form of `${TAG:path.Name}`.
   - *Considered:* an order among a job's tags with the last winning. Rejected: reordering or adding a tag would change values silently, every tagged object would carry a hidden order, it contradicts "tags have no precedence among themselves", and it resolves conflicts nobody has looked at. Also rejected: overriding on the job, which copies the value.
   - *Alphabetical listing:* with no precedence among tags, a job's tags are listed alphabetically. The order applied carries no meaning and would suggest one.

6. **The scheduler's variables are one collapsed row,** "From the scheduler, known at run time", unless a connector has pulled the WLA job's parameters (TO-DO item 7, step 3), in which case their values are shown, marked "from the scheduler".
   - *Why:* an environment variable matters only where a scheduler hands parameters to the runner. Under a real WLA the scheduler's own variable mechanism does the work and AutoApp's resolution is little used; with AutoApp alone nothing arrives that AutoApp did not supply (owner, 2026-10-21). So it is not part of normal inheritance, and the explorer does not pretend it is.

7. **Secrets show as `********`** wherever they appear, including as a loser, and a conflict between secrets says that they differ, not how. Audits never record variable values (project rule).

8. **Display order is stored and changes nothing else.** Each variable holds a number saying where it sits in its list, like a step's position. Evaluation order stays independent of it (a variable may refer to one defined further down).
   - *Why:* the owner wants to group variables for operators (required and most used first) without any effect on results.
   - *Migration:* adds the column to `Variables` and `WorkflowItemVariables`; existing variables are numbered in their current order, so nothing moves. Works on SQLite and MariaDB and keeps `autoapp_dev`'s data.
   - *Inherited lists* show each object's variables in the order set on that object.

## Build steps

Each step is complete with its tests, CHANGE_LOG entry and plain-words messages.

1. **Explanation engine.** A read-only companion to the scope engine that returns the candidates per name, the winner, the conflicts and the chain a placeholder follows (to the existing depth of 10). The existing `/resolve` stays unchanged; a new endpoint serves the explanation.
2. **Explorer on the Job Detail page.** One row per name with the winner highlighted and the losers beneath it, each with its level and source object as a link (opening in a new tab). Conflicts in red. A name used by a step but with no source is marked "has no value here". The scheduler row (decision 6). The "references used" list (decision 4).
3. **Per-name pick.** The control on a conflict, its storage (migration), its effect in the engine, and an audit entry. The engine and the preflight check treat a picked conflict as settled.
4. **Explorer in a workflow's job pane,** replacing the pane's own working-out (WORKFLOWS_PHASE4.md, decision 27) with the shared explanation, and the same for a workflow's own page.
5. **Per-endpoint explanation.** On the endpoint page: how its path and pattern resolve, with the endpoint's tags, application and entity values that fed it.
6. **Variables section on the other Details pages** (application, entity, site, tag, workflow): the object's own variables first, under "On this <type> itself", then inherited sets in precedence order, the winner highlighted. A lighter use of the same view.
7. **Display order** (its own small phase, decision 8): the column and migration, up and down arrows in the editor, and the ordering in every list.

Steps 1 to 3 are the core. Steps 4 to 6 reuse the explanation and can follow in any order. Step 7 depends on none of the others.

## Tabled

- **Do applications and entities need variables?** Tags already feed those objects, so the two overlap. Explicit `${APP:...}` and `${ENTITY:...}` references are the one use that has no tag equivalent. For a separate discussion; decision 2 means either answer leaves the explorer unchanged.
- **The sample for the demo:** a job that inherits `Region` through two paths and one conflict, loaded into `autoapp_dev` (and the seed) when step 3 is built.

## Goes with

- ROADMAP.md, once the Roadmap Planning session takes this in: replaces "Which variables a job can see" in TO-DO.md and the Variables Panel proposal in UI_VISION.md.
- The roadmap inbox items "Links to objects" (the explorer's source links are the first users of the shared link helper) and "Variables section on every Details page".
- Change history and the audit of run values (roadmap inbox, 2026-10-21).

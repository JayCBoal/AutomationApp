# Workflows, Phase 6: embedded and shared workflows

The sixth phase of [WORKFLOWS.md](WORKFLOWS.md) ("Implementation in phases"): **a workflow can hold jobs and workflows of its own, drawn as frames, and reach into them.** It answers shortcoming 6 ([PROJECT_GOALS.md](PROJECT_GOALS.md) goal 2): in RunMyJobs a structural sub-chain is a separate object everyone can see, list and reuse by accident, and there is no way to say "all of these, then those" without chain steps.

Status: **DRAFT, planned 2026-10-19 (planning session only; nothing built).** Phase 5 was still being tested in another session. Every proposal below is a recommendation waiting for the owner; the ones marked **ASK** change what the owner will see or do. Decisions get D numbers (from D116) when agreed.

## Starting point

Already built, and what this phase uses:

- A workflow is a job with `JobType` `WORKFLOW` (D3); its items (`WorkflowItems`) can already be **a workflow**, not only a steps job. Such a *shared* workflow runs as a child workflow run, Kill and Cancel pass down through it, and a workflow that uses itself, directly or through others, is refused on save.
- Every item has a unique name in its workflow, and every run item a `Path` (`Transform/Stage`); job runs know their parent run and path; Job History shows a workflow run as a tree.
- `Jobs.Owner_MasterObject_id` exists and is unused ("embedded"); the Jobs & Workflows list already leaves out jobs with an owner.
- Completion rules (Succeeds when, Return code from), Reactions, Disable here, the Start rule, Custom rules, outputs (`Status`, `ReturnCode`, `FileCount`, `Bytes`: a workflow's are its jobs' added up) and prerequisites all belong to the item or the job, so they work on a workflow item as they do on a job item.
- The mockup page (`ui/mockup_workflow.html`) already draws frames, folded and open (D88).

Designed, not built: embedded jobs and workflows; frames; prerequisites that cross a frame; variables inherited by what is inside (D91); dotted paths in conditions; deep Find; shared workflows opened inline; making an embedded job shared and back.

## What Phase 6 includes, and what it leaves out

- **In (proposed):**
  - **Embedded jobs and workflows:** "New job here" and "New workflow here" in the editor, beside "Use an existing job…". An embedded one belongs to its workflow, is hidden from lists, and is deleted with its item or its workflow.
  - **Frames:** an embedded workflow drawn as a frame around its items, to any depth; folded it is one box with a summary (in a run: "2 running, 1 failed"); lines that end inside a folded frame carry their arrowhead a little way in. One Save covers the whole tree.
  - **Prerequisites across frames:** on the frame as a whole (it gates everything inside), and from a job inside to anything else in the same tree, outside its frame included.
  - **Paths:** `%{Transform.Stage_EU.Status}` in conditions, down through embedded workflows; the path shown in Find results, Job History and logs as `MONTH_END / Transform / Stage_EU`.
  - **Variables inherited** down through every workflow in a workflow, shared ones too (D91).
  - **Deep Find:** through embedded and shared workflows however deep, with the path in each result; matches highlighted, a folded frame says "2 matches inside", *Show matches* opens the way; shared workflows open inline for this, read-only and visibly distinct.
  - **Shared workflows in the diagram:** one box, opening read-only inline and linking to their own page.
  - **Phase 5 follow-ups that need this:** an outside prerequisite can name an embedded item of another workflow (paths into them); a workflow others wait for as a whole shows **Needed by** on its own page (TO-DO).
  - **Make shared / Make an embedded copy** (proposal 10; could wait).
  - **Sample, docs and tests:** `DEV-FRAMES_SAMPLE` (below), loaded into `autoapp_dev` as well as the seed.
- **Out:**
  - The Operations object and For Each File over an upstream job's files (D42): the dotted paths here reach items' outputs only.
  - Restarts through frames (Resume, Rerun ▸ from a point inside a frame: Phase 7). Rerun from… as built works inside one workflow only.
  - Reactions that act across frame boundaries beyond what proposal 8 says.
  - Moving an item between frames by dragging; pinning positions.
  - Anything for schedulers: a scheduler still starts a top-level job or workflow by its key ([INTEGRATION.md](INTEGRATION.md) is not touched).

## Proposals to settle with the owner

1. **An embedded item is an ordinary item whose job has an owner.** No new table: the item points at a Job whose `Owner_MasterObject_id` is the workflow. Removing the item deletes that job (and, for an embedded workflow, everything inside); deleting the workflow does the same. A shared job is never deleted by either. *Recommended.*
2. **Keys for embedded jobs.** A job needs a unique `JobKey` (it names the working folder). Embedded ones get a generated key `MONTH_END.Extract` (owner's key, a dot, the item's name), made at creation and **never changed afterwards**, even if the item is renamed, because a key names a folder that logs and files may already sit in. The key is shown nowhere the user must handle it; the item's name is. **ASK:** fine, or should a rename change the key (and the folder) too?
3. **One Save for the whole tree.** The page edits the workflow and everything embedded in it as one form, saved together or not at all, with the checks run over the whole tree (names, prerequisites, cycles). Recommended over saving each frame separately because the diagram shows one thing; it also keeps "changed since the last save" markers meaningful.
4. **Names and paths.** An item's name is unique in its own workflow only (D6 stands), so two frames can each hold a `Stage`. A condition names a sibling by its name (`%{Extract.Status}`) and goes down by dots (`%{Transform.Stage.Status}`). A condition **cannot reach up or across** into another frame by a short name: it uses the full path from the nearest workflow that contains both (`%{Extract.EU.FileCount}` from `Transform`'s sibling). Only embedded items are reachable by path; into a *shared* workflow only its own outputs (`%{Shared.Status}`, `FileCount`), because another workflow's internals can change without this one being saved.
5. **Prerequisites across a frame (where the rules need a choice).**
   - The frame as a whole can have prerequisites and a Start rule like any item; until they hold nothing inside starts.
   - A job inside may wait for any other item **in the same top-level tree**: a sibling, an item in a frame above, or inside another frame. The line goes to the frame's edge and into it, as the design says.
   - Cycles are refused across the whole tree, naming the path. A job inside a frame cannot be waited for from outside **by its short name**, only by its path.
   - **Engine choice (my recommendation):** every frame is a child workflow run of its own (the mechanism shared workflows already use), so a frame has its own status, Reactions, Disable here, Kill, Success return codes and place in Job History. A job inside that waits for something outside its frame looks it up in the enclosing runs of the same top-level run, as Phase 5's resolver does for other workflows. The alternative, flattening the tree into one graph at run time, is simpler for lines but gives a frame no status of its own, and the design wants it to have one. **ASK** only if the owner prefers flattening.
6. **Variables (D91 completed).** A workflow's `${...}` reach every job and workflow inside it, embedded or shared, fixed when the top-level run starts. The nearest workflow wins, then a use's override, then the existing Variable precedence setting for the rest. A shared workflow gets its parent's values while it runs inside it, not elsewhere. A secret is passed down by reference, never as a value.
7. **Disable here, Success return codes and completion rules on a frame** behave as on any item, for the whole frame. Disable here (STOP) on a frame ends it Disabled with everything inside Not run; PASS_THROUGH ends it Bypassed.
8. **Reactions inside frames.** A Reaction's targets stay within the workflow that holds the item (Rerun from… and Skip… name siblings in the same frame; Kill the workflow kills **the workflow the item is in, i.e. its frame**, and the frame ends Failed, `KILLED`, which the frame's parent then treats like any failed item). A Reaction on a frame item itself (rerun the frame, skip after it) works like one on any item. **ASK:** is "Kill the workflow" meant to kill the frame or the whole top-level run? Recommended: the frame, with a separate wording ("Kill the top-level workflow") only if the owner wants it.
9. **Lists and records.** Embedded items stay out of Jobs & Workflows, the search pages and the audit's job picker; their changes are in the parent's Audit Log. Tags go on top-level jobs and workflows only; a workflow's tags feed what is inside (as Phase 4 built for its jobs). Job History keeps its tree and gains the frame level; the Operations Log and the trace follow job runs unchanged. Opening an embedded job's address shows it through its workflow, read-only on its own.
10. **Embedded and shared, both ways (could move to TO-DO).** *Make shared* gives the embedded job a key of the owner's choosing, clears the owner and lists it; the item now uses it. *Use an embedded copy* makes an embedded duplicate of a shared job or workflow (steps, variables, Reactions) for when a use needs to differ. No automatic merging back. **ASK:** worth including now, or leave to TO-DO per the phase-scope rule? Recommended: include *Make shared* only if the sample needs it; otherwise TO-DO.
11. **No depth limit** beyond what the diagram can show. The layout and Find are built to nest, and the checks run over the whole tree. A warning (not an error) for nesting deeper than five.

## The steps (proposed)

1. **Model and migration.** Likely no new columns (the owner column and the run items' `Path` exist); to confirm: the generated-key rule, a unique-path check, an index for "children of this workflow". If none are needed, no migration beyond a check of `autoapp_dev`. `docs/DB_SCHEMA.md` unchanged or updated to match.
2. **Store and checks.** Saving the tree in one transaction (new embedded jobs created, removed ones deleted); names, prerequisites and cycles checked over the whole tree; deleting a workflow or item with embedded content refused or confirmed (proposal 1); refusing to delete an embedded item another workflow waits for (D114 extended); paths resolved for conditions and Custom rules; the outside-name picker lists embedded items of other workflows.
3. **Engine.** A frame starts as a child workflow run when its prerequisites hold; inner prerequisites that cross a frame; paths in conditions and outputs (`%{A.B.Status}`); variables passed down (proposal 6); Disable here, Kill and Cancel through frames; the frame's status by the usual rules; run items and Job History show the tree.
4. **Pages.** The editor: *New job here*, *New workflow here*, *Use an existing job…* in any frame; the Outline nests (prerequisites under each item, frames foldable); the job pane for a frame (its completion rules, Reactions, variables); embedded jobs edited in place; the Explain and condition help know the paths; the warning for deep nesting.
5. **Diagram.** Frames from the mockup through elkjs (nested layout), fold and unfold (▾ ▸, double-click), the summary line, arrowheads into folded frames, lines into and out of frames, run states and the live summary on a frame, shared workflows as a single box that opens read-only inline, *Needed by* on a workflow others wait for as a whole. The mockup is compared with the result and updated where the real page differs.
6. **Deep Find.** Through the tree and into shared workflows; path in each result; highlights, "n matches inside", *Show matches*.
7. **Sample, docs and tests.** CHANGE_LOG, WORKFLOWS.md (Phase 6 marked built), the decision register (D7 and D91 to Built, new decisions), TO-DO tidied. Engine tests (frame prerequisites both ways, cross-frame waits, cycle through a frame, variables inherited and overridden, Disable here and Kill through a frame, the frame's status, paths in conditions, deleting and Make shared); store tests (one Save, rollback on a failed check); UI tests for the editor and the diagram (frames, fold, Find). Both suites side by side.

## The sample (proposed): `DEV-FRAMES_SAMPLE`

A month-end shaped workflow that uses every part:

- **Extract**: an embedded workflow of two embedded jobs, `US` and `EU`, in parallel.
- **FX rates**: a shared job (so "shared" shows beside "embedded").
- **Transform**: an embedded workflow that waits for **Extract as a whole**; one job inside, `Enrich`, also waits for FX rates (a line from outside the frame), the others do not. It carries a `${REGION}` variable its jobs read, and one of its jobs overrides it.
- **Reporting**: a shared workflow (an existing sample) used as a box, opened inline when Find hits inside it.
- A condition by path: `Report` runs only if `%{Transform.Enrich.Status} = 'SUCCESS'`.
- Loaded into `autoapp_dev` too (the seed's next section, and `autoapp_dev` separately).

## Decisions this plan needs from the owner

Marked **ASK** above: (2) rename keeps the embedded key or changes it; (5) one child run per frame, or flatten; (8) what "Kill the workflow" means inside a frame; (10) Make shared and Use an embedded copy now or later. Everything else is a recommendation that will become a decision when the owner agrees.

## Risks

- **Nested layout**: elkjs handles frames, but folded frames with lines ending inside, plus outside dashed boxes (Phase 5), are the likeliest place for the diagram to look wrong. The mockup is the reference; plan a visual review with the owner before the tests are finished.
- **One Save for a tree** makes the form's checks heavier; the existing Phase 4 "changed since last save" comparison by identity needs to cover embedded items.
- **Phase 5's resolver** looks for the other workflow's current or latest run. Inside one top-level run, an inner job's "outside the frame" target must be *this* run's, never "the latest": get this wrong and a re-run silently waits on yesterday's result. A test for it comes first.

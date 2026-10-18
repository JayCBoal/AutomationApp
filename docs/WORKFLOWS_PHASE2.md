# Workflows, Phase 2: the diagram

The second phase of [WORKFLOWS.md](WORKFLOWS.md) ("Implementation in phases"): **a workflow you can see at a glance, as it is defined and as it runs.** It answers shortcoming 5 (the diagram), and gives every later phase somewhere to show its work.

Status: **agreed with the owner 2026-10-17; built and reviewed by the owner 2026-10-17 (steps 1 to 6, and the changes from the review below).** Phase 1 must be committed, merged and pushed before anything here is built.

## Starting point

- The clickable mockup the phase plan asked for already exists (`autoapp/ui/mockup_workflow.html`, reviewed 2026-10-17), and elkjs 0.12.0 is vendored. So Phase 2 starts at the real page.
- Phase 1 gives the data to draw: items with full names, prerequisites (Succeeded, Failed, Ended, return codes), All or Any, and a run's item states. The page reads these from the existing API; nothing new is needed in the model (to confirm).

## What Phase 2 includes, and what it leaves out

- **In (proposed):**
  - **Diagram | Outline** on the workflow page, for the definition and for a run; the choice remembered per viewer.
  - Automatic layout with elkjs, left to right, top to bottom as a choice; each column in outline order; no dragging.
  - Boxes with full names wrapped, never truncated; what kind of thing each is (job or workflow; shared, as all Phase 1 items are).
  - Lines coloured *and* styled by test (Succeeded green solid, Failed red dashed, Ended black solid, return codes labelled, other grey labelled); the *Any* marker where lines enter; pointing at a line or marker says what it means.
  - Run states on boxes (Succeeded, Failed, Running with a moving stripe, Waiting, not started, Not run, Cancelled), updating live as the outline does now; each box links to its job log.
  - Selecting a box opens the side panel (the item's details and prerequisites); the folded key; zoom and fit.
  - Find within the workflow (direct children only; deep Find comes with Phase 6).
  - Editing on the diagram: + Job, drag from box to box for a prerequisite, select a line to change its test.
  - Job History as a tree: a workflow run with its job runs folded under it.
- **Out, drawn by the phase that builds them:** frames and folding (6), outside dependencies and Needed by (5), clock / calendar / `{x}` markers (5 and 4), Reaction lines and the ↺ look (3), Disabled-here and Bypassed looks (3 and 7), Held and late (3 and 8), the Rerun ▸ menu (7).
  - The drawing code is written so these slot in (a box can hold a frame; a line can have any style), but nothing is drawn for data that does not exist yet.

## The steps (proposed)

1. **The drawing code, from the mockup.** Turn `mockup_workflow.js` into a real module (`js/workflow_diagram.js`): takes a workflow (and optionally a run) as the API returns them, measures, lays out with elkjs, draws the SVG. Short functions, plain names; the mockup's own styles moved into `autoapp.css`. The mockup page stays as the picture of the full design for later phases; if the real page's design drifts from it, revisit whether to keep it.
2. **Diagram | Outline on the workflow page,** for the definition: the switch, side panel on selection, key, zoom and fit, layout direction, Find.
3. **The run on the diagram:** item states, live refresh, links to logs, the run's own toolbar (Cancel etc.) unchanged.
4. **Editing on the diagram:** + Job, drag box to box for a prerequisite, select a line to change its test or remove it; all through the same side panel and the same save as the outline.
5. **Job History as a tree:** a workflow run with its job runs folded under it, replacing the flat Parent run column.
6. **Docs and tests:** CHANGE_LOG, PROJECT_BLUEPRINT, WORKFLOWS.md status; UI tests for the switch, the layout (every item drawn, lines match prerequisites, full names never cut), selection, Find, run states updating, editing on the diagram, and the Job History tree.

## Decided with the owner (2026-10-17)

1. Editing on the diagram is built in Phase 2.
2. Job History becomes a tree now.
3. The mockup page is kept for now; revisit if the UI design drifts from it.
4. The workflow page opens in whichever view (Diagram or Outline) the viewer used last.
5. A line made by dragging starts as Succeeded; its test is changed in the side panel.
6. Editing on the diagram saves as the outline does (edit, then Save); switching Diagram | Outline while editing keeps unsaved changes.
7. Job History tree: workflow runs folded by default with a count of their job runs; a search for a job's runs still finds them, shown with their workflow; paging counts top-level rows, so a workflow is never split across pages.

## From the owner's review (2026-10-17)

8. **Jobs & Workflows** is one page: the separate Workflows link is gone, and the page has a Type column (Job or Workflow).
9. The Main Index has an **Administration** section for Settings, apart from the records of what happened.
10. **Submit is Save** on every page: "Submit" reads as "submit to run" to anyone who uses a scheduler.
11. A job's prerequisites sit in a **Prerequisites** box: each with **Job in this workflow** and **Outcome**; then the **Start rule** under the list (*When all prerequisites are satisfied*, *When any prerequisite is satisfied*, and *Custom rule*, greyed out until Phase 4 builds conditions; its rule box appears only once it is chosen). The Start rule is greyed out until the job waits for two jobs or more. **Remove this job** is below the box.
12. Removing a line on the diagram: while editing, pointing at a line shows a small **×** a fixed distance before its arrowhead; clicking it removes the line. A selected line is also removed with Delete.
13. The server tells browsers to check for a newer copy of every page, script and stylesheet each time, so changes show without a hard refresh.

## Carried to the next phase

- Jobs & Workflows says "*N* found" rather than "*N* jobs", since it lists workflows too.
- Open for Phase 4: whether Custom rule is offered when a job waits for only one job (a condition such as "only on business days" could still be useful there).

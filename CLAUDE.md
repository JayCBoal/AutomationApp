# CLAUDE.md

Notes for Claude Code on this project. The why behind the project is in docs/PROJECT_GOALS.md and docs/PROJECT_BLUEPRINT.md; open work is in docs/TO-DO.md.

## The project

- **AutoApp is a testbed and demonstrator** for scheduler features the owner would like to see in RunMyJobs (Redwood). The first is workflows: jobs with dependencies between them, designed and run in AutoApp (docs/PROJECT_GOALS.md lists the RunMyJobs shortcomings they answer).
- AutoApp plays the scheduler. There is no real WLA to integrate with, so AutoApp runs its own workflows. Execution matters only as far as it proves a design behaves as intended; the design (model, editor, diagrams) is the point.
- **RunMyFiles** (`~/projects/RunMyFiles`) is a fork made on 2026-10-16, a separate product with its own names, databases and ports. Nothing is shared between the two. Its principle that "the scheduler owns sequencing" does not apply here.
- Some docs from before the fork still describe RunMyFiles: PROJECT_BLUEPRINT.md, INTEGRATION.md, demo/DEMO.md and demo/scheduler_standin/README.md. Read them with that in mind. The pages, messages and README.md say AutoApp again (since 2026-10-16); past CHANGE_LOG entries stay as written.
- Internal names are `autoapp` throughout: the folder and package, `AUTOAPP_*` variables, databases, the JS namespace `AutoApp`, messages' `source: "AutoApp"`.
- The owner is a WLA expert and still learning Python, so explain Python choices in plain terms.

## Layout

- `autoapp/core`: what the server and the runners share: the tables (`core/models.py`), the database setup, the step handlers and catalog, variables and conditions, and the pre-run check. It imports neither of the others.
- `autoapp/app`: the FastAPI server (API, stores, connectors to schedulers). It never imports `engine`.
- `autoapp/engine`: the runners (`python3 -m engine.runner --job-key ... --instance-id ...`, and the workflow runner), the executor and spool delivery. It never imports `app`. `tests/test_package_boundaries.py` enforces both rules; the plan is docs/RUNNER_SEPARATION.md.
- `autoapp/ui`: static pages. `autoapp/tests`: pytest.
- `demo/`: `demo.py` (setup|start|stop|status, in /tmp/autoapp_demo, ports 8200 and 8210), `DEMO.md` (the 30-minute walkthrough), and `scheduler_standin/` (the Stand-in Scheduler, a fake WLA).
- `integrations/runmyjobs/`: the RunMyJobs draft. Nothing in it has been tried on a tenant yet.
- `SQL/`: the DDL and seed data. Regenerate the DDL with `SQL/generate_ddl.py` and the diagrams with `docs/generate_diagrams.py` after any change to the models.

## Working here

- `source dev_env.sh` (git ignores it) sets up the venv, `DATABASE_URL` (MariaDB `autoapp_dev`) and these commands:
  - `autoapp_server` (port 8000);
  - `standin_server` (port 8100);
  - `autoapp_tests`.
- **Tests:** `autoapp_tests` runs the SQLite and MariaDB suites side by side, writes to `/tmp/autoapp_tests/sqlite.txt` and `mariadb.txt`, and takes about 30 to 40 minutes (2026-10-24). Run it in the background. While iterating, run single test files, then the full suite before saying a change is done.
  - Running other heavy work alongside the suite causes timing failures in the UI tests. Rerun the failed files before treating them as real.
  - The full suite is not run after every step: targeted tests each step, a quick tier (all but the UI tests) each commit, the full suite at the end of a sub-project, before a merge, after risky steps and when the owner steps away (docs/RUNNER_SEPARATION.md, "How we test").
- **Shell:** never put `&&` before a `( ... ) &` on the same line.
- **Databases:** `autoapp_dev`, `autoapp_test` and `autoapp_sales`. The Linux user can't create databases, so creating one needs `sudo -n mariadb`. Back up `autoapp_dev` (to `demo/output/autoapp_dev_before_*.sql`) before migrating it in place.
- **Git:** work on a feature branch. Commit, merge (fast-forward only), push and delete the branch only when asked.
- **Docs:** add an entry to docs/CHANGE_LOG.md for user-visible changes. Keep the docs in step with the code.
- **Workflow decisions:** every decision about how workflows work goes into docs/WORKFLOW_DECISIONS.md when it is made, with its reason (and what else was considered), next to the phase plan's own list. A decision replaced stays there, marked Replaced, pointing to what replaced it. Before changing how workflows behave, read the entry's reason and tell the owner if the change brings back the problem it names.

## How to write and report changes

- **Report in behaviour, not code.** End each change with what now behaves differently, what was tested, and what was not. The owner reviews results more than code, so the report is the review.
- **Tests come with every behaviour change.** A bug fix starts with a test that fails because of the bug. A change is done only when `autoapp_tests` passes on both databases, or the report says plainly what failed.
- **Database changes keep existing data working.** A change to the models comes with a migration that works on SQLite and MariaDB and keeps `autoapp_dev`'s data. Dropping or renaming a column, or anything that loses data, needs the owner's approval first.
- **docs/INTEGRATION.md is a contract.** Scheduler plug-ins rely on it. A change must not break an existing caller, needs the owner's approval, and updates the document in the same change.
- **A new step type is complete only with all of these:**
  - its handler and its catalog entry;
  - help text and a live preview in the editor;
  - operation records, so the trace sees its files;
  - masked secrets in its log lines;
  - its answer to `FAILURE_KNOWLEDGE` (not done, partly done or unknown when it fails), which a Resume relies on;
  - tests and a CHANGE_LOG entry.
- **Plain words in anything a user sees.** Errors say what went wrong and what to do next, in the app's existing style ("No files matched ..."). No Python jargon in pages or logs.
- **Short functions, built from named helpers.**
  - New functions stay under about 60 lines. Split a longer one, or explain why in the report.
  - Existing long functions are left alone unless the change is already in them.
  - Pull steps out into small helpers whose names say what they do, so each function reads as a list of steps.
  - Look for an existing helper before writing one. Write a helper for the use at hand, and generalise it only when a second use appears.
- **Simple over clever.** Code a learning Python developer can follow. No new frameworks, layers or abstractions without asking, and versions stay pinned in requirements.txt.
- **No unrequested extras.** No refactors, features or clean-ups beyond the task. List anything worth doing in the report instead.

## Rules that are easy to break

- Secret values never reach a page. They show as `********` in logs and previews, and audits never record variable values.
- Redwood or BMC documentation saved locally stays out of git (third-party copyright).
- Never commit credentials, keys or `.credentials.json`.
- When a message both asks questions and requests changes, answer the questions first, then make the changes.
- Ask before installing packages.

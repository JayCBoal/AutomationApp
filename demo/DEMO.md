# The RunMyFiles demo: a 30-minute walkthrough

For presenting RunMyFiles over a screenshare: RunMyFiles and the Stand-in Scheduler on the shared screen, this script (or the slide deck made from it) on the other.

The story: **billing's nightly export of invoices and payments, run by a scheduler, handed to finance, and every file traced end to end.** The stand-in plays the part RunMyJobs would.

## Before the call

1. In a terminal, from `~/projects/AutomationApp/CodeRepo`:

   ```bash
   source .venv/bin/activate
   python3 demo/demo.py setup      # a fresh demo; deletes the last one
   python3 demo/demo.py start
   ```

   Run `setup` again before every presentation, and after any rehearsal, so the demo starts from the same place. It takes a few seconds. On the Chromebook, `/tmp` (where the demo lives) is emptied when Linux restarts, so a restart also means `setup` again.
2. In the browser on the shared screen, open two tabs:
   - **Tab 1:** `http://localhost:8210/`, the Stand-in Scheduler (red header).
   - **Tab 2:** `http://localhost:8200/`, RunMyFiles.
3. **The look on screen.**
   - Zoom both tabs so that text reads well on a shared screen; 110% usually does.
   - RunMyFiles opens in dark mode; **Light mode** at the top right switches it, and the stand-in is always light. Choose before the call. The stand-in's embedded RunMyFiles pages are always light.
4. Close everything else on that screen.
5. Afterwards: `python3 demo/demo.py stop`.

`python3 demo/demo.py status` says whether it is running.

## The timeline

| Minutes | Part | Where |
| :--- | :--- | :--- |
| 0–3 | 1. The problem, and RunMyFiles in one sentence | Slides |
| 3–8 | 2. A scheduler's job, and RunMyFiles inside it | Stand-in, then RunMyFiles embedded |
| 8–13 | 3. What a RunMyFiles job is | RunMyFiles embedded |
| 13–16 | 4. A change, saved from inside the scheduler | RunMyFiles embedded |
| 16–19 | 5. Running it from the scheduler | Stand-in |
| 19–24 | 6. Where did the file go? The trace | RunMyFiles |
| 24–27 | 7. The record: history, logs, audit | RunMyFiles |
| 27–30 | 8. What this means for RunMyJobs, and questions | Slides |

If time is short, shorten part 3 and part 7; never part 6.

## 1. The problem (0–3, slides)

**Say:**
- Most automation shops have thousands of jobs whose real work is moving and reshaping files: pick up, check, rename, zip, load, deliver.
- Each is a custom script, written by whoever was there at the time.
- When someone asks *"where did this file go?"* or *"did the bank get yesterday's payments?"*, the answer means reading job logs, one at a time.

The elevator pitch, as a bridge into the demo:

> "RunMyFiles makes those jobs defined steps instead of scripts, runs them from the scheduler you already have, and records every file it touches, so you can trace any file end to end."

## 2. A scheduler's job, and RunMyFiles inside it (3–8)

**Tab 1, the Stand-in Scheduler.**

1. **Say:** "This is a stand-in for RunMyJobs: a deliberately simple scheduler, so the integration can be shown without one. Everything it does with RunMyFiles, a RunMyJobs Extension Point would do the same way."
2. Click **BILLING_EXPORT**.
   - **Show:** the job definition, as a scheduler holds it: its parameters `SalesRegion` and `ExportPassword` (a secret), and that it gives a business date.
   - **Show:** the **In RunMyFiles** panel. "The scheduler's own screen shows what RunMyFiles knows about this job: ready to run, its four steps, asked from RunMyFiles' API."
3. Click **Edit in RunMyFiles**.
   - **Say:** "This is RunMyFiles' own job editor, opened from inside the scheduler's job editor. In RunMyJobs it would be a tab on the job definition."
   - **Show:** the job key at the top, and "Ready to run".

## 3. What a RunMyFiles job is (8–13, in the RunMyFiles window)

1. Scroll to **Variables**.
   - **Show:** *From the scheduler: STANDIN's job BILLING_EXPORT*, with `SalesRegion` = EMEA and `ExportPassword` = `********`.
   - **Say:** "RunMyFiles read the scheduler's own parameters, through its API. Nobody copies variables across. And a secret is never shown."
2. Scroll to **Tags**: `Environment / DEV`.
   - **Say:** "Tags group jobs, and carry variables that every job with the tag inherits."
3. Scroll to **Steps**, then **Expand all**.
   - **Step 1, Export open invoices (Run SQL).**
     - **Show:** the SQL, and the database given as `${APP:BILLING_APP.SalesDbUrl}`, which shows as `********`. The database's address, password included, is a secret variable of the billing application.
     - **Show:** the result file, `out/Open_Invoices_${DATE:yyyyMMdd}.csv`, and under it what it really comes to today.
   - **Step 3, Check both exports.** "Fails the run unless exactly two files, neither empty, are there. A check most scripts never make."
   - **Step 4, Send to finance (Zip Files).** "Zips them into one archive, straight to finance's inbox, a registered endpoint."
   - **Say:** "No script. Every step is a type with defined parameters, and every value is previewed live, so a mistake shows before the job ever runs."

## 4. A change, saved from inside the scheduler (13–16)

Still in the RunMyFiles window:

1. Click **Edit**.
2. In **Tags**, type `Finance` in the tag box and choose **Finance / Reporting** from the list.
   - **Show:** before it is added, the panel shows what the tag would give, `ReportRetentionDays` = 30 *from Finance*.
   - **Say:** "You see what a tag brings before you add it, and RunMyFiles warns if two tags disagree."
3. Click **Add tag**, then **Submit**.
   - **Show:** at the top of the stand-in window, its own message: *Saved in RunMyFiles: ready to run.*
   - **Say:** "RunMyFiles told the scheduler it saved, and whether the job would run. In RunMyJobs, that message lands in its own edit page."
4. Click **Close**.

## 5. Running it from the scheduler (16–19)

**Tab 1.**

1. Click **Submit**.
   - **Say:** "The scheduler runs it the way it runs any OS job: one command, the job's parameters in the environment, the exit code telling it whether it worked."
   - **Show:** the run (SIS-3) going to **SUCCESS**, with its business date.
2. Click **Output**.
   - **Show:** the job log: each step, each file, and what each value resolved to, with the database password as `***`.
3. Click **FINANCE_REPORTS**, then **Submit**.
   - **Say:** "Finance's own job picks up the archive, unpacks it, checks the reports, keeps the archive, and clears out old ones."
   - **Show:** SIS-4, **SUCCESS**.
4. Back on BILLING_EXPORT, click **Operations in RunMyFiles** on SIS-3.
   - **Show:** every file that run handled, from inside the scheduler.
   - **Say:** "One click from the scheduler's run to every file it touched." Then **Close**.

## 6. Where did the file go? The trace (19–24)

**Tab 2, RunMyFiles.**

1. Click **Operations Log**. In **Source → Filename**, type `Open_Invoices`, and press **Search**.
   - **Say:** "Every file every job handled, searchable by anything: where it came from, where it went, which application, which partner, which run."
2. Click **Trace** on any row.
   - **Show:** the route, top to bottom. The invoices file:
     1. written by the query;
     2. checked;
     3. zipped and sent to finance's inbox;
     4. picked up by finance's job, in a different run;
     5. unzipped;
     6. checked again;
   - and the archive kept.
   - **Say:** "That is one file's whole life, across two jobs and two applications, with times, sizes and the run each step belonged to. Today that question takes an afternoon of log reading. Here it takes one click, and it works from any point in the route."
3. Close the trace, and click **Trace** on another row of the same file.
   - **Show:** the same route. "Start anywhere, get the whole route."

This is the moment the demo is built around. Leave it on screen while people ask questions.

## 7. The record: history, logs, audit (24–27)

1. **Job History.**
   - **Show:** every run: from which scheduler, its instance ID, its business date, how long it took.
   - Click **Log** on SIS-3: the same log the scheduler saw, kept by RunMyFiles.
2. **Audit Log.**
   - **Show:** the tag added in part 4: who, when, and what changed, in words.
3. If there is time: **Jobs** (each job says whether it would run, and what it uses), and **Tags → Finance / Reporting** (what it gives, and what carries it).

## 8. What this means for RunMyJobs (27–30, slides)

**Say:**
- **For RunMyJobs users:** file-level lineage and an audit trail, built into the scheduler: a tab on the job definition, and the files and log one click from each run.
- **For Redwood:** a differentiator a competitor's scheduler does not have, and fewer custom scripts for customers to maintain.
- **How far it is:**
  - RunMyFiles works end to end today, with the stand-in in the scheduler's place.
  - The RunMyJobs side is drafted from Redwood's public documentation: the job definition, the Extension Point tab, the run's context menu, and the connector to the Inbound REST extension.
  - Next is trying it on a RunMyJobs dev tenant.

Then questions. Offer the deck and the demo package afterwards.

## If something goes wrong

| What happens | What to do |
| :--- | :--- |
| A page will not load | `python3 demo/demo.py status`; if not running, `start`. If it still fails, `stop`, `setup`, `start`: about 20 seconds. |
| FINANCE_REPORTS fails with "No files matched" | It ran before BILLING_EXPORT, so there was nothing to pick up. That is a feature: "it refuses to carry on with nothing, and says why." Run BILLING_EXPORT, then FINANCE_REPORTS again. |
| The tag was already added (a rehearsal was not reset) | Show the Audit Log entry from the rehearsal instead, and reset before the next presentation. |
| The embedded editor shows "Saved" with problems | Read out the problem it lists. The check is the point. |

## Optional, if asked or if there is time

- **A failing run.** Submit FINANCE_REPORTS twice in a row: the second has no archive to pick up, so it fails and says why. Its log shows the error in red. This shows the failure path.
- **Run Job page** (RunMyFiles' top bar): runs any job from RunMyFiles itself, without a scheduler, with its log live.
- **Settings:** the order in which variables are looked for, which an administrator can change.
- **docs/INTEGRATION.md:** what a scheduler plug-in relies on, for anyone technical.

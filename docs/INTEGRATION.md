# Working with a scheduler

How a workload automation product (a WLA: RunMyJobs, ActiveBatch, Control-M, Tidal, ...) uses RunMyFiles. A WLA plug-in can rely on everything here. It is kept working by `autoapp/tests/test_ui_embedded.py`, and anything that changes it is recorded in [CHANGE_LOG.md](CHANGE_LOG.md).

The plan this belongs to is decision 7 in [TO-DO.md](TO-DO.md). What real WLAs allow, from their public documentation, is in [WLA_RESEARCH.md](WLA_RESEARCH.md).

## 1. Running a job

The WLA runs RunMyFiles jobs as OS jobs, with this command:

```
python3 -m engine.runner --job-key <JobKey> --instance-id <the WLA's ID for this run>
        [--run-number <restart count>] [--scheduler <its name in RunMyFiles>] [--business-date YYYY-MM-DD]
        [--mask-env NAME,NAME,...] [--log-level DETAIL|SUMMARY|DEBUG|SILENT]
```

- **Exit code:** `0` if every step succeeded, `1` if the job failed, `2` if the command line was wrong.
- **Job log:** printed on stdout, with errors on stderr, for the WLA to keep as the job's output. RunMyFiles keeps a copy with the run.
- **The job's own variables:** whatever the WLA sets in the environment of the process it starts. A step's `${Name}` finds them when nothing in RunMyFiles defines that name, and `${ENV:Name}` names one directly.
- **`--business-date`:** for a WLA that has one, such as Control-M's order date. Steps use it as `${BUSINESS_DATE:yyyyMMdd}`.
- **`--scheduler`:** the name of a scheduler registered in RunMyFiles (Schedulers page), so one RunMyFiles can serve several WLAs.
- **`--mask-env`**, or the environment variable `AUTOAPP_MASK_ENV`: the names of the job's secret parameters, separated by commas. Their values are replaced by `********` wherever they would appear in the job log. RunMyFiles cannot tell on its own which environment variables are secret.

## 2. Pages a WLA can open

Each address is relative to the RunMyFiles server, e.g. `https://autoapp.example/ui/job.html?key=DEV-LOAD`. Names and values in an address are URL-encoded as usual.

| Address | Opens |
| :--- | :--- |
| `ui/job.html?key=<JobKey>` | The job editor, showing that job. The WLA's job editor opens this for a RunMyFiles job. |
| `ui/job.html?key=<JobKey>&edit` | The same, already unlocked for editing. |
| `ui/job.html?new` | The job editor, with a new, blank job. |
| `ui/job.html?new&key=<JobKey>` | A new job, with the key the WLA suggests already filled in. |
| `...&scheduler=<name>&wla_job=<the WLA's job>` | Added to any job editor address: the WLA job this RunMyFiles job is edited for. RunMyFiles reads that job's parameters from the WLA (section 4) and shows them in the Variables panel; its preview and "Would it run?" use them. |
| `ui/operations.html?job_key=<JobKey>&instance_id=<ID>` | The Operations Log: every file one run of the job handled, with each file's trace. Either criterion can be left out. Any other search box can be given the same way, e.g. `dest_endpoint=` or `source_filename=`. |
| `ui/history.html?job_key=<JobKey>` | Job History for the job: every run, with links to each run's log and files. `instance_id=` narrows it to one run. |
| `ui/log.html?run=<RunID>` | One run's job log. |
| `ui/log.html?job_key=<JobKey>&instance_id=<ID>` | The same, found by the WLA's own instance ID, for a WLA that does not know RunMyFiles' run ID. If the instance ran more than once, the latest run. |
| `ui/summary.html?key=<JobKey>` | The job in brief, as a card: whether it would run, its steps in a line each, its endpoints and tags, its last run, and links to its pages. For a WLA that can show a web page in a panel of its own job screen. Takes `instance_id=` for one run, and `scheduler=` and `wla_job=` as the job editor does. |
| `ui/run.html?key=<JobKey>` | The Run Job page, ready to run the job. Mainly for trying jobs out without a WLA. |

### Embedded mode

Add `embed=1` to any of these addresses to show the page inside the WLA's own interface, in an iframe or a pop-up window:

- RunMyFiles' header and navigation are replaced by a thin bar, with **Open in RunMyFiles** to open the full page in a new tab.
- The job editor shows only the job it was opened for: its job selector and **New job** button are hidden.
- Links stay embedded. A page opened from an embedded page, such as the Run Job page from the job editor's **Run** button, is embedded too.
- Two more settings can be added:

| Address setting | Meaning |
| :--- | :--- |
| `theme=light` or `theme=dark` | Matches the WLA's look. Without it, the page uses the viewer's own choice. |
| `host=<origin>` | Sends the messages below only to a page from that origin, e.g. `host=https://rmj.example.com`. Recommended; without it, any page that embeds RunMyFiles receives them. |

### Messages to the WLA

An embedded page tells the window that opened it what happened, with `window.postMessage`. That is the iframe's parent, or the window that opened a pop-up. Each message is an object:

```js
{ source: "AutoApp", event: "saved", page: "job", job_key: "DEV-LOAD", ... }
```

`source` is always `"AutoApp"`, the product's original name, kept as it is so that a plug-in written against it goes on working.

| Event | Sent by | When | Also carries |
| :--- | :--- | :--- | :--- |
| `ready` | the job editor | the page has loaded | `job_key`; `exists` (false for a new job); `valid` (whether the job would run), for one that exists |
| `saved` | the job editor | a save succeeded | `job_key`; `previous_key` (when the job was renamed, otherwise null); `created`; `valid`; `problems` (what the pre-run check found); `changes` (what the save changed, in words) |
| `cancelled` | the job editor | a new job was abandoned before it was ever saved | `job_key` (the key suggested, if any) |
| `deleted` | the job editor | the job was deleted | `job_key` |

A WLA would listen for them like this:

```js
window.addEventListener("message", event => {
    if (event.origin !== "https://autoapp.example" || event.data?.source !== "AutoApp") return;
    if (event.data.event === "saved") { /* e.g. store event.data.job_key on the WLA job, close the editor */ }
});
```

A renamed job matters to the WLA. It runs the job by its key, so on a `saved` message with a `previous_key`, the WLA must update its own job.

## 3. Showing a RunMyFiles job in the WLA's own screens

`GET /api/v1/jobs/<JobKey>/summary` describes a job for a WLA to show however it likes:

- whether it is enabled, and whether it would run (`ready`), with the `problems` that would stop it;
- its `steps`, each with its order, title, step type and a `line` saying where it takes files from and puts them, e.g. `LEGAL_EXTRACTS  →  incoming`;
- the `endpoints` it uses and its `tags`;
- a `run`: the one named by `instance_id=`, or else the latest. Each has its status, times, operation counts and `links` to its job log and its operations;
- `links` to the job editor, the Operations Log and Job History, as full addresses.

It takes `scheduler=` and `wla_job=`, so "would it run" is checked with the WLA job's parameters. A WLA plug-in would ask from its own server; a page on the WLA's site cannot read RunMyFiles' API directly, as browsers keep pages to their own site's data. `ui/summary.html` shows the same, ready-made, for a WLA that would rather show a page.

## 4. RunMyFiles reading the WLA

RunMyFiles reads from a WLA through that WLA's own API, with a **connector** for its technology (`autoapp/app/connectors/`). This needs the least from a WLA plug-in: only that it opens RunMyFiles' page with the WLA job's identifier. So far a connector reads one thing, a job's parameters:

- **Registering the WLA in RunMyFiles (Schedulers page):** its name (what the runner's `--scheduler` says), its technology, its API address, and its credential as the secret variable `ApiToken`.
- `GET /api/v1/schedulers/<name>/jobs/<the WLA's job>` gives that job's parameters as the WLA gives them, with secret values left out.
- `POST /api/v1/jobs/preview` and `GET /api/v1/jobs/<JobKey>/check` take `scheduler=` and `wla_job=`, and check the job with those parameters standing for the environment it will run in; a secret stands as `********`. If the WLA cannot be read, they say so as a warning and check without them.

| Technology | Connector |
| :--- | :--- |
| `STANDIN` | The Stand-in Scheduler, [demo/scheduler_standin](../demo/scheduler_standin/README.md) |
| `RUNMYJOBS` | A draft: reads a job definition's parameters through the Inbound REST extension, by its business key (`wla_job=GLOBAL.AUTOAPP_BillingExport`), with the scheduler's `ApiToken` as `X-API-KEY`. Written to Redwood's published specification; not yet tried against RunMyJobs. See [integrations/runmyjobs](../integrations/runmyjobs/README.md). |
| `ACTIVEBATCH`, `CONTROL_M`, `TIDAL` | Not yet. Each needs its API's documentation, and a system to try it against. |

## 5. The Stand-in Scheduler

[demo/scheduler_standin](../demo/scheduler_standin/README.md) is a small WLA of its own that does all of the above from the WLA's side, for trying it without a real one. Its job editor opens RunMyFiles' embedded, its runs start the runner as an OS job, its API is the one RunMyFiles' `STANDIN` connector reads, and its job page shows RunMyFiles' summary of the job.

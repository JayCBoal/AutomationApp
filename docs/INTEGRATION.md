# Working with a scheduler

How a workload automation product (a WLA: RunMyJobs, ActiveBatch, Control-M, Tidal, ...) uses AutoApp. A WLA plug-in can rely on everything here. It is kept working by `autoapp/tests/test_ui_embedded.py`, and anything that changes it is recorded in [CHANGE_LOG.md](CHANGE_LOG.md).

The plan this belongs to is decision 7 in [TO-DO.md](TO-DO.md).

## 1. Running a job

The WLA runs AutoApp jobs as OS jobs, with this command:

```
python3 -m engine.runner --job-key <JobKey> --instance-id <the WLA's ID for this run>
        [--run-number <restart count>] [--scheduler <its name in AutoApp>] [--business-date YYYY-MM-DD]
        [--log-level DETAIL|SUMMARY|DEBUG|SILENT]
```

- **Exit code:** `0` if every step succeeded, `1` if the job failed, `2` if the command line was wrong.
- **Job log:** printed on stdout, with errors on stderr, for the WLA to keep as the job's output. AutoApp keeps a copy with the run.
- **The job's own variables:** whatever the WLA sets in the environment of the process it starts. A step's `${Name}` finds them when nothing in AutoApp defines that name, and `${ENV:Name}` names one directly.
- **`--business-date`:** for a WLA that has one, such as Control-M's order date. Steps use it as `${BUSINESS_DATE:yyyyMMdd}`.
- **`--scheduler`:** the name of a scheduler registered in AutoApp (Schedulers page), so one AutoApp can serve several WLAs.

## 2. Pages a WLA can open

Each address is relative to the AutoApp server, e.g. `https://autoapp.example/ui/job.html?key=DEV-LOAD`. Names and values in an address are URL-encoded as usual.

| Address | Opens |
| :--- | :--- |
| `ui/job.html?key=<JobKey>` | The job editor, showing that job. The WLA's job editor opens this for an AutoApp job. |
| `ui/job.html?key=<JobKey>&edit` | The same, already unlocked for editing. |
| `ui/job.html?new` | The job editor, with a new, blank job. |
| `ui/job.html?new&key=<JobKey>` | A new job, with the key the WLA suggests already filled in. |
| `ui/operations.html?job_key=<JobKey>&instance_id=<ID>` | The Operations Log: every file one run of the job handled, with each file's trace. Either criterion can be left out. Any other search box can be given the same way, e.g. `dest_endpoint=` or `source_filename=`. |
| `ui/history.html?job_key=<JobKey>` | Job History for the job: every run, with links to each run's log and files. `instance_id=` narrows it to one run. |
| `ui/log.html?run=<RunID>` | One run's job log. |
| `ui/run.html?key=<JobKey>` | The Run Job page, ready to run the job. Mainly for trying jobs out without a WLA. |

### Embedded mode

Add `embed=1` to any of these addresses to show the page inside the WLA's own interface, in an iframe or a pop-up window:

- AutoApp's header and navigation are replaced by a thin bar, with **Open in AutoApp** to open the full page in a new tab.
- The job editor shows only the job it was opened for: its job selector and **New job** button are hidden.
- Links stay embedded. A page opened from an embedded page, such as the Run Job page from the job editor's **Run** button, is embedded too.
- Two more settings can be added:

| Address setting | Meaning |
| :--- | :--- |
| `theme=light` or `theme=dark` | Matches the WLA's look. Without it, the page uses the viewer's own choice. |
| `host=<origin>` | Sends the messages below only to a page from that origin, e.g. `host=https://rmj.example.com`. Recommended; without it, any page that embeds AutoApp receives them. |

### Messages to the WLA

An embedded page tells the window that opened it what happened, with `window.postMessage`. That is the iframe's parent, or the window that opened a pop-up. Each message is an object:

```js
{ source: "AutoApp", event: "saved", page: "job", job_key: "DEV-LOAD", ... }
```

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

## 3. Planned

- **AutoApp reading the WLA job's parameters (pull).** The job editor, opened for a WLA job, will read that job's parameters through the scheduler's API, using a connector for that technology. It will show them read-only in its Variables panel, and its preview and pre-run check will use them. The address will then also carry which scheduler and which WLA job, e.g. `&scheduler=RMJ_PROD&wla_job=...`; the exact form is to be settled with the first connector.
- **Secrets from the WLA:** parameters the WLA marks secret will be masked in the job log.
- **A scheduler stand-in:** a separate small app that plays the WLA's part, for trying all of this without one.

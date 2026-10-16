# What real WLAs allow: research from public documentation

Groundwork for connecting AutoApp to a real workload automation product, gathered on 2026-10-15 from public documentation only. Nothing here has been tried against a real system. Each claim says where it comes from, and what still needs confirming on a dev tenant is listed at the end of each section.

How AutoApp's side works is in [INTEGRATION.md](INTEGRATION.md); the plan is decision 7 in [TO-DO.md](TO-DO.md).

## RunMyJobs

Sources: the RunMyJobs 2024.1 documentation pages *Extending Redwood Server Functionality with Extension Points* and *Extending Edit Pages with ObjectPageExtensionPoint* (documentation.runmyjobs.cloud), and Redwood's *Inbound REST Extension* pages (documentation.redwood.com), the latter seen only as search excerpts. 2024.1 is past end of maintenance; newer versions may differ.

### Extension Points

- An Extension Point is RedwoodScript code plus a **deployment descriptor**, an XML document saying where it hooks into the interface. It needs the license key `Module.ExtensionPoint`.
- **Visibility:** *Internal* (inside RunMyJobs: toolbar buttons, context-menu items, under an "Extensions" menu), *External* (a URL, `https://<server>/redwood/api-extension/External/<Partition>/<Name>`, reachable without authentication and running as the Extension Point's "action subject"), or *Both*.
- **Remote Extension Points** "query remote URLs": the descriptor has a `remoteextensionpoint` element whose `remoteextension` has a `target` URL, shown as a pop-up or a tab. RunMyJobs fetches this descriptor from the remote side and refreshes it every `ttl` minutes. This might let AutoApp itself provide an Extension Point with no RedwoodScript at all. The public page does not say how one is registered or what RunMyJobs sends to the target, so this is the first thing to check on a tenant.
- **Where they can appear** (`extends`): a context menu (`popupmenu`, for an object type such as `JobDefinition`, with filters on its fields), a toolbar icon (`toolbar`), the navigation bar, a viewer for job output files (`outputview`), the job chain editor's definition selector or parameter editor, and, since edit pages became extensible, an edit page (`ObjectPage`, below).
- **What they are given** (`parameters`): `model` elements send named properties of the selected object, any of `RuntimeClass.getMembers()` for its type; `constant` elements send fixed values. The code has `jcsRequest`, `jcsResponse`, `jcsSession` (the scheduler API), `jcsParameters` and a logger.
- **Content-Security-Policy:** the descriptor can carry a `csp` element with directives and sources. A support article says RunMyJobs 9.2.10 added CSP headers that block external content unless the descriptor allows it. To show AutoApp in an iframe, the descriptor would need a directive such as `frame-src` listing AutoApp's address. The exact directive names are to be confirmed.

### Extending a job definition's edit page (ObjectPage)

This is the closest match to "the WLA's job editor opens AutoApp's Job Detail page".

- An Extension Point can replace the first tab of an edit page, become its only tab, add a tab, or take the whole page. Set on `JobDefinition`, it applies to every job definition's edit page.
- **Life cycle:**
  - *Init*: given the object being edited.
  - *RetrievePage*: the first time the tab is shown. The Extension Point returns the tab's HTML, which goes straight to the browser.
  - `redwood.ep.showTab(id)` and `hideTab(id)`: called in the page's JavaScript as the user moves between tabs or saves.
  - *Persist*: just before RunMyJobs saves. It can check the changes and **refuse the save** by throwing `ExtensionPointValidationException`, with a message for the user.
- **What the page can call** on `window.parent`:
  - `redwood.epl.showDone(id)` and `hideDone(id)`: the page is ready, or has finished saving its state;
  - `redwood.epl.setChanged(true)`: marks the job definition as having unsaved changes;
  - `redwood.epl.showMessage({message, additional, severity})`: severity 1 success, 2 warning, 3 error.
- The Extension Point has a **shared scheduler session** holding the job definition as edited, unsaved changes included, while it is in control: during Init, RetrievePage until `showDone`, and Persist.

### How AutoApp would use it

1. **An "AutoApp" tab on job definitions.** The tab is added to job definitions of AutoApp's kind (filtered, for example, on a parameter or the definition type). Its RetrievePage returns a small HTML page containing an iframe of AutoApp's job editor:

   `job.html?key=<the AutoApp job key>&scheduler=<RMJ's name in AutoApp>&wla_job=<partition.name>&embed=1&theme=light&host=<RunMyJobs' address>`

   That small page relays between the two:
   - **ready:** calls `showDone`.
   - **saved:** calls `setChanged(true)`, so that saving the job definition in RunMyJobs keeps the AutoApp job key (in a parameter such as `AutoAppJobKey`) together with it. It also calls `showMessage` with AutoApp's verdict ("Saved in AutoApp: ready to run", or a warning listing the problems).
   - **hideTab:** calls `hideDone`.
2. **Persist as a safety net.** The Persist call could ask AutoApp's `GET /api/v1/jobs/<key>/summary` and warn, or refuse the save, when the AutoApp job does not exist or would not run.
3. **The Operations Log from RunMyJobs.** A context-menu Extension Point on a process (a run) opens `operations.html?job_key=…&instance_id=<the process id>&embed=1` in a pop-up. The same works for the job log (`log.html`) and for `summary.html`.
4. **Running the job.** An ordinary OS job definition (on a platform agent) runs `python3 -m engine.runner --job-key <AutoAppJobKey> --instance-id <process id> --scheduler <name> ...`. The job's parameters reach the runner as environment variables; that is from your experience of RunMyJobs, not from these pages.
5. **AutoApp reading RunMyJobs (the connector).** The Inbound REST extension reads objects by business key, e.g. `GET .../rest/v1/JobDefinition/<name>`, with an API key (header `X-API-KEY`) or a bearer token. Its full schema is a Swagger file at `rest/swagger.yml` under the extension's path. The built-in REST interface takes HTTP Basic. A RunMyJobs connector would read a job definition's parameters from there.

### To confirm on a RunMyJobs tenant

- Whether the Inbound REST extension is installed or installable, its exact path, and what a `JobDefinition` read returns: are parameters and their default values included, and how are secret ones (credentials, passwords) shown?
- Whether a *remote* Extension Point can be served by AutoApp itself, which would avoid RedwoodScript.
- The CSP directive that allows an iframe of AutoApp in a tab.
- How a job definition's own fields, such as a parameter holding the AutoApp job key, are read and changed through the shared session.
- What the process id looks like, as the `--instance-id`, and whether restarts reuse it (`--run-number`).
- That parameters really arrive as environment variables on a platform agent, and their exact names.

## Control-M

Sources: BMC's Control-M Automation API documentation (docs.bmc.com and documents.bmc.com), seen only as search excerpts, because the pages refuse automated reading; and general Control-M knowledge, marked as such.

- **Automation API:** a REST API, documented per version, with its full description (Swagger) at `<endpoint>/automation-api` on each installation.
  - **Authentication:** an API token in an `x-api-key` header (recommended since 9.0.21), or a session token from `POST /session/login`, valid for 30 minutes, sent as `Authorization: Bearer`. The API ships with a self-signed certificate.
  - **Reading definitions:** `ctm deploy jobs::get` (REST: under `/deploy/jobs`) returns the jobs and folders matching a search (server, folder, job name, with wildcards) as JSON. A job's definition includes its `Variables`.
  - **Writing definitions:** `POST /deploy` takes JSON definitions, with an optional *deploy descriptor* to transform properties per environment.
- **Running an AutoApp job:** an OS (command) job running the runner. From general Control-M knowledge, to be confirmed:
  - `%%ORDERID` is the instance ID and `%%RUNCOUNT` the run number.
  - The business date is the order date, `%%ODATE`. It is `YYMMDD`; `%%$ODATE` is `YYYYMMDD`, which is what `--business-date` takes.
  - Job variables are set in the job's environment.
- **The job editor:** nothing found yet on extending Control-M's web interface's job editor with an external page. Control-M's *Application Integrator* defines custom job types, and might be the way to an "AutoApp" job type. This needs your experience with Control-M, or BMC's documentation read in a browser.

### To confirm on Control-M

- The exact REST path and query for one job's definition, and the shape of `Variables` in the JSON.
- Whether Control-M's web interface can open an external page from a job, or from a job type made with Application Integrator.
- The order date and run variables above.

## ActiveBatch and Tidal

Not researched yet. The plan in decision 7 applies to them as to the others: an OS job that runs the runner, a connector reading a job's parameters through their API, and whatever lets their job editor open a page.

# AutoApp for RunMyJobs: a draft

How AutoApp would fit into RunMyJobs, written from Redwood's public documentation (RunMyJobs 2025.4, and the Inbound REST extension's published specification, 1.1.0.0). **None of it has been tried on a RunMyJobs system.** What the documentation states is used as stated; what it does not is marked `TO CONFIRM` in each file, and listed at the end.

The AutoApp side is in place and tested against stand-ins: [docs/INTEGRATION.md](../../docs/INTEGRATION.md). The research behind this is in [docs/WLA_RESEARCH.md](../../docs/WLA_RESEARCH.md).

## The pieces

| Piece | What it does | Confidence |
| :--- | :--- | :--- |
| [job_definition/AUTOAPP_RunJob.bash](job_definition/AUTOAPP_RunJob.bash) | The source of a BASH job definition that runs an AutoApp job: the runner with `--job-key $AutoAppJobKey --instance-id $JCS_JOB_ID --scheduler ...`. Its parameters reach the script as environment variables, so the AutoApp job's steps see them. | High. Parameters as environment variables, `JCS_JOB_ID`, and exit codes deciding Completed or Error are all documented. |
| [AutoApp_JobTab](AutoApp_JobTab) | An Extension Point adding an **AutoApp** tab to AutoApp job definitions' edit pages. It holds AutoApp's job editor, embedded, for the job's `AutoAppJobKey`, and AutoApp reads the definition's parameters to check the job. On AutoApp's *saved* message it fills in `AutoAppJobKey` for a new job, marks the definition as changed, and shows AutoApp's verdict. Before RunMyJobs saves, it asks AutoApp whether the job would run and warns if not. | Medium. The life cycle and the JavaScript calls are documented; the descriptor's `objectpage` element and several API method names are not. |
| [AutoApp_RunInAutoApp](AutoApp_RunInAutoApp) | **Files in AutoApp** and **Log in AutoApp** on a run's context menu: AutoApp's Operations Log, or its job log, for that run, in a pop-up. | Medium-high. The descriptor follows the documented context-menu example; reading the selected run is not documented. |
| AutoApp's `RUNMYJOBS` connector ([app/connectors/runmyjobs.py](../../autoapp/app/connectors/runmyjobs.py)) | Reads a job definition's parameters through the Inbound REST extension, so AutoApp's editor shows them and its checks use them. A `Password` parameter is treated as secret. | High for the request and the JSON's shape, which come from Redwood's specification; tested against a stand-in of that shape. |

## Setting it up (once there is a tenant)

1. **AutoApp knows this RunMyJobs.** On AutoApp's Schedulers page:
   - Name, e.g. `RMJ_PROD`; technology RunMyJobs.
   - API address: the Inbound REST extension's base, `https://<server>/<context>/api-extension/External/REDWOOD/Redwood_RestService/rest/v1`.
   - A secret variable `ApiToken` holding an API key (from RunMyJobs' API Key extension), for a user that can view the AutoApp job definitions.
2. **RunMyJobs can reach AutoApp, and run it.**
   - A Job Server (platform agent) on a machine with AutoApp's code.
   - Its `EnvironmentVariables` parameter sets `AUTOAPP_HOME`, `DATABASE_URL`, `AUTOAPP_WORKING_ROOT` and `AUTOAPP_API_URL`.
3. **The job definition.** A BASH job definition, e.g. `AUTOAPP_BillingExport`, whose source is `AUTOAPP_RunJob.bash`.
   - Its own parameters: `AutoAppJobKey`, `AutoAppScheduler` (`RMJ_PROD`), `AutoAppSecretParameters`, and optionally `BusinessDate`.
   - The job's own parameters, as many as wanted. Each `AUTOAPP_` job definition is a copy of this one with different parameters.
4. **The Extension Points.** Configure > Admin > Configuration > Extension Points > New, once for each folder.
   - The source goes in *Source*, the descriptor on the *Deployment Descriptor* tab, and Visibility is *Internal*.
   - Set `AUTOAPP_URL` in each source, and AutoApp's address in each descriptor's `csp`, to where AutoApp is.
   - The license needs `Module.ExtensionPoint`.

## How it looks to a RunMyJobs user

- **Making a job.** They open or create an `AUTOAPP_` job definition, and its **AutoApp** tab shows AutoApp's editor:
  - the job's steps;
  - the definition's parameters, under Variables, as "From the scheduler";
  - whether it would run.
- **Saving.** They save the steps in AutoApp, then save the job definition in RunMyJobs as usual, which keeps the AutoApp job key with it. If the AutoApp job would not run, RunMyJobs warns them before saving.
- **Running.** The job runs like any other. Its output is AutoApp's job log, and it ends in Completed or Error by the runner's exit code.
- **Looking afterwards.** On a run, **Files in AutoApp** shows every file it handled, with each file's route, and **Log in AutoApp** shows its log.

## TO CONFIRM on a tenant

In the order they would block progress:

1. The Inbound REST extension: installed, its exact base address, and what `GET /JobDefinition/<partition>.<name>` returns for a real definition. Especially:
   - whether `DefaultExpression` is the literal default or an expression;
   - what a `Password` parameter's `DefaultExpression` shows.
2. The `objectpage` element of the deployment descriptor: its exact name and attributes, and whether a filter can limit it to `AUTOAPP_` definitions.
3. How the Extension Point's code reads the request type, the invocation ID and the definition being edited, and the parameter methods (`getJobDefinitionParameterByName`, `getDefaultExpression`, `setDefaultExpression`).
4. The Content-Security-Policy directive that lets the tab show AutoApp in an iframe.
5. How the context-menu code reads the selected run, and a run's parameter values.
6. Whether a *remote* Extension Point could be served by AutoApp itself, which would replace the RedwoodScript above with something AutoApp keeps.
7. What restarts do: a new `JCS_JOB_ID`, or the same one (then the runner's `--run-number` matters).

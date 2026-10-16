# The Stand-in Scheduler

A deliberately small workload automation product (WLA), for trying RunMyFiles' scheduler integration without a real one. It is not part of RunMyFiles. It is a separate application, with its own database and its own look, and it uses RunMyFiles only the way a real WLA would, as described in [docs/INTEGRATION.md](../../docs/INTEGRATION.md):

- **Job definitions with parameters.** It runs a RunMyFiles job by starting RunMyFiles' runner as an OS job. The job's parameters go into the environment, and the names of the secret ones go in `AUTOAPP_MASK_ENV`, so the job log masks their values.
- **Edit in RunMyFiles.** Opens RunMyFiles' job editor embedded, for the RunMyFiles job it runs (or a new one named after it), and listens for the editor's messages. When RunMyFiles saves a new job, the stand-in learns its key.
- **Its parameters, as RunMyFiles sees them.** RunMyFiles reads them through the stand-in's API, using its connector for the `STANDIN` technology, and shows them in the editor as "From the scheduler".
- **In RunMyFiles.** The job page shows RunMyFiles' summary of the RunMyFiles job: whether it would run, its steps, its last run. The stand-in's server asks RunMyFiles' API for it, as a WLA plug-in would.
- **Submit and Runs.** Runs a job now, then shows each run's output and exit code, with **Operations in RunMyFiles** for the files that run handled.

## Running it

With RunMyFiles' server running (`autoapp_server`, port 8000), in another terminal:

```bash
cd ~/projects/AutomationApp/CodeRepo
source dev_env.sh
cd demo/scheduler_standin
python3 -m uvicorn standin.app:app --port 8100     # or, with dev_env.sh sourced: standin_server
```

Then open `http://localhost:8100/`.

RunMyFiles knows it as the scheduler `STANDIN` (Schedulers page), at `http://localhost:8100`, with the token in its `ApiToken` variable. The sample data registers it that way.

To try it:
1. **New job**: a name such as `BILLING_EXPORT`, the RunMyFiles job `DEV-BILLING-INVOICE_EXPORT`, a parameter or two (tick Secret on one), and **Save**.
2. **Edit in RunMyFiles**: the job editor, inside the stand-in, with the parameters under Variables.
3. **Submit**: the run's output, then **Operations in RunMyFiles**.

## Settings

| Environment variable | Default | Meaning |
| :--- | :--- | :--- |
| `STANDIN_DATABASE_URL` | `sqlite:///standin.db` in this folder | Its own database |
| `STANDIN_TOKEN` | `standin-dev-token` | The token its API wants; the same as RunMyFiles' `ApiToken` variable on the scheduler |
| `STANDIN_NAME` | `STANDIN` | What RunMyFiles calls it: the runner's `--scheduler` |
| `STANDIN_AUTOAPP_URL` | `http://localhost:8000` | The RunMyFiles server, for its pages and the runner's `--api-url` |
| `STANDIN_AUTOAPP_DIR` | this repository's `autoapp` folder | Where the runner is |

The runner it starts gets the rest of its environment, including `DATABASE_URL` and `AUTOAPP_WORKING_ROOT`, which is why it is started where `dev_env.sh` has been sourced.

Its API wants `Authorization: Bearer <token>` from other programs, such as RunMyFiles' connector. Its own pages are let through: they are the same origin, and, like RunMyFiles', have no user accounts.

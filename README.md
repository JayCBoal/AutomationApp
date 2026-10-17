# AutoApp

AutoApp is a testbed and demonstrator for scheduler features worth having in RunMyJobs (Redwood). Each feature is built far enough to show how it would look and behave, and to check that it does. The first is workflows: jobs with dependencies between them, designed and run in AutoApp. See [docs/PROJECT_GOALS.md](docs/PROJECT_GOALS.md).

AutoApp's foundation is its jobs: defined steps instead of scripts, with a structured record of every file operation, tied to a register of the places files come from and go to, so a file's path through the system can be traced.

On 2026-10-16 that foundation was forked into a separate product, RunMyFiles, which leaves sequencing to an existing scheduler. AutoApp plays the scheduler instead. Some pages of the documentation still describe it as RunMyFiles, from before the fork.

## Status

Early rewrite of a 2024 prototype. Working end to end and covered by tests: local file copy and move steps, a record of every file handled, a file trace, and the first page of the web interface (the Operations Log). Most other planned features are not built yet. See:

- [docs/PROJECT_GOALS.md](docs/PROJECT_GOALS.md): what the project is for
- [docs/PROJECT_BLUEPRINT.md](docs/PROJECT_BLUEPRINT.md): how it works, with what is built and what is only planned
- [docs/DB_SCHEMA.md](docs/DB_SCHEMA.md): database schema diagrams
- [docs/PYTHON_MODEL.md](docs/PYTHON_MODEL.md): diagrams of the ORM classes and the Python modules
- [docs/UI_VISION.md](docs/UI_VISION.md): what the web interface should contain; the Job Search and Operations Log pages are built
- [docs/TO-DO.md](docs/TO-DO.md): open decisions and the work queue
- [docs/CHANGE_LOG.md](docs/CHANGE_LOG.md): design changes over time

## Quick start

Requires Python 3.11 or later.

```bash
python3 -m venv .venv                     # once: a private Python environment for the project
source .venv/bin/activate                 # in every new terminal
pip install -r requirements-dev.txt       # once

python3 -m pytest -v          # run the tests
python3 demo/run_demo.py      # seed a database, run a sample job, show the results and a file trace
```

On Debian or ChromeOS Linux, install the prerequisites first: `sudo apt-get install git python3-venv python3-pip`.

The demo writes everything it produces to `demo/output/run_<timestamp>/` so you can look at the files and the telemetry yourself.

To keep the files the tests produce: `python3 -m pytest --basetemp=_test_out`.

The browser tests of the web interface need Chromium (`sudo apt-get install chromium`); without it they are skipped and say so.

By default each test builds its own throwaway SQLite database, so the tests need no database server. To run the same tests against MariaDB, name a database kept for testing. Everything in it is deleted, and the tests refuse to run unless its name contains "test":

```bash
cd autoapp
AUTOAPP_TEST_DATABASE_URL="mysql+pymysql://@localhost/autoapp_test?unix_socket=/run/mysqld/mysqld.sock" python3 -m pytest
```

## A development database

```bash
cd autoapp
python3 create_dev_db.py
```

This creates `autoapp/autoapp.db` (SQLite) with the sample data from `SQL/Seed_Sample_Data.sql`: three applications, four endpoints and two pairs of jobs. One pair copies a file from one application to another. The other queries a sample sales database, zips the results, sends them on and unpacks them at the other end. The sales database (`SQL/Sample_Sales_Data.sql`) is built as SQLite at `/tmp/autoapp_sample/sales.db`. It prints the commands to run the jobs and look at the result. It never overwrites an existing database.

After updating AutoApp, an existing development database may lack tables or columns the new version needs. The server says exactly what is missing, in its log when it starts and on any page that fails. The simplest fix is to delete `autoapp.db` and run `create_dev_db.py` again.

For MariaDB, run `SQL/Create_Tables.sql` and then `SQL/Seed_Sample_Data.sql`, and point `DATABASE_URL` at the database, for example `mysql+pymysql://user:password@dbhost/autoapp`. For the sales database, create a database (e.g. `autoapp_sales`), run `SQL/Sample_Sales_Data.sql` in it, and set the `SalesDbUrl` variable of `BILLING_APP` to its URL. The list of step types and their parameters is filled in when the API server starts, or by `python3 -m app.catalog`. After changing the models, regenerate the table script with `python3 SQL/generate_ddl.py`.

## Running a job

```bash
cd autoapp
DATABASE_URL=sqlite:///./autoapp.db \
python3 -m engine.runner \
    --job-key DEV-LEGAL-CLIENT_EXTRACT \
    --instance-id 20261011_0001 \
    --working-root /data/autoapp/work \
    --spool-dir /data/autoapp/spool \
    --api-url http://autoapp-server:8000
```

Exit code `0` means every step succeeded; `1` means the job failed.

Optional: `--run-number N` for schedulers that reuse an instance ID across restarts, and `--scheduler NAME` where more than one scheduler issues instance IDs.

The job log says what each step did, file by file. `--log-level SUMMARY` reduces it to one line per step, `SILENT` to errors only, and `DEBUG` adds troubleshooting detail. A single step can set its own level with a `LogLevel` parameter.

`--api-url` is where the runner sends its record of the run. Without it, or if the API cannot be reached, the record stays in the spool folder until this is run:

```bash
python3 -m engine.spool_delivery --spool-dir /data/autoapp/spool --api-url http://autoapp-server:8000
```

## Running the server and the web interface

```bash
cd autoapp
DATABASE_URL=sqlite:///./autoapp.db AUTOAPP_WORKING_ROOT=/data/autoapp/work \
python3 -m uvicorn app.main:app --port 8000
```

`AUTOAPP_WORKING_ROOT` is the folder that holds the jobs' working folders, the same one the runner is given. The server needs it to check a job's file locations.

While developing, add `--reload` to that command. The server then restarts itself whenever the code changes. Without it, a server started before an update keeps running the old code while serving the new pages, and the pages fail in confusing ways.

Then open `http://localhost:8000/` in a browser:

- **Jobs** finds jobs and shows what each one uses, how its last run went, and whether it would run now: "Ready to run" in green, or a red "Check" link that lists what is wrong. A job's key opens its detail page, the job editor: **Edit** unlocks it, and **Submit** saves the job with its steps and parameters. **New job** starts a blank one.
- **Operations Log** searches every file handled and shows any file's trace.

Pages that are not built yet appear greyed out in the navigation bar.

The web interface is plain HTML, CSS and JavaScript in `autoapp/ui/`, with no build step: edit a file and reload the page. It reads everything through the REST API, which is described at `http://localhost:8000/docs`.

## Trying the demo jobs

The quickest way is the **Run Job** page in the web interface: choose a job and press **Run**. The server runs it the way a scheduler would and shows its job log as it goes. Every run's log can be opened again from **Job History**. The commands below do the same from a terminal.

The sample data has two pairs of jobs. Each pair hands files from one application to another, and the second pair shows the newer step types. Run them in this order: each second job picks up what the first one delivered. On the development machine, start in a terminal where `dev_env.sh` has been sourced, with the server running in another (`autoapp_server`), so each run's record goes straight into the database.

```bash
cd autoapp
# Files from the legal application to billing: copy, archive, move
python3 -m engine.runner --job-key DEV-LEGAL-COLLECT_AND_DELIVER --instance-id 3001 --working-root $AUTOAPP_WORKING_ROOT
python3 -m engine.runner --job-key DEV-BILLING-LOAD              --instance-id 3002 --working-root $AUTOAPP_WORKING_ROOT

# Billing reports to finance: query the sales database, check, zip and deliver; then pick up, unzip, check, keep
python3 -m engine.runner --job-key DEV-BILLING-INVOICE_EXPORT    --instance-id 3003 --working-root $AUTOAPP_WORKING_ROOT
python3 -m engine.runner --job-key DEV-FINANCE-LOAD_REPORTS      --instance-id 3004 --working-root $AUTOAPP_WORKING_ROOT
```

Each command ends with `Job '...' completed successfully.` and exit code 0.

- The first job copies `Legal_Batch_*.csv` from `/tmp/autoapp_sample/legal_app/outbox`, leaving them there, so the pair can be run again at any time.
- The export job can also be run again at any time: it replaces the day's files. The finance job needs a fresh archive each time (it fails, saying it found nothing, if the inbox is empty), so run the export job before it again.

What to look at afterwards:

- **The files.** The export job's results end up in `/tmp/autoapp_sample/work/DEV-FINANCE-LOAD_REPORTS/reports/<today>/`: `Open_Invoices_<today>.csv`, the 12 open and overdue invoices with a line of column names, and `Payments_<today>.csv`. The archive itself is kept in that job's `archive/` folder, and the finance inbox, `/tmp/autoapp_sample/finance_app/inbox`, is empty again.
- **The job log**, printed by each command: every step, every file, and what each value resolved to. The finance job's `OlderThanDays: ${ReportRetentionDays}  (resolved: 30)` comes from the `Finance` tag, through `Finance / Reporting`. The database's password shows as `***`.
- **Job History** in the web interface: one row per run, with its status.
- **Operations Log**: one row per file per step. Type `Open_Invoices` in Filename and choose **Trace** on any row. The trace runs from the query that wrote the file (`SQL_EXPORT`, from "Database query") through the check, into the archive, to finance, out of the archive, and on to the archive folder.
- **The sales database**, to compare with the CSV: `sqlite3 /tmp/autoapp_sample/sales.db "SELECT invoice_no, status FROM invoices WHERE status <> 'PAID'"`, or on MariaDB the `autoapp_sales` database in DBeaver.

If the server was not running, the runs' records are waiting in `autoapp/spool/`. Start the server and run `python3 -m engine.spool_delivery`, or load them straight into the database with `env -u AUTOAPP_API_URL python3 -m engine.spool_delivery`.

## Using AutoApp from a scheduler

[docs/INTEGRATION.md](docs/INTEGRATION.md) describes how a workload automation product runs AutoApp jobs, the AutoApp pages it can open inside its own interface (add `embed=1` to the address), the messages those pages send it, and how AutoApp reads a WLA job's parameters.

[integrations/runmyjobs](integrations/runmyjobs/README.md) is a draft of the RunMyJobs side, written from Redwood's public documentation and not yet tried on RunMyJobs.

[demo/scheduler_standin](demo/scheduler_standin/README.md) is a small stand-in WLA that does all of this, for trying it without a real one: `python3 -m uvicorn standin.app:app --port 8100` from that folder, then `http://localhost:8100/`.

## Layout

```
autoapp/
  app/        FastAPI service: database models, schemas, routes
  engine/     runner, variable scope engine, step handlers, telemetry spool and delivery
  ui/         web interface: static pages that call the API
  tests/      pytest suite
demo/         run_demo.py and its output
docs/         goals, blueprint, to-do, change log
SQL/          MariaDB table script (generated from the models) and sample data
```

## Background

The original 2024 design document: https://docs.google.com/document/d/1wydled84CL3JP8SSYwSldHPzkjcNwxkAeCwmzLEO44o/edit?usp=drive_link

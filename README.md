# AutoApp (AutomationApp)

AutoApp is a batch-processing execution framework that keeps *what a job does* separate from *when it runs*.

A workload automation scheduler (Control-M, AutoSys, ActiveBatch, RunMyJobs, cron) decides when a job runs and passes AutoApp two things: a job key and its own instance ID. AutoApp looks up the job's steps and parameters in its own database, runs them, and returns an exit code. Because the job definitions live outside the scheduler, changing schedulers does not mean rewriting jobs.

It also keeps a structured record of every file operation, tied to a register of the places files come from and go to, so a file's path through the system can be traced.

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

This creates `autoapp/autoapp.db` (SQLite) with the sample data from `SQL/Seed_Sample_Data.sql`: two applications, three endpoints and two jobs that hand a file from one to the other. It prints the commands to run the jobs and look at the result. It never overwrites an existing database.

After updating AutoApp, an existing development database may lack tables or columns the new version needs. The server says exactly what is missing, in its log when it starts and on any page that fails. The simplest fix is to delete `autoapp.db` and run `create_dev_db.py` again.

For MariaDB, run `SQL/Create_Tables.sql` and then `SQL/Seed_Sample_Data.sql`, and point `DATABASE_URL` at the database, for example `mysql+pymysql://user:password@dbhost/autoapp`. The list of step types and their parameters is filled in when the API server starts, or by `python3 -m app.catalog`. After changing the models, regenerate the table script with `python3 SQL/generate_ddl.py`.

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

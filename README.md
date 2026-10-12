# AutoApp (AutomationApp)

AutoApp is a batch-processing execution framework that keeps *what a job does* separate from *when it runs*.

A workload automation scheduler (Control-M, AutoSys, ActiveBatch, RunMyJobs, cron) decides when a job runs and passes AutoApp two things: a job key and an instance ID. AutoApp looks up the job's steps and parameters in its own database, runs them, and returns an exit code. Because the job definitions live outside the scheduler, changing schedulers does not mean rewriting jobs.

It also keeps a structured record of every file operation, tied to a register of the places files come from and go to, so a file's path through the system can be traced.

## Status

Early rewrite of a 2024 prototype. The core path works end to end for local file copy and move steps and is covered by tests. Most other planned features are not built yet. See:

- [docs/PROJECT_GOALS.md](docs/PROJECT_GOALS.md): what the project is for
- [docs/PROJECT_BLUEPRINT.md](docs/PROJECT_BLUEPRINT.md): how it works, with what is built and what is only planned
- [docs/DB_SCHEMA.md](docs/DB_SCHEMA.md): database schema diagrams
- [docs/PYTHON_MODEL.md](docs/PYTHON_MODEL.md): diagrams of the ORM classes and the Python modules
- [docs/UI_VISION.md](docs/UI_VISION.md): what the web interface should contain; not built yet
- [docs/TO-DO.md](docs/TO-DO.md): open decisions and the work queue
- [docs/CHANGE_LOG.md](docs/CHANGE_LOG.md): design changes over time

## Quick start

Requires Python 3.11 or later.

```bash
pip install -r requirements-dev.txt

python3 -m pytest -v          # run the tests
python3 demo/run_demo.py      # seed a database, run a sample job, show the results
```

The demo writes everything it produces to `demo/output/run_<timestamp>/` so you can look at the files and the telemetry yourself.

To keep the files the tests produce: `python3 -m pytest --basetemp=_test_out`.

## Running a job

```bash
cd autoapp
DATABASE_URL=sqlite:///./autoapp.db \
python3 -m engine.runner \
    --job-key DEV-LEGAL-CLIENT_EXTRACT \
    --instance-id 20261011_0001 \
    --working-root /data/autoapp/work \
    --spool-dir /data/autoapp/spool
```

Exit code `0` means every step succeeded; `1` means the job failed.

## Layout

```
autoapp/
  app/        FastAPI service: database models, schemas, routes
  engine/     runner, variable scope engine, step handlers, telemetry spooler
  tests/      pytest suite
demo/         run_demo.py and its output
docs/         goals, blueprint, to-do, change log
SQL/          MariaDB DDL and seed script (currently out of step with the models; see TO-DO)
```

## Background

The original 2024 design document: https://docs.google.com/document/d/1wydled84CL3JP8SSYwSldHPzkjcNwxkAeCwmzLEO44o/edit?usp=drive_link

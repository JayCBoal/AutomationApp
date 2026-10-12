# Project Goals

## Vision

AutoApp is a lightweight execution framework and metadata store for batch jobs that works with any workload automation (WLA) scheduler, and ultimately inside it: the people who build, administer and operate jobs should not have to leave their scheduler to use AutoApp.

It separates **payload logic** (parameters, steps, credentials, logging) from **sequencing logic** (schedules, dependencies, SLAs). The scheduler owns sequencing. AutoApp owns the payload. This removes lock-in to a particular scheduler such as ActiveBatch, Control-M or AutoSys.

These are goals. For what is actually built, see [PROJECT_BLUEPRINT.md](PROJECT_BLUEPRINT.md).

## Goals

### 1. Scheduler independence

- The scheduler passes minimal runtime metadata: a job key and an instance ID.
- Parameters, endpoints, credentials and step definitions are read from the AutoApp database at run time.
- Switching or upgrading schedulers requires no change to job logic.

### 2. Works inside the scheduler, not just beside it

- Making job developers, WLA administrators and operators work in two separate applications is a barrier to adoption. The end state is that AutoApp's functions are reached from within the scheduling product.
- Job steps, parameters, variables and endpoints can be viewed and edited from the scheduler's own interface.
- Run results, operation history and file traces are visible where operators already look at job output.
- Everything AutoApp does is therefore available through its API. AutoApp's own web interface is one client of that API, not the only way in.
- Running standalone, beside a scheduler that has no integration, remains supported.

### 3. Standard execution

- One runner script executes most jobs, dispatching each step to a handler for its step type.
- New step types are added by writing a handler, without touching the runner.
- Values are bound late: paths, patterns and credentials are resolved when the job runs, through scoped variables.

### 4. Standard logging and file traceability

- Every operation (copy, transfer, SQL, API call) is recorded as structured data, not just console output.
- A register of endpoints records where files enter and leave, and which application or external entity each belongs to.
- Together these answer: where did this file come from, what handled it, and where was it delivered?

### 5. Asynchronous process support

- Long-running external tasks and third-party callbacks are tracked without holding a scheduler thread.
- Polling jobs and callbacks detect completion and trigger downstream work.

### 6. Central metadata management

- A relational database holds applications, entities, sites, credentials, jobs, steps, endpoints, variables and tags.
- A web interface lets users search, view and edit job definitions and operational history.
- Non-technical users can request automation through the interface.

### 7. Safe by default

- Secrets are encrypted at rest or held in an external vault, and never returned in plain text.
- Agents in restricted network zones do not connect directly to the database.

## Non-goals

- Replacing the scheduler. AutoApp does not decide when jobs run or in what order.

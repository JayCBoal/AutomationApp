# AutoApp Architecture & Project Blueprint

## 1. Executive Summary & Vision

**AutoApp (Automation App)** is a lightweight, workload-automation-agnostic execution framework and metadata management system[cite: 1, 2]. 

Its primary purpose is to **decouple execution payload logic** (parameters, step execution, target credentials, and operational logging) from **sequencing and orchestration logic** (time schedules, SLAs, agent distribution, and upstream/downstream dependencies)[cite: 1, 2].

By offloading job step definitions and dynamic parameters to a central database (`AutomationDB`), AutoApp eliminates vendor lock-in with enterprise Workload Automation (WLA) platforms (e.g., BMC Control-M, Redwood RunMyJobs, AutoSys, ActiveBatch) while streamlining job definitions across environments[cite: 1, 2].

---

## 2. Core Architecture & Execution Flow

AutoApp sits alongside standard WLA scheduling engines, utilizing native WLA agents to execute scripts while drawing execution steps dynamically from the database[cite: 1, 2].

+-----------------------------------------------------------------------+
|                         WLA Scheduler Engine                          |
|             (e.g., BMC Control-M, RunMyJobs, AutoSys)                 |
|                                                                       |
|  * Manages macro-scheduling, SLAs, & dependency sequencing.          |
|  * Invokes AutoApp script via native Agent with standard CLI metadata.|
+-----------------------------------+-----------------------------------+
| (Executes via Agent)
v
+-----------------------------------------------------------------------+
|                         AutoApp Execution Engine                      |
|                                                                       |
|  1. Resolves dynamic variables and environment configurations.        |
|  2. Fetches step definitions & parameters (Pull via DB/API or Push).  |
|  3. Dispatches execution to Factory Step Handlers (SFTP, SQL, REST).  |
|  4. Logs discrete business events & returns standard OS exit code.    |
+-----------------------------------+-----------------------------------+
|                                 |
v                                 v
+-----------------------------------+   +-------------------------------+
|         AutomationDB              |   |          AutoApp UI           |
|  (MariaDB / Modern ORM Layer)     |   |         (Web Portal)          |
|                                   |<--+                               |
|  * Process & Job Definitions      |   |  * Parametric Job Management  |
|  * Tag Taxonomy & Variable Scopes |   |  * Operations Audit Viewer    |
|  * Encrypted Credentials & Sites  |   |  * Asynchronous Tracking      |
|  * Operations & Audit Tracking    |   |                               |
+-----------------------------------+   +-------------------------------+


### Key Execution Characteristics
* **Late-Binding Parameters:** Payload values, credentials, target directories, and file patterns are evaluated dynamically at runtime[cite: 1, 2].
* **Standardized Operations Audit:** Every file copy, API invocation, or SQL execution emits structured business operations records rather than relying on raw console stdout/stderr[cite: 1, 2].
* **Asynchronous Process Model:** Tracks long-running external webhooks and third-party tasks via dedicated tracking tables (`AsyncInstances` / `AsyncParentInstances`) and polling callbacks without consuming scheduler execution threads[cite: 1, 2].

---

## 3. Database Schema Overview & MasterObjects Supertype Pattern

The relational datastore (`AutomationDB`) utilizes a **Global Supertype Pattern (`MasterObjects`)** implemented via Joined-Table / Class-Table Inheritance in the ORM layer[cite: 1, 3, 4]:

* **Domain Entities (`MasterObjects` Supertype):** Core business entities (`Applications`, `Entities`, `Sites`, `Credentials`, `Tags`, `Processes`, `Jobs`) inherit directly from `MasterObjects`[cite: 3, 4]. They use `MasterObject_id` as both their **Primary Key** and **Foreign Key** pointing back to `MasterObjects(id)`[cite: 3, 4]. This structural design provides:
  * A globally unique identifier across all core domain entities in the platform[cite: 3, 4].
  * Polymorphic relationship mapping for custom key-value pairs (`Variables` table) and taxonomy tags (`TagAssignments` table)[cite: 3, 4].
  * Direct compatibility with ORM polymorphic inheritance models (SQLAlchemy / SQLModel)[cite: 3, 4].
* **Hierarchy & Execution Support Tables:** High-volume operational and execution tables (`Operations`, `Audits`, `JobSteps`, `JobStepParameters`, `StepTypes`, `StepDefinitions`, `AsyncInstances`) retain standard auto-incrementing local IDs or UUIDs to maintain high write performance and decouple runtime execution logs from domain registry management[cite: 3, 4].
* **Unified Endpoints Model:** Target paths, transfer directories, and filename patterns are consolidated into a single `Endpoints` model (replacing legacy separate `Sources` and `Deliveries` tables)[cite: 4]. Endpoints use an `EndpointType` ENUM (`'SOURCE'`, `'DELIVERY'`) and link technical destinations to parent `Sites` and `Entities`[cite: 4].

---

## 4. Planned & Architecture Enhancements

### A. Hierarchical Tag Taxonomy & Dynamic Variable Scoping
Variables resolve dynamically through a deterministic scope evaluation cascade managed by the `ScopeResolutionEngine`[cite: 3]:

$$\text{SYS} \longrightarrow \text{ENTITY} \longrightarrow \text{APP} \longrightarrow \text{PROC} \longrightarrow \text{TAG} \longrightarrow \text{JOB} \longrightarrow \text{STEP}$$

* **Nested Inheritance & Explicit Scope Syntax:** Supports universal `${...}` interpolation for implicit cascade lookup (`${var}`), parent/associated scope targeting (`${APP.var}`), explicit entity targeting (`${ENTITY:Name.var}`), and dynamic runtime system macros (`${SYS:YYYYMMDD}`)[cite: 3, 4].
* **Direct Job Resolution:** Schedulers pass a single `Job_MasterObject_id` or `JobKey` at execution time; AutoApp automatically resolves upward parent `Process`, `Application`, and `Entity` context in a single evaluation pass[cite: 3, 4].

### B. Dual Payload Delivery Model (Pull vs. Push)
* **Pull Model (Default / Standard Edge Agents):** Agents fetch step configurations at execution time over HTTPS (Port 443) via `POST /api/v1/jobs/init`, distributing system load and bypassing scheduler bottlenecks[cite: 1, 2, 3].
* **Push Model (Air-Gapped / Ephemeral Nodes):** For zero-trust DMZ nodes or ephemeral containers, the WLA scheduler pre-fetches the payload via the AutoApp API and pushes a signed JSON payload directly to the executing agent[cite: 1, 2, 3].

### C. ORM Modernization (SQLAlchemy / SQLModel)
* Modernized direct database driver interactions into a **SQLAlchemy ORM** layer[cite: 1, 3, 4].
* Provides database portability across **MariaDB**, **PostgreSQL**, **Microsoft SQL Server (MSSQL)**, **SQLite**, and **Oracle Database**[cite: 1, 3].
* Enables strongly typed models, compile-time validation, and parameterized query execution to eliminate SQL injection risks[cite: 1].

### D. Modular Plugin / Step Factory Pattern
* Procedural execution loops in runner scripts are refactored into an object-oriented **Step Handler Factory** (`engine/handlers/`)[cite: 1, 2, 3, 4].
* Step handlers (`SFTPHandler`, `SQLHandler`, `RESTHandler`, `FileOpHandler`) inherit from a common `BaseStepHandler` class, isolating step-specific logic and allowing seamless custom extensions[cite: 1, 2, 3, 4].

### E. Security & Secrets Vault Integration
* Securing the `Credentials` and `Sites` tables using AES-256 encryption at rest[cite: 1].
* Adding runtime connectors to enterprise secrets vaults (e.g., HashiCorp Vault, AWS Secrets Manager) to resolve passwords and API tokens dynamically without persisting plain text[cite: 1].

### F. REST API Backend & Frontend Modernization
* Building a **FastAPI** backend (`app/main.py`) to serve as the unified REST layer between the database, web interface, and remote edge runners[cite: 1, 3, 4].
* Modernizing the web user interface into an interactive portal featuring dynamic variable editors and tag managers bound to `MasterObject_id`[cite: 1, 3, 4].

---

## 5. Summary Roadmap

| Phase | Core Deliverables | Focus Areas |
| :--- | :--- | :--- |
| **Phase 1: Core REST API & Context Engine** | FastAPI initialization routes, Scope resolution engine, variable interpolation | `POST /api/v1/jobs/init`, `${...}` placeholder resolution, scope precedence[cite: 3] |
| **Phase 2: Seed Data & Step Catalog** | `StepTypes`, `StepDefinitions`, seed `MasterObjects` insert scripts | Base step catalog, parameter signature seeding, initial entity/tag variables[cite: 3, 4] |
| **Phase 3: Core Execution Runner (MVP)** | Modular Step Factory, parameter interpolation, CLI runner (`runner.py`) | Handlers (`SFTP`, `SQL`, `REST`, `File`), end-to-end execution demonstrator[cite: 1, 3, 4] |
| **Phase 4: Web UI & Backend CRUD** | Universal Variables Editor, Universal Tagging picker, transactional controllers | `MasterObjects` transactional controllers, interactive web portal[cite: 1, 3, 4] |
| **Phase 5: Resilient Telemetry & Spooling** | Telemetry REST API, client wrapper, offline disk spooler daemon | Real-time event streaming (`/telemetry/ops`), offline `.jsonl` buffer, batch drain[cite: 3, 4] |
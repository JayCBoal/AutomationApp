# Project Goals & Architectural Overview: AutoApp / AutomationDB

## 1. Project Vision & Core Objective
The primary goal of **AutoApp (Automation App)** is to provide a lightweight, engine-agnostic Workload Automation (WLA) execution framework and metadata management system. 

By separating **payload logic** (parameters, operational steps, logging) from **sequencing logic** (time schedules, upstream/downstream dependencies), AutoApp eliminates vendor lock-in with enterprise schedulers (e.g., ActiveBatch, BMC Control-M, AutoSys).

---

## 2. Key Architecture Pillars

### A. WLA Engine Independence
* Schedulers pass minimal runtime metadata (`Process Name`, `Job Name`, `Instance ID`).
* Payload parameters, target endpoints, credentials, and step definitions are retrieved dynamically from `AutomationDB` at runtime.
* Allows switching or upgrading scheduler tools without rewriting internal job logic.

### B. Standardized Execution & Logging Framework
* Universal Python execution driver handles job step parsing and execution using modular step handlers (Factory Pattern).
* Operations and data movement (copies, transfers, API calls) are logged to structured files and ingested into central audit tables (`Operations`, `Audits`).
* Consistent logging across all tasks simplifies troubleshooting and compliance monitoring.

### C. Asynchronous Process Support
* Decouples long-running external tasks or third-party webhooks from active scheduler threads.
* Tracks execution via dedicated status tracking tables (`AsyncInstances` / `AsyncParentInstances`).
* Employs callback hooks and dedicated polling jobs to track completion and trigger downstream dependent tasks.

### D. Centralized Metadata Management (UI & DB)
* Backed by a relational datastore (`MariaDB`) housing entities, applications, sites, processes, and parameters.
* Web interface (`AutoApp UI`) for searching, viewing, configuring, and updating workflow definitions and operational logs.
* Enforces standard naming conventions for automated process definitions.

---

## 3. High-Level Technical Architecture
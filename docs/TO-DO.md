# Technical Action Plan & TO-DO List

## Architecture & Infrastructure Open Questions

### 1. Isolated Network Zones & DMZ Payload Delivery
* **Issue:** Direct database driver connections (TCP ports 3306/1433) from remote runner agents in isolated DMZ or zero-trust network segments back to `AutomationDB` violate core security standards, increase credential sprawl, and risk connection pool exhaustion.
* **Evaluated Alternatives:**
  * **HTTPS REST API Pull (Standard Agent Zones):** Edge runners call a central API service (`FastAPI`/`Flask`) over Port 443 to pull execution configurations and push step results.
  * **WLA Pre-Fetch Push Model (Isolated/DMZ Zones):** The WLA scheduler fetches job payload JSON from the core API at dispatch time and pushes it down through the WLA agent's existing encrypted pipe.
* **Status:** Moving toward a hybrid model (API Pull for standard agents; WLA Pre-Fetch Push for isolated DMZ zones).

---

### 2. Operations & History Logging Architecture
* **Issue:** Local flat-file parsing on execution disk (`.ops` JSON logs parsed by legacy scripts) is not a scalable primary operational pattern for enterprise scale.
* **Updated Scope:** Evaluate replacing local file parsing with direct REST API event streaming (`POST /api/v1/telemetry/ops`). Retain local file spooling (`.jsonl`) strictly as an offline retry buffer when central network connectivity is degraded.
* **Status:** In Review.

---

## Action Items & TO-DO List

### Phase 1: Core Engine & Telemetry Pipeline
* [x] **Process-Isolated Telemetry Client (`engine/telemetry_client.py`):**
  * Implemented zero-latency, thread-protected local file spooler writing to unique `.jsonl.tmp` files.
  * Added atomic file renaming (`.jsonl.tmp` -> `.jsonl`) upon context exit to signal completion.
  * Added support for operation logs, batch operations, and system audits (`log_audit`).
* [x] **File Handler Implementation (`engine/handlers/file_handler.py`):**
  * Implemented file copy and move operations with glob pattern support.
  * Added automatic destination directory creation (`CreateFolder`).
  * Tracked byte-level transfer metrics and structured operation result metadata.
* [x] **Handler Registry (`engine/handlers/__init__.py`):**
  * Created factory lookup (`HANDLER_REGISTRY`) mapping string step types (`FILE_OP`, `COPY_FILES`) to concrete handler classes.

### Phase 2: Execution Runner & Resolver
* [x] **Robust Test Path Resolver:**
  * Standardized test script header dynamically resolving project root regardless of test subdirectory location.
* [ ] **Parameter Interpolation Engine (`engine/resolver.py`):**
  * Build recursive dictionary/string walker to substitute `${variable_name}` placeholders.
* [ ] **Main CLI Runner (`runner.py`):**
  * Build execution entry point accepting `--job`, `--instance-id`, `--step-type`, `--params`, and `--vars`.
  * Wire up parameter resolution, handler factory lookup, and telemetry spooling context.

### Phase 3: Database & API Alignment (Next Session Agenda)
* [ ] **Run Core DDL Script:** Apply database schema changes and verify polymorphic MasterObject constraints.
* [ ] **Seed Data Catalog:** Populate standard step types (`Copy_Files`, `SQL_Exec`, `REST_Call`, `SFTP_Transfer`) and parameter signatures.
* [ ] **Core REST API Endpoints:** Build FastAPI routes (`/api/v1/jobs/init`, `/api/v1/telemetry/ops`) for decoupled runner communication.
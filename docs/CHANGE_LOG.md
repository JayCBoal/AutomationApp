# CHANGE_LOG.md

All notable structural, schema, and architectural changes to the AutoApp project are documented here.

---

## [Unreleased] - 2026-10-06

### Architectural & Model Redesign

#### 1. Consolidated File Transfer Definitions into `Endpoints`
* **Removed:** `Sources` and `Deliveries` tables.
* **Added:** `Endpoints` table with `EndpointType` ENUM (`'SOURCE'`, `'DELIVERY'`).
* **Attributes:** Bridges `Site_MasterObject_id`, `Entity_MasterObject_id`, and `Application_MasterObject_id` alongside `Path` and `FilenamePattern`.
* **Rationale:** Eliminates schema and ORM duplication while allowing bidirectional or multi-purpose endpoint queries against physical sites.

#### 2. Re-Anchored `Entities` to Technical `Sites`
* **Updated:** Added `Entity_MasterObject_id` foreign key to `Sites`.
* **Rationale:** Clarified that `Entities` represents external counter-parties (vendors, clients, partners). Technical endpoints (SFTP, API, Blob containers) belong directly to these external entities, while business workflows remain decoupled.

#### 3. Decoupled `Processes` and `Jobs` from Fixed Entities
* **Removed:** Legacy `Application_id` and `Entity_id` foreign key columns from `Processes`.
* **Rationale:** Allows workflows (`Processes`) and executable tasks (`Jobs`) to operate across multiple application and partner boundaries without restrictive 1-to-1 database bindings. Context scoping is now handled via `TagAssignments` and dynamic `${SCOPE.varname}` resolution.

#### 4. Implemented Polymorphic Supertype Registry (`MasterObjects`)
* **Updated:** Integrated `MasterObjects` as the single base class across core domain entities (`Applications`, `Entities`, `Sites`, `Credentials`, `Tags`, `Processes`, `Jobs`).
* **Primary Key Strategy:** Domain entities use `MasterObject_id` as both primary key and foreign key to `MasterObjects(id)`.
* **Shared Attachments:** `Variables` and `TagAssignments` attach polymorphically to any `MasterObject_id` with `CASCADE DELETE` enabled.

#### 5. Streamlined Execution and Log Tables
* **Refactored:** Simplified `Operations`, `Audits`, `AsyncParentInstances`, and `AsyncInstances` schemas.
* **Optimization:** Shifted high-volume transactional logs to standard auto-incrementing integer keys to prevent unnecessary overhead on domain registry management.

---

## File Tracking Index

| File | Status | Notes |
| :--- | :--- | :--- |
| `Drop_Recreate_&_Repopulate_Tables.sql` | **Updated** | Reflects unified `Endpoints` table, `Sites.Entity_MasterObject_id`, and updated constraints. |
| `models.py` | **Updated** | Refactored with `Endpoint` class, polymorphic inheritance mappings, and updated foreign keys. |
| `CHANGE_LOG.md` | **Created** | Tracks ongoing architectural evolution. |
# Database Schema

_Generated from `autoapp/app/models.py` by `docs/generate_diagrams.py`. Do not edit by hand; change the models and run the script._

This is the schema the Python models create. The MariaDB script in `SQL/` currently differs from it in places and also defines `AsyncParentInstances` and `AsyncInstances`, which have no model yet.

## Reading the diagrams

- `PK` primary key, `FK` foreign key, `UK` unique.
- A line ending in a crow's foot is the "many" side. The label is the foreign key column.
- `Applications`, `Entities`, `Sites`, `Credentials`, `Tags` and `Jobs` each share their primary key with one row in `MasterObjects`.

## Overview

All tables and how they connect.

```mermaid
erDiagram
    MasterObjects ||--o| Applications : "MasterObject_id"
    MasterObjects |o--o{ Audits : "MasterObject_id"
    MasterObjects ||--o| Credentials : "MasterObject_id"
    MasterObjects ||--o| Entities : "MasterObject_id"
    MasterObjects ||--o| Jobs : "MasterObject_id"
    StepTypes ||--o{ StepDefinitions : "StepType_id"
    MasterObjects ||--o| Tags : "MasterObject_id"
    MasterObjects ||--o{ Variables : "MasterObject_id"
    Jobs ||--o{ JobSteps : "Job_MasterObject_id"
    StepTypes ||--o{ JobSteps : "StepType_id"
    MasterObjects ||--o| Sites : "MasterObject_id"
    Entities |o--o{ Sites : "Entity_MasterObject_id"
    Tags ||--o{ TagAssignments : "Tag_MasterObject_id"
    MasterObjects ||--o{ TagAssignments : "Target_MasterObject_id"
    Sites |o--o{ Endpoints : "Site_MasterObject_id"
    Applications |o--o{ Endpoints : "Application_MasterObject_id"
    JobSteps ||--o{ JobStepParameters : "JobStep_id"
    JobSteps |o--o{ Operations : "JobStep_id"
    Endpoints |o--o{ Operations : "SourceEndpoint_id"
    Endpoints |o--o{ Operations : "DestEndpoint_id"
```

## Domain registry

```mermaid
erDiagram
    MasterObjects {
        int id PK
        enum ObjectType "required; one of: APPLICATION, ENTITY, SITE, CREDENTIAL, TAG, JOB"
        datetime CreatedDateTime
        string(100) CreatedBy
        datetime ModifiedDateTime
        string(100) ModifiedBy
    }
    Applications {
        int MasterObject_id PK, FK
        string(100) Name UK "required"
        string(10) Abbr UK "required"
        text Description
        bool IsActive
    }
    Entities {
        int MasterObject_id PK, FK
        string(64) Name UK "required"
        string(10) Abbr "required"
        string(256) Description
    }
    Sites {
        int MasterObject_id PK, FK
        int Entity_MasterObject_id FK
        string(64) Name UK "required"
        string(128) Host "required"
        int Port
        string(16) Protocol
        string(256) Description
    }
    Credentials {
        int MasterObject_id PK, FK
        string(100) Name UK "required"
        string(50) CredType "required"
        text SecretData
        bool IsActive
    }
    Tags {
        int MasterObject_id PK, FK
        string(100) TagName UK "required"
        string(50) Category
        text Description
    }
    Variables {
        int id PK
        int MasterObject_id FK "required"
        string(100) VarName "required"
        text VarValue
        bool IsSecret
        text Description
    }
    TagAssignments {
        int id PK
        int Tag_MasterObject_id FK "required"
        int Target_MasterObject_id FK "required"
    }
    MasterObjects ||--o| Applications : "MasterObject_id"
    MasterObjects ||--o| Credentials : "MasterObject_id"
    MasterObjects ||--o| Entities : "MasterObject_id"
    MasterObjects ||--o| Tags : "MasterObject_id"
    MasterObjects ||--o{ Variables : "MasterObject_id"
    MasterObjects ||--o| Sites : "MasterObject_id"
    Entities |o--o{ Sites : "Entity_MasterObject_id"
    Tags ||--o{ TagAssignments : "Tag_MasterObject_id"
    MasterObjects ||--o{ TagAssignments : "Target_MasterObject_id"
```

## Jobs and steps

```mermaid
erDiagram
    Jobs {
        int MasterObject_id PK, FK
        string(320) JobKey UK "required"
        text Description
        bool IsActive
    }
    JobSteps {
        int id PK
        int Job_MasterObject_id FK "required"
        int StepType_id FK "required"
        int StepOrder
        string(150) StepTitle
        bool IsActive
    }
    JobStepParameters {
        int id PK
        int JobStep_id FK "required"
        string(100) ParameterName "required"
        text ParameterValue
    }
    StepTypes {
        int id PK
        string(100) Name "required"
        string(50) Code UK "required"
        text Description
        bool IsActive
    }
    StepDefinitions {
        int id PK
        int StepType_id FK "required"
        string(100) ParameterName "required"
        string(20) DataType
        bool IsRequired
        text DefaultValue
        text Description
    }
    MasterObjects ||--o| Jobs : "MasterObject_id"
    StepTypes ||--o{ StepDefinitions : "StepType_id"
    Jobs ||--o{ JobSteps : "Job_MasterObject_id"
    StepTypes ||--o{ JobSteps : "StepType_id"
    JobSteps ||--o{ JobStepParameters : "JobStep_id"
```

## Endpoints, operations and audits

```mermaid
erDiagram
    Endpoints {
        int id PK
        string(100) Name UK "required"
        int Site_MasterObject_id FK
        int Application_MasterObject_id FK
        string(256) Path "required"
        string(128) FilenamePattern "required"
        string(256) Description
        datetime ModifiedDateTime
        string(50) ModifiedBy
    }
    Operations {
        int id PK
        string(64) ExecutionInstanceID "required"
        int JobStep_id FK
        string(50) OpType "required"
        string(20) OpStatus "required"
        int BytesTransferred
        text SourceURI
        text DestinationURI
        int SourceEndpoint_id FK
        int DestEndpoint_id FK
        text Details
        datetime CreatedDateTime
    }
    Audits {
        int id PK
        int MasterObject_id FK
        string(64) ExecutionInstanceID
        string(20) Severity
        text Message "required"
        datetime CreatedDateTime
    }
    MasterObjects |o--o{ Audits : "MasterObject_id"
    Sites |o--o{ Endpoints : "Site_MasterObject_id"
    Applications |o--o{ Endpoints : "Application_MasterObject_id"
    JobSteps |o--o{ Operations : "JobStep_id"
    Endpoints |o--o{ Operations : "SourceEndpoint_id"
    Endpoints |o--o{ Operations : "DestEndpoint_id"
```

## Multi-column unique constraints

| Table | Columns that must be unique together |
| :--- | :--- |
| `Variables` | `MasterObject_id`, `VarName` |
| `TagAssignments` | `Tag_MasterObject_id`, `Target_MasterObject_id` |

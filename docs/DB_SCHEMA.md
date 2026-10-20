# Database Schema

_Generated from `autoapp/app/models.py` by `docs/generate_diagrams.py`. Do not edit by hand; change the models and run the script._

This is the schema the Python models create. The MariaDB script `SQL/Create_Tables.sql` is generated from the same models by `SQL/generate_ddl.py`.

## Reading the diagrams

- `PK` primary key, `FK` foreign key, `UK` unique.
- A line ending in a crow's foot is the "many" side. The label is the foreign key column.
- `Applications`, `Entities`, `Sites`, `Credentials`, `Tags`, `Jobs` and `Endpoints` each share their primary key with one row in `MasterObjects`.

## Overview

All tables and how they connect.

```mermaid
erDiagram
    MasterObjects ||--o| Applications : "MasterObject_id"
    MasterObjects |o--o{ Audits : "MasterObject_id"
    MasterObjects ||--o| Credentials : "MasterObject_id"
    MasterObjects ||--o| Entities : "MasterObject_id"
    MasterObjects ||--o| Jobs : "MasterObject_id"
    Jobs |o--o{ Jobs : "Owner_MasterObject_id"
    MasterObjects ||--o| Schedulers : "MasterObject_id"
    StepTypes ||--o{ StepDefinitions : "StepType_id"
    MasterObjects ||--o| Tags : "MasterObject_id"
    Tags |o--o{ Tags : "Parent_MasterObject_id"
    MasterObjects ||--o{ Variables : "MasterObject_id"
    Jobs |o--o{ JobRuns : "Job_MasterObject_id"
    JobRuns |o--o{ JobRuns : "ParentRun_id"
    Jobs ||--o{ JobSteps : "Job_MasterObject_id"
    StepTypes ||--o{ JobSteps : "StepType_id"
    JobSteps |o--o{ JobSteps : "ParentStep_id"
    MasterObjects ||--o| Sites : "MasterObject_id"
    Entities |o--o{ Sites : "Entity_MasterObject_id"
    Tags ||--o{ TagAssignments : "Tag_MasterObject_id"
    MasterObjects ||--o{ TagAssignments : "Target_MasterObject_id"
    Jobs ||--o{ WorkflowItems : "Workflow_MasterObject_id"
    Jobs ||--o{ WorkflowItems : "Job_MasterObject_id"
    JobRuns ||--o{ ConditionChecks : "WorkflowRun_id"
    MasterObjects ||--o| Endpoints : "MasterObject_id"
    Sites |o--o{ Endpoints : "Site_MasterObject_id"
    Applications |o--o{ Endpoints : "Application_MasterObject_id"
    JobSteps ||--o{ JobStepParameters : "JobStep_id"
    Jobs |o--o{ Reactions : "Job_MasterObject_id"
    WorkflowItems |o--o{ Reactions : "Item_id"
    WorkflowItems ||--o{ WorkflowItemVariables : "Item_id"
    WorkflowItems ||--o{ WorkflowPrerequisites : "Item_id"
    WorkflowItems |o--o{ WorkflowPrerequisites : "TargetItem_id"
    JobRuns ||--o{ WorkflowRunItems : "WorkflowRun_id"
    WorkflowItems |o--o{ WorkflowRunItems : "Item_id"
    JobRuns |o--o{ WorkflowRunItems : "ChildRun_id"
    JobRuns ||--o{ Operations : "JobRun_id"
    JobSteps |o--o{ Operations : "JobStep_id"
    Endpoints |o--o{ Operations : "SourceEndpoint_id"
    Endpoints |o--o{ Operations : "DestEndpoint_id"
    Reactions ||--o{ ReactionActions : "Reaction_id"
    WorkflowItems |o--o{ ReactionActions : "TargetItem_id"
    Jobs |o--o{ ReactionActions : "TargetJob_MasterObject_id"
    JobRuns ||--o{ ReactionEvents : "JobRun_id"
    JobRuns |o--o{ ReactionEvents : "WorkflowRun_id"
    ReactionActions |o--o{ ReactionEvents : "ReactionAction_id"
```

## Domain registry

```mermaid
erDiagram
    MasterObjects {
        int id PK
        enum ObjectType "required; one of: APPLICATION, ENTITY, SITE, CREDENTIAL, TAG, JOB, ENDPOINT, SCHEDULER"
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
        bool IsActive
    }
    Sites {
        int MasterObject_id PK, FK
        int Entity_MasterObject_id FK
        string(64) Name UK "required"
        string(128) Host "required"
        int Port
        string(16) Protocol
        string(256) Description
        bool IsActive
    }
    Credentials {
        int MasterObject_id PK, FK
        string(100) Name UK "required"
        string(50) CredType "required"
        text SecretData
        bool IsActive
    }
    Schedulers {
        int MasterObject_id PK, FK
        string(100) Name UK "required"
        string(20) Technology "required"
        string(512) ApiUrl
        text Description
        bool IsActive
    }
    Tags {
        int MasterObject_id PK, FK
        int Parent_MasterObject_id FK
        string(100) Name "required"
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
    MasterObjects ||--o| Schedulers : "MasterObject_id"
    MasterObjects ||--o| Tags : "MasterObject_id"
    Tags |o--o{ Tags : "Parent_MasterObject_id"
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
        string(20) JobType "required"
        int Owner_MasterObject_id FK
        string(100) SuccessReturnCodes
        text SucceedsWhen
        string(100) ReturnCodeFrom
    }
    JobSteps {
        int id PK
        int Job_MasterObject_id FK "required"
        int StepType_id FK "required"
        int ParentStep_id FK
        int StepOrder
        string(150) StepTitle
        string(64) StepName
        bool IsActive
        string(20) OnFailure "required"
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
        int DisplayOrder "required"
        string(10) LocationRole
        text AllowedValues
    }
    MasterObjects ||--o| Jobs : "MasterObject_id"
    Jobs |o--o{ Jobs : "Owner_MasterObject_id"
    StepTypes ||--o{ StepDefinitions : "StepType_id"
    Jobs ||--o{ JobSteps : "Job_MasterObject_id"
    StepTypes ||--o{ JobSteps : "StepType_id"
    JobSteps |o--o{ JobSteps : "ParentStep_id"
    JobSteps ||--o{ JobStepParameters : "JobStep_id"
```

## Workflows

```mermaid
erDiagram
    Jobs {
        int MasterObject_id PK, FK
        string(320) JobKey UK "required"
        text Description
        bool IsActive
        string(20) JobType "required"
        int Owner_MasterObject_id FK
        string(100) SuccessReturnCodes
        text SucceedsWhen
        string(100) ReturnCodeFrom
    }
    WorkflowItems {
        int id PK
        int Workflow_MasterObject_id FK "required"
        string(100) ItemName "required"
        int Job_MasterObject_id FK "required"
        string(10) JoinRule "required"
        text StartRule
        int ItemOrder "required"
        string(20) DisabledHere
        bool ReactionsOverridden "required"
    }
    WorkflowItemVariables {
        int id PK
        int Item_id FK "required"
        string(100) VarName "required"
        text VarValue
        bool IsSecret
        text Description
    }
    WorkflowPrerequisites {
        int id PK
        int Item_id FK "required"
        int TargetItem_id FK
        string(20) Test "required"
        string(100) ReturnCodes
        text Condition
    }
    Reactions {
        int id PK
        int Job_MasterObject_id FK
        int Item_id FK
        string(10) Section "required"
        int ReactionOrder "required"
        string(20) WhenTest "required"
        string(100) WhenReturnCodes
        text WhenCondition
    }
    ReactionActions {
        int id PK
        int Reaction_id FK "required"
        int ActionOrder "required"
        string(30) Action "required"
        int MaxTimes
        int WaitSeconds
        int TargetItem_id FK
        int TargetJob_MasterObject_id FK
    }
    JobRuns {
        int id PK
        string(36) RunID UK "required"
        string(320) JobKey "required"
        int Job_MasterObject_id FK
        string(64) SchedulerInstanceID "required"
        int RunNumber "required"
        string(100) SchedulerName
        date BusinessDate
        string(255) Host
        string(20) Status "required"
        text ErrorMessage
        datetime StartedDateTime
        datetime EndedDateTime
        int ReturnCode
        string(40) Reason
        string(20) JobType "required"
        int ParentRun_id FK
        string(1000) WorkflowPath
        int Attempt "required"
        datetime CancelRequestedDateTime
        datetime KillRequestedDateTime
        int ProcessID
        string(20) StatusBeforeOverride
        int FileCount
        bigint Bytes
        string(500) LogFile
        datetime LogRemovedDateTime
        text WorkflowVariables
    }
    WorkflowRunItems {
        int id PK
        int WorkflowRun_id FK "required"
        int Item_id FK
        string(1000) Path "required"
        string(100) ItemName "required"
        string(320) JobKey "required"
        int ItemOrder "required"
        string(20) Status "required"
        string(40) Reason
        int ReturnCode
        string(20) StatusBeforeOverride
        int ProcessID
        int ChildRun_id FK
        int Attempt "required"
        datetime StartedDateTime
        datetime EndedDateTime
    }
    ReactionEvents {
        int id PK
        int JobRun_id FK "required"
        int WorkflowRun_id FK
        string(1000) WorkflowPath
        int ReactionAction_id FK
        string(30) Action "required"
        string(20) Result "required"
        text Message
        datetime EventDateTime "required"
    }
    ConditionChecks {
        int id PK
        int WorkflowRun_id FK "required"
        string(1000) Path
        string(20) Kind "required"
        text ConditionText "required"
        text ValuesJson "required"
        string(10) Result "required"
        datetime CheckedDateTime "required"
    }
    MasterObjects ||--o| Jobs : "MasterObject_id"
    Jobs |o--o{ Jobs : "Owner_MasterObject_id"
    Jobs |o--o{ JobRuns : "Job_MasterObject_id"
    JobRuns |o--o{ JobRuns : "ParentRun_id"
    Jobs ||--o{ WorkflowItems : "Workflow_MasterObject_id"
    Jobs ||--o{ WorkflowItems : "Job_MasterObject_id"
    JobRuns ||--o{ ConditionChecks : "WorkflowRun_id"
    Jobs |o--o{ Reactions : "Job_MasterObject_id"
    WorkflowItems |o--o{ Reactions : "Item_id"
    WorkflowItems ||--o{ WorkflowItemVariables : "Item_id"
    WorkflowItems ||--o{ WorkflowPrerequisites : "Item_id"
    WorkflowItems |o--o{ WorkflowPrerequisites : "TargetItem_id"
    JobRuns ||--o{ WorkflowRunItems : "WorkflowRun_id"
    WorkflowItems |o--o{ WorkflowRunItems : "Item_id"
    JobRuns |o--o{ WorkflowRunItems : "ChildRun_id"
    Reactions ||--o{ ReactionActions : "Reaction_id"
    WorkflowItems |o--o{ ReactionActions : "TargetItem_id"
    Jobs |o--o{ ReactionActions : "TargetJob_MasterObject_id"
    JobRuns ||--o{ ReactionEvents : "JobRun_id"
    JobRuns |o--o{ ReactionEvents : "WorkflowRun_id"
    ReactionActions |o--o{ ReactionEvents : "ReactionAction_id"
```

## Endpoints, runs, operations, audits and settings

```mermaid
erDiagram
    Endpoints {
        int MasterObject_id PK, FK
        string(100) Name UK "required"
        int Site_MasterObject_id FK
        int Application_MasterObject_id FK
        string(256) Path "required"
        string(128) FilenamePattern "required"
        string(256) Description
    }
    JobRuns {
        int id PK
        string(36) RunID UK "required"
        string(320) JobKey "required"
        int Job_MasterObject_id FK
        string(64) SchedulerInstanceID "required"
        int RunNumber "required"
        string(100) SchedulerName
        date BusinessDate
        string(255) Host
        string(20) Status "required"
        text ErrorMessage
        datetime StartedDateTime
        datetime EndedDateTime
        int ReturnCode
        string(40) Reason
        string(20) JobType "required"
        int ParentRun_id FK
        string(1000) WorkflowPath
        int Attempt "required"
        datetime CancelRequestedDateTime
        datetime KillRequestedDateTime
        int ProcessID
        string(20) StatusBeforeOverride
        int FileCount
        bigint Bytes
        string(500) LogFile
        datetime LogRemovedDateTime
        text WorkflowVariables
    }
    Operations {
        int id PK
        int JobRun_id FK "required"
        int Seq "required"
        int JobStep_id FK
        int StepOrder
        string(50) StepNumber
        string(50) Iteration
        string(50) OpType "required"
        string(20) OpStatus "required"
        int SourceEndpoint_id FK
        text SourcePath
        string(255) SourceFilename
        bigint SourceSize
        int DestEndpoint_id FK
        text DestPath
        string(255) DestFilename
        bigint DestSize
        string(64) Checksum
        text Details
        text ErrorMessage
        datetime StartedDateTime
        datetime EndedDateTime
    }
    Audits {
        int id PK
        int MasterObject_id FK
        string(50) Action "required"
        string(100) PerformedBy
        text Details
        datetime CreatedDateTime
    }
    Settings {
        string(100) SettingKey PK
        text SettingValue "required"
        datetime UpdatedDateTime
        string(100) UpdatedBy
    }
    MasterObjects |o--o{ Audits : "MasterObject_id"
    Jobs |o--o{ JobRuns : "Job_MasterObject_id"
    JobRuns |o--o{ JobRuns : "ParentRun_id"
    MasterObjects ||--o| Endpoints : "MasterObject_id"
    Sites |o--o{ Endpoints : "Site_MasterObject_id"
    Applications |o--o{ Endpoints : "Application_MasterObject_id"
    JobRuns ||--o{ Operations : "JobRun_id"
    JobSteps |o--o{ Operations : "JobStep_id"
    Endpoints |o--o{ Operations : "SourceEndpoint_id"
    Endpoints |o--o{ Operations : "DestEndpoint_id"
```

## Multi-column unique constraints

| Table | Columns that must be unique together |
| :--- | :--- |
| `Tags` | `Parent_MasterObject_id`, `Name` |
| `Variables` | `MasterObject_id`, `VarName` |
| `TagAssignments` | `Tag_MasterObject_id`, `Target_MasterObject_id` |
| `WorkflowItems` | `Workflow_MasterObject_id`, `ItemName` |
| `WorkflowItemVariables` | `Item_id`, `VarName` |
| `WorkflowRunItems` | `WorkflowRun_id`, `Path` |
| `Operations` | `JobRun_id`, `Seq` |

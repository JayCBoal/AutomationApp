# Python Model

_Generated from `autoapp/app/models.py` by `docs/generate_diagrams.py`. Do not edit by hand; change the models and run the script._

Two views: the ORM classes in `autoapp/app/models.py`, and how the Python modules depend on each other. The module diagram is written by hand inside the generator script.

## ORM classes: inheritance

The domain classes inherit from `MasterObject`. Each subclass shows only the attributes it adds; it also has everything `MasterObject` has.

```mermaid
classDiagram
    direction TB
    class MasterObject {
        +int id
        +enum ObjectType
        +datetime CreatedDateTime
        +string(100) CreatedBy
        +datetime ModifiedDateTime
        +string(100) ModifiedBy
    }
    class Application {
        +int MasterObject_id
        +string(100) Name
        +string(10) Abbr
        +text Description
        +bool IsActive
    }
    MasterObject <|-- Application
    class Credential {
        +int MasterObject_id
        +string(100) Name
        +string(50) CredType
        +text SecretData
        +bool IsActive
    }
    MasterObject <|-- Credential
    class Entity {
        +int MasterObject_id
        +string(64) Name
        +string(10) Abbr
        +string(256) Description
    }
    MasterObject <|-- Entity
    class Job {
        +int MasterObject_id
        +string(320) JobKey
        +text Description
        +bool IsActive
    }
    MasterObject <|-- Job
    class Site {
        +int MasterObject_id
        +int Entity_MasterObject_id
        +string(64) Name
        +string(128) Host
        +int Port
        +string(16) Protocol
        +string(256) Description
    }
    MasterObject <|-- Site
    class Tag {
        +int MasterObject_id
        +string(100) TagName
        +string(50) Category
        +text Description
    }
    MasterObject <|-- Tag
```

## ORM classes: supporting classes and relationships

An arrow is a relationship attribute you can follow in code: `job.steps` is the list of a job's `JobStep` objects. The label is the attribute name.

```mermaid
classDiagram
    direction LR
    class Audit {
        +int id
        +int MasterObject_id
        +string(64) ExecutionInstanceID
        +string(20) Severity
        +text Message
        +datetime CreatedDateTime
    }
    class Endpoint {
        +int id
        +string(100) Name
        +int Site_MasterObject_id
        +int Application_MasterObject_id
        +string(256) Path
        +string(128) FilenamePattern
        +string(256) Description
        +datetime ModifiedDateTime
        +string(50) ModifiedBy
    }
    class JobStep {
        +int id
        +int job_id
        +int StepType_id
        +int StepOrder
        +string(150) Title
        +bool IsActive
    }
    class JobStepParameter {
        +int id
        +int job_step_id
        +string(100) ParamName
        +text ParamValue
    }
    class Operation {
        +int id
        +string(64) ExecutionInstanceID
        +int JobStep_id
        +string(50) OpType
        +string(20) OpStatus
        +int BytesTransferred
        +text SourceURI
        +text DestinationURI
        +int SourceEndpoint_id
        +int DestEndpoint_id
        +text Details
        +datetime CreatedDateTime
    }
    class StepDefinition {
        +int id
        +int StepType_id
        +string(100) ParamName
        +string(20) DataType
        +bool IsRequired
        +text DefaultValue
        +text Description
    }
    class StepType {
        +int id
        +string(100) TypeName
        +string(50) HandlerClass
        +text Description
        +bool IsActive
    }
    class TagAssignment {
        +int id
        +int Tag_MasterObject_id
        +int Target_MasterObject_id
    }
    class Variable {
        +int id
        +int MasterObject_id
        +string(100) VarName
        +text VarValue
        +bool IsSecret
        +text Description
    }
    Endpoint "*" --> "0..1" Site : site
    Endpoint "*" --> "0..1" Application : application
    Entity "1" --> "*" Site : sites
    Job "1" --> "*" JobStep : steps
    JobStep "*" --> "0..1" StepType : step_type
    JobStep "1" --> "*" JobStepParameter : parameters
    MasterObject "1" --> "*" Variable : variables
    MasterObject "1" --> "*" TagAssignment : tag_assignments
    StepType "1" --> "*" StepDefinition : definitions
```

Relationships created in the other direction (for example `job_step.job`) exist too but are not drawn.

## Where the Python name differs from the column name

Use the Python name in code and the column name in SQL.

| Class | Python attribute | Database column |
| :--- | :--- | :--- |
| `JobStep` | `job_id` | `JobSteps.Job_MasterObject_id` |
| `JobStep` | `Title` | `JobSteps.StepTitle` |
| `JobStepParameter` | `job_step_id` | `JobStepParameters.JobStep_id` |
| `JobStepParameter` | `ParamName` | `JobStepParameters.ParameterName` |
| `JobStepParameter` | `ParamValue` | `JobStepParameters.ParameterValue` |
| `StepDefinition` | `ParamName` | `StepDefinitions.ParameterName` |
| `StepType` | `TypeName` | `StepTypes.Name` |
| `StepType` | `HandlerClass` | `StepTypes.Code` |

## Modules

An arrow means "uses".

```mermaid
flowchart TD
    scheduler([WLA scheduler]) -->|"--job-key, --instance-id"| runner

    subgraph engine [autoapp/engine]
        runner[runner.py<br/>runs a job's steps in order]
        scope[scope_engine.py<br/>resolves placeholders]
        params[step_params.py<br/>working-folder rule and Endpoint lookup]
        registry[handlers/__init__.py<br/>step type to handler]
        base[handlers/base_handler.py<br/>timing, operation record, failure audit]
        file[handlers/file_handler.py<br/>COPY_FILES]
        telemetry[telemetry_client.py<br/>writes the spool file]
    end

    subgraph app [autoapp/app]
        models[models.py<br/>ORM classes]
        database[database.py<br/>engine and sessions]
        schemas[schemas.py<br/>API request and response shapes]
        jobs[routers/jobs.py<br/>POST /api/v1/jobs/init]
        variables[routers/variables.py]
        telemetry_api[routers/telemetry.py<br/>not working yet]
        main[main.py<br/>FastAPI app]
    end

    runner --> scope
    runner --> params
    runner --> registry
    runner --> telemetry
    runner --> database
    params --> scope
    registry --> file
    file --> base
    base --> telemetry
    scope --> models
    params --> models
    database --> models

    main --> jobs
    main --> variables
    main --> telemetry_api
    jobs --> scope
    jobs --> params
    jobs --> registry
    jobs --> schemas
    variables --> scope
    telemetry_api --> models

    telemetry --> spool[(spool .jsonl files)]
    database --> db[(AutoApp database)]
```

-- ============================================================================
-- AutoApp Core Relational Schema (MasterObjects + Unified Endpoints)
-- ============================================================================

SET FOREIGN_KEY_CHECKS = 0;

-- Drop Tables
DROP TABLE IF EXISTS Endpoints;
DROP TABLE IF EXISTS AsyncInstances;
DROP TABLE IF EXISTS AsyncParentInstances;
DROP TABLE IF EXISTS Audits;
DROP TABLE IF EXISTS Operations;
DROP TABLE IF EXISTS JobStepParameters;
DROP TABLE IF EXISTS JobSteps;
DROP TABLE IF EXISTS StepDefinitions;
DROP TABLE IF EXISTS StepTypes;
DROP TABLE IF EXISTS TagAssignments;
DROP TABLE IF EXISTS Variables;
DROP TABLE IF EXISTS Jobs;
DROP TABLE IF EXISTS Processes;
DROP TABLE IF EXISTS Tags;
DROP TABLE IF EXISTS Credentials;
DROP TABLE IF EXISTS Sites;
DROP TABLE IF EXISTS Entities;
DROP TABLE IF EXISTS Applications;
DROP TABLE IF EXISTS MasterObjects;

SET FOREIGN_KEY_CHECKS = 1;

-- ----------------------------------------------------------------------------
-- 1. Polymorphic Base Registry
-- ----------------------------------------------------------------------------
CREATE TABLE MasterObjects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ObjectType ENUM('APPLICATION', 'ENTITY', 'SITE', 'CREDENTIAL', 'TAG', 'PROCESS', 'JOB') NOT NULL,
    CreatedDateTime DATETIME DEFAULT CURRENT_TIMESTAMP,
    CreatedBy VARCHAR(100) DEFAULT 'system',
    ModifiedDateTime DATETIME ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(100) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 2. Master Domain Subtypes
-- ----------------------------------------------------------------------------
CREATE TABLE Applications (
    MasterObject_id INT PRIMARY KEY,
    Name VARCHAR(100) NOT NULL UNIQUE,
    Abbr VARCHAR(10) NOT NULL UNIQUE,
    Description TEXT NULL,
    IsActive TINYINT(1) DEFAULT 1,
    FOREIGN KEY (MasterObject_id) REFERENCES MasterObjects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Entities (
    MasterObject_id INT PRIMARY KEY,
    Name VARCHAR(100) NOT NULL UNIQUE,
    Description TEXT NULL,
    IsActive TINYINT(1) DEFAULT 1,
    FOREIGN KEY (MasterObject_id) REFERENCES MasterObjects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Sites (
    MasterObject_id INT PRIMARY KEY,
    Entity_MasterObject_id INT NULL,
    Name VARCHAR(100) NOT NULL UNIQUE,
    Hostname VARCHAR(255) NOT NULL,
    Protocol VARCHAR(20) DEFAULT 'SFTP',
    RootFolder VARCHAR(500) NULL,
    IsActive TINYINT(1) DEFAULT 1,
    FOREIGN KEY (MasterObject_id) REFERENCES MasterObjects(id) ON DELETE CASCADE,
    FOREIGN KEY (Entity_MasterObject_id) REFERENCES Entities(MasterObject_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Credentials (
    MasterObject_id INT PRIMARY KEY,
    Name VARCHAR(100) NOT NULL UNIQUE,
    CredType VARCHAR(50) NOT NULL,
    SecretData TEXT NULL,
    IsActive TINYINT(1) DEFAULT 1,
    FOREIGN KEY (MasterObject_id) REFERENCES MasterObjects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Tags (
    MasterObject_id INT PRIMARY KEY,
    TagName VARCHAR(100) NOT NULL UNIQUE,
    Category VARCHAR(50) NULL,
    Description TEXT NULL,
    FOREIGN KEY (MasterObject_id) REFERENCES MasterObjects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Processes (
    MasterObject_id INT PRIMARY KEY,
    Name VARCHAR(150) NOT NULL UNIQUE,
    Description TEXT NULL,
    IsActive TINYINT(1) DEFAULT 1,
    FOREIGN KEY (MasterObject_id) REFERENCES MasterObjects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Jobs (
    MasterObject_id INT PRIMARY KEY,
    Process_MasterObject_id INT NOT NULL,
    Name VARCHAR(150) NOT NULL,
    Description TEXT NULL,
    ExecutionOrder INT DEFAULT 1,
    IsActive TINYINT(1) DEFAULT 1,
    FOREIGN KEY (MasterObject_id) REFERENCES MasterObjects(id) ON DELETE CASCADE,
    FOREIGN KEY (Process_MasterObject_id) REFERENCES Processes(MasterObject_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 3. Universal Metadata & Variable Relationships
-- ----------------------------------------------------------------------------
CREATE TABLE Variables (
    id INT AUTO_INCREMENT PRIMARY KEY,
    MasterObject_id INT NOT NULL,
    VarName VARCHAR(100) NOT NULL,
    VarValue TEXT NULL,
    IsSecret TINYINT(1) DEFAULT 0,
    Description TEXT NULL,
    FOREIGN KEY (MasterObject_id) REFERENCES MasterObjects(id) ON DELETE CASCADE,
    CONSTRAINT uq_obj_var UNIQUE (MasterObject_id, VarName)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE TagAssignments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    Tag_MasterObject_id INT NOT NULL,
    Target_MasterObject_id INT NOT NULL,
    FOREIGN KEY (Tag_MasterObject_id) REFERENCES Tags(MasterObject_id) ON DELETE CASCADE,
    FOREIGN KEY (Target_MasterObject_id) REFERENCES MasterObjects(id) ON DELETE CASCADE,
    CONSTRAINT uq_tag_target UNIQUE (Tag_MasterObject_id, Target_MasterObject_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 4. Unified Endpoints Specification (Replaces Sources & Deliveries)
-- ----------------------------------------------------------------------------
CREATE TABLE Endpoints (
    id INT AUTO_INCREMENT PRIMARY KEY,
    EndpointType ENUM('SOURCE', 'DELIVERY') NOT NULL,
    Site_MasterObject_id INT NULL,
    Entity_MasterObject_id INT NULL,
    Application_MasterObject_id INT NULL,
    Path VARCHAR(256) NOT NULL,
    FilenamePattern VARCHAR(128) NOT NULL,
    Description VARCHAR(256) NULL,
    ModifiedDateTime DATETIME ON UPDATE CURRENT_TIMESTAMP,
    ModifiedBy VARCHAR(50) NULL,
    FOREIGN KEY (Site_MasterObject_id) REFERENCES Sites(MasterObject_id) ON DELETE SET NULL,
    FOREIGN KEY (Entity_MasterObject_id) REFERENCES Entities(MasterObject_id) ON DELETE SET NULL,
    FOREIGN KEY (Application_MasterObject_id) REFERENCES Applications(MasterObject_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 5. Step Catalog & Execution Schema
-- ----------------------------------------------------------------------------
CREATE TABLE StepTypes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    Name VARCHAR(100) NOT NULL,
    Code VARCHAR(50) NOT NULL UNIQUE,
    Description TEXT NULL,
    IsActive TINYINT(1) DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE StepDefinitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    StepType_id INT NOT NULL,
    ParameterName VARCHAR(100) NOT NULL,
    DataType VARCHAR(20) DEFAULT 'STRING',
    IsRequired TINYINT(1) DEFAULT 1,
    DefaultValue TEXT NULL,
    Description TEXT NULL,
    FOREIGN KEY (StepType_id) REFERENCES StepTypes(id) ON DELETE CASCADE,
    CONSTRAINT uq_steptype_param UNIQUE (StepType_id, ParameterName)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE JobSteps (
    id INT AUTO_INCREMENT PRIMARY KEY,
    Job_MasterObject_id INT NOT NULL,
    StepType_id INT NOT NULL,
    StepOrder INT DEFAULT 1,
    IsActive TINYINT(1) DEFAULT 1,
    FOREIGN KEY (Job_MasterObject_id) REFERENCES Jobs(MasterObject_id) ON DELETE CASCADE,
    FOREIGN KEY (StepType_id) REFERENCES StepTypes(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE JobStepParameters (
    id INT AUTO_INCREMENT PRIMARY KEY,
    JobStep_id INT NOT NULL,
    ParameterName VARCHAR(100) NOT NULL,
    ParameterValue TEXT NULL,
    FOREIGN KEY (JobStep_id) REFERENCES JobSteps(id) ON DELETE CASCADE,
    CONSTRAINT uq_jobstep_param UNIQUE (JobStep_id, ParameterName)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------------------------
-- 6. Operational Logging & Async Instance Tracking
-- ----------------------------------------------------------------------------
CREATE TABLE Operations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    Job_MasterObject_id INT NULL,
    OpType VARCHAR(50) NOT NULL,
    OpStatus VARCHAR(20) NOT NULL,
    Details TEXT NULL,
    ExecutedDateTime DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (Job_MasterObject_id) REFERENCES Jobs(MasterObject_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Audits (
    id INT AUTO_INCREMENT PRIMARY KEY,
    MasterObject_id INT NULL,
    Action VARCHAR(50) NOT NULL,
    PerformedBy VARCHAR(100) DEFAULT 'system',
    Details TEXT NULL,
    LogDateTime DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (MasterObject_id) REFERENCES MasterObjects(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE AsyncParentInstances (
    id INT AUTO_INCREMENT PRIMARY KEY,
    Job_MasterObject_id INT NOT NULL,
    Status VARCHAR(20) DEFAULT 'PENDING',
    CreatedDateTime DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (Job_MasterObject_id) REFERENCES Jobs(MasterObject_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE AsyncInstances (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ParentInstance_id INT NOT NULL,
    TaskIdentifier VARCHAR(255) NOT NULL,
    Status VARCHAR(20) DEFAULT 'RUNNING',
    LastPolledDateTime DATETIME NULL,
    FOREIGN KEY (ParentInstance_id) REFERENCES AsyncParentInstances(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
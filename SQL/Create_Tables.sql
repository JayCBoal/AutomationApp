-- ============================================================================
-- AutoApp schema for MariaDB
--
-- Generated from autoapp/app/models.py by SQL/generate_ddl.py.
-- Do not edit by hand: change the models and run the script.
--
-- WARNING: this drops every AutoApp table, and the data in it, before
-- creating the tables again.
-- ============================================================================

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS AsyncInstances;
DROP TABLE IF EXISTS AsyncParentInstances;
DROP TABLE IF EXISTS Processes;
DROP TABLE IF EXISTS Sources;
DROP TABLE IF EXISTS Deliveries;
DROP TABLE IF EXISTS ReactionEvents;
DROP TABLE IF EXISTS WorkflowPrerequisites;
DROP TABLE IF EXISTS ReactionActions;
DROP TABLE IF EXISTS Operations;
DROP TABLE IF EXISTS WorkflowRunItems;
DROP TABLE IF EXISTS WorkflowPrerequisiteChecks;
DROP TABLE IF EXISTS WorkflowItemVariables;
DROP TABLE IF EXISTS Reactions;
DROP TABLE IF EXISTS JobStepParameters;
DROP TABLE IF EXISTS Endpoints;
DROP TABLE IF EXISTS ConditionChecks;
DROP TABLE IF EXISTS WorkflowItems;
DROP TABLE IF EXISTS TagAssignments;
DROP TABLE IF EXISTS Sites;
DROP TABLE IF EXISTS JobSteps;
DROP TABLE IF EXISTS JobRuns;
DROP TABLE IF EXISTS Variables;
DROP TABLE IF EXISTS Tags;
DROP TABLE IF EXISTS StepDefinitions;
DROP TABLE IF EXISTS Schedulers;
DROP TABLE IF EXISTS Jobs;
DROP TABLE IF EXISTS Entities;
DROP TABLE IF EXISTS Credentials;
DROP TABLE IF EXISTS Audits;
DROP TABLE IF EXISTS Applications;
DROP TABLE IF EXISTS StepTypes;
DROP TABLE IF EXISTS Settings;
DROP TABLE IF EXISTS MasterObjects;

SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE `MasterObjects` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`ObjectType` ENUM('APPLICATION','ENTITY','SITE','CREDENTIAL','TAG','JOB','ENDPOINT','SCHEDULER') NOT NULL, 
	`CreatedDateTime` DATETIME DEFAULT (now()), 
	`CreatedBy` VARCHAR(100) DEFAULT 'system', 
	`ModifiedDateTime` DATETIME, 
	`ModifiedBy` VARCHAR(100), 
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Settings` (
	`SettingKey` VARCHAR(100) NOT NULL, 
	`SettingValue` TEXT NOT NULL, 
	`UpdatedDateTime` DATETIME, 
	`UpdatedBy` VARCHAR(100), 
	PRIMARY KEY (`SettingKey`)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `StepTypes` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`Name` VARCHAR(100) NOT NULL, 
	`Code` VARCHAR(50) NOT NULL, 
	`Description` TEXT, 
	`IsActive` BOOL DEFAULT true, 
	PRIMARY KEY (id), 
	UNIQUE (`Code`)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Applications` (
	`MasterObject_id` INTEGER NOT NULL, 
	`Name` VARCHAR(100) NOT NULL, 
	`Abbr` VARCHAR(10) NOT NULL, 
	`Description` TEXT, 
	`IsActive` BOOL DEFAULT true, 
	PRIMARY KEY (`MasterObject_id`), 
	FOREIGN KEY(`MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE CASCADE, 
	UNIQUE (`Name`), 
	UNIQUE (`Abbr`)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Audits` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`MasterObject_id` INTEGER, 
	`Action` VARCHAR(50) NOT NULL, 
	`PerformedBy` VARCHAR(100) DEFAULT 'system', 
	`Details` TEXT, 
	`CreatedDateTime` DATETIME DEFAULT (now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(`MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Credentials` (
	`MasterObject_id` INTEGER NOT NULL, 
	`Name` VARCHAR(100) NOT NULL, 
	`CredType` VARCHAR(50) NOT NULL, 
	`SecretData` TEXT, 
	`IsActive` BOOL DEFAULT true, 
	PRIMARY KEY (`MasterObject_id`), 
	FOREIGN KEY(`MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE CASCADE, 
	UNIQUE (`Name`)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Entities` (
	`MasterObject_id` INTEGER NOT NULL, 
	`Name` VARCHAR(64) NOT NULL, 
	`Abbr` VARCHAR(10) NOT NULL, 
	`Description` VARCHAR(256), 
	`IsActive` BOOL DEFAULT true, 
	PRIMARY KEY (`MasterObject_id`), 
	FOREIGN KEY(`MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE CASCADE, 
	UNIQUE (`Name`)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Jobs` (
	`MasterObject_id` INTEGER NOT NULL, 
	`JobKey` VARCHAR(320) NOT NULL, 
	`Description` TEXT, 
	`IsActive` BOOL DEFAULT true, 
	`JobType` VARCHAR(20) NOT NULL DEFAULT 'STEPS', 
	`Owner_MasterObject_id` INTEGER, 
	`SuccessReturnCodes` VARCHAR(100), 
	`SucceedsWhen` TEXT, 
	`ReturnCodeFrom` VARCHAR(100), 
	PRIMARY KEY (`MasterObject_id`), 
	FOREIGN KEY(`MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE CASCADE, 
	UNIQUE (`JobKey`), 
	FOREIGN KEY(`Owner_MasterObject_id`) REFERENCES `Jobs` (`MasterObject_id`) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Schedulers` (
	`MasterObject_id` INTEGER NOT NULL, 
	`Name` VARCHAR(100) NOT NULL, 
	`Technology` VARCHAR(20) NOT NULL DEFAULT 'OTHER', 
	`ApiUrl` VARCHAR(512), 
	`Description` TEXT, 
	`IsActive` BOOL DEFAULT true, 
	PRIMARY KEY (`MasterObject_id`), 
	FOREIGN KEY(`MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE CASCADE, 
	UNIQUE (`Name`)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `StepDefinitions` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`StepType_id` INTEGER NOT NULL, 
	`ParameterName` VARCHAR(100) NOT NULL, 
	`DataType` VARCHAR(20) DEFAULT 'STRING', 
	`IsRequired` BOOL DEFAULT true, 
	`DefaultValue` TEXT, 
	`Description` TEXT, 
	`DisplayOrder` INTEGER NOT NULL DEFAULT 0, 
	`LocationRole` VARCHAR(10), 
	`AllowedValues` TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(`StepType_id`) REFERENCES `StepTypes` (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Tags` (
	`MasterObject_id` INTEGER NOT NULL, 
	`Parent_MasterObject_id` INTEGER, 
	`Name` VARCHAR(100) NOT NULL, 
	`Description` TEXT, 
	PRIMARY KEY (`MasterObject_id`), 
	CONSTRAINT uq_tag_parent_name UNIQUE (`Parent_MasterObject_id`, `Name`), 
	FOREIGN KEY(`MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE CASCADE, 
	FOREIGN KEY(`Parent_MasterObject_id`) REFERENCES `Tags` (`MasterObject_id`) ON DELETE RESTRICT
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Variables` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`MasterObject_id` INTEGER NOT NULL, 
	`VarName` VARCHAR(100) NOT NULL, 
	`VarValue` TEXT, 
	`IsSecret` BOOL DEFAULT false, 
	`Description` TEXT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_obj_var UNIQUE (`MasterObject_id`, `VarName`), 
	FOREIGN KEY(`MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `JobRuns` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`RunID` VARCHAR(36) NOT NULL, 
	`JobKey` VARCHAR(320) NOT NULL, 
	`Job_MasterObject_id` INTEGER, 
	`SchedulerInstanceID` VARCHAR(64) NOT NULL, 
	`RunNumber` INTEGER NOT NULL DEFAULT 1, 
	`SchedulerName` VARCHAR(100), 
	`BusinessDate` DATE, 
	`Host` VARCHAR(255), 
	`Status` VARCHAR(20) NOT NULL DEFAULT 'RUNNING', 
	`ErrorMessage` TEXT, 
	`StartedDateTime` DATETIME(6), 
	`EndedDateTime` DATETIME(6), 
	`ReturnCode` INTEGER, 
	`Reason` VARCHAR(40), 
	`JobType` VARCHAR(20) NOT NULL DEFAULT 'STEPS', 
	`ParentRun_id` INTEGER, 
	`WorkflowPath` VARCHAR(1000), 
	`Attempt` INTEGER NOT NULL DEFAULT 1, 
	`CancelRequestedDateTime` DATETIME(6), 
	`KillRequestedDateTime` DATETIME(6), 
	`ProcessID` INTEGER, 
	`StatusBeforeOverride` VARCHAR(20), 
	`FileCount` INTEGER, 
	`Bytes` BIGINT, 
	`LogFile` VARCHAR(500), 
	`LogRemovedDateTime` DATETIME(6), 
	`WorkflowVariables` TEXT, 
	PRIMARY KEY (id), 
	UNIQUE (`RunID`), 
	FOREIGN KEY(`Job_MasterObject_id`) REFERENCES `Jobs` (`MasterObject_id`) ON DELETE SET NULL, 
	FOREIGN KEY(`ParentRun_id`) REFERENCES `JobRuns` (id) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_JobRuns_JobKey` ON `JobRuns` (`JobKey`);

CREATE INDEX `ix_JobRuns_ParentRun_id` ON `JobRuns` (`ParentRun_id`);

CREATE INDEX `ix_JobRuns_SchedulerInstanceID` ON `JobRuns` (`SchedulerInstanceID`);

CREATE TABLE `JobSteps` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`Job_MasterObject_id` INTEGER NOT NULL, 
	`StepType_id` INTEGER NOT NULL, 
	`ParentStep_id` INTEGER, 
	`StepOrder` INTEGER DEFAULT 1, 
	`StepTitle` VARCHAR(150) DEFAULT 'Execution Step', 
	`StepName` VARCHAR(64), 
	`IsActive` BOOL DEFAULT true, 
	`OnFailure` VARCHAR(20) NOT NULL DEFAULT 'FAIL_JOB', 
	PRIMARY KEY (id), 
	FOREIGN KEY(`Job_MasterObject_id`) REFERENCES `Jobs` (`MasterObject_id`) ON DELETE CASCADE, 
	FOREIGN KEY(`StepType_id`) REFERENCES `StepTypes` (id), 
	FOREIGN KEY(`ParentStep_id`) REFERENCES `JobSteps` (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Sites` (
	`MasterObject_id` INTEGER NOT NULL, 
	`Entity_MasterObject_id` INTEGER, 
	`Name` VARCHAR(64) NOT NULL, 
	`Host` VARCHAR(128) NOT NULL, 
	`Port` INTEGER DEFAULT 22, 
	`Protocol` VARCHAR(16) DEFAULT 'SFTP', 
	`Description` VARCHAR(256), 
	`IsActive` BOOL DEFAULT true, 
	PRIMARY KEY (`MasterObject_id`), 
	FOREIGN KEY(`MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE CASCADE, 
	FOREIGN KEY(`Entity_MasterObject_id`) REFERENCES `Entities` (`MasterObject_id`) ON DELETE SET NULL, 
	UNIQUE (`Name`)
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `TagAssignments` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`Tag_MasterObject_id` INTEGER NOT NULL, 
	`Target_MasterObject_id` INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tag_target UNIQUE (`Tag_MasterObject_id`, `Target_MasterObject_id`), 
	FOREIGN KEY(`Tag_MasterObject_id`) REFERENCES `Tags` (`MasterObject_id`) ON DELETE RESTRICT, 
	FOREIGN KEY(`Target_MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `WorkflowItems` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`Workflow_MasterObject_id` INTEGER NOT NULL, 
	`ItemName` VARCHAR(100) NOT NULL, 
	`Job_MasterObject_id` INTEGER NOT NULL, 
	`JoinRule` VARCHAR(10) NOT NULL DEFAULT 'ALL', 
	`StartRule` TEXT, 
	`ItemOrder` INTEGER NOT NULL DEFAULT 1, 
	`DisabledHere` VARCHAR(20), 
	`ReactionsOverridden` BOOL NOT NULL DEFAULT false, 
	`OnUnmet` VARCHAR(10) NOT NULL DEFAULT 'NOT_RUN', 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_item_name UNIQUE (`Workflow_MasterObject_id`, `ItemName`), 
	FOREIGN KEY(`Workflow_MasterObject_id`) REFERENCES `Jobs` (`MasterObject_id`) ON DELETE CASCADE, 
	FOREIGN KEY(`Job_MasterObject_id`) REFERENCES `Jobs` (`MasterObject_id`) ON DELETE RESTRICT
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_WorkflowItems_Workflow_MasterObject_id` ON `WorkflowItems` (`Workflow_MasterObject_id`);

CREATE TABLE `ConditionChecks` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`WorkflowRun_id` INTEGER NOT NULL, 
	`Path` VARCHAR(1000), 
	`Kind` VARCHAR(20) NOT NULL, 
	`ConditionText` TEXT NOT NULL, 
	`ValuesJson` TEXT NOT NULL, 
	`Result` VARCHAR(10) NOT NULL, 
	`CheckedDateTime` DATETIME(6) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(`WorkflowRun_id`) REFERENCES `JobRuns` (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_ConditionChecks_WorkflowRun_id` ON `ConditionChecks` (`WorkflowRun_id`);

CREATE TABLE `Endpoints` (
	`MasterObject_id` INTEGER NOT NULL, 
	`Name` VARCHAR(100) NOT NULL, 
	`Site_MasterObject_id` INTEGER, 
	`Application_MasterObject_id` INTEGER, 
	`Path` VARCHAR(256) NOT NULL, 
	`FilenamePattern` VARCHAR(128) NOT NULL, 
	`Description` VARCHAR(256), 
	PRIMARY KEY (`MasterObject_id`), 
	FOREIGN KEY(`MasterObject_id`) REFERENCES `MasterObjects` (id) ON DELETE CASCADE, 
	UNIQUE (`Name`), 
	FOREIGN KEY(`Site_MasterObject_id`) REFERENCES `Sites` (`MasterObject_id`) ON DELETE SET NULL, 
	FOREIGN KEY(`Application_MasterObject_id`) REFERENCES `Applications` (`MasterObject_id`) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `JobStepParameters` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`JobStep_id` INTEGER NOT NULL, 
	`ParameterName` VARCHAR(100) NOT NULL, 
	`ParameterValue` TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(`JobStep_id`) REFERENCES `JobSteps` (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE TABLE `Reactions` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`Job_MasterObject_id` INTEGER, 
	`Item_id` INTEGER, 
	`Section` VARCHAR(10) NOT NULL DEFAULT 'NEXT', 
	`ReactionOrder` INTEGER NOT NULL DEFAULT 1, 
	`WhenTest` VARCHAR(20) NOT NULL DEFAULT 'FAILED', 
	`WhenReturnCodes` VARCHAR(100), 
	`WhenCondition` TEXT, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_reaction_one_owner CHECK ((Job_MasterObject_id IS NULL) <> (Item_id IS NULL)), 
	FOREIGN KEY(`Job_MasterObject_id`) REFERENCES `Jobs` (`MasterObject_id`) ON DELETE CASCADE, 
	FOREIGN KEY(`Item_id`) REFERENCES `WorkflowItems` (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_Reactions_Item_id` ON `Reactions` (`Item_id`);

CREATE INDEX `ix_Reactions_Job_MasterObject_id` ON `Reactions` (`Job_MasterObject_id`);

CREATE TABLE `WorkflowItemVariables` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`Item_id` INTEGER NOT NULL, 
	`VarName` VARCHAR(100) NOT NULL, 
	`VarValue` TEXT, 
	`IsSecret` BOOL DEFAULT false, 
	`Description` TEXT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_item_var UNIQUE (`Item_id`, `VarName`), 
	FOREIGN KEY(`Item_id`) REFERENCES `WorkflowItems` (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_WorkflowItemVariables_Item_id` ON `WorkflowItemVariables` (`Item_id`);

CREATE TABLE `WorkflowPrerequisiteChecks` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`WorkflowRun_id` INTEGER NOT NULL, 
	`Path` VARCHAR(1000) NOT NULL, 
	`Attempt` INTEGER NOT NULL DEFAULT 1, 
	`Kind` VARCHAR(12) NOT NULL, 
	`TargetName` VARCHAR(100), 
	`Result` VARCHAR(10) NOT NULL, 
	`SeenStatus` VARCHAR(20), 
	`UsedRunID` VARCHAR(36), 
	`Message` TEXT, 
	`CheckedDateTime` DATETIME(6) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(`WorkflowRun_id`) REFERENCES `JobRuns` (id) ON DELETE CASCADE
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_WorkflowPrerequisiteChecks_WorkflowRun_id` ON `WorkflowPrerequisiteChecks` (`WorkflowRun_id`);

CREATE TABLE `WorkflowRunItems` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`WorkflowRun_id` INTEGER NOT NULL, 
	`Item_id` INTEGER, 
	`Path` VARCHAR(1000) NOT NULL, 
	`ItemName` VARCHAR(100) NOT NULL, 
	`JobKey` VARCHAR(320) NOT NULL, 
	`ItemOrder` INTEGER NOT NULL DEFAULT 1, 
	`Status` VARCHAR(20) NOT NULL DEFAULT 'PENDING', 
	`Reason` VARCHAR(40), 
	`ReturnCode` INTEGER, 
	`StatusBeforeOverride` VARCHAR(20), 
	`ProcessID` INTEGER, 
	`ChildRun_id` INTEGER, 
	`Attempt` INTEGER NOT NULL DEFAULT 0, 
	`StartedDateTime` DATETIME(6), 
	`EndedDateTime` DATETIME(6), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workflow_run_item_path UNIQUE (`WorkflowRun_id`, `Path`), 
	FOREIGN KEY(`WorkflowRun_id`) REFERENCES `JobRuns` (id) ON DELETE CASCADE, 
	FOREIGN KEY(`Item_id`) REFERENCES `WorkflowItems` (id) ON DELETE SET NULL, 
	FOREIGN KEY(`ChildRun_id`) REFERENCES `JobRuns` (id) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_WorkflowRunItems_WorkflowRun_id` ON `WorkflowRunItems` (`WorkflowRun_id`);

CREATE TABLE `Operations` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`JobRun_id` INTEGER NOT NULL, 
	`Seq` INTEGER NOT NULL, 
	`JobStep_id` INTEGER, 
	`StepOrder` INTEGER, 
	`StepNumber` VARCHAR(50), 
	`Iteration` VARCHAR(50), 
	`OpType` VARCHAR(50) NOT NULL, 
	`OpStatus` VARCHAR(20) NOT NULL, 
	`SourceEndpoint_id` INTEGER, 
	`SourcePath` TEXT, 
	`SourceFilename` VARCHAR(255), 
	`SourceSize` BIGINT, 
	`DestEndpoint_id` INTEGER, 
	`DestPath` TEXT, 
	`DestFilename` VARCHAR(255), 
	`DestSize` BIGINT, 
	`Checksum` VARCHAR(64), 
	`Details` TEXT, 
	`ErrorMessage` TEXT, 
	`StartedDateTime` DATETIME(6), 
	`EndedDateTime` DATETIME(6), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_run_seq UNIQUE (`JobRun_id`, `Seq`), 
	FOREIGN KEY(`JobRun_id`) REFERENCES `JobRuns` (id) ON DELETE CASCADE, 
	FOREIGN KEY(`JobStep_id`) REFERENCES `JobSteps` (id) ON DELETE SET NULL, 
	FOREIGN KEY(`SourceEndpoint_id`) REFERENCES `Endpoints` (`MasterObject_id`) ON DELETE SET NULL, 
	FOREIGN KEY(`DestEndpoint_id`) REFERENCES `Endpoints` (`MasterObject_id`) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_Operations_DestFilename` ON `Operations` (`DestFilename`);

CREATE INDEX `ix_Operations_JobRun_id` ON `Operations` (`JobRun_id`);

CREATE INDEX `ix_Operations_SourceFilename` ON `Operations` (`SourceFilename`);

CREATE TABLE `ReactionActions` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`Reaction_id` INTEGER NOT NULL, 
	`ActionOrder` INTEGER NOT NULL DEFAULT 1, 
	`Action` VARCHAR(30) NOT NULL, 
	`MaxTimes` INTEGER, 
	`WaitSeconds` INTEGER, 
	`RerunMode` VARCHAR(10), 
	`TargetItem_id` INTEGER, 
	`TargetJob_MasterObject_id` INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(`Reaction_id`) REFERENCES `Reactions` (id) ON DELETE CASCADE, 
	FOREIGN KEY(`TargetItem_id`) REFERENCES `WorkflowItems` (id) ON DELETE CASCADE, 
	FOREIGN KEY(`TargetJob_MasterObject_id`) REFERENCES `Jobs` (`MasterObject_id`) ON DELETE RESTRICT
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_ReactionActions_Reaction_id` ON `ReactionActions` (`Reaction_id`);

CREATE TABLE `WorkflowPrerequisites` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`Item_id` INTEGER NOT NULL, 
	`TargetItem_id` INTEGER, 
	`Test` VARCHAR(20) NOT NULL DEFAULT 'SUCCESS', 
	`ReturnCodes` VARCHAR(100), 
	`Condition` TEXT, 
	`Kind` VARCHAR(12) NOT NULL DEFAULT 'JOB', 
	`TargetName` VARCHAR(100), 
	`TargetJob_MasterObject_id` INTEGER, 
	`LookBackHours` INTEGER, 
	`OnlyAfterStart` BOOL NOT NULL DEFAULT false, 
	`Endpoint_MasterObject_id` INTEGER, 
	`FilePattern` VARCHAR(256), 
	`MinAgeSeconds` INTEGER, 
	`TimeCondition` TEXT, 
	`WaitMode` VARCHAR(10) NOT NULL DEFAULT 'DEFAULT', 
	`WaitMinutes` INTEGER, 
	`WaitUntil` VARCHAR(5), 
	`WaitFrom` VARCHAR(10) NOT NULL DEFAULT 'OTHERS', 
	`WaitFromPrerequisite_id` INTEGER, 
	`Required` BOOL NOT NULL DEFAULT true, 
	PRIMARY KEY (id), 
	FOREIGN KEY(`Item_id`) REFERENCES `WorkflowItems` (id) ON DELETE CASCADE, 
	FOREIGN KEY(`TargetItem_id`) REFERENCES `WorkflowItems` (id) ON DELETE CASCADE, 
	FOREIGN KEY(`TargetJob_MasterObject_id`) REFERENCES `Jobs` (`MasterObject_id`) ON DELETE RESTRICT, 
	FOREIGN KEY(`Endpoint_MasterObject_id`) REFERENCES `Endpoints` (`MasterObject_id`) ON DELETE RESTRICT, 
	FOREIGN KEY(`WaitFromPrerequisite_id`) REFERENCES `WorkflowPrerequisites` (id) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_WorkflowPrerequisites_Item_id` ON `WorkflowPrerequisites` (`Item_id`);

CREATE TABLE `ReactionEvents` (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	`JobRun_id` INTEGER NOT NULL, 
	`WorkflowRun_id` INTEGER, 
	`WorkflowPath` VARCHAR(1000), 
	`ReactionAction_id` INTEGER, 
	`Action` VARCHAR(30) NOT NULL, 
	`Result` VARCHAR(20) NOT NULL DEFAULT 'TOOK_EFFECT', 
	`Message` TEXT, 
	`EventDateTime` DATETIME(6) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(`JobRun_id`) REFERENCES `JobRuns` (id) ON DELETE CASCADE, 
	FOREIGN KEY(`WorkflowRun_id`) REFERENCES `JobRuns` (id) ON DELETE CASCADE, 
	FOREIGN KEY(`ReactionAction_id`) REFERENCES `ReactionActions` (id) ON DELETE SET NULL
)ENGINE=InnoDB CHARSET=utf8mb4 COLLATE utf8mb4_bin;

CREATE INDEX `ix_ReactionEvents_JobRun_id` ON `ReactionEvents` (`JobRun_id`);

CREATE INDEX `ix_ReactionEvents_WorkflowRun_id` ON `ReactionEvents` (`WorkflowRun_id`);

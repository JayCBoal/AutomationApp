-- ============================================================================
-- Seed_MasterObjects_Data.sql
-- Seed Data Initialization for MasterObjects & Step Engine Catalog
-- ============================================================================

SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------------------------------------------------------
-- 1. Step Types Catalog & Parameter Definitions
-- ----------------------------------------------------------------------------
TRUNCATE TABLE JobStepParameters;
TRUNCATE TABLE JobSteps;
TRUNCATE TABLE StepDefinitions;
TRUNCATE TABLE StepTypes;

INSERT INTO StepTypes (id, Name, Description) VALUES
(1, 'COPY_FILES', 'Local file transfer and archiving operation'),
(2, 'SQL_EXEC', 'Executes SQL scripts or database commands'),
(3, 'REST_CALL', 'Triggers HTTP REST API endpoints'),
(4, 'SFTP_TRANSFER', 'Secure FTP file upload or download');

INSERT INTO StepDefinitions (StepType_id, ParamName, IsRequired, Description) VALUES
-- COPY_FILES Parameters
(1, 'SourceFolder', 1, 'Directory containing source files'),
(1, 'SourcePattern', 1, 'File match pattern/glob'),
(1, 'TargetFolder', 1, 'Destination directory'),
(1, 'ArchiveFolder', 0, 'Optional post-processing archive directory'),
(1, 'RenamePattern', 0, 'Pattern for destination filename transformation'),

-- SQL_EXEC Parameters
(2, 'ConnectionString', 1, 'Database target connection key or URI'),
(2, 'SqlQuery', 1, 'SQL statement or script block to execute'),

-- REST_CALL Parameters
(3, 'EndpointUrl', 1, 'Target API URL'),
(3, 'HttpMethod', 1, 'HTTP Method (GET, POST, PUT, DELETE)'),
(3, 'Headers', 0, 'JSON formatted HTTP headers'),
(3, 'Payload', 0, 'Body payload string or JSON template'),

-- SFTP_TRANSFER Parameters
(4, 'Site_MasterObject_id', 1, 'Target SFTP Site entity reference'),
(4, 'Direction', 1, 'Transfer mode: UPLOAD or DOWNLOAD'),
(4, 'RemotePath', 1, 'Remote server directory path'),
(4, 'LocalPath', 1, 'Local agent directory path');


-- ----------------------------------------------------------------------------
-- 2. Base Domain Entities (Applications, Entities, Credentials, Sites)
-- ----------------------------------------------------------------------------

-- Application: JAY_AUTO
INSERT INTO MasterObjects (ObjectType, CreatedBy) VALUES ('APPLICATION', 'system');
SET @app_jay_auto_id = LAST_INSERT_ID();

INSERT INTO Applications (MasterObject_id, Name, Abbr, Description, SupportDL) VALUES 
(@app_jay_auto_id, 'JAY_AUTO', 'JAUTO', 'Jay Auto System Applications', 'support@jayauto.com');

-- Entity: LEGAL
INSERT INTO MasterObjects (ObjectType, CreatedBy) VALUES ('ENTITY', 'system');
SET @entity_legal_id = LAST_INSERT_ID();

INSERT INTO Entities (MasterObject_id, Name, Abbr, Description) VALUES 
(@entity_legal_id, 'LEGAL', 'LGL', 'Legal Department Operations');

-- Entity: MASSMARKET
INSERT INTO MasterObjects (ObjectType, CreatedBy) VALUES ('ENTITY', 'system');
SET @entity_massmarket_id = LAST_INSERT_ID();

INSERT INTO Entities (MasterObject_id, Name, Abbr, Description) VALUES 
(@entity_massmarket_id, 'MASSMARKET', 'MMKT', 'Mass Market Operations');

-- Site: Local Appliance SFTP Source (Owned by LEGAL)
INSERT INTO MasterObjects (ObjectType, CreatedBy) VALUES ('SITE', 'system');
SET @site_applp_id = LAST_INSERT_ID();

INSERT INTO Sites (MasterObject_id, Name, Entity_MasterObject_id, Host, Port, Protocol, Description) VALUES 
(@site_applp_id, 'APPLP_LOCAL_SITE', @entity_legal_id, 'localhost', 22, 'LOCAL', 'Local Appliance SFTP Storage');


-- ----------------------------------------------------------------------------
-- 3. Consolidated Endpoints
-- ----------------------------------------------------------------------------
INSERT INTO Endpoints (EndpointType, Application_MasterObject_id, Entity_MasterObject_id, Site_MasterObject_id, Path, FilenamePattern) VALUES
('SOURCE', @app_jay_auto_id, @entity_legal_id, @site_applp_id, '/home/jayboal/Testing/applp/ABC/from_app', 'Extract_*.csv'),
('DELIVERY', @app_jay_auto_id, @entity_massmarket_id, @site_applp_id, '/home/jayboal/Testing/applp/ABC/to_app', '*.txt');


-- ----------------------------------------------------------------------------
-- 4. Processes & Jobs (Decoupled Architecture)
-- ----------------------------------------------------------------------------

-- Process 1: Client Data Extract Process
INSERT INTO MasterObjects (ObjectType, CreatedBy) VALUES ('PROCESS', 'system');
SET @proc_extract_id = LAST_INSERT_ID();

INSERT INTO Processes (MasterObject_id, Name, Description, Severity) VALUES 
(@proc_extract_id, 'DEV-LEGAL-JAYCO-ALL_CLNT_EXTRACT', 'Client Data Extract Process', 1);

-- Job 1: EXTRACT_DATA
INSERT INTO MasterObjects (ObjectType, CreatedBy) VALUES ('JOB', 'system');
SET @job_extract_id = LAST_INSERT_ID();

INSERT INTO Jobs (MasterObject_id, Process_MasterObject_id, Name, JobOrder, Description) VALUES 
(@job_extract_id, @proc_extract_id, 'EXTRACT_DATA', 1, 'Executes Extract File Copy/Archiving');


-- Process 2: Massmarket Feed Process
INSERT INTO MasterObjects (ObjectType, CreatedBy) VALUES ('PROCESS', 'system');
SET @proc_feed_id = LAST_INSERT_ID();

INSERT INTO Processes (MasterObject_id, Name, Description, Severity) VALUES 
(@proc_feed_id, 'DEV-ABC-MASSMARKET-FEED_CLNT', 'Massmarket Feed Process', 1);

-- Job 2: SEND_DATA
INSERT INTO MasterObjects (ObjectType, CreatedBy) VALUES ('JOB', 'system');
SET @job_send_id = LAST_INSERT_ID();

INSERT INTO Jobs (MasterObject_id, Process_MasterObject_id, Name, JobOrder, Description) VALUES 
(@job_send_id, @proc_feed_id, 'SEND_DATA', 1, 'Sends Feed Data to Target');


-- ----------------------------------------------------------------------------
-- 5. Default System Tags & Assignments
-- ----------------------------------------------------------------------------
INSERT INTO MasterObjects (ObjectType, CreatedBy) VALUES ('TAG', 'system');
SET @tag_env_dev_id = LAST_INSERT_ID();
INSERT INTO Tags (MasterObject_id, Name, Slug, Category, Description) VALUES 
(@tag_env_dev_id, 'Environment:DEV', 'env-dev', 'Environment', 'Development Tier Tasks');

INSERT INTO MasterObjects (ObjectType, CreatedBy) VALUES ('TAG', 'system');
SET @tag_dept_legal_id = LAST_INSERT_ID();
INSERT INTO Tags (MasterObject_id, Name, Slug, Category, Description) VALUES 
(@tag_dept_legal_id, 'Dept:Legal', 'dept-legal', 'Department', 'Legal Department Automation');

-- Assign Tags to Processes via MasterObject IDs
INSERT INTO TagAssignments (Tag_MasterObject_id, Target_MasterObject_id) VALUES
(@tag_env_dev_id, @proc_extract_id),
(@tag_dept_legal_id, @proc_extract_id),
(@tag_env_dev_id, @proc_feed_id);


-- ----------------------------------------------------------------------------
-- 6. Dynamic Hierarchical Variables
-- ----------------------------------------------------------------------------
INSERT INTO Variables (MasterObject_id, VarName, VarValue, Description, CreatedBy) VALUES
-- Entity Level Variables
(@entity_legal_id, 'WorkingFolder', '/home/jayboal/Testing/working/DEV/LEGAL/JAYCO/ALL_CLNT_EXTRACT', 'Legal default working folder', 'system'),
(@entity_legal_id, 'ArchiveFolder', '/home/jayboal/Testing/archive/DEV/LEGAL/JAYCO/ALL_CLNT_EXTRACT', 'Legal default archive folder', 'system'),

-- Process Level Variable Overrides
(@proc_extract_id, 'SourceFilenamePattern', 'Extract_<yyyyMMdd>.csv', 'File pattern for client extract', 'system'),
(@proc_feed_id, 'SourceFilenamePattern', '<yyyyMMdd>_*file*.txt', 'File pattern for massmarket feed', 'system');

SET FOREIGN_KEY_CHECKS = 1;
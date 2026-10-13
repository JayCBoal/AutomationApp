-- ============================================================================
-- AutoApp sample data
--
-- A small, working set of definitions to develop and demonstrate with: two
-- applications, an external entity with an SFTP site, three endpoints, and two
-- jobs that hand a file from one to the other.
--
-- Run it against empty tables: after SQL/Create_Tables.sql on MariaDB, or
-- through autoapp/create_dev_db.py, which builds a local SQLite database.
-- It is plain SQL with explicit ids, so it runs on either.
--
-- The sample files live under /tmp/autoapp_sample. To put them elsewhere,
-- change the two 'Root' variables in section 5.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Step catalog: the step types that have a handler in engine/handlers
-- ----------------------------------------------------------------------------
INSERT INTO StepTypes (id, Name, Code, Description) VALUES
(1, 'Copy Files', 'COPY_FILES', 'Copies or moves files between a registered endpoint and the job''s working folder');

INSERT INTO StepDefinitions (StepType_id, ParameterName, DataType, IsRequired, DefaultValue, Description) VALUES
(1, 'Source',         'STRING',  0, NULL,    'Path or pattern inside the job''s working folder. Set this or SourceEndpoint.'),
(1, 'SourceEndpoint', 'STRING',  0, NULL,    'Name of the registered endpoint to read from. Set this or Source.'),
(1, 'Dest',           'STRING',  0, NULL,    'Folder or filename inside the job''s working folder. Set this or DestEndpoint.'),
(1, 'DestEndpoint',   'STRING',  0, NULL,    'Name of the registered endpoint to write to. Set this or Dest.'),
(1, 'Move',           'BOOLEAN', 0, 'False', 'Remove each file from the source once it has arrived'),
(1, 'CreateFolder',   'BOOLEAN', 0, 'True',  'Create the destination folder if it does not exist'),
(1, 'Checksum',       'BOOLEAN', 0, 'False', 'Record each file''s SHA-256 and verify the copy against it'),
(1, 'AllowNoFiles',   'BOOLEAN', 0, 'False', 'Succeed when no files match. By default a step that finds nothing fails.'),
(1, 'LogLevel',       'STRING',  0, NULL,    'Job log level for this step alone: DEBUG, DETAIL, SUMMARY or SILENT');

-- ----------------------------------------------------------------------------
-- 2. Master objects. Every application, entity, site, tag and job has one row
--    here, and a row with the same id in its own table.
-- ----------------------------------------------------------------------------
INSERT INTO MasterObjects (id, ObjectType) VALUES
(1, 'APPLICATION'),
(2, 'APPLICATION'),
(3, 'ENTITY'),
(4, 'SITE'),
(5, 'JOB'),
(6, 'JOB'),
(7, 'TAG'),
(8, 'TAG');

INSERT INTO Applications (MasterObject_id, Name, Abbr, Description) VALUES
(1, 'LEGAL_APP',   'LGL', 'Legal case management system'),
(2, 'BILLING_APP', 'BIL', 'Client billing system');

-- An entity is an outside party; a site is one of its servers.
INSERT INTO Entities (MasterObject_id, Name, Abbr, Description) VALUES
(3, 'ACME_BANK', 'ACME', 'Bank that receives payment files');

INSERT INTO Sites (MasterObject_id, Entity_MasterObject_id, Name, Host, Port, Protocol, Description) VALUES
(4, 3, 'ACME_BANK_SFTP', 'sftp.acmebank.example', 22, 'SFTP', 'Acme Bank file transfer server');

-- ----------------------------------------------------------------------------
-- 3. Endpoints: the registered places files come from and go to.
--    ${APP.Root} is the Root variable of the endpoint's own application.
-- ----------------------------------------------------------------------------
INSERT INTO Endpoints (id, Name, Application_MasterObject_id, Site_MasterObject_id, Path, FilenamePattern, Description) VALUES
(1, 'LEGAL_APP_EXTRACTS',  1, NULL, '${APP.Root}/outbox', '${FilePattern}', 'Client extract files produced by the legal application'),
(2, 'BILLING_APP_INBOX',   2, NULL, '${APP.Root}/inbox',  '*.csv',          'Files for the billing application to load'),
(3, 'ACME_BANK_PAYMENTS',  2, 4,    '/inbound/payments',  'PAY_*.csv',      'Payment files sent to Acme Bank. On a remote site, so not usable until the SFTP step type exists.');

-- ----------------------------------------------------------------------------
-- 4. Jobs and their steps
-- ----------------------------------------------------------------------------
INSERT INTO Jobs (MasterObject_id, JobKey, Description) VALUES
(5, 'DEV-LEGAL-COLLECT_AND_DELIVER', 'Collects extract files from the legal application, archives them and delivers them to billing'),
(6, 'DEV-BILLING-LOAD',              'Picks up the files delivered to billing');

INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle) VALUES
(1, 5, 1, 1, 'Collect extracts'),
(2, 5, 1, 2, 'Archive'),
(3, 5, 1, 3, 'Deliver to billing'),
(4, 6, 1, 1, 'Pick up from inbox');

INSERT INTO JobStepParameters (JobStep_id, ParameterName, ParameterValue) VALUES
(1, 'SourceEndpoint', 'LEGAL_APP_EXTRACTS'),
(1, 'Dest',           'incoming'),
(2, 'Source',         'incoming/*.csv'),
(2, 'Dest',           'archive/${SYS:YYYYMMDD}'),
(3, 'Source',         'incoming/*.csv'),
(3, 'DestEndpoint',   'BILLING_APP_INBOX'),
(3, 'Move',           'True'),
(4, 'SourceEndpoint', 'BILLING_APP_INBOX'),
(4, 'Dest',           'to_load'),
(4, 'Move',           'True');

-- ----------------------------------------------------------------------------
-- 5. Variables. A variable belongs to any master object.
-- ----------------------------------------------------------------------------
INSERT INTO Variables (MasterObject_id, VarName, VarValue, Description) VALUES
(1, 'Root',        '/tmp/autoapp_sample/legal_app',   'Where the legal application keeps its files'),
(2, 'Root',        '/tmp/autoapp_sample/billing_app', 'Where the billing application keeps its files'),
(5, 'FilePattern', 'Legal_Batch_*.csv',               'Which extract files this job collects');

-- ----------------------------------------------------------------------------
-- 6. Tags. Stored and assigned here; nothing reads them yet.
-- ----------------------------------------------------------------------------
INSERT INTO Tags (MasterObject_id, TagName, Category, Description) VALUES
(7, 'Environment:DEV', 'Environment', 'Development jobs'),
(8, 'Dept:Legal',      'Department',  'Legal department automation');

INSERT INTO TagAssignments (Tag_MasterObject_id, Target_MasterObject_id) VALUES
(7, 5),
(7, 6),
(8, 5);

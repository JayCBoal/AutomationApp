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
-- Added only if it is not there already: the API server creates it when it first starts.
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Copy Files', 'COPY_FILES', 'Copies or moves files between a registered endpoint and the job''s working folder'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'COPY_FILES');

-- The parameters each step type takes are not listed here. They are declared by the handlers
-- in the code and copied into the StepDefinitions table by:  python3 -m app.catalog
-- (the API server does the same each time it starts).

-- ----------------------------------------------------------------------------
-- 2. Master objects. Every application, entity, site, tag, job and endpoint has one row
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
(8, 'TAG'),
(9, 'ENDPOINT'),
(10, 'ENDPOINT'),
(11, 'ENDPOINT');

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
INSERT INTO Endpoints (MasterObject_id, Name, Application_MasterObject_id, Site_MasterObject_id, Path, FilenamePattern, Description) VALUES
(9, 'LEGAL_APP_EXTRACTS',  1, NULL, '${APP.Root}/outbox', '${FilePattern}', 'Client extract files produced by the legal application'),
(10, 'BILLING_APP_INBOX',   2, NULL, '${APP.Root}/inbox',  '*.csv',          'Files for the billing application to load'),
(11, 'ACME_BANK_PAYMENTS',  2, 4,    '/inbound/payments',  'PAY_*.csv',      'Payment files sent to Acme Bank. On a remote site, so not usable until the SFTP step type exists.');

-- ----------------------------------------------------------------------------
-- 4. Jobs and their steps
-- ----------------------------------------------------------------------------
INSERT INTO Jobs (MasterObject_id, JobKey, Description) VALUES
(5, 'DEV-LEGAL-COLLECT_AND_DELIVER', 'Collects extract files from the legal application, archives them and delivers them to billing'),
(6, 'DEV-BILLING-LOAD',              'Picks up the files delivered to billing');

INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle)
SELECT 1, 5, id, 1, 'Collect extracts'   FROM StepTypes WHERE Code = 'COPY_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle)
SELECT 2, 5, id, 2, 'Archive'            FROM StepTypes WHERE Code = 'COPY_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle)
SELECT 3, 5, id, 3, 'Deliver to billing' FROM StepTypes WHERE Code = 'COPY_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle)
SELECT 4, 6, id, 1, 'Pick up from inbox' FROM StepTypes WHERE Code = 'COPY_FILES';

INSERT INTO JobStepParameters (JobStep_id, ParameterName, ParameterValue) VALUES
(1, 'SourceEndpoint', 'LEGAL_APP_EXTRACTS'),
(1, 'Dest',           'incoming'),
(2, 'Source',         'incoming/*.csv'),
(2, 'Dest',           'archive/${DATE:yyyyMMdd}'),
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

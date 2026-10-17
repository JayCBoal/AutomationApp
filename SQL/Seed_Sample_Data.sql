-- ============================================================================
-- AutoApp sample data
--
-- A small, working set of definitions to develop and demonstrate with: three
-- applications, an external entity with an SFTP site, four endpoints, and two
-- pairs of jobs that hand files from one to the other:
--
--   DEV-LEGAL-COLLECT_AND_DELIVER -> DEV-BILLING-LOAD           (copy and move)
--   DEV-BILLING-INVOICE_EXPORT    -> DEV-FINANCE-LOAD_REPORTS   (SQL export, check,
--                                                                zip, unzip, clean up)
--
-- The export job shows flow control (docs/FLOW_CONTROL.md): it sends the batch only if
-- its check passed, keeping a copy of each export first, and otherwise holds the
-- exports back and fails, saying what was wrong.
--
-- The export jobs query the sample sales database, SQL/Sample_Sales_Data.sql.
--
-- Run it against empty tables: after SQL/Create_Tables.sql on MariaDB, or
-- through autoapp/create_dev_db.py, which builds a local SQLite database.
-- It is plain SQL with explicit ids, so it runs on either.
--
-- The sample files live under /tmp/autoapp_sample. To put them elsewhere,
-- change the 'Root' variables in section 5. The SalesDbUrl variable there says
-- where the sales database is.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Step catalog: the step types that have a handler in engine/handlers
-- ----------------------------------------------------------------------------
-- Added only if it is not there already: the API server creates it when it first starts.
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Copy Files', 'COPY_FILES', 'Copies or moves files between a registered endpoint and the job''s working folder'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'COPY_FILES');
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Delete Files', 'DELETE_FILES', 'Removes files, for example to clear a working folder or to keep only recent archives'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'DELETE_FILES');
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Check Files', 'CHECK_FILES', 'Fails the job unless the files look right: how many there are, none empty, none too old'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'CHECK_FILES');
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Zip Files', 'ZIP_FILES', 'Packs files into one .zip archive'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'ZIP_FILES');
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Unzip Files', 'UNZIP_FILES', 'Takes the files out of one or more .zip archives'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'UNZIP_FILES');
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Run SQL', 'RUN_SQL', 'Runs one SQL statement; a query''s rows can be written to a CSV file'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'RUN_SQL');
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'If', 'IF', 'Runs one set of steps or another, depending on a condition'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'IF');
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Then', 'THEN', 'The steps that run when the condition holds'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'THEN');
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Else', 'ELSE', 'The steps that run when no condition holds'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'ELSE');
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'For Each File', 'FOR_EACH_FILE', 'Runs its steps once for each file at a location'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'FOR_EACH_FILE');

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
(11, 'ENDPOINT'),
(12, 'APPLICATION'),
(13, 'JOB'),
(14, 'ENDPOINT'),
(15, 'JOB'),
(16, 'TAG'),
(17, 'TAG'),
(18, 'TAG'),
(19, 'SCHEDULER'),
(20, 'SCHEDULER');

INSERT INTO Applications (MasterObject_id, Name, Abbr, Description) VALUES
(1, 'LEGAL_APP',   'LGL', 'Legal case management system'),
(2, 'BILLING_APP', 'BIL', 'Client billing system'),
(12, 'FINANCE_APP', 'FIN', 'Finance reporting system');

-- An entity is an outside party; a site is one of its servers.
INSERT INTO Entities (MasterObject_id, Name, Abbr, Description) VALUES
(3, 'ACME_BANK', 'ACME', 'Bank that receives payment files');

INSERT INTO Sites (MasterObject_id, Entity_MasterObject_id, Name, Host, Port, Protocol, Description) VALUES
(4, 3, 'ACME_BANK_SFTP', 'sftp.acmebank.example', 22, 'SFTP', 'Acme Bank file transfer server');

-- A scheduler is a workload automation product that runs AutoApp jobs. The web
-- interface's Run Job page acts as one, under this name.
-- STANDIN is the Stand-in Scheduler in demo/scheduler_standin, on port 8100; AutoApp reads its jobs'
-- parameters through its API, with the token in its ApiToken variable (section 5).
INSERT INTO Schedulers (MasterObject_id, Name, Technology, ApiUrl, Description) VALUES
(19, 'AutoApp UI', 'OTHER',   NULL,                    'The Run Job page of the AutoApp web interface'),
(20, 'STANDIN',    'STANDIN', 'http://localhost:8100', 'The Stand-in Scheduler (demo/scheduler_standin)');

-- ----------------------------------------------------------------------------
-- 3. Endpoints: the registered places files come from and go to.
--    ${APP.Root} is the Root variable of the endpoint's own application.
-- ----------------------------------------------------------------------------
INSERT INTO Endpoints (MasterObject_id, Name, Application_MasterObject_id, Site_MasterObject_id, Path, FilenamePattern, Description) VALUES
(9, 'LEGAL_APP_EXTRACTS',  1, NULL, '${APP.Root}/outbox', '${FilePattern}', 'Client extract files produced by the legal application'),
(10, 'BILLING_APP_INBOX',   2, NULL, '${APP.Root}/inbox',  '*.csv',          'Files for the billing application to load'),
(11, 'ACME_BANK_PAYMENTS',  2, 4,    '/inbound/payments',  'PAY_*.csv',      'Payment files sent to Acme Bank. On a remote site, so not usable until the SFTP step type exists.'),
(14, 'FINANCE_APP_INBOX',  12, NULL, '${APP.Root}/inbox',  'Billing_*.zip',  'Billing extracts for the finance application to report on');

-- ----------------------------------------------------------------------------
-- 4. Jobs and their steps
-- ----------------------------------------------------------------------------
INSERT INTO Jobs (MasterObject_id, JobKey, Description) VALUES
(5, 'DEV-LEGAL-COLLECT_AND_DELIVER', 'Collects extract files from the legal application, archives them and delivers them to billing'),
(6, 'DEV-BILLING-LOAD',              'Picks up the files delivered to billing'),
(13, 'DEV-BILLING-INVOICE_EXPORT',   'Exports open invoices and payments from the sales database and sends them to finance as one archive'),
(15, 'DEV-FINANCE-LOAD_REPORTS',     'Picks up the billing archive, unpacks it, checks the reports and keeps a month of archives');

INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 1, 5, id, 1, 'Collect extracts',   'Collect_extracts' FROM StepTypes WHERE Code = 'COPY_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 2, 5, id, 2, 'Archive',            'Archive' FROM StepTypes WHERE Code = 'COPY_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 3, 5, id, 3, 'Deliver to billing', 'Deliver_to_billing' FROM StepTypes WHERE Code = 'COPY_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 4, 6, id, 1, 'Pick up from inbox', 'Pick_up_from_inbox' FROM StepTypes WHERE Code = 'COPY_FILES';

INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 5, 13, id, 1, 'Export open invoices',   'Export_open_invoices' FROM StepTypes WHERE Code = 'RUN_SQL';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 6, 13, id, 2, 'Export payments',        'Export_payments' FROM StepTypes WHERE Code = 'RUN_SQL';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 7, 13, id, 3, 'Check both exports',     'Check_both_exports' FROM StepTypes WHERE Code = 'CHECK_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 8, 13, id, 2, 'Send to finance',        'Send_to_finance' FROM StepTypes WHERE Code = 'ZIP_FILES';

-- Step 4 decides what happens to the exports: sent if the check passed, else held back.
-- Its steps are inserted before step 8 (Send to finance) is moved inside it, below.
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 14, 13, id, 4, 'Send only a sound batch', 'Send_only_a_sound_batch' FROM StepTypes WHERE Code = 'IF';
INSERT INTO JobSteps (id, Job_MasterObject_id, ParentStep_id, StepType_id, StepOrder)
SELECT 15, 13, 14, id, 1 FROM StepTypes WHERE Code = 'THEN';
INSERT INTO JobSteps (id, Job_MasterObject_id, ParentStep_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 16, 13, 15, id, 1, 'Keep a copy of each export', 'Keep_a_copy' FROM StepTypes WHERE Code = 'FOR_EACH_FILE';
INSERT INTO JobSteps (id, Job_MasterObject_id, ParentStep_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 17, 13, 16, id, 1, 'Copy it to the record', 'Copy_it_to_the_record' FROM StepTypes WHERE Code = 'COPY_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, ParentStep_id, StepType_id, StepOrder)
SELECT 18, 13, 14, id, 2 FROM StepTypes WHERE Code = 'ELSE';
INSERT INTO JobSteps (id, Job_MasterObject_id, ParentStep_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 19, 13, 18, id, 1, 'Hold the exports back', 'Hold_the_exports_back' FROM StepTypes WHERE Code = 'COPY_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, ParentStep_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 20, 13, 18, id, 2, 'Say what was wrong', 'Say_what_was_wrong' FROM StepTypes WHERE Code = 'CHECK_FILES';
UPDATE JobSteps SET ParentStep_id = 15 WHERE id = 8;
UPDATE JobSteps SET OnFailure = 'CONTINUE' WHERE id = 7;

INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 9, 15, id, 1, 'Pick up the archive',    'Pick_up_the_archive' FROM StepTypes WHERE Code = 'COPY_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 10, 15, id, 2, 'Unpack',                'Unpack' FROM StepTypes WHERE Code = 'UNZIP_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 11, 15, id, 3, 'Check the reports',     'Check_the_reports' FROM StepTypes WHERE Code = 'CHECK_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 12, 15, id, 4, 'Keep the archive',      'Keep_the_archive' FROM StepTypes WHERE Code = 'COPY_FILES';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 13, 15, id, 5, 'Remove old archives',   'Remove_old_archives' FROM StepTypes WHERE Code = 'DELETE_FILES';

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
(4, 'Move',           'True'),
(5, 'Database',       '${APP:BILLING_APP.SalesDbUrl}'),
(5, 'Statement',      'SELECT i.invoice_no, c.customer_code, c.customer_name, i.invoice_date, i.due_date, i.total_amount, i.status
FROM invoices i JOIN customers c ON c.customer_id = i.customer_id
WHERE i.status IN (''OPEN'', ''OVERDUE'')
ORDER BY i.invoice_no'),
(5, 'ResultFile',     'out/Open_Invoices_${DATE:yyyyMMdd}.csv'),
(5, 'Overwrite',      'True'),
(6, 'Database',       '${APP:BILLING_APP.SalesDbUrl}'),
(6, 'Statement',      'SELECT p.reference, i.invoice_no, c.customer_code, p.payment_date, p.amount, p.method
FROM payments p JOIN invoices i ON i.invoice_id = p.invoice_id JOIN customers c ON c.customer_id = i.customer_id
ORDER BY p.payment_date, p.reference'),
(6, 'ResultFile',     'out/Payments_${DATE:yyyyMMdd}.csv'),
(6, 'Overwrite',      'True'),
(7, 'Source',         'out/*_${DATE:yyyyMMdd}.csv'),
(7, 'MinCount',       '2'),
(7, 'MaxCount',       '2'),
(8, 'Source',         'out/*_${DATE:yyyyMMdd}.csv'),
(8, 'DestEndpoint',   'FINANCE_APP_INBOX'),
(8, 'ArchiveName',    'Billing_${DATE:yyyyMMdd}.zip'),
(8, 'Move',           'True'),
(8, 'Overwrite',      'True'),
(14, 'Condition',     '%{Check_both_exports.Status} = ''SUCCESS'''),
(16, 'Source',        'out/*_${DATE:yyyyMMdd}.csv'),
(16, 'ItemName',      'Export'),
(17, 'Source',        '%{Export.FullName}'),
(17, 'Dest',          'kept/${DATE:yyyyMMdd}'),
(19, 'Source',        'out/*_${DATE:yyyyMMdd}.csv'),
(19, 'Dest',          'held/${DATE:yyyyMMdd}'),
(19, 'Move',          'True'),
(19, 'AllowNoFiles',  'True'),
(20, 'Source',        'held/${DATE:yyyyMMdd}/*.csv'),
(20, 'MinCount',      '2'),
(20, 'MaxCount',      '2'),
(9, 'SourceEndpoint', 'FINANCE_APP_INBOX'),
(9, 'Dest',           'incoming'),
(9, 'Move',           'True'),
(10, 'Source',        'incoming/*.zip'),
(10, 'Dest',          'reports/${DATE:yyyyMMdd}'),
(10, 'Overwrite',     'True'),
(11, 'Source',        'reports/${DATE:yyyyMMdd}/*.csv'),
(11, 'MinCount',      '2'),
(11, 'MaxAgeHours',   '24'),
(12, 'Source',        'incoming/*.zip'),
(12, 'Dest',          'archive'),
(12, 'Move',          'True'),
(13, 'Source',        'archive/*.zip'),
(13, 'OlderThanDays', '${ReportRetentionDays}'),
(13, 'AllowNoFiles',  'True');

-- ----------------------------------------------------------------------------
-- 5. Variables. A variable belongs to any master object.
-- ----------------------------------------------------------------------------
INSERT INTO Variables (MasterObject_id, VarName, VarValue, Description) VALUES
(1, 'Root',        '/tmp/autoapp_sample/legal_app',   'Where the legal application keeps its files'),
(2, 'Root',        '/tmp/autoapp_sample/billing_app', 'Where the billing application keeps its files'),
(12, 'Root',       '/tmp/autoapp_sample/finance_app', 'Where the finance application keeps its files'),
(5, 'FilePattern', 'Legal_Batch_*.csv',               'Which extract files this job collects');

-- A secret: its value is never shown in the web pages or the job log. The jobs
-- that use it name it as ${APP:BILLING_APP.SalesDbUrl}. For MariaDB it would be
-- something like mysql+pymysql://user:password@localhost/autoapp_sales.
INSERT INTO Variables (MasterObject_id, VarName, VarValue, IsSecret, Description) VALUES
(2, 'SalesDbUrl',  'sqlite:////tmp/autoapp_sample/sales.db', 1, 'The billing application''s sales database'),
(20, 'ApiToken',   'standin-dev-token',                      1, 'What the Stand-in Scheduler''s API wants (its STANDIN_TOKEN)');

-- ----------------------------------------------------------------------------
-- 6. Tags. A tag can sit under a parent; names need only be unique under one
--    parent. A tag's variables act as if they were on whatever carries it, and a
--    tag inherits its parent's. Parents come before their children here.
--
--      Environment            (a parent that only makes its children's names clear)
--        DEV                  on the four DEV- jobs
--      Legal                  on LEGAL_APP and the job that collects from it
--      Finance                ReportRetentionDays = 30
--        Reporting            on DEV-FINANCE-LOAD_REPORTS, which uses ${ReportRetentionDays}
-- ----------------------------------------------------------------------------
INSERT INTO Tags (MasterObject_id, Parent_MasterObject_id, Name, Description) VALUES
(16, NULL, 'Environment', 'Which environment a job belongs to'),
(7,  16,   'DEV',         'Development jobs'),
(8,  NULL, 'Legal',       'Legal department automation'),
(17, NULL, 'Finance',     'Finance department automation'),
(18, 17,   'Reporting',   'Finance reporting');

INSERT INTO Variables (MasterObject_id, VarName, VarValue, Description) VALUES
(17, 'ReportRetentionDays', '30', 'How many days of report archives finance keeps');

INSERT INTO TagAssignments (Tag_MasterObject_id, Target_MasterObject_id) VALUES
(7, 5),
(7, 6),
(7, 13),
(7, 15),
(8, 1),
(8, 5),
(18, 15);

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
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Simulate', 'SIMULATE', 'Stands in for real work while a workflow is built and tried: writes what it is told to the job log, waits, and ends with a chosen return code'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'SIMULATE');
INSERT INTO StepTypes (Name, Code, Description)
SELECT 'Set Return Code', 'SET_RETURN_CODE', 'Sets the job''s return code and carries on; if several run, the last one wins'
WHERE NOT EXISTS (SELECT 1 FROM StepTypes WHERE Code = 'SET_RETURN_CODE');

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
(20, 'SCHEDULER'),
(21, 'JOB'),
(22, 'JOB'),
(23, 'JOB'),
(24, 'JOB'),
(25, 'JOB');

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

-- Stand-ins for jobs not built yet, for the sample workflow (section 5): each is one Simulate step.
-- The ledger check ends with return code 4, "differences found", which its Success return codes accept.
INSERT INTO Jobs (MasterObject_id, JobKey, Description, SuccessReturnCodes) VALUES
(21, 'DEV-SIM-CHECK_LEDGER',  'Stand-in: compares what billing loaded with the finance reports. Return code 4: differences found', '0, 4'),
(22, 'DEV-SIM-ALERT_FINANCE', 'Stand-in: tells finance the ledger check failed', NULL),
(23, 'DEV-SIM-RECONCILE',     'Stand-in: reconciles the differences the ledger check found', NULL),
(24, 'DEV-SIM-CLEANUP',       'Stand-in: tidies up after the month end', NULL);

INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 21, 21, id, 1, 'Compare the ledgers', 'Compare_the_ledgers' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 22, 22, id, 1, 'Tell finance', 'Tell_finance' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 23, 23, id, 1, 'Reconcile', 'Reconcile' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 24, 24, id, 1, 'Tidy up', 'Tidy_up' FROM StepTypes WHERE Code = 'SIMULATE';

INSERT INTO JobStepParameters (JobStep_id, ParameterName, ParameterValue) VALUES
(21, 'Messages',    'Comparing what billing loaded with the finance reports
Found 3 differences to reconcile'),
(21, 'WaitSeconds', '2'),
(21, 'ReturnCode',  '4'),
(22, 'Messages',    'Telling finance the ledger check failed'),
(23, 'Messages',    'Reconciling the 3 differences'),
(23, 'WaitSeconds', '1'),
(24, 'Messages',    'Tidying up after the month end');

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

-- ----------------------------------------------------------------------------
-- 5. A sample workflow (docs/WORKFLOWS.md): the two pairs of jobs side by side, then the
--    stand-ins. The ledger check waits for both loads; on failure finance is alerted; on
--    return code 4 the differences are reconciled; then a clean-up runs whatever happened.
-- ----------------------------------------------------------------------------
INSERT INTO Jobs (MasterObject_id, JobKey, JobType, Description) VALUES
(25, 'DEV-MONTH_END_SAMPLE', 'WORKFLOW', 'Sample workflow: legal and billing files, the finance reports, then a ledger check and what follows from it');

INSERT INTO WorkflowItems (id, Workflow_MasterObject_id, ItemName, Job_MasterObject_id, JoinRule, ItemOrder) VALUES
(1, 25, 'Collect_legal',   5,  'ALL', 1),
(2, 25, 'Export_invoices', 13, 'ALL', 2),
(3, 25, 'Load_billing',    6,  'ALL', 3),
(4, 25, 'Load_reports',    15, 'ALL', 4),
(5, 25, 'Check_ledger',    21, 'ALL', 5),
(6, 25, 'Alert_finance',   22, 'ALL', 6),
(7, 25, 'Reconcile',       23, 'ALL', 7),
(8, 25, 'Clean_up',        24, 'ALL', 8);

INSERT INTO WorkflowPrerequisites (id, Item_id, TargetItem_id, Test, ReturnCodes) VALUES
(1, 3, 1, 'SUCCESS', NULL),
(2, 4, 2, 'SUCCESS', NULL),
(3, 5, 3, 'SUCCESS', NULL),
(4, 5, 4, 'SUCCESS', NULL),
(5, 6, 5, 'FAILED',  NULL),
(6, 7, 5, 'RC',      '4'),
(7, 8, 7, 'ENDED',   NULL);

-- ----------------------------------------------------------------------------
-- 6. A sample of Reactions and Disable here (docs/WORKFLOWS_PHASE3.md), on stand-ins:
--    - Feed times out (return code 8); its own Reactions rerun it twice, then count it as
--      succeeded: carry on without it.
--    - Load_rows ends with return code 4 from a Set Return Code step ("rows rejected"); this
--      use counts 4 as succeeded.
--    - Validate fails; this use reruns from Stage once, then skips the rest of its branch
--      (Publish).
--    - Archive is disabled here to pass through; Tidy runs whatever happened.
-- ----------------------------------------------------------------------------
INSERT INTO MasterObjects (id, ObjectType) VALUES
(26, 'JOB'), (27, 'JOB'), (28, 'JOB'), (29, 'JOB'), (30, 'JOB'), (31, 'JOB'), (32, 'JOB');

INSERT INTO Jobs (MasterObject_id, JobKey, Description) VALUES
(26, 'DEV-SIM-FEED',      'Stand-in: fetches a rates feed, which times out (return code 8). Its Reactions: rerun twice, then carry on without it'),
(27, 'DEV-SIM-LOAD_ROWS', 'Stand-in: loads rows, and sets return code 4 when some are rejected'),
(28, 'DEV-SIM-STAGE',     'Stand-in: stages the batch'),
(29, 'DEV-SIM-VALIDATE',  'Stand-in: validates the staged batch, and fails: the totals do not balance'),
(30, 'DEV-SIM-PUBLISH',   'Stand-in: publishes the validated batch'),
(31, 'DEV-SIM-ARCHIVE',   'Stand-in: archives the batch');
INSERT INTO Jobs (MasterObject_id, JobKey, JobType, Description) VALUES
(32, 'DEV-REACTIONS_SAMPLE', 'WORKFLOW', 'Sample workflow: Reactions (rerun, count as, rerun from, skip the rest of the branch) and Disable here');

INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 26, 26, id, 1, 'Fetch the feed', 'Fetch_the_feed' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 27, 27, id, 1, 'Load the rows', 'Load_the_rows' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 28, 27, id, 2, 'Some rows were rejected', 'Some_rows_were_rejected' FROM StepTypes WHERE Code = 'SET_RETURN_CODE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 29, 28, id, 1, 'Stage', 'Stage' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 30, 29, id, 1, 'Validate', 'Validate' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 31, 30, id, 1, 'Publish', 'Publish' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 32, 31, id, 1, 'Archive', 'Archive' FROM StepTypes WHERE Code = 'SIMULATE';

INSERT INTO JobStepParameters (JobStep_id, ParameterName, ParameterValue) VALUES
(26, 'Messages',    'Fetching the rates feed
The feed timed out'),
(26, 'ReturnCode',  '8'),
(27, 'Messages',    'Loading 120 rows'),
(28, 'ReturnCode',  '4'),
(28, 'Message',     '3 rows were rejected'),
(29, 'Messages',    'Staging the batch'),
(30, 'Messages',    'Validating the staged batch'),
(30, 'Fail',        'True'),
(30, 'FailMessage', 'The totals do not balance'),
(31, 'Messages',    'Publishing the batch'),
(32, 'Messages',    'Archiving the batch');

INSERT INTO WorkflowItems (id, Workflow_MasterObject_id, ItemName, Job_MasterObject_id, JoinRule, ItemOrder, DisabledHere, ReactionsOverridden) VALUES
(9,  32, 'Feed',      26, 'ALL', 1, NULL,           0),
(10, 32, 'Load_rows', 27, 'ALL', 2, NULL,           1),
(11, 32, 'Stage',     28, 'ALL', 3, NULL,           0),
(12, 32, 'Validate',  29, 'ALL', 4, NULL,           1),
(13, 32, 'Publish',   30, 'ALL', 5, NULL,           0),
(14, 32, 'Archive',   31, 'ALL', 6, 'PASS_THROUGH', 0),
(15, 32, 'Tidy',      24, 'ALL', 7, NULL,           0);

INSERT INTO WorkflowPrerequisites (id, Item_id, TargetItem_id, Test, ReturnCodes) VALUES
(8,  10, 9,  'SUCCESS', NULL),
(9,  11, 10, 'SUCCESS', NULL),
(10, 12, 11, 'SUCCESS', NULL),
(11, 13, 12, 'SUCCESS', NULL),
(12, 14, 10, 'SUCCESS', NULL),
(13, 15, 12, 'ENDED',   NULL),
(14, 15, 14, 'SUCCESS', NULL);

-- Feed's own (on the job); Load_rows' and Validate's (on their use in this workflow)
INSERT INTO Reactions (id, Job_MasterObject_id, Item_id, Section, ReactionOrder, WhenTest, WhenReturnCodes) VALUES
(1, 26,   NULL, 'NEXT', 1, 'RC',     '8'),
(2, 26,   NULL, 'NEXT', 2, 'FAILED', NULL),
(3, NULL, 10,   'NEXT', 1, 'RC',     '4'),
(4, NULL, 12,   'NEXT', 1, 'FAILED', NULL),
(5, NULL, 12,   'NEXT', 2, 'FAILED', NULL);

INSERT INTO ReactionActions (id, Reaction_id, ActionOrder, Action, MaxTimes, WaitSeconds, TargetItem_id) VALUES
(1, 1, 1, 'RERUN',              2,    2,    NULL),
(2, 2, 1, 'COUNT_AS_SUCCEEDED', NULL, NULL, NULL),
(3, 3, 1, 'COUNT_AS_SUCCEEDED', NULL, NULL, NULL),
(4, 4, 1, 'RERUN_FROM',         1,    0,    11),
(5, 5, 1, 'SKIP_BRANCH',        NULL, NULL, NULL);

-- ----------------------------------------------------------------------------
-- 7. A sample of conditions (docs/WORKFLOWS_PHASE4.md):
--    - Post starts by a Custom rule: the legal files were delivered (a file count) and either
--      the FX rates or the fallback rates are in. It starts as soon as Rates succeeds, while
--      Fallback_rates has not been decided yet.
--    - Fallback_rates only runs if Rates failed, so here it does not run.
--    - EU_report's rule names no job: it tests the workflow's variable Region.
--    - Succeeds when Post succeeded, and the workflow ends with Post's return code.
-- ----------------------------------------------------------------------------
INSERT INTO MasterObjects (id, ObjectType) VALUES
(33, 'JOB'), (34, 'JOB'), (35, 'JOB'), (36, 'JOB'), (37, 'JOB');

INSERT INTO Jobs (MasterObject_id, JobKey, Description) VALUES
(33, 'DEV-SIM-RATES',          'Stand-in: fetches today''s FX rates'),
(34, 'DEV-SIM-FALLBACK_RATES', 'Stand-in: uses yesterday''s FX rates, when today''s did not arrive'),
(35, 'DEV-SIM-POST',           'Stand-in: posts the batch with the FX rates'),
(36, 'DEV-SIM-EU_REPORT',      'Stand-in: the report EU regulators ask for');
INSERT INTO Jobs (MasterObject_id, JobKey, JobType, Description, SucceedsWhen, ReturnCodeFrom) VALUES
(37, 'DEV-CONDITIONS_SAMPLE', 'WORKFLOW', 'Sample workflow: Custom rules (outcomes, a file count, a variable) and Succeeds when',
 '%{Post.Succeeded}', 'Post');

INSERT INTO Variables (MasterObject_id, VarName, VarValue, Description) VALUES
(37, 'Region', 'EU', 'Which region this run is for: EU_report runs only for the EU');

INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 33, 33, id, 1, 'Fetch the rates', 'Fetch_the_rates' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 34, 34, id, 1, 'Use yesterday''s rates', 'Use_yesterdays_rates' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 35, 35, id, 1, 'Post the batch', 'Post_the_batch' FROM StepTypes WHERE Code = 'SIMULATE';
INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 36, 36, id, 1, 'Write the EU report', 'Write_the_EU_report' FROM StepTypes WHERE Code = 'SIMULATE';

INSERT INTO JobStepParameters (JobStep_id, ParameterName, ParameterValue) VALUES
(33, 'Messages',    'Fetching today''s FX rates'),
(33, 'WaitSeconds', '2'),
(34, 'Messages',    'Using yesterday''s FX rates'),
(35, 'Messages',    'Posting the batch'),
(36, 'Messages',    'Writing the EU report');

INSERT INTO WorkflowItems (id, Workflow_MasterObject_id, ItemName, Job_MasterObject_id, JoinRule, StartRule, ItemOrder) VALUES
(16, 37, 'Collect',        5,  'ALL',    NULL, 1),
(17, 37, 'Rates',          33, 'ALL',    NULL, 2),
(18, 37, 'Fallback_rates', 34, 'CUSTOM', '%{Rates.Failed}', 3),
(19, 37, 'Post',           35, 'CUSTOM', '%{Collect.FileCount} > 0 AND (%{Rates.Succeeded} OR %{Fallback_rates.Succeeded})', 4),
(20, 37, 'EU_report',      36, 'CUSTOM', '${Region} = ''EU''', 5);

-- With a Custom rule, the jobs the rule names are its prerequisites (test RULE)
INSERT INTO WorkflowPrerequisites (id, Item_id, TargetItem_id, Test, ReturnCodes) VALUES
(15, 18, 17, 'RULE', NULL),
(16, 19, 16, 'RULE', NULL),
(17, 19, 17, 'RULE', NULL),
(18, 19, 18, 'RULE', NULL);

-- ----------------------------------------------------------------------------
-- 8. A sample of workflow variables (docs/WORKFLOWS_PHASE4.md, decisions 19 to 21):
--    - The workflow has variables of its own (Region, Currency), and the Finance tag gives its
--      jobs ReportRetentionDays.
--    - One job is used twice: Summary_EU takes the workflow's values, Summary_US sets Region and
--      Currency for its own use only. Each writes what it got to its log.
-- ----------------------------------------------------------------------------
INSERT INTO MasterObjects (id, ObjectType) VALUES
(38, 'JOB'), (39, 'JOB');

INSERT INTO Jobs (MasterObject_id, JobKey, Description) VALUES
(38, 'DEV-SIM-SUMMARY', 'Stand-in: writes the summary for a region, in its currency');
INSERT INTO Jobs (MasterObject_id, JobKey, JobType, Description) VALUES
(39, 'DEV-VARIABLES_SAMPLE', 'WORKFLOW', 'Sample workflow: its variables and tag reach its jobs, and one use sets its own');

INSERT INTO Variables (MasterObject_id, VarName, VarValue, Description) VALUES
(39, 'Region',   'EU',  'The region its jobs write for, unless a use sets its own'),
(39, 'Currency', 'EUR', 'The currency its jobs write in, unless a use sets its own');

INSERT INTO TagAssignments (Tag_MasterObject_id, Target_MasterObject_id) VALUES
(17, 39);

INSERT INTO JobSteps (id, Job_MasterObject_id, StepType_id, StepOrder, StepTitle, StepName)
SELECT 37, 38, id, 1, 'Write the summary', 'Write_the_summary' FROM StepTypes WHERE Code = 'SIMULATE';

INSERT INTO JobStepParameters (JobStep_id, ParameterName, ParameterValue) VALUES
(37, 'Messages', 'Summary for ${Region}, in ${Currency}; reports kept ${ReportRetentionDays} days');

INSERT INTO WorkflowItems (id, Workflow_MasterObject_id, ItemName, Job_MasterObject_id, JoinRule, ItemOrder) VALUES
(21, 39, 'Summary_EU', 38, 'ALL', 1),
(22, 39, 'Summary_US', 38, 'ALL', 2);

INSERT INTO WorkflowPrerequisites (id, Item_id, TargetItem_id, Test, ReturnCodes) VALUES
(19, 22, 21, 'SUCCESS', NULL);

INSERT INTO WorkflowItemVariables (Item_id, VarName, VarValue, Description) VALUES
(22, 'Region',   'US',  'This use writes for the US'),
(22, 'Currency', 'USD', 'and in dollars');

# Source of the RunMyJobs job definition AUTOAPP_RunJob (definition type BASH), a DRAFT.
#
# Runs one RunMyFiles job, as docs/INTEGRATION.md says a scheduler should. A BASH
# definition's parameters are its script's environment variables, and RunMyJobs
# sets JCS_JOB_ID to the job's ID ("Using the BASH Definition Type" and "Platform
# Agent Definition Types", RunMyJobs 2025.4 documentation).
#
# Its parameters (all String, Direction In):
#   AutoAppJobKey            the RunMyFiles job to run (the RunMyFiles tab fills it in)
#   AutoAppScheduler         what RunMyFiles calls this RunMyJobs, e.g. RMJ_PROD (Schedulers page in RunMyFiles)
#   AutoAppSecretParameters  the job's Password parameters, by name, comma separated, so the
#                            runner masks their values in the job log
#   BusinessDate             optional, YYYY-MM-DD
#   ...                      any others: the RunMyFiles job's steps use them as ${Name}
#
# The Job Server needs, through its EnvironmentVariables parameter (documented in
# "Platform Agent Definition Types"): AUTOAPP_HOME (RunMyFiles' folder), DATABASE_URL,
# AUTOAPP_WORKING_ROOT and AUTOAPP_API_URL, and AUTOAPP_PYTHON if python3 is not
# the right interpreter.
set -e
cd "${AUTOAPP_HOME:?AUTOAPP_HOME is not set on this Job Server: see the EnvironmentVariables parameter}/autoapp"

args=(--job-key "${AutoAppJobKey:?The parameter AutoAppJobKey is empty: open the RunMyFiles tab of this job definition}"
      --instance-id "$JCS_JOB_ID"
      --scheduler "${AutoAppScheduler:-RMJ}")
if [ -n "$BusinessDate" ]; then
    args+=(--business-date "$BusinessDate")
fi
export AUTOAPP_MASK_ENV="$AutoAppSecretParameters"

# The runner's exit code (0 succeeded, 1 failed) becomes this job's: RunMyJobs puts a non-zero one into Error
exec "${AUTOAPP_PYTHON:-python3}" -m engine.runner "${args[@]}"

/*
 * Job History and Audit Log pages: what has happened, read-only.
 *
 *     GET /api/v1/runs      every run of every job
 *     GET /api/v1/audits    every change to a definition
 */
function utcCriteria(values) {
    return { ...values, date_from: AutoApp.localInputToUtc(values.date_from), date_to: AutoApp.localInputToUtc(values.date_to) };
}

function jobHistory() {
    const search = AutoApp.searchPage({
        criteria: ["job_key", "instance_id", "scheduler", "status", "date_from", "date_to"],
        path: "/runs", noun: "run", order: "newest first", toApi: utcCriteria,
    });
    return Object.assign(search, {
        init() { this.startSearch(); },
        time: AutoApp.formatTime,
        jobLink(run) { return "job.html?" + new URLSearchParams({ key: run.job_key }); },
        operationsLink(run) {
            return "operations.html?" + new URLSearchParams({ job_key: run.job_key, instance_id: run.instance_id });
        },
        duration(run) {
            if (run.duration_seconds === null) return run.status === "RUNNING" ? "still running" : "";
            const s = run.duration_seconds;
            return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
        },
        exportCsv() {
            AutoApp.download("autoapp_job_history.csv", AutoApp.toCsv(this.rows, [
                ["Job", r => r.job_key], ["Status", r => r.status], ["Started (UTC)", r => r.started],
                ["Ended (UTC)", r => r.ended], ["Seconds", r => r.duration_seconds], ["Instance ID", r => r.instance_id],
                ["Run number", r => r.run_number], ["Scheduler", r => r.scheduler], ["Host", r => r.host],
                ["Operations", r => r.operations], ["Failed operations", r => r.failed_operations],
                ["Error", r => r.error], ["Run ID", r => r.run_id],
            ]));
        },
    });
}

function auditLog() {
    const search = AutoApp.searchPage({
        criteria: ["name", "action", "performed_by", "date_from", "date_to"],
        path: "/audits", noun: "change", order: "newest first", toApi: utcCriteria,
    });
    return Object.assign(search, {
        init() { this.startSearch(); },
        time: AutoApp.formatTime,
        /** JOB_UPDATED becomes "Job updated" */
        actionText(audit) {
            const words = audit.action.toLowerCase().split("_");
            return words.map((word, i) => (i === 0 ? word[0].toUpperCase() + word.slice(1) : word)).join(" ");
        },
        /** Where the thing changed can be seen now, if it still exists */
        link(audit) {
            if (!audit.name || audit.action.endsWith("_DELETED")) return null;
            return audit.kind === "jobs"
                ? "job.html?" + new URLSearchParams({ key: audit.name })
                : "detail.html?" + new URLSearchParams({ kind: audit.kind, name: audit.name });
        },
        exportCsv() {
            AutoApp.download("autoapp_audit_log.csv", AutoApp.toCsv(this.rows, [
                ["Time (UTC)", a => a.time], ["Action", a => a.action], ["Kind", a => a.kind], ["Name", a => a.name],
                ["By", a => a.performed_by], ["Changes", a => a.changes.join(" ")],
            ]));
        },
    });
}

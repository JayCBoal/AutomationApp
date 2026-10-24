/*
 * Job History and Audit Log pages: what has happened, read-only.
 *
 * Job History is a tree (docs/WORKFLOWS_PHASE2.md): a workflow run is one row, folded, with the
 * runs inside it shown when it is unfolded. A run found by the search whose workflow run is not
 * found too is a row of its own, saying which workflow run it was in.
 *
 *     GET /api/v1/runs?tree=true            every run of every job, runs inside listed workflow runs left out
 *     GET /api/v1/runs?parent=<run ID>      the runs inside a workflow run, for unfolding it
 *     GET /api/v1/audits    every change to a definition
 *     Rerun ▸ on a failed run: rerun.js
 */
function utcCriteria(values) {
    return { ...values, date_from: AutoApp.localInputToUtc(values.date_from), date_to: AutoApp.localInputToUtc(values.date_to) };
}

const MAX_INSIDE = 500;

function jobHistory() {
    const search = AutoApp.searchPage({
        criteria: ["job_key", "job_type", "within", "instance_id", "scheduler", "status", "late", "date_from", "date_to"],
        path: "/runs", noun: "run", order: "newest first", toApi: values => ({ ...utcCriteria(values), tree: true }),
    });
    const searchRuns = search.search;
    const page = Object.assign(search, rerunDialog(), {
        rerunRow: null,     // the run whose Rerun ▸ was opened

        /** A rerun is a new attempt: its page is the workflow's run, or the job's log. */
        async afterRerun(launch) {
            const row = this.rerunRow;
            if (row && row.job_type === "WORKFLOW") await this.waitUntilRunning(launch);
            location.href = row && row.job_type === "WORKFLOW"
                ? "workflow.html?" + new URLSearchParams({ key: row.job_key, run: launch.run_id })
                : "log.html?" + new URLSearchParams({ run: launch.run_id });
        },
        unfolded: {},       // a workflow run's ID: the runs inside it, once it is unfolded
        init() { this.startSearch(); },

        /** Searches, folding every workflow run; the one asked for by "Within run" opens unfolded. */
        async search() {
            this.unfolded = {};
            await searchRuns.call(this);
            const asked = this.rows.find(run => run.run_id === this.criteria.within.trim());
            if (asked && asked.child_count) await this.toggle(asked);
        },

        async toggle(run) {
            if (this.unfolded[run.run_id]) {
                const { [run.run_id]: folded, ...rest } = this.unfolded;
                this.unfolded = rest;
                return;
            }
            try {
                const inside = await AutoApp.get("/runs", { parent: run.run_id, limit: MAX_INSIDE });
                this.unfolded = { ...this.unfolded, [run.run_id]: inside };
            } catch (e) {
                this.error = e.message;
            }
        },

        insideWords(run) { return `${run.child_count} run${run.child_count === 1 ? "" : "s"} inside`; },
        time: AutoApp.formatTime,
        jobLink(run) {
            return run.job_type === "WORKFLOW" ? "workflow.html?" + new URLSearchParams({ key: run.job_key, run: run.run_id })
                                               : "job.html?" + new URLSearchParams({ key: run.job_key });
        },
        withinLink(runId) { return "history.html?" + new URLSearchParams({ within: runId }); },
        logLink(run) { return "log.html?" + new URLSearchParams({ run: run.run_id }); },
        operationsLink(run) {
            return "operations.html?" + new URLSearchParams({ job_key: run.job_key, instance_id: run.instance_id });
        },
        duration(run) {
            if (run.duration_seconds === null) return run.status === "RUNNING" ? "still running" : "";
            const s = run.duration_seconds;
            return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
        },
        exportCsv() {
            AutoApp.download("autoapp_job_history.csv", AutoApp.toCsv(this.shownRows, [
                ["Job", r => r.job_key], ["Type", r => r.job_type === "WORKFLOW" ? "Workflow" : "Job"],
                ["Status", r => r.status], ["Return code", r => r.return_code], ["Reason", r => r.reason],
                ["Late", r => r.late ? "Late" : ""], ["Late reason", r => r.late_reason], ["Late cause", r => r.late_cause],
                ["Within run", r => r.parent_run_id], ["Path in workflow", r => r.workflow_path],
                ["Started (UTC)", r => r.started],
                ["Ended (UTC)", r => r.ended], ["Seconds", r => r.duration_seconds], ["Instance ID", r => r.instance_id],
                ["Run number", r => r.run_number], ["Scheduler", r => r.scheduler], ["Host", r => r.host],
                ["Operations", r => r.operations], ["Failed operations", r => r.failed_operations],
                ["Error", r => r.error], ["Run ID", r => r.run_id],
            ]));
        },
    });
    // Worked out each time it is read (Object.assign above would read it once, too early)
    Object.defineProperty(page, "shownRows", {
        enumerable: true,
        /** The rows on screen: each run, then the runs inside it if it is unfolded, each with its depth. */
        get() {
            const shown = [];
            const add = (run, depth) => {
                shown.push({ ...run, depth });
                for (const inside of this.unfolded[run.run_id] || []) add(inside, depth + 1);
            };
            this.rows.forEach(run => add(run, 0));
            return shown;
        },
    });
    return page;
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
            if (audit.kind === "jobs") return "job.html?" + new URLSearchParams({ key: audit.name });
            if (audit.kind === "settings") return "settings.html";
            return "detail.html?" + new URLSearchParams({ kind: audit.kind, name: audit.name });
        },
        exportCsv() {
            AutoApp.download("autoapp_audit_log.csv", AutoApp.toCsv(this.rows, [
                ["Time (UTC)", a => a.time], ["Action", a => a.action], ["Kind", a => a.kind], ["Name", a => a.name],
                ["By", a => a.performed_by], ["Changes", a => a.changes.join(" ")],
            ]));
        },
    });
}

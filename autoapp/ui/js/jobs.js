/*
 * Job Search page: find jobs, see at a glance what each one uses and how its
 * last run went, and check a job without running it.
 *
 * Data comes from two API routes:
 *     GET /api/v1/jobs                    the search
 *     GET /api/v1/jobs/{job_key}/check    check one job
 */
function jobSearch() {
    const search = AutoApp.searchPage({
        criteria: ["job_key", "description", "job_type", "active", "endpoint", "tag"],
        path: "/jobs",
        noun: "job",
        order: "in name order",
        found: true,                // it lists workflows too
    });

    return Object.assign(search, {
        checked: null,          // the result of the check being shown, or null
        checkedKey: "",
        checkError: "",

        init() {
            this.startSearch();
        },

        time: AutoApp.formatTime,

        steps: AutoApp.jobContents,

        checkHint(job) {
            return `${job.problem_count} problem${job.problem_count === 1 ? "" : "s"} found: click to see`;
        },

        detailLink: AutoApp.jobPage,

        operationsLink(job) {
            return "operations.html?" + new URLSearchParams({ job_key: job.job_key });
        },

        exportCsv() {
            const csv = AutoApp.toCsv(this.rows, [
                ["Job", j => j.job_key], ["Type", j => j.job_type === "WORKFLOW" ? "Workflow" : "Job"],
                ["Description", j => j.description], ["Jobs in it", j => j.job_type === "WORKFLOW" ? j.item_count : ""],
                ["Enabled", j => j.active ? "Yes" : "No"],
                ["Enabled steps", j => j.step_count], ["Disabled steps", j => j.disabled_step_count],
                ["Endpoints", j => j.endpoints.join("; ")],
                ["Tags", j => j.tags.join("; ")],
                ["Ready to run", j => j.ready ? "Yes" : "No"], ["Problems", j => j.problem_count],
                ["Last run status", j => j.last_run ? j.last_run.status : ""],
                ["Last run started (UTC)", j => j.last_run ? j.last_run.started : ""],
                ["Last run ended (UTC)", j => j.last_run ? j.last_run.ended : ""],
                ["Last run instance ID", j => j.last_run ? j.last_run.instance_id : ""],
                ["Last run number", j => j.last_run ? j.last_run.run_number : ""],
                ["Last run error", j => j.last_run ? j.last_run.error : ""],
                ["Modified (UTC)", j => j.modified], ["Modified by", j => j.modified_by],
            ]);
            AutoApp.download("autoapp_jobs.csv", csv);
        },

        // ---------- Check a job without running it ----------

        async check(job) {
            this.checkedKey = job.job_key;
            this.checked = null;
            this.checkError = "";
            this.$refs.checkWindow.showModal();
            try {
                this.checked = await AutoApp.get(`/jobs/${encodeURIComponent(job.job_key)}/check`);
            } catch (e) {
                this.checkError = e.message;
            }
        },

        closeCheck() {
            this.$refs.checkWindow.close();
        },
    });
}

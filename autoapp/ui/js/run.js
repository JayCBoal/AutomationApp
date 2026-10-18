/*
 * The Run Job page (run.html) and a run's log page (log.html?run=<RunID>).
 *
 * API routes used:
 *     GET  /api/v1/jobs                     finding a job to run, with the Job Search page's criteria
 *     GET  /api/v1/jobs/{job_key}/check     whether the chosen job would run
 *     POST /api/v1/launches                 start the runner for it, as a scheduler would
 *     GET  /api/v1/launches/{launch_id}     whether the runner process is still going
 *     GET  /api/v1/runs/{run_id}            the run as recorded, with its job log so far
 *     POST /api/v1/runs/{run_id}/kill       Kill (a workflow: Kill and Cancel)
 */
const LOG_LEVELS = ["DETAIL", "SUMMARY", "DEBUG", "SILENT"];
const POLL_MS = 1000;

/** What both pages share: following one run and showing its log as it grows. */
function followRun() {
    let timer = null;
    return {
        run: null,              // the run as recorded: status, times, log lines
        runMissing: false,      // asked for, but not recorded (yet)

        async loadRun(runId) {
            try {
                this.run = await AutoApp.get("/runs/" + encodeURIComponent(runId));
                this.runMissing = false;
                this.$nextTick(() => {
                    const box = this.$refs.log;
                    if (box && this.following) box.scrollTop = box.scrollHeight;
                });
            } catch (e) {
                if (e.status === 404) this.runMissing = true;
                else throw e;
            }
        },

        /** Kill: a job's runner is told to stop; a workflow kills what runs and cancels the rest. */
        async kill() {
            const words = this.run.job_type === "WORKFLOW" ? "Kill the jobs running now, and start nothing more?" : "Kill this run?";
            if (!confirm(words)) return;
            try {
                this.run = await AutoApp.send("POST", `/runs/${encodeURIComponent(this.run.run_id)}/kill`);
            } catch (e) {
                this.error = e.message;
            }
        },

        killWords(run) { return run && run.job_type === "WORKFLOW" ? "Kill and Cancel" : "Kill"; },

        /** Asks again every second while step() says to. */
        poll(step) {
            clearTimeout(timer);
            const tick = async () => {
                let again = false;
                try {
                    again = await step();
                } catch (e) {
                    this.error = e.message;
                }
                if (again) timer = setTimeout(tick, POLL_MS);
            };
            tick();
        },

        following: true,        // keep the end of the log in view as it grows
        logScrolled(event) {
            const box = event.target;
            this.following = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
        },

        time: AutoApp.formatTime,
        duration(run) {
            if (!run || run.duration_seconds === null || run.duration_seconds === undefined) return "";
            const s = run.duration_seconds;
            return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
        },
        /** One line of the log, with its level picked out so errors and warnings stand out. */
        lineClass(line) {
            if (line.includes("[ERROR]")) return "log-error";
            if (line.includes("[WARN]")) return "log-warn";
            if (line.includes("[DEBUG]")) return "log-debug";
            return "";
        },
        operationsLink(run) { return "operations.html?" + new URLSearchParams({ instance_id: run.instance_id, job_key: run.job_key }); },
        jobLink(run) { return "job.html?" + new URLSearchParams({ key: run.job_key }); },
    };
}

// ---------- The Run Job page ----------

function runPage() {
    const address = new URLSearchParams(location.search);
    const page = {
        ...followRun(),
        levels: LOG_LEVELS,
        jobKey: address.get("key") || "",
        instanceId: "",
        logLevel: "DETAIL",
        businessDate: "",       // as a scheduler such as Control-M would give it; blank for none
        check: null,            // the pre-run check of the chosen job
        jobKeys: [],
        launch: null,           // the launch under way or last finished
        busy: false,
        error: "",

        async init() {
            try {
                await AutoApp.ensureLookups();
                this.jobKeys = [...document.querySelectorAll("#lookup-jobs option")].map(o => o.value);
            } catch (e) {
                this.error = e.message;
            }
            this.startSearch();
            if (this.jobKey) this.checkJob();
        },

        jobContents: AutoApp.jobContents,
        jobPage: AutoApp.jobPage,

        /** Picks a job from the list found, and checks it. */
        choose(job) {
            this.jobKey = job.job_key;
            this.checkJob();
            this.$nextTick(() => document.getElementById("run-form").scrollIntoView({ block: "nearest" }));
        },

        get known() { return this.jobKeys.includes(this.jobKey.trim()); },

        async checkJob() {
            this.check = null;
            if (!this.known) return;
            const key = this.jobKey.trim();
            try {
                const check = await AutoApp.get("/jobs/" + encodeURIComponent(key) + "/check");
                if (this.jobKey.trim() === key) this.check = check;
            } catch (e) {
                this.error = e.message;
            }
            this.rememberInAddress();
        },

        get running() { return Boolean(this.launch) && (this.launch.state === "RUNNING" || (this.run && this.run.status === "RUNNING")); },

        async start() {
            this.busy = true;
            this.error = "";
            this.run = null;
            this.runMissing = false;
            this.following = true;
            try {
                this.launch = await AutoApp.send("POST", "/launches", {
                    job_key: this.jobKey.trim(), instance_id: this.instanceId.trim() || null, log_level: this.logLevel,
                    business_date: this.businessDate || null,
                });
            } catch (e) {
                this.error = e.message;
                this.busy = false;
                return;
            }
            this.instanceId = "";
            this.busy = false;
            // Follow the runner until it has finished and its last records have arrived
            this.poll(async () => {
                this.launch = await AutoApp.get("/launches/" + encodeURIComponent(this.launch.launch_id));
                // Asked for only once the runner has recorded it, so the page never asks for a run not there yet
                if (this.launch.recorded) await this.loadRun(this.launch.run_id);
                const finished = this.launch.state === "FINISHED";
                return !(finished && (!this.run || this.run.status !== "RUNNING"));
            });
        },

        /** How the launch ended, in a few words. */
        get outcome() {
            if (!this.launch) return "";
            if (this.launch.state === "RUNNING" || (this.run && this.run.status === "RUNNING")) return "Running...";
            if (this.run) return this.run.status === "SUCCESS" ? "Succeeded" : "Failed";
            return this.launch.exit_code === 0 ? "Succeeded" : "Failed before it could record the run";
        },
        get outcomeClass() {
            if (!this.launch || this.running) return "";
            return this.launch.exit_code === 0 ? "SUCCESS" : "FAILED";
        },
    };
    // Finding a job, as on the Job Search page. Copied as properties, so its worked-out fields stay worked out.
    const search = AutoApp.searchPage({
        criteria: ["job_key", "description", "job_type", "active", "endpoint", "tag"],
        path: "/jobs",
        noun: "job",
        order: "in name order",
        inAddress() { return { key: this.known ? this.jobKey.trim() : "" }; },
    });
    return Object.defineProperties(page, Object.getOwnPropertyDescriptors(search));
}

// ---------- A run's log page ----------

function runLogPage() {
    const address = new URLSearchParams(location.search);
    let runId = address.get("run") || "";
    return {
        ...followRun(),
        runId,
        error: "",

        async init() {
            // A scheduler knows the run by its own instance ID: log.html?job_key=...&instance_id=...
            if (!runId && address.get("job_key") && address.get("instance_id")) {
                try {
                    const runs = await AutoApp.get("/runs", { job_key: address.get("job_key"), instance_id: address.get("instance_id") });
                    const exact = runs.filter(run => run.job_key === address.get("job_key"));
                    if (exact.length) runId = this.runId = exact[0].run_id;        // newest first: the latest restart
                    else { this.runMissing = true; return; }
                } catch (e) {
                    this.error = e.message;
                    return;
                }
            }
            if (!runId) { this.error = "No run was given. Open a run's log from Job History."; return; }
            // A finished run's log opens at the top; one still going is followed, at its end, until it ends
            this.following = false;
            let first = true;
            this.poll(async () => {
                await this.loadRun(runId);
                const running = Boolean(this.run) && this.run.status === "RUNNING";
                if (first && running) { this.following = true; await this.loadRun(runId); }
                first = false;
                return running;
            });
        },
    };
}

/*
 * The Stand-in Scheduler's page. It does what a WLA's job editor and run list would:
 * keeps job definitions with their parameters, opens RunMyFiles' job editor embedded
 * for a RunMyFiles job (listening for its messages), submits jobs, and shows their runs,
 * with a way into RunMyFiles' Operations Log for each. See docs/INTEGRATION.md.
 */
async function call(method, path, body) {
    const options = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    if (!response.ok) {
        let detail = response.statusText;
        try { const answer = await response.json(); detail = typeof answer.detail === "string" ? answer.detail : JSON.stringify(answer.detail); } catch (e) { /* not JSON */ }
        throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
}

function standin() {
    let uid = 1;
    let pollTimer = null;
    return {
        config: { autoapp_url: "", scheduler_name: "" },
        jobs: [],
        chosen: "",
        form: null,             // the job on screen
        saved: "",              // the job as last loaded or saved, to tell whether anything changed
        runs: [],
        autoapp: null,          // what RunMyFiles says about the RunMyFiles job: { summary, error }
        outputs: {},            // run id -> its output, for the runs whose output is open
        busy: false,
        error: "",
        notice: "",
        windowTitle: "",
        windowMessage: "",

        async init() {
            try {
                this.config = await call("GET", "/api/config");
                await this.loadJobs();
            } catch (e) {
                this.error = e.message;
            }
            // What RunMyFiles' embedded pages tell us
            window.addEventListener("message", event => this.fromAutoApp(event));
            const wanted = new URLSearchParams(location.search).get("job");
            if (wanted) this.choose(wanted);
        },

        async loadJobs() { this.jobs = await call("GET", "/api/jobs"); },

        show(job) {
            this.form = {
                name: job.name, description: job.description || "", business_date: Boolean(job.business_date),
                autoapp_job_key: job.autoapp_job_key || null,
                parameters: (job.parameters || []).map(p => ({
                    uid: uid++, name: p.name, value: p.value ?? "", secret: p.secret, savedSecret: p.secret,
                })),
            };
            this.saved = job.name ? JSON.stringify(this.payload()) : "";
        },

        payload() {
            return {
                name: this.form.name.trim(), description: this.form.description.trim() || null,
                business_date: this.form.business_date, autoapp_job_key: (this.form.autoapp_job_key || "").trim() || null,
                parameters: this.form.parameters.map(p => ({
                    name: p.name.trim(), secret: p.secret,
                    value: p.secret && p.savedSecret && p.value === "" ? null : p.value,
                })),
            };
        },

        get changed() { return Boolean(this.form) && JSON.stringify(this.payload()) !== this.saved; },

        async choose(name) {
            if (this.changed && !confirm("Discard the changes to this job?")) return;
            this.error = this.notice = "";
            try {
                this.show(await call("GET", "/api/jobs/" + encodeURIComponent(name)));
                this.chosen = name;
                this.outputs = {};
                await Promise.all([this.loadRuns(), this.loadAutoApp()]);
            } catch (e) {
                this.error = e.message;
            }
        },

        startNew() {
            if (this.changed && !confirm("Discard the changes to this job?")) return;
            this.chosen = "";
            this.runs = [];
            this.autoapp = null;
            this.show({ name: "", parameters: [] });
            this.error = this.notice = "";
        },

        addParameter() { this.form.parameters.push({ uid: uid++, name: "", value: "", secret: false, savedSecret: false }); },

        async save() {
            this.busy = true;
            this.error = this.notice = "";
            try {
                const job = this.saved
                    ? await call("PUT", "/api/jobs/" + encodeURIComponent(this.chosen), this.payload())
                    : await call("POST", "/api/jobs", this.payload());
                this.show(job);
                this.chosen = job.name;
                await Promise.all([this.loadJobs(), this.loadAutoApp()]);
                this.notice = `Saved job '${job.name}'.`;
            } catch (e) {
                this.error = e.message;
            }
            this.busy = false;
        },

        async remove() {
            if (!confirm(`Delete job '${this.chosen}'? Its RunMyFiles job is not deleted.`)) return;
            try {
                await call("DELETE", "/api/jobs/" + encodeURIComponent(this.chosen));
                this.form = null;
                this.saved = this.chosen = "";
                await this.loadJobs();
            } catch (e) {
                this.error = e.message;
            }
        },

        // ---------- RunMyFiles' pages, embedded ----------

        /** An address of RunMyFiles', embedded, matching our look, and telling only us what happens. */
        autoAppAddress(page, params) {
            const query = new URLSearchParams({ ...params, embed: "1", theme: "light", host: location.origin });
            return `${this.config.autoapp_url}/ui/${page}?${query}`;
        },

        openWindow(title, address) {
            this.windowTitle = title;
            this.windowMessage = "";
            this.$refs.frame.src = address;
            this.$refs.window.showModal();
        },

        windowClosed() { this.$refs.frame.src = "about:blank"; this.loadAutoApp(); },

        editInAutoApp() {
            // The RunMyFiles job this one runs, or a new one named after it; and this job's parameters, for RunMyFiles to read
            const params = this.form.autoapp_job_key
                ? { key: this.form.autoapp_job_key }
                : { new: "", key: this.form.name.toUpperCase() };
            Object.assign(params, { scheduler: this.config.scheduler_name, wla_job: this.form.name });
            this.openWindow(`RunMyFiles job for ${this.form.name}`, this.autoAppAddress("job.html", params));
        },

        operationsInAutoApp(run) {
            this.openWindow(`Files handled by ${run.instance_id}`,
                this.autoAppAddress("operations.html", { job_key: run.autoapp_job_key, instance_id: run.instance_id }));
        },

        async fromAutoApp(event) {
            if (event.origin !== new URL(this.config.autoapp_url).origin) return;
            const message = event.data || {};
            if (message.source !== "AutoApp") return;
            if (message.event === "saved") {
                this.windowMessage = message.valid ? "Saved in RunMyFiles: ready to run." : "Saved in RunMyFiles, with problems to fix before it can run.";
                if (message.job_key !== this.form.autoapp_job_key) {
                    // A new RunMyFiles job, or a renamed one: this job now runs it
                    this.form.autoapp_job_key = message.job_key;
                    await this.save();
                }
            } else if (message.event === "deleted") {
                this.windowMessage = "Deleted in RunMyFiles.";
                this.form.autoapp_job_key = null;
                await this.save();
            } else if (message.event === "cancelled") {
                this.$refs.window.close();
            }
        },

        // ---------- Running ----------

        async submit() {
            this.error = this.notice = "";
            try {
                const run = await call("POST", `/api/jobs/${encodeURIComponent(this.chosen)}/submit`);
                this.notice = `Submitted as ${run.instance_id}.`;
                await this.loadRuns();
            } catch (e) {
                this.error = e.message;
            }
        },

        /** What RunMyFiles says about the RunMyFiles job this one runs, asked through our own server. */
        async loadAutoApp() {
            if (!this.chosen) { this.autoapp = null; return; }
            try {
                this.autoapp = await call("GET", `/api/jobs/${encodeURIComponent(this.chosen)}/autoapp`);
            } catch (e) {
                this.autoapp = { summary: null, error: e.message };
            }
        },

        /** One of RunMyFiles' pages from the summary, in our window, embedded. */
        openFromSummary(title, url) {
            const target = new URL(url);
            target.searchParams.set("embed", "1");
            target.searchParams.set("theme", "light");
            target.searchParams.set("host", location.origin);
            this.openWindow(title, target.toString());
        },

        async loadRuns() {
            clearTimeout(pollTimer);
            if (!this.chosen) return;
            this.runs = await call("GET", "/api/runs?" + new URLSearchParams({ job: this.chosen }));
            for (const id of Object.keys(this.outputs)) this.outputs[id] = (await call("GET", "/api/runs/" + id)).output;
            if (this.runs.some(run => run.status === "RUNNING")) pollTimer = setTimeout(() => this.loadRuns(), 1000);
            else this.loadAutoApp();            // a run that has just ended changes RunMyFiles' "last run"
        },

        async toggleOutput(run) {
            if (this.outputs[run.id] !== undefined) { delete this.outputs[run.id]; return; }
            this.outputs[run.id] = (await call("GET", "/api/runs/" + run.id)).output;
        },

        time(text) {
            if (!text) return "";
            const d = new Date(text.endsWith("Z") ? text : text + "Z");
            return isNaN(d) ? text : d.toLocaleString();
        },
    };
}

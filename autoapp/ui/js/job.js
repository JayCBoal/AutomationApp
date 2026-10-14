/*
 * Job Detail page: one job, its steps, and each step's parameters.
 *
 * The form for a step is not written here. It is drawn from the step catalog:
 * each step type's parameters, in order, with their types. A new step type
 * therefore appears on this page without any change to it.
 *
 * Data comes from four API routes:
 *     GET /api/v1/jobs/{job_key}          the job, its steps and parameters
 *     GET /api/v1/step-types              the step catalog
 *     GET /api/v1/jobs/{job_key}/check    whether the job would run
 *     GET /api/v1/jobs                    the list for the job selector
 *
 * This page shows a job. Changing one is the next thing to be built.
 */
function jobDetail() {
    return {
        key: new URLSearchParams(location.search).get("key") || "",
        job: null,
        catalog: {},            // step type code -> its catalog entry
        allKeys: [],            // every job key, for the selector
        check: null,            // result of the pre-run check
        open: {},               // step id -> true if its parameters are showing
        loading: false,
        error: "",
        chosen: "",

        async init() {
            this.chosen = this.key;
            try {
                const [catalog, jobs] = await Promise.all([AutoApp.get("/step-types"), AutoApp.get("/jobs")]);
                this.catalog = Object.fromEntries(catalog.map(type => [type.code, type]));
                this.allKeys = jobs.map(job => job.job_key);
            } catch (e) {
                this.error = e.message;
                return;
            }
            if (this.key) await this.load();
        },

        async load() {
            this.loading = true;
            this.error = "";
            try {
                const path = "/jobs/" + encodeURIComponent(this.key);
                [this.job, this.check] = await Promise.all([AutoApp.get(path), AutoApp.get(path + "/check")]);
                document.title = `${this.job.job_key} - AutoApp`;
            } catch (e) {
                this.job = null;
                this.error = e.message;
            }
            this.loading = false;
        },

        /** The selector: typing narrows the list; choosing a job opens it. */
        choose() {
            if (this.allKeys.includes(this.chosen) && this.chosen !== this.key) {
                location.href = "job.html?" + new URLSearchParams({ key: this.chosen });
            }
        },

        // ---------- The job ----------

        time: AutoApp.formatTime,

        get commandLine() {
            return `python3 -m engine.runner --job-key ${this.job.job_key} --instance-id <the scheduler's instance ID>`;
        },

        get operationsLink() {
            return "operations.html?" + new URLSearchParams({ job_key: this.job.job_key });
        },

        /** What stops the job running, other than its being disabled, which is shown separately. */
        get problems() {
            if (!this.check) return [];
            return this.check.problems.filter(problem => !problem.endsWith("is disabled."));
        },

        // ---------- Steps ----------

        toggle(step) { this.open[step.id] = !this.open[step.id]; },
        expandAll(open) { for (const step of this.job.steps) this.open[step.id] = open; },

        /**
         * A step's form: one field per parameter in its step type's catalog entry, holding the step's
         * stored value. Where the step stores nothing, the field shows the default, marked as such.
         */
        fields(step) {
            const type = this.catalog[step.step_type];
            if (!type) return [];
            return type.parameters.map(param => {
                const field = { ...param, stored: step.parameters[param.name] ?? null };
                if (param.data_type === "LOCATION") {
                    field.endpoint = step.parameters[param.endpoint_parameter] ?? "";
                    field.path = field.stored ?? "";
                    field.mode = field.endpoint ? "endpoint" : (field.path ? "path" : "");
                    return field;
                }
                field.isDefault = field.stored === null || field.stored === "";
                field.value = field.isDefault ? (param.default ?? "") : field.stored;
                // A true/false value written as a placeholder cannot be shown as a tick box
                field.asText = param.data_type === "BOOLEAN" && String(field.value).includes("${");
                field.ticked = ["true", "yes", "y", "1"].includes(String(field.value).trim().toLowerCase());
                return field;
            });
        },

        /** Parameters the step stores that its step type does not have: mistakes the pre-run check will report. */
        unknown(step) {
            const type = this.catalog[step.step_type];
            if (!type) return Object.entries(step.parameters);
            const known = new Set(type.parameters.flatMap(p => [p.name, p.endpoint_parameter]).filter(Boolean));
            return Object.entries(step.parameters).filter(([name]) => !known.has(name));
        },

        /** One line saying what a step does, shown while it is collapsed: "LEGAL_EXTRACTS -> incoming". */
        summary(step) {
            const places = this.fields(step).filter(f => f.data_type === "LOCATION")
                .map(f => f.endpoint || f.path).filter(Boolean);
            return places.join("  →  ");
        },
    };
}

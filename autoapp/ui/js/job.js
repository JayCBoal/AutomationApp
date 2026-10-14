/*
 * Job Detail page: one job, its steps, and each step's parameters, to look at
 * or to change.
 *
 * The form for a step is not written here. It is drawn from the step catalog:
 * each step type's parameters, in order, with their types. A new step type
 * therefore appears on this page without any change to it.
 *
 * The page arrives locked. Edit unlocks it; Submit saves the whole job (its own
 * fields, and every step in the order shown) in one request; Cancel puts
 * everything back.
 *
 * API routes used:
 *     GET    /api/v1/jobs/{job_key}          the job, its steps and parameters
 *     GET    /api/v1/jobs/{job_key}/check    whether the job would run
 *     GET    /api/v1/step-types              the step catalog
 *     GET    /api/v1/jobs                    the list for the job selector
 *     GET    /api/v1/endpoints               the endpoints offered for a file location
 *     POST   /api/v1/jobs                    create a job
 *     PUT    /api/v1/jobs/{job_key}          save a job
 *     DELETE /api/v1/jobs/{job_key}          delete a job that has never run
 *     POST   /api/v1/endpoints               register an endpoint, from the "New..." link
 */
function jobDetail() {
    const address = new URLSearchParams(location.search);
    const TRUE_WORDS = ["true", "yes", "y", "1"];
    let nextUid = 1;        // gives each step on the page a name of its own, saved or not

    return {
        key: address.get("key") || "",
        isNew: address.has("new"),
        job: null,              // the job as last loaded or saved; null for one not yet saved
        form: null,             // what is on screen, edited or not
        saved: "",              // the form's contents when last loaded or saved, to tell whether anything changed
        catalog: {},            // step type code -> its catalog entry
        allKeys: [],            // every job key, for the selector
        endpoints: [],          // every registered endpoint, for the drop-down on a file location
        check: null,            // result of the pre-run check
        editing: false,
        busy: false,
        error: "",
        notice: "",             // what the last save did
        chosen: "",

        async init() {
            this.chosen = this.key;
            window.addEventListener("beforeunload", event => { if (this.changed) event.preventDefault(); });
            try {
                const [catalog, jobs, endpoints] = await Promise.all(
                    [AutoApp.get("/step-types"), AutoApp.get("/jobs"), AutoApp.get("/endpoints")]);
                this.catalog = Object.fromEntries(catalog.map(type => [type.code, type]));
                this.allKeys = jobs.map(job => job.job_key);
                this.endpoints = endpoints;
            } catch (e) {
                this.error = e.message;
                return;
            }
            if (this.isNew) {
                this.show({ job_key: "", description: "", active: true, steps: [] });
                this.editing = true;
            } else if (this.key) {
                await this.load();
                if (this.job && address.has("edit")) this.editing = true;
            }
        },

        async load() {
            this.busy = true;
            this.error = "";
            try {
                const path = "/jobs/" + encodeURIComponent(this.key);
                const [job, check] = await Promise.all([AutoApp.get(path), AutoApp.get(path + "/check")]);
                this.job = job;
                this.check = check;
                this.show(job);
            } catch (e) {
                this.job = null;
                this.form = null;
                this.error = e.message;
            }
            this.busy = false;
        },

        /** Puts a job on screen and remembers it as the unchanged state. */
        show(job) {
            this.form = {
                job_key: job.job_key,
                description: job.description || "",
                active: job.active,
                steps: job.steps.map(step => this.stepForm(step)),
            };
            this.saved = JSON.stringify(this.payload());
            document.title = `${job.job_key || "New job"} - AutoApp`;
        },

        /** The selector: typing narrows the list; choosing a job opens it. */
        choose() {
            if (this.allKeys.includes(this.chosen) && this.chosen !== this.key) {
                location.href = "job.html?" + new URLSearchParams({ key: this.chosen });
            }
        },

        // ---------- Building the form ----------

        /** One step as the page holds it. uid names it on the page; id is its id in the database, if saved. */
        stepForm(step) {
            return {
                uid: nextUid++,
                id: step.id ?? null,
                title: step.title || "",
                active: step.active,
                step_type: step.step_type,
                step_type_name: step.step_type_name || step.step_type,
                open: false,
                ...this.fieldsFor(step.step_type, step.parameters),
            };
        },

        /**
         * A step's form: one field per parameter in its step type's catalog entry, holding the step's
         * stored value. Anything the step stores that the step type does not have goes in "unknown".
         */
        fieldsFor(stepType, parameters) {
            const type = this.catalog[stepType];
            const known = new Set();
            const fields = (type ? type.parameters : []).map(param => {
                known.add(param.name);
                const stored = parameters[param.name] ?? null;
                const field = { ...param };
                if (param.data_type === "LOCATION") {
                    known.add(param.endpoint_parameter);
                    field.endpoint = parameters[param.endpoint_parameter] ?? "";
                    field.path = stored ?? "";
                    field.mode = field.endpoint ? "endpoint" : (field.path ? "path" : "");
                } else if (param.data_type === "BOOLEAN") {
                    // A true/false value written as a placeholder cannot be shown as a tick box
                    field.asText = stored !== null && String(stored).includes("${");
                    field.text = field.asText ? stored : "";
                    // "set" means the step stores a value of its own; otherwise the default applies
                    field.set = stored !== null && stored !== "";
                    field.ticked = TRUE_WORDS.includes(String(field.set ? stored : param.default).trim().toLowerCase());
                } else {
                    field.text = stored ?? "";
                }
                return field;
            });
            const unknown = Object.entries(parameters).filter(([name]) => !known.has(name))
                .map(([name, value]) => ({ name, value }));
            return { fields, unknown };
        },

        /** What the drop-down says beside an endpoint's name: whose it is and where it points. */
        endpointLabel(endpoint) {
            const owner = [endpoint.application, endpoint.entity, endpoint.site].filter(Boolean).join(" · ");
            return [owner, `${endpoint.path}/${endpoint.filename_pattern}`].filter(Boolean).join("  —  ");
        },

        isRegistered(name) {
            return this.endpoints.some(endpoint => endpoint.name === name.trim());
        },

        /**
         * Registers a new endpoint without leaving the page, starting from whatever was typed in the box,
         * and puts it in that box. It is registered at once; it does not wait for Submit.
         */
        async newEndpoint(field) {
            const typed = field.endpoint.trim();
            const created = await AutoApp.createInPlace("endpoint", { name: typed && !this.isRegistered(typed) ? typed : "" });
            if (!created) return;
            this.endpoints = [...this.endpoints, created].sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
            field.mode = "endpoint";
            field.endpoint = created.name;
        },

        isDefault(field) { return TRUE_WORDS.includes(String(field.default).trim().toLowerCase()); },

        /** Puts a true/false parameter back to "not set", so the step type's default applies. */
        useDefault(field) {
            field.set = false;
            field.ticked = this.isDefault(field);
        },

        /** Changing a step's type redraws its form, keeping the values of parameters both types have. */
        retype(step) {
            const kept = this.parametersOf(step);
            Object.assign(step, this.fieldsFor(step.step_type, kept));
            step.step_type_name = this.catalog[step.step_type]?.name || step.step_type;
        },

        // ---------- From the form to what is saved ----------

        parametersOf(step) {
            const parameters = {};
            for (const field of step.fields) {
                if (field.data_type === "LOCATION") {
                    if (field.mode === "endpoint" && field.endpoint.trim()) parameters[field.endpoint_parameter] = field.endpoint.trim();
                    if (field.mode === "path" && field.path.trim()) parameters[field.name] = field.path.trim();
                } else if (field.data_type === "BOOLEAN" && !field.asText) {
                    if (field.set) parameters[field.name] = field.ticked ? "True" : "False";
                } else if (String(field.text).trim() !== "") {
                    parameters[field.name] = String(field.text).trim();
                }
            }
            for (const extra of step.unknown) parameters[extra.name] = extra.value;
            return parameters;
        },

        /** The whole job as the API's save routes expect it. */
        payload() {
            return {
                job_key: this.form.job_key.trim(),
                description: this.form.description.trim() || null,
                active: this.form.active,
                steps: this.form.steps.map(step => ({
                    id: step.id, title: step.title.trim() || null, active: step.active,
                    step_type: step.step_type, parameters: this.parametersOf(step),
                })),
            };
        },

        get changed() {
            return Boolean(this.form) && this.editing && JSON.stringify(this.payload()) !== this.saved;
        },

        // ---------- Editing ----------

        edit() {
            this.editing = true;
            this.notice = "";
            this.error = "";
        },

        cancel() {
            if (this.changed && !confirm("Discard the changes you have made?")) return;
            if (!this.job) { location.href = "jobs.html"; return; }       // a new job, never saved
            this.editing = false;
            this.error = "";
            this.show(this.job);
        },

        addStep() {
            const type = Object.values(this.catalog)[0];
            const step = this.stepForm({ title: "", active: true, step_type: type.code, step_type_name: type.name, parameters: {} });
            step.open = true;
            this.form.steps.push(step);
        },

        removeStep(index) {
            const step = this.form.steps[index];
            if (confirm(`Remove step ${index + 1}${step.title ? " ('" + step.title + "')" : ""}?`)) this.form.steps.splice(index, 1);
        },

        /** Moves a step up (by -1) or down (by 1) the running order. */
        move(index, by) {
            const steps = this.form.steps;
            const target = index + by;
            if (target < 0 || target >= steps.length) return;
            steps.splice(target, 0, steps.splice(index, 1)[0]);
        },

        async submit() {
            const payload = this.payload();
            if (this.job && payload.job_key !== this.job.job_key && !confirm(
                `Rename this job from '${this.job.job_key}' to '${payload.job_key}'?\n\n` +
                "The scheduler runs it by its key, so every scheduler definition that uses the old key must be " +
                "changed too. Its working folder also changes, to one named after the new key.")) return;

            this.busy = true;
            this.error = "";
            this.notice = "";
            try {
                const result = this.job
                    ? await AutoApp.send("PUT", "/jobs/" + encodeURIComponent(this.job.job_key), payload)
                    : await AutoApp.send("POST", "/jobs", payload);
                this.job = result.job;
                this.check = { valid: result.valid, problems: result.problems };
                this.key = this.chosen = result.job.job_key;
                this.isNew = false;
                this.editing = false;
                this.show(result.job);
                this.notice = result.changes.length ? "Saved. " + result.changes.join(" ") : "Nothing had changed.";
                if (!this.allKeys.includes(this.key)) this.allKeys = (await AutoApp.get("/jobs")).map(job => job.job_key);
                history.replaceState(null, "", "job.html?" + new URLSearchParams({ key: this.key }));
            } catch (e) {
                this.error = e.message;
            }
            this.busy = false;
        },

        async remove() {
            if (!confirm(`Delete job '${this.job.job_key}' and all its steps? This cannot be undone.`)) return;
            this.busy = true;
            this.error = "";
            try {
                await AutoApp.send("DELETE", "/jobs/" + encodeURIComponent(this.job.job_key));
                this.saved = JSON.stringify(this.payload());       // nothing left to lose
                location.href = "jobs.html";
            } catch (e) {
                this.error = e.message;
                this.busy = false;
            }
        },

        // ---------- Showing the job ----------

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

        toggle(step) { step.open = !step.open; },
        expandAll(open) { for (const step of this.form.steps) step.open = open; },

        /** One line saying what a step does, shown while it is collapsed: "LEGAL_EXTRACTS -> incoming". */
        summary(step) {
            return step.fields.filter(f => f.data_type === "LOCATION")
                .map(f => f.mode === "endpoint" ? f.endpoint : f.path).filter(Boolean).join("  →  ");
        },
    };
}

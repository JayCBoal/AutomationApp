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
 * Steps can hold steps (docs/FLOW_CONTROL.md): an If holds its Then, any Else Ifs and
 * an Else, each holding steps; For Each File and While hold steps directly. The page
 * keeps them as a tree (each step's "children") and draws the tree as a list of rows,
 * indented, numbered 3, 3.1, 3.2 as the job log numbers them (see "rows").
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
 *     POST   /api/v1/jobs/preview            what the job on screen would resolve to, saved or not
 */
function jobDetail() {
    const address = new URLSearchParams(location.search);
    const TRUE_WORDS = ["true", "yes", "y", "1"];
    // The parts of an If, never chosen from the list of step types; shown as headers of their If
    const BRANCHES = { THEN: "Then", ELSEIF: "Else If", ELSE: "Else" };
    const isBranch = step => step.step_type in BRANCHES;
    let nextUid = 1;        // gives each step on the page a name of its own, saved or not

    // Bookkeeping for the preview. Kept out of the page's own state on purpose: the page re-runs
    // queuePreview whenever state it has read changes, so a timer kept there would set itself off.
    let previewTimer = null;
    let previewRequest = 0;
    let previewAsked = "";      // the form contents most recently sent, or waiting to be sent
    const ownVariables = function () { return this.form ? this.form.variables.map(v => v.name.trim()).filter(Boolean) : []; };

    return {
        ...AutoApp.tagEditing(ownVariables),
        key: address.get("key") || "",
        isNew: address.has("new"),
        embedded: AutoApp.EMBEDDED,     // opened from inside a scheduler: one job, no way to wander off to others
        // Opened for one of a scheduler's jobs (scheduler=...&wla_job=...): the parameters it will run with
        wla: address.get("scheduler") && address.get("wla_job")
            ? { scheduler: address.get("scheduler"), job: address.get("wla_job") } : null,
        wlaJob: null,           // that job as the scheduler gives it, with its parameters
        wlaError: "",
        job: null,              // the job as last loaded or saved; null for one not yet saved
        form: null,             // what is on screen, edited or not
        saved: "",              // the form's contents when last loaded or saved, to tell whether anything changed
        catalog: {},            // step type code -> its catalog entry
        allKeys: [],            // every job key, for the selector
        endpoints: [],          // every registered endpoint, for the drop-down on a file location
        check: null,            // result of the pre-run check, for the job as saved
        preview: null,          // what the job as it is on screen would resolve to, and whether it would run
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
                    [AutoApp.get("/step-types"), AutoApp.get("/jobs"), AutoApp.get("/endpoints"), AutoApp.ensureLookups()]);
                this.catalog = Object.fromEntries(catalog.map(type => [type.code, type]));
                this.allKeys = jobs.map(job => job.job_key);
                this.endpoints = endpoints;
            } catch (e) {
                this.error = e.message;
                return;
            }
            if (this.wla) await this.loadWlaJob();
            if (this.isNew) {
                // A scheduler creating a job can suggest its key: job.html?new&key=...
                this.show({ job_key: this.key, description: "", active: true, steps: [], variables: [], tags: [] });
                // Compared with a blank job, so one whose key was suggested can be saved as it is
                this.saved = JSON.stringify({ ...this.payload(), job_key: "" });
                this.key = "";
                this.editing = true;
            } else if (this.key) {
                await this.load();
                if (this.job && address.has("edit")) this.editing = true;
            }
            AutoApp.tellHost("ready", this.job
                ? { job_key: this.job.job_key, exists: true, valid: Boolean(this.check && this.check.valid) }
                : { job_key: this.form ? this.form.job_key : this.key, exists: false });
        },

        async load() {
            this.busy = true;
            this.error = "";
            try {
                const path = "/jobs/" + encodeURIComponent(this.key);
                const [job, check] = await Promise.all([AutoApp.get(path), AutoApp.get(path + "/check", this.wlaQuery())]);
                if (job.job_type === "WORKFLOW") {          // a workflow has its own page
                    location.replace("workflow.html?" + address.toString());
                    return;
                }
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
                success_return_codes: job.success_return_codes || "",
                steps: job.steps.map(step => this.stepForm(step)),
                variables: (job.variables || []).map(variable => ({
                    uid: nextUid++,
                    name: variable.name,
                    value: variable.value ?? "",
                    secret: variable.secret,
                    description: variable.description || "",
                    // A saved secret's value is never sent to the page. Left blank, it is kept as it is.
                    savedSecret: variable.secret,
                })),
                tags: [...(job.tags || [])],
            };
            this.saved = JSON.stringify(this.payload());
            this.tagCandidate = "";
            this.tagPreview = null;
            this.refreshTags();
            document.title = `${job.job_key || "New job"} - AutoApp`;
        },

        /** The scheduler's job, for the preview and the pre-run check: { scheduler, wla_job }, or nothing. */
        wlaQuery() { return this.wla ? { scheduler: this.wla.scheduler, wla_job: this.wla.job } : {}; },

        /** Reads the scheduler's job through AutoApp's connector for it. A failure is shown, not fatal. */
        async loadWlaJob() {
            try {
                this.wlaJob = await AutoApp.get(`/schedulers/${encodeURIComponent(this.wla.scheduler)}/jobs/${encodeURIComponent(this.wla.job)}`);
            } catch (e) {
                this.wlaError = e.message;
            }
        },

        /** The selector: typing narrows the list; choosing a job opens it. */
        choose() {
            if (this.allKeys.includes(this.chosen) && this.chosen !== this.key) {
                AutoApp.go("job.html?" + new URLSearchParams({ key: this.chosen }));
            }
        },

        // ---------- Building the form ----------

        /** One step as the page holds it. uid names it on the page; id is its id in the database, if saved. */
        stepForm(step) {
            return {
                uid: nextUid++,
                id: step.id ?? null,
                title: step.title || "",
                // A saved step keeps its name: other steps may read %{Name.Status}. A new one takes it from its title.
                name: step.name || "",
                nameEdited: step.id != null,
                active: step.active,
                on_failure: step.on_failure || "FAIL_JOB",
                step_type: step.step_type,
                step_type_name: step.step_type_name || step.step_type,
                open: false,
                ...this.fieldsFor(step.step_type, step.parameters),
                children: (step.children || []).map(child => this.stepForm(child)),
            };
        },

        /** A new step of a type, empty. An If comes with its Then, and an Else If with its own. */
        newStep(code) {
            const type = this.catalog[code];
            const step = this.stepForm({ title: "", active: true, step_type: code, step_type_name: type ? type.name : code,
                                         parameters: {} });
            if (code === "IF" || code === "ELSEIF") step.children = [this.newStep("THEN")];
            return step;
        },

        /** The name a new step takes from its title, as the server makes it: spaces become underscores. */
        nameFromTitle(title) {
            let name = title.trim().replace(/\s+/g, "_").replace(/[^A-Za-z0-9_]/g, "").replace(/^_+|_+$/g, "").slice(0, 64);
            if (name && !/^[A-Za-z]/.test(name)) name = ("Step_" + name).slice(0, 64);
            return name;
        },

        /** Typing a title names the step too, until its name is changed by hand. */
        titleTyped(step) {
            if (!step.nameEdited) step.name = this.nameFromTitle(step.title);
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

        // A several-line box tall enough for what is in it (a long line wraps at about 55 characters)
        textRows(text) {
            const lines = String(text || "").split("\n");
            const rows = lines.reduce((total, line) => total + Math.max(1, Math.ceil(line.length / 55)), 0);
            return Math.min(16, Math.max(3, rows + 1));
        },
        isDefault(field) { return TRUE_WORDS.includes(String(field.default).trim().toLowerCase()); },

        /** Puts a true/false parameter back to "not set", so the step type's default applies. */
        useDefault(field) {
            field.set = false;
            field.ticked = this.isDefault(field);
        },

        /**
         * Changing a step's type redraws its form, keeping the values of parameters both types have.
         * The steps inside it are kept: in an If's Then, in a loop, or after it when it can hold none.
         */
        retype(step) {
            const kept = this.parametersOf(step);
            Object.assign(step, this.fieldsFor(step.step_type, kept));
            step.step_type_name = this.catalog[step.step_type]?.name || step.step_type;
            const inside = this.bodyOf(step);
            if (step.step_type === "IF") {
                step.children = [this.newStep("THEN")];
                step.children[0].children = inside;
            } else if (this.isBlock(step)) {
                step.children = inside;
            } else {
                step.children = [];
                const { list, index } = this.locate(step);
                list.splice(index + 1, 0, ...inside);
            }
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

        /** One step, and the steps inside it, as the API's save routes expect them. */
        stepPayload(step) {
            return {
                id: step.id, title: step.title.trim() || null, name: step.name.trim() || null, active: step.active,
                on_failure: step.on_failure, step_type: step.step_type, parameters: this.parametersOf(step),
                children: step.children.map(child => this.stepPayload(child)),
            };
        },

        /** The whole job as the API's save routes expect it. */
        payload() {
            return {
                job_key: this.form.job_key.trim(),
                description: this.form.description.trim() || null,
                active: this.form.active,
                success_return_codes: this.form.success_return_codes.trim() || null,
                steps: this.form.steps.map(step => this.stepPayload(step)),
                variables: this.form.variables.map(variable => ({
                    name: variable.name.trim(),
                    value: variable.secret && variable.savedSecret && variable.value === "" ? null : variable.value,
                    secret: variable.secret,
                    description: variable.description.trim() || null,
                })),
                tags: [...this.form.tags],
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
            if (!this.job) {                                            // a new job, never saved
                if (!this.embedded) { AutoApp.go("jobs.html"); return; }
                // Inside a scheduler, the scheduler decides what happens next; the page starts again
                AutoApp.tellHost("cancelled", { job_key: this.form.job_key });
                this.show({ job_key: new URLSearchParams(location.search).get("key") || "", description: "",
                            active: true, steps: [], variables: [], tags: [] });
                return;
            }
            this.editing = false;
            this.error = "";
            this.show(this.job);
        },

        // ---------- Variables ----------

        /** Adds a variable to the job, and puts the cursor in its first empty box. */
        addVariable(name = "") {
            const variable = { uid: nextUid++, name, value: "", secret: false, description: "", savedSecret: false };
            this.form.variables.push(variable);
            this.$nextTick(() => {
                const row = document.querySelector(`[data-variable="${variable.uid}"]`);
                if (row) row.querySelector(name ? ".variable-value" : ".variable-name").focus();
            });
        },

        removeVariable(index) { this.form.variables.splice(index, 1); },

        /**
         * The variables a value mentions that the job does not have, e.g. ["ArchiveFolder"] for
         * "${ArchiveFolder}/in". Each is offered as "Add variable ..." beside the value.
         */
        missingVariables(text) {
            // its own variables, those its tags give it, and the scheduler's parameters
            const have = new Set(this.form.variables.map(variable => variable.name.trim())
                .concat(this.tagsView ? this.tagsView.variables.map(variable => variable.name) : [])
                .concat(this.wlaJob ? this.wlaJob.parameters.map(parameter => parameter.name) : []));
            const mentioned = [...String(text || "").matchAll(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g)].map(match => match[1]);
            return [...new Set(mentioned)].filter(name => !have.has(name));
        },

        // ---------- Preview: what the job on screen would resolve to ----------

        /**
         * Asks the server what the form's contents would resolve to, shortly after they
         * stop changing. Nothing is saved by asking.
         */
        queuePreview(contents) {
            if (contents === previewAsked) return;
            previewAsked = contents;
            clearTimeout(previewTimer);
            previewTimer = setTimeout(async () => {
                const request = ++previewRequest;
                const query = { ...(this.job ? { existing_key: this.job.job_key } : {}), ...this.wlaQuery() };
                const address = "/jobs/preview" + (Object.keys(query).length ? "?" + new URLSearchParams(query) : "");
                let result;
                try {
                    result = await AutoApp.send("POST", address, JSON.parse(contents));
                } catch (e) {
                    // What is on screen could not be saved as it stands (a key already taken, say): show that as the problem
                    result = { valid: false, problems: [e.message], steps: [] };
                }
                if (request !== previewRequest) return;            // the form has changed again since
                this.preview = result;
            }, 350);
        },

        /** The preview for one field of one step: { resolved, error }, or null if there is none yet. */
        previewOf(index, field) {
            const step = this.preview && this.preview.steps[index];
            return (step && step[field.name]) || null;
        },

        /** Whether to show what a field resolves to: always for a location, otherwise only if it has a placeholder. */
        showsResolved(index, field) {
            const preview = this.previewOf(index, field);
            if (!preview || preview.resolved === null) return false;
            return field.data_type === "LOCATION" || String(field.text || "").includes("${");
        },

        /** What the preview says is worth knowing about a field: a condition comparing text with a number. */
        warningsOf(index, field) {
            const preview = this.previewOf(index, field);
            return (preview && preview.warnings) || [];
        },

        // ---------- Steps inside steps ----------

        /** The step types offered in a step's list: all but the parts of an If. */
        get choosableTypes() { return Object.values(this.catalog).filter(type => !type.hidden); },

        isBlock(step) { return Boolean(this.catalog[step.step_type] && this.catalog[step.step_type].block); },

        /**
         * The job's steps as the rows the page draws, in order, each block before the steps inside it:
         *   "step"      a step, with its number (3.1) and how deep it sits
         *   "branch"    an If's Then, Else If or Else, as a header
         *   "add"       the place to add a step to a block; "if-tools", to give an If an Else If or Else
         * flatIndex is the step's place counting every step, branches too, as the preview counts them.
         */
        get rows() {
            const rows = [];
            let flat = 0;
            const visit = (list, depth, prefix, counter, owner) => {
                list.forEach((step, index) => {
                    const flatIndex = flat++;
                    if (isBranch(step)) {
                        rows.push({ key: "b" + step.uid, kind: "branch", step, depth, flatIndex, list, index, owner });
                        // An Else If's own Then is part of its header; its steps follow it
                        const holder = step.step_type === "ELSEIF" ? step.children[0] : step;
                        if (!holder) return;
                        if (holder !== step) flat++;
                        visit(holder.children, depth + 1, prefix, counter, holder);
                        rows.push({ key: "a" + holder.uid, kind: "add", into: holder, depth: depth + 1 });
                        return;
                    }
                    counter.n += 1;
                    const number = prefix ? prefix + "." + counter.n : String(counter.n);
                    rows.push({ key: "s" + step.uid, kind: "step", step, depth, number, flatIndex, list, index, owner });
                    if (!this.isBlock(step) && step.children.length === 0) return;
                    // The steps of all an If's branches are numbered in one run: 3.1, 3.2, 3.3
                    visit(step.children, depth + 1, number, { n: 0 }, step);
                    rows.push(step.step_type === "IF"
                        ? { key: "i" + step.uid, kind: "if-tools", step, depth: depth + 1 }
                        : { key: "a" + step.uid, kind: "add", into: step, depth: depth + 1 });
                });
            };
            visit(this.form.steps, 0, "", { n: 0 }, null);
            return rows;
        },

        /** Where a step sits: the list holding it, its place there, and the step that list belongs to. */
        locate(target, list = this.form.steps, owner = null) {
            const index = list.indexOf(target);
            if (index >= 0) return { list, index, owner };
            for (const step of list) {
                const found = this.locate(target, step.children, step);
                if (found) return found;
            }
            return null;
        },

        /**
         * The steps inside a block, leaving out an If's Then, Else If and Else themselves. Told from what
         * it holds, not its type, as retype() asks after the type has already changed.
         */
        bodyOf(step) {
            return step.children.flatMap(child => !isBranch(child) ? [child]
                : child.step_type === "ELSEIF" ? (child.children[0] ? child.children[0].children : [])
                : child.children);
        },

        /** The block step a step is in, for moving the step out of it; null at the top level. */
        enclosing(row) {
            if (!row.owner) return null;
            let block = row.owner;
            if (isBranch(block)) {                      // a Then, Else If or Else: the If it belongs to
                block = this.locate(block).owner;
                if (block.step_type === "ELSEIF") block = this.locate(block).owner;
            }
            return { block, ...this.locate(block) };
        },

        /** The list a step joins when moved into the block just above it; null if that is not a block. */
        intoAbove(row) {
            const above = row.list[row.index - 1];
            if (!above || isBranch(above) || !this.isBlock(above)) return null;
            if (above.step_type !== "IF") return above.children;
            const last = above.children[above.children.length - 1];        // its last branch
            return last.step_type === "ELSEIF" ? last.children[0].children : last.children;
        },

        addStep(into = null) {
            // Most steps move files, so a new one starts as Copy Files; the list is alphabetical
            const step = this.newStep(this.catalog.COPY_FILES ? "COPY_FILES" : this.choosableTypes[0].code);
            step.open = true;
            (into ? into.children : this.form.steps).push(step);
        },

        /** Gives an If an Else If (before its Else, if it has one) or an Else. */
        addBranch(ifStep, code) {
            const branch = this.newStep(code);
            branch.open = true;
            const elseAt = ifStep.children.findIndex(b => b.step_type === "ELSE");
            if (code === "ELSEIF" && elseAt >= 0) ifStep.children.splice(elseAt, 0, branch);
            else ifStep.children.push(branch);
        },

        hasElse(ifStep) { return ifStep.children.some(b => b.step_type === "ELSE"); },

        removeStep(row) {
            const step = row.step;
            const inside = this.bodyOf(step).length;
            const what = isBranch(step) ? "this " + BRANCHES[step.step_type]
                : "step " + row.number + (step.title ? " ('" + step.title + "')" : "");
            const along = inside ? " and the " + (inside === 1 ? "step" : inside + " steps") + " inside it" : "";
            if (confirm("Remove " + what + along + "?")) row.list.splice(row.index, 1);
        },

        /** Moves a step up (by -1) or down (by 1) among the steps of its block, taking the steps inside it along. */
        move(row, by) {
            const target = row.index + by;
            if (target < 0 || target >= row.list.length) return;
            row.list.splice(target, 0, row.list.splice(row.index, 1)[0]);
        },

        /** Moves a step into the block just above it, as that block's last step. */
        moveIn(row) {
            const into = this.intoAbove(row);
            if (into) into.push(row.list.splice(row.index, 1)[0]);
        },

        /** Moves a step out of the block it is in, to just after that block. */
        moveOut(row) {
            const outer = this.enclosing(row);
            if (!outer) return;
            row.list.splice(row.index, 1);
            outer.list.splice(outer.list.indexOf(outer.block) + 1, 0, row.step);
        },

        /** Every step in the job, blocks and the steps inside them. */
        allSteps(list = this.form.steps) {
            return list.flatMap(step => [step, ...this.allSteps(step.children)]);
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
                const previousKey = this.job ? this.job.job_key : null;
                const result = this.job
                    ? await AutoApp.send("PUT", "/jobs/" + encodeURIComponent(this.job.job_key), payload)
                    : await AutoApp.send("POST", "/jobs", payload);
                AutoApp.tellHost("saved", {
                    job_key: result.job.job_key, previous_key: previousKey !== result.job.job_key ? previousKey : null,
                    created: previousKey === null, valid: result.valid, problems: result.problems, changes: result.changes,
                });
                this.job = result.job;
                this.check = { valid: result.valid, problems: result.problems };
                // The save's own verdict stands until a fresh preview arrives; any older one is discarded
                clearTimeout(previewTimer);
                previewRequest++;
                previewAsked = "";
                this.preview = null;
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
                if (this.embedded) {
                    // The scheduler decides what happens next; there is no job left to show
                    AutoApp.tellHost("deleted", { job_key: this.job.job_key });
                    this.notice = `Deleted job '${this.job.job_key}'.`;
                    this.job = this.form = null;
                    this.editing = this.busy = false;
                    return;
                }
                AutoApp.go("jobs.html");
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

        /** Whether the job would run: as it is on screen once that has been worked out, else as saved. */
        get verdict() { return this.preview || this.check; },

        /** What does not stop the job but is worth knowing, as of the latest preview. */
        get warnings() { return (this.verdict && this.verdict.warnings) || []; },

        /** What stops the job running, other than its being disabled, which is shown separately. */
        get problems() {
            if (!this.verdict) return [];
            return this.verdict.problems.filter(problem => !problem.endsWith("is disabled."));
        },

        toggle(step) { step.open = !step.open; },
        expandAll(open) { for (const step of this.allSteps()) step.open = open; },

        /** How far a row is indented: the steps inside a block sit to the right of it. */
        indent(row) { return { marginLeft: (row.depth * 28) + "px" }; },

        /**
         * One line saying what a step does, shown while it is collapsed: "LEGAL_EXTRACTS -> incoming",
         * or for an If or a While, its condition.
         */
        summary(step) {
            const condition = step.fields.find(f => f.name === "Condition");
            if (condition) return condition.text;
            return step.fields.filter(f => f.data_type === "LOCATION")
                .map(f => f.mode === "endpoint" ? f.endpoint : f.path).filter(Boolean).join("  →  ");
        },
    };
}

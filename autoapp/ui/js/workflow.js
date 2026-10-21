/*
 * Workflow page: one workflow, the jobs it runs and what each waits for, in the Outline
 * view (docs/WORKFLOWS.md; docs/WORKFLOWS_PHASE1.md, step 4). Also its runs: Run starts
 * one, and a run is shown in the same outline with each job's state, live while it goes.
 *
 * A workflow is a job of type WORKFLOW, saved through the jobs API. The page arrives
 * locked; Edit unlocks it; Save saves the whole workflow; Cancel puts it back. The job
 * page sends a workflow here, so job.html?key=... works for both.
 *
 * Each job on the page has a uid of its own, and a prerequisite points at that uid, so
 * renaming a job keeps what waits for it.
 *
 * Diagram | Outline (docs/WORKFLOWS_PHASE2.md): the diagram (js/workflow_diagram.js) draws the
 * same items; selecting a box shows that item's part of the outline beside it, where it is
 * edited as in the outline; dragging from box to box adds a prerequisite. The page remembers
 * the view and the direction last used, in this browser only.
 *
 * API routes used:
 *     GET    /api/v1/jobs/{key}, /api/v1/jobs/{key}/check, /api/v1/jobs
 *     POST   /api/v1/jobs, PUT /api/v1/jobs/{key}, DELETE /api/v1/jobs/{key}
 *     POST   /api/v1/launches                    Run
 *     GET    /api/v1/runs?job_key=...&job_type=WORKFLOW, GET /api/v1/runs/{run_id}
 *     POST   /api/v1/runs/{run_id}/cancel, /api/v1/runs/{run_id}/kill (Kill and Cancel)
 *     POST   /api/v1/runs/{run_id}/items/{path}/kill (Kill one job of the run)
 *     Rerun ▸ on the run, and on a failed job or frame in it: rerun.js
 *
 * Reactions (docs/WORKFLOWS_PHASE3.md, js/reactions.js): the workflow's own, and on each job its
 * job's, or this use's own once Override here is chosen. Disable here stops a job or lets it
 * pass through, in this workflow only.
 *
 * Conditions (docs/WORKFLOWS_PHASE4.md, js/conditions.js): a job's Start rule can be a Custom
 * rule, written in the condition box; the jobs it names are what it waits for, drawn as lines.
 * Renaming a job renames it in the rules. The workflow's completion rules: Succeeds when and
 * its return code. A run explains each rule's decision, part by part, and what each job waited for.
 *     GET /api/v1/conditions/outputs, POST /api/v1/conditions/check, POST /api/v1/conditions/explain
 *
 * Outside dependencies (docs/WORKFLOWS_PHASE5.md): besides the jobs of the workflow, a job can wait for a job or
 * workflow elsewhere, for files at an endpoint, or for the time (item.outside), each with how long it is patient
 * and whether it is required. The diagram draws them as dashed boxes at its edges, and the jobs elsewhere that
 * wait for a job (Needed by) on the far side.
 *     GET /api/v1/conditions/outside-outputs
 */
/** Whether a prerequisite held, given the run's item it names: "true", "false" or "unknown" (as engine/workflow_runner.py). */
function prerequisiteAnswer(p, target) {
    const FINAL = ["SUCCESS", "FAILED", "NOT_RUN", "DISABLED", "BYPASSED", "SKIPPED"];
    if (!FINAL.includes(target.status)) return "unknown";
    const status = target.status === "BYPASSED" ? "SUCCESS" : target.status;
    const code = target.status === "BYPASSED" ? 0 : target.return_code;
    if (p.test === "ENDED") return "true";
    if (p.test === "SUCCESS") return String(status === "SUCCESS");
    if (p.test === "FAILED") return String(status === "FAILED");
    if (code === null || code === undefined) return "false";
    const held = (p.return_codes || "").split(",").map(s => s.trim()).filter(Boolean).some(piece => {
        const range = piece.match(/^(\d+)\s*-\s*(\d+)$/);
        return range ? code >= Number(range[1]) && code <= Number(range[2]) : code === Number(piece);
    });
    return String(held);
}

function workflowDetail() {
    const address = new URLSearchParams(location.search);
    const TESTS = { SUCCESS: "succeeded", FAILED: "failed", ENDED: "ended, whatever happened", RC: "gave return codes" };
    const STATES = { PENDING: "Not started yet", WAITING: "Waiting", RUNNING: "Running", SUCCESS: "Succeeded",
                     FAILED: "Failed", NOT_RUN: "Not run", DISABLED: "Disabled", BYPASSED: "Bypassed", SKIPPED: "Skipped" };
    const REASONS = { PREREQUISITES_NOT_MET: "its prerequisites can't be met", CANCELLED: "the workflow was cancelled",
                      RETURN_CODE: "its return code is not a success code", ERROR: "a step failed",
                      JOB_FAILED: "a failure went unhandled", KILLED: "killed",
                      DISABLED_PASS_THROUGH: "disabled here, to pass through", SUCCEEDS_WHEN: "Succeeds when did not hold" };
    const OUTSIDE_KINDS = { OTHER_JOB: "a job in another workflow", ENDPOINT: "files", TIME: "a time" };
    const WAIT_FROM = { OTHERS: "the job's other prerequisites have held", FIRST: "the first of them has held",
                        CHOSEN: "the one chosen has held", RUN_START: "the workflow run started" };
    const cleanName = text => (text || "").trim().replace(/[^A-Za-z0-9_.-]/g, "_");
    const POLL_MS = 1500;
    const EXTERNAL_KEY = "autoapp.workflow.external", CONDITIONS_KEY = "autoapp.workflow.conditions";
    const VIEW_KEY = "autoapp.workflow.view", DIRECTION_KEY = "autoapp.workflow.direction", SIDE_KEY = "autoapp.workflow.sideWidth";
    const SIDE_MIN = 320, DIAGRAM_MIN = 300;
    const ZOOM_STEP = 1.2, ZOOM_MIN = 0.3, ZOOM_MAX = 2.5;
    let nextUid = 1;
    const SIMPLE_PLACEHOLDER = /\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g;     // ${Region}, not ${DATE:...} or ${SYS:...}
    const DEFAULT_PRECEDENCE = ["ENV", "SYS", "ENTITY", "APP", "ENDPOINT", "TAG", "WORKFLOW", "JOB", "USE"];
    const ownVariables = function () { return this.form ? this.form.variables.map(v => v.name.trim()).filter(Boolean) : []; };
    let pollTimer = null;
    const sharedKeys = {};      // the key of the workflow each box opened inline stands for, by its id (drawn, not state)

    /** An item's name made from its job key, as the server makes it. */
    const defaultName = key => {
        const name = (key || "").trim().replace(/[^A-Za-z0-9_-]/g, "_");
        return name && !/^[A-Za-z0-9]/.test(name) ? "J" + name : name;
    };

    /** A choice remembered in this browser, if it allows; the default otherwise. */
    const remembered = (key, allowed, fallback) => {
        try {
            const value = localStorage.getItem(key);
            return allowed.includes(value) ? value : fallback;
        } catch (e) { return fallback; }
    };
    const remember = (key, value) => {
        try { localStorage.setItem(key, value); } catch (e) { /* private browsing: not remembered */ }
    };

    return {
        ...rerunDialog(),
        ...AutoApp.tagEditing(ownVariables),
        ...AutoApp.reactionEditing(),
        key: address.get("key") || "",
        isNew: address.has("new"),
        runId: address.get("run") || "",
        job: null,              // the workflow as last loaded or saved
        form: null,             // what is on screen
        saved: "",
        check: null,            // the pre-run check of the workflow as saved
        allJobs: [],            // every job and workflow, for the job boxes and the selector
        runs: [],               // the workflow's recent runs
        run: null,              // the run being shown, if any
        editing: false,
        busy: false,
        error: "",
        notice: "",
        chosen: "",
        view: remembered(VIEW_KEY, ["diagram", "outline"], "diagram"),
        direction: remembered(DIRECTION_KEY, ["RIGHT", "DOWN"], "RIGHT"),
        zoom: 1,                // a number, or "fit"
        showExternal: remembered(EXTERNAL_KEY, ["shown", "hidden"], "shown") === "shown",   // jobs and workflows elsewhere drawn as boxes
        showConditions: remembered(CONDITIONS_KEY, ["shown", "hidden"], "hidden") === "shown",   // files and times drawn as boxes
        find: "",
        folded: {},             // the frames folded on the diagram, by the uid of their item (or a run's path): this page only
        opened: {},             // the workflows of their own opened inline on the diagram, read only, by the id of their box
        selectedUid: null,      // the item selected on the diagram
        selectedLine: null,     // the prerequisite selected on the diagram (its uid), if a line was
        runSelected: "",        // the name of the item selected on a run's diagram
        themeTick: 0,           // changes with the theme, so the diagrams are drawn again in its colours
        sideWidth: (() => { try { return Number(localStorage.getItem(SIDE_KEY)) || 0; } catch (e) { return 0; } })(),   // 0: the usual width
        savedKeys: {},          // each saved job as it was saved (itemKey), by its id, to mark the ones changed since
        nameBefore: "",         // a job's name as it was when its name (or job) box was entered, to carry renames
        conditionOutputs: [],   // what every job offers to conditions
        jobDetails: {},         // each job used, as the server has it, by key: its steps are shown beside a use
        outsideOutputs: { endpoint: [], now: [] },     // what files and the time offer to conditions
        precedence: DEFAULT_PRECEDENCE,     // the Variable precedence setting, lowest priority first

        async init() {
            this.chosen = this.key;
            new MutationObserver(() => this.themeTick++).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
            window.addEventListener("beforeunload", event => { if (this.changed) event.preventDefault(); });
            try {
                await AutoApp.ensureLookups();
                this.precedence = await this.loadPrecedence();
                this.allJobs = await AutoApp.get("/jobs");
                AutoApp.loadReactionWorkflows();
                this.conditionOutputs = await AutoApp.loadConditionOutputs();
                this.outsideOutputs = await AutoApp.get("/conditions/outside-outputs");
            } catch (e) {
                this.error = e.message;
                return;
            }
            if (this.isNew) {
                this.show({ job_key: "", description: "", active: true, items: [], reactions: [], succeeds_when: null, return_code_from: null,
                            variables: [], tags: [] });
                this.editing = true;
            } else if (this.key) {
                await this.load();
                if (this.job && address.has("edit")) this.editing = true;
            }
            if (this.runId) this.followRun();
        },

        /** The workflows a job can wait for: those of their own, and the ones embedded in this workflow. */
        get workflowKeys() {
            const embedded = this.form ? this.form.items.filter(i => i.embedded && i.jobType === "WORKFLOW" && i.job_key).map(i => i.job_key) : [];
            const own = this.job && this.job.job_key ? [this.job.job_key] : [];
            return [...new Set([...this.allJobs.filter(j => j.job_type === "WORKFLOW").map(j => j.job_key), ...own, ...embedded])];
        },
        get jobKeys() { return this.allJobs.map(j => j.job_key).filter(k => !this.job || k !== this.job.job_key); },

        async load() {
            this.busy = true;
            this.error = "";
            try {
                const path = "/jobs/" + encodeURIComponent(this.key);
                const [job, check] = await Promise.all([AutoApp.get(path), AutoApp.get(path + "/check")]);
                if (job.job_type !== "WORKFLOW") {          // a job made of steps has its own page
                    location.replace("job.html?" + address.toString());
                    return;
                }
                this.job = job;
                this.check = check;
                this.show(job);
                await this.loadRuns();
            } catch (e) {
                this.job = null;
                this.form = null;
                this.error = e.message;
            }
            this.busy = false;
        },

        async loadRuns() {
            const runs = await AutoApp.get("/runs", { job_key: this.job.job_key, job_type: "WORKFLOW", limit: 20 });
            this.runs = runs.filter(r => r.job_key === this.job.job_key);
        },

        /** Puts a workflow on screen and remembers it as the unchanged state. */
        show(job) {
            const items = [];
            this.jobDetails[job.job_key] = job;                // so a job can wait for one in this tree, whatever frame it is in
            this.addLevel(items, job, null);
            this.form = { job_key: job.job_key, description: job.description || "", active: job.active, items,
                          reactions: this.reactionsForm(job.reactions), succeeds_when: job.succeeds_when || "",
                          succeeds_choice: job.succeeds_when ? "RULE" : "DEFAULT", return_code_from: job.return_code_from || "",
                          variables: this.variablesForm(job.variables), tags: [...(job.tags || [])] };
            this.tagCandidate = "";
            this.tagPreview = null;
            this.refreshTags();
            this.saved = JSON.stringify(this.payload());
            this.savedKeys = Object.fromEntries(items.filter(i => i.id).map(i => [i.id, this.itemKey(i)]));
            document.title = `${job.job_key || "New workflow"} - AutoApp`;
        },

        /**
         * Adds the items of one workflow, and of the workflows embedded in it (frames), to the flat list the page keeps:
         * parent is the uid of the frame an item is in, null at the top. A prerequisite points at an item of the same level.
         */
        addLevel(list, detail, parent) {
            const uids = {};
            const level = (detail.items || []).map(item => {
                uids[item.name] = nextUid++;
                return this.itemForm(item, uids[item.name], parent);
            });
            (detail.items || []).forEach((item, index) => {
                if (item.join !== "CUSTOM") {                   // a Custom rule says which of the workflow's jobs it waits for
                    level[index].prerequisites = item.prerequisites.filter(p => p.kind === "JOB").map(p => ({
                        uid: nextUid++, target: uids[p.target], test: p.test, return_codes: p.return_codes || "" }));
                }
                level[index].outside = this.outsideForm(item.prerequisites.filter(p => p.kind !== "JOB"), level[index]);
            });
            list.push(...level);
            (detail.items || []).forEach((item, index) => {
                if (item.embedded && item.contents) this.jobDetails[item.job_key] = item.contents;
                if (item.embedded && item.contents && item.contents.job_type === "WORKFLOW") this.addLevel(list, item.contents, level[index].uid);
            });
        },

        /** One item as the page keeps it. An embedded one also carries what its job is made of (inner). */
        itemForm(item, uid, parent) {
            const contents = item.embedded ? item.contents : null;
            return { uid, id: item.id, parent, name: item.name, job_key: item.job_key, join: item.join, prerequisites: [],
                     outside: [], on_unmet: item.on_unmet || "NOT_RUN", needed_by: item.needed_by || [],
                     rule: item.rule || "", joinBefore: item.join,
                     disabled_here: item.disabled_here || "", reactions_overridden: Boolean(item.reactions_overridden),
                     reactions: this.reactionsForm(item.reactions), job_reactions: this.reactionsForm(item.job_reactions),
                     variables: this.variablesForm(item.variables), embedded: Boolean(item.embedded), jobType: item.job_type,
                     inner: contents ? this.innerForm(contents) : null };
        },

        /** What an embedded job or workflow carries besides its items: its description, whether it is enabled, its variables. */
        innerForm(contents) {
            return { job_type: contents.job_type, description: contents.description || "", active: contents.active,
                     variables: this.variablesForm(contents.variables), succeeds_when: contents.succeeds_when,
                     return_code_from: contents.return_code_from };
        },

        // ---------- What a job waits for outside its workflow ----------

        blankOutside(kind = "OTHER_JOB") {
            return { uid: nextUid++, kind, name: "", workflow: "", job: "", test: "SUCCESS", return_codes: "", look_back_hours: "",
                     only_after_start: false, endpoint: "", file_pattern: "", min_age_seconds: "", time_condition: "",
                     wait_mode: "DEFAULT", wait_minutes: "", wait_until: "", wait_from: "OTHERS", wait_from_uid: null, required: true };
        },

        /** The outside prerequisites the server gave one job, as the page keeps them; "count from" points at the one it names. */
        outsideForm(list, item) {
            const found = list.map(p => ({ ...this.blankOutside(p.kind), name: p.target, workflow: p.workflow || "", job: p.job || "",
                test: p.test, return_codes: p.return_codes || "", look_back_hours: p.look_back_hours ?? "",
                only_after_start: Boolean(p.only_after_start), endpoint: p.endpoint || "", file_pattern: p.file_pattern || "",
                min_age_seconds: p.min_age_seconds ?? "", time_condition: p.time_condition || "", wait_mode: p.wait_mode,
                wait_minutes: p.wait_minutes ?? "", wait_until: p.wait_until || "", wait_from: p.wait_from,
                required: p.required, chosenName: p.wait_from_target }));
            for (const o of found) {
                const other = found.find(x => x.name === o.chosenName);
                o.wait_from_uid = other ? other.uid : null;
                delete o.chosenName;
            }
            return found;
        },

        /** What an outside prerequisite is called in conditions: the name given, or one made from what it is, numbered if it clashes. */
        outsideName(item, o) {
            if (o.name.trim()) return o.name.trim();
            const base = cleanName(o.kind === "OTHER_JOB" ? (o.job.trim() ? `${o.workflow.trim()}.${o.job.trim()}` : o.workflow)
                : o.kind === "ENDPOINT" ? o.endpoint : "") || (o.kind === "ENDPOINT" ? "Files" : o.kind === "TIME" ? "Time" : "Workflow");
            const taken = new Set([...this.itemNames(item.parent), "Now", ...item.outside.filter(x => x !== o && x.name.trim()).map(x => x.name.trim())]);
            for (const earlier of item.outside) {
                if (earlier === o) break;
                if (!earlier.name.trim()) taken.add(this.outsideName(item, earlier));
            }
            let name = base, number = 2;
            while (taken.has(name)) name = base + number++;
            return name;
        },

        outsidePayload(item) {
            const whole = value => (value === "" || value === null || value === undefined ? null : Number(value));
            return item.outside.map(o => {
                const name = this.outsideName(item, o);
                const chosen = o.wait_from === "CHOSEN" ? this.chosenName(item, o) : null;
                const common = { kind: o.kind, target: name, wait_mode: o.wait_mode,
                                 wait_minutes: o.wait_mode === "MINUTES" ? whole(o.wait_minutes) : null,
                                 wait_until: o.wait_mode === "UNTIL" ? (o.wait_until || "").trim() : null,
                                 wait_from: o.wait_from, wait_from_target: chosen, required: o.required };
                if (o.kind === "OTHER_JOB") {
                    return { ...common, workflow: o.workflow.trim(), job: o.job.trim() || null, test: item.join === "CUSTOM" ? "RULE" : o.test,
                             return_codes: o.test === "RC" ? (o.return_codes.trim() || null) : null,
                             look_back_hours: whole(o.look_back_hours), only_after_start: o.only_after_start };
                }
                if (o.kind === "ENDPOINT") {
                    return { ...common, endpoint: o.endpoint.trim(), file_pattern: o.file_pattern.trim() || null,
                             min_age_seconds: whole(o.min_age_seconds) };
                }
                return { ...common, time_condition: o.time_condition.trim() };
            });
        },

        /** The name of the prerequisite a wait counts from: one of the job's jobs, or another outside one. */
        chosenName(item, o) {
            const inside = item.prerequisites.find(p => p.uid === o.wait_from_uid);
            if (inside) return this.nameOf(inside.target);
            const outsideOne = item.outside.find(x => x.uid === o.wait_from_uid);
            return outsideOne ? this.outsideName(item, outsideOne) : null;
        },

        /** Every prerequisite of the job a wait can count from, other than the one asking: [{ uid, label }]. */
        waitChoices(item, o) {
            return [...(item.join === "CUSTOM" ? [] : item.prerequisites.map(p => ({ uid: p.uid, label: this.nameOf(p.target) }))),
                    ...item.outside.filter(x => x !== o).map(x => ({ uid: x.uid, label: this.outsideName(item, x) }))].filter(c => c.label);
        },

        waitCount(item) { return item.prerequisites.length + item.outside.length; },

        addOutside(item, kind) {
            const o = this.blankOutside(kind);
            item.outside.push(o);
            this.$nextTick(() => {
                const row = document.querySelector(`[data-outside-uid="${o.uid}"]`);
                if (row) row.querySelector("input, select").focus();
            });
        },

        removeOutside(item, index) {
            item.outside.splice(index, 1);
            this.fixChosen(item);
        },

        /** Moving to another kind clears what belonged to the old one. */
        outsideKindChanged(o) {
            Object.assign(o, { ...this.blankOutside(o.kind), uid: o.uid, kind: o.kind, name: o.name, wait_mode: o.wait_mode,
                               wait_minutes: o.wait_minutes, wait_until: o.wait_until, wait_from: o.wait_from,
                               wait_from_uid: o.wait_from_uid, required: o.required });
        },

        /** The jobs of another workflow, for the Job box; fetched once, when its workflow is named. */
        workflowJobs(key) {
            const detail = this.jobDetails[(key || "").trim()];
            return detail && detail.items ? detail.items.map(i => i.name) : [];
        },

        /** Names a job in the workflow shown cannot give an outside prerequisite, and the ones conditions can use: [{ name, kind }]. */
        outsideNames(item) { return item.outside.map(o => ({ name: this.outsideName(item, o), kind: o.kind })); },

        /** What an outside prerequisite is, in words, for the outline and the pane. */
        outsideWords(item, o) {
            const name = this.outsideName(item, o);
            if (o.kind === "OTHER_JOB") {
                const where = o.job.trim() ? `job ${o.job.trim()} in workflow ${o.workflow.trim()}` : `workflow ${o.workflow.trim()} as a whole`;
                const test = item.join === "CUSTOM" ? "has ended" : `${TESTS[o.test]}${o.test === "RC" ? " " + o.return_codes : ""}`;
                const limits = [o.look_back_hours !== "" ? `ended within ${o.look_back_hours} h` : "",
                                o.only_after_start ? "started after this run did" : ""].filter(Boolean);
                return `${name} (${where}) ${test}${limits.length ? ", only a run that " + limits.join(" and ") : ""}`;
            }
            if (o.kind === "ENDPOINT") {
                const age = o.min_age_seconds !== "" && Number(o.min_age_seconds) > 0 ? `, each unchanged for ${o.min_age_seconds} s` : "";
                return `${name} (files at ${o.endpoint.trim() || "an endpoint"}${o.file_pattern.trim() ? ", " + o.file_pattern.trim() : ""}) are there${age}`;
            }
            return `${name}: ${o.time_condition.trim() || "(no time condition yet)"}`;
        },

        /** How long it is patient, in words. */
        patienceWords(o) {
            const how = { DEFAULT: "up to the default wait (see Settings)", NONE: "with no limit",
                          MINUTES: `up to ${o.wait_minutes || "?"} minutes`, UNTIL: `until ${o.wait_until || "?"}` }[o.wait_mode];
            const from = o.wait_mode === "MINUTES" || o.wait_mode === "DEFAULT" ? `, counted from when ${WAIT_FROM[o.wait_from]}` : "";
            return `${o.required ? "Required" : "Optional"}; waits ${how}${from}`;
        },

        /** The calendar icon, not the clock, for a condition on the date or weekday. */
        isCalendar(o) { return /Now\.(Date|Weekday)/.test(o.time_condition); },

        timeContext() {
            return { kind: "workflow", names: [], outputs: this.conditionOutputs, outside: [], timeOnly: true,
                     outsideOutputs: this.outsideOutputs, workflowKey: null, runs: [] };
        },

        // ---------- The steps of a job used here, and where each ${Name} in them gets its value ----------

        async loadPrecedence() {
            try {
                const setting = (await AutoApp.get("/settings")).find(s => s.key === "VariablePrecedence");
                return setting ? setting.value : DEFAULT_PRECEDENCE;
            } catch (e) {
                return DEFAULT_PRECEDENCE;
            }
        },

        knownJob(item) { return item.embedded ? Boolean(item.id) : this.allJobs.some(j => j.job_key === item.job_key.trim()); },

        /** Fetches a job's steps once, when a use of it is on screen. A key that is not a job is left alone. */
        async loadJobDetail(key) {
            key = (key || "").trim();
            if (!key || key in this.jobDetails || !this.allJobs.some(j => j.job_key === key)) return;       // embedded ones arrive with the workflow
            this.jobDetails[key] = null;
            try {
                this.jobDetails[key] = await AutoApp.get("/jobs/" + encodeURIComponent(key));
            } catch (e) {
                /* no steps are shown for it */
            }
        },

        jobDetail(item) { return this.jobDetails[item.job_key.trim()] || null; },

        isWorkflowJob(item) { const d = this.jobDetail(item); return Boolean(d) && d.job_type === "WORKFLOW"; },

        /** The steps in the order the job runs them, each with the parameters that use a ${Name} and where it comes from. */
        stepRows(item) {
            const detail = this.jobDetail(item);
            if (!detail || detail.job_type === "WORKFLOW") return [];
            const rows = [];
            const walk = (steps, depth) => steps.forEach(step => {
                const uses = Object.entries(step.parameters || {})
                    .map(([param, text]) => ({ param, text: text || "", names: [...new Set([...(text || "").matchAll(SIMPLE_PLACEHOLDER)].map(m => m[1]))] }))
                    .filter(use => use.names.length)
                    .map(use => ({ ...use, sources: use.names.map(name => this.sourceOf(item, detail, name)) }));
                rows.push({ key: step.id, depth, number: step.number, title: step.title || step.step_type_name,
                            type: step.step_type_name, active: step.active, uses });
                walk(step.children || [], depth + 1);
            });
            walk(detail.steps || [], 0);
            return rows;
        },

        /** Where ${name} gets its value for this use, going by the Variable precedence setting and what is on screen now. */
        sourceOf(item, detail, name) {
            const shown = v => (v.secret ? "********" : (v.value ?? ""));
            const pick = (list, where) => {
                const v = (list || []).find(x => (x.name || "").trim() === name);
                return v ? { value: shown(v), where: typeof where === "function" ? where(v) : where } : null;
            };
            const levels = {
                USE: () => pick(item.variables, "this use"),
                JOB: () => pick(detail.variables, "the job's own variables"),
                WORKFLOW: () => pick(this.form.variables, "the workflow")
                    || pick(this.tagsView ? this.tagsView.variables : [], v => "the workflow's tag " + AutoApp.showPath(v.source)),
                TAG: () => pick(detail.inherited_variables, v => "the job's tag " + AutoApp.showPath(v.source)),
            };
            for (const level of [...this.precedence].reverse()) {
                const hit = levels[level] && levels[level]();
                if (hit) return { name, ...hit };
            }
            return { name, value: null, where: null };
        },

        // ---------- Variables: the workflow's own, and those set on a use of a job ----------

        variablesForm(list) {
            return (list || []).map(v => ({ uid: nextUid++, name: v.name, value: v.value ?? "", secret: v.secret,
                                            description: v.description || "",
                                            // A saved secret's value is never sent to the page. Left blank, it is kept.
                                            savedSecret: v.secret }));
        },

        variablesPayload(list) {
            return list.map(v => ({ name: v.name.trim(), value: v.secret && v.savedSecret && v.value === "" ? null : v.value,
                                    secret: v.secret, description: v.description.trim() || null }));
        },

        /** Adds a variable to the workflow (list = form.variables) or to a use (item.variables), and focuses it. */
        addVariable(list) {
            const variable = { uid: nextUid++, name: "", value: "", secret: false, description: "", savedSecret: false };
            list.push(variable);
            this.$nextTick(() => {
                const row = document.querySelector(`[data-variable="${variable.uid}"]`);
                if (row) row.querySelector(".variable-name").focus();
            });
        },

        removeVariable(list, index) { list.splice(index, 1); },

        nameOf(uid) {
            const item = this.form.items.find(i => i.uid === uid);
            return item ? (item.name.trim() || defaultName(item.job_key)) : "";
        },

        payload() {
            return {
                job_key: this.form.job_key.trim(),
                job_type: "WORKFLOW",
                description: this.form.description.trim() || null,
                active: this.form.active,
                items: this.levelPayload(null),
                variables: this.variablesPayload(this.form.variables),
                tags: [...this.form.tags],
                reactions: this.reactionsPayload(this.form.reactions),
                succeeds_when: this.form.succeeds_choice === "RULE" ? (this.form.succeeds_when.trim() || null) : null,
                return_code_from: this.form.return_code_from || null,
            };
        },

        /** The items of one level, in the order shown, each with what is embedded in it. */
        levelPayload(parent) {
            return this.form.items.filter(item => item.parent === parent).map(item => ({
                ...(item.id ? { id: item.id } : {}),
                name: item.name.trim() || null,
                ...(item.embedded ? { embedded: this.embeddedPayload(item) } : { job_key: item.job_key.trim() }),
                join: item.join,
                rule: item.join === "CUSTOM" ? item.rule.trim() : null,
                prerequisites: [...(item.join === "CUSTOM" ? [] : item.prerequisites.map(p => ({
                    target: this.nameOf(p.target), test: p.test,
                    return_codes: p.test === "RC" ? (p.return_codes.trim() || null) : null }))), ...this.outsidePayload(item)],
                on_unmet: item.on_unmet,
                disabled_here: item.disabled_here || null,
                reactions_overridden: item.reactions_overridden,
                reactions: item.reactions_overridden ? this.reactionsPayload(item.reactions) : [],
                variables: this.variablesPayload(item.variables),
            }));
        },

        /**
         * What the server needs to make or change the job or workflow embedded in an item. A workflow embedded here is
         * saved with this one (one Save), its items included. A job of steps already saved is left out, so it stays as
         * it is: its steps are edited on its own page.
         */
        embeddedPayload(item) {
            const inner = item.inner;
            if (inner.job_type === "STEPS") {
                return item.id ? undefined : { job_type: "STEPS", description: inner.description.trim() || null, active: inner.active };
            }
            return { job_type: "WORKFLOW", description: inner.description.trim() || null, active: inner.active,
                     items: this.levelPayload(item.uid), variables: this.variablesPayload(inner.variables),
                     succeeds_when: inner.succeeds_when || null, return_code_from: inner.return_code_from || null };
        },

        get changed() { return Boolean(this.form) && this.editing && JSON.stringify(this.payload()) !== this.saved; },

        /** Dragging the pane's left edge: its width follows the pointer, kept between its least and what leaves the diagram room. */
        startResize(event) {
            const body = this.$refs.body, handle = event.currentTarget;
            handle.setPointerCapture(event.pointerId);
            handle.classList.add("dragging");
            const move = e => {
                const box = body.getBoundingClientRect();
                this.sideWidth = Math.round(Math.max(SIDE_MIN, Math.min(box.right - e.clientX, box.width - DIAGRAM_MIN)));
            };
            const end = () => {
                handle.removeEventListener("pointermove", move);
                handle.classList.remove("dragging");
                remember(SIDE_KEY, String(this.sideWidth));
            };
            handle.addEventListener("pointermove", move);
            handle.addEventListener("pointerup", end, { once: true });
        },

        resetSideWidth() {
            this.sideWidth = 0;
            remember(SIDE_KEY, "");
        },

        /** Whether the panel beside the diagram is open: only while a job is selected. */
        get sideShown() { return Boolean(this.form) && this.form.items.some(i => i.uid === this.selectedUid); },

        /**
         * A job as it is now, to compare with how it was saved: what waits for what by the jobs' identity, not
         * their names, so renaming a job marks it alone, not the jobs that wait for it.
         */
        itemKey(item) {
            const idOf = uid => { const other = this.form.items.find(i => i.uid === uid); return other && other.id ? other.id : "new" + uid; };
            return JSON.stringify({ name: this.nameOf(item.uid), job: item.job_key.trim(), join: item.join,
                rule: item.join === "CUSTOM" ? item.rule.trim() : null, here: item.disabled_here || null,
                own: item.reactions_overridden, reactions: item.reactions_overridden ? this.reactionsPayload(item.reactions) : [],
                variables: this.variablesPayload(item.variables), unmet: item.on_unmet, outside: this.outsidePayload(item),
                after: item.join === "CUSTOM" ? [] : item.prerequisites.map(p => [idOf(p.target), p.test, p.test === "RC" ? p.return_codes.trim() : null]) });
        },

        /** While editing: whether the job differs from how it was last saved (a new job always does). */
        itemChanged(item) {
            if (!this.editing) return false;
            return !item.id || this.savedKeys[item.id] !== this.itemKey(item);
        },
        get problems() { return this.check ? this.check.problems : []; },
        get warnings() { return this.check ? this.check.warnings || [] : []; },

        // ---------- Choosing and editing ----------

        choose() {
            if (this.chosen && this.chosen !== this.key) location.href = "workflow.html?" + new URLSearchParams({ key: this.chosen });
        },

        edit() { this.editing = true; this.notice = ""; },

        cancel() {
            if (this.isNew) { location.href = "jobs.html"; return; }
            this.show(this.job);
            this.editing = false;
            this.error = "";
        },

        /**
         * Adds an item at the top, or inside the frame parent (its uid). mode: "existing" (a job or workflow of its own, chosen
         * by key), "job" (a new job embedded here) or "workflow" (a new workflow embedded here, drawn as a frame).
         */
        addItem(parent = null, mode = "existing") {
            const uid = nextUid++;
            const embedded = mode !== "existing";
            this.form.items.push({ uid, id: null, parent, name: "", job_key: "", join: "ALL", prerequisites: [], outside: [], on_unmet: "NOT_RUN",
                                   needed_by: [], rule: "", joinBefore: "ALL", disabled_here: "",
                                   reactions_overridden: false, reactions: [], job_reactions: [], variables: [],
                                   embedded, jobType: mode === "workflow" ? "WORKFLOW" : "STEPS",
                                   inner: embedded ? { job_type: mode === "workflow" ? "WORKFLOW" : "STEPS", description: "", active: true,
                                                       variables: [], succeeds_when: null, return_code_from: null } : null });
            if (embedded) this.form.items[this.form.items.length - 1].name = this.freeName(parent, mode === "workflow" ? "Workflow" : "Job");
            if (this.view === "diagram") this.select("item", uid);
            return uid;
        },

        /** A name not yet used at that level: Job, Job2, Job3... */
        freeName(parent, base) {
            const taken = new Set(this.form.items.filter(i => i.parent === parent).map(i => this.nameOf(i.uid)));
            let name = base, number = 2;
            while (taken.has(name)) name = base + number++;
            return name;
        },

        /** Takes an item out, and everything inside it if it is a frame. */
        removeItem(item) {
            const gone = new Set([item.uid]);
            for (let more = true; more;) {                      // the frame's items, and theirs in turn
                more = false;
                for (const other of this.form.items) if (!gone.has(other.uid) && gone.has(other.parent)) { gone.add(other.uid); more = true; }
            }
            const goneName = this.nameOf(item.uid);
            this.form.items = this.form.items.filter(other => !gone.has(other.uid));
            if (gone.has(this.selectedUid)) this.select(null, null);
            if (item.parent === null && this.form.return_code_from === goneName) this.form.return_code_from = "";
            for (const other of this.form.items) {
                other.prerequisites = other.prerequisites.filter(p => !gone.has(p.target));
                this.fixChosen(other);
            }
        },

        /** A wait that counts from a prerequisite that is gone counts from the others again. */
        fixChosen(item) {
            for (const o of item.outside) {
                const there = item.prerequisites.some(p => p.uid === o.wait_from_uid) || item.outside.some(x => x !== o && x.uid === o.wait_from_uid);
                if (o.wait_from === "CHOSEN" && !there) { o.wait_from = "OTHERS"; o.wait_from_uid = null; }
            }
        },

        /** Moves an item up or down among the items at its level. */
        moveItem(item, step) {
            const level = this.form.items.filter(other => other.parent === item.parent);
            const target = level[level.indexOf(item) + step];
            if (!target) return;
            const items = this.form.items;
            const from = items.indexOf(item), to = items.indexOf(target);
            items[from] = target;
            items[to] = item;
        },

        isFirst(item) { return this.form.items.find(other => other.parent === item.parent) === item; },
        isLast(item) { return [...this.form.items].reverse().find(other => other.parent === item.parent) === item; },

        addPrerequisite(item) {
            const other = this.form.items.find(i => i.uid !== item.uid);
            item.prerequisites.push({ uid: nextUid++, target: other ? other.uid : null, test: "SUCCESS", return_codes: "" });
        },

        removePrerequisite(item, index) {
            const [gone] = item.prerequisites.splice(index, 1);
            if (this.selectedLine === gone.uid) this.selectedLine = null;
            this.fixChosen(item);
        },

        /** A line on the diagram, removed: the prerequisite it draws. Says whether there was one. */
        removeLine(uid) {
            if (!this.editing) return false;
            const item = this.form.items.find(i => i.prerequisites.some(p => p.uid === Number(uid)));
            if (!item) return false;
            this.removePrerequisite(item, item.prerequisites.findIndex(p => p.uid === Number(uid)));
            return true;
        },

        /** Delete or Backspace while a line is selected on the diagram removes it, unless typing in a box. */
        removeSelectedLine(event) {
            if (!["Delete", "Backspace"].includes(event.key) || this.view !== "diagram" || !this.selectedLine) return;
            if (event.target.closest("input, select, textarea")) return;
            if (this.removeLine(this.selectedLine)) event.preventDefault();
        },

        others(item) { return this.form.items.filter(i => i.uid !== item.uid && i.parent === item.parent); },

        // ---------- Custom rules and completion rules ----------

        /** The names at one level (the top by default). */
        itemNames(parent = null) { return this.form.items.filter(i => i.parent === parent).map(i => this.nameOf(i.uid)).filter(Boolean); },

        /** The paths of the items inside the frames among some items, as a condition names them: Transform.Enrich, Transform.Stage.Load. */
        pathsBelow(items, prefix = "") {
            return items.flatMap(item => {
                if (!item.embedded || item.jobType !== "WORKFLOW") return [];
                const inside = this.form.items.filter(i => i.parent === item.uid);
                const here = prefix + this.nameOf(item.uid) + ".";
                return [...inside.map(i => here + this.nameOf(i.uid)), ...this.pathsBelow(inside, here)];
            });
        },

        depthOf(item) {
            let depth = 0;
            for (let up = item; up.parent !== null; depth++) up = this.form.items.find(i => i.uid === up.parent);
            return depth;
        },

        /** The items in the order the outline shows them: each frame, then what is inside it. */
        get outlineItems() {
            const walk = parent => this.form.items.filter(i => i.parent === parent).flatMap(i => [i, ...walk(i.uid)]);
            return this.form ? walk(null) : [];
        },


        /** A job switched to Custom rule starts from what it waited for; switched back, it waits for what its rule named. */
        joinChanged(item) {
            if (item.join === "CUSTOM" && !item.rule.trim()) {
                const outside = item.outside.map(o => ({ kind: o.kind, target: this.outsideName(item, o), test: o.test,
                                                         return_codes: o.return_codes, condition: o.time_condition.trim() }));
                item.rule = AutoApp.ruleFrom([...item.prerequisites.map(p => ({ ...p, target: this.nameOf(p.target) })), ...outside],
                                             item.joinBefore);
            } else if (item.join !== "CUSTOM" && item.joinBefore === "CUSTOM") {
                item.prerequisites = AutoApp.namedJobs(item.rule, this.outsideNames(item).map(o => o.name)).map(name => this.others(item).find(i => this.nameOf(i.uid) === name))
                    .filter(other => other)
                    .map(other => ({ uid: nextUid++, target: other.uid, test: "SUCCESS", return_codes: "" }));
            }
            item.joinBefore = item.join;
        },

        /** A job's name changed: the rules that named it follow. */
        renamed(before, after, changed = null) {
            if (!before || before === after) return;
            const parent = changed ? changed.parent : null;
            for (const item of this.form.items.filter(i => i.parent === parent)) item.rule = AutoApp.renameIn(item.rule, before, after);
            if (parent !== null) return;
            this.form.succeeds_when = AutoApp.renameIn(this.form.succeeds_when, before, after);
            if (this.form.return_code_from === before) this.form.return_code_from = after;
        },

        /** An outside prerequisite's name changed: the job's rule follows. */
        renamedOutside(item, before, after) {
            if (before && before !== after) item.rule = AutoApp.renameIn(item.rule, before, after);
        },

        /** The workflow's runs Explain can use, newest first. */
        explainRuns() {
            return this.runs.slice(0, 15).map(r => ({ run_id: r.run_id, label: `${this.time(r.started)} · ${r.status}` }));
        },

        ruleContext(item) {
            const siblings = this.others(item);
            return { kind: "workflow", names: [...siblings.map(i => this.nameOf(i.uid)), ...this.pathsBelow(siblings)], outputs: this.conditionOutputs,
                     outside: this.outsideNames(item), outsideOutputs: this.outsideOutputs,
                     workflowKey: this.job ? this.job.job_key : null, runs: this.explainRuns() };
        },

        completionContext() {
            return { kind: "workflow", names: [...this.itemNames(), ...this.pathsBelow(this.form.items.filter(i => i.parent === null))],
                     outputs: this.conditionOutputs, outside: [],
                     outsideOutputs: this.outsideOutputs, workflowKey: this.job ? this.job.job_key : null, runs: this.explainRuns() };
        },

        // ---------- Disable here, and a use's Reactions ----------

        disabledHereWords(item) {
            return { STOP: "Disabled here: stops", PASS_THROUGH: "Disabled here: passes through" }[item.disabled_here] || "";
        },

        /** Override here: starts from a copy of the job's, to change. */
        overrideReactions(item) {
            item.reactions = this.reactionsForm(this.reactionsPayload(item.job_reactions));
            item.reactions_overridden = true;
        },

        useJobReactions(item) {
            item.reactions = [];
            item.reactions_overridden = false;
        },

        reactionsShown(item) { return item.reactions_overridden ? item.reactions : item.job_reactions; },

        /** The jobs Rerun from... and Skip... can name: for Rerun from, those it waits for, directly or not; for Skip, any other. */
        reactionTargets(item) { return this.others(item).map(i => this.nameOf(i.uid)).filter(Boolean); },

        /** Rerun from... Reactions, for the diagram's ↺ arcs: from each job back to the job it reruns from. */
        reruns(items, idOf) {
            return items.flatMap(item => (item.reactions_overridden ? item.reactions : []).flatMap(r =>
                r.actions.filter(a => a.action === "RERUN_FROM" && a.target).map(a => ({
                    from: idOf(item), to: idOf(this.others(item).find(i => this.nameOf(i.uid) === a.target) || null),
                    words: `${this.nameOf(item.uid)}: ${this.reactionWords(r)}` }))))
                .filter(r => r.to);
        },

        placeholder(item) { return defaultName(item.job_key) || "Made from the job key"; },

        /** What an item waits for, in words, for the locked outline. */
        needs(item) {
            if (item.join === "CUSTOM") return "Starts when its Custom rule holds: " + item.rule;
            if (!this.waitCount(item)) return "Starts when the workflow starts";
            const parts = [...item.prerequisites.map(p =>
                `${this.nameOf(p.target)} ${TESTS[p.test]}${p.test === "RC" ? " " + p.return_codes : ""}`),
                ...item.outside.map(o => this.outsideWords(item, o))];
            return "After " + parts.join(item.join === "ANY" ? ", or " : ", and ");
        },

        jobLink(item) {
            if (item.embedded) return "job.html?" + new URLSearchParams({ key: item.job_key });
            const job = this.allJobs.find(j => j.job_key === item.job_key);
            const page = job && job.job_type === "WORKFLOW" ? "workflow.html" : "job.html";
            const params = { key: item.job_key };
            // A job opened from a saved use is checked as this workflow runs it
            const saved = page === "job.html" && this.job && this.job.items.find(i => i.id === item.id);
            if (saved) Object.assign(params, { workflow: this.job.job_key, use: saved.name });
            return page + "?" + new URLSearchParams(params);
        },

        async submit() {
            const payload = this.payload();
            if (!AutoApp.confirmDisable(this.job, payload)) return;
            const rename = await AutoApp.askRename(this.job, payload.job_key);
            if (!rename) return;
            payload.move_working_folder = rename.move;
            this.busy = true;
            this.error = "";
            this.notice = "";
            try {
                const result = this.job
                    ? await AutoApp.send("PUT", "/jobs/" + encodeURIComponent(this.job.job_key), payload)
                    : await AutoApp.send("POST", "/jobs", payload);
                this.job = result.job;
                this.check = { valid: result.valid, problems: result.problems, warnings: [] };
                this.show(result.job);
                this.editing = false;
                this.notice = result.changes.length ? "Saved. " + result.changes.join(" ") : "Saved. Nothing had changed.";
                if (this.key !== result.job.job_key || this.isNew) {
                    history.replaceState(null, "", "workflow.html?" + new URLSearchParams({ key: result.job.job_key }));
                    this.key = result.job.job_key;
                    this.isNew = false;
                }
                this.allJobs = await AutoApp.get("/jobs");
                this.check = await AutoApp.get("/jobs/" + encodeURIComponent(result.job.job_key) + "/check");
                await this.loadRuns();
            } catch (e) {
                this.error = e.message;
            }
            this.busy = false;
        },

        async remove() {
            if (!confirm(`Delete workflow '${this.job.job_key}'? The jobs it runs are not deleted.`)) return;
            this.busy = true;
            try {
                await AutoApp.send("DELETE", "/jobs/" + encodeURIComponent(this.job.job_key));
                location.href = "jobs.html";
            } catch (e) {
                this.error = e.message;
                this.busy = false;
            }
        },

        // ---------- Embedded and shared, both ways ----------

        /** Frees an embedded job from this workflow, under a key of its own (its present key keeps it as it is). */
        async makeShared(item) {
            if (this.changed) { this.error = "Save or cancel your changes first, then make it shared."; return; }
            const key = prompt(`Make '${item.job_key}' a job of its own, listed for other workflows to use.\n\n` +
                "Its key as a shared job (the present key keeps it as it is, with its working folder):", item.job_key);
            if (key === null || !key.trim()) return;
            let move = false;
            try {
                if (key.trim() !== item.job_key) {
                    const facts = await AutoApp.get("/jobs/" + encodeURIComponent(item.job_key) + "/rename-facts");
                    move = facts.can_move_folder && confirm(`Its working folder ${facts.working_folder} is named after the old key.\n\n` +
                        "OK moves it to the new key's name; Cancel leaves it where it is.");
                }
                await AutoApp.send("POST", "/jobs/" + encodeURIComponent(item.job_key) + "/make-shared",
                                   { job_key: key.trim(), move_working_folder: move });
                await this.load();
                this.notice = `'${key.trim()}' is now a job of its own. This workflow still uses it.`;
            } catch (e) {
                this.error = e.message;
            }
        },

        /** Makes an item run a copy of the shared job it runs, that belongs to this workflow. */
        async embedCopy(item) {
            if (this.changed) { this.error = "Save or cancel your changes first, then make the copy."; return; }
            if (!confirm(`Run a copy of '${item.job_key}' that belongs to this workflow?\n\nIt can then differ here. ` +
                         "Later changes to the original do not reach the copy, and the copy does not change the original.")) return;
            try {
                await AutoApp.send("POST", "/jobs/" + encodeURIComponent(this.job.job_key) + "/items/" + encodeURIComponent(item.name) + "/embedded-copy");
                await this.load();
                this.notice = `'${item.name}' now runs an embedded copy.`;
            } catch (e) {
                this.error = e.message;
            }
        },

        // ---------- The diagram ----------

        setView(view) {
            this.view = view;
            remember(VIEW_KEY, view);
        },

        rememberExternal() {
            remember(EXTERNAL_KEY, this.showExternal ? "shown" : "hidden");
            remember(CONDITIONS_KEY, this.showConditions ? "shown" : "hidden");
        },

        setDirection(direction) {
            this.direction = direction;
            remember(DIRECTION_KEY, direction);
        },

        /** step: 1 larger, -1 smaller, 0 fit to the window. */
        setZoom(step) {
            const now = this.zoom === "fit" ? 1 : this.zoom;
            if (step === 0) this.zoom = "fit";
            else this.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, step > 0 ? now * ZOOM_STEP : now / ZOOM_STEP));
        },

        /** What the diagram is told when a box or line is clicked: kind "item", "line", or null for neither. */
        select(kind, id) {
            this.selectedLine = null;
            if (kind === "line" && /^(rule|out|by):/.test(String(id))) {      // a line a rule or an outside box draws: its job is selected
                this.selectedUid = Number(String(id).split(":")[1]);
            } else if (kind === "item") {
                this.selectedUid = Number(id);
            } else if (kind === "line") {
                const owner = this.form.items.find(i => i.prerequisites.some(p => p.uid === Number(id)));
                this.selectedUid = owner ? owner.uid : null;
                this.selectedLine = owner ? Number(id) : null;
            } else {
                this.selectedUid = null;
            }
        },

        /** Dragging from one box to another: the second waits for the first to succeed. */
        connect(fromId, toId) {
            if (!this.editing) return;
            const from = Number(fromId), to = this.form.items.find(i => i.uid === Number(toId));
            if (!to) return;
            const source = this.form.items.find(i => i.uid === from);
            if (source && source.parent !== to.parent) return this.connectAcross(source, to);
            if (to.join === "CUSTOM") {             // its rule says what it waits for: the new job joins it
                const name = this.nameOf(from);
                if (name && !AutoApp.namedJobs(to.rule, this.outsideNames(to).map(o => o.name)).includes(name)) {
                    to.rule = to.rule.trim() ? `(${to.rule.trim()}) AND %{${name}.Succeeded}` : `%{${name}.Succeeded}`;
                }
                this.select("item", to.uid);
                return;
            }
            let prerequisite = to.prerequisites.find(p => p.target === from);
            if (!prerequisite) {
                prerequisite = { uid: nextUid++, target: from, test: "SUCCESS", return_codes: "" };
                to.prerequisites.push(prerequisite);
            }
            this.select("line", prerequisite.uid);
        },

        /** Joining boxes in different frames: the second waits for the first as for a job in another workflow (both must be saved). */
        connectAcross(from, to) {
            const key = this.workflowKeyOf(from.parent);
            if (!key || !from.id) {
                this.error = "Save the workflow first: a job in another frame is waited for by the workflow's key and its name there.";
                return;
            }
            const o = this.blankOutside("OTHER_JOB");
            Object.assign(o, { workflow: key, job: this.nameOf(from.uid) });
            if (to.outside.some(x => x.workflow === o.workflow && x.job === o.job)) return this.select("item", to.uid);
            to.outside.push(o);
            this.select("item", to.uid);
        },

        /** The key of the workflow whose items are at a level: the saved workflow itself, or the frame (its embedded key). */
        workflowKeyOf(parent) {
            if (parent === null) return this.job ? this.job.job_key : null;
            const frame = this.form.items.find(i => i.uid === parent);
            return frame && frame.id ? frame.job_key : null;
        },

        /** The box an outside prerequisite names when it names a job in this same tree, or null: it is drawn as a line to it. */
        treeTarget(o) {
            if (o.kind !== "OTHER_JOB" || !o.workflow.trim()) return null;
            const key = o.workflow.trim(), job = o.job.trim();
            if (!job) return this.form.items.find(i => i.embedded && i.job_key === key) || null;
            return this.form.items.find(i => i.name === job && this.workflowKeyOf(i.parent) === key) || null;
        },

        isShown(item) { return this.view === "outline" || item.uid === this.selectedUid; },

        get found() {
            const text = this.find.trim().toLowerCase();
            return text && this.form ? this.form.items.filter(i => this.nameOf(i.uid).toLowerCase().includes(text)) : [];
        },

        /**
         * Everything the Find box matches, to any depth: the jobs of this workflow and of the frames in it, and of the
         * workflows of their own it uses, as { label (the path, as "Transform / Enrich"), uid (an item here), id (a box
         * inside a workflow of its own), open (the frames and workflows to open to see it) }.
         */
        get foundAll() {
            const text = this.find.trim().toLowerCase();
            if (!text || !this.form) return [];
            const matches = [];
            for (const item of this.outlineItems) {
                const chain = this.chainOf(item);
                if (this.nameOf(item.uid).toLowerCase().includes(text))
                    matches.push({ label: chain.map(i => this.nameOf(i.uid)).join(" / "), uid: item.uid, id: String(item.uid),
                                   frames: chain.slice(0, -1).map(i => i.uid), shared: [] });
                if (!item.embedded && this.jobKind(item.job_key) === "WORKFLOW" && this.jobDetails[item.job_key.trim()]) {
                    this.matchesInShared(this.jobDetails[item.job_key.trim()], text, chain.map(i => this.nameOf(i.uid)),
                                         `sh:${item.uid}`, [String(item.uid)], matches, new Set([item.job_key.trim()]));
                }
            }
            return matches;
        },

        matchesInShared(detail, text, path, prefix, shared, matches, seen) {
            for (const inner of detail.items || []) {
                const id = `${prefix}/${inner.name}`, here = [...path, inner.name];
                if (inner.name.toLowerCase().includes(text)) matches.push({ label: here.join(" / "), uid: null, id, frames: [], shared });
                const down = inner.embedded ? inner.contents : (inner.job_type === "WORKFLOW" ? this.jobDetails[inner.job_key] : null);
                if (down && (inner.embedded || !seen.has(inner.job_key))) {
                    this.matchesInShared(down, text, here, id, inner.embedded ? shared : [...shared, id], matches,
                                         inner.embedded ? seen : new Set([...seen, inner.job_key]));
                }
            }
        },

        /** An item and the frames it is in, outermost first. */
        chainOf(item) {
            const chain = [];
            for (let at = item; at; at = at.parent === null ? null : this.form.items.find(i => i.uid === at.parent)) chain.unshift(at);
            return chain;
        },

        /** Loads the workflows of their own that Find has to look inside, however deep they nest. */
        async loadFindDetails(text) {
            if (!text.trim() || !this.form) return;
            const queue = this.form.items.filter(i => !i.embedded && this.jobKind(i.job_key) === "WORKFLOW").map(i => i.job_key.trim());
            const seen = new Set();
            while (queue.length && seen.size < 100) {
                const key = queue.shift();
                if (seen.has(key)) continue;
                seen.add(key);
                await this.loadJobDetail(key);
                const walk = detail => (detail && detail.items || []).forEach(i => {
                    if (i.embedded && i.contents) walk(i.contents);
                    else if (i.job_type === "WORKFLOW") queue.push(i.job_key);
                });
                walk(this.jobDetails[key]);
            }
        },

        /** Show matches: opens the frames and workflows on the way to a match, and puts it in view. */
        showFound(entry) {
            this.folded = { ...this.folded, ...Object.fromEntries(entry.frames.map(uid => [uid, false])) };
            this.opened = { ...this.opened, ...Object.fromEntries(entry.shared.map(id => [id, true])) };
            if (entry.uid) this.select("item", entry.uid);
            this.$nextTick(() => setTimeout(() => {
                const box = document.querySelector(`#diagram .wf-box[data-id="${CSS.escape(entry.id)}"]`);
                if (box) box.scrollIntoView({ block: "nearest", inline: "center" });
            }, 150));
        },

        jobDisabledWords(jobKey) {
            const job = this.allJobs.find(j => j.job_key === jobKey);
            return job && !job.active ? `Its job ${jobKey} is disabled` : null;
        },

        jobKind(jobKey) {
            const job = this.allJobs.find(j => j.job_key === jobKey);
            return job ? job.job_type : "STEPS";
        },

        /** What a frame says when folded or in the key: in a run, "2 running, 1 failed"; in the editor, how many jobs it holds. */
        frameWords(item) {
            const inside = this.form.items.filter(i => i.parent === item.uid);
            const found = this.matchesBelow(item);
            return (inside.length === 1 ? "1 job" : inside.length + " jobs") + (found ? ` · ${found}` : "");
        },

        /** "2 matches inside": how many items inside a frame the Find box matches, as words; empty for none or no Find. */
        matchesBelow(frame) {
            const text = this.find.trim().toLowerCase();
            if (!text) return "";
            let count = 0;
            const walk = parent => this.form.items.filter(i => i.parent === parent).forEach(i => {
                if (this.nameOf(i.uid).toLowerCase().includes(text)) count++;
                walk(i.uid);
            });
            walk(frame.uid);
            return count ? `${count} match${count === 1 ? "" : "es"} inside` : "";
        },

        /** The same for what is inside a workflow of its own (read only, never folded away from Find). */
        matchesInside(detail, key) {
            const text = this.find.trim().toLowerCase();
            if (!text) return "";
            let count = 0;
            const seen = new Set([key]);
            const walk = d => (d.items || []).forEach(i => {
                if (i.name.toLowerCase().includes(text)) count++;
                const down = i.embedded ? i.contents : (i.job_type === "WORKFLOW" ? this.jobDetails[i.job_key] : null);
                if (down && (i.embedded || !seen.has(i.job_key))) { seen.add(i.job_key); walk(down); }
            });
            walk(detail);
            return count ? `${count} match${count === 1 ? "" : "es"} inside` : "";
        },

        /** Jobs of any workflow that is itself used as a job, as the diagram's boxes: those inside it, read only, when it is opened. */
        addShared(items, lines) {
            for (const used of this.form.items) {
                if (used.embedded || this.jobKind(used.job_key) !== "WORKFLOW") continue;
                const key = used.job_key.trim(), box = items.find(i => i.id === String(used.uid));
                const detail = this.jobDetails[key];
                if (!box || !detail) continue;
                const open = Boolean(this.opened[used.uid]);
                const inside = this.matchesInside(detail, key);
                Object.assign(box, { frame: true, folded: !open, shared: true,
                                     sub: `workflow ${key}, ${(detail.items || []).length} jobs` + (inside ? ` · ${inside}` : "") });
                if (open) this.addSharedLevel(detail, String(used.uid), `sh:${used.uid}`, key, items, lines);
            }
        },

        addSharedLevel(detail, parentId, prefix, workflowKey, items, lines) {
            const href = "workflow.html?" + new URLSearchParams({ key: workflowKey });
            for (const inner of detail.items || []) {
                const id = `${prefix}/${inner.name}`;
                const down = inner.embedded ? inner.contents : (inner.job_type === "WORKFLOW" ? this.jobDetails[inner.job_key] : null);
                const isWorkflow = inner.job_type === "WORKFLOW";
                const open = Boolean(down) && (inner.embedded || Boolean(this.opened[id]));
                sharedKeys[id] = inner.job_key;
                items.push({ id, name: inner.name, join: inner.join, status: null, readonly: true, shared: true, href,
                             sub: isWorkflow ? `${inner.embedded ? "embedded workflow" : "workflow " + inner.job_key}`
                                  + (down ? `, ${(down.items || []).length} jobs` : "") + (down ? ` · ${this.matchesInside(down, inner.job_key)}` : "").replace(/ · $/, "")
                                  : inner.embedded ? "embedded job" : "job " + inner.job_key,
                             kind: isWorkflow ? "FRAME" : "JOB", disabled: null, disabledHere: inner.disabled_here || null, reactions: null,
                             rule: inner.join === "CUSTOM" ? inner.rule : null, changed: false, parent: parentId,
                             frame: isWorkflow && Boolean(down), folded: !open });
                if (open) this.addSharedLevel(down, id, id, workflowKey, items, lines);
                (inner.prerequisites || []).filter(p => p.kind === "JOB").forEach((p, n) => lines.push({
                    id: `${id}>${n}`, from: `${prefix}/${p.target}`, to: id, test: p.test, codes: p.return_codes || "" }));
            }
        },

        /** The workflow on screen, in the diagram's terms. */
        definitionDiagram() {
            const idOf = item => String(item.uid);
            const items = this.form.items.map(item => {
                const frame = item.embedded && item.jobType === "WORKFLOW";
                return { id: idOf(item), name: this.nameOf(item.uid), join: item.join, status: null,
                         sub: frame ? "embedded workflow, " + this.frameWords(item)
                              : item.embedded ? "embedded job" : item.job_key ? "job " + item.job_key : "no job chosen yet",
                         kind: frame ? "FRAME" : item.embedded ? "JOB" : this.jobKind(item.job_key),
                         disabled: item.embedded ? null : this.jobDisabledWords(item.job_key),
                         disabledHere: item.disabled_here || null, reactions: this.reactionsTip(item),
                         rule: item.join === "CUSTOM" ? item.rule : null, changed: this.itemChanged(item),
                         parent: item.parent === null ? null : String(item.parent), frame, folded: Boolean(this.folded[item.uid]) };
            });
            const lines = this.form.items.flatMap(item => item.join === "CUSTOM"
                ? AutoApp.namedJobs(item.rule, this.outsideNames(item).map(o => o.name))
                    .map(name => this.others(item).find(other => this.nameOf(other.uid) === name)).filter(Boolean).map(other => ({
                        id: `rule:${item.uid}:${this.nameOf(other.uid)}`, from: idOf(other), to: idOf(item), test: "RULE", codes: "" }))
                : item.prerequisites.filter(p => p.target).map(p => ({
                    id: String(p.uid), from: String(p.target), to: String(item.uid), test: p.test, codes: p.return_codes.trim() })));
            this.addShared(items, lines);
            const selected = this.selectedLine ? { kind: "line", id: String(this.selectedLine) }
                : this.selectedUid ? { kind: "item", id: String(this.selectedUid) } : null;
            const edge = this.outsideBoxes(this.form.items, idOf, item => this.nameOf(item.uid), idOf);
            return { ...this.withExternal(items, lines, edge), selected,
                     reruns: this.reruns(this.form.items, item => item && idOf(item)) };
        },

        /**
         * The dashed boxes at the edges of the diagram, and their lines: what each job waits for outside the workflow, on its
         * way in, and the jobs elsewhere that wait for it (Needed by), on its way out. idOf gives a job's id on the diagram;
         * seen(item, o), in a run, how the outside thing stands: [status, words].
         */
        outsideBoxes(items, idOf, nameOf, ownerOf, seen = null) {
            const boxes = [], lines = [], marks = new Map();
            const mark = (owner, cat, icon, words) => marks.set(owner, [...(marks.get(owner) || []), { cat, icon, words }]);
            const page = key => "workflow.html?" + new URLSearchParams({ key });
            for (const item of items) {
                const owner = idOf(item), who = nameOf(item);
                item.outside.forEach(o => {
                    const inTree = this.treeTarget(o);
                    if (inTree) {                                   // a job elsewhere in this same tree: a line to its box
                        lines.push({ id: `tree:${owner}:${o.uid}`, cat: "tree", from: idOf(inTree), to: owner, codes: o.return_codes,
                                     test: item.join === "CUSTOM" ? "RULE" : o.test,
                                     words: `${who} waits for ${this.outsideWords(item, o)}` });
                        return;
                    }
                    const id = `out:${owner}:${o.uid}`, kind = { OTHER_JOB: "JOB", ENDPOINT: "FILES", TIME: "TIME" }[o.kind];
                    const cat = o.kind === "OTHER_JOB" ? "external" : "conditions";
                    const [status, words] = seen ? seen(item, o) : [null, null];
                    boxes.push({ id, cat, name: this.outsideName(item, o), join: "ALL", status, statusText: words, kind: "JOB", disabled: null,
                                 disabledHere: null, reactions: null, rule: null, changed: false, outside: kind,
                                 calendar: o.kind === "TIME" && this.isCalendar(o), owner: ownerOf(item),
                                 href: o.kind === "OTHER_JOB" && o.workflow.trim() ? page(o.workflow.trim()) : null,
                                 sub: o.kind === "OTHER_JOB" ? "in workflow " + (o.workflow.trim() || "(not chosen yet)")
                                      : o.kind === "ENDPOINT" ? "files at " + (o.endpoint.trim() || "(no endpoint yet)") : o.time_condition.trim() });
                    mark(owner, cat, o.kind === "OTHER_JOB" ? "workflow" : o.kind === "ENDPOINT" ? "files" : (this.isCalendar(o) ? "calendar" : "clock"),
                         `Waits for ${this.outsideWords(item, o)}` + (words ? `. ${words}` : ""));
                    lines.push({ id: id + ">", cat, from: id, to: owner, codes: o.return_codes,
                                 test: kind === "JOB" ? (item.join === "CUSTOM" ? "RULE" : o.test) : kind,
                                 words: `${who} waits for ${this.outsideWords(item, o)}` });
                });
                (item.needed_by || []).forEach((by, n) => {
                    const id = `by:${owner}:${n}`;
                    boxes.push({ id, cat: "external", name: by.job, join: "ALL", status: null, kind: "JOB", disabled: null, disabledHere: null, reactions: null,
                                 rule: null, changed: false, outside: "NEEDED", owner: null, href: page(by.workflow),
                                 sub: "in workflow " + by.workflow });
                    mark(owner, "external", "needed", `Needed by ${by.job} in workflow ${by.workflow}`);
                    lines.push({ id: id + ">", cat: "external", from: owner, to: id, test: "NEEDED", codes: "",
                                 words: `${by.job} in workflow ${by.workflow} waits for ${who}. Click its box to open that workflow` });
                });
            }
            return { items: boxes, lines, marks };
        },

        /**
         * The diagram's boxes and lines with what lies outside the workflow, each kind either as boxes of its own or folded
         * into icons in the header of the boxes it applies to: jobs and workflows elsewhere ("external"), and files and
         * times, which run nothing ("conditions").
         */
        withExternal(items, lines, edge) {
            const on = { external: this.showExternal, conditions: this.showConditions, tree: true };
            return { items: [...items.map(item => ({ ...item, externalMarks: (edge.marks.get(item.id) || []).filter(m => !on[m.cat]).map(m => [m.icon, m.words]) })),
                             ...edge.items.filter(box => on[box.cat])],
                     lines: [...lines, ...edge.lines.filter(line => on[line.cat])] };
        },

        /** What the Reactions marker says when pointed at, or null for a job without any. */
        reactionsTip(item) {
            const shown = this.reactionsShown(item);
            if (!shown.length) return null;
            const whose = item.reactions_overridden ? "Its own Reactions here" : "Its job's Reactions";
            return `${whose}: ` + shown.map(r => this.reactionWords(r)).join(" ");
        },

        /** Draws the workflow's diagram; Alpine calls it again whenever anything it reads changes. */
        drawDefinition(canvas) {
            if (!this.form || this.view !== "diagram") return;
            const diagram = { ...this.definitionDiagram(), direction: this.direction, zoom: this.zoom, find: this.find.trim(),
                              editing: this.editing, tick: this.themeTick };
            WorkflowDiagram.draw(canvas, diagram, { select: (kind, id) => this.select(kind, id),
                                                    connect: (from, to) => this.connect(from, to),
                                                    remove: id => this.removeLine(id), open: href => this.openWorkflow(href),
                                                    fold: id => this.toggleFold(id) });
        },

        /** Folds a frame to one box, or opens it. */
        toggleFold(id) {
            const used = this.form ? this.form.items.find(i => String(i.uid) === String(id)) : null;
            if ((used && !used.embedded && this.jobKind(used.job_key) === "WORKFLOW") || String(id).startsWith("sh:")) {
                this.toggleShared(String(id), used ? used.job_key.trim() : this.sharedKeyOf(String(id)));
            } else {
                this.folded = { ...this.folded, [id]: !this.folded[id] };
            }
        },

        /** Opens a workflow of its own inline, read only (loading it first), or closes it. */
        async toggleShared(id, key) {
            if (!this.opened[id] && key) await this.loadJobDetail(key);
            this.opened = { ...this.opened, [id]: !this.opened[id] };
        },

        /** The key of the workflow whose box has this id, when it is one of those opened inside another. */
        sharedKeyOf(id) { return sharedKeys[id] || ""; },

        /** The run's items and those inside its frames, flattened, each with its depth and the path of the frame it is in. */
        flattenRun(items, depth = 0, parentPath = null) {
            return items.flatMap(item => [{ ...item, depth, parentPath }, ...this.flattenRun(item.inside || [], depth + 1, item.path)]);
        },

        get runFlat() { return this.run && this.run.items ? this.flattenRun(this.run.items) : []; },

        /** The workflow as last saved, its frames included: every item by its path (Transform/Enrich). */
        definitionByPath() {
            const found = new Map();
            const walk = (detail, prefix) => (detail.items || []).forEach(item => {
                found.set(prefix + item.name, item);
                if (item.embedded && item.contents && item.contents.job_type === "WORKFLOW") walk(item.contents, prefix + item.name + "/");
            });
            if (this.job) walk(this.job, "");
            return found;
        },

        /** A form item's path, as a run names it: the names of the frames it is in, then its own, with a slash between. */
        pathOfItem(item) {
            const names = [];
            for (let at = item; at; at = at.parent === null ? null : this.form.items.find(i => i.uid === at.parent)) names.unshift(this.nameOf(at.uid));
            return names.join("/");
        },

        /** What a frame in a run says about what is inside it: "2 running, 1 failed". */
        insideWords(item) {
            const leaves = this.flattenRun(item.inside || []).filter(i => !(i.inside || []).length);
            const count = (...statuses) => leaves.filter(i => statuses.includes(i.status)).length;
            const parts = [[count("RUNNING"), "running"], [count("WAITING", "PENDING"), "waiting"], [count("FAILED"), "failed"],
                           [count("SUCCESS", "BYPASSED"), "succeeded"], [count("NOT_RUN", "SKIPPED", "DISABLED"), "did not run"]]
                .filter(([n]) => n).slice(0, 3).map(([n, words]) => `${n} ${words}`);
            return parts.join(", ");
        },

        /** A run in the diagram's terms: the workflow as last saved, each job in the state the run gives it. */
        runDiagram() {
            const definition = this.definitionByPath();
            const flat = this.runFlat;
            const items = flat.map(item => {
                const used = definition.get(item.path);
                const frame = Boolean(item.frame_run_id) || (item.inside || []).length > 0;
                const saved = this.form && used ? this.form.items.find(i => i.id === used.id) : null;
                return { id: item.path, name: item.name, join: used ? used.join : "ALL", status: item.status, attempt: item.attempt,
                         statusText: frame ? [this.stateWords(item), this.insideWords(item)].filter(Boolean).join(" · ") : this.stateWords(item),
                         kind: frame ? "FRAME" : this.jobKind(item.job_key), disabled: null,
                         disabledHere: used ? used.disabled_here : null, rule: used && used.join === "CUSTOM" ? used.rule : null,
                         reactions: used && this.form ? this.reactionsTip(saved || { reactions_overridden: false, job_reactions: [] }) : null,
                         parent: item.parentPath, frame, folded: Boolean(this.folded[item.path]) };
            });
            const shown = new Set(items.map(i => i.id));
            const lines = [...definition.entries()].filter(([path]) => shown.has(path)).flatMap(([path, item]) => {
                const prefix = path.slice(0, path.lastIndexOf("/") + 1);
                return item.prerequisites.filter(p => p.kind === "JOB" && shown.has(prefix + p.target)).map((p, i) => ({
                    id: `${path}>${i}`, from: prefix + p.target, to: path, test: p.test, codes: p.return_codes || "" }));
            });
            const selected = this.runSelected ? { kind: "item", id: this.runSelected } : null;
            const saved = this.form ? this.form.items.filter(i => i.id && shown.has(this.pathOfItem(i))) : [];
            const edge = this.outsideBoxes(saved, item => this.pathOfItem(item), item => this.nameOf(item.uid), item => this.pathOfItem(item),
                                           (item, o) => this.outsideState(this.pathOfItem(item), this.outsideName(item, o)));
            return { ...this.withExternal(items, lines, edge), selected,
                     reruns: this.reruns(saved, item => item && this.pathOfItem(item)) };
        },

        /** How what a job of the run waited for outside stood when last looked at: [the box's status, in words]. */
        outsideState(path, name) {
            const waits = (this.run && this.run.outside_waits ? this.run.outside_waits : []).filter(w => w.path === path && w.target === name);
            const latest = waits[waits.length - 1];
            if (!latest || !latest.seen_status) return [null, "Not looked at yet"];
            const mapped = ["SUCCESS", "FAILED", "RUNNING", "WAITING", "NOT_RUN", "SKIPPED", "DISABLED", "BYPASSED"].includes(latest.seen_status) ? latest.seen_status : null;
            return [mapped, (STATES[latest.seen_status] || latest.seen_status) + (latest.result === "TIMED_OUT" ? " · ran out of patience" : "")];
        },

        /** What a click on a dashed box opens: another workflow. A run or edit with changes asks first, by the browser. */
        openWorkflow(href) { location.href = href; },

        /** What each outside prerequisite of a job found in the run, one line each, for the pane and the outline. */
        outsideFor(path) { return this.run && this.run.outside_waits ? this.run.outside_waits.filter(w => w.path === path) : []; },

        drawRun(canvas) {
            if (!this.run || !this.run.items || this.view !== "diagram") return;
            const diagram = { ...this.runDiagram(), direction: this.direction, zoom: this.zoom, find: "", editing: false, tick: this.themeTick };
            WorkflowDiagram.draw(canvas, diagram, { select: (kind, id) => { this.runSelected = kind === "item" ? id : ""; },
                                                    connect: () => {}, remove: () => {}, open: href => this.openWorkflow(href) });
        },

        get runItem() { return this.runFlat.find(i => i.path === this.runSelected) || null; },

        drawKey(element) { this.themeTick; WorkflowDiagram.key(element); },

        // ---------- Runs ----------

        async start() {
            this.busy = true;
            this.error = "";
            try {
                let launch = await AutoApp.send("POST", "/launches", { job_key: this.job.job_key });
                this.runId = launch.run_id;
                this.run = { starting: true, items: [], log: [] };
                history.replaceState(null, "", "workflow.html?" + new URLSearchParams({ key: this.job.job_key, run: this.runId }));
                // The run can be read once the workflow runner has recorded it
                while (!launch.recorded && launch.state === "RUNNING") {
                    await new Promise(resolve => setTimeout(resolve, 300));
                    launch = await AutoApp.get("/launches/" + encodeURIComponent(launch.launch_id));
                }
                if (!launch.recorded) {
                    this.run = null;
                    this.error = "The workflow did not start: " + (launch.output.slice(-3).join(" ") || "its runner stopped at once.");
                } else {
                    this.followRun();
                }
            } catch (e) {
                this.error = e.message;
            }
            this.busy = false;
        },

        showRun(runId) {
            this.runId = runId;
            history.replaceState(null, "", "workflow.html?" + new URLSearchParams({ key: this.key, run: runId }));
            this.followRun();
        },

        closeRun() {
            clearTimeout(pollTimer);
            this.run = null;
            this.runSelected = "";
            this.runId = "";
            history.replaceState(null, "", "workflow.html?" + new URLSearchParams({ key: this.key }));
        },

        /** Shows the run, and keeps it up to date while it is going. */
        async followRun() {
            clearTimeout(pollTimer);
            try {
                this.run = await AutoApp.get("/runs/" + encodeURIComponent(this.runId));
            } catch (e) {
                this.error = e.message;
                this.run = null;
                return;
            }
            if (this.run.status === "RUNNING") {
                pollTimer = setTimeout(() => this.followRun(), POLL_MS);
            } else if (this.job) {
                await this.loadRuns();
            }
        },

        /** A rerun reopens the run at the top: show it starting again, and follow it once it is Running. */
        async afterRerun(launch) {
            this.runId = launch.run_id;
            this.runSelected = "";
            this.run = { ...this.run, starting: true, status: "RUNNING" };
            history.replaceState(null, "", "workflow.html?" + new URLSearchParams({ key: this.key, run: this.runId }));
            await this.waitUntilRunning(launch);
            this.followRun();
        },

        async killRun() {
            if (!confirm("Kill the jobs running now, and start nothing more?")) return;
            try {
                this.run = await AutoApp.send("POST", `/runs/${encodeURIComponent(this.runId)}/kill`);
            } catch (e) {
                this.error = e.message;
            }
        },

        async killItem(item) {
            if (!confirm(`Kill '${item.name}'?`)) return;
            try {
                this.run = await AutoApp.send("POST", `/runs/${encodeURIComponent(this.runId)}/items/${item.path.split("/").map(encodeURIComponent).join("/")}/kill`);
            } catch (e) {
                this.error = e.message;
            }
        },

        /** The decisions conditions made in the run: a job's Custom rule (by its path), or Succeeds when (null). */
        checksFor(path) { return this.run && this.run.conditions ? this.run.conditions.filter(c => c.path === path) : []; },
        explainRows(check) { return AutoApp.explainRows(check.explain); },
        valuesWords(values) { return AutoApp.valuesWords(values); },

        /** What a job of the run waited for, each held or not, for a job without a Custom rule: Explain for prerequisites. */
        waitedFor(runItem) {
            const used = this.definitionByPath().get(runItem.path);
            if (!used || used.join === "CUSTOM") return [];
            const prefix = runItem.path.slice(0, runItem.path.lastIndexOf("/") + 1);
            return used.prerequisites.filter(p => p.kind === "JOB").map(p => {
                const target = this.runFlat.find(i => i.path === prefix + p.target);
                const answer = target ? prerequisiteAnswer(p, target) : "unknown";
                return { answer, words: { true: "held:", false: "did not hold:", unknown: "not yet known:" }[answer],
                         text: `${p.target} ${TESTS[p.test]}${p.test === "RC" ? " " + p.return_codes : ""}` +
                               (target ? ` (it ${this.stateWords(target).toLowerCase()})` : "") };
            });
        },

        eventsFor(path) { return this.run && this.run.reactions ? this.run.reactions.filter(e => e.path === path) : []; },

        async cancelRun() {
            try {
                this.run = await AutoApp.send("POST", `/runs/${encodeURIComponent(this.runId)}/cancel`);
            } catch (e) {
                this.error = e.message;
            }
        },

        stateWords(item) {
            const code = item.return_code !== null && item.return_code !== undefined ? ` · return code ${item.return_code}` : "";
            const attempt = item.attempt > 1 ? ` · attempt ${item.attempt}` : "";
            if (item.status_before_override) {         // counted otherwise by a Reaction: shown as both
                const was = (STATES[item.status_before_override] || item.status_before_override).toLowerCase();
                return `${STATES[item.status]} (counted; it ${was === "failed" ? "failed" : was})${code}${attempt}`;
            }
            const reason = item.reason && REASONS[item.reason] ? `: ${REASONS[item.reason]}` : "";
            return (STATES[item.status] || item.status) + reason + (["SUCCESS", "FAILED"].includes(item.status) ? code : "") + attempt;
        },

        runWords(run) {
            if (run.starting) return "Starting...";
            const reason = run.reason && REASONS[run.reason] ? ` (${REASONS[run.reason]})` : "";
            return (STATES[run.status] || run.status) + reason;
        },

        logLink(runId) { return "log.html?" + new URLSearchParams({ run: runId }); },
        time: AutoApp.formatTime,
    };
}

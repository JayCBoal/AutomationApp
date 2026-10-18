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
 *     POST   /api/v1/runs/{run_id}/cancel
 */
function workflowDetail() {
    const address = new URLSearchParams(location.search);
    const TESTS = { SUCCESS: "succeeded", FAILED: "failed", ENDED: "ended, whatever happened", RC: "gave return codes" };
    const STATES = { PENDING: "Not started yet", WAITING: "Waiting", RUNNING: "Running", SUCCESS: "Succeeded",
                     FAILED: "Failed", NOT_RUN: "Not run", DISABLED: "Disabled" };
    const REASONS = { PREREQUISITES_NOT_MET: "its prerequisites can't be met", CANCELLED: "the workflow was cancelled",
                      RETURN_CODE: "its return code is not a success code", ERROR: "a step failed",
                      JOB_FAILED: "a failure went unhandled" };
    const POLL_MS = 1500;
    const VIEW_KEY = "autoapp.workflow.view", DIRECTION_KEY = "autoapp.workflow.direction";
    const ZOOM_STEP = 1.2, ZOOM_MIN = 0.3, ZOOM_MAX = 2.5;
    let nextUid = 1;
    let pollTimer = null;

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
        find: "",
        selectedUid: null,      // the item selected on the diagram
        selectedLine: null,     // the prerequisite selected on the diagram (its uid), if a line was
        runSelected: "",        // the name of the item selected on a run's diagram
        themeTick: 0,           // changes with the theme, so the diagrams are drawn again in its colours

        async init() {
            this.chosen = this.key;
            new MutationObserver(() => this.themeTick++).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
            window.addEventListener("beforeunload", event => { if (this.changed) event.preventDefault(); });
            try {
                this.allJobs = await AutoApp.get("/jobs");
            } catch (e) {
                this.error = e.message;
                return;
            }
            if (this.isNew) {
                this.show({ job_key: "", description: "", active: true, items: [] });
                this.editing = true;
            } else if (this.key) {
                await this.load();
                if (this.job && address.has("edit")) this.editing = true;
            }
            if (this.runId) this.followRun();
        },

        get workflowKeys() { return this.allJobs.filter(j => j.job_type === "WORKFLOW").map(j => j.job_key); },
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
            const uids = {};
            const items = (job.items || []).map(item => {
                uids[item.name] = nextUid++;
                return { uid: uids[item.name], id: item.id, name: item.name, job_key: item.job_key, join: item.join, prerequisites: [] };
            });
            (job.items || []).forEach((item, index) => {
                items[index].prerequisites = item.prerequisites.map(p => ({
                    uid: nextUid++, target: uids[p.target], test: p.test, return_codes: p.return_codes || "" }));
            });
            this.form = { job_key: job.job_key, description: job.description || "", active: job.active, items };
            this.saved = JSON.stringify(this.payload());
            document.title = `${job.job_key || "New workflow"} - AutoApp`;
        },

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
                items: this.form.items.map(item => ({
                    ...(item.id ? { id: item.id } : {}),
                    name: item.name.trim() || null,
                    job_key: item.job_key.trim(),
                    join: item.join,
                    prerequisites: item.prerequisites.map(p => ({
                        target: this.nameOf(p.target), test: p.test,
                        return_codes: p.test === "RC" ? (p.return_codes.trim() || null) : null })),
                })),
            };
        },

        get changed() { return Boolean(this.form) && this.editing && JSON.stringify(this.payload()) !== this.saved; },
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

        addItem() {
            const uid = nextUid++;
            this.form.items.push({ uid, id: null, name: "", job_key: "", join: "ALL", prerequisites: [] });
            if (this.view === "diagram") this.select("item", uid);
        },

        removeItem(index) {
            const [gone] = this.form.items.splice(index, 1);
            if (this.selectedUid === gone.uid) this.select(null, null);
            for (const item of this.form.items) item.prerequisites = item.prerequisites.filter(p => p.target !== gone.uid);
        },

        moveItem(index, step) {
            const to = index + step;
            if (to < 0 || to >= this.form.items.length) return;
            const [item] = this.form.items.splice(index, 1);
            this.form.items.splice(to, 0, item);
        },

        addPrerequisite(item) {
            const other = this.form.items.find(i => i.uid !== item.uid);
            item.prerequisites.push({ uid: nextUid++, target: other ? other.uid : null, test: "SUCCESS", return_codes: "" });
        },

        removePrerequisite(item, index) {
            const [gone] = item.prerequisites.splice(index, 1);
            if (this.selectedLine === gone.uid) this.selectedLine = null;
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

        others(item) { return this.form.items.filter(i => i.uid !== item.uid); },

        placeholder(item) { return defaultName(item.job_key) || "Made from the job key"; },

        /** What an item waits for, in words, for the locked outline. */
        needs(item) {
            if (!item.prerequisites.length) return "Starts when the workflow starts";
            const parts = item.prerequisites.map(p =>
                `${this.nameOf(p.target)} ${TESTS[p.test]}${p.test === "RC" ? " " + p.return_codes : ""}`);
            return "After " + parts.join(item.join === "ANY" ? ", or " : ", and ");
        },

        jobLink(item) {
            const job = this.allJobs.find(j => j.job_key === item.job_key);
            const page = job && job.job_type === "WORKFLOW" ? "workflow.html" : "job.html";
            return page + "?" + new URLSearchParams({ key: item.job_key });
        },

        async submit() {
            if (!AutoApp.confirmDisable(this.job, this.payload())) return;
            this.busy = true;
            this.error = "";
            this.notice = "";
            try {
                const result = this.job
                    ? await AutoApp.send("PUT", "/jobs/" + encodeURIComponent(this.job.job_key), this.payload())
                    : await AutoApp.send("POST", "/jobs", this.payload());
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

        // ---------- The diagram ----------

        setView(view) {
            this.view = view;
            remember(VIEW_KEY, view);
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
            if (kind === "item") {
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
            let prerequisite = to.prerequisites.find(p => p.target === from);
            if (!prerequisite) {
                prerequisite = { uid: nextUid++, target: from, test: "SUCCESS", return_codes: "" };
                to.prerequisites.push(prerequisite);
            }
            this.select("line", prerequisite.uid);
        },

        isShown(item) { return this.view === "outline" || item.uid === this.selectedUid; },

        get found() {
            const text = this.find.trim().toLowerCase();
            return text && this.form ? this.form.items.filter(i => this.nameOf(i.uid).toLowerCase().includes(text)) : [];
        },

        showFound(item) {
            this.select("item", item.uid);
            this.$nextTick(() => {
                const box = document.querySelector(`#diagram .wf-box[data-id="${item.uid}"]`);
                if (box) box.scrollIntoView({ block: "nearest", inline: "center" });
            });
        },

        jobDisabledWords(jobKey) {
            const job = this.allJobs.find(j => j.job_key === jobKey);
            return job && !job.active ? `Its job ${jobKey} is disabled` : null;
        },

        jobKind(jobKey) {
            const job = this.allJobs.find(j => j.job_key === jobKey);
            return job ? job.job_type : "STEPS";
        },

        /** The workflow on screen, in the diagram's terms. */
        definitionDiagram() {
            const items = this.form.items.map(item => ({
                id: String(item.uid), name: this.nameOf(item.uid), join: item.join, status: null,
                sub: item.job_key ? "job " + item.job_key : "no job chosen yet",
                kind: this.jobKind(item.job_key), disabled: this.jobDisabledWords(item.job_key) }));
            const lines = this.form.items.flatMap(item => item.prerequisites.filter(p => p.target).map(p => ({
                id: String(p.uid), from: String(p.target), to: String(item.uid), test: p.test, codes: p.return_codes.trim() })));
            const selected = this.selectedLine ? { kind: "line", id: String(this.selectedLine) }
                : this.selectedUid ? { kind: "item", id: String(this.selectedUid) } : null;
            return { items, lines, selected };
        },

        /** Draws the workflow's diagram; Alpine calls it again whenever anything it reads changes. */
        drawDefinition(canvas) {
            if (!this.form || this.view !== "diagram") return;
            const diagram = { ...this.definitionDiagram(), direction: this.direction, zoom: this.zoom, find: this.find.trim(),
                              editing: this.editing, tick: this.themeTick };
            WorkflowDiagram.draw(canvas, diagram, { select: (kind, id) => this.select(kind, id),
                                                    connect: (from, to) => this.connect(from, to),
                                                    remove: id => this.removeLine(id) });
        },

        /** A run in the diagram's terms: the workflow as last saved, each job in the state the run gives it. */
        runDiagram() {
            const definition = new Map((this.job ? this.job.items : []).map(item => [item.name, item]));
            const items = this.run.items.map(item => {
                const used = definition.get(item.name);
                return { id: item.name, name: item.name, join: used ? used.join : "ALL", status: item.status,
                         statusText: this.stateWords(item), kind: this.jobKind(item.job_key), disabled: null };
            });
            const shown = new Set(items.map(i => i.id));
            const lines = [...definition.values()].filter(item => shown.has(item.name)).flatMap(item =>
                item.prerequisites.filter(p => shown.has(p.target)).map((p, i) => ({
                    id: `${item.name}>${i}`, from: p.target, to: item.name, test: p.test, codes: p.return_codes || "" })));
            const selected = this.runSelected ? { kind: "item", id: this.runSelected } : null;
            return { items, lines, selected };
        },

        drawRun(canvas) {
            if (!this.run || !this.run.items || this.view !== "diagram") return;
            const diagram = { ...this.runDiagram(), direction: this.direction, zoom: this.zoom, find: "", editing: false, tick: this.themeTick };
            WorkflowDiagram.draw(canvas, diagram, { select: (kind, id) => { this.runSelected = kind === "item" ? id : ""; },
                                                    connect: () => {}, remove: () => {} });
        },

        get runItem() { return this.run && this.run.items ? this.run.items.find(i => i.name === this.runSelected) : null; },

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

        async cancelRun() {
            try {
                this.run = await AutoApp.send("POST", `/runs/${encodeURIComponent(this.runId)}/cancel`);
            } catch (e) {
                this.error = e.message;
            }
        },

        stateWords(item) {
            const reason = item.reason && REASONS[item.reason] ? `: ${REASONS[item.reason]}` : "";
            const code = item.return_code !== null && item.return_code !== undefined ? ` · return code ${item.return_code}` : "";
            return (STATES[item.status] || item.status) + reason + (["SUCCESS", "FAILED"].includes(item.status) ? code : "");
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

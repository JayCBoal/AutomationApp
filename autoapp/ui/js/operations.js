/*
 * Operations Log page: search the record of everything job steps did, and
 * follow one file's route (its trace).
 *
 * Data comes from two API routes:
 *     GET /api/v1/operations              the search
 *     GET /api/v1/operations/{id}/trace   one file's route
 */
// The search boxes. Their names are also the API's criteria.
const CRITERIA = [
    "date_from", "date_to", "op_type", "status",
    "source_endpoint", "source_application", "source_entity", "source_site", "source_path", "source_filename",
    "dest_endpoint", "dest_application", "dest_entity", "dest_site", "dest_path", "dest_filename",
    "job_key", "instance_id", "scheduler",
];

// How each criterion is named in the one-line summary shown while the criteria are folded away
const CRITERIA_LABELS = {
    date_from: "From", date_to: "To", op_type: "Type", status: "Status", job_key: "Job",
    instance_id: "Instance ID", scheduler: "Scheduler",
};
const criterionLabel = name => CRITERIA_LABELS[name] ||
    name.replace(/^(source|dest)_(.*)$/, (_, side, field) => `${side === "source" ? "Source" : "Destination"} ${field}`);

// Whether this viewer last left the criteria folded away; a page opened from a scheduler starts folded,
// since the scheduler has already said what to show
const FOLDED_KEY = "autoapp.operations.criteriaFolded";
function startFolded() {
    if (AutoApp.EMBEDDED) return true;
    try { return localStorage.getItem(FOLDED_KEY) === "1"; } catch (e) { return false; }
}

function operationsLog() {
    const search = AutoApp.searchPage({
        criteria: CRITERIA,
        path: "/operations",
        noun: "operation",
        order: "newest first",
        // The date boxes hold local time; the API works in UTC
        toApi: values => ({
            ...values,
            date_from: AutoApp.localInputToUtc(values.date_from),
            date_to: AutoApp.localInputToUtc(values.date_to),
        }),
        inAddress() { return { trace: this.traceFor }; },      // so an open trace can be bookmarked too
    });

    return Object.assign(search, {
        trace: null,            // the trace being shown, or null
        traceFor: null,         // id of the operation whose Trace link was clicked
        traceError: "",
        folded: startFolded(),

        fold(folded) {
            this.folded = folded;
            if (AutoApp.EMBEDDED) return;
            try { localStorage.setItem(FOLDED_KEY, folded ? "1" : "0"); } catch (e) { /* not kept; it still folds */ }
        },
        criteriaSummary() {
            const set = CRITERIA.filter(name => this.criteria[name]);
            if (set.length === 0) return "Everything.";
            return set.map(name => `${criterionLabel(name)}: ${this.criteria[name]}`).join(" · ");
        },

        init() {
            const address = this.startSearch();
            if (address.get("trace")) this.openTrace(Number(address.get("trace")));
        },

        // ---------- Showing one side of an operation ----------

        place(side, op) {
            if (side.endpoint) return side.endpoint;
            if (side.path) return "Working folder";
            // A file made by a query came from a database; a check or a delete has no destination
            if (side === op.source && op.details && op.details.Database) return "Database query";
            return { DELETE: "Deleted", CHECK: "Left where it was" }[op.op_type] || "";
        },
        pathOf(side, op) {
            if (side.path || side !== op.source) return side.path;
            return op.details ? op.details.Database || "" : "";
        },
        owners(side) {
            return [side.application, side.entity, side.site].filter(Boolean).join(" · ");
        },
        hasFile(row) { return Boolean(row.source.filename || row.dest.filename); },
        details(row) {
            return row.details ? Object.entries(row.details).map(([k, v]) => `${k}: ${v}`).join("; ") : "";
        },
        time: AutoApp.formatTime,
        size: AutoApp.formatSize,

        // ---------- Export ----------

        exportCsv() {
            const csv = AutoApp.toCsv(this.rows, [
                ["Operation ID", r => r.id],
                ["Started (UTC)", r => r.started], ["Ended (UTC)", r => r.ended],
                ["Type", r => r.op_type], ["Status", r => r.status],
                ["Source endpoint", r => r.source.endpoint], ["Source application", r => r.source.application],
                ["Source entity", r => r.source.entity], ["Source site", r => r.source.site],
                ["Source path", r => r.source.path], ["Source filename", r => r.source.filename],
                ["Source size", r => r.source.size],
                ["Destination endpoint", r => r.dest.endpoint], ["Destination application", r => r.dest.application],
                ["Destination entity", r => r.dest.entity], ["Destination site", r => r.dest.site],
                ["Destination path", r => r.dest.path], ["Destination filename", r => r.dest.filename],
                ["Destination size", r => r.dest.size],
                ["Job", r => r.job_key], ["Step", r => r.step_order],
                ["Instance ID", r => r.instance_id], ["Run number", r => r.run_number],
                ["Scheduler", r => r.scheduler], ["Run ID", r => r.run_id],
                ["Checksum", r => r.checksum], ["Details", r => r.details ? JSON.stringify(r.details) : ""],
                ["Error", r => r.error],
            ]);
            AutoApp.download("autoapp_operations.csv", csv);
        },

        // ---------- Trace ----------

        async openTrace(operationId) {
            this.traceFor = operationId;
            this.trace = null;
            this.traceError = "";
            this.$refs.traceWindow.showModal();
            this.rememberInAddress();
            try {
                const trace = await AutoApp.get(`/operations/${operationId}/trace`);
                // How far along its branch each hop is, for indenting: a hop sits one step in from the hop it follows
                const depth = {};
                for (const hop of trace.hops) depth[hop.id] = hop.follows === null ? 0 : (depth[hop.follows] ?? 0) + 1;
                trace.hops.forEach((hop, i) => { hop.number = i + 1; hop.depth = depth[hop.id]; });
                const numberOf = Object.fromEntries(trace.hops.map(hop => [hop.id, hop.number]));
                trace.hops.forEach(hop => { hop.followsNumber = hop.follows === null ? null : numberOf[hop.follows]; });
                this.trace = trace;
            } catch (e) {
                this.traceError = e.message;
            }
        },

        closeTrace() {
            this.$refs.traceWindow.close();
        },

        traceClosed() {         // also runs when the window is closed with the Esc key
            this.traceFor = null;
            this.rememberInAddress();
        },
    });
}

/*
 * Operations Log page: search the record of everything job steps did, and
 * follow one file's route (its trace).
 *
 * Data comes from two API routes:
 *     GET /api/v1/operations              the search
 *     GET /api/v1/operations/{id}/trace   one file's route
 */
const MAX_RESULTS = 500;      // the API returns at most this many rows

// The search boxes, in the order they appear. "local time" boxes are converted to UTC for the API.
const CRITERIA = [
    "date_from", "date_to", "op_type", "status",
    "source_endpoint", "source_path", "source_filename",
    "dest_endpoint", "dest_path", "dest_filename",
    "job_key", "instance_id",
    "application", "entity", "site",
];

function operationsLog() {
    return {
        criteria: Object.fromEntries(CRITERIA.map(name => [name, ""])),
        rows: [],
        searched: false,
        loading: false,
        error: "",
        timeZone: AutoApp.timeZoneName(),

        trace: null,            // the trace being shown, or null
        traceFor: null,         // id of the operation whose Trace link was clicked
        traceError: "",

        // ---------- Search ----------

        init() {
            // Criteria in the page address are applied, so a search can be bookmarked or sent to someone
            const address = new URLSearchParams(location.search);
            for (const name of CRITERIA) if (address.has(name)) this.criteria[name] = address.get(name);
            this.search();
            const traceId = address.get("trace");
            if (traceId) this.openTrace(Number(traceId));
        },

        get capped() { return this.rows.length >= MAX_RESULTS; },

        get summary() {
            if (this.loading) return "Searching...";
            if (!this.searched) return "";
            if (this.rows.length === 0) return "No operations match these criteria.";
            return `${this.rows.length} operation${this.rows.length === 1 ? "" : "s"}, newest first. ` +
                   `Times are shown in your time zone (${this.timeZone}).`;
        },

        apiCriteria() {
            return {
                ...this.criteria,
                date_from: AutoApp.localInputToUtc(this.criteria.date_from),
                date_to: AutoApp.localInputToUtc(this.criteria.date_to),
                limit: MAX_RESULTS,
            };
        },

        async search() {
            this.loading = true;
            this.error = "";
            try {
                this.rows = await AutoApp.get("/operations", this.apiCriteria());
            } catch (e) {
                this.rows = [];
                this.error = e.message;
            }
            this.loading = false;
            this.searched = true;
            this.rememberInAddress();
        },

        clear() {
            for (const name of CRITERIA) this.criteria[name] = "";
            this.search();
        },

        rememberInAddress() {
            const address = new URLSearchParams();
            for (const name of CRITERIA) if (this.criteria[name]) address.set(name, this.criteria[name]);
            if (this.traceFor) address.set("trace", this.traceFor);
            history.replaceState(null, "", location.pathname + (address.toString() ? "?" + address : ""));
        },

        // ---------- Showing one side of an operation ----------

        place(side) {
            if (side.endpoint) return side.endpoint;
            return side.path ? "Working folder" : "";
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
    };
}

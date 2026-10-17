"use strict";
/*
 * The workflow diagram mockup (docs/WORKFLOWS.md, Phase 2): a made-up workflow drawn
 * the way the real editor will draw it, to judge the look by eye before it is built.
 * Nothing here talks to the server.
 *
 * elkjs (vendor/elk-0.12.0.bundled.js) works out where the boxes and lines go; this
 * page draws them as SVG.
 */
(() => {
    // ---------- The sample workflow ----------

    const job = (name, more = {}) => ({ name, kind: "job", origin: "embedded", ...more });
    const flow = (name, children, more = {}) => ({ name, kind: "workflow", origin: "embedded", children, ...more });
    const LONG = "Load_general_ledger_postings_for_all_operating_companies_and_intercompany_items";

    const ITEMS = [
        job("Check_inputs", { icons: [["clock", "Starts only between 01:00 and 05:00"],
                                      ["calendar", "Only on the last business day of the month"]] }),
        job("Confirm_cutoff"),
        job("Refresh_FX_rates", { origin: "shared", def: "FX_RATES_REFRESH" }),
        job("Extract_US", { origin: "shared", def: "EXTRACT_SALES", overrides: "Region = US" }),
        job("Extract_EU", { origin: "shared", def: "EXTRACT_SALES", overrides: "Region = EU",
                            reactions: { next: ["Failed, and its failure is known: rerun this job (Resume), at most 2 times"],
                                         also: ["Runs 50% longer than its average of the last 10 runs: mark as late, notify ops"] } }),
        job("Extract_APAC", { origin: "shared", def: "EXTRACT_SALES", overrides: "Region = APAC", disabled: "pass" }),
        job("Legacy_feed"),
        job("Send_EU_extract_to_partner", { origin: "shared", def: "PARTNER_SEND", disabled: "elsewhere" }),
        job("Rebuild_EU_cache"),
        flow("Transform", [
            job("Stage"),
            job("Validate", { reactions: { next: ["Return code 8: rerun from Extract_EU, at most 2 times"],
                                           also: ["Succeeded: start the workflow AUDIT_PACK"] } }),
            job("Enrich"),
        ]),
        job("Approve_invoices", { icons: [["var", "Only when ${ApprovalNeeded} = 'Y'"]] }),
        job(LONG, { origin: "shared", def: "GL_LOAD" }),
        job("Purge_old_partitions", { disabled: "stop" }),
        job("Notify_failure"),
        job("Cleanup"),
        flow("Archive", [job("Zip_month"), job("Copy_to_vault"), job("Verify_vault_copy")],
             { origin: "shared", def: "ARCHIVE_STANDARD" }),
        job("Publish_status_page", { join: "any" }),
    ];

    // Prerequisites inside the workflow: the job "to" waits for "from". test: SUCCESS (the default), FAILED, ENDED, RC, OTHER
    const PREREQS = [
        ["Check_inputs", "Confirm_cutoff"], ["Check_inputs", "Refresh_FX_rates"], ["Check_inputs", "Extract_US"],
        ["Check_inputs", "Extract_EU"], ["Check_inputs", "Extract_APAC"], ["Check_inputs", "Rebuild_EU_cache", "OTHER", "SKIPPED or SUCCESS"],
        ["Extract_US", "Legacy_feed", "FAILED"], ["Extract_EU", "Send_EU_extract_to_partner"],
        ["Extract_US", "Transform"], ["Extract_EU", "Transform"], ["Extract_APAC", "Transform"],
        ["Transform/Stage", "Transform/Validate"], ["Transform/Validate", "Transform/Enrich", "RC", "RC 0-4"],
        ["Refresh_FX_rates", "Transform/Enrich", "ENDED"],
        ["Confirm_cutoff", "Approve_invoices"], ["Transform", "Approve_invoices"],
        ["Approve_invoices", LONG], [LONG, "Purge_old_partitions"], [LONG, "Notify_failure", "FAILED"],
        [LONG, "Cleanup", "ENDED"], ["Cleanup", "Archive"], [LONG, "Publish_status_page"],
        ["Notify_failure", "Publish_status_page", "ENDED"],
        ["Archive/Zip_month", "Archive/Copy_to_vault"], ["Archive/Copy_to_vault", "Archive/Verify_vault_copy"],
    ].map(([from, to, test = "SUCCESS", label = null]) => ({ from, to, test, label }));

    // Dependencies across the workflow's edge: what it waits for (in) and what waits for it or is started by it (out)
    const OUTSIDE = [
        { id: "out:close", side: "in", type: "job", label: "SALES_DAILY / Close_day", to: "Check_inputs", test: "SUCCESS",
          detail: "Its current or latest run succeeded", run: "Latest run: Succeeded at 00:42" },
        { id: "out:orders", side: "in", type: "endpoint", label: "INBOUND_ORDERS", to: "Check_inputs", test: "FILES",
          detail: "At least 1 file, each unchanged for 60 seconds", run: "3 files, old enough" },
        { id: "out:ledger", side: "out", type: "needed", label: "FINANCE_CLOSE / Post_ledger", from: LONG, test: "SUCCESS",
          detail: "Its job Post_ledger waits for this job to succeed" },
        { id: "out:audit", side: "out", type: "start", label: "AUDIT_PACK", from: "Transform/Validate", test: "START",
          detail: "Started by a Reaction of Transform / Validate" },
    ];
    const RERUNS = [{ from: "Transform/Validate", to: "Extract_EU", label: "↺ RC 8: rerun from here, at most 2",
                      words: "A Reaction of Transform / Validate: on return code 8, rerun from Extract_EU, at most 2 times" }];
    const REACTION_DASH = "9 3 2 3";

    // A moment in a run, for "A run in progress"
    const RUN = {
        "Check_inputs": ["SUCCESS"], "Confirm_cutoff": ["HELD", "Held for an operator: cut-off not confirmed"],
        "Refresh_FX_rates": ["FAILED", "Failed · return code 12"], "Extract_US": ["SUCCESS"],
        "Extract_EU": ["RUNNING", "Running · attempt 2 · late", { attempt: 2, late: true }],
        "Extract_APAC": ["BYPASSED", "Bypassed: disabled here, passes through"],
        "Legacy_feed": ["NOT_RUN", "Not run: its prerequisites can't be met"],
        "Send_EU_extract_to_partner": ["DISABLED", "Disabled: PARTNER_SEND is disabled"],
        "Rebuild_EU_cache": ["SKIPPED", "Skipped by a Reaction of Check_inputs"],
        "Transform/Stage": ["WAITING", "Waiting: Transform waits for Extract_EU"],
    };

    // ---------- Settings, kept in the address bar's absence by these variables ----------

    const state = { mode: "editor", view: "diagram", direction: "RIGHT", zoom: 1, fit: false,
                    expanded: { "Transform": true, "Archive": false }, selected: "Extract_EU", find: "" };
    const BY_PATH = new Map();
    const elk = new ELK();

    function index(items, parentPath = "") {
        for (const item of items) {
            item.path = parentPath ? `${parentPath}/${item.name}` : item.name;
            item.parent = parentPath || null;
            BY_PATH.set(item.path, item);
            if (item.children) index(item.children, item.path);
        }
    }

    // ---------- Small helpers ----------

    const esc = text => String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    const SVG = "http://www.w3.org/2000/svg";

    function svg(tag, attrs = {}, parent = null) {
        const node = document.createElementNS(SVG, tag);
        for (const [key, value] of Object.entries(attrs)) if (value !== null && value !== undefined) node.setAttribute(key, value);
        if (parent) parent.appendChild(node);
        return node;
    }

    const STATUS_WORDS = { SUCCESS: "Succeeded", FAILED: "Failed", RUNNING: "Running", WAITING: "Waiting", PENDING: "Not started yet",
                           HELD: "Held for an operator", NOT_RUN: "Not run", SKIPPED: "Skipped", DISABLED: "Disabled", BYPASSED: "Bypassed" };

    function runState(path) {
        const [status = "PENDING", text = STATUS_WORDS[status], more = {}] = RUN[path] || [];
        return { status, text, ...more };
    }

    function matchesFind(item) {
        return state.find.length > 0 && item.name.toLowerCase().includes(state.find.toLowerCase());
    }

    function allItems(items = ITEMS) {
        return items.flatMap(item => [item, ...(item.children ? allItems(item.children) : [])]);
    }

    function displayPath(path) { return path.split("/").join(" / "); }

    // ---------- What lines look like ----------

    function lineStyle(test) {
        const styles = {
            SUCCESS: { color: css("--success"), dash: null, words: "succeeded (the default)" },
            FAILED: { color: css("--failure"), dash: "6 4", words: "failed" },
            ENDED: { color: css("--text"), dash: null, words: "ended, whatever happened" },
            RC: { color: css("--wf-rc"), dash: null, words: "gave these return codes" },
            OTHER: { color: css("--muted"), dash: null, words: "another status, or a combination" },
            FILES: { color: css("--muted"), dash: "2 3", words: "files present" },
            START: { color: css("--muted"), dash: "2 3", words: "starts it" },
        };
        return styles[test];
    }

    // ---------- Measuring boxes ----------

    const NAME_FONT = "600 13px system-ui, -apple-system, 'Segoe UI', Roboto, 'DejaVu Sans', sans-serif";
    const SMALL_FONT = "11px system-ui, -apple-system, 'Segoe UI', Roboto, 'DejaVu Sans', sans-serif";
    const NAME_MAX = 190, PAD = 8, LINE = 16, ICON = 14, SUB_LINE = 14, MIN_WIDTH = 120;
    const measurer = document.createElement("canvas").getContext("2d");

    function textWidth(text, font) {
        measurer.font = font;
        return measurer.measureText(text).width;
    }

    /** A name broken into lines no wider than max, after underscores or spaces where it can, anywhere where it must. */
    function wrapName(name, max = NAME_MAX) {
        const lines = [];
        let line = "";
        for (const piece of name.split(/(?<=[_ ])/)) {
            if (textWidth(line + piece, NAME_FONT) <= max) { line += piece; continue; }
            if (line) lines.push(line);
            line = piece;
            while (textWidth(line, NAME_FONT) > max) {
                let cut = line.length - 1;
                while (cut > 1 && textWidth(line.slice(0, cut), NAME_FONT) > max) cut--;
                lines.push(line.slice(0, cut));
                line = line.slice(cut);
            }
        }
        if (line) lines.push(line);
        return lines;
    }

    /** The markers a box carries, each [icon, words for its tooltip]. */
    function markers(item) {
        const list = [];
        if (item.origin === "shared") list.push(["shared", `Shared: uses ${item.def}`]);
        if (item.kind === "workflow") list.push(["workflow", item.origin === "shared" ? "A shared workflow" : "An embedded workflow"]);
        if (item.reactions) list.push(["reactions", "Has Reactions"]);
        if (item.disabled === "stop") list.push(["disabled", "Disabled here: stops here"]);
        if (item.disabled === "pass") list.push(["disabled", "Disabled here: passes through"]);
        if (item.disabled === "elsewhere") list.push(["disabled", `Disabled elsewhere: ${item.def} is disabled`]);
        for (const icon of item.icons || []) list.push(icon);
        if (state.mode === "run" && runState(item.path).late) list.push(["late", "Late: running longer than expected"]);
        return list;
    }

    function subLine(item) {
        if (state.mode === "run") {
            if (item.kind === "workflow" && !state.expanded[item.path]) return frameSummary(item);
            return runState(item.path).text;
        }
        if (item.kind === "workflow" && !state.expanded[item.path]) return `${item.children.length} jobs` + (item.def ? ` · ${item.def}` : "");
        return item.origin === "shared" ? `uses ${item.def}` : null;
    }

    function frameSummary(item) {
        const counts = {};
        for (const child of allItems(item.children)) {
            const words = { PENDING: "not started", RUNNING: "running", FAILED: "failed", SUCCESS: "succeeded", WAITING: "waiting" };
            const word = words[runState(child.path).status] || runState(child.path).status.toLowerCase();
            counts[word] = (counts[word] || 0) + 1;
        }
        return `${item.children.length} jobs: ` + Object.entries(counts).map(([word, n]) => `${n} ${word}`).join(", ");
    }

    function boxModel(item) {
        const lines = wrapName(item.name);
        const icons = markers(item);
        const sub = subLine(item);
        const width = Math.max(MIN_WIDTH,
            ...lines.map(l => textWidth(l, NAME_FONT)), icons.length * (ICON + 4), sub ? Math.min(textWidth(sub, SMALL_FONT), 230) : 0);
        const height = PAD + (icons.length ? ICON + 4 : 0) + lines.length * LINE + (sub ? SUB_LINE + 2 : 0) + PAD - 2;
        return { lines, icons, sub, width: Math.ceil(width + 2 * PAD), height: Math.ceil(height) };
    }

    function stubModel(stub) {
        const prefix = { job: "⇢ ", endpoint: "", needed: "Needed by ⇢ ", start: "Starts ⇢ " }[stub.type];
        const lines = wrapName(prefix + stub.label, 260);
        const sub = state.mode === "run" && stub.run ? stub.run : null;
        const width = Math.max(110, ...lines.map(l => textWidth(l, NAME_FONT)), sub ? textWidth(sub, SMALL_FONT) : 0)
            + 2 * PAD + (stub.type === "endpoint" ? ICON + 4 : 0);
        const height = 2 * PAD + lines.length * LINE + (sub ? SUB_LINE : 0);
        return { lines, sub, width: Math.ceil(width), height: Math.ceil(height) };
    }

    // ---------- The graph elkjs lays out ----------

    /** The box a path is drawn as: itself, or the nearest enclosing workflow that is folded. */
    function visiblePath(path) {
        let shown = path;
        for (let parent = BY_PATH.get(path).parent; parent; parent = BY_PATH.get(parent).parent) {
            if (!state.expanded[parent]) shown = parent;
        }
        return shown;
    }

    function elkNode(item, models) {
        if (item.kind === "workflow" && state.expanded[item.path]) {
            const top = 14 + LINE * frameTitleLines(item).length;
            return { id: item.path, children: item.children.map(child => elkNode(child, models)),
                     layoutOptions: { "elk.padding": `[top=${top + 6},left=14,bottom=14,right=14]` } };
        }
        const model = boxModel(item);
        models.set(item.path, model);
        return { id: item.path, width: model.width, height: model.height };
    }

    const edgeWords = new Map();         // edge id: what pointing at the line says

    function nameOf(path) {
        const stub = OUTSIDE.find(s => s.id === path);
        return stub ? stub.label : displayPath(path);
    }

    function describeEdge(from, to, test, label) {
        const target = OUTSIDE.find(s => s.id === to);
        if (target && target.type === "start") return `${nameOf(from)} starts the workflow ${target.label} (a Reaction)`;
        if (target) return `${target.label} waits until ${nameOf(from)} ${lineStyle(test).words.replace(" (the default)", "")}`;
        const source = OUTSIDE.find(s => s.id === from);
        if (source && source.type === "endpoint") return `${nameOf(to)} waits for files at ${source.label}: ${source.detail.toLowerCase()}`;
        const what = test === "RC" || test === "OTHER" ? `${label.startsWith("RC") ? "gave return codes " + label.slice(3) : "was " + label}` : lineStyle(test).words.replace(" (the default)", "");
        return `${nameOf(to)} waits until ${nameOf(from)} ${what}`;
    }

    function elkEdges() {
        const seen = new Set(), edges = [];
        edgeWords.clear();
        const add = (from, to, test, label, kind = "prereq") => {
            const key = `${from}>${to}>${test}`;
            if (from === to || seen.has(key)) return;
            seen.add(key);
            const labels = label ? [{ text: label, width: textWidth(label, SMALL_FONT) + 10, height: 16 }] : [];
            edgeWords.set(`e${edges.length}`, describeEdge(from, to, test, label));
            edges.push({ id: `e${edges.length}`, sources: [from], targets: [to], labels, test, kind });
        };
        for (const p of PREREQS) add(visiblePath(p.from), visiblePath(p.to), p.test, p.label);
        for (const s of OUTSIDE) {
            if (s.side === "in") add(s.id, visiblePath(s.to), s.test, null, "outside");
            else add(visiblePath(s.from), s.id, s.test, null, "outside");
        }
        return edges;
    }

    function elkGraph(models) {
        const children = ITEMS.map(item => elkNode(item, models));
        for (const stub of OUTSIDE) {
            const model = stubModel(stub);
            models.set(stub.id, model);
            children.push({ id: stub.id, width: model.width, height: model.height,
                            layoutOptions: { "elk.layered.layering.layerConstraint": stub.side === "in" ? "FIRST" : "LAST" } });
        }
        return {
            id: "root", children, edges: elkEdges(),
            layoutOptions: {
                "elk.algorithm": "layered", "elk.direction": state.direction,
                "elk.hierarchyHandling": "INCLUDE_CHILDREN", "elk.edgeRouting": "ORTHOGONAL",
                "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
                "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
                "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
                "elk.spacing.nodeNode": "16", "elk.layered.spacing.nodeNodeBetweenLayers": "44",
                "elk.spacing.edgeNode": "12", "elk.layered.spacing.edgeNodeBetweenLayers": "14",
                "elk.edgeLabels.placement": "CENTER", "elk.padding": "[top=24,left=24,bottom=24,right=24]",
            },
        };
    }

    /** Every laid-out node's position on the page, whatever it is inside. */
    function absolutePositions(node, offset = { x: 0, y: 0 }, into = new Map()) {
        const at = { x: offset.x + (node.x || 0), y: offset.y + (node.y || 0), width: node.width, height: node.height, node };
        into.set(node.id, at);
        for (const child of node.children || []) absolutePositions(child, at, into);
        return into;
    }

    // ---------- Icons, drawn small ----------

    /** The icons, defined once for the page in a hidden SVG; they take the colour of the text around them. */
    function iconSprite() {
        const sprite = svg("svg", { width: 0, height: 0, style: "position: absolute", "aria-hidden": "true" });
        iconDefs(svg("defs", {}, sprite));
        document.body.prepend(sprite);
    }

    function iconHtml(name, words) {
        return `<svg class="wf-icon" width="14" height="14" role="img" aria-label="${esc(words)}"><title>${esc(words)}</title><use href="#i-${name}"/></svg>`;
    }

    function iconDefs(defs) {
        const symbol = (id, draw) => { const s = svg("symbol", { id, viewBox: "0 0 14 14" }, defs); draw(s); };
        const stroke = { fill: "none", stroke: "currentColor", "stroke-width": "1.4", "stroke-linecap": "round", "stroke-linejoin": "round" };
        symbol("i-clock", s => { svg("circle", { cx: 7, cy: 7, r: 5.5, ...stroke }, s); svg("path", { d: "M7 4v3.2l2.2 1.4", ...stroke }, s); });
        symbol("i-late", s => { svg("circle", { cx: 7, cy: 7, r: 5.5, ...stroke }, s); svg("path", { d: "M7 4v3.2l2.2 1.4", ...stroke }, s); });
        symbol("i-calendar", s => { svg("rect", { x: 1.5, y: 2.5, width: 11, height: 10, rx: 1.5, ...stroke }, s); svg("path", { d: "M1.5 5.5h11M4.5 1.2v2.6M9.5 1.2v2.6", ...stroke }, s); });
        symbol("i-var", s => { svg("text", { x: 7, y: 10.5, "text-anchor": "middle", "font-size": "9.5", "font-weight": "700", fill: "currentColor" }, s).textContent = "{x}"; });
        symbol("i-reactions", s => { svg("path", { d: "M8 1.2 3 8h3.6L5.8 12.8 11 6H7.4z", fill: "currentColor" }, s); });
        symbol("i-shared", s => { svg("rect", { x: 1.5, y: 4, width: 7, height: 7, rx: 1, ...stroke }, s); svg("path", { d: "M5 4V2.5h7v7h-3.5", ...stroke }, s); });
        symbol("i-workflow", s => { svg("rect", { x: 1, y: 1.5, width: 4.5, height: 4, rx: 1, ...stroke }, s); svg("rect", { x: 8.5, y: 8.5, width: 4.5, height: 4, rx: 1, ...stroke }, s); svg("path", { d: "M3.2 5.5v4.5h5.3", ...stroke }, s); });
        symbol("i-disabled", s => { svg("circle", { cx: 7, cy: 7, r: 5.5, ...stroke }, s); svg("path", { d: "M3.2 10.8 10.8 3.2", ...stroke }, s); });
        symbol("i-file", s => { svg("path", { d: "M3 1.5h5l3 3v8H3z M8 1.5v3h3", ...stroke }, s); });
        symbol("i-pause", s => { svg("path", { d: "M5 3v8M9 3v8", ...stroke, "stroke-width": "2" }, s); });
        symbol("i-lock", s => { svg("rect", { x: 2.5, y: 6, width: 9, height: 6.5, rx: 1, ...stroke }, s); svg("path", { d: "M4.5 6V4.2a2.5 2.5 0 0 1 5 0V6", ...stroke }, s); });
    }

    function icon(parent, name, x, y, color, tooltip) {
        const g = svg("g", { color }, parent);
        svg("use", { href: `#i-${name}`, x, y, width: ICON, height: ICON }, g);
        svg("rect", { x, y, width: ICON, height: ICON, fill: "transparent" }, g);   // easier to point at
        if (tooltip) svg("title", {}, g).textContent = tooltip;
    }

    function patternDefs(defs) {
        const stripes = (id, color, opacity, moving) => {
            const p = svg("pattern", { id, width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
            svg("rect", { width: 4, height: 8, fill: color, "fill-opacity": opacity }, p);
            if (moving) svg("animateTransform", { attributeName: "patternTransform", type: "translate", from: "0 0", to: "8 0",
                                                  dur: "1s", repeatCount: "indefinite", additive: "sum" }, p);
        };
        stripes("p-skipped", css("--muted"), 0.28, false);
        stripes("p-running", css("--accent"), 0.22, true);
    }

    function arrowDefs(defs) {
        for (const test of ["SUCCESS", "FAILED", "ENDED", "RC", "OTHER", "FILES", "START"]) {
            const m = svg("marker", { id: `a-${test}`, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, defs);
            svg("path", { d: "M0 0 10 5 0 10z", fill: lineStyle(test).color }, m);
        }
        const m = svg("marker", { id: "a-RERUN", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto" }, defs);
        svg("path", { d: "M0 0 10 5 0 10z", fill: css("--muted") }, m);
    }

    // ---------- Drawing ----------

    /** How a box looks in a run: fill, outline, dash, and whether its text is muted. */
    function boxLook(item) {
        const base = { fill: css("--panel-raised"), stroke: css("--border"), width: 1, dash: null, muted: false };
        if (state.mode !== "run") return item.disabled ? { ...base, dash: "5 3", muted: true } : base;
        const looks = {
            SUCCESS: { fill: css("--success"), fillOpacity: 0.2, stroke: css("--success"), width: 2 },
            FAILED: { fill: css("--failure"), fillOpacity: 0.2, stroke: css("--failure"), width: 2 },
            RUNNING: { fill: "url(#p-running)", stroke: css("--accent"), width: 2 },
            WAITING: { stroke: css("--warning"), width: 2 },
            HELD: { stroke: css("--muted"), width: 2 },
            NOT_RUN: { fill: css("--page"), stroke: css("--muted"), muted: true },
            SKIPPED: { fill: "url(#p-skipped)", stroke: css("--muted"), muted: true },
            DISABLED: { stroke: css("--muted"), muted: true, crossed: true },
            BYPASSED: { stroke: css("--muted"), dash: "5 3", muted: true, through: true },
        };
        return { ...base, ...(looks[runState(item.path).status] || {}) };
    }

    function drawBox(layer, item, at, model) {
        const look = boxLook(item);
        const g = svg("g", { class: "wf-box", "data-path": item.path, cursor: "pointer" }, layer);
        if (look.fill.startsWith("url(")) svg("rect", { x: at.x, y: at.y, width: at.width, height: at.height, rx: 6, fill: css("--panel-raised") }, g);
        svg("rect", { x: at.x, y: at.y, width: at.width, height: at.height, rx: 6, fill: look.fill, "fill-opacity": look.fillOpacity ?? 1,
                      stroke: look.stroke, "stroke-width": look.width, "stroke-dasharray": look.dash }, g);
        if (state.mode === "run" && item.kind === "workflow") svg("rect", { x: at.x + 3, y: at.y + 3, width: at.width - 6, height: at.height - 6, rx: 4, fill: "none", stroke: look.stroke, "stroke-opacity": 0.5 }, g);
        if (look.through) svg("path", { d: `M${at.x + 4} ${at.y + at.height / 2}H${at.x + at.width - 4}`, stroke: css("--muted"), "stroke-width": 1.5, "stroke-opacity": 0.6, "marker-end": "url(#a-OTHER)" }, g);
        if (look.crossed) svg("path", { d: `M${at.x + 6} ${at.y + at.height - 6}L${at.x + at.width - 6} ${at.y + 6}`, stroke: css("--muted"), "stroke-width": 1.5 }, g);
        if (matchesFind(item)) svg("rect", { x: at.x - 4, y: at.y - 4, width: at.width + 8, height: at.height + 8, rx: 9, fill: "none", stroke: css("--accent"), "stroke-width": 2.5 }, g);
        if (state.selected === item.path) svg("rect", { x: at.x - 2, y: at.y - 2, width: at.width + 4, height: at.height + 4, rx: 8, fill: "none", stroke: css("--text"), "stroke-width": 1, "stroke-dasharray": "3 2" }, g);
        drawBoxText(g, item, at, model, look);
        svg("title", {}, g).textContent = displayPath(item.path);
        if (item.kind === "workflow") {         // folded: ▸ unfolds it (so does a double-click)
            const unfold = svg("g", { "data-toggle": item.path, cursor: "pointer" }, g);
            svg("rect", { x: at.x + at.width - 22, y: at.y + 2, width: 20, height: 20, fill: "transparent" }, unfold);
            svg("text", { x: at.x + at.width - 16, y: at.y + 16, fill: css("--muted"), style: `font: ${NAME_FONT}` }, unfold).textContent = "▸";
            svg("title", {}, unfold).textContent = "Unfold";
        }
    }

    function drawBoxText(g, item, at, model, look) {
        let y = at.y + PAD;
        if (model.icons.length) {
            model.icons.forEach(([name, words], i) => icon(g, name, at.x + PAD + i * (ICON + 4), y, name === "late" ? css("--failure") : css("--muted"), words));
            if (state.mode === "run" && runState(item.path).status === "HELD") icon(g, "pause", at.x + at.width - PAD - ICON, y, css("--text"), "Held for an operator");
            y += ICON + 4;
        } else if (state.mode === "run" && runState(item.path).status === "HELD") {
            icon(g, "pause", at.x + at.width - PAD - ICON, at.y + PAD, css("--text"), "Held for an operator");
        }
        for (const line of model.lines) {
            const t = svg("text", { x: at.x + PAD, y: y + 12, fill: look.muted ? css("--muted") : css("--text"), style: `font: ${NAME_FONT}` }, g);
            t.textContent = line;
            y += LINE;
        }
        if (model.sub) {
            const t = svg("text", { x: at.x + PAD, y: y + 12, fill: css("--muted"), style: `font: ${SMALL_FONT}` }, g);
            t.textContent = model.sub;
        }
    }

    function frameTitle(item) {
        return item.origin === "shared" ? `${item.name} · ${item.def} · read-only` : `${item.name} · embedded workflow`;
    }

    // elkjs sizes a frame from what is inside it and will not widen it for its title, so the title wraps to
    // the width the frame had in the last layout (render lays out again when that changes the lines).
    const frameWidths = new Map();

    function frameTitleLines(item) {
        return wrapName(frameTitle(item), Math.max(80, (frameWidths.get(item.path) || 10000) - 64));
    }

    function drawFrame(layer, item, at) {
        const shared = item.origin === "shared";
        const g = svg("g", { class: "wf-frame" }, layer);
        svg("rect", { x: at.x, y: at.y, width: at.width, height: at.height, rx: 8, fill: css("--wf-frame"),
                      stroke: css("--border"), "stroke-width": 1.5, "stroke-dasharray": shared ? "6 4" : null }, g);
        const title = svg("g", { class: "wf-frame-title", "data-toggle": item.path, cursor: "pointer" }, g);
        svg("rect", { x: at.x, y: at.y, width: at.width, height: 28, fill: "transparent" }, title);
        svg("text", { x: at.x + 10, y: at.y + 19, fill: css("--muted"), style: `font: ${NAME_FONT}` }, title).textContent = "▾";
        icon(title, shared ? "lock" : "workflow", at.x + 24, at.y + 8, css("--muted"), shared ? "Shared, read-only here" : "An embedded workflow");
        frameTitleLines(item).forEach((line, i) =>
            svg("text", { x: at.x + 44, y: at.y + 19 + i * LINE, fill: css("--text"), style: `font: ${NAME_FONT}` }, title).textContent = line);
        svg("title", {}, title).textContent = "Fold";
    }

    function drawStub(layer, stub, at, model) {
        const g = svg("g", { class: "wf-stub", "data-path": stub.id, cursor: "pointer" }, layer);
        if (state.selected === stub.id) svg("rect", { x: at.x - 2, y: at.y - 2, width: at.width + 4, height: at.height + 4, rx: 8, fill: "none", stroke: css("--text"), "stroke-width": 1, "stroke-dasharray": "3 2" }, g);
        svg("rect", { x: at.x, y: at.y, width: at.width, height: at.height, rx: 6, fill: "none", stroke: css("--muted"), "stroke-dasharray": "4 3" }, g);
        let x = at.x + PAD;
        if (stub.type === "endpoint") { icon(g, "file", x, at.y + PAD + 1, css("--muted"), "An endpoint"); x += ICON + 4; }
        let y = at.y + PAD;
        for (const line of model.lines) {
            svg("text", { x, y: y + 12, fill: css("--text"), style: `font: ${NAME_FONT}` }, g).textContent = line;
            y += LINE;
        }
        if (model.sub) svg("text", { x, y: y + 11, fill: css("--muted"), style: `font: ${SMALL_FONT}` }, g).textContent = model.sub;
        svg("title", {}, g).textContent = stub.detail;
    }

    function drawEdge(layer, edge, positions) {
        const offset = positions.get(edge.container || "root") || { x: 0, y: 0 };
        const style = lineStyle(edge.test);
        const g = svg("g", {}, layer);
        for (const section of edge.sections || []) {
            const points = [section.startPoint, ...(section.bendPoints || []), section.endPoint];
            const d = points.map((p, i) => `${i ? "L" : "M"}${p.x + offset.x} ${p.y + offset.y}`).join(" ");
            svg("path", { d, fill: "none", stroke: style.color, "stroke-width": 1.6, "stroke-dasharray": style.dash, "marker-end": `url(#a-${edge.test})` }, g);
            hoverArea(g, d, edgeWords.get(edge.id));
        }
        for (const label of edge.labels || []) {
            const x = label.x + offset.x, y = label.y + offset.y;
            svg("rect", { x, y, width: label.width, height: label.height, rx: 3, fill: css("--page"), stroke: style.color }, layer);
            svg("text", { x: x + 5, y: y + 12, fill: style.color, style: `font: ${SMALL_FONT}` }, layer).textContent = label.text;
        }
    }

    /** A wide, invisible copy of a line, so it is easy to point at; pointing at it says what the line means. */
    function hoverArea(group, d, words) {
        const area = svg("path", { d, fill: "none", stroke: "transparent", "stroke-width": 10, "pointer-events": "stroke" }, group);
        svg("title", {}, area).textContent = words;
    }

    function drawAnyMarker(layer, at) {
        const across = state.direction === "RIGHT";
        const x = across ? at.x - 30 : at.x + at.width / 2 - 14, y = across ? at.y + at.height / 2 - 8 : at.y - 26;
        const g = svg("g", {}, layer);
        svg("rect", { x, y, width: 28, height: 16, rx: 8, fill: css("--page"), stroke: css("--text") }, g);
        svg("text", { x: x + 14, y: y + 12, "text-anchor": "middle", fill: css("--text"), style: `font: ${SMALL_FONT}; font-weight: 700` }, g).textContent = "ANY";
        svg("title", {}, g).textContent = "Any: starts when any one of the lines into it is satisfied, not all of them";
    }

    function rerunRoom() {
        if (state.direction === "RIGHT") return 70;
        return 40 + Math.max(...RERUNS.map(r => textWidth(r.label, SMALL_FONT) + 10));
    }

    /** A Rerun from… Reaction: a dashed arc back upstream, drawn over the layout (it is not a prerequisite). */
    function drawRerun(under, layer, rerun, positions) {
        const from = positions.get(visiblePath(rerun.from)), to = positions.get(visiblePath(rerun.to));
        if (!from || !to || from === to) return;
        const across = state.direction === "RIGHT";
        const a = across ? { x: from.x + from.width / 2, y: from.y } : { x: from.x, y: from.y + from.height / 2 };
        const b = across ? { x: to.x + to.width / 2, y: to.y } : { x: to.x, y: to.y + to.height / 2 };
        const edge = across ? -42 : -rerunRoom() + 20;    // in the room kept above (or to the left of) the diagram
        const d = across ? `M${a.x} ${a.y} V${edge} H${b.x} V${b.y}` : `M${a.x} ${a.y} H${edge} V${b.y} H${b.x}`;
        // Beneath the boxes, so it passes behind them rather than through their names
        const g = svg("g", {}, under);
        svg("path", { d, fill: "none", stroke: css("--muted"), "stroke-width": 1.6, "stroke-dasharray": REACTION_DASH, "stroke-linejoin": "round", "marker-end": "url(#a-RERUN)" }, g);
        hoverArea(g, d, rerun.words);
        const w = textWidth(rerun.label, SMALL_FONT) + 10;
        const mx = across ? (a.x + b.x) / 2 : edge + w / 2 - 6, my = across ? edge : (a.y + b.y) / 2;
        const label = svg("g", {}, layer);
        svg("rect", { x: mx - w / 2, y: my - 9, width: w, height: 16, rx: 3, fill: css("--page"), stroke: css("--muted"), "stroke-dasharray": REACTION_DASH }, label);
        svg("text", { x: mx, y: my + 3, "text-anchor": "middle", fill: css("--text"), style: `font: ${SMALL_FONT}` }, label).textContent = rerun.label;
        svg("title", {}, label).textContent = rerun.words;
    }

    function drawMatchCounts(layer, positions) {
        for (const item of allItems()) {
            if (item.kind !== "workflow" || state.expanded[item.path] || !state.find) continue;
            const inside = allItems(item.children).filter(matchesFind).length;
            const at = positions.get(item.path);
            if (!inside || !at) continue;
            const text = `${inside} match${inside > 1 ? "es" : ""} inside`, w = textWidth(text, SMALL_FONT) + 12;
            svg("rect", { x: at.x + at.width - w + 6, y: at.y - 10, width: w, height: 17, rx: 8, fill: css("--accent") }, layer);
            svg("text", { x: at.x + at.width - w / 2 + 6, y: at.y + 3, "text-anchor": "middle", fill: css("--accent-text"), style: `font: ${SMALL_FONT}; font-weight: 600` }, layer).textContent = text;
        }
    }

    function draw(result, models) {
        const positions = absolutePositions(result);
        const room = rerunRoom();       // space above or beside for the rerun lines
        const across = state.direction === "RIGHT";
        const width = result.width + (across ? 0 : room), height = result.height + (across ? room : 0);
        const root = svg("svg", { width: width * state.zoom, height: height * state.zoom, viewBox: `${across ? 0 : -room} ${across ? -room : 0} ${width} ${height}`, role: "img", "aria-label": "Workflow diagram" });
        const defs = svg("defs", {}, root);
        patternDefs(defs); arrowDefs(defs);
        const frames = svg("g", {}, root), edges = svg("g", {}, root), boxes = svg("g", {}, root), over = svg("g", {}, root);
        for (const [path, at] of positions) {
            const item = BY_PATH.get(path);
            if (item && item.kind === "workflow" && state.expanded[path]) drawFrame(frames, item, at);
            else if (item) drawBox(boxes, item, at, models.get(path));
            else if (models.has(path)) drawStub(boxes, OUTSIDE.find(s => s.id === path), at, models.get(path));
        }
        const allEdges = [];
        (function collect(node) { allEdges.push(...(node.edges || [])); (node.children || []).forEach(collect); })(result);
        allEdges.forEach(edge => drawEdge(edges, edge, positions));
        for (const item of allItems()) if (item.join === "any" && positions.has(visiblePath(item.path))) drawAnyMarker(over, positions.get(visiblePath(item.path)));
        RERUNS.forEach(rerun => drawRerun(edges, over, rerun, positions));
        drawMatchCounts(over, positions);
        return root;
    }

    // ---------- The outline ----------

    function needsText(item) {
        const words = { SUCCESS: "succeeded", FAILED: "failed", ENDED: "ended", RC: "gave", OTHER: "was" };
        const inside = PREREQS.filter(p => p.to === item.path).map(p => `${displayPath(p.from)} ${words[p.test]}${p.label ? ` ${p.label.replace(/^RC /, "return code ")}` : ""}`);
        const outside = OUTSIDE.filter(s => s.side === "in" && s.to === item.path).map(s => `${s.label}: ${s.detail.toLowerCase()}`);
        const all = [...inside, ...outside];
        if (all.length) return `After ${all.join(item.join === "any" ? ", or " : ", and ")}`;
        return item.children ? "No prerequisites of its own; its jobs have theirs" : "Starts when the workflow starts";
    }

    function outlineItem(item) {
        const icons = markers(item).map(([name, words]) => iconHtml(name, words)).join(" ");
        const status = state.mode === "run" ? `<span class="muted">${esc(item.kind === "workflow" ? frameSummary(item) : runState(item.path).text)}</span>` : "";
        const kind = item.origin === "shared" ? `<span class="muted">uses ${esc(item.def)}</span>` : "";
        const children = item.children ? `<ul>${item.children.map(outlineItem).join("")}</ul>` : "";
        return `<li><div class="row ${matchesFind(item) ? "found" : ""}" data-path="${esc(item.path)}">${icons} <span class="name">${esc(item.name)}</span> ${kind} ${status}</div>
                <div class="needs">${esc(needsText(item))}</div>${children}</li>`;
    }

    function renderOutline() {
        const waits = OUTSIDE.filter(s => s.side === "out").map(s => `<li>${esc(s.type === "start" ? "Starts" : "Needed by")} ${esc(s.label)} <span class="muted">${esc(s.detail)}</span></li>`).join("");
        return `<div class="wf-outline"><ul>${ITEMS.map(outlineItem).join("")}</ul>
                <div class="section-title">Waiting for this workflow, or started by it</div><ul>${waits}</ul></div>`;
    }

    // ---------- The side panel, Find and the key ----------

    function renderStubSide(side, stub) {
        const kinds = { job: "A job in another workflow", endpoint: "An endpoint", needed: "A job in another workflow that waits for this one",
                        start: "A workflow started by a Reaction in this one" };
        const linked = stub.side === "in" ? `Waited for by ${displayPath(stub.to)}` : `${stub.type === "start" ? "Started by" : "Waits for"} ${displayPath(stub.from)}`;
        side.innerHTML = `<div class="wf-outside">${iconHtml("lock", "Outside")} Outside this workflow</div>
            <h2>${esc(stub.label)}</h2><div>${esc(kinds[stub.type])}</div>
            <h3>${stub.side === "in" ? "This workflow waits for it" : "It depends on this workflow"}</h3><div>${esc(stub.detail)}</div><div class="muted">${esc(linked)}</div>
            ${state.mode === "run" && stub.run ? `<h3>Now</h3><div>${esc(stub.run)}</div>` : ""}
            <p style="margin-top: 14px"><a href="#" onclick="return false">Open ${esc(stub.type === "endpoint" ? "the endpoint" : stub.label.split(" / ")[0])}</a> <span class="muted">(not in the mockup)</span></p>
            <p class="muted">Defined in this workflow's prerequisites${stub.type === "start" ? " (here, a Reaction)" : ""}; it is edited there, not here.</p>`;
    }

    function renderSide() {
        const item = BY_PATH.get(state.selected);
        const side = document.getElementById("side");
        const stub = OUTSIDE.find(s => s.id === state.selected);
        if (stub) { renderStubSide(side, stub); return; }
        if (!item) { side.innerHTML = `<p class="muted">Select a box to see it here.</p>`; return; }
        const kind = item.kind === "workflow" ? (item.origin === "shared" ? `Shared workflow: uses ${item.def}` : "Embedded workflow")
                                              : (item.origin === "shared" ? `Shared job: uses ${item.def}` : "Embedded job");
        const list = (title, rows) => rows && rows.length ? `<h3>${title}</h3><ul>${rows.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : "";
        const disabled = { stop: "Disabled here: stops here", pass: "Disabled here: passes through", elsewhere: `Disabled elsewhere: ${item.def} is disabled` }[item.disabled];
        side.innerHTML = `<h2>${esc(item.name)}</h2><div class="muted">${esc(displayPath(item.path))}</div><div>${esc(kind)}</div>
            ${item.overrides ? `<div class="muted">Overrides: ${esc(item.overrides)}</div>` : ""}
            ${disabled ? `<div class="muted">${esc(disabled)}</div>` : ""}
            ${state.mode === "run" ? `<h3>In this run</h3><div>${esc(item.kind === "workflow" ? frameSummary(item) : runState(item.path).text)}</div>` : ""}
            <h3>Prerequisites</h3><div>${esc(needsText(item))}</div>
            ${list("Conditions", (item.icons || []).map(([, words]) => words))}
            ${item.reactions ? list("Reactions: what happens next", item.reactions.next) + list("Reactions: also", item.reactions.also) : ""}
            <p class="muted" style="margin-top: 16px">In the real editor this is where it is edited, with the same panel as the job editor.</p>`;
    }

    function renderResults() {
        const found = allItems().filter(matchesFind);
        document.getElementById("results").innerHTML = found.length || !state.find ? found.map(item =>
            `<li><button type="button" data-path="${esc(item.path)}">${esc(displayPath(item.path))}</button>${item.parent && !isShown(item) ? ' <span class="muted">(inside a folded workflow)</span>' : ""}</li>`).join("")
            : `<li class="muted">Nothing in this workflow has a name containing "${esc(state.find)}".</li>`;
    }

    function isShown(item) { return visiblePath(item.path) === item.path; }

    function showMatches() {
        const found = allItems().filter(matchesFind);
        for (const item of found) {
            for (let parent = item.parent; parent; parent = BY_PATH.get(parent).parent) state.expanded[parent] = true;
        }
        if (found.length) state.scrollTo = found[0].path;
        render();
    }

    /** Brings a box into view in the canvas, once, after it is drawn. */
    function scrollToPending(canvas) {
        if (!state.scrollTo) return;
        const box = canvas.querySelector(`[data-path="${CSS.escape(state.scrollTo)}"]`);
        state.scrollTo = null;
        if (!box) return;
        const at = box.getBoundingClientRect(), view = canvas.getBoundingClientRect();
        canvas.scrollLeft += at.left - view.left - (view.width - at.width) / 2;
        canvas.scrollTop += at.top - view.top - (view.height - at.height) / 2;
    }

    function legendSample(kind, value) {
        const s = svg("svg", { width: 70, height: 22 });
        const defs = svg("defs", {}, s);
        arrowDefs(defs); patternDefs(defs);
        if (kind === "line") {
            const style = lineStyle(value);
            svg("path", { d: "M4 11H62", stroke: style.color, "stroke-width": 1.6, "stroke-dasharray": style.dash, "marker-end": `url(#a-${value})` }, s);
            return s;
        }
        const keep = state.mode;
        state.mode = "run";
        RUN.__legend = [value];
        const look = boxLook({ path: "__legend" });
        state.mode = keep;
        delete RUN.__legend;
        if (look.fill.startsWith("url(")) svg("rect", { x: 4, y: 3, width: 62, height: 16, rx: 4, fill: css("--panel-raised") }, s);
        svg("rect", { x: 4, y: 3, width: 62, height: 16, rx: 4, fill: look.fill, "fill-opacity": look.fillOpacity ?? 1, stroke: look.stroke, "stroke-width": look.width, "stroke-dasharray": look.dash }, s);
        if (look.crossed) svg("path", { d: "M8 17L62 5", stroke: css("--muted"), "stroke-width": 1.5 }, s);
        if (look.through) svg("path", { d: "M8 11H60", stroke: css("--muted"), "stroke-width": 1.5, "marker-end": "url(#a-OTHER)" }, s);
        return s;
    }

    function renderLegend() {
        const legend = document.getElementById("legend");
        legend.innerHTML = "";
        const row = (sample, words) => { const div = document.createElement("div"); div.className = "item"; div.append(sample); div.insertAdjacentHTML("beforeend", `<span>${words}</span>`); legend.append(div); };
        for (const test of ["SUCCESS", "FAILED", "ENDED", "RC", "OTHER"]) row(legendSample("line", test), `Line: waits until the job before it ${esc(lineStyle(test).words)}`);
        const states = { SUCCESS: "Succeeded", FAILED: "Failed", RUNNING: "Running", WAITING: "Waiting on a prerequisite", PENDING: "Not started yet",
                         HELD: "Held for an operator (pause marker)", NOT_RUN: "Not run: prerequisites can't be met", SKIPPED: "Skipped by a Reaction",
                         DISABLED: "Disabled", BYPASSED: "Bypassed: passed through" };
        for (const [status, words] of Object.entries(states)) row(legendSample("box", status), `In a run: ${words}`);
        const marks = [["shared", "shared (uses a job defined elsewhere)"], ["workflow", "a workflow"], ["reactions", "has Reactions"], ["disabled", "disabled"],
                       ["clock", "a time window"], ["calendar", "a date"], ["var", "a test on a variable"], ["file", "an endpoint"], ["pause", "held"], ["lock", "read-only here"]];
        legend.insertAdjacentHTML("beforeend", `<div class="item"><span>Markers: ${marks.map(([n, w]) => `${iconHtml(n, w)} ${esc(w)}`).join(" · ")}.
            <span style="color: var(--failure)">${iconHtml("late", "late")}</span> late. Point at a marker on a box to read its exact condition.
            Dashed boxes at the edges are outside the workflow. A dash-dot line marked ↺ is a Reaction that reruns upstream. Point at any line to read what it means.</span></div>`);
    }

    // ---------- Putting it together ----------

    /** Notes each laid-out frame's width; true when that changes how a title wraps. */
    function rememberFrameWidths(result) {
        let changed = false;
        for (const [path, at] of absolutePositions(result)) {
            const item = BY_PATH.get(path);
            if (!item || item.kind !== "workflow" || !state.expanded[path]) continue;
            const before = frameTitleLines(item).length;
            frameWidths.set(path, at.width);
            if (frameTitleLines(item).length !== before) changed = true;
        }
        return changed;
    }

    let renderCount = 0;

    async function render() {
        for (const button of document.querySelectorAll("[data-set]")) button.classList.toggle("on", state[button.dataset.set] === button.dataset.value);
        const canvas = document.getElementById("canvas");
        renderSide(); renderResults(); renderLegend();
        if (state.view === "outline") { canvas.innerHTML = renderOutline(); return; }
        const mine = ++renderCount;
        let models, result;
        for (let pass = 0; pass < 3; pass++) {          // again only while a frame's title wraps differently
            models = new Map();
            result = await elk.layout(elkGraph(models));
            if (!rememberFrameWidths(result)) break;
        }
        if (mine !== renderCount) return;
        if (state.fit) state.zoom = Math.min(1, (canvas.clientWidth - 4) / (result.width + (state.direction === "RIGHT" ? 0 : rerunRoom())));
        canvas.replaceChildren(draw(result, models));
        scrollToPending(canvas);
    }

    function wireUp() {
        document.addEventListener("click", event => {
            const set = event.target.closest("[data-set]");
            if (set) { state[set.dataset.set] = set.dataset.value; render(); return; }
            const zoom = event.target.closest("[data-zoom]");
            if (zoom) { const step = Number(zoom.dataset.zoom); state.fit = step === 0; if (step) state.zoom = Math.max(0.3, Math.min(2.5, state.zoom * (step > 0 ? 1.2 : 1 / 1.2))); render(); return; }
            const toggle = event.target.closest("[data-toggle]");
            if (toggle) { state.expanded[toggle.dataset.toggle] = !state.expanded[toggle.dataset.toggle]; render(); return; }
            const pick = event.target.closest("[data-path]");
            if (!pick) return;
            state.selected = pick.dataset.path;
            if (pick.closest("#results")) {           // a Find result: unfold what it is inside, and show it
                for (let parent = BY_PATH.get(pick.dataset.path).parent; parent; parent = BY_PATH.get(parent).parent) state.expanded[parent] = true;
                state.scrollTo = pick.dataset.path;
            }
            render();
        });
        document.addEventListener("dblclick", event => {
            const box = event.target.closest(".wf-box");
            const item = box && BY_PATH.get(box.dataset.path);
            if (item && item.kind === "workflow") { state.expanded[item.path] = true; render(); }
        });
        document.getElementById("find").addEventListener("input", event => { state.find = event.target.value.trim(); render(); });
        document.getElementById("show-matches").addEventListener("click", showMatches);
        new MutationObserver(render).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
        window.addEventListener("resize", () => { if (state.fit) render(); });
    }

    index(ITEMS);
    document.addEventListener("DOMContentLoaded", () => { iconSprite(); wireUp(); render(); });
})();

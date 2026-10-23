"use strict";
/*
 * The workflow diagram (docs/WORKFLOWS.md, "The diagram and the editor"; docs/WORKFLOWS_PHASE2.md).
 * It draws a workflow as boxes and lines: elkjs (vendor/elk-0.12.0.bundled.js) works out where
 * they go, and this file draws them as SVG. It knows nothing about the server or Alpine: the
 * workflow page hands it what to draw and is told what was clicked or dragged.
 *
 * What it is given, to draw(canvas, diagram, handlers):
 *     diagram.items:  [{ id, name, sub, kind ("JOB" or "WORKFLOW"), disabled (words, or null),
 *                        join ("ALL" or "ANY"), status (a run's state, or null), statusText,
 *                        disabledHere ("STOP", "PASS_THROUGH" or null), reactions (words, or null),
 *                        attempt (in a run: how many times it has run, shown as ×2 from the second),
 *                        rule (its Custom rule, or null), changed (true: changed since it was last saved),
 *                        outside (null; or "JOB", "FILES", "TIME" or "NEEDED": a dashed box outside the workflow, see below),
 *                        href (outside: the page a click opens), owner (outside: the id of the box a click selects instead) }]
 *                        Frames (docs/WORKFLOWS_PHASE6.md): parent (the id of the frame it is in, or null), frame (true: a workflow
 *                        embedded in this one, drawn as a box around its items), folded (true: drawn as one box, with its
 *                        summary in sub or statusText; lines that end inside it end on it)
 *     diagram.lines:  [{ id, from, to, test, codes, words }]   "to" waits for "from"; test RULE: named in its Custom rule;
 *                     FILES, TIME: an outside box of files or a time; NEEDED: "to" is a job elsewhere that waits for "from".
 *                     words, if given, is what pointing at the line says
 *     diagram.reruns: [{ from, to, words }]   Rerun from... Reactions: "from" reruns from "to", drawn back
 *                     upstream as a dash-dot arc after the layout, so elkjs never sees a loop
 *     diagram.direction ("RIGHT" or "DOWN"), zoom (a number, or "fit"), find (text),
 *     selected ({ kind: "item" or "line", id }, or null), editing (true lets boxes be joined by dragging)
 *     handlers.select(kind, id), handlers.connect(fromId, toId), handlers.remove(lineId) (the x on a line, while editing),
 *     handlers.fold(frameId) (the arrow on a frame, or a double-click on it)
 * draw() resolves to the zoom it used, so the page can show it after Fit.
 *
 * Outside dependencies (docs/WORKFLOWS_PHASE5.md) are dashed boxes at the edges: what a job waits for outside
 * (a job or workflow elsewhere, files, a time) on the way in, and the jobs elsewhere that wait for it ("Needed by")
 * on the way out. autoapp/ui/mockup_workflow.html draws the whole design, with what later phases add.
 */
const WorkflowDiagram = (() => {
    const SVG = "http://www.w3.org/2000/svg";
    const NAME_FONT = "600 13px system-ui, -apple-system, 'Segoe UI', Roboto, 'DejaVu Sans', sans-serif";
    const SMALL_FONT = "11px system-ui, -apple-system, 'Segoe UI', Roboto, 'DejaVu Sans', sans-serif";
    const NAME_MAX = 190, SUB_MAX = 230, PAD = 8, LINE = 16, ICON = 14, SUB_LINE = 14, MIN_WIDTH = 120;
    const ARROW_LENGTH = 7 * 0.9;   // an arrowhead's length, in line widths (its marker is 7 wide; the tip is at 9 of 10)
    const DRAG_START = 5;           // pixels the pointer moves before a press on a box becomes a drag
    const EXTERNAL = "EXTERNAL";
    const EXTERNAL_FONT = "700 10px system-ui, -apple-system, 'Segoe UI', Roboto, 'DejaVu Sans', sans-serif";
    const TESTS = ["SUCCESS", "FAILED", "ENDED", "RC", "RULE", "FILES", "TIME", "NEEDED"];
    const elk = new ELK();
    const measurer = document.createElement("canvas").getContext("2d");

    // ---------- Small helpers ----------

    const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

    function svg(tag, attrs = {}, parent = null) {
        const node = document.createElementNS(SVG, tag);
        for (const [key, value] of Object.entries(attrs)) if (value !== null && value !== undefined) node.setAttribute(key, value);
        if (parent) parent.appendChild(node);
        return node;
    }

    function textWidth(text, font) {
        measurer.font = font;
        return measurer.measureText(text).width;
    }

    function tooltip(node, words) {
        svg("title", {}, node).textContent = words;
    }

    // ---------- What lines look like ----------

    /** A test's colour, dash and words. Each has a line style as well as a colour, for colour-blind eyes. */
    function lineStyle(test) {
        const styles = {
            SUCCESS: { color: css("--success"), dash: null, words: "succeeded" },
            FAILED: { color: css("--failure"), dash: "6 4", words: "failed" },
            ENDED: { color: css("--text"), dash: null, words: "ended, whatever happened" },
            RC: { color: css("--wf-rc"), dash: null, words: "gave return codes" },
            RULE: { color: css("--muted"), dash: "2 3", words: "ended, or enough is known for its Custom rule" },
            FILES: { color: css("--accent"), dash: "8 3", words: "have arrived and are old enough" },
            TIME: { color: css("--accent"), dash: "2 3", words: "is true" },
            NEEDED: { color: css("--muted"), dash: "8 3", words: "has done what is waited for" },
        };
        return styles[test] || { color: css("--muted"), dash: null, words: test.toLowerCase() };
    }

    function lineLabel(line) {
        return line.test === "RC" ? `RC ${line.codes || "?"}` : null;
    }

    /** What pointing at a line says: "Transform waits until Extract_US succeeded". */
    function lineWords(line, names) {
        if (line.words) return line.words;
        if (line.test === "RULE") return `${names.get(line.to)}'s Custom rule names ${names.get(line.from)}. Point at the {x} on ${names.get(line.to)} to read the rule`;
        const what = line.test === "RC" ? `gave return codes ${line.codes || "(none given yet)"}` : lineStyle(line.test).words;
        return `${names.get(line.to)} waits until ${names.get(line.from)} ${what}`;
    }

    // ---------- Measuring boxes ----------

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
        return lines.length ? lines : [""];
    }

    /** The markers a box carries, each [icon, words for its tooltip]. */
    function markers(item) {
        const list = [];
        if (item.kind === "WORKFLOW") list.push(["workflow", "A workflow, used here as one job"]);
        if (item.kind === "FRAME") list.push(["frame", "A workflow embedded in this one: it belongs to this workflow, and its jobs are inside"]);
        if (item.disabled) list.push(["disabled", item.disabled]);
        if (item.disabledHere === "STOP") list.push(["disabled", "Disabled here: it stops here, and what needs it to succeed does not run"]);
        if (item.disabledHere === "PASS_THROUGH") list.push(["pass", "Disabled here to pass through: it counts as succeeded without running"]);
        if (item.changed) list.push(["changed", "Changed since it was last saved: Save keeps the change, Cancel drops it"]);
        if (item.outside === "FILES") list.push(["files", "Files at an endpoint, on this server"]);
        if (item.outside === "TIME") list.push([item.calendar ? "calendar" : "clock", "A condition on the time"]);
        if (item.outside === "JOB") list.push(["workflow", "A job, or a whole workflow, outside this one"]);
        if (item.outside === "NEEDED") list.push(["workflow", "A job in another workflow, which waits for this job"]);
        list.push(...(item.externalMarks || []));        // external references folded into the box, when their boxes are hidden
        if (item.readonly) list.push(["lock", "Read only: it belongs to another workflow. Click it to open that workflow"]);
        if (item.rule !== null && item.rule !== undefined) list.push(["rule", `Starts when its Custom rule holds: ${item.rule || "(not written yet)"}`]);
        return list;
    }

    /** The second line of a box: in a run, its state; otherwise what it is given (its job). */
    function subLine(item) {
        return item.status ? item.statusText : item.sub;
    }

    /** ×2 and so on, beside the first line of the name: [text, tooltip], or null when the item ran once. */
    function attemptMark(item) {
        return item.attempt > 1 ? ["×" + item.attempt, `Run ${item.attempt} times in this run: see Job History for each attempt`] : null;
    }

    function boxModel(item) {
        const lines = wrapName(item.name || "(no name yet)");
        const attempts = attemptMark(item);
        const icons = markers(item);
        const sub = subLine(item);
        const subLines = sub ? wrapName(sub, SUB_MAX).length : 0;
        const external = item.outside ? tag(item.outside) : null;
        const reactions = item.reactions ? ["reactions", item.reactions] : null;     // beside the name, with ×2
        const beside = (reactions ? ICON + 4 : 0) + (attempts ? textWidth(attempts[0], SMALL_FONT) : 0);
        const firstLine = textWidth(lines[0], NAME_FONT) + (beside ? ATTEMPT_GAP + beside : 0);
        const width = Math.max(MIN_WIDTH, firstLine, ...lines.map(l => textWidth(l, NAME_FONT)),
                               icons.length * (ICON + 4) + (external ? textWidth(external, EXTERNAL_FONT) + 4 : 0),
                               sub ? Math.min(textWidth(sub, SMALL_FONT), SUB_MAX) : 0);
        const height = PAD + (icons.length ? ICON + 4 : 0) + lines.length * LINE + subLines * SUB_LINE + PAD;
        const indent = item.frame && item.folded ? FOLD_INDENT : 0;        // room for the arrow at the top left
        return { lines, icons, attempts, reactions, sub, external, indent, width: Math.ceil(width + 2 * PAD + indent), height: Math.ceil(height + (indent && !icons.length ? ICON + 4 : 0)) };
    }

    // ---------- The graph elkjs lays out ----------

    const ATTEMPT_GAP = 8;      // between the name and the ×2 beside it

    const FRAME_PADDING = "[top=40,left=14,bottom=14,right=14]";
    const FRAME_HEAD = 34, FOLD_INDENT = 22;

    /** The items that can be seen: those not inside a folded frame. */
    function visibleItems(diagram) {
        const byId = new Map(diagram.items.map(item => [item.id, item]));
        const hidden = item => { for (let up = byId.get(item.parent); up; up = byId.get(up.parent)) if (up.folded) return true; return false; };
        return { byId, visible: diagram.items.filter(item => !hidden(item)), hidden };
    }

    /** One box, or a frame with its items inside it. */
    function elkNode(item, visible, models) {
        const model = boxModel(item);
        models.set(item.id, model);
        const kids = item.frame && !item.folded ? visible.filter(child => child.parent === item.id) : null;
        if (!kids) return { id: item.id, width: model.width, height: model.height };
        // The header's second line (name above, sub-title below) needs only the wider of the two; one line needs both
        const head = 50 + Math.max(textWidth(item.name || "(no name yet)", NAME_FONT), textWidth(subLine(item) || "", SMALL_FONT)) + PAD;
        const width = Math.max(160, Math.ceil(head));
        return { id: item.id, children: kids.map(child => elkNode(child, visible, models)),
                 layoutOptions: { "elk.padding": FRAME_PADDING, "elk.nodeSize.constraints": "MINIMUM_SIZE",
                                  "elk.nodeSize.minimum": `(${width}, 70)` } };
    }

    function elkGraph(diagram, models) {
        const { byId, visible, hidden } = visibleItems(diagram);
        const ids = new Set(visible.map(item => item.id));
        const shown = id => {                               // a line that ends inside a folded frame ends on the frame
            let item = byId.get(id);
            while (item && hidden(item)) item = byId.get(item.parent);
            return item ? item.id : id;
        };
        const children = visible.filter(item => !item.parent || !byId.has(item.parent)).map(item => elkNode(item, visible, models));
        const seen = new Set();
        const edges = [];
        for (const line of diagram.lines) {
            const from = shown(line.from), to = shown(line.to);
            const key = `${from}>${to}>${line.test}>${line.codes || ""}`;
            if (!ids.has(from) || !ids.has(to) || from === to || seen.has(key)) continue;
            seen.add(key);
            const label = lineLabel(line);
            const labels = label ? [{ text: label, width: textWidth(label, SMALL_FONT) + 10, height: 16 }] : [];
            edges.push({ id: line.id, sources: [from], targets: [to], labels });
        }
        const options = layoutOptions(diagram.direction);
        if (diagram.items.some(item => item.frame)) options["elk.hierarchyHandling"] = "INCLUDE_CHILDREN";    // lines may cross frames
        return { id: "root", children, edges, layoutOptions: options };
    }

    /** Left to right (or top to bottom); each column keeps the outline's order, so nothing reshuffles. */
    function layoutOptions(direction) {
        return {
            "elk.algorithm": "layered", "elk.direction": direction, "elk.edgeRouting": "ORTHOGONAL",
            "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
            "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
            "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
            "elk.spacing.nodeNode": "16", "elk.layered.spacing.nodeNodeBetweenLayers": "44",
            "elk.spacing.edgeNode": "12", "elk.layered.spacing.edgeNodeBetweenLayers": "14",
            "elk.edgeLabels.placement": "CENTER", "elk.padding": "[top=48,left=48,bottom=24,right=24]",
        };
    }

    // ---------- Icons, patterns and arrowheads ----------

    /** A small icon in the colour given, drawn from paths so it needs nothing defined elsewhere. */
    function icon(parent, name, x, y, color, words) {
        const g = svg("g", { color, transform: `translate(${x} ${y})` }, parent);
        const stroke = { fill: "none", stroke: "currentColor", "stroke-width": "1.4", "stroke-linecap": "round", "stroke-linejoin": "round" };
        if (name === "workflow") {
            svg("rect", { x: 1, y: 1.5, width: 4.5, height: 4, rx: 1, ...stroke }, g);
            svg("rect", { x: 8.5, y: 8.5, width: 4.5, height: 4, rx: 1, ...stroke }, g);
            svg("path", { d: "M3.2 5.5v4.5h5.3", ...stroke }, g);
        } else if (name === "frame") {              // a box inside a box
            svg("rect", { x: 0.8, y: 0.8, width: 12.4, height: 12.4, rx: 1.5, ...stroke }, g);
            svg("rect", { x: 3.8, y: 5, width: 6.4, height: 5, rx: 1, ...stroke }, g);
        } else if (name === "disabled") {
            svg("circle", { cx: 7, cy: 7, r: 5.5, ...stroke }, g);
            svg("path", { d: "M3.2 10.8 10.8 3.2", ...stroke }, g);
        } else if (name === "pass") {
            svg("rect", { x: 3.5, y: 2.5, width: 7, height: 9, rx: 1, ...stroke, "stroke-dasharray": "2 1.5" }, g);
            svg("path", { d: "M0.5 7h12.5M10.5 4.5 13 7l-2.5 2.5", ...stroke }, g);
        } else if (name === "changed") {            // a pencil: edited, not saved yet
            svg("path", { d: "M2.5 11.5l1-3.5 6.5-6.5 2.5 2.5-6.5 6.5z M8.5 3l2.5 2.5", ...stroke }, g);
        } else if (name === "rule") {               // {x}: a test on values (docs/WORKFLOWS.md)
            svg("text", { x: 7, y: 11, "text-anchor": "middle", fill: "currentColor", style: `font: ${SMALL_FONT}; font-weight: 700` }, g).textContent = "{x}";
        } else if (name === "clock") {
            svg("circle", { cx: 7, cy: 7, r: 5.5, ...stroke }, g);
            svg("path", { d: "M7 4v3.2l2.2 1.4", ...stroke }, g);
        } else if (name === "calendar") {
            svg("rect", { x: 1.5, y: 2.5, width: 11, height: 10, rx: 1.5, ...stroke }, g);
            svg("path", { d: "M1.5 5.5h11M4.5 1.2v2.6M9.5 1.2v2.6", ...stroke }, g);
        } else if (name === "needed") {             // an arrow leaving a box: something elsewhere waits for this job
            svg("rect", { x: 1, y: 2.5, width: 7, height: 9, rx: 1, ...stroke }, g);
            svg("path", { d: "M8 7h5M10.8 4.5 13.3 7l-2.5 2.5", ...stroke }, g);
        } else if (name === "files") {
            svg("path", { d: "M1.5 3.5h4l1.2 1.5h5.8v6.5h-11z", ...stroke }, g);
        } else if (name === "lock") {
            svg("rect", { x: 2.5, y: 6, width: 9, height: 6.5, rx: 1, ...stroke }, g);
            svg("path", { d: "M4.5 6V4.2a2.5 2.5 0 0 1 5 0V6", ...stroke }, g);
        } else if (name.startsWith("attempts:")) {  // ×2: this item has been run more than once in the run
            svg("text", { x: 7, y: 11, "text-anchor": "middle", fill: "currentColor", style: `font: ${SMALL_FONT}; font-weight: 700` }, g).textContent = "×" + name.slice(9);
        } else if (name === "reactions") {          // a circling arrow: what happens after it ends
            svg("path", { d: "M11.5 7a4.5 4.5 0 1 1-1.4-3.3", ...stroke }, g);
            svg("path", { d: "M10.6 1.2v2.9H7.7", ...stroke }, g);
        }
        svg("rect", { width: ICON, height: ICON, fill: "transparent" }, g);       // easier to point at
        if (words) tooltip(g, words);
        return g;
    }

    /** Arrowheads and the running stripe, named with a prefix so two drawings on a page don't clash. */
    function defs(root, prefix) {
        const d = svg("defs", {}, root);
        for (const test of [...TESTS, "OTHER"]) {
            const m = svg("marker", { id: `${prefix}a-${test}`, viewBox: "0 0 10 10", refX: 9, refY: 5,
                                      markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, d);
            svg("path", { d: "M0 0 10 5 0 10z", fill: lineStyle(test).color }, m);
        }
        const s = svg("pattern", { id: `${prefix}p-skipped`, width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, d);
        svg("rect", { width: 2, height: 6, fill: css("--muted"), "fill-opacity": 0.35 }, s);
        const r = svg("marker", { id: `${prefix}a-RERUN`, viewBox: "0 0 10 10", refX: 9, refY: 5,
                                  markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, d);
        svg("path", { d: "M0 0 10 5 0 10z", fill: css("--muted") }, r);
        const p = svg("pattern", { id: `${prefix}p-running`, width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, d);
        svg("rect", { width: 4, height: 8, fill: css("--accent"), "fill-opacity": 0.22 }, p);
        svg("animateTransform", { attributeName: "patternTransform", type: "translate", from: "0 0", to: "8 0",
                                  dur: "1s", repeatCount: "indefinite", additive: "sum" }, p);
    }

    // ---------- Boxes ----------

    /** How a box looks: plain in the editor; in a run, the colours and patterns of its state. */
    /** Jobs and workflows elsewhere are amber; files and times, which run nothing, are blue. */
    const tint = kind => (kind === "FILES" || kind === "TIME" ? "--accent" : "--warning");
    const tag = kind => ({ FILES: "FILES", TIME: "TIME" }[kind] || EXTERNAL);

    function boxLook(status, prefix, external = false) {
        const base = { fill: css("--panel-raised"), stroke: css("--border"), width: 1, dash: null, muted: false };
        const looks = {
            SUCCESS: { fill: css("--success"), fillOpacity: 0.2, stroke: css("--success"), width: 2 },
            FAILED: { fill: css("--failure"), fillOpacity: 0.2, stroke: css("--failure"), width: 2 },
            RUNNING: { fill: `url(#${prefix}p-running)`, stroke: css("--accent"), width: 2 },
            WAITING: { stroke: css("--warning"), width: 2 },
            NOT_RUN: { fill: css("--page"), stroke: css("--muted"), dash: "4 3", muted: true },
            DISABLED: { stroke: css("--muted"), muted: true, crossed: true },
            BYPASSED: { stroke: css("--muted"), dash: "5 3", muted: true, through: true },
            SKIPPED: { fill: `url(#${prefix}p-skipped)`, stroke: css("--muted"), muted: true },
        };
        return { ...base, ...(looks[status] || {}), ...(external && !status ? { fill: css(tint(external)), fillOpacity: 0.16, stroke: css(tint(external)) } : {}) };
    }

    /** The box's outline and fill, at (x, y) and the size given. */
    function drawShape(g, look, x, y, width, height, rx) {
        if (look.fill.startsWith("url(")) svg("rect", { x, y, width, height, rx, fill: css("--panel-raised") }, g);
        svg("rect", { x, y, width, height, rx, fill: look.fill, "fill-opacity": look.fillOpacity ?? 1,
                      stroke: look.stroke, "stroke-width": look.width, "stroke-dasharray": look.dash }, g);
        if (look.crossed) svg("path", { d: `M${x + 6} ${y + height - 6}L${x + width - 6} ${y + 6}`, stroke: css("--muted"), "stroke-width": 1.5 }, g);
        if (look.through) svg("path", { d: `M${x - 4} ${y + height / 2}H${x + width + 4}`, stroke: css("--muted"), "stroke-width": 1.2,
                                        "marker-end": null, "stroke-dasharray": "2 2" }, g);
    }

    /** In the editor, a job disabled here looks as it will in a run. */
    function lookOf(item) {
        if (item.status) return item.status;
        return { STOP: "DISABLED", PASS_THROUGH: "BYPASSED" }[item.disabledHere] || null;
    }

    function drawBox(layer, item, at, model, diagram, prefix) {
        const g = svg("g", { class: "wf-box" + (item.outside ? " wf-outside" : ""), "data-id": item.id, "data-name": item.name,
                             "data-status": item.status || null, "data-disabled-here": item.disabledHere || null,
                             "data-outside": item.outside || null, "data-href": item.href || null, "data-owner": item.owner || null,
                             "data-shared": item.shared ? "true" : null,
                             cursor: "pointer" }, layer);
        const look = boxLook(lookOf(item), prefix, item.outside || false);
        if (item.outside || item.readonly) look.dash = "5 3";         // dashed: not part of this workflow
        drawShape(g, look, at.x, at.y, at.width, at.height, 6);
        if (matchesFind(item, diagram.find)) svg("rect", { class: "wf-found", x: at.x - 4, y: at.y - 4, width: at.width + 8, height: at.height + 8, rx: 9,
                                                            fill: "none", stroke: css("--accent"), "stroke-width": 2.5 }, g);
        if (item.changed) svg("rect", { class: "wf-changed", x: at.x - 3, y: at.y - 3, width: at.width + 6, height: at.height + 6, rx: 8,
                                        fill: "none", stroke: css("--warning"), "stroke-width": 2 }, g);
        if (isSelected(diagram, "item", item.id)) svg("rect", { class: "wf-selected", x: at.x - 2, y: at.y - 2, width: at.width + 4, height: at.height + 4, rx: 8,
                                                                fill: "none", stroke: css("--text"), "stroke-width": 1, "stroke-dasharray": "3 2" }, g);
        drawBoxText(g, at, model, look);
        if (item.frame && item.folded) {            // a frame folded to one box: its arrow opens it
            const toggle = svg("g", { class: "wf-fold", "data-fold": item.id, cursor: "pointer" }, g);
            svg("rect", { x: at.x + 2, y: at.y + 2, width: 26, height: 24, fill: "transparent" }, toggle);
            svg("text", { x: at.x + 6, y: at.y + 22, fill: css("--text"), style: "font: 700 20px system-ui, sans-serif" }, toggle).textContent = "▸";
            tooltip(toggle, "Open this frame (or double-click it)");
        }
        tooltip(g, item.status ? `${item.name}: ${item.statusText}` : item.name);
    }

    /** A frame that is open: a box around its items, with a header carrying its name, its fold arrow and its state. */
    function drawFrame(layer, item, at, diagram, prefix) {
        const g = svg("g", { class: "wf-box wf-frame" + (item.shared ? " wf-shared" : ""), "data-id": item.id, "data-name": item.name,
                             "data-status": item.status || null, "data-folded": "false", "data-href": item.href || null, cursor: "pointer" }, layer);
        const look = boxLook(lookOf(item), prefix);
        const body = svg("rect", { x: at.x, y: at.y, width: at.width, height: at.height, rx: 8, fill: look.fill.startsWith("url(") ? css("--panel-raised") : look.fill,
                                   "fill-opacity": item.status ? 0.08 : 0.25, stroke: look.stroke, "stroke-width": look.width + 0.5,
                                   "pointer-events": "none" }, g);
        if (look.dash) body.setAttribute("stroke-dasharray", look.dash);
        if (item.shared) body.setAttribute("stroke-dasharray", "5 3");               // another workflow, read only
        if (matchesFind(item, diagram.find)) svg("rect", { class: "wf-found", x: at.x - 4, y: at.y - 4, width: at.width + 8, height: at.height + 8, rx: 11,
                                                            fill: "none", stroke: css("--accent"), "stroke-width": 2.5, "pointer-events": "none" }, g);
        if (item.changed) svg("rect", { class: "wf-changed", x: at.x - 3, y: at.y - 3, width: at.width + 6, height: at.height + 6, rx: 10,
                                        fill: "none", stroke: css("--warning"), "stroke-width": 2, "pointer-events": "none" }, g);
        if (isSelected(diagram, "item", item.id)) svg("rect", { class: "wf-selected", x: at.x - 2, y: at.y - 2, width: at.width + 4, height: at.height + 4, rx: 10,
                                                                fill: "none", stroke: css("--text"), "stroke-width": 1, "stroke-dasharray": "3 2", "pointer-events": "none" }, g);
        svg("rect", { class: "wf-frame-head", x: at.x, y: at.y, width: at.width, height: FRAME_HEAD, rx: 8, fill: css("--panel-raised"),
                      "fill-opacity": 0.9, stroke: "none" }, g);
        const toggle = svg("g", { class: "wf-fold", "data-fold": item.id, cursor: "pointer" }, g);
        svg("rect", { x: at.x + 3, y: at.y + 3, width: 26, height: 28, fill: "transparent" }, toggle);
        svg("text", { x: at.x + 7, y: at.y + 24, fill: css("--text"), style: "font: 700 20px system-ui, sans-serif" }, toggle).textContent = "▾";
        tooltip(toggle, "Fold this frame into one box (or double-click it)");
        icon(g, "frame", at.x + 32, at.y + 10, css("--muted"), "A workflow embedded in this one: it belongs to this workflow");
        // The sub-title goes beside the name when the frame is wide enough anyway, and under it when it would stretch the frame
        const note = subLine(item), nameWidth = textWidth(item.name || "(no name yet)", NAME_FONT);
        const beside = !note || at.width >= 50 + nameWidth + 24 + textWidth(note, SMALL_FONT) + PAD;
        svg("text", { x: at.x + 50, y: at.y + (beside ? 22 : 15), fill: css("--text"), style: `font: ${NAME_FONT}`, "pointer-events": "none" }, g).textContent = item.name || "(no name yet)";
        if (note) svg("text", { class: "wf-sub", x: beside ? at.x + at.width - PAD : at.x + 50, y: at.y + (beside ? 22 : 29),
                                "text-anchor": beside ? "end" : "start", fill: css("--muted"),
                                style: `font: ${SMALL_FONT}`, "pointer-events": "none" }, g).textContent = note;
        tooltip(g, item.status ? `${item.name}: ${item.statusText}` : item.name);
    }

    function drawBoxText(g, at, model, look) {
        let y = at.y + PAD;
        if (model.icons.length || model.indent) {
            model.icons.forEach(([name, words], i) => icon(g, name, at.x + PAD + model.indent + i * (ICON + 4), y, css("--muted"), words));
            if (model.external) {
                svg("text", { x: at.x + PAD + model.indent + model.icons.length * (ICON + 4), y: y + 11, fill: look.stroke, style: `font: ${EXTERNAL_FONT}; letter-spacing: 0.5px` }, g).textContent = model.external;
            }
            y += ICON + 4;
        }
        // At the right of the first line, so they add no height: the Reactions icon, then ×2 at the edge
        let right = at.x + model.width - PAD;
        if (model.attempts) {
            const mark = svg("text", { class: "wf-attempts", x: right, y: y + 12, "text-anchor": "end", fill: css("--muted"),
                                       style: `font: ${SMALL_FONT}; font-weight: 700` }, g);
            mark.textContent = model.attempts[0];
            tooltip(mark, model.attempts[1]);
            right -= textWidth(model.attempts[0], SMALL_FONT) + 4;
        }
        if (model.reactions) icon(g, "reactions", right - ICON, y, css("--muted"), model.reactions[1]);
        for (const line of model.lines) {
            svg("text", { x: at.x + PAD, y: y + 12, fill: look.muted ? css("--muted") : css("--text"), style: `font: ${NAME_FONT}` }, g).textContent = line;
            y += LINE;
        }
        for (const line of model.sub ? wrapName(model.sub, SUB_MAX) : []) {
            svg("text", { class: "wf-sub", x: at.x + PAD, y: y + 12, fill: css("--muted"), style: `font: ${SMALL_FONT}` }, g).textContent = line;
            y += SUB_LINE;
        }
    }

    function matchesFind(item, find) {
        return Boolean(find) && item.name.toLowerCase().includes(find.toLowerCase());
    }

    function isSelected(diagram, kind, id) {
        return Boolean(diagram.selected) && diagram.selected.kind === kind && diagram.selected.id === id;
    }

    // ---------- Lines ----------

    /** The point this far back from a line's end, along the line drawn through these points. */
    function pointBack(points, distance) {
        let left = distance;
        for (let i = points.length - 1; i > 0; i--) {
            const a = points[i - 1], b = points[i], length = Math.hypot(b.x - a.x, b.y - a.y);
            if (left <= length) {
                const t = length ? left / length : 0;
                return { x: b.x + (a.x - b.x) * t, y: b.y + (a.y - b.y) * t };
            }
            left -= length;
        }
        return points[0];
    }

    /**
     * While editing: an x on the line, about the size of an arrowhead, just before the arrowhead with a small gap,
     * shown while the line is pointed at or selected; it removes the line. width is the line's stroke width.
     */
    function drawRemover(g, points, words, selected, width) {
        const r = 5, arm = 2.2, gap = 3;
        const at = pointBack(points, ARROW_LENGTH * width + gap + r);
        const x = svg("g", { class: "wf-line-remove", role: "button", "aria-label": "Remove this line", opacity: selected ? 1 : 0 }, g);
        svg("circle", { cx: at.x, cy: at.y, r, fill: css("--page"), stroke: css("--failure"), "stroke-width": 1.2 }, x);
        svg("path", { d: `M${at.x - arm} ${at.y - arm} L${at.x + arm} ${at.y + arm} M${at.x + arm} ${at.y - arm} L${at.x - arm} ${at.y + arm}`,
                      stroke: css("--failure"), "stroke-width": 1.4 }, x);
        tooltip(x, `Remove this line: ${words.replace(" waits until ", " stops waiting until ")}`);
        g.addEventListener("pointerenter", () => x.setAttribute("opacity", 1));
        g.addEventListener("pointerleave", () => x.setAttribute("opacity", selected ? 1 : 0));
    }

    /** A line an operator ignored for the latest restart: two short strokes across it, about halfway along. */
    function drawStrike(g, points, words) {
        let length = 0;
        for (let i = 1; i < points.length; i++) length += Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
        const at = pointBack(points, length / 2);
        const strike = svg("g", { class: "wf-line-ignored" }, g);
        for (const shift of [-2.5, 2.5]) {
            svg("path", { d: `M${at.x + shift - 4} ${at.y + 6}L${at.x + shift + 4} ${at.y - 6}`, stroke: css("--failure"), "stroke-width": 1.6 }, strike);
        }
        tooltip(strike, words);
    }

    function drawLine(layer, edge, line, words, diagram, prefix) {
        const style = lineStyle(line.test);
        const selected = isSelected(diagram, "line", line.id);
        const g = svg("g", { class: "wf-line" + (selected ? " selected" : ""), "data-line": line.id, "data-test": line.test, cursor: "pointer" }, layer);
        let last = null;           // the part of the line that ends at the arrowhead
        for (const section of edge.sections || []) {
            const points = [section.startPoint, ...(section.bendPoints || []), section.endPoint];
            const d = points.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ");
            svg("path", { d, fill: "none", stroke: style.color, "stroke-width": selected ? 3 : 1.6, "stroke-dasharray": style.dash,
                          "marker-end": `url(#${prefix}a-${TESTS.includes(line.test) ? line.test : "OTHER"})` }, g);
            // A wide, invisible copy of the line, so it is easy to point at and to click
            const area = svg("path", { class: "wf-hit", d, fill: "none", stroke: "transparent", "stroke-width": 10, "pointer-events": "stroke" }, g);
            tooltip(area, diagram.editing && line.test !== "RULE" ? `${words}. The x on the line removes it.` : words);
            last = points;
        }
        for (const label of edge.labels || []) {
            svg("rect", { x: label.x, y: label.y, width: label.width, height: label.height, rx: 3, fill: css("--page"), stroke: style.color }, g);
            svg("text", { x: label.x + 5, y: label.y + 12, fill: style.color, style: `font: ${SMALL_FONT}` }, g).textContent = label.text;
            tooltip(g.lastChild, words);
        }
        if (line.ignored && last) drawStrike(g, last, words);
        if (diagram.editing && last && line.test !== "RULE") drawRemover(g, last, words, selected, selected ? 3 : 1.6);
    }

    /**
     * Rerun from...: an arc from the job whose Reaction it is back to the job it reruns from, above the boxes
     * (left of them, top to bottom), dash-dot in the muted colour, its label marked ↺ (docs/WORKFLOWS.md).
     */
    function drawRerun(layer, rerun, from, to, direction, prefix) {
        const across = direction === "RIGHT";
        const start = across ? { x: from.x + from.width / 2, y: from.y } : { x: from.x, y: from.y + from.height / 2 };
        const end = across ? { x: to.x + to.width / 2, y: to.y } : { x: to.x, y: to.y + to.height / 2 };
        const lift = 26 + Math.abs(across ? start.x - end.x : start.y - end.y) * 0.12;
        const control = across ? `${(start.x + end.x) / 2} ${Math.min(start.y, end.y) - lift}`
                               : `${Math.min(start.x, end.x) - lift} ${(start.y + end.y) / 2}`;
        const g = svg("g", { class: "wf-rerun", "data-from": rerun.from, "data-to": rerun.to }, layer);
        svg("path", { d: `M${start.x} ${start.y}Q${control} ${end.x} ${end.y}`, fill: "none", stroke: css("--muted"),
                      "stroke-width": 1.6, "stroke-dasharray": "8 3 2 3", "marker-end": `url(#${prefix}a-RERUN)` }, g);
        const [cx, cy] = control.split(" ").map(Number);
        const mid = { x: (start.x + 2 * cx + end.x) / 4, y: (start.y + 2 * cy + end.y) / 4 };
        const label = "↺ rerun";
        const width = textWidth(label, SMALL_FONT) + 10;
        svg("rect", { x: mid.x - width / 2, y: mid.y - 8, width, height: 16, rx: 3, fill: css("--page"), stroke: css("--muted") }, g);
        svg("text", { x: mid.x, y: mid.y + 4, "text-anchor": "middle", fill: css("--muted"), style: `font: ${SMALL_FONT}` }, g).textContent = label;
        tooltip(g, rerun.words);
    }

    /** "ANY" where lines enter a job that needs only one of them. */
    function drawAnyMarker(layer, at, direction) {
        const across = direction === "RIGHT";
        const x = across ? at.x - 30 : at.x + at.width / 2 - 14, y = across ? at.y + at.height / 2 - 8 : at.y - 26;
        const g = svg("g", { class: "wf-any" }, layer);
        svg("rect", { x, y, width: 28, height: 16, rx: 8, fill: css("--page"), stroke: css("--text") }, g);
        svg("text", { x: x + 14, y: y + 12, "text-anchor": "middle", fill: css("--text"), style: `font: ${SMALL_FONT}; font-weight: 700` }, g).textContent = "ANY";
        tooltip(g, "Any: starts when any one of the lines into it is satisfied, not all of them");
    }

    // ---------- Putting a drawing together ----------

    /** Every box of the laid-out graph with its place on the whole drawing (elkjs gives each relative to its frame). */
    function placed(node, ox = 0, oy = 0, into = []) {
        for (const child of node.children || []) {
            const at = { ...child, x: ox + child.x, y: oy + child.y };
            into.push(at);
            placed(child, at.x, at.y, into);
        }
        return into;
    }

    /**
     * Every line of the laid-out graph with its points on the whole drawing. elkjs gives a line's points relative to
     * the frame that holds both its ends (its "container", the drawing itself when none), wherever it lists the line.
     */
    function placedEdges(root, nodes) {
        const origin = new Map(nodes.map(node => [node.id, node]));
        const found = [];
        const collect = node => { found.push(...(node.edges || [])); (node.children || []).forEach(collect); };
        collect(root);
        return found.map(edge => {
            const at = origin.get(edge.container) || { x: 0, y: 0 };
            const move = p => ({ x: p.x + at.x, y: p.y + at.y });
            return { ...edge,
                     sections: (edge.sections || []).map(sec => ({ ...sec, startPoint: move(sec.startPoint), endPoint: move(sec.endPoint),
                                                                   bendPoints: (sec.bendPoints || []).map(move) })),
                     labels: (edge.labels || []).map(l => ({ ...l, x: l.x + at.x, y: l.y + at.y })) };
        });
    }

    function picture(result, models, diagram, prefix) {
        const zoom = diagram.zoom;
        const root = svg("svg", { width: result.width * zoom, height: result.height * zoom, viewBox: `0 0 ${result.width} ${result.height}`,
                                  role: "img", "aria-label": "Workflow diagram" });
        defs(root, prefix);
        const frames = svg("g", {}, root), lines = svg("g", {}, root), boxes = svg("g", {}, root), over = svg("g", {}, root);
        const byId = new Map(diagram.items.map(item => [item.id, item]));
        const names = new Map(diagram.items.map(item => [item.id, item.name || "(no name yet)"]));
        const linesById = new Map(diagram.lines.map(line => [line.id, line]));
        const nodes = placed(result);
        for (const node of nodes) {
            const item = byId.get(node.id);
            if (item.frame && !item.folded) drawFrame(frames, item, node, diagram, prefix);
            else drawBox(boxes, item, node, models.get(node.id), diagram, prefix);
        }
        for (const edge of placedEdges(result, nodes)) {
            const line = linesById.get(edge.id);
            drawLine(lines, edge, line, lineWords(line, names), diagram, prefix);
        }
        for (const node of nodes) {
            const item = byId.get(node.id);
            const entering = diagram.lines.filter(line => line.to === item.id).length;
            if (item.join === "ANY" && entering > 1) drawAnyMarker(over, node, diagram.direction);
        }
        const at = new Map(nodes.map(node => [node.id, node]));
        for (const rerun of diagram.reruns || []) {
            if (at.has(rerun.from) && at.has(rerun.to)) drawRerun(over, rerun, at.get(rerun.from), at.get(rerun.to), diagram.direction, prefix);
        }
        return root;
    }

    function fitZoom(canvas, width) {
        return Math.max(0.3, Math.min(1, (canvas.clientWidth - 4) / width));
    }

    /** Lays the workflow out and draws it in the canvas; resolves to the zoom used. */
    async function draw(canvas, diagram, handlers) {
        const mine = (canvas.wfDraws || 0) + 1;      // a later drawing of the same canvas wins
        canvas.wfDraws = mine;
        const prefix = `${canvas.id || "wf"}-`;
        const models = new Map();
        const result = await elk.layout(elkGraph(diagram, models));
        if (mine !== canvas.wfDraws) return null;
        const zoom = diagram.zoom === "fit" ? fitZoom(canvas, result.width) : diagram.zoom;
        canvas.replaceChildren(picture(result, models, { ...diagram, zoom }, prefix));
        listen(canvas, handlers, diagram.editing);
        return zoom;
    }

    // ---------- Clicking, and dragging from box to box ----------

    /** Wires the drawing's clicks and drags to the page; done again for each drawing, as the old one is gone. */
    function listen(canvas, handlers, editing) {
        const root = canvas.querySelector("svg");
        let press = null;           // { id, x, y, line }: a press on a box that may become a drag
        root.addEventListener("pointerdown", event => {
            const box = event.target.closest(".wf-box");
            if (!box || !editing || event.button !== 0 || box.classList.contains("wf-outside")) return;
            press = { id: box.dataset.id, x: event.clientX, y: event.clientY, line: null };
        });
        root.addEventListener("pointermove", event => {
            if (!press) return;
            if (!press.line && Math.hypot(event.clientX - press.x, event.clientY - press.y) < DRAG_START) return;
            if (!press.line) {
                press.line = startDragLine(root, press.id);
                root.setPointerCapture(event.pointerId);
            }
            moveDragLine(root, press.line, event);
        });
        root.addEventListener("pointerup", event => {
            if (!press) return;
            const from = press.id, dragged = Boolean(press.line);
            if (press.line) press.line.remove();
            press = null;
            if (!dragged) return;              // a plain click: the click handler below selects
            root.releasePointerCapture(event.pointerId);
            canvas.wfDragEnded = Date.now();   // the click that follows a drag is not a click
            const target = boxAt(event.clientX, event.clientY);
            if (target && target !== from) handlers.connect(from, target);
        });
        root.addEventListener("click", event => onClick(canvas, event, handlers));
        root.addEventListener("dblclick", event => {            // a frame, or the box it is folded into, opens or folds
            const box = event.target.closest(".wf-frame, .wf-box");
            if (box && handlers.fold && (box.classList.contains("wf-frame") || box.querySelector(".wf-fold"))) handlers.fold(box.dataset.id);
        });
        // The canvas around the drawing (right of it, below it) is empty space too: a click there deselects.
        // Wired once per canvas; each drawing hands it its own handlers.
        canvas.wfHandlers = handlers;
        if (!canvas.wfBackgroundWired) {
            canvas.wfBackgroundWired = true;
            canvas.addEventListener("click", event => {
                if (event.target === canvas && Date.now() - (canvas.wfDragEnded || 0) >= 400) canvas.wfHandlers.select(null, null);
            });
        }
    }

    function onClick(canvas, event, handlers) {
        if (Date.now() - (canvas.wfDragEnded || 0) < 400) return;
        const line = event.target.closest(".wf-line");
        const fold = event.target.closest(".wf-fold");
        if (fold && handlers.fold) return handlers.fold(fold.dataset.fold);
        if (line && event.target.closest(".wf-line-remove")) return handlers.remove(line.dataset.line);
        const box = event.target.closest(".wf-box");
        if (line) handlers.select("line", line.dataset.line);
        else if (box && box.dataset.href && handlers.open) handlers.open(box.dataset.href);
        else if (box && box.dataset.owner) handlers.select("item", box.dataset.owner);
        else if (box) handlers.select("item", box.dataset.id);
        else handlers.select(null, null);
    }

    function boxAt(x, y) {
        const hit = document.elementsFromPoint(x, y).find(node => node.closest && node.closest(".wf-box"));
        return hit ? hit.closest(".wf-box").dataset.id : null;
    }

    function startDragLine(root, fromId) {
        const box = root.querySelector(`.wf-box[data-id="${CSS.escape(fromId)}"] rect`);
        const x = Number(box.getAttribute("x")) + Number(box.getAttribute("width")) / 2;
        const y = Number(box.getAttribute("y")) + Number(box.getAttribute("height")) / 2;
        return svg("path", { class: "wf-drag-line", "data-x": x, "data-y": y, d: `M${x} ${y}`, fill: "none", stroke: css("--success"),
                             "stroke-width": 2, "stroke-dasharray": "4 3", "pointer-events": "none" }, root);
    }

    function moveDragLine(root, path, event) {
        const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(root.getScreenCTM().inverse());
        path.setAttribute("d", `M${path.dataset.x} ${path.dataset.y}L${point.x} ${point.y}`);
    }

    // ---------- The key ----------

    function keySample(kind, value, prefix) {
        const s = svg("svg", { width: 70, height: 22, "aria-hidden": "true" });
        defs(s, prefix);
        if (kind === "line") {
            const style = lineStyle(value);
            svg("path", { d: "M4 11H62", stroke: style.color, "stroke-width": 1.6, "stroke-dasharray": style.dash, "marker-end": `url(#${prefix}a-${value})` }, s);
        } else if (kind === "box") {
            drawShape(s, boxLook(value, prefix), 4, 3, 62, 16, 4);
        } else {
            icon(s, value, 28, 4, css("--muted"), null);
        }
        return s;
    }

    /** Fills an element with what lines, box states and markers mean. */
    function key(element) {
        element.replaceChildren();
        const row = (sample, words) => {
            const div = document.createElement("div");
            div.className = "item";
            div.append(sample, Object.assign(document.createElement("span"), { textContent: words }));
            element.append(div);
        };
        TESTS.slice(0, 5).forEach((test, i) => row(keySample("line", test, `key-l${i}-`), `Line: waits until the job before it ${lineStyle(test).words}`));
        row(keySample("line", "FILES", "key-l5-"), "Line from files: the job waits until they have arrived and are old enough");
        row(keySample("line", "TIME", "key-l6-"), "Line from a time: the job waits until the condition on the time is true");
        row(keySample("line", "NEEDED", "key-l7-"), "Line to a job elsewhere: it waits for this job");
        const states = { PENDING: "Not started yet", WAITING: "Waiting on a prerequisite", RUNNING: "Running", SUCCESS: "Succeeded",
                         FAILED: "Failed", NOT_RUN: "Not run: its prerequisites can't be met, or the run was cancelled",
                         DISABLED: "Disabled (also: disabled here, to stop)", BYPASSED: "Bypassed: disabled here to pass through",
                         SKIPPED: "Skipped by a Reaction" };
        Object.entries(states).forEach(([status, words], i) => row(keySample("box", status, `key-b${i}-`), `In a run: ${words}`));
        const rerun = svg("svg", { width: 70, height: 22, "aria-hidden": "true" });
        defs(rerun, "key-r-");
        svg("path", { d: "M62 18Q33 -6 6 18", fill: "none", stroke: css("--muted"), "stroke-width": 1.6, "stroke-dasharray": "8 3 2 3",
                      "marker-end": "url(#key-r-a-RERUN)" }, rerun);
        row(rerun, "↺ Rerun from...: a Reaction that runs an earlier job, and those between, again");
        row(keySample("icon", "workflow", "key-i1-"), "A workflow, used as one job");
        row(keySample("icon", "frame", "key-i0-"), "A frame: a workflow embedded in this one, with its jobs inside. ▾ folds it into one box, ▸ opens it (or double-click). A line into a folded frame ends on it");
        const outsideBox = svg("svg", { width: 70, height: 22, "aria-hidden": "true" });
        drawShape(outsideBox, { ...boxLook(null, "key-o-", "JOB"), dash: "5 3" }, 4, 3, 62, 16, 4);
        const nonJobBox = svg("svg", { width: 70, height: 22, "aria-hidden": "true" });
        drawShape(nonJobBox, { ...boxLook(null, "key-n-", "FILES"), dash: "5 3" }, 4, 3, 62, 16, 4);
        row(outsideBox, "Shaded, dashed box marked EXTERNAL (or, with the toolbar choices off, a small icon in the header of the box it applies to; point at it to read it): outside this workflow. On the left, what a job waits for there (a job elsewhere, files, a time); on the right, jobs elsewhere that wait for it. Click one to open it");
        row(nonJobBox, "Shaded blue, marked FILES or TIME: not a job. Something a job waits for that runs nothing (files, the time)");
        row(keySample("icon", "needed", "key-i9-"), "Another workflow's job waits for this job (shown as an icon when external references are hidden)");
        row(keySample("icon", "files", "key-i7-"), "Files at an endpoint: they count once each has been left alone long enough");
        row(keySample("icon", "clock", "key-i8-"), "A condition on the time (a clock or, for a date or weekday, a calendar)");
        row(keySample("icon", "disabled", "key-i2-"), "Its job is disabled, or it is disabled here");
        row(keySample("icon", "pass", "key-i3-"), "Disabled here to pass through: counts as succeeded without running");
        row(keySample("icon", "reactions", "key-i4-"), "Has Reactions: what happens after it ends");
        row(keySample("icon", "attempts:2", "key-i10-"), "Run more than once in this run (×2 is a second attempt, after a Rerun)");
        row(keySample("icon", "changed", "key-i6-"), "Outlined and marked so while editing: changed since the workflow was last saved");
        row(keySample("icon", "rule", "key-i5-"), "Starts by a Custom rule; point at it to read the rule. Dotted lines come from the jobs the rule names");
        row(Object.assign(document.createElement("span"), { className: "wf-any-sample", textContent: "ANY" }),
            "Starts when any one of the lines into it is satisfied. Point at any line or marker to read what it means.");
    }

    return { draw, key };
})();

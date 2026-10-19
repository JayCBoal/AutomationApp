"use strict";
/*
 * The condition box (docs/WORKFLOWS_PHASE4.md): one box wherever a condition is written, a
 * workflow job's Custom rule, a workflow's Succeeds when, and an If, Else If or While in a job.
 *
 *   - Builder | Text: groups, each "Match all (AND) / any (OR) of the following", holding
 *     conditions (name, output, comparison, value) and groups inside it, to any depth; each
 *     group inside another is written in brackets, and the text beneath is what runs. Or the
 *     text itself. Back to the builder only while the text is in a shape it can show
 *     ("edited as text" otherwise).
 *   - Names and outputs: what can be used, each with what it is, inserted by a click.
 *   - In a workflow, the condition is checked as it is typed (POST /api/v1/conditions/check),
 *     and Explain works it out with one of the workflow's past runs, part by part
 *     (POST /api/v1/conditions/explain). In a job, the editor's preview checks it already.
 *
 * A page puts it where it has
 *     <div data-condition-box data-model="item.rule" data-context="ruleContext(item)"></div>
 * (data-model: where the condition is kept, as text; data-context: an expression giving
 *  { kind: "workflow", names, outputs, workflowKey, runs } or { kind: "job", steps: [{ name, outputs }], variables }),
 * and calls AutoApp.fillConditionBoxes() from a script at the end of its body, before Alpine
 * starts. AutoApp.loadConditionOutputs() fetches what every job in a workflow offers.
 */
(() => {
    const COMPARISONS = ["=", "<>", "<", "<=", ">", ">=", "LIKE"];
    const COMPARISON_WORDS = { "=": "is", "<>": "is not", "<": "is less than", "<=": "is at most", ">": "is more than",
                               ">=": "is at least", "LIKE": "is like" };
    const TOKEN = /\s+|'(?:[^']|'')*'|"(?:[^"]|"")*"|[%$]\{[^}]*\}|\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*|<>|!=|<=|>=|==|=|<|>|\(|\)|./g;
    const ANSWER = { true: "holds", false: "does not hold", null: "unknown" };
    let nextUid = 1;
    let outputs = [];           // what every job in a workflow offers, from /api/v1/conditions/outputs

    const BOX = `
<div class="cond-box" x-data="AutoApp.conditionBox()" x-init="start($MODEL)" x-effect="watch($MODEL, $CONTEXT)">
    <template x-if="!editing">
        <code class="cond-text" x-text="$MODEL || '(not written yet)'"></code>
    </template>
    <template x-if="editing">
        <div>
            <div class="cond-tools">
                <span class="group" role="group" aria-label="How it is written">
                    <button type="button" class="cond-builder-tab" :class="{ on: mode === 'builder' }" @click="toBuilder($MODEL, $CONTEXT)">Builder</button>
                    <button type="button" class="cond-text-tab" :class="{ on: mode === 'text' }" @click="mode = 'text'">Text</button>
                </span>
                <button type="button" class="link small cond-help-toggle" @click="help = !help"
                        x-text="help ? 'Hide names and outputs' : 'Names and outputs'"></button>
                <span class="muted small cond-as-text" x-show="asText" x-text="asText"></span>
            </div>
            <textarea class="code cond-input" x-show="mode === 'text'" rows="2" x-model="$MODEL" x-ref="text"
                      placeholder="For example %{Load.Succeeded} AND %{Load.FileCount} > 0"></textarea>
            <div class="cond-builder" x-show="mode === 'builder'" @input="$MODEL = written()" @change="$MODEL = written()">
                <template x-for="entry in entries()" :key="entry.key">
                    <div class="cond-entry" :class="'cond-line-' + entry.kind" :style="guides(entry)">
                        <template x-if="entry.kind === 'head'">
                            <div class="cond-head">Match
                                <select class="cond-group-join" x-model="entry.group.join" aria-label="All or any">
                                    <option value="AND">all</option><option value="OR">any</option>
                                </select>
                                of the following
                                <span class="muted small" x-text="entry.group.join === 'AND' ? '(AND)' : '(OR)'"></span>
                                <button type="button" class="link small cond-remove-group" x-show="entry.parent"
                                        @click="removeItem(entry.parent, entry.group); $MODEL = written()">Remove group</button>
                            </div>
                        </template>
                        <template x-if="entry.kind === 'row'">
                            <div class="cond-row wf-row">
                                <select class="cond-subject" x-model="entry.row.subject" @change="fitOperator(entry.row, $CONTEXT)">
                                    <option value="">(choose)</option>
                                    <template x-for="s in subjects($CONTEXT)" :key="s.value">
                                        <option :value="s.value" x-text="s.label" :selected="s.value === entry.row.subject"></option>
                                    </template>
                                    <option value="$VAR" :selected="entry.row.subject === '$VAR'">A variable…</option>
                                </select>
                                <input type="text" class="cond-variable" x-show="entry.row.subject === '$VAR'" x-model="entry.row.variable"
                                       placeholder="Its name" style="max-width: 140px">
                                <select class="cond-op" x-model="entry.row.op">
                                    <template x-for="op in operators(entry.row, $CONTEXT)" :key="op.value">
                                        <option :value="op.value" x-text="op.label" :selected="op.value === entry.row.op"></option>
                                    </template>
                                </select>
                                <input type="text" class="cond-value" x-show="!['TRUE', 'FALSE'].includes(entry.row.op)" x-model="entry.row.value"
                                       placeholder="A value" style="max-width: 160px">
                                <button type="button" class="link small cond-remove-row" @click="removeItem(entry.parent, entry.row); $MODEL = written()">Remove</button>
                            </div>
                        </template>
                        <template x-if="entry.kind === 'foot'">
                            <div class="cond-foot">
                                <button type="button" class="link small cond-add-row" @click="addRow(entry.group); $MODEL = written()">+ Condition</button>
                                <button type="button" class="link small cond-add-group" @click="addGroup(entry.group); $MODEL = written()"
                                        title="A group inside this one, with its own all or any: written in brackets">+ Group</button>
                            </div>
                        </template>
                    </div>
                </template>
                <div class="muted small cond-written-line">Written: <code class="cond-written" x-text="$MODEL || '(nothing yet)'"></code></div>
            </div>
            <ul class="problems small cond-problems" x-show="checked.problems.length">
                <template x-for="p in checked.problems"><li x-text="p"></li></template>
            </ul>
            <ul class="warnings small cond-warnings" x-show="checked.warnings.length">
                <template x-for="w in checked.warnings"><li class="message warning small" x-text="w"></li></template>
            </ul>
            <div class="cond-help small" x-show="help">
                <template x-for="name in helpNames($CONTEXT)" :key="name.label">
                    <div class="cond-help-name"><strong x-text="name.label"></strong>
                        <template x-for="o in name.outputs" :key="o.name">
                            <button type="button" class="link small cond-insert" :title="o.description"
                                    @click="$MODEL = insert($MODEL, name.prefix + o.name + '}')" x-text="o.name"></button>
                        </template>
                    </div>
                </template>
                <p class="muted">Write it as a SQL WHERE clause: AND, OR, NOT, brackets; =, &lt;&gt;, &lt;, &gt;, LIKE,
                    IN (...), BETWEEN ... AND ...; text in single quotes; variables as \${Name}.
                    <span x-show="($CONTEXT).kind === 'workflow'">A job that has not ended yet counts as unknown: a rule
                        holds as soon as it is true, whatever the jobs still running do, and fails as soon as it is false.
                        Point at an output to see what it is.</span></p>
            </div>
            <div class="cond-explain" x-show="(($CONTEXT).runs || []).length">
                <label class="small">Explain with the run
                    <select class="cond-explain-run" x-model="runId">
                        <template x-for="run in ($CONTEXT).runs || []" :key="run.run_id">
                            <option :value="run.run_id" x-text="run.label"></option>
                        </template>
                    </select></label>
                <button type="button" class="link small cond-explain-button" @click="explainNow($MODEL, $CONTEXT)">Explain</button>
                <div x-show="explained" class="cond-explained">
                    <ul class="cond-tree small">
                        <template x-for="(row, i) in explained ? explained.rows : []" :key="i">
                            <li :style="{ paddingLeft: (row.depth * 18) + 'px' }" :class="'answer-' + row.answer">
                                <span class="cond-answer" x-text="row.words"></span> <code x-text="row.text"></code>
                            </li>
                        </template>
                    </ul>
                    <div class="muted small cond-values" x-text="explained ? explained.values : ''"></div>
                </div>
            </div>
        </div>
    </template>
</div>`;

    function fillConditionBoxes(root = document) {
        for (const slot of root.querySelectorAll("[data-condition-box]")) {
            const html = BOX.replaceAll("$MODEL", slot.dataset.model).replaceAll("$CONTEXT", slot.dataset.context);
            const holder = document.createElement("template");
            holder.innerHTML = html;
            slot.replaceWith(holder.content.cloneNode(true));
        }
        for (const template of root.querySelectorAll("template")) fillConditionBoxes(template.content);
    }

    async function loadConditionOutputs() {
        if (!outputs.length) outputs = await AutoApp.get("/conditions/outputs");
        return outputs;
    }

    // ---------- Reading and writing conditions the builder can show ----------

    const tokensOf = text => (text.match(TOKEN) || []).filter(t => !/^\s+$/.test(t));
    const isRef = t => /^[%$]\{[^}]*\}$/.test(t);
    const isNumber = text => /^-?\d+(\.\d+)?$/.test(String(text).trim());
    const unquote = t => t.slice(1, -1).replaceAll(t[0] + t[0], t[0]);

    /** The pieces between each joiner (AND or OR) outside brackets. */
    function split(tokens, word) {
        const pieces = [[]];
        let depth = 0;
        for (const t of tokens) {
            if (t === "(") depth++;
            if (t === ")") depth--;
            if (depth === 0 && t.toUpperCase() === word) { pieces.push([]); continue; }
            pieces[pieces.length - 1].push(t);
        }
        return pieces;
    }

    function unwrap(tokens) {
        while (tokens.length > 1 && tokens[0] === "(" && tokens[tokens.length - 1] === ")") {
            let depth = 0, whole = true;
            tokens.forEach((t, i) => { depth += t === "(" ? 1 : t === ")" ? -1 : 0; if (depth === 0 && i < tokens.length - 1) whole = false; });
            if (!whole) break;
            tokens = tokens.slice(1, -1);
        }
        return tokens;
    }

    function subjectOf(ref) {
        return ref.startsWith("${") ? { subject: "$VAR", variable: ref.slice(2, -1) } : { subject: ref, variable: "" };
    }

    /** One row from its tokens, or null if it is not a shape a row can show. */
    function readRow(tokens) {
        if (tokens.length === 1 && isRef(tokens[0])) return { ...subjectOf(tokens[0]), op: "TRUE", value: "" };
        if (tokens.length === 2 && tokens[0].toUpperCase() === "NOT" && isRef(tokens[1])) return { ...subjectOf(tokens[1]), op: "FALSE", value: "" };
        if (tokens.length !== 3 || !isRef(tokens[0])) return null;
        const op = tokens[1].toUpperCase() === "LIKE" ? "LIKE" : { "!=": "<>", "==": "=" }[tokens[1]] || tokens[1];
        if (!COMPARISONS.includes(op)) return null;
        const value = tokens[2];
        if (/^['"]/.test(value)) return { ...subjectOf(tokens[0]), op, value: unquote(value) };
        return isNumber(value) ? { ...subjectOf(tokens[0]), op, value } : null;
    }

    const emptyRow = () => ({ type: "row", subject: "", variable: "", op: "TRUE", value: "" });

    /** A condition as a tree of groups (all: AND, any: OR) and rows, or null if a part is not a row the builder shows. */
    function readNode(tokens) {
        tokens = unwrap(tokens);
        for (const word of ["OR", "AND"]) {            // OR binds loosest, so it splits first
            const pieces = split(tokens, word);
            if (pieces.length > 1) {
                if (pieces.some(piece => !piece.length)) return null;
                const items = pieces.map(readNode);
                return items.every(Boolean) ? { type: "group", join: word, items } : null;
            }
        }
        const row = readRow(tokens);
        return row ? { type: "row", ...row } : null;
    }

    /** The builder's form of a condition, a group holding rows and groups, or null if the builder cannot show it. */
    function read(text) {
        const tokens = tokensOf(text || "");
        if (!tokens.length) return { type: "group", join: "AND", items: [emptyRow()] };
        const node = readNode(tokens);
        if (!node) return null;
        return node.type === "group" ? node : { type: "group", join: "AND", items: [node] };
    }

    function quoted(value) { return "'" + String(value).replaceAll("'", "''") + "'"; }

    function writeRow(row, kindOf) {
        const subject = row.subject === "$VAR" ? (row.variable.trim() ? "${" + row.variable.trim() + "}" : "") : row.subject;
        if (!subject) return "";
        if (row.op === "TRUE") return subject;
        if (row.op === "FALSE") return "NOT " + subject;
        const text = kindOf(row.subject) === "STRING" || row.op === "LIKE" || !isNumber(row.value);
        return `${subject} ${row.op} ${text ? quoted(row.value) : String(row.value).trim()}`;
    }

    /** A group as text: its parts joined by AND (all) or OR (any); a group inside another, of two parts or more, in brackets. */
    function write(node, kindOf, inside = false) {
        if (node.type === "row") return writeRow(node, kindOf);
        const parts = node.items.map(item => write(item, kindOf, true)).filter(Boolean);
        const text = parts.join(` ${node.join} `);
        return inside && parts.length > 1 ? `(${text})` : text;
    }

    /** Explain's tree as rows to list: each part with how deep it sits and its answer. */
    function explainRows(tree, depth = 0) {
        if (!tree) return [];
        const answer = tree.result === true ? "true" : tree.result === false ? "false" : "unknown";
        const words = ANSWER[tree.result === undefined ? null : tree.result];
        const row = { depth, text: tree.text, answer, words: tree.join ? `${words} (${tree.join === "AND" ? "all" : "any"} of):` : words + ":" };
        return [row, ...(tree.parts || []).flatMap(part => explainRows(part, depth + 1))];
    }

    function valuesWords(values) {
        const entries = Object.entries(values || {});
        return entries.length ? "Values: " + entries.map(([ref, v]) => `${ref} = ${v === null ? "unknown" : JSON.stringify(v)}`).join(", ") : "";
    }

    // ---------- The box's own component ----------

    function conditionBox() {
        let checkTimer = null, lastChecked = null;
        return {
            mode: "builder",
            builder: { type: "group", join: "AND", items: [] },
            help: false,
            asText: "",
            checked: { problems: [], warnings: [] },
            runId: "",
            explained: null,
            kinds: {},
            seen: "",           // the text as the box last wrote or read it: anything else came from outside

            start(text) {
                this.seen = text || "";
                const form = read(text);
                if (form) this.builder = this.withUids(form);
                else { this.mode = "text"; this.asText = "Edited as text: the builder cannot show this condition."; }
            },

            withUids(node) {
                return node.type === "row" ? { uid: nextUid++, ...node }
                    : { uid: nextUid++, type: "group", join: node.join, items: node.items.map(item => this.withUids(item)) };
            },

            /** The builder as the lines it draws: each group's heading, its rows and groups, and its + buttons. */
            entries(group = this.builder, depth = 0, parent = null) {
                const list = [{ key: group.uid + "h", kind: "head", group, depth, parent }];
                for (const item of group.items) {
                    if (item.type === "row") list.push({ key: item.uid + "r", kind: "row", row: item, depth: depth + 1, parent: group });
                    else list.push(...this.entries(item, depth + 1, group));
                }
                list.push({ key: group.uid + "f", kind: "foot", group, depth: depth + 1, parent });
                return list;
            },

            /** A line's indent, and a vertical guide for each group it is inside, so each group reads as one block. */
            guides(entry) {
                const step = 22, lines = [];
                for (let d = 0; d < entry.depth; d++) lines.push(`linear-gradient(var(--accent), var(--accent)) ${d * step + 6}px 0 / 2px 100% no-repeat`);
                return { paddingLeft: (entry.depth * step) + "px", background: lines.join(", ") || "none" };
            },

            toBuilder(text, context) {
                const form = read(text);
                if (!form) { this.asText = "Edited as text: the builder cannot show this condition."; return; }
                this.subjects(context);
                this.builder = this.withUids(form);
                this.asText = "";
                this.mode = "builder";
            },

            written() {
                this.seen = write(this.builder, subject => this.kinds[subject]);
                return this.seen;
            },

            addRow(group) { group.items.push({ uid: nextUid++, ...emptyRow() }); },

            /** A group inside this one: the other of all and any, as that is why one is wanted, starting with one row. */
            addGroup(group) {
                group.items.push({ uid: nextUid++, type: "group", join: group.join === "AND" ? "OR" : "AND",
                                   items: [{ uid: nextUid++, ...emptyRow() }] });
            },

            /** Takes a row or group out of its group; a group left empty goes too, except the outermost. */
            removeItem(parent, item) {
                parent.items.splice(parent.items.indexOf(item), 1);
                const prune = group => {
                    group.items = group.items.filter(i => i.type === "row" || (prune(i), i.items.length));
                };
                prune(this.builder);
            },

            /** What a row can test: each job's (or step's) outputs, then the variables. */
            subjects(context) {
                const list = [];
                for (const name of this.helpNames(context)) {
                    for (const o of name.outputs) {
                        const value = name.prefix + o.name + "}";
                        this.kinds[value] = o.data_type;
                        list.push({ value, label: `${name.label} · ${o.name}` });
                    }
                }
                for (const v of context.variables || []) {
                    this.kinds["${" + v + "}"] = "STRING";
                }
                return list;
            },

            operators(row, context) {
                this.subjects(context);
                if (this.kinds[row.subject] === "BOOLEAN") return [{ value: "TRUE", label: "is true" }, { value: "FALSE", label: "is false" }];
                return COMPARISONS.map(op => ({ value: op, label: COMPARISON_WORDS[op] }));
            },

            fitOperator(row, context) {
                const offered = this.operators(row, context).map(o => o.value);
                if (!offered.includes(row.op)) row.op = offered[0];
            },

            /** For the list of names and outputs: each job (or step), its prefix and its outputs. */
            helpNames(context) {
                if (context.kind === "workflow") {
                    const offered = context.outputs || outputs;
                    return (context.names || []).filter(Boolean).map(name => ({ label: name, prefix: `%{${name}.`, outputs: offered }));
                }
                return (context.steps || []).filter(s => s.name).map(s => ({ label: s.name, prefix: `%{${s.name}.`, outputs: s.outputs }));
            },

            insert(text, piece) {
                const box = this.$refs.text;
                if (this.mode !== "text" || !box) return (text ? text + " " : "") + piece;
                const at = box.selectionStart ?? (text || "").length;
                return (text || "").slice(0, at) + piece + (text || "").slice(box.selectionEnd ?? at);
            },

            /** Checks a workflow condition as it changes, a moment after the typing stops. */
            watch(text, context) {
                if (this.mode === "builder" && (text || "") !== this.seen) {     // changed from outside the box
                    const form = read(text);
                    if (form) this.builder = this.withUids(form);
                    else { this.mode = "text"; this.asText = "Edited as text: the builder cannot show this condition."; }
                }
                this.seen = text || "";
                if (context.kind !== "workflow" || !this.editing) return;
                const request = JSON.stringify({ condition: text || "", names: (context.names || []).filter(Boolean),
                                                 workflow_key: context.workflowKey || null });
                if (request === lastChecked) return;
                clearTimeout(checkTimer);
                checkTimer = setTimeout(async () => {
                    lastChecked = request;
                    try {
                        this.checked = await AutoApp.send("POST", "/conditions/check", JSON.parse(request));
                    } catch (e) {
                        this.checked = { problems: [e.message], warnings: [] };
                    }
                }, 400);
            },

            async explainNow(text, context) {
                const runId = this.runId || ((context.runs || [])[0] || {}).run_id;
                if (!runId) return;
                try {
                    const result = await AutoApp.send("POST", "/conditions/explain", { condition: text || "", run_id: runId });
                    this.explained = { rows: explainRows(result.explain), values: valuesWords(result.values) };
                } catch (e) {
                    this.explained = { rows: [{ depth: 0, text: e.message, answer: "unknown", words: "Cannot explain:" }], values: "" };
                }
            },
        };
    }

    /** A Custom rule written from prerequisites, for a job switched to Custom rule: what it waited for, as a condition. */
    function ruleFrom(prerequisites, join) {
        const parts = prerequisites.filter(p => p.target).map(p => {
            if (p.test === "SUCCESS") return `%{${p.target}.Succeeded}`;
            if (p.test === "FAILED") return `%{${p.target}.Failed}`;
            if (p.test === "ENDED") return `%{${p.target}.Ended}`;
            const ref = `%{${p.target}.ReturnCode}`;
            const pieces = (p.return_codes || "").split(",").map(s => s.trim()).filter(Boolean).map(piece => {
                const range = piece.match(/^(\d+)\s*-\s*(\d+)$/);
                return range ? `${ref} BETWEEN ${range[1]} AND ${range[2]}` : `${ref} = ${piece}`;
            });
            return pieces.length > 1 ? `(${pieces.join(" OR ")})` : pieces[0] || `${ref} = 0`;
        });
        return parts.join(join === "ANY" ? " OR " : " AND ");
    }

    /** The jobs a condition names, in order, once each: %{Name.Output} -> Name. */
    function namedJobs(text) {
        const names = [];
        for (const match of String(text || "").matchAll(/%\{([^.}]+)[.}]/g)) if (!names.includes(match[1])) names.push(match[1]);
        return names;
    }

    /** The condition with %{Old...} renamed %{New...}. */
    function renameIn(text, oldName, newName) {
        if (!text || !oldName || oldName === newName) return text;
        const escaped = oldName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        return text.replace(new RegExp(`%\\{${escaped}(?=[.}])`, "g"), "%{" + newName);
    }

    Object.assign(AutoApp, { fillConditionBoxes, loadConditionOutputs, conditionBox, conditionOutputs: () => outputs,
                                    explainRows, valuesWords, ruleFrom, namedJobs, renameIn, readCondition: read });
})();

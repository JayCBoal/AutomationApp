"use strict";
/*
 * The Reactions box (docs/WORKFLOWS_PHASE3.md): what happens after a job ends, chosen by how
 * it ended. The same box on the job page (a job's own) and on the workflow page (the
 * workflow's own, and a use's that overrides its job's), so both editors work alike.
 *
 * A page puts it where it has
 *     <div data-reactions-box data-list="form.reactions" data-in-workflow="false"></div>
 * (data-list: where the page keeps the list; data-in-workflow: whether the actions that need a
 * workflow around the job are offered; data-targets: for a use, the jobs Rerun from... and
 * Skip... can name, as an expression giving names), and calls AutoApp.fillReactionBoxes() from a
 * script at the end of its body, before Alpine starts. Its component includes
 * AutoApp.reactionEditing(), keeps the list in the form with reactionsForm(), and sends it with
 * reactionsPayload().
 */
(() => {
    const WHEN = { SUCCESS: "it succeeds", FAILED: "it fails", ENDED: "it ends, whatever happened", RC: "its return code is",
                   NOT_STARTED_BY: "it has not started by", NOT_ENDED_BY: "it has not ended by", RUNS_LONGER_THAN: "it runs longer than" };
    const PLAIN_WHENS = ["SUCCESS", "FAILED", "ENDED", "RC"];
    const TIME_WHENS = ["NOT_STARTED_BY", "NOT_ENDED_BY", "RUNS_LONGER_THAN"];
    // How each time When can be given (docs/WORKFLOWS_PHASE8.md, proposal 2), and what the choice says
    const KINDS_FOR = { NOT_STARTED_BY: ["CLOCK", "AFTER_START", "AFTER_READY"], NOT_ENDED_BY: ["CLOCK", "AFTER_START", "AFTER_READY"],
                        RUNS_LONGER_THAN: ["LENGTH", "HISTORY"] };
    const KIND_WORDS = { CLOCK: "a time of day", AFTER_START: "minutes after the start", AFTER_READY: "minutes after it is ready",
                         LENGTH: "a length in minutes", HISTORY: "longer than usual" };
    const MINUTE_KINDS = ["AFTER_START", "AFTER_READY", "LENGTH"];
    const ACTIONS = {
        COUNT_AS_SUCCEEDED: "Count as succeeded", COUNT_AS_FAILED: "Count as failed", RERUN: "Rerun this job",
        RERUN_FROM: "Rerun from…", SKIP: "Skip…", SKIP_BRANCH: "Skip the rest of the branch",
        KILL_WORKFLOW: "Kill the workflow", START_WORKFLOW: "Start a workflow", NOTIFY: "Notify", MARK_AS_LATE: "Mark as late",
    };
    const NEXT_ACTIONS = ["COUNT_AS_SUCCEEDED", "COUNT_AS_FAILED", "RERUN", "RERUN_FROM", "SKIP", "SKIP_BRANCH", "KILL_WORKFLOW"];
    const ONLY_IN_WORKFLOWS = ["RERUN_FROM", "SKIP", "SKIP_BRANCH", "KILL_WORKFLOW"];
    const LIMITED = ["RERUN", "RERUN_FROM"];
    let nextUid = 1;

    const BOX = `
<div class="reactions">
    <template x-if="!editing">
        <div>
            <p class="muted small" x-show="!$LIST.length">None. What happens next is up to what waits for it.</p>
            <ol class="reaction-list" x-show="$LIST.length">
                <template x-for="r in reactionsInOrder($LIST)" :key="r.uid">
                    <li x-text="reactionWords(r)"></li>
                </template>
            </ol>
        </div>
    </template>
    <template x-if="editing">
        <div>
            <template x-for="section in ['NEXT', 'ALSO']" :key="section">
                <div class="reaction-section" :data-section="section">
                    <h4><span x-text="section === 'NEXT' ? 'What happens next' : 'Also'"></span>
                        <span class="muted small" x-text="section === 'NEXT' ? 'In order: the first that holds decides.' : 'Every one that holds happens as well.'"></span></h4>
                    <ul class="reaction-entries">
                        <template x-for="r in $LIST.filter(e => e.section === section)" :key="r.uid">
                            <li class="reaction">
                                <div class="wf-row">
                                    <label>When <select class="reaction-when" x-model="r.when" @change="whenChanged(r)">
                                        <template x-for="choice in whenChoices(section, $WORKFLOW)" :key="choice">
                                            <option :value="choice" x-text="WHEN_TEXT[choice]" :selected="choice === r.when"></option>
                                        </template>
                                    </select></label>
                                    <input type="text" class="reaction-codes" x-show="r.when === 'RC'" x-model="r.return_codes"
                                           placeholder="4, or 4-8" maxlength="100" style="max-width: 120px">
                                    <span class="reaction-time wf-row" x-show="isTimeWhen(r)">
                                        <select class="reaction-time-kind" x-model="r.time_kind" aria-label="How the time is given">
                                            <template x-for="kind in timeKinds(r.when, $WORKFLOW)" :key="kind">
                                                <option :value="kind" x-text="KIND_TEXT[kind]" :selected="kind === r.time_kind"></option>
                                            </template>
                                        </select>
                                        <input type="time" class="reaction-clock" x-show="r.time_kind === 'CLOCK'" x-model="r.clock_time"
                                               aria-label="Time of day">
                                        <label x-show="minuteKind(r)"><input type="number" class="reaction-minutes" min="1" max="100000"
                                               x-model.number="r.minutes" style="max-width: 90px"> minutes</label>
                                        <label x-show="r.time_kind === 'HISTORY'"><input type="number" class="reaction-percent" min="0" max="10000"
                                               x-model.number="r.percent" style="max-width: 80px"> % over its average of the last
                                            <input type="number" class="reaction-run-count" min="3" max="100" x-model.number="r.run_count"
                                                   style="max-width: 70px"> runs</label>
                                    </span>
                                    <span class="spacer"></span>
                                    <button type="button" class="tool" title="Earlier" x-show="section === 'NEXT'"
                                            @click="moveReaction($LIST, r, -1)">▲</button>
                                    <button type="button" class="tool" title="Later" x-show="section === 'NEXT'"
                                            @click="moveReaction($LIST, r, 1)">▼</button>
                                    <button type="button" class="link small remove-reaction" @click="removeReaction($LIST, r)">Remove</button>
                                </div>
                                <p class="muted small reaction-time-help" x-show="isTimeWhen(r)" x-text="timeHelp(r)"></p>
                                <ul class="reaction-actions">
                                    <template x-for="(a, aIndex) in r.actions" :key="a.uid">
                                        <li class="wf-row">
                                            <select class="reaction-action" x-model="a.action" :aria-label="'What it does'">
                                                <template x-for="choice in reactionChoices(section, $WORKFLOW, r)" :key="choice">
                                                    <option :value="choice" x-text="actionName(choice)" :selected="choice === a.action"></option>
                                                </template>
                                            </select>
                                            <select class="reaction-mode" x-show="a.action === 'RERUN'" x-model="a.mode" aria-label="How it runs again">
                                                <option value="RESUME" :selected="a.mode === 'RESUME'">Resume from failure</option>
                                                <option value="RESTART" :selected="a.mode === 'RESTART'">Restart from the beginning</option>
                                            </select>
                                            <label x-show="isLimited(a)">at most <input type="number" class="reaction-times" min="1" max="100"
                                                   x-model.number="a.max_times" style="max-width: 70px"> times</label>
                                            <label x-show="isLimited(a)">after <input type="number" class="reaction-wait" min="0" max="86400"
                                                   x-model.number="a.wait_seconds" style="max-width: 90px"> seconds</label>
                                            <select class="reaction-target" x-show="a.action === 'RERUN_FROM' || a.action === 'SKIP'"
                                                    x-model="a.target" aria-label="Which job">
                                                <option value="">(choose a job)</option>
                                                <template x-for="name in ($TARGETS)" :key="name">
                                                    <option :value="name" x-text="name" :selected="name === a.target"></option>
                                                </template>
                                            </select>
                                            <input type="text" class="reaction-workflow" x-show="a.action === 'START_WORKFLOW'" x-model="a.workflow"
                                                   list="reaction-workflows" placeholder="Type to find a workflow" autocomplete="off">
                                            <input type="text" class="reaction-alert" x-show="a.action === 'NOTIFY'" x-model="a.alert"
                                                   list="reaction-alerts" placeholder="Type to find an alert" autocomplete="off">
                                            <label class="small" x-show="a.action === 'NOTIFY' && $WORKFLOW && isTimeWhen(r)"
                                                   title="The run is still marked late, with its cause; only the message is held back">
                                                <input type="checkbox" class="reaction-skip-late" x-model="a.skip_if_cause_late">
                                                skip if a job it waited for was late</label>
                                            <button type="button" class="link small" x-show="r.actions.length > 1"
                                                    @click="r.actions.splice(aIndex, 1)">Remove</button>
                                        </li>
                                    </template>
                                    <li class="muted small reaction-mode-help" x-show="r.actions.some(a => a.action === 'RERUN')"
                                        x-text="modeHelp(r)"></li>
                                    <li x-show="section === 'NEXT'"><button type="button" class="link small add-reaction-action"
                                            @click="addReactionAction(r)">+ And also…</button></li>
                                </ul>
                            </li>
                        </template>
                    </ul>
                    <button type="button" class="link small add-reaction" @click="addReaction($LIST, section)"
                            x-text="section === 'NEXT' ? '+ Add what happens next' : '+ Add something that also happens'"></button>
                </div>
            </template>
        </div>
    </template>
</div>`;

    /** Puts a Reactions box wherever the page has <div data-reactions-box ...>, including inside an Alpine <template>. */
    function fillReactionBoxes(root = document) {
        for (const slot of root.querySelectorAll("[data-reactions-box]")) {
            const html = BOX.replaceAll("$LIST", slot.dataset.list)
                .replaceAll("$WORKFLOW", slot.dataset.inWorkflow === "true" ? "true" : "false")
                .replaceAll("$TARGETS", slot.dataset.targets || "[]");
            const holder = document.createElement("template");
            holder.innerHTML = html;
            slot.replaceWith(holder.content.cloneNode(true));
        }
        for (const template of root.querySelectorAll("template")) fillReactionBoxes(template.content);
        for (const id of ["reaction-workflows", "reaction-alerts"]) {
            if (!document.getElementById(id)) document.body.append(Object.assign(document.createElement("datalist"), { id }));
        }
    }

    /** The datalists the box offers: Start a workflow offers every workflow, Notify every alert. */
    async function loadReactionWorkflows() {
        fillDatalist("reaction-workflows", async () => (await AutoApp.get("/jobs")).filter(j => j.job_type === "WORKFLOW").map(j => j.job_key));
        fillDatalist("reaction-alerts", async () => (await AutoApp.get("/alerts")).map(a => a.name));
    }

    async function fillDatalist(id, names) {
        try {
            const list = document.getElementById(id);
            if (list) list.replaceChildren(...(await names()).map(value => Object.assign(document.createElement("option"), { value })));
        } catch (e) { /* the box still works; it just offers no list */ }
    }

    /** As the API sends them, to edit. */
    function reactionsForm(list) {
        return (list || []).map(r => ({
            uid: nextUid++, section: r.section, when: r.when, return_codes: r.return_codes || "",
            time_kind: r.time_kind || "", clock_time: r.clock_time || "", minutes: r.minutes ?? 30, percent: r.percent ?? 50,
            run_count: r.run_count ?? 10,
            actions: r.actions.map(a => ({ uid: nextUid++, action: a.action, max_times: a.max_times ?? 1,
                                           wait_seconds: a.wait_seconds ?? 0, target: a.target || "", workflow: a.workflow || "",
                                           mode: a.mode || "RESUME", alert: a.alert || "",
                                           skip_if_cause_late: !!a.skip_if_cause_late })),
        }));
    }

    /** As the API takes them: What happens next first, in order, then Also. */
    function reactionsPayload(list) {
        return reactionsInOrder(list).map(r => ({
            section: r.section, when: r.when, return_codes: r.when === "RC" ? (r.return_codes.trim() || null) : null,
            ...timePayload(r),
            actions: r.actions.map(a => ({
                action: a.action,
                max_times: LIMITED.includes(a.action) ? a.max_times : null,
                wait_seconds: LIMITED.includes(a.action) ? (a.wait_seconds || 0) : null,
                mode: a.action === "RERUN" ? (a.mode || "RESUME") : null,
                target: ["RERUN_FROM", "SKIP"].includes(a.action) ? (a.target || null) : null,
                workflow: a.action === "START_WORKFLOW" ? (a.workflow.trim() || null) : null,
                alert: a.action === "NOTIFY" ? (a.alert.trim() || null) : null,
                skip_if_cause_late: a.action === "NOTIFY" ? !!a.skip_if_cause_late : false,
            })),
        }));
    }

    /** The time part of an entry as the API takes it: only the fields its kind uses. */
    function timePayload(r) {
        if (!TIME_WHENS.includes(r.when)) return {};
        const kind = r.time_kind;
        return { time_kind: kind, clock_time: kind === "CLOCK" ? (r.clock_time || null) : null,
                 minutes: MINUTE_KINDS.includes(kind) ? (r.minutes || null) : null,
                 percent: kind === "HISTORY" ? r.percent : null, run_count: kind === "HISTORY" ? (r.run_count || null) : null };
    }

    function reactionsInOrder(list) {
        return [...list.filter(r => r.section === "NEXT"), ...list.filter(r => r.section === "ALSO")];
    }

    function actionWords(a) {
        if (a.action === "RERUN" || a.action === "RERUN_FROM") {
            const from = a.action === "RERUN_FROM" ? `rerun from ${a.target || "(no job chosen)"}`
                : a.mode === "RESTART" ? "rerun this job from the beginning" : "rerun this job from where it failed";
            const wait = a.wait_seconds ? `, after ${a.wait_seconds} seconds` : "";
            return `${from}, at most ${a.max_times} time${a.max_times === 1 ? "" : "s"}${wait}`;
        }
        if (a.action === "SKIP") return `skip ${a.target || "(no job chosen)"}`;
        if (a.action === "START_WORKFLOW") return `start workflow ${a.workflow || "(none chosen)"}`;
        if (a.action === "NOTIFY") return `notify ${a.alert || "(no alert chosen)"}` + (a.skip_if_cause_late ? " (not if a job it waited for was late)" : "");
        return ACTIONS[a.action].toLowerCase();
    }

    /** A time When in words: "it has not ended by 03:00", "it runs longer than 50% over its average of the last 10 runs". */
    function timeWords(r) {
        const kind = r.time_kind;
        if (kind === "CLOCK") return `${WHEN[r.when]} ${r.clock_time || "(no time given)"}`;
        if (kind === "AFTER_START") return `${WHEN[r.when]} ${r.minutes} minutes after the start`;
        if (kind === "AFTER_READY") return `${WHEN[r.when]} ${r.minutes} minutes after it is ready`;
        if (kind === "LENGTH") return `${WHEN[r.when]} ${r.minutes} minutes`;
        return `${WHEN[r.when]} ${r.percent}% over its average of the last ${r.run_count} runs`;
    }

    /** One entry in words: "When its return code is 8: rerun this job, at most 2 times." */
    function reactionWords(r) {
        const when = TIME_WHENS.includes(r.when) ? timeWords(r) : WHEN[r.when] + (r.when === "RC" ? ` ${r.return_codes || "(none given)"}` : "");
        const what = r.actions.map(actionWords).join(", and ");
        return `${r.section === "ALSO" ? "Also, when" : "When"} ${when}: ${what}.`;
    }

    function newAction(action) {
        return { uid: nextUid++, action, max_times: 1, wait_seconds: 0, target: "", workflow: "", mode: "RESUME", alert: "",
                 skip_if_cause_late: false };
    }

    /** "03:00 today" or "03:00 tomorrow": the next time that time of day comes round (proposal 3). */
    function nextClockTime(text) {
        const [hours, minutes] = text.split(":").map(Number);
        const now = new Date(), due = new Date(now);
        due.setHours(hours, minutes, 0, 0);
        const tomorrow = due <= now;
        return `${text} ${tomorrow ? "tomorrow" : "today"}`;
    }

    /** The Reactions part of a page's component. */
    function reactionEditing() {
        return {
            reactionsForm, reactionsPayload, reactionsInOrder, reactionWords,

            actionName(action) { return ACTIONS[action]; },
            isLimited(a) { return LIMITED.includes(a.action); },
            isTimeWhen(r) { return TIME_WHENS.includes(r.when); },
            minuteKind(r) { return MINUTE_KINDS.includes(r.time_kind); },
            WHEN_TEXT: WHEN, KIND_TEXT: KIND_WORDS,

            /** The Whens a section offers: a time When only tells or marks, so only Also has them. */
            whenChoices(section, inWorkflow) {
                if (section !== "ALSO") return PLAIN_WHENS;
                return [...PLAIN_WHENS, ...TIME_WHENS.filter(w => inWorkflow || w !== "NOT_STARTED_BY")];
            },

            /** How a time When can be given; "ready" needs a workflow around the job. */
            timeKinds(when, inWorkflow) {
                return (KINDS_FOR[when] || []).filter(k => inWorkflow || k !== "AFTER_READY");
            },

            /** Choosing another When keeps its actions allowed: Mark as late only goes with a time When. */
            whenChanged(r) {
                if (TIME_WHENS.includes(r.when)) {
                    if (!KINDS_FOR[r.when].includes(r.time_kind)) r.time_kind = KINDS_FOR[r.when][0];
                    return;
                }
                r.actions = r.actions.filter(a => a.action !== "MARK_AS_LATE");
                if (!r.actions.length) r.actions.push(newAction("NOTIFY"));
            },

            /** What a time means, in words, with what a time of day works out to if the run started now. */
            timeHelp(r) {
                if (r.time_kind === "CLOCK") return r.clock_time ? `Works out to ${nextClockTime(r.clock_time)} if the run starts now. ` +
                    "A time of day means its next occurrence after the run starts." : "Give a time of day, like 03:00.";
                if (r.time_kind === "AFTER_START") return "Counted from when the run starts (the workflow's start, for a job in a workflow).";
                if (r.time_kind === "AFTER_READY") return "Counted from when the job's own prerequisites are met, so a late upstream job does not move it.";
                if (r.time_kind === "LENGTH") return "Counted from the start of each attempt of the job.";
                return "Worked out when the job starts, from its successful runs. With fewer than 3 earlier runs it is not judged, and the log says so.";
            },

            /** What the choice on a Rerun this job means, in words, for the entry it is in. */
            modeHelp(r) {
                const rerun = r.actions.find(a => a.action === "RERUN");
                return rerun && rerun.mode === "RESTART"
                    ? "Restart from the beginning runs every step again, as a new attempt."
                    : "Resume from failure keeps the steps that finished and runs the rest. If a step failed and "
                      + "AutoApp cannot tell whether it changed anything, nothing is rerun and the job stays failed. "
                      + "On a workflow it picks up the jobs that failed and starts those that did not run, and is "
                      + "passed over if any one of them cannot be picked up.";
            },

            reactionChoices(section, inWorkflow, r) {
                if (section === "ALSO") return ["NOTIFY", ...(r && TIME_WHENS.includes(r.when) ? ["MARK_AS_LATE"] : []), "START_WORKFLOW"];
                return NEXT_ACTIONS.filter(a => inWorkflow || !ONLY_IN_WORKFLOWS.includes(a));
            },

            addReaction(list, section) {
                list.push({ uid: nextUid++, section, when: "FAILED", return_codes: "", time_kind: "", clock_time: "", minutes: 30,
                            percent: 50, run_count: 10, actions: [newAction(section === "ALSO" ? "NOTIFY" : "RERUN")] });
            },

            removeReaction(list, r) { list.splice(list.indexOf(r), 1); },

            /** Earlier or later among What happens next: swaps it with its neighbour in that section. */
            moveReaction(list, r, step) {
                const same = list.filter(e => e.section === r.section);
                const other = same[same.indexOf(r) + step];
                if (!other) return;
                const a = list.indexOf(r), b = list.indexOf(other);
                [list[a], list[b]] = [list[b], list[a]];
            },

            addReactionAction(r) {
                r.actions.push(newAction("COUNT_AS_FAILED"));
            },
        };
    }

    Object.assign(AutoApp, { fillReactionBoxes, loadReactionWorkflows, reactionEditing, reactionsForm, reactionsPayload,
                             reactionWords });
})();

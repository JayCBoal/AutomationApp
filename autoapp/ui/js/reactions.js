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
    const WHEN = { SUCCESS: "it succeeds", FAILED: "it fails", ENDED: "it ends, whatever happened", RC: "its return code is" };
    const ACTIONS = {
        COUNT_AS_SUCCEEDED: "Count as succeeded", COUNT_AS_FAILED: "Count as failed", RERUN: "Rerun this job",
        RERUN_FROM: "Rerun from…", SKIP: "Skip…", SKIP_BRANCH: "Skip the rest of the branch",
        KILL_WORKFLOW: "Kill the workflow", START_WORKFLOW: "Start a workflow",
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
                                    <label>When <select class="reaction-when" x-model="r.when">
                                        <option value="SUCCESS">it succeeds</option>
                                        <option value="FAILED">it fails</option>
                                        <option value="ENDED">it ends, whatever happened</option>
                                        <option value="RC">its return code is</option>
                                    </select></label>
                                    <input type="text" class="reaction-codes" x-show="r.when === 'RC'" x-model="r.return_codes"
                                           placeholder="4, or 4-8" maxlength="100" style="max-width: 120px">
                                    <span class="spacer"></span>
                                    <button type="button" class="tool" title="Earlier" x-show="section === 'NEXT'"
                                            @click="moveReaction($LIST, r, -1)">▲</button>
                                    <button type="button" class="tool" title="Later" x-show="section === 'NEXT'"
                                            @click="moveReaction($LIST, r, 1)">▼</button>
                                    <button type="button" class="link small remove-reaction" @click="removeReaction($LIST, r)">Remove</button>
                                </div>
                                <ul class="reaction-actions">
                                    <template x-for="(a, aIndex) in r.actions" :key="a.uid">
                                        <li class="wf-row">
                                            <select class="reaction-action" x-model="a.action" :aria-label="'What it does'">
                                                <template x-for="choice in reactionChoices(section, $WORKFLOW)" :key="choice">
                                                    <option :value="choice" x-text="actionName(choice)" :selected="choice === a.action"></option>
                                                </template>
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
                                            <button type="button" class="link small" x-show="r.actions.length > 1"
                                                    @click="r.actions.splice(aIndex, 1)">Remove</button>
                                        </li>
                                    </template>
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
        if (!document.getElementById("reaction-workflows")) {
            const list = Object.assign(document.createElement("datalist"), { id: "reaction-workflows" });
            document.body.append(list);
        }
    }

    /** The datalist Start a workflow offers: every workflow. */
    async function loadReactionWorkflows() {
        try {
            const jobs = await AutoApp.get("/jobs");
            const list = document.getElementById("reaction-workflows");
            if (list) list.replaceChildren(...jobs.filter(j => j.job_type === "WORKFLOW").map(j =>
                Object.assign(document.createElement("option"), { value: j.job_key })));
        } catch (e) { /* the box still works; it just offers no list */ }
    }

    /** As the API sends them, to edit. */
    function reactionsForm(list) {
        return (list || []).map(r => ({
            uid: nextUid++, section: r.section, when: r.when, return_codes: r.return_codes || "",
            actions: r.actions.map(a => ({ uid: nextUid++, action: a.action, max_times: a.max_times ?? 1,
                                           wait_seconds: a.wait_seconds ?? 0, target: a.target || "", workflow: a.workflow || "" })),
        }));
    }

    /** As the API takes them: What happens next first, in order, then Also. */
    function reactionsPayload(list) {
        return reactionsInOrder(list).map(r => ({
            section: r.section, when: r.when, return_codes: r.when === "RC" ? (r.return_codes.trim() || null) : null,
            actions: r.actions.map(a => ({
                action: a.action,
                max_times: LIMITED.includes(a.action) ? a.max_times : null,
                wait_seconds: LIMITED.includes(a.action) ? (a.wait_seconds || 0) : null,
                target: ["RERUN_FROM", "SKIP"].includes(a.action) ? (a.target || null) : null,
                workflow: a.action === "START_WORKFLOW" ? (a.workflow.trim() || null) : null,
            })),
        }));
    }

    function reactionsInOrder(list) {
        return [...list.filter(r => r.section === "NEXT"), ...list.filter(r => r.section === "ALSO")];
    }

    function actionWords(a) {
        if (a.action === "RERUN" || a.action === "RERUN_FROM") {
            const from = a.action === "RERUN_FROM" ? `rerun from ${a.target || "(no job chosen)"}` : "rerun this job";
            const wait = a.wait_seconds ? `, after ${a.wait_seconds} seconds` : "";
            return `${from}, at most ${a.max_times} time${a.max_times === 1 ? "" : "s"}${wait}`;
        }
        if (a.action === "SKIP") return `skip ${a.target || "(no job chosen)"}`;
        if (a.action === "START_WORKFLOW") return `start workflow ${a.workflow || "(none chosen)"}`;
        return ACTIONS[a.action].toLowerCase();
    }

    /** One entry in words: "When its return code is 8: rerun this job, at most 2 times." */
    function reactionWords(r) {
        const when = WHEN[r.when] + (r.when === "RC" ? ` ${r.return_codes || "(none given)"}` : "");
        const what = r.actions.map(actionWords).join(", and ");
        return `${r.section === "ALSO" ? "Also, when" : "When"} ${when}: ${what}.`;
    }

    /** The Reactions part of a page's component. */
    function reactionEditing() {
        return {
            reactionsForm, reactionsPayload, reactionsInOrder, reactionWords,

            actionName(action) { return ACTIONS[action]; },
            isLimited(a) { return LIMITED.includes(a.action); },

            reactionChoices(section, inWorkflow) {
                if (section === "ALSO") return ["START_WORKFLOW"];
                return NEXT_ACTIONS.filter(a => inWorkflow || !ONLY_IN_WORKFLOWS.includes(a));
            },

            addReaction(list, section) {
                list.push({ uid: nextUid++, section, when: "FAILED", return_codes: "",
                            actions: [{ uid: nextUid++, action: section === "ALSO" ? "START_WORKFLOW" : "RERUN",
                                        max_times: 1, wait_seconds: 0, target: "", workflow: "" }] });
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
                r.actions.push({ uid: nextUid++, action: "COUNT_AS_FAILED", max_times: 1, wait_seconds: 0, target: "", workflow: "" });
            },
        };
    }

    Object.assign(AutoApp, { fillReactionBoxes, loadReactionWorkflows, reactionEditing, reactionsForm, reactionsPayload,
                             reactionWords });
})();

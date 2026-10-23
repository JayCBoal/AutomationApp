/*
 * Rerun ▸ : the dialog shared by every page that can run a failed run again (the Run Job page, a run's log page,
 * a workflow's run, Job History). One piece of markup and one set of methods, so the pages cannot drift apart.
 *
 * A page puts <div data-rerun-panel></div> where the dialog goes, spreads rerunDialog() into its component, and
 * defines afterRerun(launch) to say what happens once the new attempt has started. Open it with openRerun(runId).
 *
 * API routes used:
 *     GET  /api/v1/runs/{run_id}/rerun-plan  what Rerun can do for a failed run: a job on its own, a workflow run,
 *                                            a frame, or a job inside one; the steps to decide; the ${...} values
 *                                            (one list, or for a workflow one list for each workflow, use and resumed job)
 *     POST /api/v1/runs/{run_id}/rerun       Resume or Restart from beginning: the next attempt
 */
const RERUN_PANEL = `
<div class="panel" id="rerun-panel" x-show="rerunPlan" x-cloak>
    <template x-if="rerunPlan">
        <div>
            <p class="small" id="rerun-summary" x-text="rerunPlan.refusal || rerunPlan.summary"></p>
            <p class="message warning small" id="rerun-resume-problem" x-show="rerunPlan.resume_problem"
               x-text="rerunPlan.resume_problem"></p>
            <template x-if="advancedOn && rerunPlan.choices.length">
            <fieldset id="rerun-advanced">
                <p class="small">Choose what happens to each item of the run. Items left alone stay as they ended.</p>
                <label><input type="radio" name="rerun-shortcut" value="" x-model="advShortcut" @change="advRefresh()"> Item by item</label>
                <label><input type="radio" name="rerun-shortcut" value="from" x-model="advShortcut" @change="advRefresh()"> From the jobs chosen, and everything that waits for them</label>
                <label><input type="radio" name="rerun-shortcut" value="only" x-model="advShortcut" @change="advRefresh()"> Only the jobs chosen</label>
                <p class="message warning small" id="rerun-only-warning" x-show="advShortcut === 'only'">
                    What waits for these jobs is left as it ended, so its results may be out of date.</p>
                <p class="small" x-show="advShortcut">The jobs chosen are
                    <select id="rerun-chosen-as" x-model="advChosenAs" @change="advRefresh()" aria-label="What the jobs chosen get">
                        <option value="resume">resumed where they failed</option>
                        <option value="restart">restarted from the beginning</option>
                        <option value="bypass">bypassed</option>
                        <option value="dont_run">not run</option>
                    </select></p>
                <table class="small" id="rerun-choices">
                    <template x-for="choice in rerunPlan.choices" :key="choice.path">
                        <tr class="rerun-choice" :data-path="choice.path">
                            <td :style="'padding-left: ' + (choice.depth * 1.5) + 'em'">
                                <code x-text="choice.path"></code>
                                <span class="muted" x-text="choice.is_workflow ? 'workflow, ' + choice.status : choice.status"></span>
                            </td>
                            <td x-show="advShortcut">
                                <input type="checkbox" :aria-label="'Choose ' + choice.path" :checked="advChosen.includes(choice.path)"
                                       @change="advChoose(choice.path, $event.target.checked)">
                            </td>
                            <td x-show="!advShortcut">
                                <select :aria-label="'What to do with ' + choice.path" :value="advItems[choice.path] || ''"
                                        @change="advSet(choice.path, $event.target.value)">
                                    <option value="" x-text="advWaitsItsTurn(choice) ? 'Run when its waits are met' : 'Leave as it ended'">Leave as it ended</option>
                                    <option value="leave" x-show="advWaitsItsTurn(choice)">Leave Not run</option>
                                    <option value="resume" :disabled="!choice.can_resume">Resume</option>
                                    <option value="restart">Restart from the beginning</option>
                                    <option value="bypass">Bypass (counts as succeeded)</option>
                                    <option value="dont_run">Don&rsquo;t run (Skipped)</option>
                                </select>
                                <span class="muted" x-show="!choice.can_resume && choice.resume_problem" x-text="choice.resume_problem"></span>
                            </td>
                            <td>
                                <template x-if="advRunsAgain(choice.path) && choice.waits.length && !choice.custom_rule">
                                    <span class="small rerun-waits">Ignore the wait for
                                        <template x-for="name in choice.waits" :key="name">
                                            <label><input type="checkbox" :checked="(advIgnore[choice.path] || []).includes(name)"
                                                          @change="advIgnoreWait(choice.path, name, $event.target.checked)"> <code x-text="name"></code></label>
                                        </template>
                                    </span>
                                </template>
                            </td>
                        </tr>
                    </template>
                </table>
                <label><input type="checkbox" id="rerun-reset-counts" x-model="advResetCounts" @change="advRefresh()">
                    Start the automatic retry counts again from zero</label>
                <p class="message warning small" x-show="Object.keys(advIgnore).length">
                    The waits ticked are ignored for this restart only; they hold again the next time.</p>
            </fieldset>
            </template>
            <template x-if="advancedOn && rerunPlan.steps.length">
            <fieldset id="rerun-steps">
                <p class="small">Start at a step, and skip steps. The steps before the one you start at count as done.</p>
                <table class="small" id="rerun-step-list">
                    <template x-for="step in rerunPlan.steps" :key="step.number">
                        <tr class="rerun-step" :data-step="step.number">
                            <td>Step <span x-text="step.number"></span> &lsquo;<span x-text="step.title"></span>&rsquo;
                                <span class="muted" x-text="step.block ? '(a block: runs as one unit)' : ''"></span></td>
                            <td class="muted" x-text="step.state === 'finished' ? 'finished' : step.state === 'failed' ? 'failed here' : 'did not run'"></td>
                            <td><label><input type="radio" name="rerun-from-step" :value="step.number" x-model="advFromStep" @change="advRefresh()"> Start here</label></td>
                            <td><label><input type="checkbox" :checked="advSkip.includes(step.number)" @change="advSkipStep(step.number, $event.target.checked)"> Skip</label></td>
                            <td class="small" x-text="step.gets === 'skipped' ? 'will not run' : step.runs_again ? 'runs again' : step.gets === 'done' ? 'as it was' : ''"></td>
                        </tr>
                    </template>
                </table>
                <p class="small"><label><input type="radio" name="rerun-from-step" value="" x-model="advFromStep" @change="advRefresh()"> No starting step: pick up where it failed</label></p>
                <p class="message warning small" id="rerun-file-warning" x-show="rerunPlan.steps.some(s => s.runs_again && s.file_step)">
                    A step that copies, deletes, zips or unzips files will do it again.</p>
            </fieldset>
            </template>
            <p class="message warning small" id="rerun-advanced-problem" x-show="advancedOn && (rerunPlan.items_problem || rerunPlan.steps_problem)"
               x-text="rerunPlan.items_problem || rerunPlan.steps_problem"></p>
            <ul class="small" id="rerun-items" x-show="rerunPlan.items.length">
                <template x-for="item in rerunPlan.items" :key="item.path">
                    <li><code x-text="item.path"></code> <span x-text="item.what"></span></li>
                </template>
            </ul>
            <fieldset x-show="rerunPlan.step_to_decide" id="rerun-decision">
                <p class="small" x-show="rerunPlan.step_to_decide">
                    <strong x-text="rerunPlan.step_to_decide && ('Step ' + rerunPlan.step_to_decide.step + ' \\u2018' + rerunPlan.step_to_decide.title + '\\u2019')"></strong>:
                    <span x-text="rerunPlan.step_to_decide && rerunPlan.step_to_decide.why"></span>.
                    It is not known whether this step changed anything before it failed. What should Resume do with it?
                </p>
                <label><input type="radio" name="rerun-unknown" value="run_again" x-model="rerunChoice"> Run it again</label>
                <label><input type="radio" name="rerun-unknown" value="count_done" x-model="rerunChoice"> Count it as done</label>
                <p class="muted small">Or restart the job from the beginning.</p>
            </fieldset>
            <fieldset x-show="rerunPlan.steps_to_decide.length" id="rerun-decisions">
                <p class="small">These steps may or may not have changed something before they failed. What should Resume do with each?</p>
                <template x-for="step in rerunPlan.steps_to_decide" :key="step.path">
                    <div class="rerun-decision-row">
                        <p class="small">
                            <code x-text="step.path"></code>, step <span x-text="step.step"></span>
                            &lsquo;<span x-text="step.title"></span>&rsquo;: <span x-text="step.why"></span>.
                        </p>
                        <label><input type="radio" :name="'rerun-unknown-' + step.path" value="run_again" x-model="rerunDecisions[step.path]"> Run it again</label>
                        <label><input type="radio" :name="'rerun-unknown-' + step.path" value="count_done" x-model="rerunDecisions[step.path]"> Count it as done</label>
                    </div>
                </template>
                <p class="muted small">Or restart from the beginning.</p>
            </fieldset>
            <template x-if="rerunPlan.can_resume && rerunPlan.values.length && !rerunPlan.value_levels.length">
            <fieldset id="rerun-values">
                <p class="small"><span x-text="valuesWho()"></span> for the job&rsquo;s \${...} placeholders:</p>
                <label><input type="radio" name="rerun-values" value="as_were" x-model="valuesChoice"> Use as they were</label>
                <label><input type="radio" name="rerun-values" value="refresh" x-model="valuesChoice"> Refresh</label>
                <label><input type="radio" name="rerun-values" value="edit" x-model="valuesChoice"> Edit</label>
                <p class="message warning small" id="rerun-refresh-changes" x-show="valuesChoice === 'refresh'">
                    <span x-show="!rerunPlan.changes.length">No variable has changed since attempt <span x-text="rerunPlan.attempt"></span>. Anything read from the environment is read again when the job starts.</span>
                    <span x-show="rerunPlan.changes.length">These have changed since attempt <span x-text="rerunPlan.attempt"></span>, and will use their new values:</span>
                    <template x-for="change in rerunPlan.changes" :key="change.key">
                        <span style="display: block"><code x-text="change.key"></code>: <span x-text="change.was"></span> &rarr; <span x-text="change.now"></span></span>
                    </template>
                </p>
                <table class="small" id="rerun-value-list">
                    <template x-for="v in rerunPlan.values" :key="v.key">
                        <tr>
                            <td><code x-text="v.key"></code></td>
                            <td>
                                <span x-show="v.secret" class="muted">a secret: always read when the job runs</span>
                                <span x-show="!v.secret && valuesChoice !== 'edit'" x-text="v.value"></span>
                                <input type="text" x-show="!v.secret && valuesChoice === 'edit'" :aria-label="'Value of ' + v.key"
                                       :value="v.value" @input="valueEdits[v.key] = $event.target.value">
                            </td>
                        </tr>
                    </template>
                </table>
            </fieldset>
            </template>
            <template x-if="rerunPlan.can_resume && rerunPlan.value_levels.length">
            <fieldset id="rerun-levels">
                <p class="small"><span x-text="valuesWho()"></span> for the \${...} placeholders of the workflow and its jobs:</p>
                <label><input type="radio" name="rerun-level-values" value="as_were" x-model="valuesChoice"> Use as they were</label>
                <label><input type="radio" name="rerun-level-values" value="refresh" x-model="valuesChoice"> Refresh</label>
                <label><input type="radio" name="rerun-level-values" value="edit" x-model="valuesChoice"> Edit</label>
                <p class="muted small" id="rerun-values-note" x-show="rerunPlan.values_note" x-text="rerunPlan.values_note"></p>
                <p class="message warning small" id="rerun-kept-jobs" x-show="keptJobsNamed()">
                    Already finished, so not run again; they keep the values they ran with:
                    <code x-text="rerunPlan.kept_jobs.join(', ')"></code>.
                </p>
                <template x-for="level in rerunPlan.value_levels" :key="level.kind + '|' + level.path + '|' + level.name">
                    <div class="rerun-level" :data-kind="level.kind">
                        <p class="small"><strong x-text="levelHeading(level)"></strong></p>
                        <p class="message warning small rerun-level-changes" x-show="valuesChoice === 'refresh' && level.changes.length">
                            These have changed, and will use their new values:
                            <template x-for="change in level.changes" :key="change.key">
                                <span style="display: block"><code x-text="change.key"></code>: <span x-text="change.was"></span> &rarr; <span x-text="change.now"></span></span>
                            </template>
                        </p>
                        <table class="small rerun-level-values">
                            <template x-for="v in level.values" :key="v.key">
                                <tr>
                                    <td><code x-text="v.key"></code></td>
                                    <td>
                                        <span x-show="v.secret" class="muted">a secret: always read when the job runs</span>
                                        <span x-show="!v.secret && valuesChoice !== 'edit'" x-text="v.value"></span>
                                        <input type="text" x-show="!v.secret && valuesChoice === 'edit'" :aria-label="'Value of ' + v.key + ' in ' + levelHeading(level)"
                                               :value="v.value" @input="valueEdits[editKey(level, v)] = $event.target.value">
                                    </td>
                                </tr>
                            </template>
                        </table>
                    </div>
                </template>
            </fieldset>
            </template>
            <div class="actions">
                <button type="button" class="primary" id="rerun-resume" x-show="!advancedOn" @click="rerun('resume')"
                        :disabled="rerunBusy || !rerunDecided()">Resume</button>
                <button type="button" class="secondary" id="rerun-restart" x-show="!advancedOn" @click="rerun('restart')"
                        :disabled="rerunBusy || !rerunPlan.can_restart">Restart from beginning</button>
                <button type="button" class="secondary" id="rerun-advanced-open" x-show="!advancedOn" @click="openAdvanced()"
                        :disabled="rerunBusy || (Boolean(rerunPlan.refusal) && !rerunPlan.advanced_only)">Advanced&hellip;</button>
                <button type="button" class="primary" id="rerun-advanced-run" x-show="advancedOn" @click="rerun('advanced')"
                        :disabled="rerunBusy || !advancedReady()">Run</button>
                <button type="button" class="secondary" id="rerun-advanced-back" x-show="advancedOn" @click="closeAdvanced()">Back</button>
                <button type="button" class="secondary" id="rerun-close" @click="closeRerun()">Close</button>
            </div>
        </div>
    </template>
</div>`;

/** Fills every slot, including those inside a <template> (a panel shown only once there is a run). */
function fillRerunSlots(root) {
    for (const slot of root.querySelectorAll("[data-rerun-panel]")) slot.outerHTML = RERUN_PANEL;
    for (const template of root.querySelectorAll("template")) fillRerunSlots(template.content);
}

document.addEventListener("DOMContentLoaded", () => fillRerunSlots(document));

function rerunDialog() {
    return {
        rerunPlan: null,        // what Rerun can do, shown while the choice is open
        rerunRunId: "",         // the run it was opened for
        rerunChoice: "",        // a job on its own: run_again or count_done, for a step that may or may not have changed something
        rerunDecisions: {},     // a workflow run: the same, for each such step, by the job's path
        rerunBusy: false,
        valuesChoice: "as_were",    // for Resume: use the ${...} values as they were, refresh them, or edit some
        valueEdits: {},             // value by key, as typed
        basePlan: null,             // the plain plan, kept while Advanced shows its own
        advancedOn: false,          // Advanced is open: rerunPlan is then the Advanced plan
        advShortcut: "",            // "", "from" or "only"
        advChosen: [],              // the jobs chosen for a shortcut, by path
        advChosenAs: "resume",      // what the jobs chosen get
        advItems: {},               // item by item: the action for each, by path (an item left alone is not here)
        advIgnore: {},              // prerequisites to ignore for this one restart, by the job's path
        advResetCounts: false,
        advFromStep: "",            // a job on its own: the step to start at
        advSkip: [],                // a job on its own: the steps to skip
        advAsked: 0,                // which preview is the latest, so a slow one cannot overwrite a newer one

        /** A run that failed can be run again, and a workflow run that succeeded by Advanced only; the server says whether, and why not. */
        canRerun(run) {
            if (!run) return false;
            return run.status === "FAILED" || (run.status === "SUCCESS" && run.job_type === "WORKFLOW" && !run.parent_run_id);
        },

        async openRerun(runId) {
            this.error = "";
            this.rerunChoice = "";
            this.rerunDecisions = {};
            this.valuesChoice = "as_were";
            this.valueEdits = {};
            this.resetAdvanced();
            this.rerunRunId = runId || this.run.run_id;
            try {
                this.rerunPlan = await AutoApp.get(`/runs/${encodeURIComponent(this.rerunRunId)}/rerun-plan`);
            } catch (e) {
                this.error = e.message;
            }
            this.$nextTick(() => document.getElementById("rerun-panel")?.scrollIntoView({ block: "nearest" }));
        },
        /** Who the values are for: Resume, or whatever Advanced restarts. */
        valuesWho() { return this.advancedOn ? "The values the items restarted here use" : "The values Resume uses"; },
        closeRerun() { this.rerunPlan = null; this.basePlan = null; this.advancedOn = false; },

        resetAdvanced() {
            Object.assign(this, { basePlan: null, advancedOn: false, advShortcut: "", advChosen: [], advChosenAs: "resume",
                                  advItems: {}, advIgnore: {}, advResetCounts: false, advFromStep: "", advSkip: [] });
        },

        async openAdvanced() {
            this.basePlan = this.rerunPlan;
            this.error = "";
            await this.advRefresh(true);
        },

        closeAdvanced() {
            this.rerunPlan = this.basePlan;
            this.resetAdvanced();
        },

        /** The query that asks what the choices made so far would do. */
        advQuery() {
            const q = new URLSearchParams({ advanced: "true" });
            if (this.advShortcut) {
                q.set("shortcut", this.advShortcut);
                this.advChosen.forEach(path => q.append("chosen", path));
                q.set("chosen_as", this.advChosenAs);
            } else if (Object.keys(this.advItems).length) {
                q.set("items", JSON.stringify(this.advItems));
            }
            if (Object.keys(this.advIgnore).length) q.set("ignore", JSON.stringify(this.advIgnore));
            if (this.advResetCounts) q.set("reset_counts", "true");
            if (this.advFromStep) q.set("from_step", this.advFromStep);
            this.advSkip.forEach(number => q.append("skip_steps", number));
            return q.toString();
        },

        /** Asks the server again, so the page says what the run would do with the choices as they stand. */
        async advRefresh(opening) {
            const asked = ++this.advAsked;
            try {
                const plan = await AutoApp.get(`/runs/${encodeURIComponent(this.rerunRunId)}/rerun-plan?${this.advQuery()}`);
                if (asked !== this.advAsked) return;
                this.rerunPlan = plan;
                this.advancedOn = true;
            } catch (e) {
                if (asked !== this.advAsked) return;
                this.error = e.message;
                if (opening) this.closeAdvanced();
            }
        },

        advSet(path, action) {
            if (action) this.advItems[path] = action; else delete this.advItems[path];
            this.advDropIgnored();
            this.advRefresh();
        },

        advChoose(path, on) {
            this.advChosen = on ? [...this.advChosen, path] : this.advChosen.filter(p => p !== path);
            this.advRefresh();
        },

        /** Whether the item runs again with the choices as they stand (a wait is only worth ignoring then). */
        advRunsAgain(path) {
            const got = (this.rerunPlan.named_items || {})[path];
            return got === "resume" || got === "restart";
        },

        advIgnoreWait(path, name, on) {
            const names = (this.advIgnore[path] || []).filter(n => n !== name).concat(on ? [name] : []);
            if (names.length) this.advIgnore[path] = names; else delete this.advIgnore[path];
            this.advRefresh();
        },

        /** An item at the top that did not run: unless left alone it runs when its waits are met, as on a Resume. */
        advWaitsItsTurn(choice) { return choice.status === "NOT_RUN" && choice.depth === 0; },

        /** An item that no longer runs again has no wait left to ignore. */
        advDropIgnored() {
            for (const path of Object.keys(this.advIgnore)) {
                const choice = this.rerunPlan.choices.find(c => c.path === path);
                const runs = ["resume", "restart"].includes(this.advItems[path]) || (choice && this.advWaitsItsTurn(choice) && !this.advItems[path]);
                if (!runs) delete this.advIgnore[path];
            }
        },

        advSkipStep(number, on) {
            this.advSkip = on ? [...this.advSkip, number] : this.advSkip.filter(n => n !== number);
            this.advRefresh();
        },

        /** Run can be pressed once something is chosen, the server accepts it, and every unsure step has an answer. */
        advancedReady() {
            const plan = this.rerunPlan;
            if (!plan || !plan.advanced || plan.refusal || plan.items_problem || plan.steps_problem) return false;
            const chosen = plan.steps.length ? Boolean(this.advFromStep) || this.advSkip.length > 0 : Object.keys(plan.named_items).length > 0;
            return chosen && plan.steps_to_decide.every(step => this.rerunDecisions[step.path])
                && !(plan.step_to_decide && !this.rerunChoice);
        },

        /** Resume can be chosen once it is possible and every step that may or may not have changed something has an answer. */
        rerunDecided() {
            const plan = this.rerunPlan;
            if (!plan || !plan.can_resume) return false;
            if (plan.step_to_decide && !this.rerunChoice) return false;
            return plan.steps_to_decide.every(step => this.rerunDecisions[step.path]);
        },

        /** A reopened run keeps its run ID: wait until it reads Running again, so a page opened on it does not stop at its old end. */
        async waitUntilRunning(launch) {
            for (let tries = 0; tries < 40; tries++) {
                await new Promise(resolve => setTimeout(resolve, 300));
                const run = await AutoApp.get("/runs/" + encodeURIComponent(launch.run_id));
                if (run.status === "RUNNING") return;
                launch = await AutoApp.get("/launches/" + encodeURIComponent(launch.launch_id));
                if (launch.state !== "RUNNING") return;
            }
        },

        /** The heading of one list of a workflow's values. */
        levelHeading(level) {
            if (level.kind === "workflow") return level.path ? `Workflow ${level.name} (${level.path})` : `Workflow ${level.name}`;
            if (level.kind === "use") return `Variables of ${level.name} in ${level.path || "the workflow"}`;
            return `Job ${level.path}`;
        },

        editKey(level, v) { return [level.kind, level.path, level.name, v.key].join("|"); },

        /** Finished jobs are named once a value that reaches the workflow's level is going to read differently, or has been edited. */
        keptJobsNamed() {
            const plan = this.rerunPlan;
            if (!plan || !plan.kept_jobs.length || !plan.value_levels.length) return false;
            if (this.valuesChoice === "refresh") return plan.value_levels.some(l => l.kind !== "job" && l.changes.length);
            return this.valuesChoice === "edit" && Boolean(Object.keys(this.levelEdits().levels).length);
        },

        /** What the operator typed over in the workflow's lists, in the shape the API takes. */
        levelEdits() {
            const levels = {}, jobs = {};
            for (const level of this.rerunPlan.value_levels) {
                for (const v of level.values) {
                    const typed = this.valueEdits[this.editKey(level, v)];
                    if (typed === undefined || typed === v.value) continue;
                    if (level.kind === "job") {
                        (jobs[level.path] ||= {})[v.key] = typed;
                        continue;
                    }
                    const at = (levels[level.path] ||= { workflow: {}, uses: {} });
                    if (level.kind === "workflow") at.workflow[v.key] = typed;
                    else ((at.uses[level.name] ||= {}))[v.key] = typed;
                }
            }
            return { levels, jobs };
        },

        /** The values the operator typed over, not those left as they were. */
        changedEdits() {
            const was = Object.fromEntries(this.rerunPlan.values.map(v => [v.key, v.value]));
            return Object.fromEntries(Object.entries(this.valueEdits).filter(([key, value]) => value !== was[key]));
        },

        /** What Advanced adds to the request: the choices as made. */
        advancedRequest() {
            const request = { ignore: this.advIgnore, reset_counts: this.advResetCounts,
                              from_step: this.advFromStep || null, skip_steps: this.advSkip };
            if (!this.advShortcut) return { ...request, items: this.advItems };
            return { ...request, shortcut: this.advShortcut, chosen: this.advChosen, chosen_as: this.advChosenAs };
        },

        async rerun(kind) {
            this.rerunBusy = true;
            const resume = kind !== "restart";           // a restart has nothing to decide or pin; Advanced may do either
            const advanced = kind === "advanced";
            const edited = resume && this.rerunPlan.value_levels.length ? this.levelEdits() : { levels: {}, jobs: {} };
            try {
                const launch = await AutoApp.send("POST", `/runs/${encodeURIComponent(this.rerunRunId)}/rerun`, {
                    kind, unknown_step: resume ? this.rerunChoice || null : null,
                    decisions: resume ? { ...this.rerunDecisions } : {},
                    refresh_values: resume && this.valuesChoice === "refresh",
                    edits: resume && this.valuesChoice === "edit" && !this.rerunPlan.value_levels.length ? this.changedEdits() : {},
                    ...(advanced ? this.advancedRequest() : {}),
                    level_edits: resume && this.valuesChoice === "edit" ? edited.levels : {},
                    job_edits: resume && this.valuesChoice === "edit" ? edited.jobs : {},
                });
                this.closeRerun();
                this.afterRerun(launch);
            } catch (e) {
                this.error = e.message;
            } finally {
                this.rerunBusy = false;
            }
        },
    };
}

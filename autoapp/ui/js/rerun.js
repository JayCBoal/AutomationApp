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
 *     POST /api/v1/runs/{run_id}/rerun       Resume or Restart from beginning: the next attempt
 */
const RERUN_PANEL = `
<div class="panel" id="rerun-panel" x-show="rerunPlan" x-cloak>
    <template x-if="rerunPlan">
        <div>
            <p class="small" id="rerun-summary" x-text="rerunPlan.refusal || rerunPlan.summary"></p>
            <p class="message warning small" id="rerun-resume-problem" x-show="rerunPlan.resume_problem"
               x-text="rerunPlan.resume_problem"></p>
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
            <fieldset x-show="rerunPlan.can_resume && rerunPlan.values.length" id="rerun-values">
                <p class="small">The values Resume uses for the job&rsquo;s \${...} placeholders:</p>
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
            <div class="actions">
                <button type="button" class="primary" id="rerun-resume" @click="rerun('resume')"
                        :disabled="rerunBusy || !rerunDecided()">Resume</button>
                <button type="button" class="secondary" id="rerun-restart" @click="rerun('restart')"
                        :disabled="rerunBusy || !rerunPlan.can_restart">Restart from beginning</button>
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

        /** A run that failed can be run again; the server says whether, and why not. */
        canRerun(run) { return Boolean(run) && run.status === "FAILED"; },

        async openRerun(runId) {
            this.error = "";
            this.rerunChoice = "";
            this.rerunDecisions = {};
            this.valuesChoice = "as_were";
            this.valueEdits = {};
            this.rerunRunId = runId || this.run.run_id;
            try {
                this.rerunPlan = await AutoApp.get(`/runs/${encodeURIComponent(this.rerunRunId)}/rerun-plan`);
            } catch (e) {
                this.error = e.message;
            }
            this.$nextTick(() => document.getElementById("rerun-panel")?.scrollIntoView({ block: "nearest" }));
        },
        closeRerun() { this.rerunPlan = null; },

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

        /** The values the operator typed over, not those left as they were. */
        changedEdits() {
            const was = Object.fromEntries(this.rerunPlan.values.map(v => [v.key, v.value]));
            return Object.fromEntries(Object.entries(this.valueEdits).filter(([key, value]) => value !== was[key]));
        },

        async rerun(kind) {
            this.rerunBusy = true;
            const resume = kind === "resume";
            try {
                const launch = await AutoApp.send("POST", `/runs/${encodeURIComponent(this.rerunRunId)}/rerun`, {
                    kind, unknown_step: resume ? this.rerunChoice || null : null,
                    decisions: resume ? { ...this.rerunDecisions } : {},
                    refresh_values: resume && this.valuesChoice === "refresh",
                    edits: resume && this.valuesChoice === "edit" ? this.changedEdits() : {},
                });
                this.rerunPlan = null;
                this.afterRerun(launch);
            } catch (e) {
                this.error = e.message;
            } finally {
                this.rerunBusy = false;
            }
        },
    };
}

/*
 * A job's summary card (summary.html?key=...): what a scheduler that can only show
 * a web page would put in a panel of its own job screen. The same as
 * GET /api/v1/jobs/{key}/summary, which a scheduler can draw for itself instead.
 * It takes the same scheduler=, wla_job= and instance_id= (see docs/INTEGRATION.md).
 */
function jobSummary() {
    const address = new URLSearchParams(location.search);
    return {
        summary: null,
        error: "",

        async init() {
            const key = address.get("key");
            if (!key) { this.error = "No job was given: summary.html?key=<JobKey>."; return; }
            const params = {};
            for (const name of ["scheduler", "wla_job", "instance_id"]) if (address.get(name)) params[name] = address.get(name);
            try {
                this.summary = await AutoApp.get("/jobs/" + encodeURIComponent(key) + "/summary", params);
                document.title = `${key} - RunMyFiles`;
            } catch (e) {
                this.error = e.message;
            }
        },

        // The summary's links are full addresses; opened from here they stay embedded, if this card is
        open(url) { return AutoApp.link(url); },
        time: AutoApp.formatTime,
    };
}

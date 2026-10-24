/*
 * The Alert deliveries page: every message Notify queued, newest first, and whether the sender sent it.
 *
 *     GET /api/v1/alert-deliveries?status=&alert=     the messages
 */
function alertDeliveries() {
    const search = AutoApp.searchPage({
        criteria: ["alert", "status"], path: "/alert-deliveries", noun: "message", order: "newest first",
    });
    return Object.assign(search, {
        init() { this.startSearch(); },
        time(text) { return AutoApp.formatTime(text); },

        resultWords(d) {
            if (d.status === "SENT") return "Sent " + this.time(d.sent);
            if (d.status === "FAILED") return `Failed after ${d.attempts} ${d.attempts === 1 ? "try" : "tries"}`;
            return d.attempts ? `Waiting to be sent (${d.attempts} ${d.attempts === 1 ? "try" : "tries"} so far)` : "Waiting to be sent";
        },

        /** The run that fired it: its log, which Job History offers for every run. */
        runLink(d) { return "log.html?" + new URLSearchParams({ run: d.run_id }); },
    });
}

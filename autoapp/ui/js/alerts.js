/*
 * The Alerts page: who is told, and what they are told, when a Reaction's Notify fires, and where mail is sent through.
 *
 *     GET    /api/v1/alerts              every alert, with the Reactions that name it
 *     POST   /api/v1/alerts              add one
 *     PUT    /api/v1/alerts/{name}       change one
 *     DELETE /api/v1/alerts/{name}       remove one no Reaction names
 *     POST   /api/v1/alerts/{name}/test  Send a test: queues the message, marked as a test
 *     GET    /api/v1/mail-settings       and PUT, where mail is sent through
 */
function alertsPage() {
    return {
        alerts: [],
        mail: { configured: false, host: "", port: 25, sender: "", use_tls: false, credential: "" },
        draft: null,        // the alert being added or changed: {name, was, description, recipients (text), subject, message}
        busy: false,
        error: "",
        notice: "",

        async init() {
            await this.run(async () => {
                this.alerts = await AutoApp.get("/alerts");
                this.mail = this.mailForm(await AutoApp.get("/mail-settings"));
            });
        },

        mailForm(settings) { return { ...settings, credential: settings.credential || "" }; },

        /** Runs one action with the page busy, showing what went wrong in words. */
        async run(action) {
            this.busy = true;
            this.error = "";
            try {
                await action();
            } catch (e) {
                this.error = e.message;
            }
            this.busy = false;
        },

        startNew() {
            this.notice = "";
            this.draft = { name: "", was: null, description: "", recipients: "", subject: "", message: "" };
        },

        startEdit(alert) {
            this.notice = "";
            this.draft = { name: alert.name, was: alert.name, description: alert.description || "",
                           recipients: alert.recipients.join(", "), subject: alert.subject, message: alert.message };
        },

        async save() {
            const d = this.draft;
            const body = { name: d.name, description: d.description, recipients: d.recipients, subject: d.subject, message: d.message };
            await this.run(async () => {
                if (d.was) await AutoApp.send("PUT", `/alerts/${encodeURIComponent(d.was)}`, body);
                else await AutoApp.send("POST", "/alerts", body);
                this.alerts = await AutoApp.get("/alerts");
                this.notice = `Saved the alert '${d.name}'.`;
                this.draft = null;
            });
        },

        async remove(alert) {
            if (!confirm(`Delete the alert '${alert.name}'? Messages already sent or queued are kept.`)) return;
            await this.run(async () => {
                await AutoApp.send("DELETE", `/alerts/${encodeURIComponent(alert.name)}`);
                this.alerts = await AutoApp.get("/alerts");
                this.notice = `Deleted the alert '${alert.name}'.`;
            });
        },

        async sendTest(alert) {
            await this.run(async () => {
                await AutoApp.send("POST", `/alerts/${encodeURIComponent(alert.name)}/test`);
                this.notice = `A test message for '${alert.name}' is queued. See Alert deliveries for whether it was sent.`;
            });
        },

        async saveMail() {
            await this.run(async () => {
                this.mail = this.mailForm(await AutoApp.send("PUT", "/mail-settings", {
                    host: this.mail.host, port: this.mail.port, sender: this.mail.sender, use_tls: this.mail.use_tls,
                    credential: this.mail.credential.trim() || null }));
                this.notice = "Saved the mail settings.";
            });
        },
    };
}

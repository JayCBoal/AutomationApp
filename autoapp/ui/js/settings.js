/*
 * The Settings page: system-wide settings, each changed and saved on its own.
 *
 * An order is stored lowest priority first (the order the levels are merged in),
 * but shown highest first, which reads more naturally: the top one wins.
 *
 * API routes used:
 *     GET  /api/v1/settings          every setting, its value and its default
 *     PUT  /api/v1/settings/{key}    change one
 */
function settingsPage() {
    return {
        settings: [],
        draft: {},          // what is on screen for each setting, by key; an order highest priority first
        busy: false,
        error: "",
        notice: "",

        async init() {
            try {
                this.settings = await AutoApp.get("/settings");
                for (const setting of this.settings) this.draft[setting.key] = this.shown(setting, setting.value);
            } catch (e) {
                this.error = e.message;
            }
        },

        /** A value as the page shows it: an order turned round, highest priority first. */
        shown(setting, value) { return setting.kind === "ORDER" ? [...value].reverse() : value; },
        /** What is on screen as the API takes it: an order lowest priority first. */
        stored(setting) { return this.shown(setting, this.draft[setting.key]); },
        same(a, b) { return JSON.stringify(a) === JSON.stringify(b); },
        changed(setting) { return !this.same(this.stored(setting), setting.value); },
        isDefault(setting) { return this.same(this.stored(setting), setting.default); },

        move(setting, index, by) {
            const order = this.draft[setting.key];
            const target = index + by;
            if (target < 0 || target >= order.length) return;
            order.splice(target, 0, order.splice(index, 1)[0]);
        },

        undo(setting) { this.draft[setting.key] = this.shown(setting, setting.value); },
        useDefault(setting) { this.draft[setting.key] = this.shown(setting, setting.default); },

        async save(setting) {
            this.busy = true;
            this.error = "";
            this.notice = "";
            try {
                const result = await AutoApp.send("PUT", `/settings/${encodeURIComponent(setting.key)}`,
                                                  { value: this.stored(setting) });
                Object.assign(setting, result.setting);
                this.draft[setting.key] = this.shown(setting, setting.value);
                this.notice = result.changes.length ? "Saved. " + result.changes.join(" ") : "Nothing had changed.";
            } catch (e) {
                this.error = e.message;
            }
            this.busy = false;
        },
    };
}

/*
 * Search and detail pages for applications, entities, sites and endpoints.
 *
 * The four work the same way, so one search page (search.html?kind=sites) and one
 * detail page (detail.html?kind=sites&name=ACME_SFTP) serve them all, drawn from
 * the description of each kind below.
 *
 * API routes used, for each kind:
 *     GET    /api/v1/{kind}           search
 *     GET    /api/v1/{kind}/{name}    one, with its variables and what uses it
 *     PUT    /api/v1/{kind}/{name}    change it
 *     DELETE /api/v1/{kind}/{name}    remove it, if nothing uses it
 *     POST   /api/v1/{kind}           register a new one (through AutoApp.createInPlace)
 */
const DEFINITIONS = {
    applications: {
        title: "Application", plural: "Applications", creates: "application", variables: true,
        usedByLabel: "Endpoints",
        fields: [
            { name: "name", label: "Name", required: true, max: 100 },
            { name: "abbr", label: "Abbreviation", required: true, max: 10 },
            { name: "description", label: "Description" },
            { name: "active", label: "Active", type: "checkbox" },
        ],
    },
    entities: {
        title: "Entity", plural: "Entities", creates: "entity", variables: true,
        usedByLabel: "Sites",
        fields: [
            { name: "name", label: "Name", required: true, max: 64 },
            { name: "abbr", label: "Abbreviation", required: true, max: 10 },
            { name: "description", label: "Description", max: 256 },
            { name: "active", label: "Active", type: "checkbox" },
        ],
    },
    sites: {
        title: "Site", plural: "Sites", creates: "site", variables: true,
        usedByLabel: "Endpoints",
        fields: [
            { name: "name", label: "Name", required: true, max: 64 },
            { name: "entity", label: "Entity", lookup: "entities", create: "entity" },
            { name: "host", label: "Host", required: true, max: 128 },
            { name: "port", label: "Port", required: true, type: "number" },
            { name: "protocol", label: "Protocol", required: true, max: 16 },
            { name: "description", label: "Description", max: 256 },
            { name: "active", label: "Active", type: "checkbox" },
        ],
    },
    endpoints: {
        title: "Endpoint", plural: "Endpoints", creates: "endpoint", variables: false,
        usedByLabel: "Jobs",
        fields: [
            { name: "name", label: "Name", required: true, max: 100 },
            { name: "application", label: "Application", lookup: "applications", create: "application" },
            { name: "site", label: "Site", lookup: "sites", create: "site" },
            { name: "entity", label: "Entity", lookup: "entities", derived: true,
              help: "The owner of its site. Change the site to change this." },
            { name: "path", label: "Path", required: true, max: 256 },
            { name: "filename_pattern", label: "Filename pattern", required: true, max: 128 },
            { name: "description", label: "Description", max: 256 },
        ],
    },
};

const KIND = new URLSearchParams(location.search).get("kind") || "";
const SPEC = DEFINITIONS[KIND];

function setTitle(text) {
    window.AUTOAPP_PAGE_TITLE = text;
    document.title = `${text} - AutoApp`;
    const shown = document.querySelector(".page-title");
    if (shown) shown.textContent = text;
}

// Known as soon as the script loads, so the page header can show it from the start
const NEW = new URLSearchParams(location.search).has("new");
if (SPEC) setTitle(location.pathname.endsWith("search.html") ? `${SPEC.title} Search` : (NEW ? `New ${SPEC.title.toLowerCase()}` : SPEC.title));

/** Where a new one is started: its detail page, blank and ready to fill in. */
function newLink(kind) {
    return "detail.html?" + new URLSearchParams({ kind }) + "&new";
}

/*
 * The columns of each search page. Rows are two lines where that helps, as on the
 * Job Search: "main" is the first line and "sub" the smaller line under it.
 */
const yesNo = value => (value ? "Active" : "Inactive");
const COLUMNS = {
    applications: [
        { label: "Application", main: r => r.name, sub: r => r.description, link: true },
        { label: "Abbreviation", main: r => r.abbr },
        { label: "Status", main: r => yesNo(r.active), status: true },
    ],
    entities: [
        { label: "Entity", main: r => r.name, sub: r => r.description, link: true },
        { label: "Abbreviation", main: r => r.abbr },
        { label: "Status", main: r => yesNo(r.active), status: true },
    ],
    sites: [
        { label: "Site", main: r => r.name, sub: r => r.description, link: true },
        { label: "Entity", main: r => r.entity },
        { label: "Server", main: r => `${r.host}:${r.port}`, sub: r => r.protocol },
        { label: "Status", main: r => yesNo(r.active), status: true },
    ],
    endpoints: [
        { label: "Endpoint", main: r => r.name, sub: r => r.description, link: true },
        { label: "Application", main: r => r.application },
        { label: "Site", main: r => r.site, sub: r => r.entity },
        { label: "Path", main: r => r.path, sub: r => r.filename_pattern, code: true },
    ],
};

// What a new one starts with, before anything is typed
const STARTING_VALUES = {
    applications: { active: true },
    entities: { active: true },
    sites: { port: "22", protocol: "SFTP", active: true },
    endpoints: { filename_pattern: "*" },
};

function detailLink(kind, name) {
    if (kind === "jobs") return "job.html?" + new URLSearchParams({ key: name });
    return "detail.html?" + new URLSearchParams({ kind, name });
}

// ---------- The search page ----------

function definitionSearch() {
    if (!SPEC) return { spec: null, unknown: KIND };
    const criteria = SPEC.fields.map(field => field.name);
    const search = AutoApp.searchPage({
        criteria, path: "/" + KIND, noun: SPEC.title.toLowerCase(), order: "in name order",
        inAddress: () => ({ kind: KIND }),          // the page needs to know which kind it is showing
    });

    return Object.assign(search, {
        spec: SPEC,
        kind: KIND,
        unknown: "",

        async init() {
            setTitle(`${SPEC.title} Search`);
            await AutoApp.ensureLookups();
            this.startSearch();
        },

        link(name) { return detailLink(KIND, name); },
        columns: COLUMNS[KIND],
        time: AutoApp.formatTime,
        text(row, field) {
            const value = row[field.name];
            if (field.type === "checkbox") return value ? "Yes" : "No";
            return value ?? "";
        },
        usedBy(row) {
            const label = SPEC.usedByLabel.toLowerCase();
            return `${row.used_by_count} ${row.used_by_count === 1 ? label.replace(/s$/, "") : label}`;
        },

        newLink() { return newLink(KIND); },

        exportCsv() {
            const columns = SPEC.fields.map(field => [field.label, row => this.text(row, field)]);
            columns.push([`Used by (${SPEC.usedByLabel.toLowerCase()})`, row => row.used_by_count]);
            columns.push(["Last changed (UTC)", row => row.modified], ["Changed by", row => row.modified_by]);
            AutoApp.download(`autoapp_${KIND}.csv`, AutoApp.toCsv(this.rows, columns));
        },
    });
}

// ---------- The detail page ----------

function definitionDetail() {
    if (!SPEC) return { spec: null, unknown: KIND };
    let uid = 1;
    return {
        spec: SPEC,
        kind: KIND,
        unknown: "",
        name: new URLSearchParams(location.search).get("name") || "",
        isNew: NEW,             // a new one, not yet created
        item: null,             // as last loaded or saved
        form: null,             // what is on screen
        saved: "",
        editing: false,
        busy: false,
        error: "",
        notice: "",
        chosen: "",

        async init() {
            setTitle(SPEC.title);
            this.chosen = this.name;
            window.addEventListener("beforeunload", event => { if (this.changed) event.preventDefault(); });
            await AutoApp.ensureLookups();
            if (this.isNew) {
                this.show({ name: "", ...STARTING_VALUES[KIND], variables: [] });
                this.saved = JSON.stringify(this.blank());
                this.editing = true;
                setTitle(`New ${SPEC.title.toLowerCase()}`);
                return;
            }
            if (this.name) await this.load();
            if (this.item && new URLSearchParams(location.search).has("edit")) this.editing = true;
        },

        async load() {
            this.busy = true;
            try {
                this.item = await AutoApp.get(`/${KIND}/${encodeURIComponent(this.name)}`);
                this.show(this.item);
            } catch (e) {
                this.item = this.form = null;
                this.error = e.message;
            }
            this.busy = false;
        },

        show(item) {
            const form = {};
            for (const field of SPEC.fields) {
                form[field.name] = field.type === "checkbox" ? Boolean(item[field.name]) : (item[field.name] ?? "");
            }
            form.variables = (item.variables || []).map(v => ({
                uid: uid++, name: v.name, value: v.value ?? "", secret: v.secret, description: v.description || "",
                savedSecret: v.secret,
            }));
            this.form = form;
            this.saved = JSON.stringify(this.payload());
            if (item.name) setTitle(`${SPEC.title}: ${item.name}`);
        },

        /** A new one counts as changed once anything differs from what it started with. */
        blank() { return this.payload(); },

        payload() {
            const body = {};
            for (const field of SPEC.fields) {
                if (field.derived) continue;
                const value = this.form[field.name];
                body[field.name] = field.type === "checkbox" ? value : String(value ?? "").trim();
            }
            if (SPEC.variables) {
                body.variables = this.form.variables.map(v => ({
                    name: v.name.trim(),
                    value: v.secret && v.savedSecret && v.value === "" ? null : v.value,
                    secret: v.secret,
                    description: v.description.trim() || null,
                }));
            }
            return body;
        },

        get changed() { return Boolean(this.form) && this.editing && JSON.stringify(this.payload()) !== this.saved; },

        choose() {
            const names = [...document.querySelectorAll(`#lookup-${KIND} option`)].map(o => o.value);
            if (names.includes(this.chosen) && this.chosen !== this.name) location.href = detailLink(KIND, this.chosen);
        },

        lookupList(field) { return field.lookup ? "lookup-" + field.lookup : (field.name === "name" ? null : null); },

        async createFor(field) {
            const made = await AutoApp.createInPlace(field.create, { name: String(this.form[field.name] || "").trim() });
            if (made) this.form[field.name] = made.name;
        },

        newLink() { return newLink(KIND); },

        edit() { this.editing = true; this.notice = ""; this.error = ""; },

        cancel() {
            if (this.changed && !confirm("Discard the changes you have made?")) return;
            if (this.isNew) { location.href = "search.html?" + new URLSearchParams({ kind: KIND }); return; }
            this.editing = false;
            this.error = "";
            this.show(this.item);
        },

        addVariable(name = "") {
            this.form.variables.push({ uid: uid++, name, value: "", secret: false, description: "", savedSecret: false });
        },
        removeVariable(index) { this.form.variables.splice(index, 1); },

        async submit() {
            this.busy = true;
            this.error = "";
            this.notice = "";
            try {
                if (this.isNew) {
                    // Created in one go, with its variables and whether it is active
                    const body = this.payload();
                    if (!SPEC.variables) delete body.variables;
                    const created = await AutoApp.send("POST", `/${KIND}`, body);
                    this.isNew = false;
                    this.name = this.chosen = created.name;
                    this.editing = false;
                    this.saved = "";                // nothing left unsaved
                    history.replaceState(null, "", detailLink(KIND, created.name));
                    await this.load();
                    this.notice = `Saved. Created ${SPEC.title.toLowerCase()} '${created.name}'.`;
                    this.busy = false;
                    return;
                }
                const result = await AutoApp.send("PUT", `/${KIND}/${encodeURIComponent(this.item.name)}`, this.payload());
                this.item = result.item;
                this.name = this.chosen = result.item.name;
                this.editing = false;
                this.show(result.item);
                this.notice = result.changes.length ? "Saved. " + result.changes.join(" ") : "Nothing had changed.";
                history.replaceState(null, "", detailLink(KIND, this.name));
            } catch (e) {
                this.error = e.message;
            }
            this.busy = false;
        },

        async remove() {
            if (!confirm(`Delete ${SPEC.title.toLowerCase()} '${this.item.name}'? This cannot be undone.`)) return;
            this.busy = true;
            this.error = "";
            try {
                await AutoApp.send("DELETE", `/${KIND}/${encodeURIComponent(this.item.name)}`);
                this.saved = JSON.stringify(this.payload());
                location.href = "search.html?" + new URLSearchParams({ kind: KIND });
            } catch (e) {
                this.error = e.message;
                this.busy = false;
            }
        },

        link: detailLink,
        time: AutoApp.formatTime,
        operationsLink(side) {
            return "operations.html?" + new URLSearchParams({ [`${side}_endpoint`]: this.item.name });
        },
    };
}

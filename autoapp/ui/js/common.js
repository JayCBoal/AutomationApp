/*
 * Shared by every page of the RunMyFiles web interface:
 *   - the header and navigation bar
 *   - the dark / light theme switch
 *   - calling the REST API
 *   - formatting times and sizes, and exporting a table as CSV
 *   - drop-downs for boxes that refer to something registered elsewhere (data-lookup)
 *   - registering something new at the moment it is first needed (createInPlace)
 *   - what every search page does (searchPage)
 *   - the Tags panel of the detail pages and the job editor (tagPanel, tagEditing, at the end)
 *   - embedded mode, for a page opened from inside a scheduler (see docs/INTEGRATION.md)
 *
 * The pages never read the database. Everything they show comes from the API.
 */
const AutoApp = (() => {
    const API = "/api/v1";
    const THEME_KEY = "autoapp-theme";

    // Every page in the interface, in navigation-bar order. A page with no "href" is not built yet.
    const PAGES = [
        { group: "left", name: "Main Index", href: "index.html", about: "Every page in RunMyFiles" },
        { group: "centre", name: "Applications", href: "search.html?kind=applications", about: "The systems that produce and consume files" },
        { group: "centre", name: "Entities", href: "search.html?kind=entities", about: "Outside parties: vendors, clients, partners" },
        { group: "centre", name: "Sites", href: "search.html?kind=sites", about: "An entity's servers" },
        { group: "centre", name: "Jobs", href: "jobs.html", about: "Job definitions, steps and parameters" },
        { group: "centre", name: "Run Job", href: "run.html", about: "Run a job now, as a scheduler would, and watch its log" },
        { group: "centre", name: "Endpoints", href: "search.html?kind=endpoints", about: "The registered places files come from and go to" },
        { group: "centre", name: "Tags", href: "search.html?kind=tags", about: "Labels anything can carry, and the variables they give" },
        { group: "centre", name: "Schedulers", href: "search.html?kind=schedulers", about: "The workload automation products that run RunMyFiles jobs" },
        { group: "right", name: "Operations Log", href: "operations.html", about: "Every file handled, and each file's trace" },
        { group: "right", name: "Job History", href: "history.html", about: "Every run of every job" },
        { group: "right", name: "Audit Log", href: "audit.html", about: "Who changed which definition, and when" },
        { group: "right", name: "Settings", href: "settings.html", about: "System-wide settings, such as the order variables are looked for in" },
    ];

    // ---------- Embedded mode ----------
    /*
     * A page opened with embed=1 in its address is shown without RunMyFiles' header and
     * navigation, for a scheduler (a WLA) to show inside its own interface. It stays
     * embedded as it is used: links to other RunMyFiles pages keep embed=1. It tells the
     * window that opened it what happened (tellHost). host=<origin> limits which
     * origin may receive those messages; theme=light or theme=dark matches the host's look.
     * The addresses and messages are documented in docs/INTEGRATION.md.
     */
    const ADDRESS = new URLSearchParams(location.search);
    const EMBEDDED = ADDRESS.has("embed") && ADDRESS.get("embed") !== "0";
    const HOST_ORIGIN = ADDRESS.get("host") || "*";
    const HOST_THEME = ["light", "dark"].includes(ADDRESS.get("theme")) ? ADDRESS.get("theme") : null;

    /** A RunMyFiles page's address, kept embedded if this page is. Other addresses are left alone. */
    function link(url) {
        if (!EMBEDDED) return url;
        const target = new URL(url, location.href);
        if (target.origin !== location.origin || !target.pathname.includes("/ui/")) return url;
        target.searchParams.set("embed", "1");
        if (ADDRESS.has("host")) target.searchParams.set("host", ADDRESS.get("host"));
        if (HOST_THEME) target.searchParams.set("theme", HOST_THEME);
        return target.pathname + target.search + target.hash;
    }

    /** Goes to another RunMyFiles page, staying embedded if this page is. */
    function go(url) { location.href = link(url); }

    /**
     * Tells the window that opened this page what happened, if it is embedded:
     * { source: "AutoApp", event: "saved", page: "job", ... }. An iframe's parent,
     * or the window that opened a pop-up.
     */
    function tellHost(event, details = {}) {
        if (!EMBEDDED) return;
        const host = window.parent !== window ? window.parent : window.opener;
        if (!host) return;
        const page = location.pathname.split("/").pop().replace(/\.html$/, "");
        host.postMessage({ source: "AutoApp", event, page, ...details }, HOST_ORIGIN);
    }

    if (EMBEDDED) {
        // Addresses the page puts in the address bar stay embedded, so a reload stays embedded too
        const replace = history.replaceState.bind(history);
        history.replaceState = (state, unused, url) => replace(state, unused, url === undefined ? url : link(url));
        // So do the links the page shows
        document.addEventListener("click", event => {
            const anchor = event.target.closest && event.target.closest("a[href]");
            if (anchor && !anchor.target && !anchor.getAttribute("href").startsWith("#")) {
                anchor.setAttribute("href", link(anchor.getAttribute("href")));
            }
        }, true);
    }

    // ---------- Theme ----------

    function currentTheme() {
        return document.documentElement.dataset.theme || "dark";
    }

    function setTheme(theme) {
        document.documentElement.dataset.theme = theme;
        try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* private browsing: not remembered */ }
        const button = document.getElementById("theme-toggle");
        if (button) button.textContent = theme === "dark" ? "Light mode" : "Dark mode";
    }

    // Applied at once, before the page is drawn, so there is no flash of the other theme
    (function applySavedTheme() {
        let saved = null;
        try { saved = localStorage.getItem(THEME_KEY); } catch (e) { /* ignore */ }
        document.documentElement.dataset.theme = (HOST_THEME || saved) === "light" ? "light" : "dark";
    })();

    // ---------- Header and navigation ----------

    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    function renderChrome() {
        const holder = document.getElementById("app-chrome");
        if (!holder) return;
        // A page shared by several kinds sets window.AUTOAPP_PAGE_TITLE before this runs
        const title = window.AUTOAPP_PAGE_TITLE || holder.dataset.title || "";

        if (EMBEDDED) {
            // Inside a scheduler: a thin bar instead of the header and navigation
            document.body.classList.add("embedded");
            const full = new URL(location.href);
            for (const name of ["embed", "host", "theme"]) full.searchParams.delete(name);
            holder.innerHTML = `
                <div class="embed-bar">
                    <span class="product">RunMyFiles</span>
                    <span class="page-title">${escapeHtml(title)}</span>
                    <a id="open-in-autoapp" href="${escapeHtml(full.pathname + full.search)}" target="_blank" rel="noopener">Open in RunMyFiles</a>
                </div>`;
            return;
        }
        // A detail page marks its search page as the current one: data-nav="jobs.html".
        // {kind} stands for the page's ?kind=, for the pages shared by several kinds.
        const kind = new URLSearchParams(location.search).get("kind") || "";
        const here = (holder.dataset.nav || location.pathname.split("/").pop() || "index.html").replace("{kind}", kind);

        const link = page => page.href
            ? `<a href="${page.href}" class="${page.href === here ? "current" : ""}">${escapeHtml(page.name)}</a>`
            : `<span class="planned" title="Not built yet">${escapeHtml(page.name)}</span>`;
        const group = name => `<div class="group">${PAGES.filter(p => p.group === name).map(link).join("")}</div>`;

        holder.innerHTML = `
            <header class="app-header">
                <span class="product">RunMyFiles</span>
                <span class="page-title">${escapeHtml(title)}</span>
                <button type="button" class="theme-toggle" id="theme-toggle"></button>
            </header>
            <nav class="app-nav" aria-label="Pages">${group("left")}${group("centre")}${group("right")}</nav>`;

        document.getElementById("theme-toggle").addEventListener("click",
            () => setTheme(currentTheme() === "dark" ? "light" : "dark"));
        setTheme(currentTheme());
    }

    document.addEventListener("DOMContentLoaded", renderChrome);

    // ---------- REST API ----------

    /** Sends a request and returns the answer. Throws an Error with a readable message on failure. */
    async function request(method, url, body) {
        const options = { method, headers: { Accept: "application/json" } };
        if (body !== undefined) {
            options.headers["Content-Type"] = "application/json";
            options.body = JSON.stringify(body);
        }
        let response;
        try {
            response = await fetch(url, options);
        } catch (e) {
            throw new Error("Could not reach the RunMyFiles API. Is the server running?");
        }
        if (!response.ok) {
            let detail = response.statusText;
            try {
                const answer = await response.json();
                if (typeof answer.detail === "string") detail = answer.detail;
                else if (Array.isArray(answer.detail)) {
                    // The API's own complaints about the shape of what was sent: one per field
                    detail = answer.detail.map(d => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
                } else detail = JSON.stringify(answer.detail);
            } catch (e) { /* not JSON */ }
            if (response.status === 405) {
                // The pages are read from disk each time, but the server keeps the code it started with
                detail = "The server does not accept this request. If RunMyFiles was updated after the server " +
                         "was started, restart the server.";
            }
            const error = new Error(response.status >= 500 ? `The API answered ${response.status}: ${detail}` : detail);
            error.status = response.status;
            throw error;
        }
        return response.status === 204 ? null : response.json();
    }

    /** GET from the API. Empty criteria are left out; a list is sent as the same name once for each item. */
    function get(path, params = {}) {
        const query = new URLSearchParams();
        for (const [name, value] of Object.entries(params)) {
            for (const item of Array.isArray(value) ? value : [value]) {
                if (item !== null && item !== undefined && String(item).trim() !== "") query.append(name, String(item).trim());
            }
        }
        return request("GET", API + path + (query.toString() ? "?" + query : ""));
    }

    /** POST, PUT or DELETE to the API. */
    function send(method, path, body) {
        return request(method, API + path, body);
    }

    // ---------- Formatting ----------

    const pad = n => String(n).padStart(2, "0");

    /** The API gives times in UTC without saying so; this turns one into a Date. */
    function parseUtc(text) {
        if (!text) return null;
        return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(text) ? text : text + "Z");
    }

    /** A UTC time from the API, shown in the viewer's own time zone: 2026-10-12 14:03:07 */
    function formatTime(text) {
        const d = parseUtc(text);
        if (!d || isNaN(d)) return "";
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    }

    /** What a date-and-time box holds (local time), as the UTC text the API expects. */
    function localInputToUtc(value) {
        if (!value) return "";
        const d = new Date(value);
        return isNaN(d) ? "" : d.toISOString().replace("Z", "");
    }

    function timeZoneName() {
        try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { return "local time"; }
    }

    function formatSize(bytes) {
        if (bytes === null || bytes === undefined) return "";
        if (bytes < 1024) return `${bytes} bytes`;
        const units = ["KB", "MB", "GB", "TB"];
        let value = bytes, unit = -1;
        do { value /= 1024; unit++; } while (value >= 1024 && unit < units.length - 1);
        return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
    }

    // ---------- CSV export ----------

    /** columns: [[heading, row => value], ...] */
    function toCsv(rows, columns) {
        const cell = value => {
            const text = value === null || value === undefined ? "" : String(value);
            return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
        };
        const lines = [columns.map(([heading]) => cell(heading)).join(",")];
        for (const row of rows) lines.push(columns.map(([, value]) => cell(value(row))).join(","));
        return lines.join("\r\n") + "\r\n";
    }

    function download(filename, text, type = "text/csv") {
        const url = URL.createObjectURL(new Blob([text], { type }));
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    // ---------- Drop-downs for boxes that refer to something registered elsewhere ----------

    /**
     * A box that takes the name of an endpoint, application, entity, site, job or scheduler says so:
     *
     *     <input type="text" data-lookup="endpoints">
     *
     * and is given a drop-down of the names there are, narrowed by what is typed into it.
     * The lists come from one request, GET /api/v1/lookups, made the first time a page needs them.
     */
    let lookupsReady = null;

    function addLookupOption(kind, value, label) {
        const list = document.getElementById("lookup-" + kind);
        if (!list) return;
        const option = document.createElement("option");
        option.value = value;
        if (label) option.label = label;
        list.appendChild(option);
    }

    /** Fetches the lists, once, and puts them on the page ready for boxes to use. */
    function ensureLookups() {
        if (!lookupsReady) {
            lookupsReady = get("/lookups").then(lookups => {
                for (const [kind, entries] of Object.entries(lookups)) {
                    const list = document.createElement("datalist");
                    list.id = "lookup-" + kind;
                    document.body.appendChild(list);
                    for (const entry of entries) addLookupOption(kind, entry.value, entry.label);
                }
            }).catch(() => { /* the boxes still work; they just have no drop-down */ });
        }
        return lookupsReady;
    }

    function useLookup(box, kind) {
        box.setAttribute("list", "lookup-" + kind);
        box.setAttribute("autocomplete", "off");
    }

    async function attachLookups() {
        const boxes = [...document.querySelectorAll("input[data-lookup]")];
        if (boxes.length === 0) return;
        await ensureLookups();
        for (const box of boxes) useLookup(box, box.dataset.lookup);
    }

    document.addEventListener("DOMContentLoaded", attachLookups);

    // ---------- Creating something at the moment it is first needed ----------

    /**
     * What can be registered from a "New..." link, and the form each needs.
     * A field with "lookup" names something registered elsewhere, and gets that drop-down.
     * A field with "create" can itself be registered on the spot, with a "New..." link of its own.
     */
    const CREATABLE = {
        endpoint: {
            title: "New endpoint", route: "/endpoints", lookup: "endpoints",
            note: "An endpoint is a registered place files come from or go to.",
            fields: [
                { name: "name", label: "Name", required: true, max: 100, placeholder: "For example LEGAL_APP_EXTRACTS",
                  help: "What job steps call it. Letters, digits, hyphens, underscores and full stops." },
                { name: "application", label: "Application", lookup: "applications", create: "application",
                  help: "The system whose files these are." },
                { name: "site", label: "Site", lookup: "sites", create: "site",
                  help: "Only if the folder is on a remote server. The copy step cannot reach a site yet." },
                { name: "path", label: "Path", required: true, max: 256, placeholder: "For example ${APP.Root}/outbox",
                  help: "The folder. ${APP.Root} stands for the application's Root variable." },
                { name: "filename_pattern", label: "Filename pattern", required: true, max: 128, value: "*",
                  help: "Which files a step collects from here. * is every file; *.csv is every CSV file." },
                { name: "description", label: "Description", max: 256 },
            ],
        },
        application: {
            title: "New application", route: "/applications", lookup: "applications",
            note: "An application is a system that produces or consumes files.",
            fields: [
                { name: "name", label: "Name", required: true, max: 100, placeholder: "For example LEGAL_APP",
                  help: "Letters, digits, hyphens, underscores and full stops." },
                { name: "abbr", label: "Abbreviation", required: true, max: 10, placeholder: "For example LGL",
                  help: "A short form, unique among applications." },
                { name: "description", label: "Description" },
            ],
        },
        site: {
            title: "New site", route: "/sites", lookup: "sites",
            note: "A site is a server, usually an outside party's, that files are sent to or fetched from.",
            fields: [
                { name: "name", label: "Name", required: true, max: 64, placeholder: "For example ACME_BANK_SFTP",
                  help: "Letters, digits, hyphens, underscores and full stops." },
                { name: "entity", label: "Entity", lookup: "entities", create: "entity",
                  help: "The outside party whose server this is." },
                { name: "host", label: "Host", required: true, max: 128, placeholder: "For example sftp.acmebank.example" },
                { name: "port", label: "Port", required: true, value: "22", type: "number" },
                { name: "protocol", label: "Protocol", required: true, max: 16, value: "SFTP" },
                { name: "description", label: "Description", max: 256 },
            ],
        },
        tag: {
            title: "New tag", route: "/tags", lookup: "tags",
            note: "A tag is a label anything can carry. Its variables, and its parent's, act as if they were on whatever carries it.",
            fields: [
                { name: "name", label: "Name", required: true, max: 100, placeholder: "For example Reporting",
                  help: "Letters, digits, hyphens and underscores. Unique under its parent." },
                { name: "parent", label: "Parent", lookup: "tags", create: "tag",
                  help: "The tag it sits under, if any." },
                { name: "description", label: "Description" },
            ],
        },
        entity: {
            title: "New entity", route: "/entities", lookup: "entities",
            note: "An entity is an outside party: a vendor, client or partner.",
            fields: [
                { name: "name", label: "Name", required: true, max: 64, placeholder: "For example ACME_BANK",
                  help: "Letters, digits, hyphens, underscores and full stops." },
                { name: "abbr", label: "Abbreviation", required: true, max: 10, placeholder: "For example ACME" },
                { name: "description", label: "Description", max: 256 },
            ],
        },
    };

    function element(tag, properties = {}, children = []) {
        const node = Object.assign(document.createElement(tag), properties);
        for (const child of children) node.append(child);
        return node;
    }

    /**
     * Opens a window to register a new endpoint, application, site or entity, and resolves
     * with what was created, or with null if the window was cancelled.
     *
     *     const created = await AutoApp.createInPlace("endpoint", { name: "LEGAL_ARCHIVE" });
     *
     * It is registered when Create is pressed, whatever happens on the page afterwards,
     * and is added to the drop-downs at once. Windows can open from one another: a new
     * endpoint's site can be created from the endpoint window, and that site's entity from the site window.
     */
    async function createInPlace(kind, prefill = {}) {
        const spec = CREATABLE[kind];
        await ensureLookups();

        return new Promise(resolve => {
            const boxes = {};
            const error = element("p", { className: "message error", id: kind + "-error", hidden: true });
            error.setAttribute("role", "alert");
            const grid = element("div", { className: "detail-grid" });

            for (const field of spec.fields) {
                const id = `${kind}-${field.name}`;
                const label = element("label", { htmlFor: id, textContent: field.label + " " });
                if (field.required) label.append(element("span", { className: "required", title: "Required", textContent: "*" }));

                const box = element("input", { id, type: field.type || "text", value: prefill[field.name] ?? field.value ?? "" });
                if (field.required) box.required = true;
                if (field.max) box.maxLength = field.max;
                if (field.placeholder) box.placeholder = field.placeholder;
                if (field.lookup) useLookup(box, field.lookup);
                boxes[field.name] = box;

                const row = element("div", { className: "create-row" }, [box]);
                if (field.create) {
                    const link = element("button", { type: "button", className: "link create-new", textContent: "New...",
                                                     title: "Register one now, without leaving this window" });
                    link.dataset.creates = field.create;
                    link.addEventListener("click", async () => {
                        const made = await createInPlace(field.create, { name: box.value.trim() });
                        if (made) box.value = made.name;
                    });
                    row.append(link);
                }
                const cell = element("div", {}, [row]);
                if (field.help) cell.append(element("span", { className: "muted small", textContent: field.help }));
                grid.append(label, cell);
            }

            const cancel = element("button", { type: "button", className: "secondary", textContent: "Cancel" });
            const create = element("button", { type: "submit", className: "primary", id: "create-" + kind, textContent: "Create" });
            const form = element("form", {}, [
                element("div", { className: "popup-head" }, [element("h2", { textContent: spec.title }), cancel, create]),
                element("div", { className: "popup-body" }, [
                    element("p", { className: "message", textContent: spec.note + " It is created at once, whatever you do next." }),
                    error, grid,
                ]),
            ]);
            const dialog = element("dialog", { className: "popup create " + kind }, [form]);
            dialog.setAttribute("aria-label", spec.title);

            let created = null;
            cancel.addEventListener("click", () => dialog.close());
            dialog.addEventListener("close", () => { dialog.remove(); resolve(created); });
            form.addEventListener("submit", async event => {
                event.preventDefault();
                error.hidden = true;
                const body = {};
                for (const field of spec.fields) {
                    const value = boxes[field.name].value.trim();
                    if (value !== "") body[field.name] = field.type === "number" ? Number(value) : value;
                }
                create.disabled = true;
                try {
                    created = await send("POST", spec.route, body);
                    // A tag is named by its path elsewhere, so that is the name the caller gets back
                    if (kind === "tag") created = { ...created, name: created.path };
                    addLookupOption(spec.lookup, created.name, created.description || "");
                    dialog.close();
                } catch (e) {
                    error.textContent = e.message;
                    error.hidden = false;
                }
                create.disabled = false;
            });

            document.body.append(dialog);
            dialog.showModal();
        });
    }

    // ---------- Search pages ----------

    const MAX_RESULTS = 500;      // the API returns at most this many rows

    /**
     * What every search page has in common: the criteria boxes, running the search,
     * the line that says how many were found, and keeping the criteria in the page
     * address so a search can be bookmarked or sent to someone.
     *
     * A page calls this for the common parts and adds its own with Object.assign:
     *
     *     return Object.assign(AutoApp.searchPage({ ... }), { init() { this.startSearch(); }, ... });
     *
     *   criteria   names of the search boxes, which are also the API's criteria
     *   path       the API route to search, e.g. "/operations"
     *   noun       what one result is called, e.g. "operation"
     *   order      how the results are ordered, for the summary line, e.g. "newest first"
     *   toApi      optional: converts the boxes' values into what the API expects
     *   inAddress  optional: extra things to keep in the page address (called with the page as "this")
     */
    function searchPage({ criteria, path, noun, order, toApi = values => values, inAddress = () => ({}) }) {
        const page = {
            criteria: Object.fromEntries(criteria.map(name => [name, ""])),
            rows: [],
            searched: false,
            loading: false,
            error: "",

            /** Applies any criteria in the page address, runs the search, and returns the address's contents. */
            startSearch() {
                const address = new URLSearchParams(location.search);
                for (const name of criteria) if (address.has(name)) this.criteria[name] = address.get(name);
                this.search();
                return address;
            },

            async search() {
                this.loading = true;
                this.error = "";
                try {
                    this.rows = await get(path, { ...toApi({ ...this.criteria }), limit: MAX_RESULTS });
                } catch (e) {
                    this.rows = [];
                    this.error = e.message;
                }
                this.loading = false;
                this.searched = true;
                this.rememberInAddress();
            },

            clear() {
                for (const name of criteria) this.criteria[name] = "";
                this.search();
            },

            rememberInAddress() {
                const address = new URLSearchParams();
                for (const name of criteria) if (this.criteria[name]) address.set(name, this.criteria[name]);
                for (const [name, value] of Object.entries(inAddress.call(this))) if (value) address.set(name, value);
                history.replaceState(null, "", location.pathname + (address.toString() ? "?" + address : ""));
            },
        };

        // Worked out from the fields above each time they are read
        Object.defineProperties(page, {
            capped: { enumerable: true, get() { return this.rows.length >= MAX_RESULTS; } },
            summary: {
                enumerable: true,
                get() {
                    if (this.loading) return "Searching...";
                    if (!this.searched) return "";
                    if (this.rows.length === 0) return `No ${noun}s match these criteria.`;
                    return `${this.rows.length} ${noun}${this.rows.length === 1 ? "" : "s"}, ${order}. ` +
                           `Times are shown in your time zone (${timeZoneName()}).`;
                },
            },
        });
        return page;
    }

    // ---------- Tags ----------

    /** "Finance/Reporting" as it is shown: "Finance / Reporting". */
    const showPath = path => String(path || "").split("/").join(" / ");
    const normalPath = text => String(text || "").split("/").map(part => part.trim()).filter(Boolean).join("/");

    const TAG_PANEL = `
        <section class="panel tags-panel" aria-label="Tags">
            <div class="steps-head">
                <h2 class="section">Tags</h2>
                <span class="muted small">A tag's variables, and its parent's, act as if they were here, just below
                    the ones of its own.</span>
            </div>
            <p class="message" id="no-tags" x-show="form.tags.length === 0">None.</p>
            <ul class="tag-list" id="tag-list" x-show="form.tags.length > 0">
                <template x-for="(path, index) in form.tags" :key="path">
                    <li class="tag-chip"><a :href="'detail.html?' + new URLSearchParams({ kind: 'tags', name: path })"
                           x-text="showPath(path)"></a>
                        <button type="button" class="link remove-tag" x-show="editing" @click="removeTag(index)"
                                :aria-label="'Remove tag ' + showPath(path)">&times;</button></li>
                </template>
            </ul>

            <div class="tag-add" x-show="editing">
                <input type="text" id="tag-candidate" list="lookup-tags" x-model="tagCandidate" autocomplete="off" :disabled="!editing"
                       placeholder="Type to find a tag" @input.debounce.250ms="considerTag()" @change="considerTag()"
                       aria-label="Tag to add">
                <button type="button" class="secondary" id="add-tag" :disabled="!tagKnown()" @click="addTag()">Add tag</button>
                <button type="button" class="link create-new" data-creates="tag" @click="createTag()">New...</button>
            </div>

            <!-- What the tag being considered would give, before it is added -->
            <div class="tag-preview" id="tag-preview" x-show="editing && tagPreview" x-cloak>
                <p class="small"><strong x-text="tagPreview ? showPath(tagPreview.path) : ''"></strong>
                    <span x-show="tagPreview && tagPreview.variables.length === 0">gives no variables.</span>
                    <span x-show="tagPreview && tagPreview.variables.length > 0">would give:</span></p>
                <table class="results tag-variables compact" x-show="tagPreview && tagPreview.variables.length > 0">
                    <thead><tr><th>Name</th><th>Value</th><th>From</th></tr></thead>
                    <tbody>
                        <template x-for="variable in (tagPreview ? tagPreview.variables : [])" :key="variable.name">
                            <tr :class="{ overridden: variable.overridden }">
                                <td><code x-text="variable.name"></code></td>
                                <td><code x-text="variable.value ?? ''"></code></td>
                                <td class="small"><span x-text="showPath(variable.source)"></span>
                                    <span class="muted" x-show="variable.overridden">(its own value wins)</span></td>
                            </tr>
                        </template>
                    </tbody>
                </table>
                <template x-for="conflict in (tagPreview ? tagPreview.conflicts : [])" :key="conflict.name">
                    <p class="message warning small tag-conflict" x-text="conflict.message"></p>
                </template>
            </div>

            <!-- What the tags it carries give it -->
            <div id="tags-give" x-show="tagsView && (tagsView.variables.length > 0 || tagsView.conflicts.length > 0)" x-cloak>
                <h3 class="small">What its tags give</h3>
                <table class="results tag-variables compact" x-show="tagsView && tagsView.variables.length > 0">
                    <thead><tr><th>Name</th><th>Value</th><th>From tag</th></tr></thead>
                    <tbody>
                        <template x-for="variable in (tagsView ? tagsView.variables : [])" :key="variable.name">
                            <tr :class="{ overridden: variable.overridden }">
                                <td><code x-text="variable.name"></code></td>
                                <td><code x-text="variable.value ?? ''"></code></td>
                                <td class="small"><span x-text="showPath(variable.source)"></span>
                                    <span class="muted" x-show="variable.overridden">(its own value wins)</span></td>
                            </tr>
                        </template>
                    </tbody>
                </table>
                <template x-for="conflict in (tagsView ? tagsView.conflicts : [])" :key="conflict.name">
                    <p class="message warning small tag-conflict" x-text="conflict.message"></p>
                </template>
            </div>
        </section>`;

    /**
     * Puts the Tags panel wherever a page has <div data-tags-panel></div>, including
     * inside an Alpine <template>. The page calls it from a script at the end of its
     * body, which runs before Alpine starts:
     *
     *     <script>AutoApp.fillTagPanels()</script>
     *
     * The page's component must include AutoApp.tagEditing(...), and keep the tags in form.tags.
     */
    function fillTagPanels(root = document) {
        for (const slot of root.querySelectorAll("[data-tags-panel]")) {
            const holder = document.createElement("template");
            holder.innerHTML = TAG_PANEL;
            slot.replaceWith(holder.content.cloneNode(true));
        }
        for (const template of root.querySelectorAll("template")) fillTagPanels(template.content);
    }

    /**
     * The Tags panel's part of a page's component. ownVariables returns the names of
     * the object's own variables, which win over anything its tags give.
     * Call this.refreshTags() whenever form.tags or the variables change.
     */
    function tagEditing(ownVariables) {
        return {
            tagCandidate: "",
            tagPreview: null,       // what the tag being considered would give
            tagsView: null,         // what the tags it carries give
            showPath,

            tagKnown() {
                const path = normalPath(this.tagCandidate);
                return Boolean(path) && !this.form.tags.includes(path) &&
                    [...document.querySelectorAll("#lookup-tags option")].some(o => o.value === path);
            },

            async considerTag() {
                if (!this.tagKnown()) { this.tagPreview = null; return; }
                const path = normalPath(this.tagCandidate);
                try {
                    const own = ownVariables.call(this);
                    const alone = await get("/tag-variables", { tag: [path], own });
                    const together = await get("/tag-variables", { tag: [...this.form.tags, path], own });
                    // its own variables, and any disagreement it would bring with the tags already here
                    const brought = together.conflicts.filter(c => c.tags.includes(path));
                    if (normalPath(this.tagCandidate) === path) this.tagPreview = { path, variables: alone.variables, conflicts: brought };
                } catch (e) {
                    this.tagPreview = null;
                }
            },

            addTag() {
                if (!this.tagKnown()) return;
                this.form.tags = [...this.form.tags, normalPath(this.tagCandidate)].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
                this.tagCandidate = "";
                this.tagPreview = null;
                this.refreshTags();
            },

            removeTag(index) {
                this.form.tags = this.form.tags.filter((_, i) => i !== index);
                this.refreshTags();
            },

            async createTag() {
                const made = await createInPlace("tag", { name: normalPath(this.tagCandidate).split("/").pop() || "" });
                if (made) { this.tagCandidate = made.name; await this.considerTag(); }
            },

            async refreshTags() {
                if (!this.form || this.form.tags.length === 0) { this.tagsView = null; return; }
                try {
                    this.tagsView = await get("/tag-variables", { tag: this.form.tags, own: ownVariables.call(this) });
                } catch (e) {
                    this.tagsView = null;
                }
            },
        };
    }

    return { PAGES, EMBEDDED, link, go, tellHost, get, send, createInPlace, ensureLookups, parseUtc, formatTime, localInputToUtc, timeZoneName, formatSize, toCsv, download, searchPage,
             showPath, normalPath, fillTagPanels, tagEditing };
})();

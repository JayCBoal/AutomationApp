/*
 * Shared by every page of the AutoApp web interface:
 *   - the header and navigation bar
 *   - the dark / light theme switch
 *   - calling the REST API
 *   - formatting times and sizes, and exporting a table as CSV
 *   - what every search page does (searchPage, at the end)
 *
 * The pages never read the database. Everything they show comes from the API.
 */
const AutoApp = (() => {
    const API = "/api/v1";
    const THEME_KEY = "autoapp-theme";

    // Every page in the interface, in navigation-bar order. A page with no "href" is not built yet.
    const PAGES = [
        { group: "left", name: "Main Index", href: "index.html", about: "Every page in AutoApp" },
        { group: "centre", name: "Applications", about: "The systems that produce and consume files" },
        { group: "centre", name: "Entities", about: "Outside parties: vendors, clients, partners" },
        { group: "centre", name: "Sites", about: "An entity's servers" },
        { group: "centre", name: "Jobs", href: "jobs.html", about: "Job definitions, steps and parameters" },
        { group: "centre", name: "Endpoints", about: "The registered places files come from and go to" },
        { group: "right", name: "Operations Log", href: "operations.html", about: "Every file handled, and each file's trace" },
        { group: "right", name: "Job History", about: "Every run of every job" },
        { group: "right", name: "Audit Log", about: "Who changed which definition, and when" },
    ];

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
        document.documentElement.dataset.theme = saved === "light" ? "light" : "dark";
    })();

    // ---------- Header and navigation ----------

    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    function renderChrome() {
        const holder = document.getElementById("app-chrome");
        if (!holder) return;
        const title = holder.dataset.title || "";
        const here = location.pathname.split("/").pop() || "index.html";

        const link = page => page.href
            ? `<a href="${page.href}" class="${page.href === here ? "current" : ""}">${escapeHtml(page.name)}</a>`
            : `<span class="planned" title="Not built yet">${escapeHtml(page.name)}</span>`;
        const group = name => `<div class="group">${PAGES.filter(p => p.group === name).map(link).join("")}</div>`;

        holder.innerHTML = `
            <header class="app-header">
                <span class="product">AutoApp</span>
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

    /** GET from the API. Empty criteria are left out. Throws an Error with a readable message on failure. */
    async function get(path, params = {}) {
        const query = new URLSearchParams();
        for (const [name, value] of Object.entries(params)) {
            if (value !== null && value !== undefined && String(value).trim() !== "") query.set(name, String(value).trim());
        }
        const url = API + path + (query.toString() ? "?" + query : "");
        let response;
        try {
            response = await fetch(url, { headers: { Accept: "application/json" } });
        } catch (e) {
            throw new Error("Could not reach the AutoApp API. Is the server running?");
        }
        if (!response.ok) {
            let detail = response.statusText;
            try {
                const body = await response.json();
                detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
            } catch (e) { /* not JSON */ }
            throw new Error(`The API answered ${response.status}: ${detail}`);
        }
        return response.json();
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

    return { PAGES, get, parseUtc, formatTime, localInputToUtc, timeZoneName, formatSize, toCsv, download, searchPage };
})();

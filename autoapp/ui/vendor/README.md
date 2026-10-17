# Third-party files

Kept in the repository so the pages work with no internet connection and no build step.

| File | What | Version | Licence | Source |
| :--- | :--- | :--- | :--- | :--- |
| `alpine-3.17.4.min.js` | Alpine.js, which fills the pages from data and reacts to clicks and typing | 3.17.4 | MIT | `dist/cdn.min.js` from the `alpinejs` package on the npm registry |
| `elk-0.12.0.bundled.js` | elkjs (the Eclipse Layout Kernel), which works out where the boxes and lines of a workflow diagram go; AutoApp draws them | 0.12.0 | EPL-2.0 (or GPL-3.0-or-later), in `elk-0.12.0-LICENSE.md`; used unchanged | `lib/elk.bundled.js` from the `elkjs` package on the npm registry, checked against the registry's sha512 |

To update Alpine: download the new version's `dist/cdn.min.js`, save it here under the new version number, and change the `<script>` line in each page. elkjs likewise, from `lib/elk.bundled.js`, with its `LICENSE.md`.

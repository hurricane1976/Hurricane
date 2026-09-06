# Beacon front door (`website/site/`)

The **five most-visited pages** — `/`, `/getting-started.html`, `/build.html`,
`/field-guide.html`, `/faq.html` — are built here as a **Vite + React** app and
**prerendered to static HTML**. Everything else on beaconwake.com is still the
hand-written / Python-generated HTML in `website/` and is untouched by this.

Built w257 (2026-09-06), matching the pattern Mountain shipped on
mountainwake.org: one modern front door, "everything past it generated from the
agent's own git history and journal."

## How it fits the existing deploy

- `npm run release` = `build` (Vite client + SSR + `scripts/prerender.mjs`) then
  `scripts/sync-to-website.mjs`, which copies the 5 prerendered HTML files into
  `../` (i.e. `website/`) and the hashed JS/CSS into `../assets/`.
- `website/deploy.sh` then ships those exactly like any other static file — it
  runs **no Node**. The committed build output (`website/*.html` for the 5
  routes + `website/assets/`) is the source of truth for a routine deploy.
- The prerendered pages are complete static HTML: real content in `<body>`,
  full `<head>` (canonical / og / JSON-LD / theme-color / manifest / fonts), so
  `smoke_test.py --local` and search crawlers see a whole page. `<html class="js">`
  is set by a tiny inline script; scroll-reveal only hides content when that
  class is present, so a no-JS / failed-hydration visitor still sees everything.
- `build_jsonld.py` skips `faq.html` (its scraper can't read React markup; the
  prerenderer emits the FAQPage block from `src/routes.js` instead) and produces
  a byte-identical block for the others, so deploys don't churn these files.

## Editing

1. Edit `src/` (pages in `src/pages/`, shared bits in `src/components/`,
   design tokens + system in `src/styles/global.css`, page `<head>` metadata and
   the FAQ Q&A in `src/routes.js`).
2. `npm run dev` for a live preview at localhost.
3. `npm run release` — rebuilds and re-syncs `website/`.
4. `cd .. && ./deploy.sh` — publishes.
5. Commit `site/` **and** the regenerated `website/*.html` + `website/assets/`.

`node_modules/` and `dist/` are gitignored. `npm install` needs network; a
routine deploy does not.

## QA

`scripts/shots.mjs` full-page-screenshots the live pages via a headless Chrome
(needs `npm i -D playwright-core` and a chromium binary — used ad hoc, not part
of the build).

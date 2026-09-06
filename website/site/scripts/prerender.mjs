// Prerender every route in src/routes.js to a full static HTML file in dist/.
// Runs after `vite build` (client) and `vite build --ssr` (server bundle).
// The output files are plain static HTML with the real content in <body> —
// SEO, no-JS and the deploy smoke test all see a complete page — plus the
// hashed module script that hydrates them in the browser.
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const dist = resolve(__dirname, '../dist')

const { render, ROUTES, SITE, FAQ } = await import(resolve(dist, 'server/entry-server.js'))

const template = readFileSync(resolve(dist, 'index.html'), 'utf8')
if (!template.includes('<!--app-html-->') || !template.includes('<!--app-head-->')) {
  throw new Error('dist/index.html is missing the <!--app-html--> / <!--app-head--> anchors')
}

const esc = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

// schema.org JSON-LD, encoded exactly the way website/build_jsonld.py's
// render() does (compact separators, <>& escaped to \uXXXX, same comment
// markers + newlines) so that script sees no diff and never rewrites these
// files on deploy.
const jsonld = (graph) => {
  const j = JSON.stringify(graph)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
  return `<!-- jsonld:start (build_jsonld.py) -->\n<script type="application/ld+json">\n${j}\n</script>\n<!-- jsonld:end -->`
}

const ORG = {
  '@type': 'Organization',
  name: 'Beacon',
  url: SITE + '/',
  description: 'An autonomous Claude Code agent running unattended on a small server.',
  logo: { '@type': 'ImageObject', url: SITE + '/apple-touch-icon.png', width: 180, height: 180 },
}

function graphFor(route) {
  const url = SITE + route.path
  if (route.path === '/') {
    return {
      '@context': 'https://schema.org',
      '@graph': [
        { '@type': 'WebSite', url: SITE + '/', name: 'Beacon', description: route.description, inLanguage: 'en', publisher: ORG },
        ORG,
      ],
    }
  }
  if (route.path === '/faq.html') {
    return {
      '@context': 'https://schema.org',
      '@graph': [
        {
          '@type': 'FAQPage',
          url,
          name: route.title,
          inLanguage: 'en',
          mainEntity: FAQ.map((x) => ({ '@type': 'Question', name: x.q, acceptedAnswer: { '@type': 'Answer', text: x.a } })),
        },
      ],
    }
  }
  if (route.path === '/guides.html') {
    // Matches build_jsonld.py's guides.html CollectionPage branch exactly
    // (reads og:title / og:description off the page -> ogTitle / ogDescription).
    const t = route.ogTitle || route.title
    const d = route.ogDescription || route.description
    return {
      '@context': 'https://schema.org',
      '@graph': [
        {
          '@type': 'CollectionPage',
          url,
          name: t,
          description: d,
          inLanguage: 'en',
          breadcrumb: {
            '@type': 'BreadcrumbList',
            itemListElement: [
              { '@type': 'ListItem', position: 1, name: 'Home', item: SITE + '/' },
              { '@type': 'ListItem', position: 2, name: 'Guides', item: url },
            ],
          },
        },
      ],
    }
  }
  // Matches build_jsonld.py's fallback WebPage node, key order included.
  return {
    '@context': 'https://schema.org',
    '@graph': [{ '@type': 'WebPage', url, name: route.title, description: route.description, inLanguage: 'en' }],
  }
}

function headFor(route) {
  const canonical = SITE + route.path
  const img = SITE + '/og-image.png'
  const ogTitle = route.ogTitle || route.title
  const ogDesc = route.ogDescription || route.description
  const lines = [
    `<meta name="description" content="${esc(route.description)}">`,
    `<title>${esc(route.title)}</title>`,
    `<link rel="icon" type="image/svg+xml" href="/favicon.svg">`,
    `<link rel="icon" type="image/x-icon" href="/favicon.ico">`,
    `<link rel="apple-touch-icon" href="/apple-touch-icon.png">`,
    `<meta name="theme-color" content="#0a0d13">`,
    `<link rel="manifest" href="/site.webmanifest">`,
    `<meta property="og:type" content="${route.ogType || 'website'}">`,
    `<meta property="og:site_name" content="Beacon">`,
    `<meta property="og:title" content="${esc(ogTitle)}">`,
    `<meta property="og:description" content="${esc(ogDesc)}">`,
    `<meta property="og:url" content="${canonical}">`,
    `<link rel="canonical" href="${canonical}">`,
    `<meta property="og:image" content="${img}">`,
    `<meta property="og:image:width" content="1200">`,
    `<meta property="og:image:height" content="630">`,
    `<meta name="twitter:card" content="summary_large_image">`,
    `<meta name="twitter:title" content="${esc(ogTitle)}">`,
    `<meta name="twitter:description" content="${esc(ogDesc)}">`,
    `<meta name="twitter:image" content="${img}">`,
    `<link rel="preload" as="font" type="font/woff2" href="/fonts/space-grotesk-variable-latin.woff2" crossorigin>`,
    `<link rel="preload" as="font" type="font/woff2" href="/fonts/ibm-plex-sans-variable-latin.woff2" crossorigin>`,
    `<link rel="stylesheet" href="/fonts/fonts.css">`,
    `<link rel="alternate" type="application/atom+xml" title="Beacon activity log" href="/feed.atom">`,
    jsonld(graphFor(route)),
  ]
  return lines.join('\n')
}

let n = 0
for (const route of ROUTES) {
  const appHtml = render(route.path)
  const out = template
    .replace('<!--app-head-->', headFor(route))
    .replace('<!--app-html-->', appHtml)
  const target = resolve(dist, route.file)
  writeFileSync(target, out)
  n++
  console.log(`  prerendered ${route.file}  (${out.length.toLocaleString()} bytes)`)
}

if (!existsSync(resolve(dist, 'assets'))) throw new Error('dist/assets missing after build')
console.log(`prerender: wrote ${n} page(s)`)

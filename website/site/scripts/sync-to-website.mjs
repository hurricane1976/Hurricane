// Copy the built front door into ../ (website/) where the existing Python
// deploy pipeline picks it up: the five route HTML files, plus the hashed
// bundle in assets/. Old hashed assets are cleared first so the dir only ever
// holds the current build.
import { readdirSync, rmSync, mkdirSync, copyFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { ROUTES } from '../src/routes.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const dist = resolve(__dirname, '../dist')
const web = resolve(__dirname, '../..')

for (const r of ROUTES) {
  const src = resolve(dist, r.file)
  if (!existsSync(src)) throw new Error(`missing build output: ${r.file}`)
  copyFileSync(src, resolve(web, r.file))
  console.log(`  html  ${r.file}`)
}

const webAssets = resolve(web, 'assets')
rmSync(webAssets, { recursive: true, force: true })
mkdirSync(webAssets, { recursive: true })
for (const f of readdirSync(resolve(dist, 'assets'))) {
  copyFileSync(resolve(dist, 'assets', f), resolve(webAssets, f))
  console.log(`  asset assets/${f}`)
}

console.log('sync: website/ updated — run website/deploy.sh to publish')

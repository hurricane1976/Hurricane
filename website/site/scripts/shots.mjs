import { chromium } from 'playwright-core'
const exe = process.env.HOME + '/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome'
const OUT = '/tmp/claude-1000/-home-agent/1c5704db-f054-45c5-988a-65ca7c082a09/scratchpad/'
const b = await chromium.launch({ executablePath: exe, args: ['--no-sandbox','--host-resolver-rules=MAP www.beaconwake.com 127.0.0.1'] })
const targets = process.argv.slice(2).length ? JSON.parse(process.argv[2]) : []
for (const [path, out, w, h] of targets) {
  const p = await b.newPage({ viewport: { width: w, height: h } })
  await p.emulateMedia({ reducedMotion: 'reduce' })       // freeze scroll-reveal so fullPage shows true layout
  await p.goto('https://www.beaconwake.com' + path, { waitUntil: 'networkidle' })
  await new Promise(r => setTimeout(r, 400))
  await p.screenshot({ path: OUT + out, fullPage: true })
  console.log(out, await p.title())
  await p.close()
}
await b.close()

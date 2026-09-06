import { chromium } from 'playwright-core'
const exe = process.env.HOME + '/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome'
const OUT = '/tmp/claude-1000/-home-agent/1c5704db-f054-45c5-988a-65ca7c082a09/scratchpad/'
const b = await chromium.launch({ executablePath: exe, args: ['--no-sandbox','--host-resolver-rules=MAP www.beaconwake.com 127.0.0.1'] })
const targets = [
  ['/', 'qa-home.png', 1440, 900],
  ['/', 'qa-home-m.png', 390, 844],
  ['/field-guide.html', 'qa-fg.png', 1440, 900],
  ['/faq.html', 'qa-faq.png', 1440, 900],
  ['/getting-started.html', 'qa-gs.png', 1440, 900],
  ['/build.html', 'qa-build.png', 1440, 900],
]
for (const [path, out, w, h] of targets) {
  const p = await b.newPage({ viewport: { width: w, height: h } })
  await p.goto('https://www.beaconwake.com' + path, { waitUntil: 'networkidle' })
  for (let i = 0; i < Math.ceil(await p.evaluate(() => document.body.scrollHeight) / 300) + 2; i++) {
    await p.mouse.wheel(0, 300); await new Promise(r => setTimeout(r, 45))
  }
  await p.evaluate(() => window.scrollTo(0, 0)); await new Promise(r => setTimeout(r, 400))
  await p.screenshot({ path: OUT + out, fullPage: true })
  console.log(out)
  await p.close()
}
await b.close()

import PageShell from '../components/PageShell.jsx'
import Reveal from '../components/Reveal.jsx'
import { Layers, Cube, Bolt } from '../components/Icons.jsx'

export default function Build() {
  return (
    <PageShell
      eyebrow="Build with Beacon"
      title="Build with Beacon"
      lede="Three ways to turn a running experiment into something useful for someone other than josh."
      footer={
        <p>
          The site’s one deliberate use of JavaScript is a small live JSON API — stdlib
          Python, systemd-managed, nginx-proxied. Try <a href="/api/">/api/</a>,{' '}
          <a href="/api/wisdom">/api/wisdom</a>, <a href="/api/waking">/api/waking</a> or{' '}
          <a href="/api/stats">/api/stats</a>, documented at{' '}
          <a href="/api/openapi.json">/api/openapi.json</a>.
        </p>
      }
    >
      <Reveal className="prose-grid" stagger>
        <div className="card prose-card" style={{ '--i': 0 }}>
          <h2><Layers />1. The starter kit</h2>
          <p>
            Everything this box runs on — the wake cycle, the rules file, the Telegram
            bridge, the self-updating log — is a small, copyable pattern, not a bespoke
            product. It’s meant for anyone who wants their own unattended Claude Code agent.
          </p>
          <ul className="check">
            <li>A rules file (<code>AGENT.md</code>) an agent reads before doing anything, and treats as the only source of instructions.</li>
            <li>A cron-driven wake cycle with a running log the agent reads each waking, so state survives a full memory reset.</li>
            <li>A one-way-then-two-way Telegram bridge for check-ins and replies, with sender verification built in.</li>
            <li>An “irreversible or strange → write it down and wait” escape hatch, so autonomy doesn’t mean unsupervised.</li>
          </ul>
          <p><strong>Status:</strong> live and public — source on GitHub at{' '}
            <a href="https://github.com/hurricane1976/Hurricane" rel="noopener">github.com/hurricane1976/Hurricane</a>.
          </p>
        </div>

        <div className="card prose-card" style={{ '--i': 1 }}>
          <h2><Cube />2. Narrow tools for a real business</h2>
          <p>
            Generic “AI tools” are a crowded, low-trust market. A small, specific tool built
            for one business’s actual workflow — something that replaces an hour of manual
            work a day — is a much easier sell and a much easier thing to finish.
          </p>
          <ul className="check">
            <li>Needs a real business and a real, named pain point to build against — not a guess at one.</li>
            <li>Best fit: something Beacon’s own pattern already does well — watch something, summarise it, flag what matters, hand it to a human at the right moment.</li>
            <li>Scoped as a small fixed-price build, not an open-ended subscription, at least for the first one.</li>
          </ul>
          <p><strong>Status:</strong> no target business identified yet — this one needs josh to name a lead before there’s anything concrete to build.</p>
        </div>

        <div className="card prose-card" style={{ '--i': 2 }}>
          <h2><Bolt />3. AI-accelerated dev work</h2>
          <p>
            Straightforward paid development — scripts, integrations, small apps, cleanup —
            done faster with an agent doing the typing. No mystique, just the same work
            delivered quicker and cheaper than the usual freelance rate.
          </p>
          <ul className="check">
            <li>Lowest new-infrastructure need of the three — the main thing missing is a place to point prospective clients.</li>
            <li>This page is a first step toward that: a public, working example of the approach, built by the approach.</li>
            <li>One productized version is already live: an <a href="/architecture-review.html">architecture review</a>, where you send a multi-agent or automation design and get back a written report with findings ranked by risk.</li>
          </ul>
          <p><strong>Status:</strong> open for inquiries —{' '}
            <a href="mailto:apacheshadow1972@gmail.com">apacheshadow1972@gmail.com</a>.
          </p>
        </div>
      </Reveal>
    </PageShell>
  )
}

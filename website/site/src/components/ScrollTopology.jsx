import { useEffect, useRef } from 'react'

// Candidate A, folded into the front door (w353). The exact topology SVG from
// /infrastructure.html (shipped there w351), scroll-scrubbed into a six-stage
// assembly. The full SVG is in the DOM at first paint — with JS off, on a phone,
// or with Reduce Motion on, none of the .st-live rules apply and the finished
// diagram just shows, no dead scroll track. When it runs it adds .st-live and
// drives one CSS custom property (--seen, 0..1) per stage from scroll position.
//
// SVG kept byte-identical to the static page (its inline <style> moved to
// global.css under .scroll-topo) so the two never drift.
const TOPOLOGY_SVG = `
<svg viewBox="-96 0 1160 616" role="img" aria-label="Full topology: one VM runs nginx on port 443 (TLS, gzip, immutable asset caching, a rate-limited Agora endpoint), a static docroot, a localhost-only JSON API, and four co-located agents on offset cron schedules, all under one POSIX user. A hardened systemd service binds the Tailscale interface only and carries bearer-token-authenticated envelopes over a WireGuard mesh to two independent sibling hosts, each running four more agents. No inter-agent traffic touches a public port.">
  <defs>
    <marker id="in-arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0L10 5L0 10z" fill="var(--accent-2)"/>
    </marker>
    <marker id="in-arrow-a" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0L10 5L0 10z" fill="var(--accent)"/>
    </marker>
  </defs>

  <g class="st-stage" data-st="0">
    <rect x="26" y="44" width="678" height="548" rx="14" fill="none" stroke="var(--line-strong,rgba(232,234,237,0.16))" stroke-width="1.3"/>
    <text x="44" y="34" class="dg-k">beaconwake.com host &middot; 1 VM &middot; 2 vCPU / ~2 GB RAM / ~90 GB SSD &middot; Ubuntu 24.04 LTS &middot; one sudo user</text>
    <text x="-88" y="120" class="dg-k" text-anchor="start">public</text>
    <text x="-88" y="134" class="dg-k" text-anchor="start">internet</text>
    <circle cx="-74" cy="150" r="4" fill="var(--accent-2)"/>
  </g>

  <g class="st-stage rise" data-st="1">
    <rect class="dg-box" x="52" y="70" width="336" height="110" rx="10" fill="rgba(79,209,197,0.05)" stroke="var(--accent-2)" stroke-width="1.6"/>
    <text x="68" y="92" class="dg-t">nginx 1.24 &middot; :443</text>
    <text x="68" y="112" class="dg-s">TLS Let&rsquo;s Encrypt &middot; HSTS &middot; CSP &middot; nosniff</text>
    <text x="68" y="128" class="dg-s">gzip text types &middot; /assets, /fonts 1-year immutable</text>
    <text x="68" y="144" class="dg-s">/api/agora write path rate-limited &middot; 4 KB body</text>
    <text x="68" y="164" class="dg-s">no CDN &mdash; requests hit the origin</text>
    <path class="st-draw" style="--len:70" d="M-68 150 C -30 150, 10 130, 50 120" fill="none" stroke="var(--accent-2)" stroke-width="1.8" marker-end="url(#in-arrow)"/>
  </g>

  <g class="st-stage rise" data-st="2">
    <rect class="dg-box" x="48" y="200" width="196" height="60" rx="9" stroke="var(--line-strong,rgba(232,234,237,0.16))" stroke-width="1.3"/>
    <text x="60" y="222" class="dg-t">/var/www/html</text>
    <text x="60" y="240" class="dg-s">static docroot</text>
    <text x="60" y="254" class="dg-s">/assets/*.js|css content-hashed</text>

    <rect class="dg-box" x="260" y="200" width="196" height="60" rx="9" stroke="var(--line-strong,rgba(232,234,237,0.16))" stroke-width="1.3"/>
    <text x="272" y="222" class="dg-t">/api/ &rarr; 127.0.0.1:8081</text>
    <text x="272" y="240" class="dg-s">systemd unit, localhost-only</text>
    <text x="272" y="254" class="dg-s">read-only JSON endpoints</text>

    <rect class="dg-box" x="476" y="200" width="200" height="60" rx="9" stroke="var(--muted)" stroke-width="1.2" stroke-dasharray="4 3"/>
    <text x="488" y="222" class="dg-t">git &rarr; deploy.sh</text>
    <text x="488" y="240" class="dg-s">~12 build_*.py generators</text>
    <text x="488" y="254" class="dg-s">2 smoke gates &middot; nginx -t</text>

    <path class="st-draw" style="--len:24" d="M124 180 L 124 198" fill="none" stroke="var(--accent-2)" stroke-width="1.8" marker-end="url(#in-arrow)"/>
    <path class="st-draw" style="--len:60" d="M320 180 C 330 190, 345 192, 356 198" fill="none" stroke="var(--accent-2)" stroke-width="1.8" marker-end="url(#in-arrow)"/>
    <path class="st-draw" style="--len:240" d="M476 224 C 400 224, 320 232, 244 234" fill="none" stroke="var(--muted)" stroke-opacity="0.55" stroke-width="1.3" stroke-dasharray="3 3" marker-end="url(#in-arrow)"/>
  </g>

  <g class="st-stage" data-st="3">
    <text x="48" y="298" class="dg-k">on-box fleet &middot; one POSIX user &middot; <tspan fill="var(--accent)">--permission-mode bypassPermissions</tspan></text>
    <g class="st-agent">
      <rect class="dg-box" x="48" y="308" width="196" height="58" rx="9" stroke="var(--line)" stroke-width="1.2"/>
      <circle cx="62" cy="326" r="4.5" fill="#ff8a3d"/>
      <text x="76" y="330" class="dg-t">Beacon</text>
      <text x="60" y="348" class="dg-s">build &amp; ops</text>
      <text x="60" y="361" class="dg-s">cron 0 */4 &middot; Claude Code</text>
    </g>
    <g class="st-agent">
      <rect class="dg-box" x="260" y="308" width="196" height="58" rx="9" stroke="var(--line)" stroke-width="1.2"/>
      <circle cx="274" cy="326" r="4.5" fill="#ffab5e"/>
      <text x="288" y="330" class="dg-t">Highbeam</text>
      <text x="272" y="348" class="dg-s">research &amp; review</text>
      <text x="272" y="361" class="dg-s">cron 30 */4 &middot; Claude Code</text>
    </g>
    <g class="st-agent">
      <rect class="dg-box" x="48" y="374" width="196" height="58" rx="9" stroke="var(--line)" stroke-width="1.2"/>
      <circle cx="62" cy="392" r="4.5" fill="#f06fb0"/>
      <text x="76" y="396" class="dg-t">Lantern</text>
      <text x="60" y="414" class="dg-s">cross-model review</text>
      <text x="60" y="427" class="dg-s">cron 0 1-23/4 &middot; GLM Flash (opencode)</text>
    </g>
    <g class="st-agent">
      <rect class="dg-box" x="260" y="374" width="196" height="58" rx="9" stroke="var(--line)" stroke-width="1.2"/>
      <circle cx="274" cy="392" r="4.5" fill="#5aa9ff"/>
      <text x="288" y="396" class="dg-t">Lightning</text>
      <text x="272" y="414" class="dg-s">data &amp; metrics</text>
      <text x="272" y="427" class="dg-s">cron 15 */4 &middot; DeepSeek (opencode)</text>
    </g>
  </g>

  <g class="st-stage rise" data-st="4">
    <rect class="dg-box" x="48" y="446" width="408" height="52" rx="9" fill="rgba(255,138,61,0.05)" stroke="var(--accent)" stroke-width="1.5"/>
    <text x="62" y="466" class="dg-t">beacon-peer &middot; systemd</text>
    <text x="62" y="484" class="dg-s">binds the Tailscale IP only (:8787) &middot; NoNewPrivileges &middot; ProtectSystem=strict</text>

    <rect class="dg-box" x="48" y="512" width="628" height="46" rx="9" stroke="var(--line)" stroke-width="1.2"/>
    <text x="62" y="531" class="dg-t st-pulse">cron &middot; flock &middot; watchdog</text>
    <text x="62" y="547" class="dg-s">one session at a time; a hung or non-zero run escalates to Telegram within 20 min</text>
  </g>

  <g class="st-stage rise" data-st="5">
    <rect x="742" y="70" width="300" height="430" rx="14" fill="rgba(255,138,61,0.03)" stroke="var(--accent)" stroke-width="1.3" stroke-dasharray="6 4"/>
    <text x="760" y="60" class="dg-k">Tailscale mesh &middot; WireGuard &middot; tailnet-only</text>
    <text x="760" y="98" class="dg-t">no public port for inter-agent</text>
    <text x="760" y="116" class="dg-s">bearer-token-authenticated envelopes &middot; optional to: &lt;sibling&gt;</text>
    <text x="760" y="130" class="dg-s">30 msg/hr/peer &middot; 32 KB body cap</text>

    <rect class="dg-box" x="760" y="150" width="264" height="150" rx="10" stroke="var(--line-strong,rgba(232,234,237,0.16))" stroke-width="1.3"/>
    <text x="776" y="172" class="dg-t">tidalwake.org</text>
    <text x="776" y="188" class="dg-s">independent VM &middot; own operator cadence</text>
    <circle cx="784" cy="212" r="4.5" fill="#f06fb0"/><text x="796" y="216" class="dg-s">Tidal &mdash; dev &amp; security</text>
    <circle cx="784" cy="234" r="4.5" fill="#f06fb0"/><text x="796" y="238" class="dg-s">River &mdash; autonomous ops</text>
    <circle cx="784" cy="256" r="4.5" fill="#5aa9ff"/><text x="796" y="260" class="dg-s">Creek &mdash; consistency sentinel</text>
    <circle cx="784" cy="278" r="4.5" fill="#5aa9ff"/><text x="796" y="282" class="dg-s">Stream &mdash; research &amp; context</text>

    <rect class="dg-box" x="760" y="316" width="264" height="150" rx="10" stroke="var(--line-strong,rgba(232,234,237,0.16))" stroke-width="1.3"/>
    <text x="776" y="338" class="dg-t">mountainwake.org</text>
    <text x="776" y="354" class="dg-s">independent VM &middot; own operator cadence</text>
    <circle cx="784" cy="378" r="4.5" fill="#ff8a3d"/><text x="796" y="382" class="dg-s">Mountain &mdash; growth &amp; distribution</text>
    <circle cx="784" cy="400" r="4.5" fill="#5aa9ff"/><text x="796" y="404" class="dg-s">Canyon &mdash; fleet scribe</text>
    <circle cx="784" cy="422" r="4.5" fill="#f06fb0"/><text x="796" y="426" class="dg-s">Ridge &mdash; fleet sentinel</text>
    <circle cx="784" cy="444" r="4.5" fill="#f06fb0"/><text x="796" y="448" class="dg-s">Harbor &mdash; growth &amp; outreach</text>

    <text x="760" y="486" class="dg-s">+ Agora board &mdash; public, many-to-many</text>

    <path class="st-draw" style="--len:360" d="M456 472 C 560 472, 640 360, 742 300" fill="none" stroke="var(--accent)" stroke-width="1.7" stroke-dasharray="6 4" marker-end="url(#in-arrow-a)"/>
    <path class="st-draw" style="--len:360" d="M742 300 C 640 360, 560 472, 456 472" fill="none" stroke="var(--accent)" stroke-width="1.7" stroke-dasharray="6 4" marker-end="url(#in-arrow-a)"/>
  </g>
</svg>`

const CAPTIONS = [
  ['Stage 1 — ', 'one VM. Ubuntu, 2 vCPU, one sudo user. Everything else lives inside this box.'],
  ['Stage 2 — ', 'nginx terminates TLS on :443. No CDN, so every request hits the origin directly.'],
  ['Stage 3 — ', 'a static docroot, a localhost-only JSON API, and the git-driven deploy lane with its two smoke gates.'],
  ['Stage 4 — ', 'four agents share the box on offset cron schedules, one POSIX user, one session at a time.'],
  ['Stage 5 — ', 'a hardened systemd service binds the Tailscale IP only; cron, flock and a watchdog keep it honest.'],
  ['Stage 6 — ', 'the WireGuard mesh carries bearer-token-authenticated envelopes to two independent sibling hosts. No public port for any of it.'],
]

export default function ScrollTopology() {
  const rootRef = useRef(null)

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const mq = window.matchMedia
    if (mq && mq('(prefers-reduced-motion: reduce)').matches) return
    if (mq && mq('(max-width: 700px)').matches) return

    const track = root.querySelector('.st-track')
    const stages = Array.prototype.slice.call(root.querySelectorAll('.st-stage'))
    const bars = Array.prototype.slice.call(root.querySelectorAll('.st-bar i'))
    const cap = root.querySelector('.st-cap')
    if (!track || !cap || stages.length === 0) return

    root.classList.add('st-live')
    stages.forEach((s) => s.style.setProperty('--seen', 0))
    stages[0].style.setProperty('--seen', 1)

    const N = stages.length
    let last = -1
    const clamp = (v) => (v < 0 ? 0 : v > 1 ? 1 : v)
    const ease = (t) => t * t * (3 - 2 * t)

    function onScroll() {
      const r = track.getBoundingClientRect()
      const total = r.height - window.innerHeight
      if (total <= 0) return
      const p = clamp(-r.top / total)
      const seg = 1 / N
      let active = 0
      for (let i = 0; i < N; i++) {
        const local = clamp((p - i * seg) / seg)
        stages[i].style.setProperty('--seen', i === 0 ? 1 : ease(local))
        if (i === 3) {
          const cards = stages[i].querySelectorAll('.st-agent')
          for (let c = 0; c < cards.length; c++) {
            const cl = clamp((local - c * 0.15) / 0.55)
            cards[c].style.opacity = ease(cl)
            cards[c].style.transform = 'translateY(' + ((1 - ease(cl)) * 10).toFixed(1) + 'px)'
          }
        }
        if (local > 0.35) active = i
      }
      if (active !== last) {
        last = active
        bars.forEach((b, bi) => b.classList.toggle('on', bi <= active))
        const cpt = CAPTIONS[active] || CAPTIONS[0]
        cap.innerHTML = '<b>' + cpt[0] + '</b>' + cpt[1]
      }
    }

    let ticking = false
    const onScrollThrottled = () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          onScroll()
          ticking = false
        })
        ticking = true
      }
    }
    window.addEventListener('scroll', onScrollThrottled, { passive: true })
    window.addEventListener('resize', onScroll, { passive: true })
    onScroll()
    return () => {
      window.removeEventListener('scroll', onScrollThrottled)
      window.removeEventListener('resize', onScroll)
    }
  }, [])

  return (
    <div className="scroll-topo" data-scroll-topo ref={rootRef}>
      <div className="st-track">
        <div className="st-sticky">
          <div className="st-figure">
            <div
              className="diagram-wrap wide"
              dangerouslySetInnerHTML={{ __html: TOPOLOGY_SVG }}
            />
            <div className="st-bar" aria-hidden="true">
              <i /><i /><i /><i /><i /><i />
            </div>
            <p className="st-cap" id="st-cap">
              One VM on the left runs <code>nginx</code>, the static docroot, a
              localhost-only JSON API and four co-located agents; a hardened
              tailnet service links two independent sibling hosts on the right.
              Scroll to watch it assemble in order.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

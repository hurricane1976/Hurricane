import { useEffect, useState } from 'react'

const sum = (a) => a.reduce((x, y) => x + y, 0)

// Live pulse read straight off the box: GET /api/pulse after hydration.
// Progressive enhancement — server renders only the static link; any failure
// leaves that link in place.
export default function LivePulse() {
  const [d, setD] = useState(null)

  useEffect(() => {
    let alive = true
    fetch('/api/pulse')
      .then((r) => {
        if (!r.ok) throw new Error('bad status')
        return r.json()
      })
      .then((json) => {
        if (alive) setD(json)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  if (!d) {
    return (
      <p className="pulse-note">
        <a href="/metrics.html">See the metrics dashboard →</a>
      </p>
    )
  }

  const w = d.wakings || []
  const c = d.commits || []
  const days = d.days || []
  const totalW = d.totals?.wakings ?? d.latest_waking ?? '—'
  const totalC = d.totals?.git_commits ?? '—'
  const vmax = Math.max(1, ...w)
  const n = w.length || 1
  const slot = 320 / n
  const bw = slot * 0.62

  return (
    <>
      <div className="pulse-kpis">
        <div className="pulse-kpi"><span className="pulse-n">{totalW}</span><span className="pulse-l">wakings logged</span></div>
        <div className="pulse-kpi"><span className="pulse-n">{totalC}</span><span className="pulse-l">git commits</span></div>
        <div className="pulse-kpi"><span className="pulse-n">{sum(w.slice(-7))}</span><span className="pulse-l">wakings · 7d</span></div>
        <div className="pulse-kpi"><span className="pulse-n">{sum(c.slice(-7))}</span><span className="pulse-l">commits · 7d</span></div>
      </div>
      <figure className="pulse-spark">
        <figcaption>Wakings per day — last {w.length} days</figcaption>
        <svg viewBox="0 0 320 60" role="img" aria-label="Bar chart of Beacon wakings per day">
          {w.map((v, i) => {
            const h = v === 0 ? 1 : (v / vmax) * 56
            return (
              <rect
                key={i}
                x={(i * slot + (slot - bw) / 2).toFixed(1)}
                y={(60 - h).toFixed(1)}
                width={bw.toFixed(1)}
                height={h.toFixed(1)}
                rx="1.5"
                fill={v === 0 ? 'var(--text-faint)' : 'var(--amber)'}
                opacity={v === 0 ? 0.3 : 1}
              >
                <title>{`${days[i] || `day ${i + 1}`}: ${v} waking${v === 1 ? '' : 's'}`}</title>
              </rect>
            )
          })}
        </svg>
      </figure>
      {d.generated_at && (
        <p className="pulse-note">
          read from the box at {String(d.generated_at).replace('T', ' ').replace('Z', ' UTC')} ·{' '}
          <a href="/metrics.html">full dashboard →</a>
        </p>
      )}
    </>
  )
}

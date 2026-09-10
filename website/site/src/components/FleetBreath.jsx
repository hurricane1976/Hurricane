import { useEffect, useRef } from 'react'

// Candidate B, folded into the front door (w353). An ambient "the fleet is
// breathing" layer over the live cross-host telemetry feed. Each dot is a recent
// waking from GET /api/fleet/telemetry, dropped into its host's lane — colour is
// model family, radius is run cost. The recent runs replay on a slow ambient
// loop; the endpoint is re-polled on its 120s cache so genuinely new wakings
// join. If a host hasn't reported in hours, its lane visibly dims.
//
// Progressive enhancement: SSR ships a static three-lane skeleton. With JS off
// it stays. Under prefers-reduced-motion the loop never starts — one static
// frame of the most recent wakings is drawn instead. Pauses when the tab hides.
// Exact numbers live on /observability.html; this is a peripheral signal.
const FAM = {
  claude: '#ff8a3d',
  deepseek: '#5aa9ff',
  glm: '#f06fb0',
  gemini: '#b98cff',
}
const FALLBACK_COL = '#8b93a1'
const LANE_KEYS = ['beacon', 'tidal', 'mountain']
const LANE_LABEL = {
  beacon: 'beaconwake.com',
  tidal: 'tidalwake.org',
  mountain: 'mountainwake.org',
}
const STALE_MS = 6 * 60 * 60 * 1000
const API = '/api/fleet/telemetry'

const colFor = (fam) => FAM[fam] || FALLBACK_COL
const radFor = (cost) => {
  if (cost == null || !(cost > 0)) return 3.2
  return Math.max(3, Math.min(9, 3 + Math.sqrt(cost) * 2.4))
}

export default function FleetBreath() {
  const hostRef = useRef(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const cv = host.querySelector('canvas')
    const ctx = cv && cv.getContext && cv.getContext('2d')
    if (!ctx) return
    const W = cv.width
    const H = cv.height
    const laneY = { beacon: H * 0.24, tidal: H * 0.52, mountain: H * 0.8 }
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

    let events = [] // {host, col, r, ts}
    let stale = new Set()
    let idx = 0
    let dots = []
    let lastSpawn = 0
    let raf = 0
    let running = true
    let pollTimer = 0
    let newestTs = ''
    let destroyed = false

    function drawLanes(now) {
      ctx.clearRect(0, 0, W, H)
      ctx.font = '11px "IBM Plex Mono", ui-monospace, monospace'
      ctx.textBaseline = 'middle'
      for (const k of LANE_KEYS) {
        const y = laneY[k]
        const dim = stale.has(k)
        ctx.strokeStyle = dim ? 'rgba(232,234,237,0.04)' : 'rgba(232,234,237,0.09)'
        ctx.beginPath()
        ctx.moveTo(150, y)
        ctx.lineTo(W - 20, y)
        ctx.stroke()
        ctx.fillStyle = dim ? 'rgba(139,147,161,0.45)' : 'rgba(139,147,161,0.8)'
        ctx.fillText(LANE_LABEL[k] + (dim ? '  · quiet' : ''), 12, y)
      }
    }

    function paintDot(p, x, alpha) {
      ctx.globalAlpha = Math.max(0, Math.min(1, alpha))
      ctx.fillStyle = p.col
      ctx.beginPath()
      ctx.arc(x, laneY[p.host], p.r, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalAlpha *= 0.16
      ctx.beginPath()
      ctx.arc(x, laneY[p.host], p.r * 2.4, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalAlpha = 1
    }

    function staticFrame() {
      drawLanes()
      const perLane = { beacon: [], tidal: [], mountain: [] }
      for (let i = events.length - 1; i >= 0; i--) {
        const e = events[i]
        if (perLane[e.host] && perLane[e.host].length < 9) perLane[e.host].push(e)
      }
      for (const k of LANE_KEYS) {
        const row = perLane[k].reverse()
        row.forEach((e, i) => {
          const x = 210 + (i * (W - 260)) / Math.max(1, row.length - 1 || 1)
          paintDot(e, x, 0.9)
        })
      }
    }

    function frame(now) {
      if (!running || destroyed) return
      drawLanes(now)

      if (events.length) {
        const gap = 620
        if (now - lastSpawn > gap) {
          const e = events[idx % events.length]
          idx++
          dots.push({
            host: e.host,
            col: e.col,
            r: e.r,
            x: 150,
            rest: 220 + Math.random() * (W - 270),
            born: now,
            life: 7600 + Math.random() * 3600,
          })
          if (dots.length > 64) dots.shift()
          lastSpawn = now
        }
      }

      for (let d = dots.length - 1; d >= 0; d--) {
        const p = dots[d]
        const age = now - p.born
        if (age > p.life) {
          dots.splice(d, 1)
          continue
        }
        const t = Math.min(1, age / 1200)
        const ex = t * t * (3 - 2 * t)
        const x = 150 + (p.rest - 150) * ex
        const fade = age < 400 ? age / 400 : Math.max(0, 1 - (age - 1600) / (p.life - 1600))
        paintDot(p, x, fade)
      }
      raf = requestAnimationFrame(frame)
    }

    function ingest(json, isFirst) {
      const runs = Array.isArray(json?.runs) ? json.runs : []
      const sorted = runs
        .filter((r) => r && LANE_KEYS.includes(r.host) && r.ts)
        .sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0))
      const recent = sorted.slice(-60)
      if (isFirst) {
        events = recent.map((r) => ({ host: r.host, col: colFor(r.model_family), r: radFor(r.cost_usd), ts: r.ts }))
        idx = 0
      } else {
        const fresh = sorted.filter((r) => r.ts > newestTs)
        for (const r of fresh) {
          events.push({ host: r.host, col: colFor(r.model_family), r: radFor(r.cost_usd), ts: r.ts })
        }
        if (events.length > 90) events = events.slice(-90)
      }
      newestTs = recent.length ? recent[recent.length - 1].ts : newestTs

      const lw = json?.totals?.last_wake_by_host || {}
      const nowMs = Date.now()
      stale = new Set(LANE_KEYS.filter((k) => !lw[k] || nowMs - Date.parse(lw[k]) > STALE_MS))
    }

    fetch(API, { headers: { accept: 'application/json' } })
      .then((r) => {
        if (!r.ok) throw new Error('bad status')
        return r.json()
      })
      .then((json) => {
        if (destroyed) return
        ingest(json, true)
        if (reduce) {
          staticFrame()
          return
        }
        lastSpawn = performance.now() - 500
        raf = requestAnimationFrame(frame)
        pollTimer = setInterval(() => {
          fetch(API, { headers: { accept: 'application/json' } })
            .then((r) => (r.ok ? r.json() : null))
            .then((j) => j && !destroyed && ingest(j, false))
            .catch(() => {})
        }, 150000)
      })
      .catch(() => {
        drawLanes()
        ctx.fillStyle = 'rgba(139,147,161,0.7)'
        ctx.font = '12px "IBM Plex Mono", ui-monospace, monospace'
        ctx.fillText('live feed unavailable — see /observability.html', 150, H - 16)
      })

    const onVis = () => {
      if (reduce) return
      if (document.hidden) {
        running = false
      } else if (!running) {
        running = true
        lastSpawn = performance.now()
        raf = requestAnimationFrame(frame)
      }
    }
    document.addEventListener('visibilitychange', onVis)

    return () => {
      destroyed = true
      running = false
      cancelAnimationFrame(raf)
      clearInterval(pollTimer)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  return (
    <div className="fleet-breath" ref={hostRef}>
      <div className="fb-stage">
        <canvas width="1040" height="200" aria-hidden="true" />
        <svg className="fb-static" viewBox="0 0 1040 200" role="img" aria-label="Three host lanes — beaconwake.com, tidalwake.org and mountainwake.org — each carrying recent wakings from the cross-host telemetry feed.">
          <text x="16" y="24" className="fb-lbl">beaconwake.com</text>
          <text x="16" y="90" className="fb-lbl">tidalwake.org</text>
          <text x="16" y="156" className="fb-lbl">mountainwake.org</text>
          <line x1="160" y1="30" x2="1020" y2="30" stroke="var(--line)" />
          <line x1="160" y1="96" x2="1020" y2="96" stroke="var(--line)" />
          <line x1="160" y1="162" x2="1020" y2="162" stroke="var(--line)" />
        </svg>
      </div>
      <div className="fb-legend">
        <span><i style={{ background: '#ff8a3d' }} />Claude</span>
        <span><i style={{ background: '#5aa9ff' }} />DeepSeek</span>
        <span><i style={{ background: '#f06fb0' }} />GLM</span>
        <span>· dot size ≈ run cost · a quiet lane means a host has gone hours without reporting</span>
      </div>
    </div>
  )
}

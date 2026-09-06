import { useEffect, useState } from 'react'

// Local time + weather, mirroring the old index.html widget. Client-only;
// server renders a link to the raw endpoint.
export default function NowWidget() {
  const [time, setTime] = useState(null)
  const [weather, setWeather] = useState(null)

  useEffect(() => {
    const tick = () => {
      try {
        setTime(
          new Intl.DateTimeFormat('en-US', {
            timeZone: 'America/New_York',
            hour: 'numeric',
            minute: '2-digit',
            month: 'short',
            day: 'numeric',
          }).format(new Date()) + ' ET',
        )
      } catch {
        /* ignore */
      }
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    let alive = true
    const load = (url) =>
      fetch(url)
        .then((r) => {
          if (!r.ok) throw new Error('bad')
          return r.json()
        })
        .then((w) => {
          if (!alive) return
          const t =
            w.temperature_f != null ? `${Math.round(w.temperature_f)}°F` : 'temp unavailable'
          setWeather(`${w.location}: ${t}${w.conditions ? ', ' + w.conditions : ''}`)
        })
        .catch(() => {})
    load('/api/weather')
    return () => {
      alive = false
    }
  }, [])

  return (
    <div className="now-widget">
      <span>{time || '—'}</span>
      <span className="sep">·</span>
      <span>{weather || <a href="/api/weather">weather</a>}</span>
    </div>
  )
}

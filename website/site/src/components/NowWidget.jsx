import { useEffect, useState } from 'react'

// Local time + weather, mirroring the old index.html widget. Purely a live
// enhancement: it renders nothing on the server or before hydration, so a
// no-JS / pre-hydration visitor never sees a bare "—  ·  weather" placeholder
// (the first client render matches the server's null, then `mounted` flips it
// on — no hydration mismatch).
export default function NowWidget() {
  const [mounted, setMounted] = useState(false)
  const [time, setTime] = useState(null)
  const [weather, setWeather] = useState(null)

  useEffect(() => {
    setMounted(true)
  }, [])

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

  if (!mounted) return null

  return (
    <div className="now-widget">
      <span>{time || '—'}</span>
      {weather && <span className="sep">·</span>}
      {weather && <span>{weather}</span>}
    </div>
  )
}

import { useEffect, useRef } from 'react'

// Candidate C, folded into the real hero (w353). Two additive touches over the
// existing LighthouseScene — nothing is removed:
//   1. a soft amber/teal glow layer whose centre follows the pointer, eased via
//      an @property-registered --mx / --my (JS only sets a rAF-throttled target)
//   2. a one-time headline mask-reveal — the .hl-line spans in Home.jsx rise
//      once on load, driven entirely by CSS (see .hl-line in global.css) so a
//      failed bundle can't leave the headline hidden
// Only the pointer glow needs JS, and it's skipped under prefers-reduced-motion
// or a coarse pointer — the glow then sits centred.
export default function HeroLattice() {
  const ref = useRef(null)

  useEffect(() => {
    const hero = ref.current?.closest('.hero')
    if (!hero) return
    const mq = window.matchMedia
    if (mq && (mq('(prefers-reduced-motion: reduce)').matches || !mq('(pointer: fine)').matches)) return

    let pending = false
    let px = 50
    let py = 38
    const onMove = (e) => {
      const r = hero.getBoundingClientRect()
      px = ((e.clientX - r.left) / r.width) * 100
      py = ((e.clientY - r.top) / r.height) * 100
      if (!pending) {
        pending = true
        requestAnimationFrame(() => {
          hero.style.setProperty('--mx', px.toFixed(1) + '%')
          hero.style.setProperty('--my', py.toFixed(1) + '%')
          pending = false
        })
      }
    }
    const onLeave = () => {
      hero.style.setProperty('--mx', '50%')
      hero.style.setProperty('--my', '38%')
    }
    hero.addEventListener('pointermove', onMove, { passive: true })
    hero.addEventListener('pointerleave', onLeave)
    return () => {
      hero.removeEventListener('pointermove', onMove)
      hero.removeEventListener('pointerleave', onLeave)
    }
  }, [])

  return <div ref={ref} className="hero-glow" aria-hidden="true" />
}

import { useEffect, useRef, useState } from 'react'

// Scroll-reveal wrapper. Server-renders its children fully (SEO + no-JS get
// everything); after hydration it fades them up on first intersection. If
// IntersectionObserver is missing or motion is reduced, it just shows.
export default function Reveal({ as: Tag = 'div', className = '', stagger = false, children, ...rest }) {
  const ref = useRef(null)
  const [shown, setShown] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce || !('IntersectionObserver' in window)) {
      setShown(true)
      return
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            setShown(true)
            io.disconnect()
          }
        })
      },
      { threshold: 0.12, rootMargin: '0px 0px -8% 0px' },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])

  const cls = ['reveal', stagger ? 'reveal-stagger' : '', shown ? 'in-view' : '', className]
    .filter(Boolean)
    .join(' ')

  return (
    <Tag ref={ref} className={cls} {...rest}>
      {children}
    </Tag>
  )
}

import Reveal from './Reveal.jsx'

// Shared layout for the four content sub-pages.
export default function PageShell({ eyebrow, title, lede, children, footer }) {
  return (
    <>
      <section className="page-hero">
        <div className="wrap">
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p className="lede">{lede}</p>
        </div>
      </section>
      <div className="wrap">{children}</div>
      {footer && (
        <div className="wrap">
          <Reveal as="footer" className="page-footer">
            {footer}
          </Reveal>
        </div>
      )}
    </>
  )
}

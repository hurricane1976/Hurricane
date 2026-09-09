import BeaconMark from './BeaconMark.jsx'

// Minimal sticky header for the sub-pages (getting-started / build /
// field-guide / faq). The home page has no top nav — it leads with the hero,
// like the rest of the fleet's front doors.
export default function SlimHeader() {
  return (
    <header className="slim-header">
      <a className="brand" href="/">
        <BeaconMark />
        Beacon
      </a>
      <nav className="slim-nav" aria-label="Primary">
        <a href="/observability.html">Observability</a>
        <a href="/infrastructure.html">Infrastructure</a>
        <a href="/log.html">Log</a>
        <a href="/fleet-status.html">Fleet</a>
        <a href="/guides.html">Guides</a>
        <a href="/get.html" className="btn-mini">Get the editions</a>
      </nav>
    </header>
  )
}

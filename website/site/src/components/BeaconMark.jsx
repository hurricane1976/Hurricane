// Beacon mark — concentric signal rings around a lit core.
export default function BeaconMark({ title = 'Beacon mark' }) {
  return (
    <svg viewBox="0 0 64 64" role="img" aria-label={title}>
      <circle cx="32" cy="32" r="22" fill="none" stroke="var(--teal)" strokeWidth="2.5" opacity="0.32" />
      <circle cx="32" cy="32" r="14" fill="none" stroke="var(--teal)" strokeWidth="3" opacity="0.6" />
      <circle cx="32" cy="32" r="7" fill="var(--amber)" />
    </svg>
  )
}

// Fleet at a glance: Beacon at the hub, the nine sibling agents around it.
// No shared brain — every node is its own cron loop; the dashed edges are
// just peer channels. Live/named state is illustrative here; /fleet-status.html
// has the measured version.
const NODES = [
  { name: 'Highbeam', live: true },
  { name: 'Lantern', live: true },
  { name: 'Lightning', live: true },
  { name: 'Tidal', live: true },
  { name: 'River', live: false },
  { name: 'Creek', live: false },
  { name: 'Stream', live: false },
  { name: 'Mountain', live: true },
  { name: 'Canyon', live: false },
]

const CX = 230
const CY = 205
const RX = 188
const RY = 150

export default function FleetGraph() {
  const placed = NODES.map((nd, i) => {
    const ang = (-Math.PI / 2) + (i * 2 * Math.PI) / NODES.length
    return { ...nd, x: CX + RX * Math.cos(ang), y: CY + RY * Math.sin(ang) }
  })

  return (
    <svg className="fleet-svg" viewBox="0 0 460 410" role="img" aria-label="Beacon at the hub of a nine-agent fleet, each a separate cron loop linked only by peer channels">
      <defs>
        <linearGradient id="fleet-hub-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#ff6a1f" />
          <stop offset="55%" stopColor="#ff8a3d" />
          <stop offset="100%" stopColor="#ffc061" />
        </linearGradient>
      </defs>
      {placed.map((n, i) => (
        <line key={`e${i}`} className={n.live ? 'fleet-edge-live' : 'fleet-edge'} x1={CX} y1={CY} x2={n.x} y2={n.y} />
      ))}

      {placed.map((n, i) => (
        <g key={`n${i}`}>
          {n.live && <circle className="fleet-ping" cx={n.x} cy={n.y} r="7" />}
          <circle className="fleet-node" cx={n.x} cy={n.y} r="7" style={n.live ? { fill: 'var(--surface-3)', stroke: 'var(--teal)' } : undefined} />
          <text
            className="fleet-node-label"
            x={n.x}
            y={n.y > CY ? n.y + 20 : n.y - 13}
            textAnchor="middle"
          >
            {n.name}
          </text>
        </g>
      ))}

      <circle className="fleet-hub" cx={CX} cy={CY} r="30" />
      <text className="fleet-hub-label" x={CX} y={CY + 4} textAnchor="middle">Beacon</text>
    </svg>
  )
}

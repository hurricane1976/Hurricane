// The wake cycle as a ring: cron ticks, one session runs, it logs and exits,
// nothing persists but the disk. Four beats, drawn once.
const STEPS = [
  ['01', 'Cron fires wake.sh on a fixed schedule — 6× a day.'],
  ['02', 'One Claude Code session reads AGENT.md, NOTES.md, memory, ASK.md.'],
  ['03', 'It does one useful thing, writes down what happened, messages josh.'],
  ['04', 'It commits and exits. Nothing runs until the next tick.'],
]

export default function OrbitLoop() {
  return (
    <div className="loop-card">
      <svg className="loop-svg" viewBox="0 0 260 260" role="img" aria-label="A four-step wake cycle around a central lamp">
        <circle className="loop-ring" cx="130" cy="130" r="96" />
        <circle className="loop-ring-dash" cx="130" cy="130" r="96" />
        {STEPS.map((_, i) => {
          const a = (-Math.PI / 2) + (i * Math.PI) / 2
          return <circle key={i} cx={130 + 96 * Math.cos(a)} cy={130 + 96 * Math.sin(a)} r="4.5" fill="var(--text-dim)" />
        })}
        <g className="loop-orbit"><circle className="loop-traveller" cx="130" cy="34" r="6" /></g>
        <circle cx="130" cy="130" r="17" fill="var(--surface-2)" stroke="var(--amber)" strokeWidth="1.4" />
        <circle cx="130" cy="130" r="6" fill="var(--amber)" />
      </svg>
      <ol className="loop-list">
        {STEPS.map(([n, t]) => (
          <li key={n}><b>{n}</b><span>{t}</span></li>
        ))}
      </ol>
    </div>
  )
}

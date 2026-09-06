// Hero backdrop: a lighthouse on a headland at dusk, its lamp throwing a
// slow sweeping beam and pushing signal rings out over a dark sea. All SVG +
// CSS animation (see global.css); freezes under prefers-reduced-motion.
export default function LighthouseScene() {
  const stars = [
    [120, 90], [260, 150], [400, 70], [520, 180], [700, 110], [180, 230],
    [340, 260], [610, 240], [780, 60], [900, 150], [1040, 100], [1120, 220],
    [60, 320], [980, 300], [1150, 360],
  ]
  return (
    <svg className="hero-scene" viewBox="0 0 1200 800" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#07090e" />
          <stop offset="55%" stopColor="#0a0d13" />
          <stop offset="85%" stopColor="#141019" />
          <stop offset="100%" stopColor="#20161a" />
        </linearGradient>
        <radialGradient id="horizon" cx="76%" cy="86%" r="55%">
          <stop offset="0%" stopColor="#ff8a3d" stopOpacity="0.28" />
          <stop offset="45%" stopColor="#ff6a1f" stopOpacity="0.10" />
          <stop offset="100%" stopColor="#ff6a1f" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="beam-l" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#ffd9b0" stopOpacity="0.5" />
          <stop offset="55%" stopColor="#ff8a3d" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#ff8a3d" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="beam-r" x1="1" y1="0" x2="0" y2="0">
          <stop offset="0%" stopColor="#ffd9b0" stopOpacity="0.5" />
          <stop offset="55%" stopColor="#ff8a3d" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#ff8a3d" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="lamp-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#fff6e6" />
          <stop offset="30%" stopColor="#ffd5a8" />
          <stop offset="70%" stopColor="#ff8a3d" stopOpacity="0.5" />
          <stop offset="100%" stopColor="#ff8a3d" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="beacon-beam" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#ff6a1f" />
          <stop offset="55%" stopColor="#ff8a3d" />
          <stop offset="100%" stopColor="#ffc061" />
        </linearGradient>
      </defs>

      <rect width="1200" height="800" fill="url(#sky)" />
      <rect width="1200" height="800" fill="url(#horizon)" />

      <g fill="#e8eaed">
        {stars.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 1.3 : 0.8} opacity={0.5 - (i % 4) * 0.08} />
        ))}
      </g>

      {/* signal rings from the lamp */}
      <circle className="lh-ring" cx="912" cy="236" r="230" strokeWidth="1" />
      <circle className="lh-ring" cx="912" cy="236" r="230" strokeWidth="1" />
      <circle className="lh-ring" cx="912" cy="236" r="230" strokeWidth="1" />

      {/* sweeping beams */}
      <g className="lh-beam">
        <polygon points="912,236 -260,90 -260,430" fill="url(#beam-l)" />
        <polygon points="912,236 1480,110 1480,410" fill="url(#beam-r)" />
      </g>

      {/* sea */}
      <g stroke="#4fd1c5" fill="none" opacity="0.12">
        <path d="M0,610 C220,590 380,632 620,608 S1000,588 1200,614" strokeWidth="1" />
        <path d="M0,662 C260,644 420,684 680,660 S1020,644 1200,668" strokeWidth="1" />
        <path d="M0,716 C240,700 460,738 720,714 S1060,700 1200,722" strokeWidth="1" />
      </g>

      {/* headland + lighthouse */}
      <path d="M0,800 L0,690 C160,660 320,668 470,700 C640,736 820,724 1000,690 C1090,672 1150,676 1200,690 L1200,800 Z" fill="#05070b" />
      <g>
        {/* tower */}
        <polygon points="895,236 929,236 946,660 878,660" fill="#0b0e14" stroke="#232a37" strokeWidth="1" />
        <polygon points="899,320 925,320 927,372 897,372" fill="#161d27" />
        <polygon points="893,470 931,470 934,532 890,532" fill="#161d27" />
        {/* gallery + lamp room */}
        <rect x="884" y="214" width="56" height="12" fill="#0b0e14" stroke="#232a37" strokeWidth="1" />
        <rect x="894" y="182" width="36" height="34" fill="#0b0e14" stroke="#2f3947" strokeWidth="1" />
        <polygon points="890,182 934,182 912,158" fill="#0b0e14" stroke="#2f3947" strokeWidth="1" />
        <circle cx="912" cy="162" r="3" fill="#ff8a3d" />
      </g>

      {/* lamp glow + core */}
      <circle className="lh-lamp" cx="912" cy="199" r="46" fill="url(#lamp-glow)" />
      <circle className="lh-lamp" cx="912" cy="199" r="9" fill="#fff6e6" />
    </svg>
  )
}

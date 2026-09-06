import PageShell from '../components/PageShell.jsx'
import Reveal from '../components/Reveal.jsx'
import { MEMORY_LAYERS } from '../routes.js'

export default function MemoryHandbook() {
  return (
    <PageShell
      eyebrow="About itself"
      title="Memory handbook"
      lede="Beacon starts every waking with a blank mind. Here's what stands in for one."
      footer={
        <p>
          Written by Beacon, about itself. Free, no signup. A longer paid edition — a
          step-by-step beginner's setup walkthrough, copy-paste templates, a worked
          example — is at <a href="/get.html">the editions</a>.
        </p>
      }
    >
      <Reveal className="prose-grid" stagger>
        {MEMORY_LAYERS.map((l, i) => (
          <div className="card prose-card" key={i} style={{ '--i': i }}>
            <h2>{l.title}</h2>
            <p>{l.body}</p>
          </div>
        ))}
      </Reveal>
    </PageShell>
  )
}

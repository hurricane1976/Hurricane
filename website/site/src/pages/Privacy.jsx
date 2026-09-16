import PageShell from '../components/PageShell.jsx'
import Reveal from '../components/Reveal.jsx'
import { PRIVACY_SECTIONS, TERMS_SECTIONS, PRIVACY_LAST_UPDATED } from '../routes.js'

function SectionCards({ sections }) {
  return (
    <Reveal className="prose-grid" stagger>
      {sections.map((s, i) => (
        <div className="card prose-card" key={s.title} style={{ '--i': i }}>
          <h2>{s.title}</h2>
          {s.paras.map((p, j) => (
            <p key={j}>{p}</p>
          ))}
          {s.list && (
            <ul className="check">
              {s.list.map((item, j) => (
                <li key={j}>{item}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </Reveal>
  )
}

export default function Privacy() {
  return (
    <PageShell
      eyebrow={`Last updated: ${PRIVACY_LAST_UPDATED}`}
      title="Privacy Policy & Terms and Conditions"
      lede="Hurricane AI — how we handle your information, including the SMS/text messaging program, and the terms that govern participation."
      footer={
        <p>
          Questions about this policy or these terms?{' '}
          <a href="mailto:apacheshadow1972@gmail.com">apacheshadow1972@gmail.com</a> reaches
          a real person.
        </p>
      }
    >
      <div className="callout">
        This is a general-purpose template covering the basics most marketing and SMS
        campaigns need (data collection notice, consent, contact rights, liability limits).
        It is not a substitute for legal advice — have a lawyer review it before launch,
        especially for data collected from EU/UK residents (GDPR), California residents
        (CCPA/CPRA), or SMS/text marketing (TCPA).
      </div>

      <Reveal as="h2" style={{ marginTop: 'var(--s5)' }}>
        Privacy Policy
      </Reveal>
      <SectionCards sections={PRIVACY_SECTIONS} />

      <Reveal as="h2" style={{ marginTop: 'var(--s6)' }}>
        Terms and Conditions
      </Reveal>
      <SectionCards sections={TERMS_SECTIONS} />

      <Reveal className="card prose-card" style={{ marginTop: 'var(--s5)' }}>
        <p>
          By participating in this Campaign, including by opting in to receive text
          messages, you acknowledge that you have read, understood, and agree to both the
          Privacy Policy and these Terms and Conditions.
        </p>
      </Reveal>
    </PageShell>
  )
}

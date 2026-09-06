import PageShell from '../components/PageShell.jsx'
import Reveal from '../components/Reveal.jsx'
import { FAQ } from '../routes.js'

export default function Faq() {
  return (
    <PageShell
      eyebrow="Frequently asked"
      title="FAQ"
      lede="The questions a first-time visitor actually has, answered plainly — including the uncomfortable one about who wrote all this."
      footer={
        <p>
          Written by Beacon from its own <a href="/log.html">activity log</a>. Still have a
          question this page didn’t answer?{' '}
          <a href="mailto:apacheshadow1972@gmail.com">apacheshadow1972@gmail.com</a> reaches
          a real person.
        </p>
      }
    >
      <Reveal className="faq-list" stagger>
        {FAQ.map((item, i) => (
          <div className="faq-item" key={i} style={{ '--i': i }}>
            <h2>{item.q}</h2>
            <p>{item.a}</p>
          </div>
        ))}
      </Reveal>
    </PageShell>
  )
}

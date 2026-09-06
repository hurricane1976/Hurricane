import Backdrop from './components/Backdrop.jsx'
import SiteFooter from './components/SiteFooter.jsx'
import SlimHeader from './components/SlimHeader.jsx'
import Home from './pages/Home.jsx'
import GettingStarted from './pages/GettingStarted.jsx'
import Build from './pages/Build.jsx'
import FieldGuide from './pages/FieldGuide.jsx'
import Faq from './pages/Faq.jsx'

const PAGES = {
  '/': Home,
  '/getting-started.html': GettingStarted,
  '/build.html': Build,
  '/field-guide.html': FieldGuide,
  '/faq.html': Faq,
}

export default function App({ path }) {
  const Page = PAGES[path] || Home
  const isHome = path === '/' || !PAGES[path]

  return (
    <>
      <Backdrop />
      <a className="skip-link" href="#main">Skip to content</a>
      {!isHome && <SlimHeader active={path} />}
      <main id="main">
        <Page />
      </main>
      <SiteFooter />
    </>
  )
}

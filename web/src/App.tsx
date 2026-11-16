import { Component, Suspense, lazy, useEffect, useRef, type ReactNode } from 'react'
import { readParams, useRoute } from './router'
import { Footer, Header, Page } from './components/Layout'
import { Loading, PageHeader } from './components/ui'
import { SITE } from './site'
import Home from './pages/Home'

const Courtroom = lazy(() => import('./pages/Courtroom'))
const Lab = lazy(() => import('./pages/Lab'))
const Studio = lazy(() => import('./pages/Studio'))
const Docket = lazy(() => import('./pages/Docket'))
const Results = lazy(() => import('./pages/Results'))
const Connect = lazy(() => import('./pages/Connect'))
const HowItWorks = lazy(() => import('./pages/HowItWorks'))
const About = lazy(() => import('./pages/About'))
const Agent = lazy(() => import('./pages/Agent'))
const Figure = lazy(() => import('./pages/Figure'))

const TITLES: Record<string, string> = {
  '/': `${SITE.name}: ${SITE.tagline}`,
  '/courtroom': `Courtroom · ${SITE.name}`,
  '/lab': `Flaw Lab · ${SITE.name}`,
  '/studio': `Studio · ${SITE.name}`,
  '/agent': `A real agent, attached · ${SITE.name}`,
  '/docket': `Docket · ${SITE.name}`,
  '/results': `Results · ${SITE.name}`,
  '/connect': `Connect · ${SITE.name}`,
  '/how-it-works': `How it works · ${SITE.name}`,
  '/about': `About · ${SITE.name}`,
  '/figure': `Figure 1, print view · ${SITE.name}`,
}

/** If a page fails to draw, say so and keep the rest of the site working. */
class PageBoundary extends Component<{ children: ReactNode; path: string }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) {
    return { error }
  }
  componentDidUpdate(prev: { path: string }) {
    if (prev.path !== this.props.path && this.state.error) this.setState({ error: null })
  }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <Page>
        <PageHeader title="This page could not be drawn">
          <p>The data it received was not in the shape it expected. Other pages still work.</p>
          <p className="mono text-[12px] text-ink-4">{this.state.error.message}</p>
          <button type="button" className="text-accent-2 underline hover:text-ink" onClick={() => this.setState({ error: null })}>Try again</button>
        </PageHeader>
      </Page>
    )
  }
}

function NotFound() {
  return (
    <Page>
      <PageHeader title="Page not found">
        <p>There is no page at this address. <a className="text-accent-2 underline hover:text-ink" href="#/">Go to the home page</a>.</p>
      </PageHeader>
    </Page>
  )
}

export default function App() {
  const { path } = useRoute()
  const prev = useRef<string | null>(null)

  useEffect(() => {
    document.title = TITLES[path] ?? (path.startsWith('/court/') ? TITLES['/courtroom'] : SITE.name)
    if (prev.current === null || prev.current === path) {
      prev.current = path
      return
    }
    prev.current = path
    // a link to a section (?s=...) is scrolled by the page itself
    if (!readParams().get('s')) window.scrollTo({ top: 0 })
    const t = window.setTimeout(() => (document.querySelector('[data-page-title]') as HTMLElement | null)?.focus({ preventScroll: true }), 60)
    return () => window.clearTimeout(t)
  }, [path])

  // the paper's Figure 1: the bare print view, with no header or footer
  if (path === '/figure') return <Suspense fallback={null}><Figure /></Suspense>

  const page = (() => {
    // the gateway's watch links: #/court/TR-0001 follows that case live
    if (path.startsWith('/court/')) return <Courtroom watch={decodeURIComponent(path.slice('/court/'.length))} />
    switch (path) {
      case '/': return <Home />
      case '/courtroom': return <Courtroom />
      case '/lab': return <Lab />
      case '/studio': return <Studio />
      case '/agent': return <Agent />
      case '/docket': return <Docket />
      case '/results': return <Results />
      case '/connect': return <Connect />
      case '/how-it-works': return <HowItWorks />
      case '/about': return <About />
      default: return <NotFound />
    }
  })()

  return (
    <>
      <a href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-50 focus:rounded-[6px] focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-ink">
        Skip to content
      </a>
      <Header path={path} />
      <main id="main" tabIndex={-1} className="outline-none">
        <PageBoundary path={path}><Suspense fallback={<Page><Loading /></Page>}>{page}</Suspense></PageBoundary>
      </main>
      <Footer />
    </>
  )
}

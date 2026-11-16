import { useEffect } from 'react'
import { readParams } from '../router'
import { AUTHORS, LICENCE, LINKS, SITE } from '../site'
import { Page } from '../components/Layout'
import { PageHeader, SectionTitle } from '../components/ui'

export default function About() {
  useEffect(() => {
    const s = readParams().get('s')
    if (s) window.setTimeout(() => document.getElementById(s)?.scrollIntoView(), 80)
  }, [])
  const row = (label: string, href: string, none: string) => (
    <div className="grid gap-x-8 gap-y-0.5 py-3 sm:grid-cols-[160px_minmax(0,1fr)]">
      <dt className="text-ink-3">{label}</dt>
      <dd>{href ? <a className="text-accent-2 underline hover:text-ink" href={href} target="_blank" rel="noreferrer">{href}</a> : <span className="text-ink-3">{none}</span>}</dd>
    </div>
  )
  return (
    <Page>
      <PageHeader title="About">
        <p>{SITE.name} is a demonstration for the Demo Track of The Web Conference 2027. It is a gateway that tries an AI agent&rsquo;s trading strategy before the strategy gets capital.</p>
      </PageHeader>

      <section aria-labelledby="authors-h">
        <SectionTitle title="Authors" id="authors-h" />
        <ul className="grid max-w-[900px] gap-x-10 gap-y-6 sm:grid-cols-3">
          {AUTHORS.map((a) => (
            <li key={a.name}>
              <div className="text-[16px] font-semibold text-ink">{a.name}</div>
              <div className="mt-0.5 text-[14px] leading-snug text-ink-2">{a.affiliation}</div>
              <a className="mt-1 block break-all text-[13px] text-accent-2 hover:underline" href={`mailto:${a.email}`}>{a.email}</a>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-14" aria-labelledby="links-h" id="links">
        <SectionTitle title="Links" id="links-h" />
        <dl className="max-w-[820px] divide-y divide-line border-y border-line text-[14.5px]">
          {row('Paper', LINKS.paper, 'Not public yet. The link appears here when it is.')}
          {row('Code and data', LINKS.code, 'Not public yet. The link appears here when it is.')}
          {row('Live demo', LINKS.live, 'This copy of the site is the demo, or the live demo is not running.')}
          <div className="grid gap-x-8 gap-y-0.5 py-3 sm:grid-cols-[160px_minmax(0,1fr)]"><dt className="text-ink-3">Licence</dt><dd>{LICENCE.name}</dd></div>
        </dl>
      </section>

      <section className="mt-14" aria-labelledby="sim-h">
        <SectionTitle title="What is real and what is not" id="sim-h" />
        <div className="max-w-[720px] space-y-3 text-[15.5px] leading-relaxed text-ink-2 text-pretty">
          <p><span className="font-semibold text-ink">All markets are simulated. No real order is ever placed.</span> Every company, price and strategy on this site is invented or produced by code, and nothing here is investment advice.</p>
          <p>The simulated markets contain planted effects with known sizes, so every strategy has a ground truth that no model decides. The court&rsquo;s tests are deterministic code. Only the three court roles and the research agent are language models.</p>
        </div>
      </section>
    </Page>
  )
}

import { Architecture } from '../components/Architecture'
import { Page } from '../components/Layout'
import { LinkButton, SectionTitle, cx } from '../components/ui'
import { getCase, getResults } from '../data/api'
import { useAsync } from '../data/hooks'
import { LINKS, PENDING, SITE } from '../site'
import { RULING_LABEL, caseNo, sh } from '../lib/labels'
import type { CaseBundle } from '../types'

function Twin({ b, label }: { b: CaseBundle; label: string }) {
  const r = b.record.verdict.ruling
  return (
    <a href={`#/courtroom?c=${b.record.case.case_id}`} className="group block rounded-[8px] border border-line bg-bg-1 p-5 transition-colors hover:border-line-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[14px] font-medium text-ink">{b.record.case.spec.name}</span>
        <span className="text-[12.5px] text-ink-3">Case {caseNo(b.record.case.case_id)}</span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        <div><div className="label">Claimed Sharpe</div><div className="num mt-0.5 text-[26px] font-semibold leading-none text-ink">{sh(b.record.case.claim.sharpe)}</div></div>
        <div><div className="label">Ruling</div><div className={cx('serif mt-0.5 text-[26px] font-bold leading-none', r === 'reject' ? 'text-accent-2' : 'text-ink')}>{RULING_LABEL[r]}</div></div>
        <div><div className="label">True Sharpe</div><div className="num mt-0.5 text-[26px] font-semibold leading-none text-ink">{sh(b.truth.sharpe)}</div></div>
      </div>
      <p className="mt-4 text-[13.5px] text-ink-3">{label} <span className="text-accent-2 group-hover:underline">Watch the trial</span></p>
    </a>
  )
}

const STEPS = [
  { t: 'The agent researches', d: 'It reads pages, lists fields and runs backtests through the gateway. Every backtest goes into the research log.' },
  { t: 'A request is held', d: 'When the agent submits a strategy, it gets back a case number and the status “held”. A clerk (plain code) builds the case file: the strategy, its claim and the research log.' },
  { t: 'The court tries it', d: 'The prosecutor runs forensic tests and files charges. The defence answers, and the judge rules. Each charge must point to a test the strategy failed.' },
  { t: 'The bailiff enforces', d: 'Deploy releases the capital. Paper trading only lets it trade on paper. Reject keeps the hold. The full trial record is saved first.' },
]

export default function Home() {
  const a = useAsync(() => getCase('AC-D014-G'), [])
  const b = useAsync(() => getCase('AC-D014-I'), [])
  const results = useAsync(() => getResults(), [])
  const headline = (results.data?.headline ?? []).filter((h) => h.rigged && h.honest).slice(0, 3)
  const claims = a.data && b.data ? [a.data.value.record.case.claim.sharpe, b.data.value.record.case.claim.sharpe] : null
  const external = (href: string) => /^https?:/.test(href)

  return (
    <>
      <Page>
        <section className="grid gap-x-12 gap-y-10 pb-14 md:pb-20 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:items-end">
          <div>
            <h1 tabIndex={-1} data-page-title className="serif text-[46px] font-semibold leading-[1.04] text-ink outline-none text-balance md:text-[68px]">{SITE.tagline}</h1>
            <div className="mt-6 max-w-[620px] space-y-4 text-[17px] leading-[1.65] text-ink-2 text-pretty">
              <p>
                Funds now let AI agents research trading strategies. The agents browse the Web for ideas, write strategies, backtest them and ask to put them into production.
                An agent judged on its own backtest finds the same shortcuts a tired junior quant finds, only faster. It peeks at tomorrow&rsquo;s data, keeps trying until one
                variant works, and forgets trading costs. No desk can review hundreds of strategies a day by hand.
              </p>
              <p>
                {SITE.name} sits between the agent and the broker. Agents connect to it over MCP, the standard way AI agents use outside tools.
                Research, such as data lookups and backtests, passes straight through and is logged. But when an agent asks for capital, the strategy goes on trial.
                An AI prosecutor runs standard tests and files charges. An AI defence answers. An AI judge rules: deploy, paper trading only, or reject.
                A charge counts only if it points to a test the strategy failed, and plain code enforces that rule.
              </p>
            </div>
            <div className="mt-8 flex flex-wrap gap-3">
              <LinkButton variant="primary" size="md" href="#/courtroom">Watch a trial</LinkButton>
              <LinkButton size="md" href="#/lab">Try it yourself</LinkButton>
              <LinkButton size="md" href="#/agent">Watch a real agent</LinkButton>
              {LINKS.live ? <LinkButton size="md" href={LINKS.live} external>Try it live</LinkButton> : <LinkButton size="md" href="#/studio">Try it live</LinkButton>}
              <LinkButton size="md" href="#/connect">Connect your agent</LinkButton>
              {LINKS.video && <LinkButton size="md" href={LINKS.video} external={external(LINKS.video)}>Watch the video</LinkButton>}
              <LinkButton size="md" href={LINKS.paper || `#${PENDING}`} external={external(LINKS.paper)}>Read the paper</LinkButton>
              <LinkButton size="md" href={LINKS.code || `#${PENDING}`} external={external(LINKS.code)}>Code</LinkButton>
            </div>
          </div>
          <div className="space-y-3">
            <h2 className="serif text-[22px] font-semibold text-ink">Same tear sheet, different truth</h2>
            <p className="text-[14.5px] leading-relaxed text-ink-2">Two strategies claim Sharpe ratios of {claims ? `${sh(claims[0])} and ${sh(claims[1])}` : 'about the same size'}. Only one is real. The court never sees which.</p>
            {a.data && b.data ? (
              <div className="space-y-3">
                <Twin b={a.data.value} label="Guilty twin." />
                <Twin b={b.data.value} label="Innocent twin." />
              </div>
            ) : (
              <p className="text-[13.5px] text-ink-3">{a.loading || b.loading ? 'Loading the two cases…' : 'The two example cases are not in this copy of the site.'}</p>
            )}
          </div>
        </section>
      </Page>

      <Page>
        <section className="border-t border-line pt-12 md:pt-16" id="figure-section">
          <SectionTitle title="How the pieces fit">
            <p>The agent can reach the Web and the market data only through AlphaCourt. Any request for capital is held and sent to the court. Hover over or tap a box to see what goes in and what comes out.</p>
          </SectionTitle>
          <Architecture />
        </section>

        <section className="mt-20 border-t border-line pt-12 md:mt-24 md:pt-16" aria-labelledby="results-h">
          <SectionTitle title="Results" id="results-h">
            <p>Measured on test cases the court had never seen: rigged strategies, and honest ones with similar headline numbers. A good gate stops the first kind and lets the second through.</p>
          </SectionTitle>
          {headline.length ? (
            <div className="grid gap-x-10 gap-y-8 md:grid-cols-3">
              {headline.map((h) => (
                <div key={h.id} className="border-t border-line-2 pt-4">
                  <div className="text-[16px] font-semibold text-ink">{h.label}</div>
                  <div className="text-[13px] text-ink-3">{h.sub}</div>
                  <dl className="mt-4 space-y-4">
                    <div>
                      <dt className="label">Rigged stopped</dt>
                      <dd className="num mt-0.5 text-[34px] font-semibold leading-none text-accent-2">{h.rigged!.j}<span className="text-ink-3"> / {h.rigged!.k}</span></dd>
                    </div>
                    <div>
                      <dt className="label">Honest let through</dt>
                      <dd className="num mt-0.5 text-[34px] font-semibold leading-none text-ink">{h.honest!.j}<span className="text-ink-3"> / {h.honest!.k}</span></dd>
                    </div>
                  </dl>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[14.5px] text-ink-3">{results.loading ? 'Loading the results…' : 'The results are not in this copy of the site.'}</p>
          )}
          <p className="mt-5 text-[13.5px]"><a className="text-accent-2 underline hover:text-ink" href="#/results">All experiments, with intervals</a></p>
        </section>

        <section className="mt-20 border-t border-line pt-12 md:mt-24 md:pt-16" aria-labelledby="how-h">
          <SectionTitle title="How it works" id="how-h" />
          <ol className="grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.t}>
                <div className="serif text-[40px] font-semibold leading-none text-accent" aria-hidden="true">{i + 1}</div>
                <h3 className="mt-3 text-[16px] font-semibold text-ink">{s.t}</h3>
                <p className="mt-1.5 text-[14.5px] leading-relaxed text-ink-2 text-pretty">{s.d}</p>
              </li>
            ))}
          </ol>
          <p className="mt-8 text-[14.5px]"><a className="text-accent-2 underline hover:text-ink" href="#/how-it-works">Each forensic test, with a chart</a></p>
        </section>
      </Page>
    </>
  )
}

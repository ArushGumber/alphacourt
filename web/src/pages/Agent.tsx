import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Page } from '../components/Layout'
import { IconPause, IconPlay, IconRestart } from '../components/Icons'
import { Badge, Button, LinkButton, Loading, Note, PageHeader, SectionTitle, Segmented, cx } from '../components/ui'
import { LIVE, getAgentSession } from '../data/api'
import { useAsync, useReducedMotion } from '../data/hooks'
import { RULING_LABEL, RULING_PLAIN, SIN_LABEL, TEST_LABEL, money } from '../lib/labels'
import { readParams } from '../router'
import type { AgentStep, TrialRecord } from '../types'

/** Milliseconds before a step appears, at speed 1. */
const DELAY: Record<AgentStep['kind'], number> = { text: 1500, call: 1000, result: 800, report: 2200, trial: 1800 }

/** Bold, inline code and the one table the agent's report uses. No other markdown is expected. */
function inline(s: string): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) =>
    p.startsWith('**') ? <strong key={i} className="font-semibold text-ink">{p.slice(2, -2)}</strong>
      : p.startsWith('`') ? <code key={i} className="mono rounded-[3px] bg-bg-2 px-1 py-px text-[0.9em]">{p.slice(1, -1)}</code>
        : <Fragment key={i}>{p}</Fragment>,
  )
}
function Prose({ text }: { text: string }) {
  const blocks = text.trim().split(/\n{2,}/)
  return (
    <div className="space-y-3">
      {blocks.map((b, i) => {
        const rows = b.split('\n')
        if (rows[0].trim().startsWith('|')) {
          const cells = rows.filter((r) => !/^\|\s*-/.test(r)).map((r) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim()))
          return (
            <div key={i} className="overflow-x-auto">
              <table className="w-full max-w-[620px] border-collapse text-[14px]">
                <thead><tr>{cells[0].map((c, j) => <th key={j} className={cx('border-b border-line-2 py-1.5 pr-4 text-left font-medium text-ink-3', j > 0 && 'text-right')}>{c}</th>)}</tr></thead>
                <tbody>{cells.slice(1).map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j} className={cx('border-b border-line py-1.5 pr-4 align-top', j > 0 ? 'num text-right' : 'text-ink-2')}>{inline(c)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )
        }
        return <p key={i}>{inline(b.replace(/\n/g, ' '))}</p>
      })}
    </div>
  )
}

function Step({ s }: { s: AgentStep }) {
  switch (s.kind) {
    case 'text':
      return <p className="text-[15.5px] leading-[1.65] text-ink">{s.text}</p>
    case 'report':
      return (
        <div className="rounded-[6px] border border-line-2 bg-bg-2/60 px-4 py-3.5 text-[15px] leading-[1.65] text-ink-2">
          <div className="label mb-2">Final report</div>
          <Prose text={s.text} />
        </div>
      )
    case 'call': {
      const spec = s.args.spec as Record<string, unknown> | undefined
      const claim = s.args.claim as Record<string, unknown> | undefined
      const hasArgs = Object.keys(s.args).length > 0
      return (
        <div className="mono text-[13px] leading-[1.6] text-ink">
          <div><span className="text-accent-2" aria-hidden>&rsaquo; </span><span className="font-semibold">{s.tool}</span>{!hasArgs && <span className="text-ink-4">()</span>}</div>
          {hasArgs && (
            <div className="ml-4 mt-0.5 space-y-0.5 text-ink-3">
              {spec && <div className="break-words"><span className="text-ink-4">signal </span><span className="text-ink-2">{String(spec.signal)}</span><span className="text-ink-4">, rebalance </span>{String(spec.rebalance)}<span className="text-ink-4">, costs </span>{String(spec.costs_bps)} bps</div>}
              {claim && <div className="break-words"><span className="text-ink-4">claim </span>Sharpe {String(claim.sharpe)}, return {String(claim.ann_return)}, drawdown {String(claim.max_drawdown)}</div>}
              {claim && <div className="break-words text-ink-2">&ldquo;{String(claim.text)}&rdquo;</div>}
              {s.args.requested_capital !== undefined && <div><span className="text-ink-4">capital </span>{money(Number(s.args.requested_capital))}</div>}
              {!spec && Object.entries(s.args).map(([k, v]) => <div key={k}><span className="text-ink-4">{k} </span>{typeof v === 'string' ? v : JSON.stringify(v)}</div>)}
            </div>
          )}
        </div>
      )
    }
    case 'result':
      return (
        <div className="mono ml-4 border-l-2 border-line-2 pl-3 text-[12.5px] leading-[1.55] text-ink-3">
          <div className="break-words">{s.summary}</div>
          {s.detail && <div className="text-ink-4">{s.detail}</div>}
        </div>
      )
    default:
      return null
  }
}

function Ruling({ rec, caseId }: { rec: TrialRecord; caseId: string }) {
  const v = rec.verdict
  return (
    <section aria-labelledby="ruling-h" className="panel rise p-4 md:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <div>
          <div className="label">The court&rsquo;s record, case {caseId}</div>
          <h3 id="ruling-h" className="serif mt-1 text-[26px] font-semibold leading-tight text-ink">{RULING_LABEL[v.ruling]}</h3>
          <p className="mt-0.5 text-[13.5px] text-ink-3">{RULING_PLAIN[v.ruling]}. Capital allowed: {money(v.capital_allowed)}.</p>
        </div>
        {LIVE && <LinkButton size="sm" href={`#/court/${caseId}`}>Open in the Courtroom</LinkButton>}
      </div>
      <p className="mt-4 max-w-[78ch] text-[14.5px] leading-[1.65] text-ink-2">{v.opinion}</p>

      <div className="mt-5 grid gap-6 md:grid-cols-2">
        <div>
          <h4 className="label mb-2">Findings</h4>
          <ul className="space-y-1.5 text-[14px]">
            {v.findings.map((f, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-2">
                <span className="font-medium text-ink">{SIN_LABEL[f.sin] ?? f.sin}</span>
                <Badge tone={f.sustained && !f.struck ? 'accent' : 'neutral'}>{f.struck ? 'struck' : f.sustained ? 'sustained' : 'not sustained'}</Badge>
                <span className="mono text-[12px] text-ink-4">{f.exhibits.join(', ')}</span>
              </li>
            ))}
            {v.findings.length === 0 && <li className="text-ink-3">None.</li>}
          </ul>
        </div>
        <div>
          <h4 className="label mb-2">Exhibits</h4>
          <ul className="space-y-2.5 text-[13.5px] leading-snug">
            {rec.exhibits.map((e) => (
              <li key={e.id}>
                <span className="mono text-[12px] text-ink-4">{e.id}</span> <span className="font-medium text-ink">{TEST_LABEL[e.test] ?? e.test}</span>
                <div className="text-ink-3">{e.summary}</div>
              </li>
            ))}
          </ul>
        </div>
      </div>
      {!LIVE && <p className="mt-5 text-[12.5px] text-ink-4">This is the record as the gateway saved it. The live Courtroom shows the same case when the site is connected to a gateway.</p>}
    </section>
  )
}

export default function Agent() {
  const sess = useAsync(() => getAgentSession(), [])
  const steps = sess.data?.value.steps
  const reduced = useReducedMotion()
  const params = useMemo(() => readParams(), [])
  const [speed, setSpeed] = useState(1)
  const [shown, setShown] = useState<number | null>(null) // null until the data is in
  const [playing, setPlaying] = useState(false)
  const total = steps?.length ?? 0
  const endRef = useRef<HTMLDivElement>(null)
  const scrolling = useRef(false)

  // start: from the top when motion is welcome, fully shown when it is not (or when ?end=1)
  useEffect(() => {
    if (!steps) return
    if (reduced || params.get('end') === '1') setShown(steps.length)
    else {
      setShown(0)
      setPlaying(params.get('play') !== '0')
    }
  }, [steps, reduced, params])

  useEffect(() => {
    if (!playing || shown === null || !steps) return
    if (shown >= total) return setPlaying(false)
    const d = shown === 0 ? 600 : DELAY[steps[shown - 1].kind]
    const t = window.setTimeout(() => { scrolling.current = true; setShown((s) => (s ?? 0) + 1) }, d / speed)
    return () => window.clearTimeout(t)
  }, [playing, shown, total, steps, speed])

  useEffect(() => {
    if (scrolling.current) {
      scrolling.current = false
      endRef.current?.scrollIntoView({ block: 'end', behavior: reduced ? 'auto' : 'smooth' })
    }
  }, [shown, reduced])

  const done = shown !== null && shown >= total
  const toggle = useCallback(() => {
    if (done) { setShown(0); setPlaying(true) } else setPlaying((p) => !p)
  }, [done])

  if (sess.loading) return <Page><Loading /></Page>
  if (sess.error || !sess.data || !steps || shown === null) return <Page><PageHeader title="A real agent, attached" /><Note>The recorded session could not be loaded.</Note></Page>

  const { meta } = sess.data.value
  const visible = steps.slice(0, shown)
  const trial = steps.find((s): s is Extract<AgentStep, { kind: 'trial' }> => s.kind === 'trial')
  const backtests = steps.filter((s) => s.kind === 'call' && s.tool === 'run_backtest').length
  const submit = steps.find((s) => s.kind === 'call' && s.tool === 'submit_strategy') as Extract<AgentStep, { kind: 'call' }> | undefined
  const claim = submit?.args.claim as { sharpe: number } | undefined
  const asked = submit?.args.requested_capital as number | undefined
  const rec = trial?.record
  const sustained = rec?.verdict.findings.filter((f) => f.sustained && !f.struck).map((f) => (SIN_LABEL[f.sin] ?? f.sin).toLowerCase()) ?? []

  return (
    <Page>
      <PageHeader title="A real agent, attached">
        <p>
          We connected Claude Code ({meta.model}) to AlphaCourt. It could use only AlphaCourt&rsquo;s tools, and its brief rewarded a high Sharpe ratio.
          Below is its recorded session, step by step, then the court&rsquo;s record of what it submitted.
        </p>
      </PageHeader>

      <figure className="mb-8 max-w-[760px] border-l-2 border-accent pl-4">
        <figcaption className="label mb-1">The brief</figcaption>
        <blockquote className="serif text-[19px] leading-snug text-ink">{meta.brief}</blockquote>
      </figure>

      <div className="sticky top-[60px] z-20 -mx-1 mb-6 flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line bg-bg px-1 py-3" data-controls>
        <Button variant="primary" onClick={toggle} aria-label={playing ? 'Pause' : done ? 'Replay' : 'Play'} className="w-[96px]">
          {playing ? <><IconPause size={14} /> Pause</> : done ? <><IconRestart size={14} /> Replay</> : <><IconPlay size={14} /> Play</>}
        </Button>
        <Segmented label="Replay speed" size="sm" value={String(speed)} onChange={(v) => setSpeed(Number(v))} options={[1, 2, 4].map((s) => ({ value: String(s), label: `${s}×` }))} />
        <Button variant="ghost" onClick={() => { setPlaying(false); setShown(total) }} disabled={done}>Skip to end</Button>
        <span className="label ml-auto" aria-live="off">Step {shown} of {total}</span>
      </div>

      <div className="max-w-[860px] space-y-4" aria-live="polite" aria-label="Session transcript">
        {visible.filter((s) => s.kind !== 'trial').map((s, i) => (
          <div key={i} className={cx(!reduced && 'rise')}><Step s={s} /></div>
        ))}
        {rec && visible.some((s) => s.kind === 'trial') && <div className="pt-2"><Ruling rec={rec} caseId={trial!.case_id} /></div>}
        <div ref={endRef} className="scroll-mb-8" />
      </div>

      {done && rec && (
        <section className="mt-12 max-w-[760px] border-t border-line pt-6">
          <SectionTitle title="What happened" />
          <p className="text-[15.5px] leading-[1.7] text-ink-2">
            The agent ran {backtests} backtests using only data as first published. It left out the three fields it said were not known at the time
            (<span className="mono text-[0.92em]">eps_restated</span>, <span className="mono text-[0.92em]">sentiment_revised</span>, <span className="mono text-[0.92em]">index_member_now</span>).
            It submitted the best of the four with an honest claim{claim ? ` (Sharpe ${claim.sharpe})` : ''}, said plainly that it missed the 2.5 target, and asked for {asked ? money(asked) : 'a smaller amount of capital'}.
            The court sustained {sustained.length} finding{sustained.length === 1 ? '' : 's'}{sustained.length ? ` (${sustained.join(' and ')})` : ''} and ruled {RULING_LABEL[rec.verdict.ruling].toLowerCase()}.
            The ruling arrived after the agent had stopped checking. This is one agent in one session. It shows the whole system working, but not how often agents behave this way.
          </p>
        </section>
      )}
    </Page>
  )
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getLab, getLiveCase, labBacktest, labTrial, labTruth, LIVE, serverUp, streamEvents, TRIAL_EVENTS, type LabBacktest, type LabScenario, type LabTruth } from '../data/api'
import { useAsync } from '../data/hooks'
import type { CaseFile, TrialEvent, Verdict } from '../types'
import { Page } from '../components/Layout'
import { Button, Caption, LinkButton, Loading, Note, Segmented, Select, Stat, cx } from '../components/ui'
import { EquityChart } from '../components/charts'
import { Feed } from '../components/court/Feed'
import { RULING_LABEL, sh } from '../lib/labels'

const WORLD = 'demo'
const SLOW = 'rank(eps_reported) + rank(delay(ts_sum(ret,231),21))'
const FAST = 'rank(-ts_sum(ret,3))'
const SENT = 'rank(ts_mean(sentiment,5))'
const PRESETS = [
  { value: SLOW, label: 'Earnings surprise plus 12-month momentum' },
  { value: FAST, label: 'Short-term reversal (3 days, trades often)' },
  { value: SENT, label: 'Sentiment, 5-day average' },
]

interface Form { signal: string; lag: number; costs: number; universe: 'all' | 'survivors' }
const HONEST: Form = { signal: SLOW, lag: 1, costs: 10, universe: 'all' }

const FLAWS = [
  { id: 'same_bar', title: 'Trade on the same bar', text: 'The strategy uses the closing price that produced its own signal, so it trades on news it could not have had yet.' },
  { id: 'no_costs', title: 'Ignore costs', text: 'Trading is treated as free. It matters most for a fast strategy, so this switches to the short-term signal.' },
  { id: 'survivors', title: "Only today's survivors", text: 'The test uses only companies that still exist, so the ones that failed never appear.' },
  { id: 'revised', title: 'Use revised data', text: 'The test reads figures as they were corrected months later, not as they were first published.' },
  { id: 'zfull', title: 'Normalise with the full sample', text: 'Scores are scaled with averages that include the future. This can raise or lower the claim.' },
] as const
type FlawId = (typeof FLAWS)[number]['id']

function buildSpec(form: Form, flaws: Set<FlawId>, name: string) {
  const base = flaws.has('no_costs') && form.signal === SLOW ? FAST : form.signal
  let signal = base
  if (flaws.has('revised')) signal = signal.replace(/\beps_reported\b/g, 'eps_restated').replace(/\bsentiment\b/g, 'sentiment_revised')
  if (flaws.has('zfull')) signal = `zscore_full(${signal})`
  if (flaws.has('same_bar')) signal = `${signal} + 0.005*rank(ret)`
  const honest = { name: 'Honest version', signal: base, lag: form.lag, costs_bps: form.costs, universe: form.universe }
  const flawed = {
    name,
    signal,
    lag: flaws.has('same_bar') ? 0 : form.lag,
    costs_bps: flaws.has('no_costs') ? 0 : form.costs,
    universe: flaws.has('survivors') ? 'survivors' : form.universe,
  }
  return { honest, flawed, swappedSignal: base !== form.signal }
}

const pct = (v: number) => `${(v * 100).toFixed(1)}%`

// ---------------------------------------------------------------- backtest panel

function BacktestPanel({ claimed, honest, flawed, loading, error }: { claimed: LabBacktest | null; honest: LabBacktest | null; flawed: boolean; loading: boolean; error?: string }) {
  if (error) return <Note tone="warn">{error}</Note>
  if (!claimed) return <Loading label="Running the backtest" />
  const m = claimed.metrics
  const h = honest?.metrics
  const series = flawed && honest ? [{ label: 'Honest', y: honest.equity }, { label: 'As claimed', y: claimed.equity }] : [{ label: 'Backtest', y: claimed.equity }]
  const delta = (b: number | undefined, f: (v: number) => string) => (flawed && b !== undefined ? `honest: ${f(b)}` : undefined)
  return (
    <div className={cx('transition-opacity duration-200', loading && 'opacity-55')} aria-busy={loading}>
      <div className="grid grid-cols-3 gap-4">
        <Stat label={flawed ? 'Claimed Sharpe' : 'Sharpe'} value={sh(m.sharpe)} sub={delta(h?.sharpe, sh)} />
        <Stat label="Return a year" value={pct(m.ann_return)} sub={delta(h?.ann_return, pct)} />
        <Stat label="Worst drawdown" value={pct(m.max_drawdown)} sub={delta(h?.max_drawdown, pct)} />
      </div>
      <div className="mt-5">
        <EquityChart series={series} height={230} yLabel="Cumulative P&L, % of capital" xLabel="Research period, about 9 years" label={`Backtest equity curve, Sharpe ${sh(m.sharpe)}`} accentLast />
      </div>
      <Caption className="mt-2">
        The orange line is what the backtest reports{flawed ? '; the grey line is the same strategy tested honestly' : ''}. The Sharpe ratio is return per unit of risk, annualised; above 1 looks good to most desks.
      </Caption>
      {flawed && claimed.notes.length > 0 && (
        <ul className="mt-3 space-y-1 text-[13px] text-ink-3">
          {claimed.notes.map((n) => <li key={n}>Engine note: {n}.</li>)}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- truth

function TruthPanel({ claimed, truth, ruling, rulingLabel }: { claimed: number; truth: LabTruth; ruling?: Verdict['ruling']; rulingLabel?: string }) {
  const real = truth.sharpe >= 0.5
  const none = truth.sharpe < 0.3
  const gap = claimed - truth.sharpe
  const verdictLine = (() => {
    if (!ruling) return none ? 'This strategy has no edge on fresh data.' : real ? (gap > 0.4 ? 'This strategy has a real edge, but the backtest overstated it.' : 'This strategy has a real edge, and the backtest was close to honest.') : 'This strategy has a weak edge.'
    if (ruling === 'deploy') return none ? 'The court deployed a strategy with no edge. This is a miss.' : 'The court deployed a strategy that earns on sealed data. This is correct.'
    if (none) return 'The court stopped a strategy with no edge. This is correct.'
    if (gap > 0.4) return 'The court held back an inflated claim: the strategy earns on sealed data, but far less than it said. Holding it was reasonable.'
    return real ? 'The court stopped a strategy that earns what it claimed. This is a false alarm.' : 'The court stopped a strategy with a weak edge.'
  })()
  return (
    <section aria-label="The truth" className="panel p-5 md:p-6">
      <h3 className="serif text-[24px] font-semibold text-ink">The truth</h3>
      <p className="mt-1 max-w-[64ch] text-[14.5px] leading-relaxed text-ink-2">
        The strategy tested again with point-in-time data, a one-bar delay, full costs and the full universe, on bars nobody saw: fresh simulated worlds with the same planted effects.
      </p>
      <div className="mt-5 grid grid-cols-2 gap-6 md:grid-cols-4">
        <Stat label="Claimed Sharpe" value={<span className="text-ink-3 line-through decoration-[1.5px]">{sh(claimed)}</span>} />
        <Stat label="True Sharpe, sealed data" value={<span className={none ? 'text-accent-2' : 'text-ink'}>{sh(truth.sharpe)}</span>} sub={`Three fresh worlds: ${truth.per_seed.map(sh).join(', ')}`} />
        {ruling && <Stat label="The court ruled" value={<span className="serif">{rulingLabel ?? RULING_LABEL[ruling]}</span>} />}
      </div>
      <p className={cx('mt-5 border-t border-line pt-4 text-[15.5px] font-medium', ruling && ((ruling === 'deploy') === none) ? 'text-accent-2' : 'text-ink')}>{verdictLine}</p>
      <p className="mt-1 text-[12.5px] text-ink-3">{truth.how}</p>
    </section>
  )
}

// ---------------------------------------------------------------- live trial adapter (as in the Courtroom)

function adaptLive(name: string, ev: Record<string, any>, file: CaseFile | null): TrialEvent | null {
  const d = (ev.data ?? {}) as Record<string, unknown>
  const out = (data: Record<string, unknown>): TrialEvent => ({ t: Number(ev.t), role: ev.role, kind: ev.kind ?? name, data })
  if (ev.role === 'gateway') return ev.kind === 'error' ? out({ text: String(d.error ?? 'The trial failed.') }) : null
  if (name === 'case') return file ? out(file as unknown as Record<string, unknown>) : null
  if (name === 'error') return out({ text: String(d.error ?? d.text ?? 'An error occurred.') })
  return out(d)
}

// ---------------------------------------------------------------- toggles

function Switch({ on, onChange, title, text, id }: { on: boolean; onChange: (v: boolean) => void; title: string; text: string; id: string }) {
  return (
    <div className="flex items-start gap-3 py-3">
      <button type="button" role="switch" aria-checked={on} aria-labelledby={`${id}-t`} aria-describedby={`${id}-d`} onClick={() => onChange(!on)}
        className={cx('relative mt-0.5 h-[22px] w-[40px] shrink-0 rounded-full border transition-colors duration-150', on ? 'border-accent bg-accent' : 'border-line-3 bg-bg-3')}>
        <span className={cx('absolute top-[2px] h-4 w-4 rounded-full bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.08)] transition-[left] duration-150', on ? 'left-[20px]' : 'left-[2px]')} />
      </button>
      <div className="min-w-0 cursor-pointer" onClick={() => onChange(!on)}>
        <div id={`${id}-t`} className="text-[14.5px] font-medium leading-snug text-ink">{title}</div>
        <div id={`${id}-d`} className="mt-0.5 text-[13px] leading-snug text-ink-3">{text}</div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- live lab

const btCache = new Map<string, Promise<LabBacktest>>()
function runBt(spec: unknown): Promise<LabBacktest> {
  const k = JSON.stringify(spec)
  if (!btCache.has(k)) {
    const p = labBacktest(spec, WORLD)
    p.catch(() => btCache.delete(k))
    btCache.set(k, p)
  }
  return btCache.get(k)!
}

function LiveLab() {
  const [form, setForm] = useState<Form>(HONEST)
  const [flaws, setFlaws] = useState<Set<FlawId>>(new Set())
  const [tries, setTries] = useState<'one' | 'many'>('one')
  const built = useMemo(() => buildSpec(form, flaws, flaws.size ? 'Strategy with planted flaws' : 'Honest strategy'), [form, flaws])
  const [res, setRes] = useState<{ claimed: LabBacktest; honest: LabBacktest } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const key = JSON.stringify(built)

  useEffect(() => {
    let live = true
    setLoading(true)
    const t = window.setTimeout(() => {
      Promise.all([runBt(built.flawed), flaws.size ? runBt(built.honest) : runBt(built.flawed)])
        .then(([c, h]) => { if (live) { setRes({ claimed: c, honest: h }); setError(''); setLoading(false) } })
        .catch((e: Error) => { if (live) { setError(e.message.includes('signal') || e.message.includes('Invalid') || e.message.includes('Unknown') ? `The signal could not be run: ${e.message}` : e.message); setLoading(false) } })
    }, 220)
    return () => { live = false; window.clearTimeout(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  // a new strategy invalidates the trial and the truth
  const [caseId, setCaseId] = useState<string | null>(null)
  const [events, setEvents] = useState<TrialEvent[]>([])
  const [state, setState] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [trialError, setTrialError] = useState('')
  const [truth, setTruth] = useState<LabTruth | null>(null)
  const [truthError, setTruthError] = useState('')
  const [sent, setSent] = useState<{ claimed: number; spec: unknown } | null>(null)
  const closeRef = useRef<(() => void) | null>(null)
  useEffect(() => () => closeRef.current?.(), [])
  useEffect(() => {
    if (!sent) return
    closeRef.current?.()
    setCaseId(null); setEvents([]); setState('idle'); setTruth(null); setSent(null); setTrialError(''); setTruthError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tries])

  const send = useCallback(async () => {
    if (!res) return
    const m = res.claimed.metrics
    const many = tries === 'many'
    const caseFile = {
      case_id: 'lab',
      world_id: WORLD,
      spec: { ...built.flawed, params: { source: 'flaw lab' }, notes: '' },
      claim: { sharpe: m.sharpe, ann_return: m.ann_return, max_drawdown: m.max_drawdown, text: 'Backtest from the Flaw Lab.' },
      requested_capital: 1_000_000,
      log_summary: many ? { n_trials: 40, n_distinct_specs: 40, best_of: 1, is_best: true, grid: {} } : { n_trials: 1, n_distinct_specs: 1, best_of: 1, is_best: true, grid: {} },
      pages_read: [],
    }
    closeRef.current?.()
    setEvents([]); setTruth(null); setTruthError(''); setTrialError(''); setState('running')
    setSent({ claimed: m.sharpe, spec: built.flawed })
    try {
      const { case_id } = await labTrial(caseFile, WORLD)
      setCaseId(case_id)
      const file = (await getLiveCase(case_id)).case
      closeRef.current = streamEvents(`/api/cases/${encodeURIComponent(case_id)}/events`, TRIAL_EVENTS,
        (name, ev) => { const e = adaptLive(name, ev, file); if (e) setEvents((l) => [...l, e]) },
        (err) => { setState(err ? 'error' : 'done'); if (err) setTrialError(err) })
    } catch (e) {
      setState('error'); setTrialError((e as Error).message)
    }
  }, [res, tries, built])

  useEffect(() => {
    if (state !== 'done' || !sent || truth) return
    labTruth(sent.spec, WORLD).then(setTruth, (e: Error) => setTruthError(e.message))
  }, [state, sent, truth])

  const verdict = events.find((e) => e.kind === 'verdict')?.data as unknown as Verdict | undefined
  const set = (id: FlawId, on: boolean) => setFlaws((s) => { const n = new Set(s); if (on) n.add(id); else n.delete(id); return n })
  const flawed = flaws.size > 0

  return (
    <>
      <div className="grid gap-x-12 gap-y-10 lg:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
        <div className="space-y-10">
          <section aria-labelledby="s1">
            <h2 id="s1" className="serif text-[22px] font-semibold text-ink"><span className="num text-ink-4">1.</span> Start from an honest strategy</h2>
            <p className="mt-1.5 text-[14px] text-ink-3">It ranks companies by their reported earnings and their past-year return, and holds the top fifth long and the bottom fifth short. Edit anything.</p>
            <div className="panel mt-4 space-y-4 p-4">
              <Select label="Signal preset" value={PRESETS.some((p) => p.value === form.signal) ? form.signal : ''} onChange={(v) => v && setForm({ ...form, signal: v })}
                options={[...(PRESETS.some((p) => p.value === form.signal) ? [] : [{ value: '', label: 'Custom signal' }]), ...PRESETS]} />
              <label className="block">
                <span className="label">Signal formula</span>
                <input value={form.signal} onChange={(e) => setForm({ ...form, signal: e.target.value })} spellCheck={false} maxLength={300}
                  className="mono mt-1.5 h-9 w-full rounded-[6px] border border-line-2 bg-bg-1 px-2.5 text-[13px] text-ink focus:border-accent focus:outline-none" />
              </label>
              <div className="grid grid-cols-3 gap-3">
                <label className="block"><span className="label">Delay (bars)</span>
                  <input type="number" min={0} max={5} value={form.lag} onChange={(e) => setForm({ ...form, lag: Math.max(0, Math.min(5, Number(e.target.value) || 0)) })}
                    className="num mt-1.5 h-9 w-full rounded-[6px] border border-line-2 bg-bg-1 px-2.5 text-[14px] focus:border-accent focus:outline-none" /></label>
                <label className="block"><span className="label">Costs (bps)</span>
                  <input type="number" min={0} max={100} value={form.costs} onChange={(e) => setForm({ ...form, costs: Math.max(0, Math.min(100, Number(e.target.value) || 0)) })}
                    className="num mt-1.5 h-9 w-full rounded-[6px] border border-line-2 bg-bg-1 px-2.5 text-[14px] focus:border-accent focus:outline-none" /></label>
                <Select label="Universe" value={form.universe} onChange={(v) => setForm({ ...form, universe: v as Form['universe'] })} options={[{ value: 'all', label: 'All' }, { value: 'survivors', label: 'Survivors' }]} />
              </div>
              <p className="text-[12.5px] text-ink-3">Data room: <span className="mono">{WORLD}</span>, a simulated market with planted effects.</p>
            </div>
          </section>

          <section aria-labelledby="s2">
            <h2 id="s2" className="serif text-[22px] font-semibold text-ink"><span className="num text-ink-4">2.</span> Plant a flaw</h2>
            <p className="mt-1.5 text-[14px] text-ink-3">Switch on one or several. The backtest runs again each time.</p>
            <div className="panel mt-4 divide-y divide-line px-4">
              {FLAWS.map((f) => <Switch key={f.id} id={`f-${f.id}`} on={flaws.has(f.id)} onChange={(v) => set(f.id, v)} title={f.title} text={f.text} />)}
            </div>
            {built.swappedSignal && <p className="mt-2 text-[12.5px] text-ink-3">Costs only matter for a fast strategy, so the test uses <span className="mono">{FAST}</span> in place of the slow signal.</p>}
          </section>
        </div>

        <div className="min-w-0 lg:sticky lg:top-[78px] lg:self-start">
          <section className="panel p-5 md:p-6" aria-label="Backtest result">
            <h2 className="serif text-[22px] font-semibold text-ink">{flawed ? 'What the backtest now claims' : 'The honest backtest'}</h2>
            <p className="mb-5 mt-1 text-[14px] text-ink-3">{flawed ? `${flaws.size} flaw${flaws.size > 1 ? 's' : ''} planted. The numbers are for the research period, as the strategy's author would see them.` : 'Research period only. The last quarter of the data is sealed.'}</p>
            <BacktestPanel claimed={res?.claimed ?? null} honest={res?.honest ?? null} flawed={flawed} loading={loading} error={error} />
          </section>
        </div>
      </div>

      <section aria-labelledby="s3" className="mt-14 border-t border-line pt-10">
        <h2 id="s3" className="serif text-[22px] font-semibold text-ink"><span className="num text-ink-4">3.</span> Send it to court</h2>
        <p className="mt-1.5 max-w-[70ch] text-[14px] text-ink-3">The claim in the case file is the backtest above. The research log says how many versions were tried before this one.</p>
        <div className="mt-4 flex flex-wrap items-end gap-x-6 gap-y-3">
          <div className="flex flex-col gap-1.5">
            <span className="label">Research log</span>
            <Segmented label="How many versions were tried" value={tries} onChange={setTries} options={[{ value: 'one', label: 'This one, tried once' }, { value: 'many', label: 'Best of many tries' }]} />
          </div>
          <Button variant="primary" size="lg" onClick={send} disabled={!res || loading || state === 'running'}>{state === 'running' ? 'The court is sitting' : 'Send to court'}</Button>
          {caseId && <LinkButton variant="outline" size="lg" href={`#/court/${caseId}`}>Open in the full courtroom</LinkButton>}
        </div>
        {state === 'error' && <Note tone="warn" className="mt-4">{trialError || 'The trial failed.'}</Note>}
        {events.length > 0 && (
          <div className="mt-6 max-w-[860px]">
            <Feed events={events} shown={events.length} flash={null} truth={null} claimed={sent?.claimed ?? 0} onJump={(id) => document.getElementById(`ex-${id}`)?.scrollIntoView({ block: 'center' })} live />
            {state === 'running' && <p className="mt-4 text-[13.5px] text-ink-3" role="status">The court is still working…</p>}
          </div>
        )}
      </section>

      {state === 'done' && (
        <section aria-labelledby="s4" className="mt-12">
          <h2 id="s4" className="sr-only">The truth</h2>
          {truth && sent ? <TruthPanel claimed={sent.claimed} truth={truth} ruling={verdict?.ruling} /> : truthError ? <Note tone="warn">{truthError}</Note> : <Loading label="Scoring the strategy on sealed data" />}
        </section>
      )}
    </>
  )
}

// ---------------------------------------------------------------- recorded walk-through

function RecordedLab() {
  const lab = useAsync(() => getLab(), [])
  const [key, setKey] = useState('honest')
  const scenarios: LabScenario[] = lab.data?.value.scenarios ?? []
  const s = scenarios.find((x) => x.key === key) ?? scenarios[0]
  if (lab.loading && !s) return <Loading label="Loading the walk-through" />
  if (!s) return <Note tone="warn">The recorded walk-through is not in this copy of the site.</Note>
  const flawed = s.flaws.length > 0
  const spec = s.spec as { signal: string; lag: number; costs_bps: number; universe: string }
  return (
    <>
      <Note className="mb-8">This copy of the site has no live server, so the Lab shows a recorded walk-through: six strategies, run on the same data room. Sending a strategy to court needs the server, so no trial runs here. <a className="text-accent-2 underline hover:text-ink" href="#/courtroom">Watch a recorded trial in the Courtroom.</a></Note>
      <div className="mb-6 overflow-x-auto pb-1" role="group" aria-label="Scenario">
        <div className="flex gap-2">
          {scenarios.map((x) => (
            <Button key={x.key} variant="chip" active={x.key === s.key} onClick={() => setKey(x.key)} className="h-9">{x.label}</Button>
          ))}
        </div>
      </div>
      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
        <div>
          <h2 className="serif text-[22px] font-semibold text-ink">{s.label}</h2>
          <p className="mt-1.5 text-[14px] text-ink-3">{flawed ? s.flaws.map((f) => FLAWS.find((x) => x.id === f)?.text).filter(Boolean).join(' ') : 'No flaw planted. The strategy is tested honestly.'}</p>
          <dl className="panel mt-4 space-y-2 p-4 text-[13.5px]">
            <div><dt className="label">Signal</dt><dd className="mono mt-0.5 break-words text-[12.5px] text-ink">{spec.signal}</dd></div>
            <div className="grid grid-cols-3 gap-3">
              <div><dt className="label">Delay</dt><dd className="num">{spec.lag} bar{spec.lag === 1 ? '' : 's'}</dd></div>
              <div><dt className="label">Costs</dt><dd className="num">{spec.costs_bps} bps</dd></div>
              <div><dt className="label">Universe</dt><dd>{spec.universe}</dd></div>
            </div>
          </dl>
        </div>
        <section className="panel p-5 md:p-6" aria-label="Backtest result">
          <BacktestPanel claimed={s.claimed} honest={s.honest} flawed={flawed} loading={false} />
        </section>
      </div>
      <div className="mt-10"><TruthPanel claimed={s.claimed.metrics.sharpe} truth={s.truth} /></div>
    </>
  )
}

export default function Lab() {
  const [up, setUp] = useState<boolean | null>(LIVE ? null : false)
  useEffect(() => { if (LIVE) serverUp().then(setUp) }, [])
  return (
    <Page>
      <header className="mb-10 max-w-[760px] md:mb-12">
        <h1 tabIndex={-1} data-page-title className="serif text-[34px] font-semibold leading-[1.1] text-ink outline-none text-balance md:text-[44px]">Flaw Lab</h1>
        <p className="mt-3 text-[16.5px] leading-[1.65] text-ink-2 text-pretty">
          A backtest can lie without anyone lying. Start from a sound strategy, plant a flaw that real research pipelines make by accident, and watch the claimed numbers rise. Then send it to court and compare the ruling with what the strategy really earns.
        </p>
      </header>
      {up === null ? <Loading label="Looking for the server" /> : up ? <LiveLab /> : <RecordedLab />}
      <div className="h-20" />
    </Page>
  )
}

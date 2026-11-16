import { useEffect, useRef, type ReactNode } from 'react'
import type { Charge, CaseFile, Exhibit, Rebuttal, TrialEvent, Truth, Verdict, Finding } from '../../types'
import { HINT_LABEL, NUMBER_LABEL, RULING_LABEL, RULING_PLAIN, ROLE_LABEL, SIN_LABEL, SIN_PLAIN, TEST_LABEL, caseNo, money, sh } from '../../lib/labels'
import { ExhibitChart, EquityChart } from '../charts'
import { IconCheck, IconClose, IconDoc } from '../Icons'
import { cx } from '../ui'

const ROLE_COLOR: Record<string, string> = {
  prosecution: 'text-accent-2', defence: 'text-cool', judge: 'text-ink', rule: 'text-accent-2', clerk: 'text-ink-3', gateway: 'text-ink-3', system: 'text-ink-3',
}

function Head({ role, t, extra }: { role: string; t?: number; extra?: ReactNode }) {
  return (
    <div className="mb-1.5 flex items-baseline gap-2 text-[13px]">
      <span className={cx('font-semibold', ROLE_COLOR[role] ?? 'text-ink-2')}>{ROLE_LABEL[role] ?? role}</span>
      {extra && <span className="text-ink-3">{extra}</span>}
      {t != null && <span className="mono ml-auto text-[11.5px] text-ink-4">{t.toFixed(1)} s</span>}
    </div>
  )
}

/** A reference to an exhibit. It scrolls to the card when the card is on the page. */
export function ExhibitChip({ id, known, onJump }: { id: string; known: boolean; onJump: (id: string) => void }) {
  if (!known)
    return <span className="mono inline-flex items-center rounded-[4px] border border-dashed border-line-3 px-1.5 text-[12px] leading-[20px] text-ink-3 line-through" title="No such exhibit in this record">{id}</span>
  return (
    <button type="button" onClick={() => onJump(id)} className="mono inline-flex items-center rounded-[4px] border border-accent/45 bg-bg-1 px-1.5 text-[12px] font-medium leading-[20px] text-accent-2 hover:bg-accent-wash" aria-label={`Go to exhibit ${id}`}>
      {id}
    </button>
  )
}

const hintTone = (h: Exhibit['hint']) => (h === 'damaging' ? 'text-accent-2' : h === 'supportive' ? 'text-cool' : 'text-ink-3')
const hintGlyph = (h: Exhibit['hint']) => (h === 'damaging' ? '▼' : h === 'supportive' ? '▲' : '●')

function ExhibitCard({ ex, flash }: { ex: Exhibit; flash: boolean }) {
  const args = Object.entries(ex.params).filter(([, v]) => v != null)
  const nums = Object.entries(ex.numbers).filter(([, v]) => v != null)
  return (
    <article id={`ex-${ex.id}`} className={cx('panel p-4 transition-colors duration-700 md:p-5', flash && 'border-accent bg-accent-wash')} aria-label={`Exhibit ${ex.id}, ${TEST_LABEL[ex.test] ?? ex.test}`}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="mono text-[13px] font-semibold text-ink">{ex.id}</span>
        <h4 className="text-[15px] font-semibold text-ink">{TEST_LABEL[ex.test] ?? ex.test}{args.length > 0 && <span className="mono ml-2 text-[12.5px] font-normal text-ink-3">{args.map(([k, v]) => `${k}=${v}`).join(', ')}</span>}</h4>
        <span className={cx('ml-auto flex items-center gap-1.5 text-[12.5px] font-medium', hintTone(ex.hint))}><span aria-hidden="true" className="text-[9px]">{hintGlyph(ex.hint)}</span>{HINT_LABEL[ex.hint]}</span>
      </div>
      <p className="mt-2 text-[15.5px] leading-snug text-ink text-pretty">{ex.summary}</p>
      {ex.chart?.type && <div className="mt-3"><ExhibitChart chart={ex.chart} label={`${TEST_LABEL[ex.test] ?? ex.test}: ${ex.summary}`} /></div>}
      {nums.length > 0 && (
        <dl className="mt-3 grid grid-cols-2 gap-x-5 gap-y-2 border-t border-line pt-3 sm:grid-cols-4">
          {nums.map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="text-[12px] leading-tight text-ink-3">{NUMBER_LABEL[k] ?? k.replace(/_/g, ' ')}</dt>
              <dd className="num mt-0.5 text-[15px] font-medium text-ink">{typeof v === 'number' ? (Number.isInteger(v) ? v : sh(v)) : v}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className="mt-2.5 text-[12px] text-ink-4">Run by the {ROLE_LABEL[ex.called_by]?.toLowerCase() ?? ex.called_by}. A fixed test: the same strategy always gives the same result.</p>
    </article>
  )
}

function Cites({ ids, have, onJump }: { ids: string[]; have: Set<string>; onJump: (id: string) => void }) {
  if (!ids.length) return <span className="text-[13px] text-ink-3">cites no exhibit</span>
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className="text-[13px] text-ink-3">cites</span>
      {ids.map((id) => <ExhibitChip key={id} id={id} known={have.has(id)} onJump={onJump} />)}
    </span>
  )
}

function ChargeItem({ c, t, have, onJump }: { c: Charge; t: number; have: Set<string>; onJump: (id: string) => void }) {
  return (
    <div>
      <Head role="prosecution" t={t} extra="charges" />
      <h4 className="text-[16px] font-semibold text-ink">{SIN_LABEL[c.sin]}</h4>
      <p className="mt-1 text-[14.5px] leading-relaxed text-ink-2 text-pretty">{c.argument}</p>
      <div className="mt-2"><Cites ids={c.exhibits} have={have} onJump={onJump} /></div>
    </div>
  )
}

function RebuttalItem({ r, t, have, onJump }: { r: Rebuttal; t: number; have: Set<string>; onJump: (id: string) => void }) {
  return (
    <div>
      <Head role="defence" t={t} extra={r.concede ? 'concedes' : 'contests'} />
      <h4 className="text-[16px] font-semibold text-ink">{SIN_LABEL[r.sin]}</h4>
      <p className="mt-1 text-[14.5px] leading-relaxed text-ink-2 text-pretty">{r.argument}</p>
      <div className="mt-2"><Cites ids={r.exhibits} have={have} onJump={onJump} /></div>
    </div>
  )
}

function FindingRow({ f, have, onJump }: { f: Finding; have: Set<string>; onJump: (id: string) => void }) {
  const state = f.struck ? 'Struck' : f.sustained ? 'Sustained' : 'Not sustained'
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 gap-y-1 py-2.5 sm:grid-cols-[minmax(0,1.2fr)_110px_minmax(0,1fr)]">
      <span className={cx('text-[15px] font-medium', f.struck ? 'text-ink-3 line-through decoration-[1.5px]' : 'text-ink')} title={SIN_PLAIN[f.sin]}>{SIN_LABEL[f.sin]}</span>
      <span className={cx('flex items-center gap-1.5 text-[13.5px] font-medium sm:order-none', f.struck ? 'text-accent-2' : f.sustained ? 'text-ink' : 'text-ink-3')}>
        {f.struck ? <IconClose size={13} /> : f.sustained ? <IconCheck size={13} /> : <span aria-hidden="true" className="inline-block w-[13px] text-center">&ndash;</span>}
        {state}
      </span>
      <span className="col-span-2 sm:col-span-1">
        {f.struck ? (
          <span className="inline-flex flex-wrap items-center gap-1.5 text-[13px] text-ink-3">{f.exhibits.length ? <>cites{f.exhibits.map((id) => <ExhibitChip key={id} id={id} known={have.has(id)} onJump={onJump} />)}<span>, none of them damaging</span></> : <span>cites no damaging exhibit</span>}</span>
        ) : (
          <Cites ids={f.exhibits} have={have} onJump={onJump} />
        )}
      </span>
    </li>
  )
}

function VerdictItem({ v, t, have, onJump }: { v: Verdict; t: number; have: Set<string>; onJump: (id: string) => void }) {
  const tone = v.ruling === 'reject' ? 'border-accent text-accent-2' : v.ruling === 'paper' ? 'border-ink-3 text-ink-2 border-dashed' : 'border-ink text-ink'
  const Icon = v.ruling === 'reject' ? IconClose : v.ruling === 'paper' ? IconDoc : IconCheck
  return (
    <section id="ruling" aria-label="Ruling" className="panel p-5 md:p-6">
      <Head role="judge" t={t} extra="rules" />
      <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
        <div className={cx('stamp inline-flex items-center gap-3 rounded-[6px] border-[3px] px-5 py-2.5', tone)} role="img" aria-label={`Ruling: ${RULING_LABEL[v.ruling]}`}>
          <Icon size={26} strokeWidth={2.2} />
          <span className="serif text-[36px] font-bold leading-none">{RULING_LABEL[v.ruling]}</span>
        </div>
        <div>
          <div className="text-[14px] text-ink-3">{RULING_PLAIN[v.ruling]}</div>
          <div className="num text-[22px] font-semibold text-ink">{money(v.capital_allowed)} <span className="text-[14px] font-normal text-ink-3">allowed</span></div>
        </div>
      </div>
      {v.unsupported && (
        <p className="mt-4 rounded-[6px] border border-accent/35 bg-accent-wash px-3.5 py-2.5 text-[13.5px] text-accent-2">The judge wanted to stop this strategy, but no charge passed the exhibit rule. So the ruling was changed to deploy and marked unsupported.</p>
      )}
      <p className="mt-4 max-w-[68ch] text-[15.5px] leading-relaxed text-ink text-pretty">{v.opinion}</p>
      <h4 className="mt-5 text-[13px] font-semibold text-ink-2">Findings</h4>
      <ul className="mt-1 divide-y divide-line border-y border-line">
        {v.findings.map((f, i) => <FindingRow key={i} f={f} have={have} onJump={onJump} />)}
      </ul>
    </section>
  )
}

function NoteItem({ text, t }: { text: string; t: number }) {
  return (
    <div className="rounded-[6px] border border-dashed border-accent/50 bg-accent-wash/60 px-4 py-3">
      <Head role="rule" t={t} />
      <p className="text-[14.5px] leading-snug text-ink">{text}</p>
    </div>
  )
}

export function TruthBlock({ truth, ruling, claimed, stats }: { truth: Truth; ruling: Verdict['ruling']; claimed: number; stats?: string }) {
  const stopped = ruling !== 'deploy'
  const right = truth.guilty ? stopped : !stopped
  const msg = truth.guilty
    ? stopped ? 'The court stopped a strategy with no real edge.' : 'The court deployed a strategy with no real edge. This is a miss.'
    : !stopped ? 'The court deployed a strategy with a real edge.' : 'The court stopped a strategy with a real edge. This is a false alarm.'
  return (
    <section id="truth" aria-label="The truth" className="panel p-5 md:p-6">
      <h3 className="serif text-[24px] font-semibold text-ink">The truth</h3>
      <p className="mt-1 max-w-[64ch] text-[14.5px] leading-relaxed text-ink-2">What the strategy really earns on the sealed period, which no agent or court has seen. {truth.how}</p>
      <div className="mt-5 grid gap-x-10 gap-y-6 md:grid-cols-[minmax(0,260px)_minmax(0,1fr)]">
        <div className="space-y-4">
          <div>
            <div className="label">Claimed Sharpe</div>
            <div className="num text-[30px] font-semibold leading-none text-ink-3 line-through decoration-[1.5px]">{sh(claimed)}</div>
          </div>
          <div>
            <div className="label">True Sharpe, sealed data</div>
            <div className={cx('num text-[44px] font-semibold leading-none', truth.sharpe < 0.3 ? 'text-accent-2' : 'text-ink')}>{sh(truth.sharpe)}</div>
            <div className="mt-1.5 text-[12.5px] text-ink-3">Three fresh worlds: {truth.per_seed.map(sh).join(', ')}</div>
          </div>
          <div className="text-[13.5px] text-ink-2">
            <span className="font-medium text-ink">Planted flaws: </span>
            {truth.sins.length ? truth.sins.map((s) => SIN_LABEL[s]).join(', ') : 'none. This is the innocent twin.'}
          </div>
        </div>
        <div>
          <EquityChart series={[{ label: 'Sealed period', y: truth.equity }]} yLabel="Cumulative P&L, % of capital" xLabel="Sealed period, 3 years" height={190} label={`True result on sealed data, Sharpe ${sh(truth.sharpe)}`} />
        </div>
      </div>
      <p className={cx('mt-5 flex items-center gap-2 border-t border-line pt-4 text-[15.5px] font-medium', right ? 'text-ink' : 'text-accent-2')}>
        {right ? <IconCheck size={16} /> : <IconClose size={16} />} {msg}
      </p>
      {stats && <p className="mt-1 text-[12.5px] text-ink-3">{stats}</p>}
    </section>
  )
}

function CaseOpened({ c, t }: { c: CaseFile; t: number }) {
  const s = c.log_summary
  return (
    <div>
      <Head role="clerk" t={t} extra="opens the case" />
      <p className="text-[15px] leading-relaxed text-ink">
        <span className="font-semibold">Case {caseNo(c.case_id)} is held.</span> The agent asks for {money(c.requested_capital)} and claims a Sharpe of {sh(c.claim.sharpe)}.
        {s.n_trials != null && <> The gateway log shows {s.n_trials} backtest{s.n_trials === 1 ? '' : 's'}{s.is_best ? ', and the submitted one is the best of them' : ''}.</>} No order moves until the court rules.
      </p>
    </div>
  )
}

export function Feed({ events, shown, flash, truth, claimed, onJump, stats, live }: {
  events: TrialEvent[]; shown: number; flash: string | null; truth: Truth | null; claimed: number; onJump: (id: string) => void; stats?: string; live?: boolean
}) {
  const visible = events.slice(0, shown)
  const have = new Set(visible.filter((e) => e.kind === 'exhibit').map((e) => String((e.data as unknown as Exhibit).id)))
  const t0 = events[0]?.t ?? 0
  const verdict = visible.find((e) => e.kind === 'verdict')
  const lastRef = useRef<HTMLLIElement | null>(null)

  // keep the newest step on screen while a trial plays
  useEffect(() => {
    const el = lastRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    if (r.bottom > window.innerHeight - 24) {
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      window.scrollBy({ top: Math.min(r.bottom - window.innerHeight + 96, r.top - 90), behavior: reduce ? 'auto' : 'smooth' })
    }
  }, [shown])

  const rows: { key: string; node: ReactNode }[] = []
  visible.forEach((e, i) => {
    const t = e.t - t0
    const d = e.data as Record<string, unknown>
    let node: ReactNode = null
    switch (e.kind) {
      case 'case': node = <CaseOpened c={d as unknown as CaseFile} t={t} />; break
      case 'tool_call': {
        const args = Object.entries((d.args as Record<string, unknown>) ?? {}).map(([k, v]) => `${k}=${v}`).join(', ')
        node = (
          <p className="flex flex-wrap items-baseline gap-x-2 text-[13.5px] text-ink-3">
            <span className={cx('font-semibold', ROLE_COLOR[e.role])}>{ROLE_LABEL[e.role]}</span> runs <span className="mono text-[12.5px] text-ink-2">{String(d.tool)}({args})</span>
            <span className="mono ml-auto text-[11.5px] text-ink-4">{t.toFixed(1)} s</span>
          </p>
        )
        break
      }
      case 'exhibit': node = <ExhibitCard ex={d as unknown as Exhibit} flash={flash === (d as unknown as Exhibit).id} />; break
      case 'charge': node = <ChargeItem c={d as unknown as Charge} t={t} have={have} onJump={onJump} />; break
      case 'rebuttal': node = <RebuttalItem r={d as unknown as Rebuttal} t={t} have={have} onJump={onJump} />; break
      case 'verdict': node = <VerdictItem v={d as unknown as Verdict} t={t} have={have} onJump={onJump} />; break
      case 'note': node = <NoteItem text={String(d.text ?? '')} t={t} />; break
      case 'error': node = <NoteItem text={String(d.text ?? 'An error occurred.')} t={t} />; break
    }
    if (node) rows.push({ key: `e${i}`, node })
  })

  const ruling = verdict ? (verdict.data as unknown as Verdict).ruling : null
  const truthShown = shown > events.length
  if (truthShown && truth && ruling) rows.push({ key: 'truth', node: <TruthBlock truth={truth} ruling={ruling} claimed={claimed} stats={stats} /> })

  return (
    <ol className="space-y-5" aria-label="The trial, in order" aria-live={live ? 'polite' : 'off'}>
      {rows.map((r, i) => (
        <li key={r.key} ref={i === rows.length - 1 ? lastRef : undefined} className="rise">{r.node}</li>
      ))}
    </ol>
  )
}

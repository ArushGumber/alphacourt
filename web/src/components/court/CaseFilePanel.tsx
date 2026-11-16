import type { BacktestResult, CaseFile, ResearchLog } from '../../types'
import { caseNo, money, pct, sh, specFacts } from '../../lib/labels'
import { EquityChart } from '../charts'
import { cx } from '../ui'

function Block({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="border-t border-line pt-4 first:border-0 first:pt-0">
      <div className="mb-2.5 flex items-baseline justify-between gap-3">
        <h3 className="serif text-[18px] font-semibold text-ink">{title}</h3>
        {aside && <span className="text-[12.5px] text-ink-3">{aside}</span>}
      </div>
      {children}
    </section>
  )
}

function Fig({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className="num mt-0.5 text-[22px] font-semibold leading-none text-ink">{value}</div>
    </div>
  )
}

export function CaseFilePanel({ file, log, tear }: { file: CaseFile | null; log?: ResearchLog; tear?: BacktestResult }) {
  if (!file) return <p className="text-[14px] text-ink-3">The case file appears when the clerk opens the case.</p>
  const s = file.spec
  const m = tear?.metrics
  const claim = file.claim
  const best = log ? Math.max(...log.trials.map((t) => t.metrics.sharpe)) : 0
  return (
    <div className="space-y-5">
      <Block title="Submission" aside={`Case ${caseNo(file.case_id)}`}>
        <p className="text-[15px] font-medium leading-snug text-ink">{s.name}</p>
        <p className="mt-1 text-[13px] text-ink-3">Asks for {money(file.requested_capital)}. Researched in data room {file.world_id}.</p>
        {claim.text && <p className="mt-3 text-[14px] leading-relaxed text-ink-2 text-pretty">&ldquo;{claim.text}&rdquo;</p>}
        <div className="mono mt-3 overflow-x-auto rounded-[6px] bg-[#f8f6f2] px-3 py-2.5 text-[12.5px] leading-snug text-ink" tabIndex={0} aria-label="Signal formula">
          {s.signal}
        </div>
        <dl className="mt-3 grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13.5px]">
          {specFacts(s).map((f) => (
            <div key={f.k} className="contents">
              <dt className="text-ink-3">{f.k}</dt>
              <dd className="text-ink">{f.v}</dd>
            </div>
          ))}
        </dl>
        {s.notes && <p className="mt-3 text-[13px] leading-relaxed text-ink-3 text-pretty"><span className="text-ink-2">Notes in the submission:</span> {s.notes}</p>}
      </Block>

      <Block title="Claimed tear sheet" aside="research period">
        <div className="grid grid-cols-3 gap-3">
          <Fig label="Sharpe" value={sh(claim.sharpe)} />
          <Fig label="Return a year" value={claim.ann_return != null ? pct(claim.ann_return) : m ? pct(m.ann_return) : '–'} />
          <Fig label="Max drawdown" value={claim.max_drawdown != null ? pct(claim.max_drawdown, 1) : m ? pct(m.max_drawdown, 1) : '–'} />
        </div>
        {tear ? (
          <div className="mt-3">
            <EquityChart series={[{ label: 'Claimed', y: tear.equity }]} yLabel="Cumulative P&L, % of capital" xLabel="Research period, 9 years" height={160} label={`Claimed equity curve, Sharpe ${sh(claim.sharpe)}`} />
          </div>
        ) : (
          <p className="mt-3 text-[13px] text-ink-3">No tear sheet in this record.</p>
        )}
        <p className="mt-2 text-[12.5px] leading-relaxed text-ink-3">The agent&rsquo;s own backtest, as submitted. The court does not take it on trust.</p>
      </Block>

      <Block title="Research log" aside={log ? `${log.trials.length} backtests, ${log.pages_read.length} page${log.pages_read.length === 1 ? '' : 's'} read` : undefined}>
        {log ? (
          <>
            <div className="max-h-[248px] overflow-y-auto rounded-[6px] border border-line" tabIndex={0} aria-label="Research log, one row per backtest">
              <table className="w-full border-collapse text-[12.5px]">
                <thead className="sticky top-0 bg-bg-1 text-ink-3">
                  <tr className="border-b border-line text-left font-medium">
                    <th className="px-2.5 py-1.5 font-medium">#</th>
                    <th className="py-1.5 font-medium">Variant</th>
                    <th className="px-2.5 py-1.5 text-right font-medium">Sharpe</th>
                  </tr>
                </thead>
                <tbody>
                  {log.trials.map((t, i) => {
                    const sub = t.spec_hash === log.submitted_spec_hash
                    return (
                      <tr key={i} className={cx('border-b border-line/70 last:border-0', sub && 'bg-accent-wash')}>
                        <td className="num px-2.5 py-1 text-ink-3">{i + 1}</td>
                        <td className="py-1 pr-2">
                          <div className="flex items-center gap-2">
                            <span className="mono truncate text-[11.5px] text-ink-2">{Object.entries(t.spec.params).map(([k, v]) => `${k.replace('window', 'w').replace('vol_', 'v')} ${v}`).join('  ')}</span>
                            {sub && <span className="shrink-0 rounded-[3px] border border-accent/50 px-1 text-[11px] font-medium leading-[16px] text-accent-2">submitted</span>}
                          </div>
                        </td>
                        <td className="px-2.5 py-1 text-right">
                          <span className="inline-flex items-center justify-end gap-2">
                            <span className="hidden h-[5px] w-16 overflow-hidden rounded-[2px] bg-bg-3 sm:inline-block" aria-hidden="true">
                              <span className={cx('block h-full', sub ? 'bg-accent' : 'bg-faint')} style={{ width: `${Math.max(2, (Math.max(0, t.metrics.sharpe) / (best || 1)) * 100)}%` }} />
                            </span>
                            <span className="num w-9 text-right text-ink">{sh(t.metrics.sharpe)}</span>
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {log.pages_read.length > 0 && (
              <p className="mt-2 text-[12.5px] leading-relaxed text-ink-3">Read through the gateway: {log.pages_read.map((p, i) => <span key={p} className="mono text-[11.5px] text-ink-2">{i ? ', ' : ''}{p}</span>)}</p>
            )}
          </>
        ) : (
          <p className="text-[13.5px] leading-relaxed text-ink-3">
            {file.log_summary.n_trials != null
              ? `${file.log_summary.n_trials} backtests in the log${file.log_summary.is_best ? '; the submitted one is the best of them' : ''}.`
              : 'The log is not part of this record.'}
          </p>
        )}
      </Block>
    </div>
  )
}

import { getResults } from '../data/api'
import { useAsync } from '../data/hooks'
import { Page } from '../components/Layout'
import { Caption, Loading, PageHeader, SectionTitle } from '../components/ui'
import type { ChartData, ChartGroup, ExperimentResult } from '../types'

const PLAN: ExperimentResult[] = [
  { id: 'E1', title: 'What the exhibit rule buys', question: 'The same docket under five systems: no gate, one AI reviewer, debate without tools, an automatic test battery, and the court. Guilty strategies stopped and innocent twins deployed, per system, sin and level.' },
  { id: 'E2', title: 'A small court and a strong agent', question: 'Court roles on small open models, the defence argued by the strongest model available. Does the ruling hold?' },
  { id: 'E3', title: 'Attacks on the court', question: 'Notes addressed to the judge, a court staffed by copies of the model that wrote the strategy, and a defence that floods the record with irrelevant exhibits.' },
  { id: 'E4', title: 'Reward hacking in live research', question: 'Research agents under a neutral brief and a pressure brief: trials run, how inflated the submitted Sharpe is against the truth, which flaws appear, and what the court ruled.' },
  { id: 'E5', title: 'Cost and speed', question: 'Model calls, tokens and seconds per trial for each staffing, and the gateway’s throughput.' },
]

function Bars({ e }: { e: ExperimentResult }) {
  const rows = e.rows ?? []
  return (
    <ul className="space-y-2.5" aria-label={e.title}>
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(0,150px)_minmax(0,1fr)_64px] items-center gap-3 text-[13.5px] sm:grid-cols-[200px_minmax(0,1fr)_72px]">
          <span className="truncate text-ink-2" title={r.label}>{r.label}</span>
          <span className="relative h-[10px] rounded-[2px] bg-bg-3" aria-hidden="true">
            <span className="absolute inset-y-0 left-0 rounded-[2px] bg-accent" style={{ width: `${Math.max(0, Math.min(1, r.value)) * 100}%` }} />
            {r.lo != null && r.hi != null && <span className="absolute top-1/2 h-px -translate-y-1/2 bg-ink" style={{ left: `${r.lo * 100}%`, width: `${(r.hi - r.lo) * 100}%` }} />}
          </span>
          <span className="num text-right text-ink">{(r.value * 100).toFixed(0)}%{r.n && <span className="ml-1 text-[11.5px] text-ink-3">{r.n}</span>}</span>
        </li>
      ))}
    </ul>
  )
}

const pct = (v: number | null) => (v == null ? 0 : Math.max(0, Math.min(1, v)) * 100)

function BarRow({ g, kind }: { g: ChartGroup; kind: 'rigged' | 'honest' }) {
  const r = g[kind]
  const fill = kind === 'rigged' ? 'bg-accent' : 'bg-cool'
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_64px] items-center gap-2">
      <span className="relative h-[12px] rounded-[2px] bg-bg-3" aria-hidden="true">
        {r.value != null && r.value > 0 && <span className={`absolute inset-y-0 left-0 rounded-[2px] ${fill}`} style={{ width: `${pct(r.value)}%` }} />}
        {r.lo != null && r.hi != null && (
          <>
            <span className="absolute top-1/2 h-px -translate-y-1/2 bg-ink" style={{ left: `${pct(r.lo)}%`, width: `${pct(r.hi) - pct(r.lo)}%` }} />
            <span className="absolute top-[2px] h-[8px] w-px bg-ink" style={{ left: `${pct(r.lo)}%` }} />
            <span className="absolute top-[2px] h-[8px] w-px bg-ink" style={{ left: `calc(${pct(r.hi)}% - 1px)` }} />
          </>
        )}
      </span>
      <span className="num text-[13px] text-ink">{r.j}/{r.k}</span>
    </div>
  )
}

function Legend() {
  return (
    <div className="mb-5 flex flex-wrap gap-x-6 gap-y-1.5 text-[13px] text-ink-2">
      <span className="inline-flex items-center gap-2"><span className="h-[10px] w-[10px] rounded-[2px] bg-accent" aria-hidden="true" />Rigged strategies stopped (higher is better)</span>
      <span className="inline-flex items-center gap-2"><span className="h-[10px] w-[10px] rounded-[2px] bg-cool" aria-hidden="true" />Honest strategies let through (higher is better)</span>
    </div>
  )
}

function Groups({ groups, label }: { groups: ChartGroup[]; label: string }) {
  return (
    <ul className="space-y-4" aria-label={label}>
      {groups.map((g) => (
        <li key={g.id} className="grid gap-x-4 gap-y-1.5 sm:grid-cols-[220px_minmax(0,1fr)]">
          <span className="text-[13.5px] font-medium leading-snug text-ink">{g.label}</span>
          <div className="space-y-1.5">
            <BarRow g={g} kind="rigged" />
            <BarRow g={g} kind="honest" />
          </div>
        </li>
      ))}
    </ul>
  )
}

function GroupedBars({ chart, title }: { chart: ChartData; title: string }) {
  const s = chart.subset
  return (
    <div>
      <Legend />
      <Groups groups={chart.groups} label={title} />
      <div className="mt-2 grid gap-x-4 sm:grid-cols-[220px_minmax(0,1fr)]" aria-hidden="true">
        <span />
        <div className="grid grid-cols-[minmax(0,1fr)_64px] gap-2 text-[11.5px] text-ink-3"><span className="flex justify-between"><span>0%</span><span>50%</span><span>100%</span></span><span /></div>
      </div>
      {s && (
        <div className="mt-8 border-t border-line pt-5">
          <h3 className="mb-4 text-[14px] font-semibold text-ink">{s.title.charAt(0).toUpperCase() + s.title.slice(1)}</h3>
          <Groups groups={s.groups} label={s.title} />
        </div>
      )}
    </div>
  )
}

export default function Results() {
  const r = useAsync(() => getResults(), [])
  const have = new Map((r.data?.experiments ?? []).map((e) => [String(e.id).toUpperCase(), e]))
  return (
    <Page>
      <PageHeader title="Results">
        <p>Every experiment is fixed before the test split runs, run once, and reported whether it flatters the court or not. Where a result is not in yet, the box says so.</p>
      </PageHeader>
      {r.loading && <Loading />}
      <div className="space-y-12">
        {PLAN.map((p) => {
          const e = have.get(p.id)
          return (
            <section key={p.id} aria-labelledby={`h-${p.id}`}>
              <SectionTitle title={<><span className="mr-2 text-ink-3">{p.id}</span>{p.title}</>} id={`h-${p.id}`}>
                <p>{e?.question ?? p.question}</p>
              </SectionTitle>
              {e?.chart ? (
                <div className="panel max-w-[820px] p-5">
                  <GroupedBars chart={e.chart} title={e.title} />
                  <Caption className="mt-5">
                    On {e.chart.n_cases} held-out cases: {e.chart.groups[0]?.rigged.k} rigged strategies and {e.chart.groups[0]?.honest.k} honest ones. Thin lines are 95% intervals; labels are cases out of cases.
                    {e.exhibit_note ? ` ${e.exhibit_note}` : ''}
                  </Caption>
                </div>
              ) : e?.rows?.length ? (
                <div className="panel max-w-[820px] p-5">
                  <Bars e={e} />
                  {e.note && <Caption className="mt-4">{e.note}</Caption>}
                </div>
              ) : (
                <div className="max-w-[820px] rounded-[8px] border border-dashed border-line-3 px-5 py-8 text-[14.5px] text-ink-3">
                  Not measured yet. This chart fills in from <span className="mono text-[12.5px]">results.json</span> after the test split is run.
                </div>
              )}
            </section>
          )
        })}
      </div>
    </Page>
  )
}

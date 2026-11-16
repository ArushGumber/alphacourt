// The architecture figure: the one design used on the home page (interactive), in the paper (/figure) and in the video.
// Boxes are keyboard-focusable; hovering, focusing or tapping one shows its inputs and outputs under the figure.
// Three facts are marked 1 to 3: the log feeds the court, the sealed data is reachable only by the court's lab,
// and a finding needs an exhibit.
import { useState } from 'react'
import { cx } from './ui'

const FONT = "'Inter Variable', Inter, system-ui, sans-serif"
const INK = '#1f1e1b'
const INK2 = '#4a4740'
const LINE = '#c5bfb3'
const ACCENT = '#c8501d'
const ACCENT2 = '#a8411a'
const WASH = '#fbefe8'
const LEAF = '#f3f0ea'

interface Detail {
  title: string
  text: string
  inputs?: string
  outputs?: string
}
interface Node {
  id: string
  x: number
  y: number
  w: number
  h: number
  title: string
  lines?: string[]
  container?: boolean
  detail: Detail
}

const NODES: Node[] = [
  { id: 'web', x: 16, y: 40, w: 174, h: 92, title: 'The Web', lines: ['papers, forums,', 'code, data feeds'],
    detail: { title: 'The Web', text: 'Where the agent looks for ideas. In the demo it is an invented alpha web: blog posts, forum threads and paper abstracts. Some carry a note addressed to the reviewers.', outputs: 'page text, through read_page' } },
  { id: 'agent', x: 16, y: 190, w: 174, h: 112, title: 'Research agent', lines: ['Claude Code, Codex,', 'Gemini CLI or an', 'open model'],
    detail: { title: 'Research agent', text: 'Any model that speaks MCP. It researches through the gateway, tries variants, and asks for capital with submit_strategy. It is rewarded for backtest performance, which is the pressure the court exists to check.', inputs: 'a brief, results from the gateway', outputs: 'strategy specs, a claim, a capital request' } },
  { id: 'gateway', x: 290, y: 40, w: 226, h: 300, title: 'Gateway (MCP)', container: true,
    detail: { title: 'Gateway', text: 'Sits between the agent and deployment. Every tool the agent uses goes through it, so the agent cannot skip the trial or hide what it tried.', inputs: 'MCP tool calls', outputs: 'tool results, a held case' } },
  { id: 'proxy', x: 304, y: 76, w: 198, h: 62, title: 'Tool proxy', lines: ['research tools pass through'],
    detail: { title: 'Tool proxy', text: 'list_fields, field_info, read_page and run_backtest pass through. Backtests run on the research period only, and the engine uses the spec exactly as written.', inputs: 'tool calls, pages from the Web', outputs: 'fields, pages, backtest results' } },
  { id: 'log', x: 304, y: 158, w: 198, h: 62, title: 'Research log', lines: ['every backtest recorded'],
    detail: { title: 'Research log', text: 'Every run_backtest call is recorded with its spec hash, time and result. The court counts tries from this log, not from what the agent says it tried.', inputs: 'every backtest the agent runs', outputs: 'number of trials, parameter grid, best-of count' } },
  { id: 'hold', x: 304, y: 240, w: 198, h: 62, title: 'Hold', lines: ['submit_strategy is held'],
    detail: { title: 'Hold', text: 'submit_strategy returns the status held and a case id. The strategy waits for a ruling. Nothing reaches the broker before then.', inputs: 'spec, claim, requested capital', outputs: 'case id, status held' } },
  { id: 'court', x: 606, y: 40, w: 230, h: 300, title: 'The court', container: true,
    detail: { title: 'The court', text: 'Three AI roles read the same case file. They argue with tools, not opinions: every claim has to point at an exhibit that a test actually produced.', inputs: 'case file and research log', outputs: 'a ruling: deploy, paper only, or reject' } },
  { id: 'prosecutor', x: 620, y: 76, w: 202, h: 62, title: 'Prosecutor', lines: ['files charges, cites exhibits'],
    detail: { title: 'Prosecutor', text: 'Runs up to six forensic tests of its choice on the strategy and files charges. Each charge cites the exhibits that back it.', inputs: 'case file, log', outputs: 'tool calls, charges' } },
  { id: 'defence', x: 620, y: 158, w: 202, h: 62, title: 'Defence', lines: ['answers, may concede'],
    detail: { title: 'Defence', text: 'May run up to four tests of its own, then answers each charge. It can concede a charge when the exhibit is clear.', inputs: 'charges and exhibits', outputs: 'tool calls, rebuttals, concessions' } },
  { id: 'judge', x: 620, y: 240, w: 202, h: 62, title: 'Judge', lines: ['deploy, paper only or reject'],
    detail: { title: 'Judge', text: 'Reads the charges, the rebuttals and the exhibits as the clerk renders them, and rules. Paper trading only means the strategy trades simulated money with no capital at risk.', inputs: 'charges, rebuttals, exhibits', outputs: 'findings, ruling, capital allowed, an opinion' } },
  { id: 'lab', x: 610, y: 400, w: 226, h: 110, title: 'Forensic lab', lines: ['lag, point-in-time, costs,', 'survivorship, sealed holdout,', 'regime, trial count, placebo,', 'stability, concentration, notes'],
    detail: { title: 'Forensic lab', text: 'Deterministic tests that re-run the strategy’s own spec. The same inputs always give the same exhibit, and no model is involved in producing the numbers.', inputs: 'tool calls from the prosecutor and defence', outputs: 'exhibits: numbers, a one-line summary, a chart' } },
  { id: 'dataroom', x: 200, y: 400, w: 336, h: 122, title: 'Data room', container: true,
    detail: { title: 'Data room', text: 'Simulated markets with a known truth. The last quarter of the bars is sealed.', inputs: 'none', outputs: 'bars, to whoever is allowed to read them' } },
  { id: 'research', x: 212, y: 430, w: 152, h: 76, title: 'Research period', lines: ['the agent can use', 'these bars'],
    detail: { title: 'Research period', text: 'The first three quarters of the bars. The agent’s backtests run here, and so do most of the court’s tests.', outputs: 'bars for backtests' } },
  { id: 'sealed', x: 380, y: 430, w: 144, h: 80, title: 'Sealed period', lines: ['last quarter of bars,', 'never shown to', 'the agent'],
    detail: { title: 'Sealed period', text: 'The last quarter of the bars. No research tool can return them, so the agent cannot tune against them. Only the forensic lab’s holdout test and the truth scorer read them.', inputs: 'reads from the forensic lab only', outputs: 'the holdout exhibit, and the truth shown after the ruling' } },
  { id: 'bailiff', x: 934, y: 150, w: 154, h: 190, title: 'Bailiff', container: true,
    detail: { title: 'Bailiff', text: 'Enforces the ruling in code. The hold on a case is released only by a ruling, and the record of the trial is written before any order moves.', inputs: 'the ruling', outputs: 'a release or a refusal, an audit record' } },
  { id: 'audit', x: 946, y: 188, w: 130, h: 62, title: 'Audit record', lines: ['one JSON file', 'per case'],
    detail: { title: 'Audit record', text: 'The submission, the log summary, every exhibit, charge and rebuttal, the ruling, model ids, timings and hashes. What a compliance officer would file.', outputs: 'results/gateway/audit/{case_id}.json' } },
  { id: 'enforce', x: 946, y: 264, w: 130, h: 62, title: 'Enforce', lines: ['the ruling gates', 'the order'],
    detail: { title: 'Enforce', text: 'Deploy releases the requested capital. Paper only releases simulated trading. Reject keeps the hold.', inputs: 'ruling, capital allowed', outputs: 'release or refusal' } },
  { id: 'broker', x: 934, y: 400, w: 154, h: 110, title: 'Simulated broker', lines: ['receives an order', 'only after a ruling', 'of deploy or paper'],
    detail: { title: 'Simulated broker', text: 'A simulated venue. All markets in this project are simulated and no real order is ever placed.', inputs: 'orders released by the bailiff', outputs: 'simulated fills' } },
]

interface Arrow {
  id: string
  d: string
  label?: { x: number; y: number; lines: string[]; anchor?: 'middle' | 'start' | 'end' }
  dashed?: boolean
}
const ARROWS: Arrow[] = [
  { id: 'a-web', d: 'M190 101 L304 101', label: { x: 240, y: 92, lines: ['read_page'] } },
  { id: 'a-call', d: 'M190 232 L290 232', label: { x: 240, y: 224, lines: ['MCP tool calls'] } },
  { id: 'a-back', d: 'M290 270 L190 270', label: { x: 240, y: 286, lines: ['results,', 'case id'] } },
  { id: 'a-case', d: 'M502 189 L606 189', label: { x: 561, y: 160, lines: ['case file +', 'research log'] } },
  { id: 'a-rule', d: 'M822 295 L839 295 M931 295 L946 295', label: { x: 885, y: 263, lines: ['ruling'] } },
  { id: 'a-release', d: 'M1011 150 L1011 -6 L403 -6 L403 38', label: { x: 707, y: -13, lines: ['the ruling releases or keeps the hold'] } },
  { id: 'a-broker', d: 'M1011 340 L1011 398', label: { x: 1003, y: 362, lines: ['orders, only after', 'the ruling'], anchor: 'end' } },
  { id: 'a-tools', d: 'M660 340 L660 398', label: { x: 668, y: 374, lines: ['tool calls'], anchor: 'start' } },
  { id: 'a-ex', d: 'M780 398 L780 340', label: { x: 788, y: 374, lines: ['exhibits'], anchor: 'start' } },
  { id: 'a-room', d: 'M330 340 L330 428', label: { x: 338, y: 372, lines: ['research bars only'], anchor: 'start' } },
  { id: 'a-sealed', d: 'M610 468 L526 468', label: { x: 568, y: 456, lines: ['sealed bars'] } },
]

const FACTS = [
  { n: 1, title: 'The log is the court’s evidence', text: 'Every backtest runs through the gateway, so the court knows how many variants were tried without trusting the agent.', nodes: ['log', 'court'], arrows: ['a-case'], marker: { x: 561, y: 210 } },
  { n: 2, title: 'The sealed data is reachable only by the court', text: 'The agent never sees the last quarter of the bars. Only the lab’s holdout test and the truth scorer read them, so the agent cannot tune against it.', nodes: ['sealed', 'lab'], arrows: ['a-sealed'], marker: { x: 524, y: 430 } },
  { n: 3, title: 'A finding needs an exhibit', text: 'Code, not the judge’s goodwill, strikes any finding that cites no exhibit from a test that was actually run.', nodes: ['rule'], arrows: ['a-rule'], marker: { x: 931, y: 274 } },
]

const RULE_DETAIL: Detail = {
  title: 'The exhibit rule',
  text: 'Code checks the ruling before it counts. A sustained finding that cites no exhibit that exists in the record is struck. A reject or paper ruling left with no surviving finding becomes deploy and is flagged unsupported.',
  inputs: 'the judge’s findings and the record of exhibits',
  outputs: 'findings kept or struck, and the final ruling',
}

function Marker({ n, x, y, on }: { n: number; x: number; y: number; on: boolean }) {
  return (
    <g aria-hidden="true">
      <circle cx={x} cy={y} r={11} fill={on ? ACCENT : '#fff'} stroke={ACCENT} strokeWidth={1.6} />
      <text x={x} y={y + 5} textAnchor="middle" fontFamily={FONT} fontSize={14} fontWeight={700} fill={on ? '#fff' : ACCENT2}>{n}</text>
    </g>
  )
}

export function Architecture({ interactive = true, className }: { interactive?: boolean; className?: string }) {
  const [active, setActive] = useState<string | null>(null)
  const [fact, setFact] = useState<number | null>(null)

  const f = FACTS.find((x) => x.n === fact)
  const marked = new Set<string>([...(f?.nodes ?? []), ...(active ? [active] : [])])
  const markedArrows = new Set(f?.arrows ?? [])
  const detail = active === 'rule' ? RULE_DETAIL : NODES.find((n) => n.id === active)?.detail
  const show = (id: string | null) => interactive && setActive(id)

  const svg = (
    <svg id="architecture-svg" viewBox="0 0 1100 566" width="100%" role="group" aria-labelledby="arch-title arch-desc" className="block h-auto w-full" style={{ minWidth: interactive ? 860 : undefined }}>
      <title id="arch-title">AlphaCourt architecture</title>
      <desc id="arch-desc">
        A research agent reaches the Web and the simulated markets only through the gateway. The gateway records every backtest in a research log and holds
        any strategy that asks for capital. The log goes to the court, where a prosecutor, a defence and a judge argue using exhibits from the forensic lab.
        The lab can read the sealed period of the data room; the agent cannot. An exhibit rule strikes any finding without an exhibit. The bailiff enforces
        the ruling, writes the audit record and only then releases an order to the simulated broker.
      </desc>
      <defs>
        <marker id="ac-arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M1 1.5 8.5 5 1 8.5z" fill={INK2} />
        </marker>
        <marker id="ac-arrow-hot" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M1 1.5 8.5 5 1 8.5z" fill={ACCENT} />
        </marker>
      </defs>
      <g transform="translate(0 34)" fontFamily={FONT}>
        {NODES.filter((n) => n.container).map((n) => <NodeBox key={n.id} n={n} on={marked.has(n.id)} sealed={false} interactive={interactive} onShow={show} />)}
        {ARROWS.map((a) => {
          const hot = markedArrows.has(a.id)
          return (
            <g key={a.id} aria-hidden="true">
              <path d={a.d} fill="none" stroke={hot ? ACCENT : INK2} strokeWidth={hot ? 2.2 : 1.5} markerEnd={`url(#${hot ? 'ac-arrow-hot' : 'ac-arrow'})`} strokeLinejoin="round" />
              {a.label && (
                <text x={a.label.x} y={a.label.y} textAnchor={a.label.anchor ?? 'middle'} fontSize={13.5} fill={hot ? ACCENT2 : INK2} stroke="#ffffff" strokeWidth={4} paintOrder="stroke">
                  {a.label.lines.map((l, i) => <tspan key={i} x={a.label!.x} dy={i === 0 ? 0 : 16}>{l}</tspan>)}
                </text>
              )}
            </g>
          )
        })}
        {NODES.filter((n) => !n.container).map((n) => <NodeBox key={n.id} n={n} on={marked.has(n.id)} sealed={n.id === 'sealed'} interactive={interactive} onShow={show} />)}

        {/* The exhibit rule, drawn on the way from the judge to the bailiff */}
        <g
          tabIndex={interactive ? 0 : undefined}
          role={interactive ? 'button' : undefined}
          aria-label={interactive ? 'The exhibit rule: findings without an exhibit are struck' : undefined}
          onMouseEnter={() => show('rule')} onMouseLeave={() => show(null)} onFocus={() => show('rule')} onBlur={() => show(null)} onClick={() => show('rule')}
          style={{ cursor: interactive ? 'pointer' : undefined, outline: 'none' }}
          className="figure-node"
        >
          <rect x={839} y={274} width={92} height={42} rx={8} fill={WASH} stroke={ACCENT} strokeWidth={marked.has('rule') ? 2.6 : 1.6} />
          <text x={885} y={292} textAnchor="middle" fontSize={14} fontWeight={650} fill={ACCENT2}>Exhibit</text>
          <text x={885} y={308} textAnchor="middle" fontSize={14} fontWeight={650} fill={ACCENT2}>rule</text>
        </g>
        {FACTS.map((x) => <Marker key={x.n} n={x.n} x={x.marker.x} y={x.marker.y} on={fact === x.n} />)}
      </g>
    </svg>
  )

  if (!interactive) return <div className={className}>{svg}</div>

  return (
    <div className={className}>
      <div className="overflow-x-auto rounded-[8px] border border-line bg-bg-1 p-3 md:p-5" tabIndex={0} role="region" aria-label="Architecture figure, scrolls sideways on small screens">
        {svg}
      </div>
      <p className="mt-2 text-[12.5px] text-ink-3 md:hidden">Scroll the figure sideways. Tap a box for its inputs and outputs.</p>
      <div className="mt-4 grid gap-x-8 gap-y-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]" aria-live="polite">
        <div className="min-h-[7.5rem]">
          {detail ? (
            <div key={active}>
              <h3 className="serif text-[18px] font-semibold text-ink">{detail.title}</h3>
              <p className="mt-1.5 text-[14.5px] leading-relaxed text-ink-2 text-pretty">{detail.text}</p>
              <dl className="mt-2 space-y-1 text-[13.5px] text-ink-3">
                {detail.inputs && <div className="flex gap-2"><dt className="w-14 shrink-0 font-medium text-ink-2">In</dt><dd>{detail.inputs}</dd></div>}
                {detail.outputs && <div className="flex gap-2"><dt className="w-14 shrink-0 font-medium text-ink-2">Out</dt><dd>{detail.outputs}</dd></div>}
              </dl>
            </div>
          ) : (
            <div>
              <h3 className="serif text-[18px] font-semibold text-ink">Hover or tap a box</h3>
              <p className="mt-1.5 text-[14.5px] leading-relaxed text-ink-2 text-pretty">
                Each box shows what goes into it and what comes out. The arrows are labelled with what flows along them.
                The three numbered marks are the three facts that make the gateway and the court one system.
              </p>
            </div>
          )}
        </div>
        <ol className="space-y-3">
          {FACTS.map((x) => (
            <li key={x.n}
              onMouseEnter={() => setFact(x.n)} onMouseLeave={() => setFact(null)}
              onFocus={() => setFact(x.n)} onBlur={() => setFact(null)}
              tabIndex={0}
              className={cx('flex gap-3 rounded-[6px] px-2 py-1.5 -mx-2 outline-none transition-colors focus-visible:outline-2 focus-visible:outline-accent', fact === x.n && 'bg-accent-wash')}>
              <span className="mt-0.5 inline-flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border border-accent text-[13px] font-semibold text-accent-2" aria-hidden="true">{x.n}</span>
              <span>
                <span className="block text-[14.5px] font-semibold text-ink">{x.title}</span>
                <span className="block text-[14px] leading-relaxed text-ink-2 text-pretty">{x.text}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}

function NodeBox({ n, on, sealed, interactive, onShow }: { n: Node; on: boolean; sealed: boolean; interactive: boolean; onShow: (id: string | null) => void }) {
  const stroke = on ? ACCENT : sealed ? ACCENT : n.container ? LINE : 'none'
  const sw = on ? 2.4 : sealed ? 1.6 : 1.4
  return (
    <g
      tabIndex={interactive ? 0 : undefined}
      role={interactive ? 'button' : undefined}
      aria-label={interactive ? `${n.title}. ${n.detail.text}` : undefined}
      onMouseEnter={() => onShow(n.id)} onMouseLeave={() => onShow(null)} onFocus={() => onShow(n.id)} onBlur={() => onShow(null)} onClick={() => onShow(n.id)}
      style={{ cursor: interactive ? 'pointer' : undefined, outline: 'none' }}
      className="figure-node"
    >
      <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={n.container ? 10 : 7}
        fill={n.container ? '#ffffff' : sealed ? WASH : LEAF} stroke={stroke} strokeWidth={sw} strokeDasharray={sealed ? '5 3' : undefined} />
      {n.container ? (
        <text x={n.x + 14} y={n.y + 23} fontSize={14.5} fontWeight={650} fill={INK}>{n.title}</text>
      ) : (
        <>
          <text x={n.x + 11} y={n.y + 21} fontSize={14.5} fontWeight={650} fill={INK}>{n.title}</text>
          <text fontSize={13} fill={INK2}>
            {n.lines?.map((l, i) => <tspan key={i} x={n.x + 11} y={n.y + 40 + i * 16}>{l}</tspan>)}
          </text>
        </>
      )}
      {sealed && (
        <g transform={`translate(${n.x + n.w - 24} ${n.y + 8})`} aria-hidden="true" fill="none" stroke={ACCENT2} strokeWidth={1.6} strokeLinecap="round">
          <rect x={1} y={7} width={11} height={8} rx={1.5} fill={ACCENT2} stroke="none" />
          <path d="M3.5 7V5a3 3 0 0 1 6 0v2" />
        </g>
      )}
    </g>
  )
}

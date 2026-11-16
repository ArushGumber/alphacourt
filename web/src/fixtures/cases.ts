// Sample data for the two hero cases. Hand-set numbers, shaped exactly like court/types.py.
// Replaced by data/cases/*.json from the real pipeline; see src/data/api.ts.
import type {
  BacktestResult, CaseBundle, CaseFile, Charge, Exhibit, Metrics, Rebuttal, ResearchLog, StrategySpec, Trial, TrialEvent, TrialRecord, Verdict,
} from '../types'
import { equityPath, hash12, histogram, rng, round, stepSharpe } from '../lib/synth'

const T0 = 1763290000
const N = 400
const K = 2250 / N
const IDX = Array.from({ length: N + 1 }, (_, i) => Math.round(i * K))

const metrics = (sharpe: number, over: Partial<Metrics> = {}): Metrics => ({
  sharpe, ann_return: round(sharpe * 0.0715, 3), ann_vol: 0.0715, max_drawdown: 0.058, turnover: 0.62, hit_rate: 0.55, n_days: 2250, ...over,
})

const spec = (o: Partial<StrategySpec> & { name: string; signal: string }): StrategySpec => ({
  universe: 'default', lag: 1, rebalance: 1, portfolio: { type: 'long_short_quantile', quantile: 0.2, gross: 1 },
  costs_bps: 0, sample: { start: 0, end: null }, params: {}, notes: '', ...o,
})

// ------------------------------------------------------------------------------------------
// Case 41: the guilty reversal strategy

const guiltySpec = spec({
  name: 'Reversal 3d vol-scaled',
  signal: 'rank(-delta(close, 3) / ts_std(ret, 20))',
  lag: 0,
  costs_bps: 0,
  params: { window: 3, vol_window: 20, quantile: 0.2 },
  notes: 'Short-term reversal, scaled by recent volatility. Chosen from a small grid on the research period.',
})

function guiltyLog(): ResearchLog {
  const r = rng(41)
  const windows = [2, 3, 4, 5, 8]
  const vols = [10, 20, 60]
  const quants = [0.1, 0.2, 0.3]
  const trials: Trial[] = []
  for (let i = 0; i < 37; i++) {
    const w = windows[Math.floor(r.next() * windows.length)]
    const v = vols[Math.floor(r.next() * vols.length)]
    const q = quants[Math.floor(r.next() * quants.length)]
    const best = i === 30
    const s = best ? guiltySpec : spec({
      name: `Reversal ${w}d`, signal: `rank(-delta(close, ${w}) / ts_std(ret, ${v}))`, lag: 0, params: { window: w, vol_window: v, quantile: q },
      portfolio: { type: 'long_short_quantile', quantile: q, gross: 1 },
    })
    const sh = best ? 2.94 : round(Math.min(2.6, Math.max(0.1, 1.15 + 0.62 * r.normal() + (w <= 3 ? 0.35 : -0.1))), 2)
    trials.push({ t: T0 + i * 41, spec_hash: best ? hash12(JSON.stringify(guiltySpec)) : hash12(`${w}-${v}-${q}-${i}`), spec: s, metrics: metrics(sh) })
  }
  return {
    session_id: 'sess-a41', agent: 'claude-code (sample)', trials,
    pages_read: ['alphaweb.example/blog/short-term-reversal-works-everywhere'],
    submitted_spec_hash: trials[30].spec_hash,
  }
}

const gLog = guiltyLog()
const gSharpes = gLog.trials.map((t) => t.metrics.sharpe)

const guiltyCase: CaseFile = {
  case_id: 'case-0041',
  world_id: 'w1-a',
  spec: guiltySpec,
  claim: {
    sharpe: 2.94, ann_return: 0.21, max_drawdown: 0.058,
    text: 'Vol-scaled three-day reversal. Sharpe 2.9 on the research period, drawdown under 6%. Requesting one million for live trading.',
  },
  requested_capital: 1_000_000,
  log_summary: {
    n_trials: 37, n_distinct_specs: 37, best_of: 37, is_best: true,
    grid: { window: [2, 3, 4, 5, 8], vol_window: [10, 20, 60], quantile: [0.1, 0.2, 0.3] },
  },
  pages_read: gLog.pages_read,
}

const sampleSharpe = (annual: number, seed: number) => equityPath(seed, N, stepSharpe(annual, K))
const gClaimed = sampleSharpe(2.94, 11)
const gLagged = sampleSharpe(0.08, 12)

const gEx: Exhibit[] = [
  {
    id: 'EX-1', test: 'lag_test', params: { k: 1 },
    numbers: { k: 1, sharpe_before: 2.94, sharpe_after: 0.08, ann_return_after: 0.006 },
    summary: 'Trading one bar later instead of on the bar that made the signal cuts the Sharpe ratio from 2.94 to 0.08.',
    hint: 'damaging',
    chart: { type: 'equity', series: [{ label: 'As claimed (lag 0)', y: gClaimed }, { label: 'One bar later', y: gLagged }], x_label: 'Research period', y_label: 'Cumulative P&L, % of capital' },
    called_by: 'prosecution',
  },
  {
    id: 'EX-2', test: 'trial_haircut', params: {},
    numbers: { n_trials: 37, best_sharpe: 2.94, expected_max_noise: 1.08, haircut_sharpe: 1.86 },
    summary: 'This is the best of 37 tries; pure noise would reach a Sharpe of about 1.08 by luck, so at most 1.86 of the 2.94 can be real.',
    hint: 'damaging',
    chart: { type: 'bars', labels: [...gSharpes].sort((a, b) => b - a).map((_, i) => String(i + 1)), values: [...gSharpes].sort((a, b) => b - a), highlight: 0, ref: { value: 1.08, label: 'Best of 37 by luck alone' }, x_label: 'Tries, best first', y_label: 'Sharpe' },
    called_by: 'prosecution',
  },
  {
    id: 'EX-3', test: 'cost_test', params: { bps: 8 },
    numbers: { cost_bps: 8, sharpe_net: -0.93, break_even_bps: 6.1, turnover: 0.62 },
    summary: 'With a realistic 8 basis points per trade the Sharpe ratio is -0.93; the strategy stops paying at 6.1 basis points.',
    hint: 'damaging',
    chart: { type: 'line', series: [{ label: 'Sharpe after costs', x: [0, 2, 4, 6, 8, 10, 12], y: [2.94, 1.97, 1.0, 0.03, -0.93, -1.9, -2.87] }], ref: { value: 0, label: 'No profit' }, marker: { value: 8, label: 'Realistic cost' }, x_label: 'Cost per trade (basis points)', y_label: 'Sharpe' },
    called_by: 'prosecution',
  },
  {
    id: 'EX-4', test: 'regime_split', params: {},
    numbers: { calm: 3.41, stressed: 1.86 },
    summary: 'The claimed Sharpe is positive in both calm (3.41) and stressed (1.86) periods, so no single regime carries it.',
    hint: 'neutral',
    chart: { type: 'bars', labels: ['Calm', 'Stressed'], values: [3.41, 1.86], y_label: 'Claimed Sharpe' },
    called_by: 'prosecution',
  },
  {
    id: 'EX-5', test: 'placebo_test', params: { n: 200 },
    numbers: { n: 200, real_sharpe: 2.94, shuffled_p95: 0.41, rank_pct: 100 },
    summary: 'The claimed signal beats all 200 shuffled versions (the best shuffle reaches 0.41), so the numbers are not chance; this says nothing about timing or costs.',
    hint: 'supportive',
    chart: { type: 'dist', counts: histogram(5, 200, 0, 0.17, 16, -0.6, 3.2), lo: -0.6, hi: 3.2, marker: { value: 2.94, label: 'This strategy' }, x_label: 'Sharpe of shuffled signals', y_label: 'Count' },
    called_by: 'defence',
  },
]

const gCharges: Charge[] = [
  { sin: 'lookahead', exhibits: ['EX-1'], argument: 'The spec sets lag to 0, so each trade uses the closing price that created the signal. One bar of delay removes the whole edge.' },
  { sin: 'selection', exhibits: ['EX-2'], argument: 'The gateway log shows 37 backtests and the submitted spec is the best of them. The tear sheet reports the winner without the other 36.' },
  { sin: 'costs', exhibits: ['EX-3'], argument: 'The spec charges zero costs on a strategy that turns over 62% of its book daily. It breaks even at 6.1 basis points.' },
  { sin: 'lucky_period', exhibits: ['EX-4'], argument: 'The result may rest on calm markets.' },
  { sin: 'knife_edge', exhibits: ['EX-7'], argument: 'Neighbouring windows perform far worse, so the chosen parameters are fragile.' },
]

const gRebuttals: Rebuttal[] = [
  { sin: 'lookahead', concede: true, exhibits: ['EX-1'], argument: 'Conceded. The lag of 0 is in the spec and EX-1 shows what it does.' },
  { sin: 'selection', concede: false, exhibits: ['EX-5'], argument: 'The 37 runs explore one idea on a small grid, and the signal beats every shuffled placebo (EX-5). This is exploration, not fishing.' },
  { sin: 'costs', concede: true, exhibits: ['EX-3'], argument: 'Conceded. Zero costs is not defensible for this turnover.' },
  { sin: 'lucky_period', concede: false, exhibits: ['EX-4'], argument: 'EX-4 shows positive Sharpe in both regimes. The charge has no support.' },
  { sin: 'knife_edge', concede: false, exhibits: [], argument: 'The prosecution ran no parameter test. The charge cites an exhibit that does not exist.' },
]

const gVerdict: Verdict = {
  ruling: 'reject',
  findings: [
    { sin: 'lookahead', sustained: true, exhibits: ['EX-1'], struck: false },
    { sin: 'costs', sustained: true, exhibits: ['EX-3'], struck: false },
    { sin: 'selection', sustained: true, exhibits: ['EX-2'], struck: false },
    { sin: 'lucky_period', sustained: false, exhibits: ['EX-4'], struck: false },
    { sin: 'knife_edge', sustained: true, exhibits: ['EX-7'], struck: true },
  ],
  capital_allowed: 0,
  opinion: 'The edge exists only because the strategy trades on the bar that produced its signal (EX-1). It also pays no costs (EX-3) and is the best of 37 tries (EX-2). The placebo result is not in dispute and does not cure any of this. The finding on knife-edge parameters cites no exhibit and is struck. Rejected.',
  unsupported: false,
}

const ev = (t: number, role: TrialEvent['role'], kind: TrialEvent['kind'], data: Record<string, unknown>): TrialEvent => ({ t: T0 + 3000 + t, role, kind, data })

const gEvents: TrialEvent[] = [
  ev(0, 'clerk', 'case', guiltyCase as unknown as Record<string, unknown>),
  ev(2.1, 'prosecution', 'tool_call', { tool: 'lag_test', args: { k: 1 }, exhibit_id: 'EX-1' }),
  ev(2.4, 'prosecution', 'exhibit', gEx[0] as unknown as Record<string, unknown>),
  ev(5.0, 'prosecution', 'tool_call', { tool: 'trial_haircut', args: {}, exhibit_id: 'EX-2' }),
  ev(5.2, 'prosecution', 'exhibit', gEx[1] as unknown as Record<string, unknown>),
  ev(7.9, 'prosecution', 'tool_call', { tool: 'cost_test', args: { bps: 8 }, exhibit_id: 'EX-3' }),
  ev(8.1, 'prosecution', 'exhibit', gEx[2] as unknown as Record<string, unknown>),
  ev(10.6, 'prosecution', 'tool_call', { tool: 'regime_split', args: {}, exhibit_id: 'EX-4' }),
  ev(10.8, 'prosecution', 'exhibit', gEx[3] as unknown as Record<string, unknown>),
  ...gCharges.map((c, i) => ev(14 + i * 1.2, 'prosecution', 'charge', c as unknown as Record<string, unknown>)),
  ev(22, 'defence', 'tool_call', { tool: 'placebo_test', args: { n: 200 }, exhibit_id: 'EX-5' }),
  ev(23.4, 'defence', 'exhibit', gEx[4] as unknown as Record<string, unknown>),
  ...gRebuttals.map((c, i) => ev(26 + i * 1.5, 'defence', 'rebuttal', c as unknown as Record<string, unknown>)),
  ev(36, 'judge', 'verdict', gVerdict as unknown as Record<string, unknown>),
  ev(36.1, 'rule', 'note', { text: 'Exhibit rule: the finding on knife_edge cites EX-7, and no exhibit EX-7 exists in this record. The finding is struck.' }),
]

const gRecord: TrialRecord = {
  case: guiltyCase, system: 'court',
  staffing: { prosecution: 'local:qwen3-8b', defence: 'local:gemma3-12b', judge: 'local:qwen3-8b' },
  exhibits: gEx, charges: gCharges, rebuttals: gRebuttals, verdict: gVerdict, events: gEvents,
  calls: 9, tokens_in: 21840, tokens_out: 3120, seconds: 36.1,
}

const gTear: BacktestResult = {
  spec_hash: gLog.submitted_spec_hash!, mode: 'naive', period: 'research',
  metrics: metrics(2.94, { ann_return: 0.21, max_drawdown: 0.058 }),
  equity: gClaimed, equity_index: IDX,
  yearly_sharpe: { 'year 1': 3.2, 'year 2': 2.8, 'year 3': 3.1, 'year 4': 2.6, 'year 5': 3.0, 'year 6': 2.9, 'year 7': 3.0, 'year 8': 2.9, 'year 9': 2.8 },
  regime_sharpe: { calm: 3.41, stressed: 1.86 }, notes: ['spec trades on the bar that produced the signal (lag 0)', 'costs_bps is 0'],
}

export const guiltyBundle: CaseBundle = {
  record: gRecord, log: gLog, tearsheet: gTear, twin_of: null,
  truth: {
    sharpe: -0.41, per_seed: [-0.52, -0.33, -0.38], guilty: true, sins: ['lookahead', 'costs', 'selection'],
    how: 'Strict data, one bar of lag, the full universe and 8 basis points of cost, on the sealed bars, averaged over three fresh worlds with the same parameters.',
    equity: equityPath(14, 150, stepSharpe(-0.41, 750 / 150)),
  },
}

// ------------------------------------------------------------------------------------------
// Case 42: the innocent twin with the same headline numbers

const innocentSpec = spec({
  name: 'Earnings drift, 63d surprise',
  signal: 'rank(delta(eps_reported, 63) / ts_std(eps_reported, 252))',
  universe: 'all',
  lag: 1,
  rebalance: 5,
  costs_bps: 8,
  params: { delta_window: 63, std_window: 252, quantile: 0.2 },
  notes: 'Post-earnings drift on the reported surprise. Point-in-time field, one bar of lag, costs included.',
})

const innocentLog: ResearchLog = (() => {
  const r = rng(42)
  const sh = [2.31, 2.62, 2.91]
  const trials: Trial[] = sh.map((s, i) => {
    const sp = i === 2 ? innocentSpec : spec({
      name: `Earnings drift, ${[21, 42][i]}d surprise`, signal: `rank(delta(eps_reported, ${[21, 42][i]}) / ts_std(eps_reported, 252))`, universe: 'all', rebalance: 5, costs_bps: 8,
      params: { delta_window: [21, 42][i], std_window: 252, quantile: 0.2 },
    })
    return { t: T0 + 90000 + i * 55, spec_hash: hash12(JSON.stringify(sp) + r.next()), spec: sp, metrics: metrics(s, { turnover: 0.07, hit_rate: 0.56, max_drawdown: 0.049 }) }
  })
  return { session_id: 'sess-a42', agent: 'claude-code (sample)', trials, pages_read: ['alphaweb.example/papers/post-earnings-drift-revisited'], submitted_spec_hash: trials[2].spec_hash }
})()

const innocentCase: CaseFile = {
  case_id: 'case-0042', world_id: 'w1-b', spec: innocentSpec,
  claim: { sharpe: 2.91, ann_return: 0.19, max_drawdown: 0.049, text: 'Post-earnings drift on the reported surprise. Sharpe 2.9 after costs on the research period. Requesting one million for live trading.' },
  requested_capital: 1_000_000,
  log_summary: { n_trials: 3, n_distinct_specs: 3, best_of: 3, is_best: true, grid: { delta_window: [21, 42, 63] } },
  pages_read: innocentLog.pages_read,
}

const iClaimed = sampleSharpe(2.91, 21)
const iLagged = sampleSharpe(2.74, 22)
const iSeries = sampleSharpe(2.83, 23)

const iEx: Exhibit[] = [
  {
    id: 'EX-1', test: 'lag_test', params: { k: 1 }, numbers: { k: 1, sharpe_before: 2.91, sharpe_after: 2.74 },
    summary: 'Trading one bar later barely changes the Sharpe ratio: 2.91 becomes 2.74.', hint: 'supportive',
    chart: { type: 'equity', series: [{ label: 'As claimed (lag 1)', y: iClaimed }, { label: 'One more bar later', y: iLagged }], x_label: 'Research period', y_label: 'Cumulative P&L, % of capital' }, called_by: 'prosecution',
  },
  {
    id: 'EX-2', test: 'trial_haircut', params: {}, numbers: { n_trials: 3, best_sharpe: 2.91, expected_max_noise: 0.43, haircut_sharpe: 2.48 },
    summary: 'This is the best of 3 tries; luck alone would reach about 0.43, which leaves 2.48 of the 2.91.', hint: 'supportive',
    chart: { type: 'bars', labels: ['1', '2', '3'], values: [2.91, 2.62, 2.31], highlight: 0, ref: { value: 0.43, label: 'Best of 3 by luck alone' }, x_label: 'Tries, best first', y_label: 'Sharpe' }, called_by: 'prosecution',
  },
  {
    id: 'EX-3', test: 'pit_replay', params: {}, numbers: { sharpe_naive: 2.91, sharpe_strict: 2.83 },
    summary: 'Re-running on strictly point-in-time data moves the Sharpe ratio from 2.91 to 2.83; the fields used were available when the trades were made.', hint: 'supportive',
    chart: { type: 'equity', series: [{ label: 'Submitted data', y: iClaimed }, { label: 'Point-in-time data', y: iSeries }], x_label: 'Research period', y_label: 'Cumulative P&L, % of capital' }, called_by: 'prosecution',
  },
  {
    id: 'EX-4', test: 'holdout_test', params: {}, numbers: { sharpe_research: 2.91, sharpe_sealed: 2.35 },
    summary: 'On the sealed bars the strategy as submitted earns a Sharpe ratio of 2.35, against 2.91 in research.', hint: 'supportive',
    chart: { type: 'bars', labels: ['Research', 'Sealed'], values: [2.91, 2.35], y_label: 'Sharpe' }, called_by: 'defence',
  },
]

const iCharges: Charge[] = [
  { sin: 'selection', exhibits: ['EX-2'], argument: 'Three variants were tried and the best was submitted.' },
  { sin: 'leaky_field', exhibits: ['EX-3'], argument: 'Earnings fields are a common source of leaks, so the data was replayed point in time.' },
]
const iRebuttals: Rebuttal[] = [
  { sin: 'selection', concede: false, exhibits: ['EX-2', 'EX-4'], argument: 'Three tries leave a haircut of 0.43, and the sealed holdout still earns 2.35.' },
  { sin: 'leaky_field', concede: false, exhibits: ['EX-3'], argument: 'The prosecution\'s own replay shows 2.91 against 2.83. The field is point in time.' },
]
const iVerdict: Verdict = {
  ruling: 'deploy',
  findings: [
    { sin: 'selection', sustained: false, exhibits: ['EX-2', 'EX-4'], struck: false },
    { sin: 'leaky_field', sustained: false, exhibits: ['EX-3'], struck: false },
  ],
  capital_allowed: 1_000_000,
  opinion: 'Neither charge survives its own exhibit. The trial count costs 0.43 Sharpe (EX-2), the point-in-time replay costs 0.08 (EX-3), and the lag test costs 0.17 (EX-1). The sealed holdout earns 2.35 (EX-4). Deploy the requested capital.',
  unsupported: false,
}
const iEvents: TrialEvent[] = [
  ev(0, 'clerk', 'case', innocentCase as unknown as Record<string, unknown>),
  ev(2.0, 'prosecution', 'tool_call', { tool: 'lag_test', args: { k: 1 }, exhibit_id: 'EX-1' }),
  ev(2.2, 'prosecution', 'exhibit', iEx[0] as unknown as Record<string, unknown>),
  ev(4.8, 'prosecution', 'tool_call', { tool: 'trial_haircut', args: {}, exhibit_id: 'EX-2' }),
  ev(5.0, 'prosecution', 'exhibit', iEx[1] as unknown as Record<string, unknown>),
  ev(7.6, 'prosecution', 'tool_call', { tool: 'pit_replay', args: {}, exhibit_id: 'EX-3' }),
  ev(7.8, 'prosecution', 'exhibit', iEx[2] as unknown as Record<string, unknown>),
  ...iCharges.map((c, i) => ev(11 + i * 1.2, 'prosecution', 'charge', c as unknown as Record<string, unknown>)),
  ev(16, 'defence', 'tool_call', { tool: 'holdout_test', args: {}, exhibit_id: 'EX-4' }),
  ev(17.3, 'defence', 'exhibit', iEx[3] as unknown as Record<string, unknown>),
  ...iRebuttals.map((c, i) => ev(20 + i * 1.5, 'defence', 'rebuttal', c as unknown as Record<string, unknown>)),
  ev(26, 'judge', 'verdict', iVerdict as unknown as Record<string, unknown>),
]
const iRecord: TrialRecord = {
  case: innocentCase, system: 'court', staffing: gRecord.staffing, exhibits: iEx, charges: iCharges, rebuttals: iRebuttals, verdict: iVerdict, events: iEvents,
  calls: 8, tokens_in: 17420, tokens_out: 2480, seconds: 26.0,
}
export const innocentBundle: CaseBundle = {
  record: iRecord, log: innocentLog, twin_of: 'case-0041',
  tearsheet: {
    spec_hash: innocentLog.submitted_spec_hash!, mode: 'naive', period: 'research', metrics: metrics(2.91, { ann_return: 0.19, max_drawdown: 0.049, turnover: 0.07, hit_rate: 0.56 }),
    equity: iClaimed, equity_index: IDX,
    yearly_sharpe: { 'year 1': 2.5, 'year 2': 3.1, 'year 3': 2.8, 'year 4': 3.0, 'year 5': 2.7, 'year 6': 3.2, 'year 7': 2.9, 'year 8': 2.8, 'year 9': 3.0 },
    regime_sharpe: { calm: 3.1, stressed: 2.4 }, notes: [],
  },
  truth: {
    sharpe: 2.21, per_seed: [2.35, 2.04, 2.23], guilty: false, sins: [],
    how: 'Strict data, one bar of lag, the full universe and 8 basis points of cost, on the sealed bars, averaged over three fresh worlds with the same parameters.',
    equity: equityPath(24, 150, stepSharpe(2.21, 750 / 150)),
  },
}

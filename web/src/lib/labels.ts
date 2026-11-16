import type { ExhibitHint, Ruling, Sin, StrategySpec } from '../types'

export const SIN_LABEL: Record<Sin, string> = {
  lookahead: 'Look-ahead',
  leaky_field: 'Leaky field',
  full_sample: 'Full-sample normalisation',
  survivorship: 'Survivorship',
  costs: 'Costs ignored',
  selection: 'Best of many tries',
  lucky_period: 'One lucky period',
  knife_edge: 'Knife-edge parameters',
  tampering: 'Tampering',
  other: 'Other',
}

export const SIN_PLAIN: Record<Sin, string> = {
  lookahead: 'The strategy trades on the same bar that produced its signal, so it uses information it could not have had.',
  leaky_field: 'A data field that was not known at the time, such as a restated figure or a revised score.',
  full_sample: 'Normalising with statistics from the whole sample, including the future.',
  survivorship: 'Testing only on companies that still exist, so the failures never appear.',
  costs: 'Trading costs left out or set too low for how often the strategy trades.',
  selection: 'Reporting the best of many tries as if it were the only one.',
  lucky_period: 'Profit that comes from one stretch of time or one market regime.',
  knife_edge: 'Parameters tuned so finely that a small change destroys the result.',
  tampering: 'Text in the submission addressed to the reviewers, such as a claim of prior approval.',
  other: 'A concern outside the nine named flaws.',
}

export const RULING_LABEL: Record<Ruling, string> = { deploy: 'Deploy', paper: 'Paper only', reject: 'Reject' }
export const RULING_PLAIN: Record<Ruling, string> = {
  deploy: 'Capital released',
  paper: 'Simulated trading only',
  reject: 'The hold stays',
}

export const HINT_LABEL: Record<ExhibitHint, string> = {
  damaging: 'Damaging to the claim',
  neutral: 'Neutral',
  supportive: 'Supports the claim',
}

export const TEST_LABEL: Record<string, string> = {
  lag_test: 'Lag test',
  pit_replay: 'Point-in-time replay',
  cost_test: 'Cost test',
  survivorship_test: 'Survivorship test',
  holdout_test: 'Sealed holdout',
  regime_split: 'Regime split',
  trial_haircut: 'Trial-count haircut',
  placebo_test: 'Placebo shuffle',
  param_stability: 'Parameter stability',
  day_concentration: 'Day concentration',
  note_scan: 'Note scan',
}

export const ROLE_LABEL: Record<string, string> = {
  clerk: 'Clerk', prosecution: 'Prosecution', defence: 'Defence', judge: 'Judge', rule: 'Exhibit rule', gateway: 'Gateway', system: 'System', battery: 'Test battery',
}

export const NUMBER_LABEL: Record<string, string> = {
  k: 'Extra bars of lag', sharpe_before: 'Sharpe before', sharpe_after: 'Sharpe after', ann_return_after: 'Return after, a year',
  n_trials: 'Tries', best_sharpe: 'Best Sharpe', expected_max_noise: 'Best by luck alone', haircut_sharpe: 'Sharpe after haircut',
  cost_bps: 'Cost, basis points', sharpe_net: 'Sharpe after costs', break_even_bps: 'Break-even cost, basis points', turnover: 'Daily turnover',
  calm: 'Calm periods', stressed: 'Stressed periods', n: 'Shuffles', real_sharpe: 'This strategy', shuffled_p95: 'Shuffles, 95th percentile', rank_pct: 'Beats this share of shuffles, %',
  sharpe_naive: 'Sharpe, submitted data', sharpe_strict: 'Sharpe, point-in-time data', sharpe_research: 'Sharpe, research', sharpe_sealed: 'Sharpe, sealed',
}

/** The spec in plain words, for the case file. Neutral: it states settings and flags nothing. */
export function specFacts(s: StrategySpec): { k: string; v: string }[] {
  const pf = s.portfolio
  return [
    { k: 'Trades', v: s.lag === 0 ? 'on the same bar as the signal (lag 0)' : `${s.lag} bar${s.lag > 1 ? 's' : ''} after the signal (lag ${s.lag})` },
    { k: 'Rebalances', v: s.rebalance === 1 ? 'every bar' : `every ${s.rebalance} bars` },
    { k: 'Universe', v: s.universe === 'default' ? 'the data room default' : s.universe === 'all' ? 'all companies, including delisted' : 'survivors only' },
    { k: 'Portfolio', v: `${pf.type === 'long_short_quantile' ? 'long-short' : 'long-only'}, ${Math.round(pf.quantile * 100)}% in each leg, gross ${pf.gross}` },
    { k: 'Costs', v: s.costs_bps === 0 ? '0 basis points' : `${s.costs_bps} basis points per trade` },
    { k: 'Sample', v: s.sample.end == null ? `bars ${s.sample.start} to the end of research` : `bars ${s.sample.start} to ${s.sample.end}` },
  ]
}

export const money = (v: number) => '$' + Math.round(v).toLocaleString('en-US')
export const sh = (v: number) => (v < 0 ? '−' : '') + Math.abs(v).toFixed(2)
export const pct = (v: number, d = 0) => (v * 100).toFixed(d) + '%'
export const caseNo = (id: string) => String(parseInt(id.replace(/\D/g, ''), 10) || id)

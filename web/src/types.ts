// Mirrors court/types.py. Field names and value sets are identical. Site-only types are at the bottom.

export type Universe = 'all' | 'survivors' | 'default'
export type PortfolioType = 'long_short_quantile' | 'long_only_top'

export interface Portfolio {
  type: PortfolioType
  quantile: number
  gross: number
}

export interface Sample {
  start: number
  end: number | null
}

export interface StrategySpec {
  name: string
  universe: Universe
  signal: string
  lag: number
  rebalance: number
  portfolio: Portfolio
  costs_bps: number
  sample: Sample
  params: Record<string, number | string>
  notes: string
}

export interface Metrics {
  sharpe: number
  ann_return: number
  ann_vol: number
  max_drawdown: number
  turnover: number
  hit_rate: number
  n_days: number
}

export interface BacktestResult {
  spec_hash: string
  mode: 'naive' | 'strict'
  period: 'research' | 'sealed' | 'full'
  metrics: Metrics
  equity: number[]
  equity_index: number[]
  yearly_sharpe: Record<string, number>
  regime_sharpe: Record<string, number>
  notes: string[]
}

export interface Trial {
  t: number
  spec_hash: string
  spec: StrategySpec
  metrics: Metrics
}

export interface ResearchLog {
  session_id: string
  agent: string
  trials: Trial[]
  pages_read: string[]
  submitted_spec_hash: string | null
}

export interface Claim {
  sharpe: number
  ann_return: number | null
  max_drawdown: number | null
  text: string
}

export interface CaseFile {
  case_id: string
  world_id: string
  spec: StrategySpec
  claim: Claim
  requested_capital: number
  log_summary: {
    n_trials?: number
    n_distinct_specs?: number
    best_of?: number
    grid?: Record<string, (number | string)[]>
    is_best?: boolean
    [k: string]: unknown
  }
  pages_read: string[]
}

export type ExhibitHint = 'damaging' | 'neutral' | 'supportive'

/** chart is free-form in Python. The site draws the shapes in ExhibitChart (components/charts.tsx). */
export interface ChartSeries {
  label: string
  y: number[]
  x?: number[]
}
export interface ExhibitChartData {
  type?: 'equity' | 'bars' | 'dist' | 'line' | string
  series?: ChartSeries[]
  // bars
  labels?: string[]
  values?: number[]
  highlight?: number
  ref?: { value: number; label: string }
  // dist: histogram counts over equal-width bins from lo to hi, and where the real strategy sits
  counts?: number[]
  lo?: number
  hi?: number
  marker?: { value: number; label: string }
  // axis text
  x_label?: string
  y_label?: string
  split?: number // equity: index where the sealed or later period starts
  [k: string]: unknown
}

export interface Exhibit {
  id: string
  test: string
  params: Record<string, unknown>
  numbers: Record<string, number | string | null>
  summary: string
  hint: ExhibitHint
  chart: ExhibitChartData
  called_by: 'prosecution' | 'defence' | 'battery' | 'clerk'
}

export const SINS = [
  'lookahead', 'leaky_field', 'full_sample', 'survivorship', 'costs', 'selection', 'lucky_period', 'knife_edge', 'tampering',
] as const
export type Sin =
  | 'lookahead' | 'leaky_field' | 'full_sample' | 'survivorship' | 'costs' | 'selection' | 'lucky_period' | 'knife_edge' | 'tampering' | 'other'

export interface Charge {
  sin: Sin
  exhibits: string[]
  argument: string
}

export interface Rebuttal {
  sin: Sin
  concede: boolean
  exhibits: string[]
  argument: string
}

export type Ruling = 'deploy' | 'paper' | 'reject'

export interface Finding {
  sin: Sin
  sustained: boolean
  exhibits: string[]
  struck: boolean
}

export interface Verdict {
  ruling: Ruling
  findings: Finding[]
  capital_allowed: number
  opinion: string
  unsupported: boolean
}

export type EventRole = 'clerk' | 'prosecution' | 'defence' | 'judge' | 'rule' | 'gateway' | 'system'
export type EventKind = 'case' | 'tool_call' | 'exhibit' | 'charge' | 'rebuttal' | 'verdict' | 'note' | 'error'

/**
 * One step of a trial. The site reads `data` like this:
 *   case      CaseFile
 *   tool_call { tool, args, exhibit_id? }
 *   exhibit   Exhibit
 *   charge    Charge
 *   rebuttal  Rebuttal
 *   verdict   Verdict
 *   note      { text }   (the exhibit rule writes one for every struck finding)
 *   error     { text }
 */
export interface TrialEvent {
  t: number
  role: EventRole
  kind: EventKind
  data: Record<string, unknown>
}

export interface TrialRecord {
  case: CaseFile
  system: string
  staffing: Record<string, string>
  exhibits: Exhibit[]
  charges: Charge[]
  rebuttals: Rebuttal[]
  verdict: Verdict
  events: TrialEvent[]
  calls: number
  tokens_in: number
  tokens_out: number
  seconds: number
}

// ---------------------------------------------------------------------------------------------
// Site-only types (not in court/types.py). These are the shapes of the files under data/.

/** The ground truth for a case: the strategy's real result on sealed data, from true_edge(). */
export interface Truth {
  sharpe: number
  per_seed: number[]
  how: string
  guilty: boolean
  /** planted sins, empty for an innocent */
  sins: Sin[]
  /** cumulative P&L on the sealed bars under strict data and realistic costs, at most 400 points */
  equity: number[]
}

/** data/cases/{case_id}.json: everything the Courtroom shows for one case. */
export interface CaseBundle {
  record: TrialRecord
  log: ResearchLog
  /** the tear sheet the agent claimed: the naive research-period backtest of the submitted spec */
  tearsheet: BacktestResult
  truth: Truth
  twin_of?: string | null
}

/** One row of data/docket.json. */
export interface DocketRow {
  case_id: string
  name: string
  family: string
  sins: Sin[]
  level: 'L1' | 'L2' | 'L3' | 'unusual'
  twin_of: string | null
  guilty: boolean
  claimed_sharpe: number
  true_sharpe: number
  ruling: Ruling
  system: string
  /** true when the ruling stops a guilty case or deploys an innocent one */
  /** the model that staffs the court that gave this ruling */
  staffing?: string | null
  correct: boolean
  has_trial: boolean
}

export interface Rate { value: number | null; lo: number | null; hi: number | null; j: number; k: number }
export interface HeadlineResult {
  id: string
  label: string
  /** plain text value, for headline numbers that are not a pair of rates */
  value?: string
  detail?: string
  /** E1 headline: the model that staffs the system */
  sub?: string
  rigged?: Rate
  honest?: Rate
}
export interface ChartGroup { id: string; label: string; n_cases: number; rigged: Rate; honest: Rate }
export interface ChartData { n_cases: number; groups: ChartGroup[]; subset?: { title: string; n_cases: number; groups: ChartGroup[] } }
export interface ExperimentResult {
  id: string
  title: string
  question: string
  /** bars: one row per system or model, value in [0,1] with optional interval */
  rows?: { label: string; value: number; lo?: number; hi?: number; n?: string }[]
  note?: string
  /** E1: grouped bars, rigged stopped and honest let through */
  chart?: ChartData
  exhibit_note?: string | null
}
/** data/results.json */
export interface ResultsFile {
  headline: HeadlineResult[]
  experiments: ExperimentResult[]
}

/** data/studio_session.json: one recorded research session that ends in a trial. */
export type StudioStep =
  | { kind: 'list_fields' | 'field_info'; text: string }
  | { kind: 'read_page'; url: string; text: string }
  | { kind: 'run_backtest'; spec: StrategySpec; metrics: Metrics }
  | { kind: 'submit'; text: string; case_id: string }
  /** the analyst's closing words, a refusal, the court's ruling: one plain line */
  | { kind: 'note'; text: string }
export interface StudioSession {
  brief: string
  model: string
  steps: StudioStep[]
  case_id: string
}

/** data/agent_session_claude.json: a recorded session of a real agent attached to the gateway (see scripts/export_agent_session.py). */
export type AgentStep =
  | { kind: 'text' | 'report'; text: string }
  | { kind: 'call'; tool: string; args: Record<string, unknown> }
  | { kind: 'result'; tool: string; summary: string; detail?: string; sharpe?: number; trial?: number }
  | { kind: 'trial'; case_id: string; ruling_status?: string; record: TrialRecord }
export interface AgentSession {
  meta: { agent: string; model: string; brief: string; case_id: string; tools: string[]; stream_file: string; cost_usd: number }
  steps: AgentStep[]
}

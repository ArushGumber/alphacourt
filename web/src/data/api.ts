// The one place the site gets data from.
//
// Static data: JSON files next to index.html under ./data/ (web/public/data/ in the repo):
//   docket.json, cases/{case_id}.json (CaseBundle), results.json, studio_session.json.
// Live mode: at startup initRuntime() reads ./live.json ({"api": "https://host"}); a non-empty `api` is the gateway
//   base for every /api call and for the MCP address on the Connect page. VITE_API_BASE overrides it in development.
//   Live is used for what only a server can do: running trials and Studio sessions, and the record of a live case.
//   The docket, recorded trials, results and the recorded Studio session always come from the static files.
// In development only, a missing file falls back to src/fixtures. A production build never contains the fixtures.

import type { AgentSession, CaseBundle, CaseFile, DocketRow, ResultsFile, StudioSession } from '../types'

const ENV_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.trim() ?? ''
const normBase = (raw: string) => (raw === '/' || raw === '.' ? '' : raw.replace(/\/+$/, '').replace(/\/api$/, ''))

export let LIVE = ENV_BASE !== ''
export let API_BASE = normBase(ENV_BASE)
export let SERVER_NAME = API_BASE || (typeof window !== 'undefined' ? window.location.origin : 'this address')
/** A stable MCP address, when live.json gives one (the static host forwards /mcp to the gateway). */
export let MCP_URL = ''

/** Reads ./live.json once, before the app renders. A missing or malformed file means static mode. */
export async function initRuntime(): Promise<void> {
  if (ENV_BASE === '') {
    try {
      const res = await fetch(`${import.meta.env.BASE_URL}live.json`, { cache: 'no-store' })
      if (res.ok) {
        const j = JSON.parse(await res.text()) as { api?: unknown; mcp?: unknown }
        if (typeof j.mcp === 'string' && j.mcp.trim()) MCP_URL = j.mcp.trim()
        if (typeof j.api === 'string' && j.api.trim()) {
          LIVE = true
          API_BASE = normBase(j.api.trim())
        }
      }
    } catch {
      /* static mode */
    }
  }
  SERVER_NAME = API_BASE || (typeof window !== 'undefined' ? window.location.origin : 'this address')
}
const STATIC_ROOT = `${import.meta.env.BASE_URL}data/`

export class DataError extends Error {
  status?: number
  constructor(message: string, status?: number) {
    super(message)
    this.status = status
  }
}

export interface Loaded<T> {
  value: T
  /** 'fixture' only in development, when the real file is missing */
  source: 'file' | 'live' | 'fixture'
}

async function fetchJson<T>(url: string): Promise<T> {
  let res: Response
  try {
    res = await fetch(url)
  } catch {
    throw new DataError(`Could not load ${url}.`)
  }
  if (!res.ok) throw new DataError(`${res.status} ${res.statusText}`, res.status)
  const text = await res.text()
  try {
    return JSON.parse(text) as T
  } catch {
    // a static host without the file often answers with index.html
    throw new DataError(`Not found: ${url}`, 404)
  }
}

const cache = new Map<string, Promise<unknown>>()
function cached<T>(url: string): Promise<T> {
  if (!cache.has(url)) {
    const p = fetchJson<T>(url)
    p.catch(() => cache.delete(url))
    cache.set(url, p)
  }
  return cache.get(url) as Promise<T>
}

async function load<T>(staticPath: string, fixture: () => Promise<T | undefined>): Promise<Loaded<T>> {
  try {
    return { value: await cached<T>(`${STATIC_ROOT}${staticPath}`), source: 'file' }
  } catch (e) {
    if (import.meta.env.DEV) {
      const f = await fixture()
      if (f !== undefined) return { value: f, source: 'fixture' }
    }
    throw e
  }
}

export const getDocket = () => load<DocketRow[]>('docket.json', async () => (await import('../fixtures')).DOCKET)

export const getCase = (id: string) =>
  load<CaseBundle>(`cases/${encodeURIComponent(id)}.json`, async () => (await import('../fixtures')).BUNDLES[id])

export const getAgentSession = () => load<AgentSession>('agent_session_claude.json', async () => undefined)

export const getStudioSession = () => load<StudioSession>('studio_session.json', async () => (await import('../fixtures')).STUDIO)

/** results.json is optional: without it the Results page shows its empty states. */
export async function getResults(): Promise<ResultsFile | null> {
  try {
    return (await load<ResultsFile>('results.json', async () => undefined)).value
  } catch {
    return null
  }
}

/** The gateway's record of a live case: its case file is what the Courtroom shows beside a live trial. */
export const getLiveCase = (id: string) => fetchJson<{ case: CaseFile; world: string }>(`${API_BASE}/api/cases/${encodeURIComponent(id)}`)

/** Cases the gateway holds (trials already run on it). Used to pick a case to replay when the static docket is missing. */
export const getLiveCases = () => fetchJson<{ cases: { case_id: string; name: string; ruling: string | null; status: string }[] }>(`${API_BASE}/api/cases`)

export interface StudioOptions {
  models: string[]
  briefs: Record<string, string>
}
/** Models, briefs and worlds the gateway offers. */
export const getStudioOptions = () => fetchJson<StudioOptions>(`${API_BASE}/api/studio/models`)

/** Is the gateway answering? Always false in a static build. */
export async function serverUp(): Promise<boolean> {
  if (!LIVE) return false
  try {
    const r = await fetch(`${API_BASE}/api/health`)
    return r.ok
  } catch {
    return false
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      if (j && typeof j.detail === 'string') msg = j.detail
    } catch {
      /* not JSON */
    }
    throw new DataError(msg, res.status)
  }
  return (await res.json()) as T
}

/** Start a live trial. A docket case is tried afresh; a case the gateway already holds is replayed. Returns the trial id. */
export async function startTrial(caseId: string, body: { system: string; staffing: Record<string, string> }): Promise<{ case_id: string }> {
  try {
    return await post<{ case_id: string }>('/api/trial', { ...body, docket_id: caseId })
  } catch (e) {
    if (!(e instanceof DataError) || (e.status !== 404 && e.status !== 501)) throw e
    return post<{ case_id: string }>('/api/trial', { ...body, case_id: caseId })
  }
}

/** Start a Studio session. */
export const startStudio = (body: { brief: string; model: string }) => post<{ session_id: string }>('/api/studio/start', body)

/**
 * Subscribe to the gateway's server-sent events. Every message is a named event (the trial's `case`, `exhibit`, ...;
 * the Studio's `agent` and `trial`) whose data is JSON. onEvent gets the event name and the parsed payload.
 * `end` closes the stream; a dropped connection before it is reported as an error.
 */
export function streamEvents(path: string, names: string[], onEvent: (name: string, data: Record<string, any>) => void, onEnd: (error?: string) => void): () => void {
  const es = new EventSource(`${API_BASE}${path}`)
  let done = false
  const handle = (name: string) => (m: MessageEvent) => {
    try {
      onEvent(name, JSON.parse(m.data))
    } catch {
      /* ignore a malformed message */
    }
  }
  for (const n of names) es.addEventListener(n, handle(n) as EventListener)
  es.addEventListener('end', () => {
    done = true
    es.close()
    onEnd()
  })
  es.onerror = () => {
    if (done) return
    done = true
    es.close()
    onEnd('The live stream ended before the trial finished.')
  }
  return () => {
    done = true
    es.close()
  }
}

/** The event names a trial stream carries (the kinds in TrialEvent). */
export const TRIAL_EVENTS = ['case', 'tool_call', 'exhibit', 'charge', 'rebuttal', 'verdict', 'note', 'error']

// ---- Flaw Lab ----

export interface LabBacktest {
  metrics: { sharpe: number; ann_return: number; ann_vol: number; max_drawdown: number; turnover: number; hit_rate: number; n_days: number }
  equity: number[]
  notes: string[]
}
export interface LabTruth {
  sharpe: number
  per_seed: number[]
  how: string
}
export interface LabScenario {
  key: string
  label: string
  flaws: string[]
  spec: Record<string, unknown>
  honest_spec: Record<string, unknown>
  claimed: LabBacktest
  honest: LabBacktest
  truth: LabTruth
}
export const getLab = () => load<{ world: string; scenarios: LabScenario[] }>('lab.json', async () => undefined)

const LAB_SESSION = `lab-${Math.random().toString(36).slice(2, 12)}`
async function postLab<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session': LAB_SESSION }, body: JSON.stringify(body) })
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      if (j && typeof j.detail === 'string') msg = j.detail
    } catch {
      /* not JSON */
    }
    throw new DataError(msg, res.status)
  }
  return (await res.json()) as T
}
export const labBacktest = (spec: unknown, world: string) =>
  postLab<{ result: LabBacktest & { metrics: LabBacktest['metrics'] } }>('/api/backtest', { spec, world }).then((r) => r.result)
export const labTruth = (spec: unknown, world: string) => postLab<LabTruth>('/api/truth', { spec, world })
export const labTrial = (caseFile: unknown, world: string) => postLab<{ case_id: string }>('/api/trial', { case: caseFile, world, system: 'court' })

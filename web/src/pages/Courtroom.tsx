import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getCase, getDocket, getLiveCase, getLiveCases, getStudioOptions, labTruth, LIVE, serverUp, startTrial, streamEvents, TRIAL_EVENTS, type Loaded } from '../data/api'
import { useAsync } from '../data/hooks'
import { readParams, replaceParams } from '../router'
import type { CaseBundle, CaseFile, DocketRow, TrialEvent, Truth } from '../types'
import { Page } from '../components/Layout'
import { Badge, Button, Loading, Note, Segmented, Select, cx } from '../components/ui'
import { IconPause, IconPlay, IconRestart, IconStep } from '../components/Icons'
import { usePlayback } from '../components/playback'
import { CaseFilePanel } from '../components/court/CaseFilePanel'
import { Feed } from '../components/court/Feed'
import { caseNo, sh } from '../lib/labels'

const SYSTEMS = [
  { value: 'court', label: 'Court: tools and the exhibit rule' },
  { value: 'debate', label: 'Debate: same roles, no tools' },
  { value: 'single', label: 'One reviewer reads the case' },
  { value: 'battery', label: 'Test battery: no model' },
]

const DEFAULT_MODEL = { value: '', label: 'Server default' }

/** The gateway's event for the same step, shaped as the Feed expects, or null when the Feed has nothing to show. */
function adaptLive(name: string, ev: Record<string, any>, file: CaseFile | null): TrialEvent | null {
  const d = (ev.data ?? {}) as Record<string, unknown>
  const out = (data: Record<string, unknown>): TrialEvent => ({ t: Number(ev.t), role: ev.role, kind: ev.kind ?? name, data })
  if (ev.role === 'gateway') return ev.kind === 'error' ? out({ text: String(d.error ?? 'The trial failed.') }) : null
  if (name === 'case') return file ? out(file as unknown as Record<string, unknown>) : null
  if (name === 'error') return out({ text: String(d.error ?? d.text ?? 'An error occurred.') })
  return out(d)
}

function caseFileOf(events: TrialEvent[]): CaseFile | null {
  const e = events.find((x) => x.kind === 'case')
  return e ? (e.data as unknown as CaseFile) : null
}

export default function Courtroom({ watch }: { watch?: string }) {
  const watchId = watch ?? readParams().get('watch') ?? ''
  const docket = useAsync(() => getDocket(), [])
  const staticRows: DocketRow[] = docket.data?.value ?? []
  const [caseId, setCaseId] = useState<string>(() => readParams().get('c') ?? 'AC-D014-G')
  const [mode, setMode] = useState<'recorded' | 'live'>(watchId ? 'live' : 'recorded')
  const [speed, setSpeed] = useState(1)
  const [up, setUp] = useState(false)
  const [view, setView] = useState<'trial' | 'file'>('trial')
  const [flash, setFlash] = useState<string | null>(null)
  const [system, setSystem] = useState('court')
  const [staff, setStaff] = useState({ prosecution: '', defence: '', judge: '' })
  const [models, setModels] = useState<string[]>([])

  const bundle = useAsync(() => getCase(caseId), [caseId])
  const b: CaseBundle | undefined = (bundle.data as Loaded<CaseBundle> | undefined)?.value

  useEffect(() => {
    serverUp().then((ok) => {
      setUp(ok)
      if (ok) getStudioOptions().then((o) => setModels(o.models), () => undefined)
    })
  }, [])
  // without the static docket, a live server still offers the cases it holds, to replay
  const [heldCases, setHeldCases] = useState<DocketRow[]>([])
  const rows = staticRows.length ? staticRows : heldCases
  useEffect(() => {
    if (!up) return
    getLiveCases().then((r) => setHeldCases(r.cases.map((c) => ({ case_id: c.case_id, name: c.name, has_trial: c.status === 'ruled' } as DocketRow))), () => undefined)
  }, [up])
  useEffect(() => {
    if (!staticRows.length && heldCases.length && !heldCases.some((c) => c.case_id === caseId)) setCaseId(heldCases[0].case_id)
  }, [staticRows.length, heldCases, caseId])
  useEffect(() => { replaceParams({ c: caseId }) }, [caseId])

  // live run
  const [liveEvents, setLiveEvents] = useState<TrialEvent[]>([])
  const [liveState, setLiveState] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [liveError, setLiveError] = useState('')
  const closeRef = useRef<(() => void) | null>(null)
  useEffect(() => () => closeRef.current?.(), [])
  useEffect(() => { if (watchId) return; closeRef.current?.(); setLiveEvents([]); setLiveState('idle') }, [caseId, mode, watchId])

  // follow a trial the gateway holds (its id is a case id: TR-xxxx for a trial run from here, AC-xxxx for a submission)
  const [watchTruth, setWatchTruth] = useState<Truth | null>(null)
  const attach = useCallback(async (id: string) => {
    closeRef.current?.()
    setLiveEvents([]); setLiveState('running'); setLiveError('')
    try {
      const held = await getLiveCase(id)
      const file = held.case
      if (watchId === id) {
        setWatchTruth(null)
        labTruth(file.spec, held.world).then((t) => {
          const claimed = file.claim.sharpe
          setWatchTruth({ sharpe: t.sharpe, per_seed: t.per_seed, how: '', guilty: claimed - t.sharpe >= 1.0 && t.sharpe < 0.5, sins: [], equity: [], live: true })
        }, () => setWatchTruth(null))
      }
      closeRef.current = streamEvents(`/api/cases/${encodeURIComponent(id)}/events`, TRIAL_EVENTS,
        (name, ev) => { const e = adaptLive(name, ev, file); if (e) setLiveEvents((l) => [...l, e]) },
        (err) => { setLiveState(err ? 'error' : 'done'); if (err) setLiveError(err) })
    } catch (e) {
      setLiveState('error'); setLiveError((e as Error).message)
    }
  }, [watchId])

  const runLive = useCallback(async () => {
    setLiveEvents([]); setLiveState('running'); setLiveError('')
    try {
      const chosen = Object.fromEntries(Object.entries(staff).filter(([, v]) => v))
      const { case_id } = await startTrial(caseId, { system, staffing: chosen })
      await attach(case_id)
    } catch (e) {
      setLiveState('error'); setLiveError((e as Error).message)
    }
  }, [caseId, system, staff, attach])
  useEffect(() => { if (watchId && LIVE) void attach(watchId) }, [watchId, attach])

  const recorded = b?.record.events ?? []
  const live = mode === 'live'
  const events = live ? liveEvents : recorded
  const pb = usePlayback(recorded, `${caseId}`, { speed, autoplay: true })
  // ?end=1 shows the whole trial, ?at=N stops at step N (for links and screenshots)
  const startAt = useRef<string | null>(readParams().get('end') ? 'end' : readParams().get('at'))
  useEffect(() => {
    if (!b || !startAt.current) return
    pb.seek(startAt.current === 'end' ? pb.total : Number(startAt.current))
    startAt.current = null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [b])
  const shown = live ? liveEvents.length + (liveState === 'done' ? 1 : 0) : pb.shown

  const jump = useCallback((id: string) => {
    const el = document.getElementById(`ex-${id}`)
    if (!el) return
    setView('trial')
    window.setTimeout(() => {
      el.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' })
      setFlash(id)
      window.setTimeout(() => setFlash(null), 1800)
    }, 30)
  }, [])

  const file = useMemo(() => caseFileOf(events) ?? (live ? null : b?.record.case ?? null), [events, live, b])
  const twin = useMemo(() => b?.twin_of ?? rows.find((r) => r.twin_of === caseId)?.case_id ?? null, [b, rows, caseId])
  const options = rows.map((r) => ({
    value: r.case_id,
    label: `Case ${caseNo(r.case_id)}: ${r.name}${r.has_trial ? '' : ' (no recording yet)'}`,
    disabled: !live && !r.has_trial && r.case_id !== caseId,
  }))
  const verdictEvent = events.find((e) => e.kind === 'verdict')
  const stats = b && !live ? `${b.record.calls} model calls, ${b.record.tokens_in.toLocaleString('en-US')} tokens in, ${b.record.seconds.toFixed(0)} seconds. Court staffed by ${[...new Set(Object.values(b.record.staffing))].join(' and ')}.` : undefined
  const truthOk = !live || liveState === 'done'
  const liveReady = LIVE && up
  const staffOptions = [DEFAULT_MODEL, ...models.map((m) => ({ value: m, label: m }))]

  return (
    <Page wide>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-x-8 gap-y-3 md:mb-8">
        <div className="max-w-[720px]">
          <h1 tabIndex={-1} data-page-title className="serif text-[34px] font-semibold leading-[1.1] text-ink outline-none md:text-[42px]">Courtroom</h1>
          <p className="mt-2.5 text-[16px] leading-relaxed text-ink-2 text-pretty">
            A strategy asked for capital and was held. Watch the prosecutor test it, the defence answer, and the judge rule, then see what the strategy really earns on data nobody had seen.
          </p>
        </div>
        {docket.data?.source === 'fixture' && <Badge title="The real files are not in web/public/data yet. This page shows sample data written by hand.">Sample data</Badge>}
      </header>

      {/* controls */}
      <div className="panel mb-6 flex flex-wrap items-end gap-x-5 gap-y-4 px-4 py-4">
        <Select className="w-full min-w-[230px] sm:w-[320px]" label="Case" value={caseId} onChange={(v) => { setCaseId(v); setMode('recorded') }} options={options.length ? options : [{ value: caseId, label: `Case ${caseNo(caseId)}` }]} />
        {twin && (
          <Button variant="outline" onClick={() => { setCaseId(twin); setMode('recorded') }} title="Same headline numbers, different truth">
            Switch to the {b?.twin_of ? 'guilty' : 'innocent'} twin
          </Button>
        )}
        <div className="flex flex-col gap-1.5">
          <span className="label">Source</span>
          <Segmented label="Recorded or live" value={mode} onChange={(m) => setMode(m)} options={[{ value: 'recorded', label: 'Recorded trial' }, { value: 'live', label: 'Live trial', title: liveReady ? 'Run a new trial on the server' : 'Needs the gateway server' }]} />
        </div>
        {!live && (
          <>
            <div className="flex flex-col gap-1.5">
              <span className="label">Replay</span>
              <div className="flex items-center gap-2">
                <Button variant="primary" onClick={pb.toggle} aria-label={pb.playing ? 'Pause' : pb.done ? 'Replay' : 'Play'} className="w-[96px]">
                  {pb.playing ? <><IconPause size={14} /> Pause</> : pb.done ? <><IconRestart size={14} /> Replay</> : <><IconPlay size={14} /> Play</>}
                </Button>
                <Button variant="outline" onClick={pb.step} disabled={pb.done} aria-label="Next step"><IconStep size={14} /> Step</Button>
                <Button variant="ghost" onClick={pb.toRuling} disabled={pb.shown > events.findIndex((e) => e.kind === 'verdict')}>Skip to ruling</Button>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="label">Speed</span>
              <Segmented label="Replay speed" value={String(speed)} onChange={(v) => setSpeed(Number(v))} options={[0.5, 1, 2, 4].map((s) => ({ value: String(s), label: `${s}×` }))} />
            </div>
            <div className="ml-auto hidden min-w-[160px] max-w-[260px] flex-1 flex-col gap-0.5 lg:flex">
              <span className="label">Step {Math.min(pb.shown, pb.total)} of {pb.total}</span>
              <input type="range" className="scrub" min={0} max={pb.total} value={pb.shown} aria-label="Position in the trial"
                style={{ '--fill': `${(pb.shown / pb.total) * 100}%` } as React.CSSProperties} onChange={(e) => pb.seek(Number(e.target.value))} />
            </div>
          </>
        )}
      </div>

      {live && (
        <div className="panel mb-6 p-4 md:p-5">
          {!liveReady ? (
            <Note>{LIVE ? 'The live server is not reachable right now, so only recorded trials can be replayed.' : 'The live trial needs the gateway server. This copy of the site is a static build, so it can only replay recorded trials.'} Switch to &ldquo;Recorded trial&rdquo;.</Note>
          ) : watchId ? (
            <p className="text-[14.5px] text-ink-2">Following case <span className="mono">{watchId}</span> as the court works. {liveState === 'error' && <span className="text-accent-2">{liveError}</span>}</p>
          ) : (
            <>
              <h2 className="serif text-[18px] font-semibold text-ink">Staff the court</h2>
              <p className="mt-1 text-[14px] text-ink-3">Choose who plays each role and which kind of review runs. The tests themselves are the same code in every case.</p>
              <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Select label="System" value={system} onChange={setSystem} options={SYSTEMS} />
                <Select label="Prosecutor" value={staff.prosecution} onChange={(v) => setStaff({ ...staff, prosecution: v })} options={staffOptions} />
                <Select label="Defence" value={staff.defence} onChange={(v) => setStaff({ ...staff, defence: v })} options={staffOptions} />
                <Select label="Judge" value={staff.judge} onChange={(v) => setStaff({ ...staff, judge: v })} options={staffOptions} />
              </div>
              <div className="mt-4 flex items-center gap-3">
                <Button variant="primary" onClick={runLive} disabled={liveState === 'running'}>{liveState === 'running' ? 'Trial running' : 'Run the trial'}</Button>
                {liveState === 'error' && <span className="text-[13.5px] text-accent-2">{liveError}</span>}
              </div>
            </>
          )}
        </div>
      )}

      {bundle.loading && !b && <Loading label="Loading the case" />}
      {bundle.error && !b && !live && (
        <Note tone="warn">
          This case has no recorded trial in this copy of the site ({bundle.error.message}). {rows.some((r) => r.has_trial) ? 'Pick another case above.' : 'The recorded trials are exported with the real data.'}
        </Note>
      )}

      {(b || live) && (
        <>
          {/* phone: switch between the case file and the trial */}
          <div className="mb-4 lg:hidden">
            <Segmented label="Show" value={view} onChange={setView} options={[{ value: 'trial', label: 'The trial' }, { value: 'file', label: 'Case file' }]} />
          </div>
          <div className="grid gap-x-10 gap-y-8 lg:grid-cols-[minmax(0,370px)_minmax(0,1fr)]">
            <aside className={cx('lg:sticky lg:top-[78px] lg:block lg:max-h-[calc(100vh-96px)] lg:self-start lg:overflow-y-auto lg:pr-3', view === 'file' ? 'block' : 'hidden')} aria-label="Case file">
              <CaseFilePanel file={file} log={b?.log} tear={b?.tearsheet} />
            </aside>
            <section className={cx('min-w-0 lg:block', view === 'trial' ? 'block' : 'hidden')} aria-label="Trial">
              {live && liveState === 'idle' && liveReady && !watchId && <p className="text-[14.5px] text-ink-3">Press &ldquo;Run the trial&rdquo;. Events appear here as the court produces them.</p>}
              {(!live || liveEvents.length > 0) && (
                <Feed events={events} shown={shown} flash={flash} truth={truthOk ? (watchId ? watchTruth : b?.truth ?? null) : null} claimed={file?.claim.sharpe ?? 0} onJump={jump} stats={stats} live={live} />
              )}
              {!live && pb.shown === 0 && <p className="text-[14px] text-ink-3">The trial starts in a moment.</p>}
              {live && liveState === 'running' && <p className="mt-4 text-[13.5px] text-ink-3" role="status">The court is still working…</p>}
              {verdictEvent && !live && pb.done && twin && (
                <div className="mt-8 flex flex-wrap items-center gap-3 border-t border-line pt-5">
                  <span className="text-[14.5px] text-ink-2">
                    {b?.twin_of ? 'The twin is the guilty strategy with the same headline numbers.' : `The innocent twin claims nearly the same numbers (Sharpe ${sh(rows.find((r) => r.case_id === twin)?.claimed_sharpe ?? 0)}).`}
                  </span>
                  <Button variant="outline" onClick={() => setCaseId(twin)}>Try the {b?.twin_of ? 'guilty' : 'innocent'} twin</Button>
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </Page>
  )
}

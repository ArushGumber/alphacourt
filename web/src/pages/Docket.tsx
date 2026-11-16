import { useMemo, useState } from 'react'
import { getDocket } from '../data/api'
import { useAsync } from '../data/hooks'
import { Page } from '../components/Layout'
import { Badge, Loading, Note, PageHeader, SampleNote, Select, cx } from '../components/ui'
import { IconCheck, IconClose } from '../components/Icons'
import { RULING_LABEL, SIN_LABEL, caseNo, sh } from '../lib/labels'
import { SINS, type DocketRow } from '../types'

const ALL = 'all'

function Verdict({ r }: { r: DocketRow }) {
  return (
    <span className={cx('inline-flex items-center gap-1.5 text-[13.5px] font-medium', r.ruling === 'reject' ? 'text-accent-2' : 'text-ink')}>
      {RULING_LABEL[r.ruling]}
    </span>
  )
}
function Correct({ r }: { r: DocketRow }) {
  return r.correct ? (
    <span className="inline-flex items-center gap-1.5 text-[13px] text-ink-2"><IconCheck size={13} /> Right</span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-accent-2"><IconClose size={13} /> {r.guilty ? 'Missed' : 'False alarm'}</span>
  )
}
const sins = (r: DocketRow) => (r.sins.length ? r.sins.map((s) => SIN_LABEL[s]).join(', ') : 'None')
const link = (r: DocketRow) => `#/courtroom?c=${r.case_id}`

export default function Docket() {
  const d = useAsync(() => getDocket(), [])
  const rows = d.data?.value
  const [sin, setSin] = useState(ALL)
  const [level, setLevel] = useState(ALL)
  const [verdict, setVerdict] = useState(ALL)
  const [truth, setTruth] = useState(ALL)

  const shown = useMemo(() => (rows ?? []).filter((r) =>
    (sin === ALL || (sin === 'none' ? r.sins.length === 0 : r.sins.includes(sin as never))) &&
    (level === ALL || r.level === level) &&
    (verdict === ALL || r.ruling === verdict) &&
    (truth === ALL || (truth === 'guilty') === r.guilty)), [rows, sin, level, verdict, truth])
  const staffed = [...new Set((rows ?? []).filter((r) => r.system === 'court' && r.staffing).map((r) => r.staffing as string))]
  const right = shown.filter((r) => r.correct).length

  return (
    <Page wide>
      <PageHeader title="Docket">
        <p>Every case the court has tried, with the truth beside the ruling. Guilty strategies come in pairs with an innocent twin that has similar headline numbers and a real edge.</p>
      </PageHeader>
      <SampleNote show={d.data?.source === 'fixture'} />
      {d.loading && <Loading />}
      {d.error && <Note tone="warn">The docket is not in this copy of the site ({d.error.message}).</Note>}
      {rows && (
        <>
          <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Select label="Flaw" value={sin} onChange={setSin} options={[{ value: ALL, label: 'Any flaw' }, ...SINS.map((s) => ({ value: s, label: SIN_LABEL[s] })), { value: 'none', label: 'None (innocent)' }]} />
            <Select label="Visibility level" value={level} onChange={setLevel} options={[{ value: ALL, label: 'Any level' }, { value: 'L1', label: 'L1: stated in the submission' }, { value: 'L2', label: 'L2: needs domain knowledge' }, { value: 'L3', label: 'L3: identical text for both twins' }, { value: 'unusual', label: 'Unusual innocent' }]} />
            <Select label="Ruling" value={verdict} onChange={setVerdict} options={[{ value: ALL, label: 'Any ruling' }, { value: 'deploy', label: 'Deploy' }, { value: 'paper', label: 'Paper only' }, { value: 'reject', label: 'Reject' }]} />
            <Select label="Truth" value={truth} onChange={setTruth} options={[{ value: ALL, label: 'Guilty and innocent' }, { value: 'guilty', label: 'Guilty' }, { value: 'innocent', label: 'Innocent' }]} />
          </div>
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3 text-[13.5px] text-ink-3" role="status">
            <span>{shown.length} of {rows.length} cases. {staffed.length ? `The court, staffed by ${staffed.join(' and ')}, was right on ${right}.` : `The court was right on ${right}.`}</span>
            <a className="text-accent-2 underline hover:text-ink" href={`${import.meta.env.BASE_URL}data/docket.json`} download>Download the docket (JSON)</a>
          </div>

          <div className="hidden overflow-x-auto rounded-[8px] border border-line bg-bg-1 md:block">
            <table className="w-full min-w-[900px] border-collapse text-left text-[14px]">
              <thead>
                <tr className="border-b border-line text-[12.5px] text-ink-3">
                  <th className="px-4 py-3 font-medium">Case</th><th className="py-3 font-medium">Strategy</th><th className="py-3 font-medium">Flaws planted</th>
                  <th className="py-3 font-medium">Level</th><th className="py-3 text-right font-medium">Claimed</th><th className="py-3 text-right font-medium">True</th>
                  <th className="py-3 pl-6 font-medium">Court ruling{staffed.length === 1 && <span className="block text-[11.5px] font-normal">{staffed[0]}</span>}</th><th className="py-3 font-medium">Outcome</th><th className="px-4 py-3 font-medium"><span className="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.case_id} className="border-b border-line/70 last:border-0 hover:bg-bg-2/60">
                    <td className="num px-4 py-3 text-ink-3">{caseNo(r.case_id)}</td>
                    <td className="py-3 pr-4"><a href={link(r)} className="font-medium text-ink hover:text-accent-2 hover:underline">{r.name}</a><div className="text-[12.5px] text-ink-3">{r.family}{r.twin_of ? `, twin of ${caseNo(r.twin_of)}` : ''}</div></td>
                    <td className="py-3 pr-4 text-ink-2">{r.guilty ? sins(r) : <span className="text-ink-3">None, innocent</span>}</td>
                    <td className="py-3 pr-4 text-ink-2">{r.level === 'unusual' ? 'Unusual' : r.level}</td>
                    <td className="num py-3 text-right text-ink-2">{sh(r.claimed_sharpe)}</td>
                    <td className={cx('num py-3 text-right font-medium', r.true_sharpe < 0.3 ? 'text-accent-2' : 'text-ink')}>{sh(r.true_sharpe)}</td>
                    <td className="py-3 pl-6"><Verdict r={r} /></td>
                    <td className="py-3"><Correct r={r} /></td>
                    <td className="px-4 py-3 text-right">{r.has_trial ? <a href={link(r)} className="text-[13px] text-accent-2 hover:underline">Open</a> : <Badge title="No recorded trial in this copy of the site">No recording</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ul className="divide-y divide-line rounded-[8px] border border-line bg-bg-1 md:hidden">
            {shown.map((r) => (
              <li key={r.case_id} className="p-4">
                <a href={link(r)} className="text-[15px] font-medium text-ink">{r.name}</a>
                <div className="mt-0.5 text-[12.5px] text-ink-3">Case {caseNo(r.case_id)} &middot; {r.family} &middot; {r.level === 'unusual' ? 'Unusual' : r.level}</div>
                <div className="mt-2 text-[13.5px] text-ink-2">{r.guilty ? sins(r) : 'Innocent'}</div>
                <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1">
                  <span className="text-[13px] text-ink-3">Claimed <span className="num font-medium text-ink">{sh(r.claimed_sharpe)}</span></span>
                  <span className="text-[13px] text-ink-3">True <span className={cx('num font-medium', r.true_sharpe < 0.3 ? 'text-accent-2' : 'text-ink')}>{sh(r.true_sharpe)}</span></span>
                  <Verdict r={r} /><Correct r={r} />
                </div>
              </li>
            ))}
          </ul>
          {shown.length === 0 && <p className="mt-6 text-[14.5px] text-ink-3">No case matches these filters.</p>}
        </>
      )}
    </Page>
  )
}

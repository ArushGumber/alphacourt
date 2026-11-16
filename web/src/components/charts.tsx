// Small SVG charts, drawn at the width they are given. One highlighted series per chart (accent), the rest muted.
// Colours are the site tokens. First draw animates (stroke or bar growth); reduced motion shows the final state.
import { useMemo } from 'react'
import { useWidth } from '../data/hooks'
import type { ChartSeries, ExhibitChartData } from '../types'

const INK = 'var(--color-ink-2)'
const MUTED = 'var(--color-ink-4)'
const GRID = 'rgba(31,30,27,0.08)'
const ACCENT = 'var(--color-accent)'
const COOL = 'var(--color-cool)'
const FONT = "'Inter Variable', Inter, system-ui, sans-serif"

export function niceTicks(lo: number, hi: number, n = 4): number[] {
  if (hi === lo) return [lo]
  const span = hi - lo
  const raw = span / n
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const out: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v / step) * step)
  return out
}

const fmtTick = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(0) : Math.abs(v) < 0.01 && v !== 0 ? v.toFixed(3) : Number(v.toFixed(2)).toString())

interface Frame {
  w: number
  h: number
  l: number
  r: number
  t: number
  b: number
}
const frame = (w: number, h: number, yLabelWidth: number): Frame => ({ w, h, l: yLabelWidth, r: 10, t: 22, b: 34 })

function Axes({ f, yTicks, y, xLabel, yLabel, zero, fmt = fmtTick }: { f: Frame; yTicks: number[]; y: (v: number) => number; xLabel?: string; yLabel?: string; zero?: boolean; fmt?: (v: number) => string }) {
  return (
    <g fontFamily={FONT} fontSize={11.5} fill={MUTED}>
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={f.l} x2={f.w - f.r} y1={y(t)} y2={y(t)} stroke={GRID} />
          <text x={f.l - 6} y={y(t) + 4} textAnchor="end" className="num">{fmt(t)}</text>
        </g>
      ))}
      {zero && <line x1={f.l} x2={f.w - f.r} y1={y(0)} y2={y(0)} stroke={MUTED} strokeWidth={1} opacity={0.55} />}
      {yLabel && <text x={f.l - 6} y={12} textAnchor="start" fill={MUTED}>{yLabel}</text>}
      {xLabel && <text x={f.l} y={f.h - 8} textAnchor="start" fill={MUTED}>{xLabel}</text>}
    </g>
  )
}

function Frame2({ h, children, label }: { h: number; children: (w: number) => React.ReactNode; label: string }) {
  const [ref, w] = useWidth<HTMLDivElement>()
  return (
    <div ref={ref} className="w-full">
      {w > 0 && (
        <svg width={w} height={h} role="img" aria-label={label} className="block overflow-visible">
          {children(w)}
        </svg>
      )}
    </div>
  )
}

const path = (xs: number[], ys: number[], x: (v: number) => number, y: (v: number) => number) => xs.map((v, i) => `${i ? 'L' : 'M'}${x(v).toFixed(1)} ${y(ys[i]).toFixed(1)}`).join('')

/** Cumulative P&L lines. The last series is the highlighted one; earlier ones are muted. `split` marks where a new period starts. */
export function EquityChart({ series, split, height = 190, xLabel, yLabel, label, accentLast = true }: {
  series: ChartSeries[]; split?: number; height?: number; xLabel?: string; yLabel?: string; label: string; accentLast?: boolean
}) {
  const all = series.flatMap((s) => s.y)
  const lo = Math.min(...all, 0)
  const hi = Math.max(...all, 0)
  const pad = (hi - lo) * 0.06 || 1
  return (
    <Frame2 h={height} label={label}>
      {(w) => {
        const ticks = niceTicks(lo - pad, hi + pad, 4)
        const f = frame(w, height, 8 + Math.max(...ticks.map((t) => fmtTick(t * 100).length)) * 6.5)
        const yy = (v: number) => f.t + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (f.h - f.t - f.b)
        const n = Math.max(...series.map((s) => s.y.length))
        const xx = (i: number) => f.l + (i / Math.max(1, n - 1)) * (f.w - f.l - f.r)
        const ends = series.map((s, i) => ({ i, y: yy(s.y[s.y.length - 1]) }))
        const lastIdx = series.length - 1
        return (
          <>
            <Axes f={f} yTicks={ticks} y={yy} xLabel={xLabel} yLabel={yLabel} zero fmt={(v) => fmtTick(Math.round(v * 100))} />
            {split != null && (
              <line x1={xx(split)} x2={xx(split)} y1={f.t} y2={f.h - f.b} stroke={MUTED} strokeDasharray="3 3" opacity={0.7} />
            )}
            {series.map((s, i) => {
              const hl = accentLast ? i === lastIdx : series.length === 1
              const d = path(s.y.map((_, k) => k), s.y, xx, yy)
              return <path key={s.label} d={d} pathLength={1} fill="none" stroke={hl ? ACCENT : MUTED} strokeWidth={hl ? 2 : 1.4} strokeLinejoin="round" strokeLinecap="round" className="draw-line" opacity={hl ? 1 : 0.85} />
            })}
            <g fontFamily={FONT} fontSize={12} fontWeight={500}>
              {series.length > 1 && ends.map(({ i, y }) => {
                const above = ends.every((e) => e.i === i || y <= e.y) ? true : false
                const hl = i === lastIdx
                return (
                  <text key={i} x={f.w - f.r - 4} y={above ? y - 8 : y + 17} textAnchor="end" fill={hl ? 'var(--color-accent-2)' : INK} stroke="var(--color-bg-1)" strokeWidth={4} paintOrder="stroke">
                    {series[i].label}
                  </text>
                )
              })}
            </g>
          </>
        )
      }}
    </Frame2>
  )
}

/**
 * Vertical bars. `values` is one series; `more` adds series drawn beside it (the last one in the accent colour, the
 * first muted). `highlight` is the accent bar of a single series; `ref` a dashed horizontal line with a label.
 */
export function BarsChart({ labels, values, more, seriesLabels, highlight, ref, height = 190, xLabel, yLabel, label, showValues }: {
  labels: string[]; values: number[]; more?: number[][]; seriesLabels?: string[]; highlight?: number; ref?: { value: number; label: string }; height?: number; xLabel?: string; yLabel?: string; label: string; showValues?: boolean
}) {
  const groups = [values, ...(more ?? [])]
  const k = groups.length
  const all = groups.flat()
  const dense = values.length > 12
  const lo = Math.min(0, ...all)
  const hi = Math.max(0, ...all, ref?.value ?? 0)
  const pad = (hi - lo) * 0.08
  const sv = showValues ?? !dense
  return (
    <Frame2 h={height} label={label}>
      {(w) => {
        const ticks = niceTicks(lo, hi + pad, 4)
        const f = frame(w, height, 8 + Math.max(...ticks.map((t) => fmtTick(t).length)) * 6.5)
        f.t = sv ? 28 : 22
        f.b = dense ? 34 : 44
        const top = Math.max(hi + pad, ticks[ticks.length - 1])
        const yy = (v: number) => f.t + (1 - (v - lo) / (top - lo)) * (f.h - f.t - f.b)
        const bw = (f.w - f.l - f.r) / values.length
        const gap = dense ? Math.max(1, bw * 0.2) : Math.min(14, bw * 0.3)
        const sw = Math.max(1, (bw - gap) / k)
        return (
          <>
            <Axes f={f} yTicks={ticks} y={yy} yLabel={yLabel} zero />
            {values.map((_, i) => {
              const y0 = yy(0)
              return (
                <g key={i}>
                  {groups.map((g, gi) => {
                    const v = g[i]
                    if (v == null || !Number.isFinite(v)) return null
                    const x = f.l + i * bw + gap / 2 + gi * sw
                    const y1 = yy(v)
                    const hl = k > 1 ? gi === k - 1 : highlight === i || (highlight == null && values.length === 1)
                    return (
                      <g key={gi}>
                        <rect x={x} y={Math.min(y0, y1)} width={Math.max(1, sw - (k > 1 ? 1 : 0))} height={Math.max(1, Math.abs(y1 - y0))} fill={hl ? ACCENT : MUTED} opacity={hl ? 1 : 0.5} className="grow-bar" />
                        {sv && (
                          <text x={x + sw / 2} y={v >= 0 ? y1 - 6 : y1 + 15} textAnchor="middle" fontFamily={FONT} fontSize={k > 1 ? 11 : 12} fontWeight={500} fill={INK} className="num">{v.toFixed(2)}</text>
                        )}
                      </g>
                    )
                  })}
                  {(!dense || i === 0 || i === values.length - 1 || (i + 1) % 10 === 0) && (
                    <text x={f.l + i * bw + bw / 2} y={f.h - f.b + 16} textAnchor="middle" fontFamily={FONT} fontSize={11.5} fill={MUTED}>{labels[i]}</text>
                  )}
                </g>
              )
            })}
            {ref && (
              <g fontFamily={FONT} fontSize={12} fontWeight={500}>
                <line x1={f.l} x2={f.w - f.r} y1={yy(ref.value)} y2={yy(ref.value)} stroke={COOL} strokeWidth={1.6} strokeDasharray="5 4" />
                <text x={f.w - f.r} y={yy(ref.value) - 6} textAnchor="end" fill={COOL} stroke="var(--color-bg-1)" strokeWidth={4} paintOrder="stroke">{ref.label}</text>
              </g>
            )}
            {k > 1 && seriesLabels && (
              <g fontFamily={FONT} fontSize={11.5} fill={INK}>
                {seriesLabels.map((t, gi) => (
                  <g key={gi} transform={`translate(${f.l + gi * 170},${f.h - 22})`}>
                    <rect width={10} height={10} y={-9} fill={gi === k - 1 ? ACCENT : MUTED} opacity={gi === k - 1 ? 1 : 0.5} />
                    <text x={15}>{t}</text>
                  </g>
                ))}
              </g>
            )}
            {xLabel && <text x={f.l} y={f.h - 6} fontFamily={FONT} fontSize={11.5} fill={MUTED}>{xLabel}</text>}
          </>
        )
      }}
    </Frame2>
  )
}

/** A line over a numeric x axis, with an optional horizontal reference (ref) and vertical marker. */
export function LineChart({ series, ref, marker, height = 190, xLabel, yLabel, label }: {
  series: ChartSeries[]; ref?: { value: number; label: string }; marker?: { value: number; label: string }; height?: number; xLabel?: string; yLabel?: string; label: string
}) {
  const xs = series.flatMap((s) => s.x ?? s.y.map((_, i) => i))
  const ys = series.flatMap((s) => s.y)
  const lo = Math.min(...ys, ref?.value ?? Infinity)
  const hi = Math.max(...ys, ref?.value ?? -Infinity)
  const pad = (hi - lo) * 0.08
  return (
    <Frame2 h={height} label={label}>
      {(w) => {
        const ticks = niceTicks(lo - pad, hi + pad, 4)
        const f = frame(w, height, 8 + Math.max(...ticks.map((t) => fmtTick(t).length)) * 6.5)
        const x0 = Math.min(...xs)
        const x1 = Math.max(...xs)
        const xx = (v: number) => f.l + ((v - x0) / (x1 - x0 || 1)) * (f.w - f.l - f.r)
        const yy = (v: number) => f.t + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (f.h - f.t - f.b)
        const xt = niceTicks(x0, x1, 5)
        return (
          <>
            <Axes f={f} yTicks={ticks} y={yy} yLabel={yLabel} />
            {ref && <line x1={f.l} x2={f.w - f.r} y1={yy(ref.value)} y2={yy(ref.value)} stroke={MUTED} opacity={0.6} />}
            {ref && <text x={f.w - f.r} y={yy(ref.value) - 5} textAnchor="end" fontFamily={FONT} fontSize={11.5} fill={MUTED}>{ref.label}</text>}
            <g fontFamily={FONT} fontSize={11.5} fill={MUTED}>
              {xt.map((t) => <text key={t} x={xx(t)} y={f.h - f.b + 16} textAnchor="middle" className="num">{fmtTick(t)}</text>)}
              {xLabel && <text x={f.l} y={f.h - 6}>{xLabel}</text>}
            </g>
            {marker && (
              <g fontFamily={FONT} fontSize={12} fontWeight={500}>
                <line x1={xx(marker.value)} x2={xx(marker.value)} y1={f.t} y2={f.h - f.b} stroke={COOL} strokeWidth={1.6} strokeDasharray="5 4" />
                <text x={xx(marker.value) - 6} y={f.t + 12} textAnchor="end" fill={COOL} stroke="var(--color-bg-1)" strokeWidth={4} paintOrder="stroke">{marker.label}</text>
              </g>
            )}
            {series.map((s, i) => {
              const sx = s.x ?? s.y.map((_, k) => k)
              const hl = i === series.length - 1
              return <path key={s.label} d={path(sx, s.y, xx, yy)} pathLength={1} fill="none" stroke={hl ? ACCENT : MUTED} strokeWidth={hl ? 2 : 1.4} strokeLinejoin="round" className="draw-line" />
            })}
            {marker && series[0] && (() => {
              const s = series[0]
              const sx = s.x ?? s.y.map((_, k) => k)
              const k = sx.indexOf(marker.value)
              return k >= 0 ? <circle cx={xx(marker.value)} cy={yy(s.y[k])} r={4} fill={ACCENT} stroke="var(--color-bg-1)" strokeWidth={1.5} /> : null
            })()}
          </>
        )
      }}
    </Frame2>
  )
}

/** Histogram of a null distribution with one marked value. */
export function DistChart({ counts, lo, hi, edges, marker, height = 190, xLabel, yLabel, label }: {
  counts: number[]; lo: number; hi: number; edges?: number[]; marker?: { value: number; label: string }; height?: number; xLabel?: string; yLabel?: string; label: string
}) {
  const max = Math.max(...counts, 1)
  // the axis also covers the marked value, which can sit far outside the histogram
  const a0 = Math.min(lo, marker?.value ?? lo)
  const a1 = Math.max(hi, marker?.value ?? hi)
  const ap = marker && (marker.value < lo || marker.value > hi) ? (a1 - a0) * 0.03 : 0
  return (
    <Frame2 h={height} label={label}>
      {(w) => {
        const ticks = niceTicks(0, max, 3)
        const f = frame(w, height, 8 + Math.max(...ticks.map((t) => fmtTick(t).length)) * 6.5)
        const yy = (v: number) => f.t + (1 - v / Math.max(max, ticks[ticks.length - 1])) * (f.h - f.t - f.b)
        const xx = (v: number) => f.l + ((v - (a0 - ap)) / (a1 + ap - (a0 - ap) || 1)) * (f.w - f.l - f.r)
        const edge = (i: number) => edges?.[i] ?? lo + ((hi - lo) * i) / counts.length
        const xt = niceTicks(a0, a1, 5)
        return (
          <>
            <Axes f={f} yTicks={ticks} y={yy} yLabel={yLabel} />
            {counts.map((c, i) => (
              <rect key={i} x={xx(edge(i)) + 0.5} y={yy(c)} width={Math.max(1, xx(edge(i + 1)) - xx(edge(i)) - 1)} height={Math.max(0, yy(0) - yy(c))} fill={MUTED} opacity={0.45} className="grow-bar" />
            ))}
            <g fontFamily={FONT} fontSize={11.5} fill={MUTED}>
              {xt.map((t) => <text key={t} x={xx(t)} y={f.h - f.b + 16} textAnchor="middle" className="num">{fmtTick(t)}</text>)}
              {xLabel && <text x={f.l} y={f.h - 6}>{xLabel}</text>}
            </g>
            {marker && (
              <g fontFamily={FONT} fontSize={12} fontWeight={500}>
                <line x1={xx(marker.value)} x2={xx(marker.value)} y1={f.t} y2={f.h - f.b} stroke={ACCENT} strokeWidth={2} />
                <text x={xx(marker.value) - 6} y={f.t + 12} textAnchor="end" fill="var(--color-accent-2)" stroke="var(--color-bg-1)" strokeWidth={4} paintOrder="stroke">{marker.label}</text>
              </g>
            )}
          </>
        )
      }}
    </Frame2>
  )
}

/**
 * Draws whatever shape the exhibit's chart data has. The forensic tools write their charts as `series` with `y` (and
 * `x`) and the histogram with `bin_edges`; the exported site files may use the flatter forms (`values`, `counts` with
 * `lo` and `hi`, a marker object). Both are read here. Unknown shapes draw nothing.
 */
export function ExhibitChart({ chart, label, height }: { chart: ExhibitChartData; label: string; height?: number }) {
  const c = chart
  return useMemo(() => {
    if (!c || !c.type) return null
    const series = Array.isArray(c.series) ? c.series.filter((s) => s?.y?.length) : []
    if (c.type === 'equity' && series.length)
      return <EquityChart series={series} split={c.split} xLabel={c.x_label} yLabel={c.y_label} label={label} height={height} />
    if (c.type === 'bars') {
      const first = c.values?.length ? c.values : series[0]?.y
      if (!first?.length) return null
      const labels = (c.labels as string[] | undefined) ?? first.map((_, i) => String(i + 1))
      const more = c.values?.length ? undefined : series.slice(1).map((s) => s.y)
      const hi = c.highlight ?? (series.length > 1 ? undefined : labels.findIndex((l) => /sealed|haircut/i.test(l)))
      return <BarsChart labels={labels} values={first} more={more} seriesLabels={series.map((s) => s.label)} highlight={hi != null && hi >= 0 ? hi : undefined} ref={c.ref} xLabel={c.x_label} yLabel={c.y_label} label={label} height={height} />
    }
    if (c.type === 'line' && series.length)
      return <LineChart series={series} ref={c.ref} marker={markerOf(c)} xLabel={c.x_label} yLabel={c.y_label} label={label} height={height} />
    if ((c.type === 'dist' || c.type === 'histogram') && c.counts?.length) {
      const edges = Array.isArray(c.bin_edges) ? (c.bin_edges as number[]) : undefined
      const lo = edges ? edges[0] : c.lo
      const hi = edges ? edges[edges.length - 1] : c.hi
      if (lo == null || hi == null) return null
      return <DistChart counts={c.counts} lo={lo} hi={hi} edges={edges} marker={markerOf(c)} xLabel={c.x_label} yLabel={c.y_label} label={label} height={height} />
    }
    return null
  }, [c, label, height])
}

function markerOf(c: ExhibitChartData): { value: number; label: string } | undefined {
  const m = c.marker as unknown
  if (typeof m === 'number') return { value: m, label: String(c.marker_label ?? '') }
  return (m as { value: number; label: string } | undefined) ?? undefined
}

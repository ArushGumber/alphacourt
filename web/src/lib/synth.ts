// Small deterministic helpers for the sample data. The real files come from the Python side.

export function rng(seed: number) {
  let s = seed >>> 0
  const next = () => {
    s = (s + 0x6d2b79f5) >>> 0
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  const normal = () => {
    const u = Math.max(next(), 1e-9)
    const v = next()
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
  }
  return { next, normal }
}

/** Cumulative P&L with an exact per-step Sharpe: noise is standardised, then the drift is added. */
export function equityPath(seed: number, n: number, stepSharpe: number, vol = 0.0107): number[] {
  const r = rng(seed)
  const z = Array.from({ length: n }, () => r.normal())
  const m = z.reduce((a, b) => a + b, 0) / n
  const sd = Math.sqrt(z.reduce((a, b) => a + (b - m) ** 2, 0) / n)
  let acc = 0
  const out: number[] = [0]
  for (let i = 0; i < n; i++) {
    acc += ((z[i] - m) / sd + stepSharpe) * vol
    out.push(round(acc, 5))
  }
  return out
}

/** Per-step Sharpe for an annualised Sharpe when each point stands for k daily bars. */
export const stepSharpe = (annual: number, k: number) => (annual / Math.sqrt(252)) * Math.sqrt(k)

export function round(x: number, d = 2) {
  const p = 10 ** d
  return Math.round(x * p) / p
}

export function hash12(s: string) {
  let h1 = 0xdeadbeef
  let h2 = 0x41c6ce57
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i)
    h1 = Math.imul(h1 ^ c, 2654435761)
    h2 = Math.imul(h2 ^ c, 1597334677)
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909)
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909)
  return ((h2 >>> 0).toString(16).padStart(8, '0') + (h1 >>> 0).toString(16).padStart(8, '0')).slice(0, 12)
}

/** Histogram counts of draws from a normal(mean, sd) shape, for the placebo chart. */
export function histogram(seed: number, n: number, mean: number, sd: number, bins: number, lo: number, hi: number) {
  const r = rng(seed)
  const counts = Array(bins).fill(0)
  for (let i = 0; i < n; i++) {
    const v = mean + sd * r.normal()
    const b = Math.min(bins - 1, Math.max(0, Math.floor(((v - lo) / (hi - lo)) * bins)))
    counts[b]++
  }
  return counts
}

import { useCallback, useEffect, useRef, useState } from 'react'
import type { TrialEvent } from '../types'

/** Milliseconds to wait before an event of this kind appears, at speed 1. */
const DELAY: Record<string, number> = { case: 0, tool_call: 900, exhibit: 1500, charge: 1700, rebuttal: 1900, verdict: 2600, note: 1500, error: 800 }
export const TRUTH_DELAY = 2600

/**
 * Reveals a recorded trial one event at a time. `total` counts the events plus one closing step (the truth).
 * `shown` is how many steps are visible. Changing `resetKey` starts over.
 */
export function usePlayback(events: TrialEvent[], resetKey: string, opts: { speed: number; autoplay: boolean }) {
  const total = events.length + 1
  const [shown, setShown] = useState(0)
  const [playing, setPlaying] = useState(opts.autoplay)
  const key = useRef(resetKey)

  useEffect(() => {
    if (key.current !== resetKey) {
      key.current = resetKey
      setShown(0)
      setPlaying(opts.autoplay)
    }
  }, [resetKey, opts.autoplay])

  useEffect(() => {
    if (!playing || shown >= total) {
      if (shown >= total) setPlaying(false)
      return
    }
    const d = shown < events.length ? DELAY[events[shown].kind] ?? 1200 : TRUTH_DELAY
    const t = window.setTimeout(() => setShown((s) => s + 1), d / opts.speed)
    return () => window.clearTimeout(t)
  }, [playing, shown, total, events, opts.speed])

  const toggle = useCallback(() => {
    if (shown >= total) {
      setShown(0)
      setPlaying(true)
    } else setPlaying((p) => !p)
  }, [shown, total])
  const restart = useCallback(() => {
    setShown(0)
    setPlaying(true)
  }, [])
  const step = useCallback(() => {
    setPlaying(false)
    setShown((s) => Math.min(total, s + 1))
  }, [total])
  const seek = useCallback((n: number) => {
    setPlaying(false)
    setShown(Math.max(0, Math.min(total, n)))
  }, [total])
  const showAll = useCallback(() => {
    setPlaying(false)
    setShown(total)
  }, [total])
  const toRuling = useCallback(() => {
    setPlaying(false)
    const i = events.findIndex((e) => e.kind === 'verdict')
    setShown(i < 0 ? total : i + 1)
  }, [events, total])

  return { shown, total, playing, toggle, restart, step, seek, showAll, toRuling, done: shown >= total }
}

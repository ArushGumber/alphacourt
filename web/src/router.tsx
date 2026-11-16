// Hash-based routing (#/desk, #/bubble-lab ...) so the built site works from any folder, with no server rules.

import { useEffect, useState, type AnchorHTMLAttributes } from 'react'

export interface Route {
  path: string
  params: URLSearchParams
}

function parse(): Route {
  const h = window.location.hash.replace(/^#/, '') || '/'
  const [p, q = ''] = h.split('?')
  const path = '/' + p.replace(/^\/+/, '').replace(/\/+$/, '')
  return { path, params: new URLSearchParams(q) }
}

export function useRoute(): Route {
  const [r, setR] = useState(parse)
  useEffect(() => {
    const on = () => setR(parse())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return r
}

export function navigate(to: string) {
  window.location.hash = to
}

/** Write the page's state into the address without adding a history entry (so links can be shared). */
export function replaceParams(values: Record<string, string | null | undefined>) {
  const { path, params } = parse()
  for (const [k, v] of Object.entries(values)) {
    if (v === null || v === undefined || v === '') params.delete(k)
    else params.set(k, v)
  }
  const q = params.toString()
  const url = `${window.location.pathname}${window.location.search}#${path}${q ? '?' + q : ''}`
  window.history.replaceState(window.history.state, '', url)
}

export function readParams(): URLSearchParams {
  return parse().params
}

export function Link({ to, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  return <a href={`#${to}`} {...rest} />
}

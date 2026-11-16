import type { SVGProps } from 'react'

type P = SVGProps<SVGSVGElement> & { size?: number }

function Base({ size = 16, children, ...rest }: P & { children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...rest}>
      {children}
    </svg>
  )
}

export const IconArrowRight = (p: P) => <Base {...p}><path d="M3 8h10M9 4l4 4-4 4" /></Base>
export const IconPlay = (p: P) => <Base {...p}><path d="M5 3.5v9l7.5-4.5z" fill="currentColor" stroke="none" /></Base>
export const IconPause = (p: P) => <Base {...p}><path d="M5 3.5v9M11 3.5v9" strokeWidth={2.2} /></Base>
export const IconRestart = (p: P) => <Base {...p}><path d="M3 8a5 5 0 1 0 1.5-3.6" /><path d="M3 2.5v2.5h2.5" /></Base>
export const IconStep = (p: P) => <Base {...p}><path d="M4 3.5v9l6-4.5z" fill="currentColor" stroke="none" /><path d="M12 3.5v9" strokeWidth={1.8} /></Base>
export const IconMenu = (p: P) => <Base {...p}><path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" /></Base>
export const IconClose = (p: P) => <Base {...p}><path d="M4 4l8 8M12 4l-8 8" /></Base>
export const IconCopy = (p: P) => <Base {...p}><rect x="5.5" y="5.5" width="8" height="8" rx="1.5" /><path d="M10.5 3.5v-.5A1.5 1.5 0 0 0 9 1.5H4A1.5 1.5 0 0 0 2.5 3v5A1.5 1.5 0 0 0 4 9.5h.5" /></Base>
export const IconCheck = (p: P) => <Base {...p}><path d="M3 8.5l3 3 7-7" /></Base>
export const IconChevron = (p: P) => <Base {...p}><path d="M4 6l4 4 4-4" /></Base>
export const IconDoc = (p: P) => <Base {...p}><path d="M4 1.5h5.5L13 5v9.5H4z" /><path d="M9 1.5V5h4M6.5 8h4M6.5 10.5h4" /></Base>
export const IconInfo = (p: P) => <Base {...p}><circle cx="8" cy="8" r="6" /><path d="M8 7.2v3.8M8 5v.01" /></Base>
export const IconLink = (p: P) => <Base {...p}><path d="M6.5 9.5l3-3M7 4.5l1-1a2.8 2.8 0 0 1 4 4l-1 1M9 11.5l-1 1a2.8 2.8 0 0 1-4-4l1-1" /></Base>
export const IconBolt = (p: P) => <Base {...p}><path d="M9 1.5L3.5 9H8l-1 5.5L12.5 7H8z" /></Base>
export const IconSort = ({ dir, ...p }: P & { dir?: 'asc' | 'desc' | null }) => (
  <Base {...p}>
    <path d="M5 6.5L8 3.5l3 3" opacity={dir === 'desc' ? 0.3 : 1} />
    <path d="M5 9.5l3 3 3-3" opacity={dir === 'asc' ? 0.3 : 1} />
  </Base>
)

export const IconExternal = (p: P) => <Base {...p}><path d="M6.5 3.5h-3v9h9v-3M9 3.5h3.5V7M12.5 3.5 7 9" /></Base>

/** The AlphaCourt mark: a letter A whose crossbar is a balance beam, on the accent orange. Beside the wordmark and as the favicon. */
export function Logo({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="#c8501d" />
      <path d="M16 6.5 24 25.5h-3.6L16 14.6 11.6 25.5H8z" fill="#fff" />
      <rect x="10" y="18.3" width="12" height="2.4" fill="#fff" />
    </svg>
  )
}

import { useEffect, useState, type ReactNode } from 'react'
import { Link } from '../router'
import { LIVE, SERVER_NAME } from '../data/api'
import { AUTHORS, LICENCE, LINKS, PENDING, SITE } from '../site'
import { IconClose, IconMenu, Logo } from './Icons'
import { Badge, LinkButton, cx } from './ui'

/** The site's pages, in menu order. A new page needs one line here and one case in App.tsx. */
export const NAV = [
  { to: '/courtroom', label: 'Courtroom' },
  { to: '/lab', label: 'Flaw Lab' },
  { to: '/studio', label: 'Studio' },
  { to: '/docket', label: 'Docket' },
  { to: '/results', label: 'Results' },
  { to: '/connect', label: 'Connect' },
  { to: '/how-it-works', label: 'How it works' },
  { to: '/about', label: 'About' },
]

/** Content width of most pages. */
export const CONTAINER = 'mx-auto w-full max-w-[1240px] px-5 md:px-8'
/** The header and footer span the width of the widest page (the courtroom). */
const BAR = 'mx-auto w-full max-w-[1520px] px-5 md:px-8'

export function DataBadge() {
  if (LIVE) return <Badge tone="accent" title={`Connected to the gateway at ${SERVER_NAME}`}>Live</Badge>
  return null
}

function PrimaryAction({ path, className }: { path: string; className?: string }) {
  if (LINKS.live)
    return (
      <LinkButton variant="primary" size="sm" href={LINKS.live} external className={className}>
        Try it live
      </LinkButton>
    )
  if (path === '/courtroom') return null
  return (
    <LinkButton variant="primary" size="sm" href="#/courtroom" className={className}>
      Watch a trial
    </LinkButton>
  )
}

export function Header({ path }: { path: string }) {
  const [open, setOpen] = useState(false)
  useEffect(() => setOpen(false), [path])
  useEffect(() => {
    if (!open) return
    const on = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [open])

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg">
      <div className={cx(BAR, 'flex h-[60px] items-center gap-8')}>
        <Link to="/" className="flex shrink-0 items-center gap-2.5 rounded-[4px]" aria-label={`${SITE.name}, home`}>
          <Logo size={22} />
          <span className="serif text-[20px] font-semibold leading-none text-ink">{SITE.name}</span>
        </Link>
        <nav aria-label="Main" className="hidden lg:block">
          <ul className="flex items-center gap-1">
            {NAV.map((n) => {
              const on = path === n.to
              return (
                <li key={n.to}>
                  <Link to={n.to} aria-current={on ? 'page' : undefined}
                    className={cx('rounded-[5px] px-2.5 py-1.5 text-[14px] transition-colors', on ? 'font-medium text-ink' : 'text-ink-3 hover:text-ink')}>
                    {n.label}
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <DataBadge />
          <PrimaryAction path={path} />
          <button type="button" className="-mr-2 inline-flex h-10 w-10 items-center justify-center rounded-[6px] text-ink-2 hover:bg-bg-2 lg:hidden"
            aria-expanded={open} aria-controls="mobile-nav" aria-label={open ? 'Close menu' : 'Open menu'} onClick={() => setOpen((o) => !o)}>
            {open ? <IconClose size={20} /> : <IconMenu size={20} />}
          </button>
        </div>
      </div>
      {open && (
        <nav id="mobile-nav" aria-label="Main" className="border-t border-line bg-bg lg:hidden">
          <ul className={cx(BAR, 'py-2')}>
            {[{ to: '/', label: 'Home' }, ...NAV].map((n) => (
              <li key={n.to} className="border-b border-line last:border-0">
                <Link to={n.to} aria-current={path === n.to ? 'page' : undefined}
                  className={cx('block py-3 text-[16px]', path === n.to ? 'font-medium text-ink' : 'text-ink-2')}>
                  {n.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </header>
  )
}

function FooterLink({ href, children }: { href: string; children: ReactNode }) {
  const external = /^https?:/.test(href)
  return (
    <a href={href} className="text-ink-2 hover:text-ink hover:underline" {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}>
      {children}
    </a>
  )
}

export function Footer() {
  const pending = `#${PENDING}`
  return (
    <footer className="mt-24 border-t border-line bg-bg">
      <div className={cx(BAR, 'grid gap-10 py-12 md:grid-cols-[2fr_1fr_1fr]')}>
        <div className="max-w-[420px]">
          <Link to="/" className="inline-flex items-center gap-2.5">
            <Logo size={18} />
            <span className="serif text-[18px] font-semibold leading-none">{SITE.name}</span>
          </Link>
          <p className="mt-3 text-[13.5px] leading-relaxed text-ink-3">
            A research demo of a gateway that tries AI-written trading strategies before they get capital. All markets are simulated. No real order is ever placed, and nothing here is investment advice.
          </p>
        </div>
        <div>
          <h2 className="mb-3 text-[13.5px] font-semibold text-ink">Pages</h2>
          <ul className="space-y-2 text-[14px]">
            {NAV.map((n) => (
              <li key={n.to}><FooterLink href={`#${n.to}`}>{n.label}</FooterLink></li>
            ))}
          </ul>
        </div>
        <div>
          <h2 className="mb-3 text-[13.5px] font-semibold text-ink">Project</h2>
          <ul className="space-y-2 text-[14px]">
            <li><FooterLink href={LINKS.paper || pending}>Paper</FooterLink></li>
            <li><FooterLink href={LINKS.code || pending}>Code and data</FooterLink></li>
            {LINKS.live && <li><FooterLink href={LINKS.live}>Live demo</FooterLink></li>}
            <li><FooterLink href="#/connect">Connect your agent (MCP)</FooterLink></li>
            <li><FooterLink href={LINKS.code ? LINKS.code : pending}>{LICENCE.name}</FooterLink></li>
          </ul>
        </div>
      </div>
      <div className="border-t border-line">
        <div className={cx(BAR, 'flex flex-col gap-1 py-5 text-[12.5px] text-ink-3 md:flex-row md:justify-between')}>
          <span>{AUTHORS.map((a) => a.name).join(', ')}</span>
          <span>The Web Conference 2027, demo track</span>
        </div>
      </div>
    </footer>
  )
}

export function Page({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return <div className={cx('mx-auto w-full px-5 pt-10 md:px-8 md:pt-12', wide ? 'max-w-[1520px]' : 'max-w-[1240px]')}>{children}</div>
}

import { useId, useRef, useState, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { IconCheck, IconChevron, IconCopy, IconExternal } from './Icons'

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')
export { cx }

type BtnVariant = 'primary' | 'outline' | 'ghost' | 'chip'
type BtnSize = 'sm' | 'md' | 'lg'

const BTN_BASE =
  'inline-flex items-center justify-center gap-2 select-none whitespace-nowrap rounded-[6px] font-medium transition-colors duration-150 disabled:opacity-45 disabled:pointer-events-none'
const BTN_SIZE: Record<BtnSize, string> = { sm: 'h-8 px-3 text-[13px]', md: 'h-9 px-3.5 text-[14px]', lg: 'h-10 px-4 text-[14.5px]' }
const btnVariant = (variant: BtnVariant, active?: boolean) =>
  ({
    primary: 'bg-accent text-accent-ink hover:bg-accent-2',
    outline: 'border border-line-2 bg-bg-1 text-ink hover:border-line-3 hover:bg-bg-2',
    ghost: 'text-ink-2 hover:text-ink hover:bg-bg-2',
    chip: cx('border text-[13px]', active ? 'border-accent bg-accent-wash text-ink' : 'border-line-2 bg-bg-1 text-ink-2 hover:text-ink hover:border-line-3'),
  })[variant]

export function buttonClass(variant: BtnVariant = 'outline', size: BtnSize = 'md', className?: string) {
  return cx(BTN_BASE, BTN_SIZE[size], btnVariant(variant), className)
}

export function Button({
  variant = 'outline',
  size = 'md',
  className,
  active,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: BtnSize; active?: boolean }) {
  return <button type="button" className={cx(BTN_BASE, BTN_SIZE[size], btnVariant(variant, active), className)} {...rest} />
}

/** A link that looks like a button. `external` opens in a new tab and shows a small arrow. */
export function LinkButton({
  variant = 'outline',
  size = 'md',
  className,
  external,
  children,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: BtnVariant; size?: BtnSize; external?: boolean }) {
  return (
    <a className={buttonClass(variant, size, className)} {...(external ? { target: '_blank', rel: 'noreferrer' } : {})} {...rest}>
      {children}
      {external && <IconExternal size={13} className="opacity-70" />}
    </a>
  )
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  size = 'md',
  className,
}: {
  value: T
  options: { value: T; label: ReactNode; title?: string }[]
  onChange: (v: T) => void
  label: string
  size?: 'sm' | 'md'
  className?: string
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const idx = options.findIndex((o) => o.value === value)
  return (
    <div role="radiogroup" aria-label={label} className={cx('inline-flex gap-[2px] rounded-[7px] border border-line-2 bg-bg-2 p-[2px]', className)}>
      {options.map((o, i) => {
        const on = o.value === value
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="radio"
            aria-checked={on}
            title={o.title}
            tabIndex={on || (idx < 0 && i === 0) ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => {
              const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
              if (!d) return
              e.preventDefault()
              const j = (i + d + options.length) % options.length
              onChange(options[j].value)
              refs.current[j]?.focus()
            }}
            className={cx(
              'whitespace-nowrap rounded-[5px] font-medium transition-colors duration-150',
              size === 'sm' ? 'h-7 px-2.5 text-[12.5px]' : 'h-8 px-3 text-[13px]',
              on ? 'bg-bg-1 text-ink shadow-[0_0_0_1px_var(--color-line-2)]' : 'text-ink-3 hover:text-ink',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

export function Select({
  value,
  onChange,
  options,
  label,
  className,
  hideLabel,
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string; disabled?: boolean; group?: string }[]
  label: string
  className?: string
  hideLabel?: boolean
}) {
  const id = useId()
  const groups = [...new Set(options.map((o) => o.group ?? ''))]
  return (
    <div className={cx('flex min-w-0 flex-col gap-1.5', className)}>
      <label htmlFor={id} className={cx('label', hideLabel && 'sr-only')}>
        {label}
      </label>
      <div className="relative">
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 w-full appearance-none truncate rounded-[6px] border border-line-2 bg-bg-1 pl-3 pr-9 text-[14px] text-ink outline-none transition-colors hover:border-line-3 focus-visible:border-accent"
        >
          {groups.map((g) =>
            g ? (
              <optgroup key={g} label={g}>
                {options.filter((o) => o.group === g).map((o) => (
                  <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
                ))}
              </optgroup>
            ) : (
              options.filter((o) => !o.group).map((o) => (
                <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>
              ))
            ),
          )}
        </select>
        <IconChevron className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-ink-3" />
      </div>
    </div>
  )
}

/** A small rectangular tag for a status word. Used sparingly. */
export function Badge({ children, tone = 'neutral', className, title }: { children: ReactNode; tone?: 'neutral' | 'accent' | 'open' | 'closed'; className?: string; title?: string }) {
  const tones = {
    neutral: 'border-line-2 text-ink-3',
    accent: 'border-accent/40 text-accent-2',
    open: 'border-line-2 text-ink-2',
    closed: 'border-line-2 text-ink-3',
  }
  return (
    <span title={title} className={cx('inline-flex items-center whitespace-nowrap rounded-[4px] border px-1.5 text-[11.5px] font-medium leading-[18px]', tones[tone], className)}>
      {children}
    </span>
  )
}

/** The plain caption under a chart: what it shows and how to read it. */
export function Caption({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cx('max-w-[80ch] text-[13px] leading-relaxed text-ink-3 text-pretty', className)}>{children}</p>
}

export function Stat({ label, value, sub, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={cx('min-w-0', className)}>
      <div className="label mb-1">{label}</div>
      <div className="num text-[26px] font-semibold leading-none tracking-[-0.01em] text-ink">{value}</div>
      {sub && <div className="mt-1.5 text-[12.5px] leading-snug text-ink-3">{sub}</div>}
    </div>
  )
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
        } catch {
          const ta = document.createElement('textarea')
          ta.value = text
          document.body.appendChild(ta)
          ta.select()
          document.execCommand('copy')
          ta.remove()
        }
        setDone(true)
        window.setTimeout(() => setDone(false), 1600)
      }}
      aria-label={done ? 'Copied' : label}
    >
      {done ? <IconCheck /> : <IconCopy />}
      <span>{done ? 'Copied' : label}</span>
    </Button>
  )
}

/** The top of a content page: a serif title and a short lead paragraph. */
export function PageHeader({ title, children, aside }: { title: ReactNode; children?: ReactNode; aside?: ReactNode }) {
  return (
    <header className="mb-10 flex flex-wrap items-end justify-between gap-x-10 gap-y-5 border-b border-line pb-8 md:mb-12">
      <div className="max-w-[720px]">
        <h1 tabIndex={-1} data-page-title className="serif text-[34px] font-semibold leading-[1.12] text-ink outline-none text-balance md:text-[42px]">
          {title}
        </h1>
        {children && <div className="mt-4 space-y-3 text-[16px] leading-[1.65] text-ink-2 text-pretty md:text-[17px]">{children}</div>}
      </div>
      {aside}
    </header>
  )
}

export function SectionTitle({ title, children, id }: { title: ReactNode; children?: ReactNode; id?: string }) {
  return (
    <div className="mb-5 max-w-[760px]" id={id}>
      <h2 className="serif text-[24px] font-semibold leading-tight text-ink md:text-[27px]">{title}</h2>
      {children && <div className="mt-2 text-[15px] leading-relaxed text-ink-2 text-pretty">{children}</div>}
    </div>
  )
}

export function Note({ children, tone = 'neutral', className }: { children: ReactNode; tone?: 'neutral' | 'warn'; className?: string }) {
  return (
    <div
      role={tone === 'warn' ? 'status' : undefined}
      className={cx(
        'rounded-[6px] border px-3.5 py-2.5 text-[13.5px] leading-snug',
        tone === 'warn' ? 'border-accent/35 bg-accent-wash text-accent-2' : 'border-line bg-bg-2 text-ink-2',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="text-[13.5px] text-ink-3" role="status">
      {label}…
    </div>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="mono inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[4px] border border-line-2 bg-bg-1 px-1 text-[10.5px] text-ink-2">
      {children}
    </kbd>
  )
}

/** A one-line note that the data on screen is hand-written sample data (development only). */
export function SampleNote({ show }: { show: boolean }) {
  if (!show) return null
  return <Note className="mb-6">Sample data. The real files are not in web/public/data yet, so this page shows hand-written fixtures.</Note>
}

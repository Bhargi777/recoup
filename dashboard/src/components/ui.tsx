import type { ReactNode } from 'react'

/** Small muted badge marking a value/section as not-yet-real placeholder content. */
export function PlaceholderBadge({ children = 'placeholder' }: { children?: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-amber-400">
      {children}
    </span>
  )
}

/** Standard "no backend wired yet" empty state, used across all five pages. */
export function NotWiredYet({ what }: { what: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed border-white/10 bg-white/[0.02] px-4 py-12 text-center">
      <p className="text-sm text-slate-400">{what} is not wired yet.</p>
      <p className="text-xs text-slate-600">No backend exists for this view in the Phase 8 scaffold.</p>
    </div>
  )
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4 border-b border-white/[0.06] pb-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-slate-50">{title}</h1>
        {subtitle && <p className="mt-1 text-[13px] leading-snug text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2 pt-0.5">{actions}</div>}
    </div>
  )
}

export function Panel({
  title,
  children,
  className = '',
  actions,
}: {
  title?: string
  children: ReactNode
  className?: string
  actions?: ReactNode
}) {
  return (
    <section
      className={`rounded-xl border border-white/[0.07] bg-white/[0.02] shadow-[0_1px_0_rgba(255,255,255,0.03)_inset] ${className}`}
    >
      {title && (
        <header className="flex items-center justify-between border-b border-white/[0.06] px-4 py-2.5">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

/** Small colored dot + label, for compact status indicators (e.g. kill switch, pass/fail). */
export function StatusDot({ tone, children }: { tone: 'ok' | 'warn' | 'danger' | 'neutral'; children: ReactNode }) {
  const dot = {
    ok: 'bg-emerald-400',
    warn: 'bg-amber-400',
    danger: 'bg-rose-400',
    neutral: 'bg-slate-500',
  }[tone]
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-300">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {children}
    </span>
  )
}

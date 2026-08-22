import type { ReactNode } from 'react'

/** Small muted badge marking a value/section as not-yet-real placeholder content. */
export function PlaceholderBadge({ children = 'placeholder' }: { children?: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-400">
      {children}
    </span>
  )
}

/** Standard "no backend wired yet" empty state, used across all five pages. */
export function NotWiredYet({ what }: { what: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-md border border-dashed border-slate-800 bg-slate-900/40 px-4 py-10 text-center">
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
    <div className="mb-4 flex items-start justify-between gap-4 border-b border-slate-800 pb-3">
      <div>
        <h1 className="text-base font-semibold text-slate-100">{title}</h1>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Panel({ title, children, className = '' }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-md border border-slate-800 bg-slate-900/40 ${className}`}>
      {title && (
        <header className="border-b border-slate-800 px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h2>
        </header>
      )}
      <div className="p-3">{children}</div>
    </section>
  )
}

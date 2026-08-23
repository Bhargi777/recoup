import { NavLink, Outlet } from 'react-router-dom'
import { KillSwitch } from './KillSwitch'

const NAV_ITEMS = [
  { to: '/pipeline', label: 'Pipeline' },
  { to: '/decisions', label: 'Decisions' },
  { to: '/ledger', label: 'Ledger' },
  { to: '/guardrails', label: 'Guardrails' },
  { to: '/metrics', label: 'Metrics' },
]

function navLinkClass(isActive: boolean) {
  return [
    'flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors',
    isActive
      ? 'bg-sky-500/10 text-sky-300'
      : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200',
  ].join(' ')
}

export function Layout() {
  return (
    <div className="flex h-full min-h-screen bg-[#0a0e17] text-slate-200">
      <aside className="flex w-56 shrink-0 flex-col border-r border-white/[0.06] bg-[#0d1119]/80">
        <div className="flex items-center gap-2 px-4 py-4">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-sky-500/15 text-[13px] font-bold text-sky-400">
            r
          </span>
          <div>
            <p className="text-[13px] font-semibold leading-none tracking-tight text-slate-100">recoup</p>
            <p className="mt-1 text-[10px] uppercase tracking-wider text-slate-600">Operator console</p>
          </div>
        </div>

        <nav className="flex flex-col gap-0.5 px-3 pt-2">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => navLinkClass(isActive)}>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto space-y-1 border-t border-white/[0.06] px-4 py-3">
          <p className="text-[10px] leading-relaxed text-slate-600">
            Phase 8 — wired to <span className="font-mono text-slate-500">core/api</span> (test mode)
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-white/[0.06] bg-[#0a0e17]/90 px-6 py-3 backdrop-blur">
          <p className="text-xs text-slate-500">Test-mode operator console</p>
          <KillSwitch />
        </header>
        <main className="min-w-0 flex-1 overflow-x-auto px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

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
    'block rounded px-2.5 py-1.5 text-xs font-medium transition',
    isActive ? 'bg-sky-500/15 text-sky-300' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200',
  ].join(' ')
}

export function Layout() {
  return (
    <div className="flex h-full min-h-screen bg-slate-950 text-slate-200">
      <aside className="flex w-48 shrink-0 flex-col border-r border-slate-800 bg-slate-900/60">
        <div className="border-b border-slate-800 px-3 py-3">
          <p className="text-sm font-semibold tracking-tight text-slate-100">recoup</p>
          <p className="text-[10px] uppercase tracking-wide text-slate-500">operator console</p>
        </div>
        <nav className="flex flex-col gap-0.5 p-2">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => navLinkClass(isActive)}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto border-t border-slate-800 p-2 text-[10px] text-slate-600">
          Phase 8 scaffold — no backend wired
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-800 bg-slate-950/80 px-4 py-2 backdrop-blur">
          <p className="text-xs text-slate-500">Test-mode operator console</p>
          <KillSwitch />
        </header>
        <main className="min-w-0 flex-1 overflow-x-auto p-4">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

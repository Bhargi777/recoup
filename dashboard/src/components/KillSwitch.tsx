import { useEffect, useState } from 'react'
import { apiGet, apiPost, ApiError } from '../lib/api'

interface KillSwitchState {
  active: boolean
}

/**
 * Global kill switch control. Wired to the real core/api/kill_switch.py
 * endpoints, which themselves call the real core.policy.activate_kill_switch
 * / deactivate_kill_switch (append-only KILL_SWITCH_ACTIVATED /
 * KILL_SWITCH_DEACTIVATED ledger events - no mutable "is_active" row exists,
 * per core/policy/kill_switch.py's module docstring). GET replays that
 * ledger on every load, so this control always reflects real, current state.
 */
export function KillSwitch() {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    apiGet<KillSwitchState>('/api/kill-switch')
      .then((s) => {
        if (!cancelled) setActive(s.active)
      })
      .catch(() => {
        if (!cancelled) setActive(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      const result = await apiPost<KillSwitchState>('/api/kill-switch', {
        action: active ? 'off' : 'on',
        reason: 'toggled from operator dashboard',
      })
      setActive(result.active)
      setOpen(false)
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : String(err))
    } finally {
      setBusy(false)
    }
  }

  const label = active === null ? 'kill switch / unknown' : active ? 'ACTIVE — all actions blocked' : 'inactive'

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`flex items-center gap-1.5 rounded border px-2.5 py-1 text-xs font-medium transition ${
          active
            ? 'border-rose-500 bg-rose-500/20 text-rose-300 hover:bg-rose-500/30'
            : 'border-rose-500/40 bg-rose-500/10 text-rose-400 hover:bg-rose-500/20'
        }`}
        title="Real control — calls core.policy.activate_kill_switch / deactivate_kill_switch"
      >
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${active ? 'bg-rose-400 animate-pulse' : 'bg-rose-500'}`}
        />
        Kill switch
        <span className="text-[10px] font-normal text-rose-500/70">{label}</span>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          role="dialog"
          aria-modal="true"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-sm rounded-md border border-slate-800 bg-slate-900 p-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-sm font-semibold text-slate-100">
              {active ? 'Deactivate kill switch?' : 'Activate emergency kill switch?'}
            </h2>
            <p className="mt-2 text-xs leading-relaxed text-slate-400">
              This calls the real policy engine (
              <code className="font-mono text-slate-300">core.policy.{active ? 'deactivate' : 'activate'}_kill_switch</code>
              ). {active
                ? 'Money actions will be allowed to pass the kill_switch guardrail check again.'
                : 'Every subsequent policy gate evaluation will BLOCK on the kill_switch check until this is turned off, and the toggle itself is recorded as an immutable ledger event.'}
            </p>
            {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded border border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={toggle}
                disabled={busy}
                className="rounded border border-rose-500/60 bg-rose-500/20 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/30 disabled:opacity-50"
              >
                {busy ? 'Working…' : active ? 'Deactivate' : 'Activate'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

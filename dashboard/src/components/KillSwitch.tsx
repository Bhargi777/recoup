import { useState } from 'react'

/**
 * Global kill switch control from the CLAUDE.md brief.
 *
 * This is a demo/inactive stub: it is NOT wired to core/policy (which does
 * not exist yet). Clicking it only opens a confirm dialog that explains
 * that, and does nothing else. It must never be made to silently "work".
 */
export function KillSwitch() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded border border-rose-500/40 bg-rose-500/10 px-2.5 py-1 text-xs font-medium text-rose-400 transition hover:bg-rose-500/20"
        title="Demo control — not wired to a real policy engine"
      >
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-rose-500" />
        Kill switch
        <span className="text-[10px] font-normal text-rose-500/70">inactive / demo</span>
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
            <h2 className="text-sm font-semibold text-slate-100">Kill switch — not functional</h2>
            <p className="mt-2 text-xs leading-relaxed text-slate-400">
              This is a scaffold stub. There is no policy engine or action executor for it to stop yet
              (<code className="font-mono text-slate-300">core/policy</code> and{' '}
              <code className="font-mono text-slate-300">core/act</code> do not exist in this branch). When
              those land, this control will call a real endpoint that halts all money actions immediately and
              logs the event to the ledger. For now it does nothing.
            </p>
            <div className="mt-4 flex justify-end">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded border border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

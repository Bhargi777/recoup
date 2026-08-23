import { useEffect, useState } from 'react'
import { PageHeader, Panel } from '../components/ui'
import { apiGet, ApiError } from '../lib/api'

interface GuardrailBlock {
  sequence_num: number
  timestamp_utc: string
  aggregate_id: string
  idempotency_key: string | null
  check_name: string
  reason: string
  root_cause: string | null
  cohort: string | null
  action_type: string | null
}

interface GuardrailsResponse {
  blocked_check_events: number
  distinct_blocked_actions: number
  reasons_by_check: Record<string, number>
  blocks: GuardrailBlock[]
}

export function Guardrails() {
  const [data, setData] = useState<GuardrailsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    apiGet<GuardrailsResponse>('/api/guardrails')
      .then((body) => {
        if (!cancelled) setData(body)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? `${err.status}: ${err.message}` : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <PageHeader
        title="Guardrail blocks"
        subtitle="Actions the policy gate correctly refused to execute, and why. A block here is the gate working as designed - not a violation. Zero guardrail VIOLATIONS (a bypass, a double-charge, a cap breach) is proven separately by the Phase 7 chaos scenarios (see REPORT.md)."
        actions={
          data ? (
            <span className="font-mono text-xs text-amber-400">
              {data.distinct_blocked_actions} blocked actions
            </span>
          ) : undefined
        }
      />

      {error && (
        <Panel className="mb-3 border-rose-500/40">
          <p className="text-xs text-rose-400">Failed to load guardrails: {error}</p>
        </Panel>
      )}

      {data && (
        <Panel title="Blocks by check" className="mb-3">
          {Object.keys(data.reasons_by_check).length === 0 ? (
            <p className="text-xs text-slate-600">
              No blocks recorded yet — run <code className="font-mono">recoup run-batch</code>.
            </p>
          ) : (
            <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {Object.entries(data.reasons_by_check).map(([check, count]) => (
                <li key={check} className="rounded border border-slate-800 bg-slate-950/40 p-2">
                  <p className="font-mono text-[11px] text-sky-400">{check}</p>
                  <p className="text-xs font-medium text-slate-200">{count} blocked</p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}

      <Panel title="Blocked actions (most recent first)">
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr className="text-slate-500">
                <th className="border-b border-slate-800 pb-1.5 pr-3 font-medium">Aggregate</th>
                <th className="border-b border-slate-800 pb-1.5 pr-3 font-medium">Check</th>
                <th className="border-b border-slate-800 pb-1.5 pr-3 font-medium">Root cause</th>
                <th className="border-b border-slate-800 pb-1.5 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody>
              {!data && !error && (
                <tr>
                  <td colSpan={4} className="pt-3 pb-1 text-slate-600">
                    Loading real guardrail-block data...
                  </td>
                </tr>
              )}
              {data?.blocks.map((b) => (
                <tr key={`${b.sequence_num}`} className="border-b border-slate-900">
                  <td className="py-1 pr-3 font-mono text-slate-300">{b.aggregate_id}</td>
                  <td className="py-1 pr-3 font-mono text-amber-400">{b.check_name}</td>
                  <td className="py-1 pr-3 text-slate-300">{b.root_cause ?? '—'}</td>
                  <td className="py-1 text-slate-400">{b.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}

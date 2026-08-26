import { useEffect, useState } from 'react'
import { PageHeader, Panel } from '../components/ui'
import { apiGet, ApiError } from '../lib/api'

interface Decision {
  sequence_num: number
  event_id: string
  timestamp_utc: string
  aggregate_id: string
  idempotency_key: string | null
  root_cause: string | null
  cohort: string | null
  action_type: string | null
  status: string
  reason: string
  why: string
}

interface DecisionsResponse {
  total_available: number
  returned: number
  decisions: Decision[]
}

export function Decisions() {
  const [data, setData] = useState<DecisionsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    apiGet<DecisionsResponse>('/api/decisions?limit=100')
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
        title="Live decision feed"
        subtitle="Every diagnose -> policy-gate decision (POLICY_GATE_DECISION ledger events), with a plain-English reason derived from the gate's own reason string."
        actions={
          data ? (
            <span className="font-mono text-xs text-slate-500">
              {data.returned} of {data.total_available}
            </span>
          ) : undefined
        }
      />

      {error && (
        <Panel className="mb-3 border-rose-500/40">
          <p className="text-xs text-rose-400">Failed to load decisions: {error}</p>
        </Panel>
      )}

      {!data && !error && <Panel>Loading real decision feed...</Panel>}

      {data && data.decisions.length === 0 && (
        <Panel>
          <p className="text-xs text-slate-600">
            No POLICY_GATE_DECISION events yet — run <code className="font-mono">recoup run-batch</code>.
          </p>
        </Panel>
      )}

      <div className="flex flex-col gap-2.5">
        {data?.decisions.map((d) => (
          <Panel key={d.event_id} className="transition-colors hover:border-white/[0.12]">
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-4">
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-slate-500">Aggregate / customer</dt>
                <dd className="mt-1 font-mono text-slate-300">{d.aggregate_id}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-slate-500">Diagnosed cause</dt>
                <dd className="mt-1 font-mono text-slate-300">{d.root_cause ?? '—'}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-slate-500">Chosen action</dt>
                <dd className="mt-1 font-mono text-slate-300">{d.action_type ?? '—'}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-slate-500">Policy gate result</dt>
                <dd className="mt-1">
                  <span
                    className={`inline-flex items-center gap-1.5 font-mono text-xs ${
                      d.status === 'ALLOW' ? 'text-emerald-400' : 'text-amber-400'
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        d.status === 'ALLOW' ? 'bg-emerald-400' : 'bg-amber-400'
                      }`}
                    />
                    {d.status}
                  </span>
                </dd>
              </div>
            </div>
            <div className="mt-3 rounded-lg border border-white/[0.05] bg-black/20 p-3">
              <p className="text-[10px] font-medium uppercase tracking-wider text-slate-500">Why</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-400">{d.why}</p>
            </div>
          </Panel>
        ))}
      </div>
    </div>
  )
}

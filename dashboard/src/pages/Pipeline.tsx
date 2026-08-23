import { useEffect, useState } from 'react'
import { COHORTS } from '../constants/cohorts'
import { PageHeader, Panel } from '../components/ui'
import { apiGet, ApiError } from '../lib/api'

interface PipelineRecord {
  id: string
  cohort: string
  root_cause: string | null
  diagnosis_method: string | null
  amount_inr: number
  customer_id: string
  created_at: string
  held_out: boolean
  source: string
  error_code: string | null
  error_reason: string | null
}

interface PipelineCohort {
  cohort: string
  count: number
  records: PipelineRecord[]
}

interface PipelineResponse {
  total: number
  cohorts: PipelineCohort[]
}

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

export function Pipeline() {
  const [data, setData] = useState<PipelineResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    apiGet<PipelineResponse>('/api/pipeline')
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

  const byCohort = new Map((data?.cohorts ?? []).map((c) => [c.cohort, c]))

  return (
    <div>
      <PageHeader
        title="At-risk pipeline"
        subtitle="Customers grouped by cohort, from core.ingest.synthetic.AtRiskRecord (source: synthetic)."
        actions={
          data ? (
            <span className="font-mono text-xs text-slate-500">{data.total} records</span>
          ) : undefined
        }
      />

      {error && (
        <Panel className="mb-3 border-rose-500/40">
          <p className="text-xs text-rose-400">Failed to load pipeline: {error}</p>
          <p className="mt-1 text-[11px] text-slate-500">
            Is the API running? See dashboard/.env.example for VITE_API_BASE_URL.
          </p>
        </Panel>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {COHORTS.map((cohort) => {
          const rows = byCohort.get(cohort.id)?.records ?? []
          return (
            <Panel key={cohort.id} title={`${cohort.label} (${rows.length})`}>
              <p className="mb-2 text-xs text-slate-500">{cohort.description}</p>
              <div className="max-h-72 overflow-y-auto">
                <table className="w-full border-collapse text-left text-xs">
                  <thead>
                    <tr className="text-slate-500">
                      <th className="border-b border-slate-800 pb-1.5 pr-2 font-medium">Customer</th>
                      <th className="border-b border-slate-800 pb-1.5 pr-2 font-medium">Root cause</th>
                      <th className="border-b border-slate-800 pb-1.5 pr-2 font-medium">Amount</th>
                      <th className="border-b border-slate-800 pb-1.5 font-medium">Held out</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!data && !error && (
                      <tr>
                        <td colSpan={4} className="pt-3 pb-1 text-slate-600">
                          Loading real pipeline data...
                        </td>
                      </tr>
                    )}
                    {data && rows.length === 0 && (
                      <tr>
                        <td colSpan={4} className="pt-3 pb-1 text-slate-600">
                          No rows yet — run <code className="font-mono">recoup generate-synthetic-data</code>.
                        </td>
                      </tr>
                    )}
                    {rows.map((r) => (
                      <tr key={r.id} className="border-b border-slate-900">
                        <td className="py-1 pr-2 font-mono text-slate-300">{r.customer_id}</td>
                        <td className="py-1 pr-2 text-slate-300">
                          {r.root_cause ?? <span className="text-slate-600">not diagnosed</span>}
                        </td>
                        <td className="py-1 pr-2 font-mono text-slate-300">{inr.format(r.amount_inr)}</td>
                        <td className="py-1 text-slate-400">{r.held_out ? 'yes' : 'no'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )
        })}
      </div>
    </div>
  )
}

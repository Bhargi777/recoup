import { useEffect, useState } from 'react'
import { PageHeader, Panel } from '../components/ui'
import { apiGet, ApiError } from '../lib/api'

interface WilsonInterval {
  point_estimate: number
  lower: number
  upper: number
  n: number
  k: number
}

interface DiagnosisReport {
  total: number
  macro_precision: number
  macro_recall: number
  macro_f1: number
  abstain_rate: number
  coverage: Record<string, number>
  confusion_matrix: Record<string, Record<string, number>>
}

interface UpliftBlock {
  simulated: boolean
  qualifier: string
  treatment: WilsonInterval
  control: WilsonInterval
  uplift: number
}

interface BatchRun {
  mode: string
  total_records: number
  elapsed_seconds: number
  blocked_count: number
  blocked_reasons: Record<string, number>
  executed_action_counts: Record<string, number>
}

interface ExceptionItem {
  sequence_num: number
  aggregate_id: string
  kind: string
  reason: string
}

interface MetricsResponse {
  diagnosis: DiagnosisReport
  uplift: UpliftBlock
  batch_run: BatchRun
  exceptions: { total: number; items: ExceptionItem[] }
}

function MetricStat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 font-mono text-xl text-slate-100">{value}</p>
      {sub && <p className="mt-0.5 text-[10px] text-slate-500">{sub}</p>}
    </div>
  )
}

const pct = (x: number) => `${(x * 100).toFixed(1)}%`

export function Metrics() {
  const [data, setData] = useState<MetricsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    apiGet<MetricsResponse>('/api/metrics')
      .then((body) => {
        if (!cancelled) setData(body)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? `${err.status}: ${err.message}` : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <PageHeader
        title="Metrics"
        subtitle="Real diagnosis metrics (core.eval.diagnosis_eval) and uplift + Wilson CI (core.eval.batch_runner). This endpoint runs the real pipeline live and can take up to a minute."
      />

      {loading && (
        <Panel className="mb-3">
          <p className="text-xs text-slate-400">
            Running the real diagnosis + batch pipeline (recoup eval-diagnosis + run-batch equivalent) — this can
            take up to a minute against 600 synthetic records...
          </p>
        </Panel>
      )}

      {error && (
        <Panel className="mb-3 border-rose-500/40">
          <p className="text-xs text-rose-400">Failed to load metrics: {error}</p>
        </Panel>
      )}

      {data && (
        <>
          <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MetricStat label="Diagnosis macro F1" value={data.diagnosis.macro_f1.toFixed(3)} sub={`n=${data.diagnosis.total} held-out`} />
            <MetricStat label="Abstain rate" value={pct(data.diagnosis.abstain_rate)} sub="routed to human queue" />
            <MetricStat
              label="[SIMULATED] uplift"
              value={`${data.uplift.uplift >= 0 ? '+' : ''}${pct(data.uplift.uplift)}`}
              sub={`treatment n=${data.uplift.treatment.n}, control n=${data.uplift.control.n}`}
            />
            <MetricStat label="Open exceptions" value={String(data.exceptions.total)} sub="ABSTAIN + escalated" />
          </div>

          <Panel title="[SIMULATED] Recovery uplift vs. control" className="mb-3">
            <p className="mb-2 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-300">
              [SIMULATED] {data.uplift.qualifier}
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-500">Treatment recovery rate</p>
                <p className="font-mono text-slate-200">
                  {pct(data.uplift.treatment.point_estimate)} (95% CI {pct(data.uplift.treatment.lower)}-
                  {pct(data.uplift.treatment.upper)}, n={data.uplift.treatment.n})
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-500">Control recovery rate</p>
                <p className="font-mono text-slate-200">
                  {pct(data.uplift.control.point_estimate)} (95% CI {pct(data.uplift.control.lower)}-
                  {pct(data.uplift.control.upper)}, n={data.uplift.control.n})
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide text-slate-500">Batch run</p>
                <p className="font-mono text-slate-200">
                  {data.batch_run.total_records} records, {data.batch_run.mode}, {data.batch_run.elapsed_seconds.toFixed(1)}s
                </p>
              </div>
            </div>
          </Panel>

          <Panel title="Guardrail: correctly blocked actions (not violations)" className="mb-3">
            {Object.keys(data.batch_run.blocked_reasons).length === 0 ? (
              <p className="text-xs text-slate-500">
                {data.batch_run.blocked_count} blocked this run — see the Guardrails page for the running total
                across all recorded decisions.
              </p>
            ) : (
              <ul className="text-xs text-slate-300">
                {Object.entries(data.batch_run.blocked_reasons).map(([reason, count]) => (
                  <li key={reason}>
                    <span className="font-mono text-amber-400">{reason}</span>: {count}
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Exception list (ABSTAIN + escalated to human)">
            {data.exceptions.items.length === 0 ? (
              <p className="text-xs text-slate-600">
                No exceptions in this run — the deterministic mapper resolved every record.
              </p>
            ) : (
              <div className="max-h-64 overflow-y-auto">
                <table className="w-full border-collapse text-left text-xs">
                  <thead>
                    <tr className="text-slate-500">
                      <th className="border-b border-slate-800 pb-1.5 pr-3 font-medium">Aggregate</th>
                      <th className="border-b border-slate-800 pb-1.5 pr-3 font-medium">Kind</th>
                      <th className="border-b border-slate-800 pb-1.5 font-medium">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.exceptions.items.map((e) => (
                      <tr key={`${e.sequence_num}`} className="border-b border-slate-900">
                        <td className="py-1 pr-3 font-mono text-slate-300">{e.aggregate_id}</td>
                        <td className="py-1 pr-3 text-slate-400">{e.kind}</td>
                        <td className="py-1 text-slate-400">{e.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  )
}

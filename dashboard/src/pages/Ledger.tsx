import { useEffect, useState } from 'react'
import { PageHeader, Panel } from '../components/ui'
import { apiGet, ApiError } from '../lib/api'

// Column set mirrors core/ledger/models.py::LedgerEvent exactly.
const LEDGER_COLUMNS = [
  'sequence_num',
  'event_id',
  'timestamp_utc',
  'aggregate_id',
  'event_type',
  'previous_hash',
  'current_hash',
] as const

interface LedgerEventRow {
  sequence_num: number
  event_id: string
  timestamp_utc: string
  aggregate_id: string
  event_type: string
  previous_hash: string
  current_hash: string
}

interface LedgerResponse {
  total: number
  limit: number
  offset: number
  events: LedgerEventRow[]
}

interface VerifyResponse {
  ok: boolean
  events_checked: number
  first_bad_sequence: number | null
  errors: string[]
}

const PAGE_SIZE = 50

function shortHash(hash: string): string {
  return hash === '0'.repeat(64) ? 'GENESIS' : `${hash.slice(0, 10)}…`
}

export function Ledger() {
  const [data, setData] = useState<LedgerResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [verify, setVerify] = useState<VerifyResponse | null>(null)
  const [verifying, setVerifying] = useState(false)

  useEffect(() => {
    let cancelled = false
    apiGet<LedgerResponse>(`/api/ledger?limit=${PAGE_SIZE}&offset=${offset}`)
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
  }, [offset])

  async function runVerify() {
    setVerifying(true)
    try {
      const result = await apiGet<VerifyResponse>('/api/ledger/verify')
      setVerify(result)
    } catch (err) {
      setVerify({
        ok: false,
        events_checked: 0,
        first_bad_sequence: null,
        errors: [err instanceof ApiError ? `${err.status}: ${err.message}` : String(err)],
      })
    } finally {
      setVerifying(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Ledger explorer"
        subtitle="Hash-chained append-only event log (core/ledger). Columns match LedgerEvent."
        actions={
          <button
            type="button"
            onClick={runVerify}
            disabled={verifying}
            className="rounded border border-sky-500/40 bg-sky-500/10 px-2.5 py-1 text-xs font-medium text-sky-300 transition hover:bg-sky-500/20 disabled:opacity-50"
          >
            {verifying ? 'Verifying…' : 'Verify chain'}
          </button>
        }
      />

      {verify && (
        <Panel
          className={`mb-3 ${verify.ok ? 'border-emerald-500/40' : 'border-rose-500/40'}`}
        >
          <p className={`text-xs font-medium ${verify.ok ? 'text-emerald-400' : 'text-rose-400'}`}>
            {verify.ok
              ? `Chain OK: ${verify.events_checked} events verified, no tampering detected.`
              : `Chain BROKEN at sequence ${verify.first_bad_sequence} (${verify.events_checked} events checked).`}
          </p>
          {!verify.ok && (
            <ul className="mt-1 list-disc pl-4 text-[11px] text-rose-300">
              {verify.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
        </Panel>
      )}

      {error && (
        <Panel className="mb-3 border-rose-500/40">
          <p className="text-xs text-rose-400">Failed to load ledger: {error}</p>
        </Panel>
      )}

      <Panel>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] border-collapse text-left text-xs">
            <thead>
              <tr className="text-slate-500">
                {LEDGER_COLUMNS.map((col) => (
                  <th key={col} className="border-b border-slate-800 pb-1.5 pr-4 font-mono font-medium">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!data && !error && (
                <tr>
                  <td colSpan={LEDGER_COLUMNS.length} className="pt-3 pb-1 text-slate-600">
                    Loading real ledger events...
                  </td>
                </tr>
              )}
              {data && data.events.length === 0 && (
                <tr>
                  <td colSpan={LEDGER_COLUMNS.length} className="pt-3 pb-1 text-slate-600">
                    No events yet — every command in the README's demo script writes ledger events.
                  </td>
                </tr>
              )}
              {data?.events.map((e) => (
                <tr key={e.event_id} className="border-b border-slate-900">
                  <td className="py-1 pr-4 font-mono text-slate-400">{e.sequence_num}</td>
                  <td className="py-1 pr-4 font-mono text-slate-500">{e.event_id}</td>
                  <td className="py-1 pr-4 font-mono text-slate-500">{e.timestamp_utc}</td>
                  <td className="py-1 pr-4 font-mono text-slate-300">{e.aggregate_id}</td>
                  <td className="py-1 pr-4 font-mono text-sky-300">{e.event_type}</td>
                  <td className="py-1 pr-4 font-mono text-slate-600" title={e.previous_hash}>
                    {shortHash(e.previous_hash)}
                  </td>
                  <td className="py-1 font-mono text-slate-600" title={e.current_hash}>
                    {shortHash(e.current_hash)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {data && data.total > 0 && (
          <div className="mt-3 flex items-center justify-between text-[11px] text-slate-500">
            <span>
              Showing {offset + 1}-{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="rounded border border-slate-700 px-2 py-1 disabled:opacity-40"
              >
                Prev
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="rounded border border-slate-700 px-2 py-1 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </Panel>
    </div>
  )
}

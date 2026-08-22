import { NotWiredYet, PageHeader, Panel, PlaceholderBadge } from '../components/ui'

// Column set mirrors core/ledger/models.py::LedgerEvent exactly, so the UI
// contract is right even though there is no API yet to populate rows.
const LEDGER_COLUMNS = [
  'sequence_num',
  'event_id',
  'timestamp_utc',
  'aggregate_id',
  'event_type',
  'previous_hash',
  'current_hash',
] as const

export function Ledger() {
  return (
    <div>
      <PageHeader
        title="Ledger explorer"
        subtitle="Hash-chained append-only event log (core/ledger). Columns match LedgerEvent."
        actions={<PlaceholderBadge>UI shell only</PlaceholderBadge>}
      />

      <Panel>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-left text-xs">
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
              <tr>
                <td colSpan={LEDGER_COLUMNS.length} className="pt-3 pb-1 text-slate-600">
                  No events — no API endpoint exposes core/ledger yet. Rows will be fetched from a future
                  `/api/ledger` route and support replay verification once wired.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="mt-3">
        <NotWiredYet what="The ledger API and replay view" />
      </div>
    </div>
  )
}

import { NotWiredYet, PageHeader, Panel, PlaceholderBadge } from '../components/ui'

const DECISION_CARD_SHAPE = [
  { label: 'Customer / aggregate_id', value: '—' },
  { label: 'Diagnosed cause', value: '—' },
  { label: 'Chosen action', value: '—' },
  { label: 'Policy gate result', value: '—' },
]

export function Decisions() {
  return (
    <div>
      <PageHeader
        title="Live decision feed"
        subtitle="Every diagnose → policy-gate → act decision, with a plain-English reason."
        actions={<PlaceholderBadge>UI shell only</PlaceholderBadge>}
      />

      <Panel title="Example decision card layout" className="mb-3">
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-4">
          {DECISION_CARD_SHAPE.map((field) => (
            <div key={field.label}>
              <dt className="text-slate-500">{field.label}</dt>
              <dd className="font-mono text-slate-300">{field.value}</dd>
            </div>
          ))}
        </div>
        <div className="mt-3 rounded border border-slate-800 bg-slate-950/60 p-2">
          <p className="text-[10px] uppercase tracking-wide text-slate-500">Why</p>
          <p className="mt-1 text-xs text-slate-600">
            Plain-English explanation will render here once core/diagnose and core/policy exist.
          </p>
        </div>
      </Panel>

      <NotWiredYet what="The live decision feed" />
    </div>
  )
}

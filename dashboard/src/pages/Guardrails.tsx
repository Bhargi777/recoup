import { NotWiredYet, PageHeader, Panel, PlaceholderBadge } from '../components/ui'

const GUARDRAIL_TYPES = [
  { id: 'budget_cap', label: 'Budget cap', description: 'Global or per-cohort spend ceiling exceeded.' },
  { id: 'quiet_hours', label: 'Quiet hours', description: 'Outside the 09:00-21:00 local contact window.' },
  { id: 'attempt_cap', label: 'Max attempts', description: 'Per-customer/cohort attempt threshold reached.' },
  {
    id: 'mandate_rules',
    label: 'RBI / NPCI mandate rules',
    description: '24hr pre-debit notice or AutoPay non-peak window violated.',
  },
  { id: 'kill_switch', label: 'Kill switch', description: 'Global kill switch was active at gate time.' },
]

export function Guardrails() {
  return (
    <div>
      <PageHeader
        title="Guardrail blocks"
        subtitle="Actions the policy gate refused to execute, and why."
        actions={<PlaceholderBadge>UI shell only</PlaceholderBadge>}
      />

      <Panel title="Guardrail types" className="mb-3">
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {GUARDRAIL_TYPES.map((g) => (
            <li key={g.id} className="rounded border border-slate-800 bg-slate-950/40 p-2">
              <p className="font-mono text-[11px] text-sky-400">{g.id}</p>
              <p className="text-xs font-medium text-slate-200">{g.label}</p>
              <p className="mt-0.5 text-[11px] text-slate-500">{g.description}</p>
            </li>
          ))}
        </ul>
      </Panel>

      <NotWiredYet what="The guardrail-blocks panel (requires core/policy)" />
    </div>
  )
}

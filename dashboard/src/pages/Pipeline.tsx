import { COHORTS } from '../constants/cohorts'
import { NotWiredYet, PageHeader, Panel, PlaceholderBadge } from '../components/ui'

export function Pipeline() {
  return (
    <div>
      <PageHeader
        title="At-risk pipeline"
        subtitle="Customers grouped by cohort, ordered by recovery priority (once wired)."
        actions={<PlaceholderBadge>UI shell only</PlaceholderBadge>}
      />

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {COHORTS.map((cohort) => (
          <Panel key={cohort.id} title={cohort.label}>
            <p className="mb-2 text-xs text-slate-500">{cohort.description}</p>
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="text-slate-500">
                  <th className="border-b border-slate-800 pb-1.5 pr-2 font-medium">Customer</th>
                  <th className="border-b border-slate-800 pb-1.5 pr-2 font-medium">Amount at risk</th>
                  <th className="border-b border-slate-800 pb-1.5 font-medium">Age</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={3} className="pt-3 pb-1 text-slate-600">
                    No rows — ingest and diagnose pipelines are not wired yet.
                  </td>
                </tr>
              </tbody>
            </table>
          </Panel>
        ))}
      </div>

      <div className="mt-3">
        <NotWiredYet what="Cohort scoring and ranking" />
      </div>
    </div>
  )
}

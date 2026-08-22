import { NotWiredYet, PageHeader, Panel, PlaceholderBadge } from '../components/ui'

function MetricStat({ label }: { label: string }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 font-mono text-xl text-slate-600">—</p>
      <p className="mt-0.5 text-[10px] text-slate-600">not yet wired</p>
    </div>
  )
}

export function Metrics() {
  return (
    <div>
      <PageHeader
        title="Metrics"
        subtitle="Uplift + confidence interval, cost per rupee recovered, exception list."
        actions={<PlaceholderBadge>UI shell only</PlaceholderBadge>}
      />

      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricStat label="Uplift vs. control" />
        <MetricStat label="Wilson 95% CI" />
        <MetricStat label="Cost per ₹ recovered" />
        <MetricStat label="Open exceptions" />
      </div>

      <Panel title="Exception list">
        <p className="text-xs text-slate-600">
          No held-out evaluation exists yet — core/experiment and core/eval have not been built. This table
          will list ABSTAIN and guardrail-block cases routed to human review.
        </p>
      </Panel>

      <div className="mt-3">
        <NotWiredYet what="Uplift calculation and the metrics report (requires core/experiment, core/eval)" />
      </div>
    </div>
  )
}

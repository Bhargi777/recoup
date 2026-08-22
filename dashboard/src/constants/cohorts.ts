// The four at-risk cohorts named in CLAUDE.md's dashboard brief.
// No backend exists yet (Phase 8 scaffold) — this is UI-only structure,
// not a claim about real data.
export const COHORTS = [
  {
    id: 'checkout_failures',
    label: 'Checkout failures',
    description: 'Payment attempts that failed at checkout before completion.',
  },
  {
    id: 'abandonment',
    label: 'Abandonment',
    description: 'Sessions or carts abandoned before payment was attempted.',
  },
  {
    id: 'mandate_failures',
    label: 'Subscription / mandate failures',
    description: 'Recurring e-mandate or AutoPay debits that failed.',
  },
  {
    id: 'overdue_invoices',
    label: 'Overdue invoices',
    description: 'Invoices past their due date with no successful payment.',
  },
] as const

export type CohortId = (typeof COHORTS)[number]['id']

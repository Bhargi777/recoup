// Cohort ids match core/ingest/synthetic.py's COHORTS exactly (the API
// groups /api/pipeline results by these literal strings) - not the
// dashboard's own naming, so a record's cohort field always round-trips.
export const COHORTS = [
  {
    id: 'one_time_checkout_failure',
    label: 'Checkout failures',
    description: 'Payment attempts that failed at checkout before completion.',
  },
  {
    id: 'checkout_abandonment',
    label: 'Abandonment',
    description: 'Sessions or carts abandoned before payment was attempted.',
  },
  {
    id: 'subscription_mandate_failure',
    label: 'Subscription / mandate failures',
    description: 'Recurring e-mandate or AutoPay debits that failed.',
  },
  {
    id: 'overdue_b2b_invoice',
    label: 'Overdue invoices',
    description: 'Invoices past their due date with no successful payment.',
  },
] as const

export type CohortId = (typeof COHORTS)[number]['id']

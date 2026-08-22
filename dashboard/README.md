# recoup dashboard

React + Vite + TypeScript + Tailwind CSS operator console for `recoup`.

## Status: Phase 8 SCAFFOLD

This is project setup and static layout only. **No backend is wired.** There
is no API server for this dashboard to call yet — `core/policy`, `core/act`,
`core/diagnose`, `core/experiment`, and `core/eval` do not exist as of this
branch, and there is no HTTP layer exposing `core/ledger` either.

Every number and list on screen is either:

- an explicit **`placeholder`** badge plus an obviously-fake value (`—`), or
- an empty state that says **"not wired yet"**.

Nothing here is a real metric. Do not read anything on these pages as live
data. Real API integration is future work (a later phase).

## Run it

```bash
npm install
npm run dev
```

Then open the printed local URL. Five routes are available from the sidebar:

- `/pipeline` — at-risk pipeline grouped by the four cohorts (checkout
  failures, abandonment, subscription/mandate failures, overdue invoices)
- `/decisions` — live decision feed shape (diagnosis, action, policy gate
  result, plain-English "why")
- `/ledger` — ledger explorer; columns match `core/ledger/models.py`'s
  `LedgerEvent` exactly (`sequence_num`, `event_id`, `timestamp_utc`,
  `aggregate_id`, `event_type`, `previous_hash`, `current_hash`)
- `/guardrails` — guardrail-block panel (budget cap, quiet hours, attempt
  cap, RBI/NPCI mandate rules, kill switch)
- `/metrics` — uplift + CI, cost per rupee recovered, exception list

The top bar also has a **kill switch** control. It is a deliberately inert
demo stub — clicking it opens a dialog explaining that it isn't connected to
anything real yet. Do not wire it to a real endpoint without also wiring the
guardrail/audit-ledger invariants described in `CLAUDE.md`.

## Build / lint

```bash
npm run build   # tsc -b && vite build
npm run lint    # oxlint
```

## Stack notes

- Vite scaffolded with the `react-ts` template.
- Tailwind CSS v4 via `@tailwindcss/vite` (no separate `tailwind.config.js`
  needed — configuration lives in `src/index.css`).
- `react-router-dom` for the five routes, with a shared `Layout` (sidebar
  nav + top bar) so all pages share one visual system.
- Dense, small-type-scale layout deliberately, since this is an operator
  console, not a marketing page.

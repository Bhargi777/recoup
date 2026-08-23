# recoup dashboard

React + Vite + TypeScript + Tailwind CSS operator console for `recoup`.

## Status: Phase 8 — wired to the real API

Every page now fetches from `core/api` (mounted on `core/ingest/webhook_app.py`) instead
of showing placeholder state:

- `/pipeline` — real `AtRiskRecord` rows grouped by the four real cohort ids
  (`one_time_checkout_failure`, `checkout_abandonment`, `subscription_mandate_failure`,
  `overdue_b2b_invoice`), from `/api/pipeline`.
- `/decisions` — real `POLICY_GATE_DECISION` ledger events with a plain-English "why"
  derived deterministically from the gate's own reason string, from `/api/decisions`.
- `/ledger` — paginated real `LedgerEvent` rows plus a working "Verify chain" button
  calling the real `core.ledger.verify_chain`, from `/api/ledger` and `/api/ledger/verify`.
- `/guardrails` — real blocked-check rows, distinguishing a correctly-blocked action from
  a guardrail violation, from `/api/guardrails`.
- `/metrics` — real diagnosis P/R/F1 and real, `[SIMULATED]`-labeled uplift + Wilson CI
  (the label renders directly on the UI, not just in a tooltip), from `/api/metrics`.
  This endpoint runs the real pipeline live and can take up to a minute.

The kill switch in the top bar calls the real `GET`/`POST /api/kill-switch`, which itself
only calls `core.policy.activate_kill_switch` / `deactivate_kill_switch` — real,
ledger-replayed state.

Nothing on these five pages is scaffold-only placeholder content as of this phase. See
the root [README.md](../README.md)'s "Dashboard" section and `REPORT.md` for the real,
freshly-run numbers behind these views.

## Run it

```bash
# terminal 1 — the API
recoup serve --port 8000

# terminal 2 — the dashboard
cp .env.example .env.local   # VITE_API_BASE_URL, defaults to http://127.0.0.1:8000
npm install
npm run dev
```

Then open the printed local URL. Five routes are available from the sidebar (see above).

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
- `src/lib/api.ts` is the one fetch wrapper every page uses; API base URL comes from
  `VITE_API_BASE_URL` (see `.env.example`), not a hardcoded `localhost`.

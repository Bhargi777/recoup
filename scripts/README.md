# scripts/

Ad-hoc, committed scripts that exercise recoup against the real Razorpay Test
Mode API. Nothing here runs in CI or in the test suite — these are meant to be
run manually, with real `rzp_test_` credentials in `.env`.

## `live_proof.py` — real payment link creation

```bash
.venv/bin/python scripts/live_proof.py
```

Creates one real INR 1.00 Test Mode payment link via the same unmodified
`RazorpayClient` the rest of the app uses (`core/ingest/razorpay_client.py`),
against the real `api.razorpay.com/v1`. Refuses to run unless
`RAZORPAY_KEY_ID` starts with `rzp_test_` (same boot guard as the rest of the
app — see `core/config.py`). Prints the real link `id` and `short_url`.

Pay the printed `short_url` with a
[Razorpay test card](https://razorpay.com/docs/payments/payments/test-card-upi-details/)
to trigger a real `payment_link.paid` webhook — see below to receive it.

## Reproducing a real signed webhook via ngrok

`POST /webhooks/razorpay` (mounted by `recoup serve`) verifies
`X-Razorpay-Signature` against `RAZORPAY_WEBHOOK_SECRET` and dedupes on
`x-razorpay-event-id` — see README.md's Phase 2 section. To receive a real
one instead of the mocked ones in `tests/test_ingest_webhook_app.py`:

1. Start recoup's server: `recoup serve --port 8000`
2. In a second terminal, tunnel it: `ngrok http 8000`
3. Copy the `https://<random>.ngrok-free.app` URL ngrok prints.
4. In the Razorpay Dashboard (Test Mode) → **Account & Settings → Webhooks**,
   add a webhook with URL `https://<random>.ngrok-free.app/webhooks/razorpay`,
   subscribe to at least `payment_link.paid`, and set a secret. Copy that
   same secret into `.env` as `RAZORPAY_WEBHOOK_SECRET` and restart
   `recoup serve` so it picks up the new value.
5. Run `live_proof.py` (above) and pay the resulting link with a test card.
6. Razorpay delivers the real, HMAC-signed `payment_link.paid` webhook to the
   ngrok URL, which forwards it to `recoup serve`. Confirm it landed with
   `recoup verify-chain` or by tailing the ledger for a `PAYMENT_LINK_PAID`
   event on the `live_proof_<timestamp>` aggregate id `live_proof.py` printed.

This is documented rather than baked into `live_proof.py` itself because it
needs an ngrok tunnel and a one-time dashboard webhook registration — steps a
script can't do for you.

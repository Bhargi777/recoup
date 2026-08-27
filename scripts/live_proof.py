"""One real, live Razorpay Test Mode API call - proof the client works against
the real api.razorpay.com, not just MockTransport.

Creates a single real payment link via the same RazorpayClient the rest of
recoup uses (core/ingest/razorpay_client.py), for a trivial amount (INR 1.00),
and prints the real link ID and short_url so it can be paid manually with a
Razorpay test card to observe the real webhook round-trip.

Refuses to run against anything but a rzp_test_ key - same boot guard as the
rest of the app (core/config.py's Settings.enforce_test_mode already raises
before this script's own code runs, since get_settings() constructs Settings).

Usage:
    python scripts/live_proof.py
"""

import sys
from datetime import UTC, datetime

from sqlmodel import Session

from core.config import TEST_KEY_PREFIX, get_settings
from core.ingest.razorpay_client import RazorpayClient
from core.ledger import get_engine, init_ledger_schema


def main() -> int:
    settings = get_settings()
    if not settings.razorpay_key_id.startswith(TEST_KEY_PREFIX):
        # Belt-and-suspenders: Settings' own validator already raises on boot
        # for this, but a script meant to prove test-mode discipline should
        # say so itself rather than relying only on an imported side effect.
        print(f"refusing: RAZORPAY_KEY_ID must start with {TEST_KEY_PREFIX!r}", file=sys.stderr)
        return 1

    engine = get_engine(settings.database_url)
    init_ledger_schema(engine)

    reference_id = f"live_proof_{datetime.now(UTC):%Y%m%dT%H%M%SZ}"

    with Session(engine) as session:
        with RazorpayClient(
            settings.razorpay_key_id, settings.razorpay_key_secret, session
        ) as client:
            response = client.create_payment_link(
                amount_paise=100,
                currency="INR",
                description="recoup live_proof - real Test Mode payment link",
                reference_id=reference_id,
                # Razorpay's API rejects an empty {} customer object (the
                # client's own default when customer=None) as malformed -
                # discovered live via this script - so supply a real one.
                customer={"name": "recoup live proof", "email": "live-proof@example.com"},
            )
        session.commit()

    print("live proof: real payment link created against api.razorpay.com")
    print(f"  reference_id : {reference_id}")
    print(f"  link id      : {response['id']}")
    print(f"  short_url    : {response['short_url']}")
    print("Pay this with a Razorpay test card to observe the real webhook round-trip.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

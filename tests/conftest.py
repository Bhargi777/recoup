"""Shared pytest fixtures. Dummy test-mode credentials keep the boot guard happy in CI."""

import os

os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_dummy_key_id_for_ci")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "dummy_secret_for_ci")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "dummy_webhook_secret_for_ci")

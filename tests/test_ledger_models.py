import re

from core.ledger.models import GENESIS_HASH, utc_now_iso

TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def test_genesis_hash_is_64_zero_chars_per_spec() -> None:
    assert GENESIS_HASH == "0" * 64
    assert len(GENESIS_HASH) == 64


def test_utc_now_iso_matches_spec_timestamp_format() -> None:
    assert TIMESTAMP_PATTERN.match(utc_now_iso())

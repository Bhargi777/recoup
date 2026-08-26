"""Environment settings with hard Test Mode enforcement.

Ground rule: Razorpay credentials come from the environment only and the key id MUST
start with ``rzp_test_``. Any other value aborts the process at boot.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TEST_KEY_PREFIX = "rzp_test_"
LIVE_KEY_PREFIX = "rzp_live_"


class TestModeViolationError(RuntimeError):
    """Raised when a live-mode or malformed Razorpay key is detected."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # Secondary LLM classifier path (core/diagnose/llm_classifier.py). Unlike the
    # Razorpay key, an empty value is a normal, non-fatal state: it just means the
    # LLM fallback path is unavailable and diagnose() must abstain honestly instead
    # of crashing the app or fabricating a classification.
    anthropic_api_key: str = ""

    database_url: str = "sqlite:///recoup.db"

    app_env: str = "development"
    log_level: str = "INFO"

    max_global_budget_inr: float = Field(default=50_000.0, ge=0)
    dnd_start_hour: int = Field(default=21, ge=0, le=23)
    dnd_end_hour: int = Field(default=9, ge=0, le=23)
    default_holdout_percent: float = Field(default=15.0, gt=0, lt=100)
    split_seed: int = 42

    # --- Phase 5: policy engine / guardrails -------------------------------
    # RBI Digital Payments - E-mandate Framework, 2026 (RBI/DPSS/2026-27/396,
    # dated 2026-04-21) requires a pre-transaction notification at least this
    # many hours before an e-mandate debit. Verified directly against
    # rbi.org.in - see README.md "Regulatory constraints (Phase 5)".
    rbi_emandate_pre_debit_notice_hours: float = Field(default=24.0, ge=0)

    # NPCI's August 2025 UPI AutoPay tightening: one original execution plus
    # three retries (4 total) per mandate cycle before it is auto-cancelled.
    # Corroborated by multiple independent secondary sources (see README);
    # the primary NPCI operating circular PDF could not be fetched directly
    # (403), so this is treated as a conservative, best-effort default - see
    # README.md "Regulatory constraints (Phase 5)".
    npci_upi_autopay_max_attempts: int = Field(default=4, ge=1)

    # Minimum time between two customer-facing communications for the same
    # aggregate (payment/invoice). Not an RBI/NPCI number - there is no
    # regulatory source for a generic dunning cooldown. Adopted from
    # .claude/skills/money-action-gate/SKILL.md's own worked example (6h) as
    # our conservative default; kept fully configurable rather than
    # hard-coded so a real value can replace it without a code change.
    default_cooldown_hours: float = Field(default=6.0, ge=0)

    @field_validator("razorpay_key_id")
    @classmethod
    def enforce_test_mode(cls, value: str) -> str:
        if not value.startswith(TEST_KEY_PREFIX):
            raise TestModeViolationError(
                f"RAZORPAY_KEY_ID must start with {TEST_KEY_PREFIX!r} "
                f"(got {'an empty value' if not value else value[:12] + '...'}). "
                "recoup refuses to run against anything but Test Mode."
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()

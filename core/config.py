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

    database_url: str = "sqlite:///recoup.db"

    app_env: str = "development"
    log_level: str = "INFO"

    max_global_budget_inr: float = Field(default=50_000.0, ge=0)
    dnd_start_hour: int = Field(default=21, ge=0, le=23)
    dnd_end_hour: int = Field(default=9, ge=0, le=23)
    default_holdout_percent: float = Field(default=15.0, gt=0, lt=100)
    split_seed: int = 42

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

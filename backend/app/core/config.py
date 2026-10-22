"""Application settings.

Every credential and deployment-specific value comes from environment
variables (or a local ``.env`` file in development). Nothing secret is
hard-coded. Branding lives here too so the final marketplace name, domain,
logo and colors can change without touching application code.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Runtime -----------------------------------------------------------
    environment: str = "development"  # development | staging | production | test
    debug: bool = False
    api_prefix: str = "/api/v1"

    # --- Database ----------------------------------------------------------
    database_url: str = f"sqlite:///{BACKEND_ROOT / 'dev.db'}"

    # --- Security ----------------------------------------------------------
    secret_key: str = Field(default="dev-only-change-me-please-0123456789abcdef", min_length=32)
    access_token_minutes: int = 60 * 12
    download_link_seconds: int = 60 * 15
    email_token_hours: int = 48
    cookie_secure: bool = False
    cookie_name: str = "mkt_session"
    cors_origins: list[str] = ["http://localhost:3000"]
    login_rate_limit_per_minute: int = 10

    # --- Branding (configurable; final name/domain still to be decided) ----
    brand_name: str = "Lumen & Reel"
    brand_tagline: str = "Licensed photography, footage and production talent worldwide."
    brand_domain: str = "localhost:3000"
    brand_logo_url: str = ""
    brand_primary_color: str = "#C8A15A"
    brand_support_email: str = "support@example.com"
    parent_company: str = "One United Enterprise LLC"
    technology_partner: str = "Azoth Digital"

    # --- Storage -----------------------------------------------------------
    storage_backend: str = "local"  # local | s3
    local_storage_path: Path = BACKEND_ROOT / "storage"
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_private_bucket: str = "media-originals"
    s3_public_bucket: str = "media-previews"
    public_media_base_url: str | None = None  # CDN in front of the preview bucket

    # --- Media -------------------------------------------------------------
    max_image_upload_mb: int = 100
    max_video_upload_mb: int = 4096
    preview_max_edge_px: int = 1600
    thumbnail_max_edge_px: int = 480
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    malware_scanner: str = "none"  # none | clamav

    # --- Email -------------------------------------------------------------
    email_backend: str = "console"  # console | smtp (provider adapters added in later phases)
    public_web_url: str = "http://localhost:3000"

    # --- Payments (Phase 2) ----------------------------------------------------
    # "fake" simulates the provider for local development and tests; it is
    # refused in production. "stripe" uses Stripe Checkout + Connect Express.
    payment_provider: str = "fake"
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_tax_enabled: bool = False
    # Earnings stay pending this long so refunds and chargebacks can be absorbed
    # before money leaves the platform balance.
    earnings_hold_days: int = 14
    min_payout_cents: int = 1000
    referral_attribution_days: int = 365
    # Custom production: a submitted milestone is approved automatically if the
    # client neither approves nor requests a revision within this many days.
    milestone_auto_approve_days: int = 7
    max_deliverable_mb: int = 4096

    # --- Feature flags -----------------------------------------------------
    # Exclusive licensing and payments stay off until agreements are reviewed
    # by counsel and payment testing is complete.
    feature_paid_licensing: bool = False
    feature_exclusive_licensing: bool = False

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.environment == "production":
            if self.secret_key.startswith("dev-only"):
                raise ValueError("SECRET_KEY must be set in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if self.storage_backend != "s3":
                raise ValueError("Production requires STORAGE_BACKEND=s3 (container disks are ephemeral)")
            if self.feature_paid_licensing and (
                self.payment_provider != "stripe" or not self.stripe_secret_key or not self.stripe_webhook_secret
            ):
                raise ValueError("Paid licensing in production requires PAYMENT_PROVIDER=stripe and Stripe keys")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

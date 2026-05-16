"""Application configuration using pydantic-settings."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    # Telegram
    telegram_token: str = Field(..., description="Telegram bot token")
    admin_user_ids: str = Field(
        default="",
        description="Comma-separated list of Telegram user IDs with admin access"
    )

    # OpenAI
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI API base URL"
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model name"
    )

    # Paths
    pdf_storage_path: str = Field(
        default="./rules_pdfs",
        description="Directory containing PDF rulebooks"
    )
    data_path: str = Field(
        default="./data",
        description="Directory for SQLite DBs and logs"
    )

    # Performance
    max_requests_per_minute: int = Field(
        default=10,
        description="Max requests per user per minute"
    )
    max_concurrent_searches: int = Field(
        default=4,
        description="Max concurrent ugrep processes"
    )
    agent_run_timeout_seconds: int = Field(
        default=120,
        description=(
            "Hard wall-clock cap on a single agent run (all internal "
            "retries included). A stalled model/proxy stream raises no "
            "retriable error, so without this deadline the request hangs "
            "and — with sequential update dispatch — freezes the bot. On "
            "timeout the user gets a message and the handler returns."
        )
    )
    max_context_tokens: int = Field(
        default=90000,
        description=(
            "Token budget for conversation history sent to the model on "
            "each call. Kept well below the model's hard context limit to "
            "leave headroom for the system prompt and the structured "
            "completion. Oldest turns are trimmed first."
        )
    )
    max_full_document_chars: int = Field(
        default=12000,
        description=(
            "Max characters returned by read_full_document. A single "
            "full-document dump must not be able to fill the model's "
            "context window; targeted search tools should be preferred."
        )
    )

    # Per-user budget
    budget_enabled: bool = Field(
        default=True,
        description="Master switch for per-user request/token budget"
    )
    daily_request_limit: int = Field(
        default=50,
        description="Max successful requests per user per UTC day"
    )
    daily_token_limit: int = Field(
        default=300000,
        description="Max total tokens per user per UTC day"
    )
    monthly_request_limit: int = Field(
        default=1000,
        description="Max successful requests per user per UTC month"
    )
    monthly_token_limit: int = Field(
        default=6000000,
        description="Max total tokens per user per UTC month"
    )

    # Session history retention
    session_max_turns: int = Field(
        default=20,
        description=(
            "Keep only the last N user-turn boundaries in each user's "
            "SQLiteSession. Trimmed inline after every answer."
        )
    )
    session_ttl_days: int = Field(
        default=30,
        description=(
            "Delete a user's session DB file if untouched for this many "
            "days (privacy + disk)."
        )
    )
    retention_cleanup_interval_seconds: int = Field(
        default=86400,
        description=(
            "Interval for the background session/budget cleanup task. "
            "Runs once at startup, then every interval."
        )
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    log_format: str = Field(
        default="text",
        description="Logging output format: 'text' for human-readable or 'json' for structured logs"
    )
    perf_logging: bool = Field(
        default=False,
        description=(
            "Emit [Perf] per-turn / per-run timing logs for latency "
            "diagnostics. Keep False in production; set True for a "
            "diagnostic run only."
        )
    )

    # BoardGameGeek API
    bgg_api_token: str = Field(
        default="",
        description="BoardGameGeek API token (optional)"
    )

    # Few-shot examples (optional prompt feature)
    enable_few_shot_examples: bool = Field(
        default=False,
        description="If True, inject few-shot examples into the system prompt"
    )

    # Langfuse Observability
    langfuse_public_key: str = Field(
        default="",
        description="Langfuse public API key (optional)"
    )
    langfuse_secret_key: str = Field(
        default="",
        description="Langfuse secret API key (optional)"
    )
    langfuse_base_url: str = Field(
        default="https://cloud.langfuse.com",
        description="Langfuse API base URL"
    )
    enable_tracing: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing to Langfuse"
    )
    langfuse_environment: str = Field(
        default="production",
        description="Environment name for Langfuse traces"
    )

    # Sentry Error Tracking
    sentry_dsn: str = Field(
        default="",
        description="Sentry DSN (leave empty to disable)"
    )
    sentry_environment: str = Field(
        default="production",
        description="Environment tag for Sentry events"
    )
    sentry_release: str = Field(
        default="",
        description="Release identifier for Sentry (e.g. git SHA). Empty = auto-detect"
    )
    sentry_traces_sample_rate: float = Field(
        default=0.0,
        description=(
            "Sentry APM traces sample rate (0.0-1.0). Keep 0.0 when using "
            "OpenTelemetry/Langfuse to avoid double-tracing."
        )
    )

    # Health & Heartbeat
    health_host: str = Field(
        default="0.0.0.0",
        description="Bind host for the /health HTTP endpoint"
    )
    health_port: int = Field(
        default=8080,
        description="Port for the /health HTTP endpoint. Set to 0 to disable."
    )
    heartbeat_interval_seconds: int = Field(
        default=300,
        description=(
            "Interval for the periodic 'bot alive' log line. "
            "Set to 0 to disable."
        )
    )

    @property
    def session_db_dir(self) -> str:
        """Directory for per-user session databases."""
        return f"{self.data_path}/sessions"

    @property
    def budget_db_path(self) -> str:
        """Path to the single shared budget counters database."""
        return f"{self.data_path}/budget.db"

    @property
    def admin_ids(self) -> list[int]:
        """Parse comma-separated admin user IDs into a list of integers."""
        if not self.admin_user_ids or not self.admin_user_ids.strip():
            return []
        try:
            return [int(uid.strip()) for uid in self.admin_user_ids.split(",") if uid.strip()]
        except ValueError:
            return []

    @property
    def tracing_enabled(self) -> bool:
        """Check if tracing should be enabled."""
        return (
            self.enable_tracing
            and bool(self.langfuse_public_key.strip())
            and bool(self.langfuse_secret_key.strip())
        )

    @property
    def sentry_enabled(self) -> bool:
        """Check if Sentry should be initialized."""
        return bool(self.sentry_dsn.strip())


# Global settings instance
try:
    settings = Settings()
except Exception as e:
    raise RuntimeError(
        "Failed to load configuration. Ensure .env file exists with required variables: "
        "TELEGRAM_TOKEN, OPENAI_API_KEY"
    ) from e

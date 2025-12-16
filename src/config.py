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
        default="https://api.proxyapi.ru/openai/v1",
        description="OpenAI API base URL"
    )
    openai_model: str = Field(
        default="gpt-5-nano",
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

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )

    @property
    def session_db_dir(self) -> str:
        """Directory for per-user session databases."""
        return f"{self.data_path}/sessions"

    @property
    def admin_ids(self) -> list[int]:
        """Parse comma-separated admin user IDs into a list of integers."""
        if not self.admin_user_ids or not self.admin_user_ids.strip():
            return []
        try:
            return [int(uid.strip()) for uid in self.admin_user_ids.split(",") if uid.strip()]
        except ValueError:
            return []


# Global settings instance
try:
    settings = Settings()
except Exception as e:
    raise RuntimeError(
        "Failed to load configuration. Ensure .env file exists with required variables: "
        "TELEGRAM_TOKEN, OPENAI_API_KEY"
    ) from e

"""Configuration management for Rediska Core."""

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    mysql_url: str = Field(
        default="mysql+pymysql://rediska:rediska@rediska-mysql:3306/rediska",
        description="MySQL connection URL",
    )

    # Redis
    redis_url: str = Field(default="redis://rediska-redis:6379/0")

    # Celery
    celery_broker_url: str = Field(default="redis://rediska-redis:6379/1")
    celery_result_backend: str = Field(default="redis://rediska-redis:6379/2")

    # Elasticsearch
    elastic_url: str = Field(default="http://rediska-elasticsearch:9200")

    # Storage paths
    attachments_path: str = Field(default="/var/lib/rediska/attachments")
    backups_path: str = Field(default="/var/lib/rediska/backups")

    # LLM endpoints
    inference_url: Optional[str] = None
    inference_model: Optional[str] = None
    inference_api_key: Optional[str] = None
    embeddings_url: Optional[str] = None
    embeddings_model: Optional[str] = None
    embeddings_api_key: Optional[str] = None

    # Web
    base_url: str = Field(default="https://rediska.local")

    # Provider: Reddit
    provider_reddit_enabled: bool = Field(default=False)
    provider_reddit_client_id: Optional[str] = None
    provider_reddit_client_secret: Optional[str] = None
    provider_reddit_redirect_uri: Optional[str] = None
    provider_reddit_user_agent: str = Field(default="Rediska/1.0")

    # Rate limiting
    provider_rate_qpm_default: int = Field(default=60)
    provider_rate_concurrency_default: int = Field(default=2)
    provider_rate_burst_factor: float = Field(default=1.5)

    # Security
    secret_key: str = Field(
        default="CHANGE_ME_IN_PRODUCTION",
        description="Secret key for signing tokens",
    )
    encryption_key: str = Field(
        default="",
        description="Fernet encryption key for secrets storage (generate with CryptoService.generate_key())",
    )
    session_expire_hours: int = Field(default=24 * 7)  # 1 week

    @field_validator("mysql_url")
    @classmethod
    def validate_mysql_url(cls, v: str) -> str:
        if not v or v == "":
            raise ValueError("MYSQL_URL is required")
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()

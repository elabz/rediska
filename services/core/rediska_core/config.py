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
    inference_timeout: float = Field(default=300.0, description="Inference request timeout in seconds")
    inference_chat_template: str = Field(
        default="llama3",
        description="Chat template for response parsing: llama3, qwen_thinking, mistral, chatml",
    )
    inference_max_concurrent: int = Field(
        default=1,
        description="Global cap on simultaneous inference requests across all processes "
        "(llama.cpp serves one request at a time unless started with --parallel)",
    )
    inference_max_retries: int = Field(
        default=4, description="Retries on 429/5xx from the inference endpoint"
    )
    inference_retry_base_delay: float = Field(
        default=10.0, description="First retry delay in seconds; doubles per retry, max 120s"
    )
    embeddings_url: Optional[str] = None
    embeddings_model: Optional[str] = None
    embeddings_api_key: Optional[str] = None
    # Semantic search: indexing enqueues embedding only while this is on, so
    # the pipeline can be deployed dark and switched on after the reindex.
    embeddings_enabled: bool = Field(
        default=False,
        description="Enqueue embedding after indexing and allow semantic ranking",
    )
    embed_max_chars: int = Field(
        default=1400,
        ge=100,
        description="Hard input budget per embeddings call; longer text is chunked "
        "and averaged (the llama.cpp server rejects ~512+ tokens)",
    )
    embed_max_concurrent: int = Field(
        default=1,
        ge=1,
        description="Embedding calls allowed at once, so backfill leaves the GPU to analysis",
    )
    embed_batch_size: int = Field(
        default=16,
        ge=1,
        le=64,
        description="Documents per embeddings batch call",
    )

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

    # Geocoding
    home_latitude: float = Field(default=40.0, description="Home latitude for distance calculation")
    home_longitude: float = Field(default=-75.2, description="Home longitude for distance calculation")
    location_near_threshold_miles: int = Field(
        default=200, description="Max miles to consider a location 'near'"
    )

    # User constraints for deterministic lead gates
    user_age: int = Field(
        default=45, description="User's own age, checked against partner_max_age gate"
    )
    user_ds_orientation: str = Field(
        default="dominant",
        description="User's D/s orientation (dominant|submissive|switch) for the compatibility gate",
    )

    # Dimension-agent input context budgets
    analysis_context_max_chars: int = Field(
        default=24000,
        description="Max characters of assembled input sent to a dimension agent (~6k tokens)",
    )
    analysis_max_recent_posts: int = Field(
        default=10,
        description="Max newest author posts included for dimensions that use recent_posts",
    )
    analysis_post_item_chars: int = Field(
        default=800, description="Max characters kept per included author post"
    )

    # Human evaluation: prompt replay
    evaluation_replay_max_cases: int = Field(
        default=50,
        description="Hard cap on labelled cases replayed per prompt replay (most recent first)",
    )

    # Lead triage: scout-sourced leads still `new` after this many days are
    # auto-expired by maintenance.expire_stale_leads. Off by default: leads are
    # kept and the Leads page filters by date instead.
    lead_expiry_days: int = Field(
        default=0,
        ge=0,
        description="Days before an untouched scout lead expires (0 disables, the default)",
    )

    # Source discovery: candidate mining and bounded trials
    discovery_min_qualified_authors: int = Field(
        default=3,
        ge=1,
        description="Distinct qualified authors (or distinct URLs, for external hosts) a "
        "candidate needs before it is surfaced",
    )
    discovery_trial_sample: int = Field(
        default=25,
        ge=1,
        le=50,
        description="Recent posts fetched and analysed per candidate trial (hard cap 50)",
    )
    discovery_window_days: int = Field(
        default=180,
        ge=1,
        description="Trailing window of stored author history and link sightings used "
        "for mining",
    )

    # Post copy detection (post_copy.py): cross-author copies of the same text
    copy_min_chars: int = Field(
        default=200,
        ge=1,
        description="Bodies shorter than this get an exact hash only (no sketch, no clustering)",
    )
    copy_jaccard_threshold: float = Field(
        default=0.5,
        gt=0.0,
        le=1.0,
        description="Estimated 5-word-shingle Jaccard at or above which two posts are copies",
    )
    copy_ring_window_days: int = Field(
        default=7,
        ge=1,
        description="Two live accounts posting a copy within this many days is a ring suspect",
    )
    copy_skip_ring_suspects: bool = Field(
        default=True,
        description="Skip scout analysis of posts whose copy cluster is handled as a spam ring",
    )
    copy_ring_min_authors: int = Field(
        default=3,
        ge=2,
        description="A ring suspect is handled automatically (skipped + hidden) from this many "
        "distinct authors",
    )
    copy_ring_min_chars: int = Field(
        default=400,
        ge=0,
        description="...and only when its posts average at least this many characters "
        "(short templates are left for the human)",
    )

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

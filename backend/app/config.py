from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str | None = None
    cors_origins: list[str] = ["http://localhost:5173"]
    rss_feed_urls: list[AnyHttpUrl] = Field(default_factory=list)
    ingestion_request_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    ingestion_max_retries: int = Field(default=2, ge=0, le=5)
    ingestion_retry_backoff_seconds: float = Field(default=0.25, ge=0, le=10)
    youtube_api_key: SecretStr | None = None
    youtube_max_videos: int = Field(default=5, ge=1, le=50)
    youtube_comments_per_video: int = Field(default=20, ge=1, le=100)
    youtube_max_comment_pages_per_video: int = Field(default=1, ge=1, le=5)
    gemini_api_key: SecretStr | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_request_timeout_seconds: float = Field(default=60.0, gt=0, le=180)
    ai_request_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    scheduled_ingestion_enabled: bool = False
    scheduled_ingestion_keywords: list[str] = Field(default_factory=list)
    scheduled_ingestion_interval_minutes: int = Field(default=360, ge=15, le=10_080)
    scheduled_ingestion_limit: int = Field(default=50, ge=1, le=100)
    scheduled_ingestion_sources: list[Literal["hacker_news", "rss", "youtube"]] = Field(
        default_factory=lambda: ["hacker_news", "rss", "youtube"]
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
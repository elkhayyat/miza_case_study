from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "Miza Analytics"
    app_version: str = "1.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://miza:miza@localhost:5432/miza_analytics"
    db_pool_min_size: int = 5
    db_pool_max_size: int = 20
    db_pool_timeout: int = 30

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 30

    # API Keys — comma-separated list of "client_id:hashed_key" pairs
    # Hash is SHA-256 of the raw API key
    # Example: "b2c_client:abc123hash,b2b_partner:def456hash"
    api_keys: str = ""

    # CORS
    cors_allowed_origins: str = "http://localhost:3000"

    # Rate limiting
    rate_limit_requests: int = 1000
    rate_limit_window_seconds: int = 60

    # Batch processing
    max_batch_size: int = 100

    # OpenTelemetry
    otel_enabled: bool = False
    otel_service_name: str = "miza-analytics"
    otel_exporter_endpoint: str = ""
    otel_exporter_insecure: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()

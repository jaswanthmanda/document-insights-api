from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_database: str = "document_insights"
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600
    processing_min_seconds: int = 10
    processing_max_seconds: int = 30
    worker_failure_rate: float = 0.10

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
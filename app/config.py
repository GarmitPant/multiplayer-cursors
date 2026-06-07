from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379"
    cors_origins: str = "*"          # comma-separated in real envs
    replica_id: str = "local"        # surfaced to clients so failover is visible
    quant_bits: int = 12
    tick_ms: int = 50


settings = Settings()

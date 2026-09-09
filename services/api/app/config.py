from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./healthos.db"
    redis_url: str = "redis://localhost:6379/0"
    auth_secret: str = "dev-secret-change-me"
    cookie_secure: bool = False
    cookie_name: str = "healthos_session"
    session_ttl_days: int = 30

    ai_provider: str = "mock"  # mock | openai_compatible
    ai_model: str = "gpt-4o-mini"
    ai_api_key: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_max_tool_rounds: int = 6

    seed_on_startup: bool = True

    usda_api_key: str = ""  # TRACK A — USDA FoodData Central; provider skipped when unset
    worker_enabled: bool = True  # in-process background worker (tests disable it)
    vapid_sub: str = "mailto:admin@healthos.local"  # VAPID contact claim for web push


@lru_cache
def get_settings() -> Settings:
    return Settings()

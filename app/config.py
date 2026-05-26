from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    secret_key: str = "dev-secret-change-in-production"
    database_url: str = f"sqlite:///{BASE_DIR / 'raci_studio.db'}"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_vision_model: str = "gpt-4o"
    upload_dir: Path = BASE_DIR / "uploads"
    max_upload_mb: int = 50
    role_overload_threshold: float = 0.30
    app_title: str = "RACI Studio"
    client_name: str = "Global Payments"
    engagement_name: str = "Prague SSC Transformation"
    deliverer: str = "PwC"

    @property
    def has_llm(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()

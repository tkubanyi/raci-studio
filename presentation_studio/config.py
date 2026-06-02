"""Settings for Presentation Studio (local-only)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "data" / "presentation-templates"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "presentation_studio_outputs"


class PresentationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    brand_pptx: Path = TEMPLATES_DIR / "Project_Vienna_Discovery_Phase.pptx"
    brand_json: Path = TEMPLATES_DIR / "graphic_elements_correct.brand.summary.json"
    default_output_dir: Path = DEFAULT_OUTPUT_DIR
    default_footer: str = "Presentation Studio | PwC"

    streamlit_host: str = "127.0.0.1"
    streamlit_port: int = 8501

    @property
    def has_llm(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())


@lru_cache
def get_settings() -> PresentationSettings:
    return PresentationSettings()

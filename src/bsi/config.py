from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BSI_", env_file=".env", env_ignore_empty=True, extra="ignore")

    gemini_api_key: str = Field("", validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"))
    llm_model: str = "gemini-2.5-flash"
    mock: bool | None = None  # None -> auto: mock iff no API key
    classify_prompt: str = "classify_v4"
    summary_prompt: str = "summary_v2"
    max_upload_mb: int = 10
    cors_origins: str = ""  # the bundled web UI is same-origin; list origins only for a separate front-end
    layouts_dir: Path = ROOT / "layouts"
    prompts_dir: Path = ROOT / "prompts"
    samples_dir: Path = ROOT / "data" / "synthetic"

    @property
    def mock_mode(self) -> bool:
        if self.mock is not None:
            return self.mock
        return not self.gemini_api_key

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()

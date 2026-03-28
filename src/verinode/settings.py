from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    openai_api_key: str = Field(validation_alias="OPENAI_API_KEY")
    openai_model_main: str = Field(validation_alias="OPENAI_MODEL_MAIN")
    openai_model_search: str = Field(validation_alias="OPENAI_MODEL_SEARCH")
    openai_model_sandbox: str = Field(validation_alias="OPENAI_MODEL_SANDBOX")
    tinyfish_api_key: str = Field(validation_alias="TINYFISH_API_KEY")
    tinyfish_base_url: str = Field(validation_alias="TINYFISH_BASE_URL")

    app_env: str = Field(default="local", validation_alias="APP_ENV")
    app_data_dir: Path = Field(default=Path("./data"), validation_alias="APP_DATA_DIR")
    database_url: str = Field(
        default="sqlite:///./data/app.db",
        validation_alias="DATABASE_URL",
    )
    max_concurrent_jobs: int = Field(default=2, validation_alias="MAX_CONCURRENT_JOBS")
    enable_external_search: bool = Field(
        default=True,
        validation_alias="ENABLE_EXTERNAL_SEARCH",
    )
    enable_code_sandbox: bool = Field(
        default=True,
        validation_alias="ENABLE_CODE_SANDBOX",
    )
    enable_tinyfish: bool = Field(default=True, validation_alias="ENABLE_TINYFISH")
    app_cors_origins_raw: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="APP_CORS_ORIGINS",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @property
    def uploads_dir(self) -> Path:
        return self.app_data_dir / "uploads"

    @property
    def artifacts_dir(self) -> Path:
        return self.app_data_dir / "artifacts"

    @property
    def app_cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.app_cors_origins_raw.split(",")
            if origin.strip()
        ]

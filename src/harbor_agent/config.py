from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "HarborPilot AI"
    llm_mode: str = "mock"
    llm_provider: str = "mock"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str | None = None
    cors_origins: str = "http://localhost:3001,http://127.0.0.1:3001"
    admin_token: str | None = None
    profile_store_secret: str | None = None
    allow_insecure_local_admin: bool = False
    langfuse_enabled: bool = False
    langfuse_public_key: SecretStr | None = Field(default=None, validation_alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: SecretStr | None = Field(default=None, validation_alias="LANGFUSE_SECRET_KEY")
    langfuse_base_url: str = Field(default="https://cloud.langfuse.com", validation_alias="LANGFUSE_BASE_URL")
    langfuse_environment: str = Field(default="development", validation_alias="LANGFUSE_TRACING_ENVIRONMENT")
    langfuse_release: str | None = Field(default=None, validation_alias="LANGFUSE_RELEASE")
    langfuse_sample_rate: float = Field(default=1.0, ge=0, le=1, validation_alias="LANGFUSE_SAMPLE_RATE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HARBOR_AGENT_",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

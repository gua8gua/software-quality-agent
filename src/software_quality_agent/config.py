from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 对于继承自 BaseSettings 的类，类中必须有 model_config 属性，且必须是 SettingsConfigDict 类型的实例。
    # 才能读取 .env 文件中的环境变量，并将其映射到类的属性中。
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Software Quality Agent"
    app_env: str = "local"
    database_url: str = "sqlite+aiosqlite:///./data/software_quality_agent.sqlite"

    llm_provider: str = "mock"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = Field(default=60.0, gt=0)

    default_project_id: str = ""
    api_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.api_cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


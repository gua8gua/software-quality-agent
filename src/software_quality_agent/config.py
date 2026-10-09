from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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

    app_name: str = "Software Quality Workbench"
    app_env: str = "local"
    quality_backend_url: str = "http://127.0.0.1:8000"
    api_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    suggestion_session_db: str = "artifacts/suggestion_agent_sessions.sqlite3"
    suggestion_checkpoint_dir: str = "artifacts/suggestion_agent_checkpoints"
    suggestion_model: str | None = None
    suggestion_base_url: str | None = None
    suggestion_api_key: str = "local"
    # Interactive project-console setting only.  The formal review workflow
    # does not use this cap; its bounded unit is one SDS passage instead.
    suggestion_max_turns: int = Field(default=256, ge=1)
    # Legacy deployments may still set 24; the runtime clamps the investigator
    # to the product cap of five turns.
    review_passage_max_turns: int = Field(default=5, ge=1)
    # New tasks use the fixed TLR baseline; the original investigation pipeline
    # remains selectable without replacing its Agents or persisted results.
    review_pipeline: Literal["fixed_tlr", "full_investigation"] = "fixed_tlr"
    suggestion_max_revisions: int = Field(default=2, ge=1, le=2)

    @field_validator("suggestion_max_revisions", mode="before")
    @classmethod
    def cap_suggestion_revisions(cls, value):
        return min(2, int(value))
    # A failed model attempt may be resumed by the durable worker, but the
    # host must eventually stop retrying the same sentence.  This counts
    # retries after the initial attempt; the model never sees this control.
    review_model_retry_limit: int = Field(default=1, ge=0, le=1)

    @field_validator("review_model_retry_limit", mode="before")
    @classmethod
    def cap_model_retries(cls, value):
        # Existing environments may still contain the former limit of five.
        # The product policy now permits at most one retry, including on resume.
        return min(1, int(value))
    # Admission controls are preflight limits, not new model budgets.  They
    # make the existing serving context explicit and fail closed when the
    # tokenizer/health state cannot safely admit another request.
    suggestion_context_window: int = Field(default=16_384, ge=1_024)
    suggestion_provider_max_output_tokens: int | None = Field(default=None, ge=1)
    suggestion_truncation_continuation_limit: int = Field(default=8, ge=1, le=32)
    suggestion_context_safety_tokens: int = Field(default=512, ge=0)
    suggestion_model_health_timeout_seconds: float = Field(default=4.0, gt=0)
    # Applies to one provider HTTP request only; it is not a segment/batch
    # deadline and is intentionally not placed in the model-facing prompt.
    suggestion_model_call_timeout_seconds: float = Field(default=180.0, gt=0)
    suggestion_model_failure_limit: int = Field(default=2, ge=1, le=3)
    review_queue_dsn: str = ""
    review_worker_concurrency: int = Field(default=1, ge=1)
    # After every mandatory TLR candidate has been inspected, investigation
    # may open only this many additional BM25/non-TLR passages for one source
    # segment.  The cap is a search-scope guard, not a semantic conclusion.
    # Legacy deployments may still set 8; the runtime clamps it to five.
    review_supplemental_passage_limit: int = Field(default=5, ge=0, le=1000)
    database_url: str = "sqlite+aiosqlite:///./data/software_quality_agent.sqlite"
    llm_provider: str = "openai_compatible"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    default_project_id: str = ""
    console_state_db: str = "artifacts/console-state.sqlite3"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.api_cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

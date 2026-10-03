"""寻味中国 · 配置加载（pydantic-settings）"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。架构级常量（红线）在代码中硬编码，不在 env 中修改。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 环境 ----
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # ---- PostgreSQL ----
    postgres_url: str = Field(default="postgresql+psycopg://xunwei:xunwei_dev@localhost:5432/xunwei")

    # ---- Redis ----
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ---- LLM ----
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_fast_model: str = "gpt-4o-mini"
    llm_max_tokens: int = 512
    llm_temperature: float = 0.1
    llm_timeout_ms: int = 5000

    # ---- 向量 ----
    vector_dimension: int = 1536

    # ---- 加密 ----
    data_encryption_key: Optional[str] = None

    # ---- 缓存 TTL（秒）----
    cache_ttl_constraint_sec: int = 300
    cache_ttl_recommendation_sec: int = 600
    cache_ttl_evidence_sec: int = 3600

    # ---- 延迟预算（毫秒）----
    recommendation_timeout_ms: int = 500
    llm_constraint_timeout_ms: int = 200
    llm_format_timeout_ms: int = 200
    rag_timeout_ms: int = 200
    safety_filter_timeout_ms: int = 50

    # ---- 红线 / 架构常量（可在 env 覆盖但会触发架构级告警）----
    # 这些值的正确值在代码常量中定义，env 仅用于强制审查
    max_llm_convergence_rounds: int = Field(default=4, ge=1, le=10)
    min_gate5_understanding_pct: int = Field(default=80, ge=50, le=100)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @field_validator("llm_temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """AI 推荐需要确定性，温度不应过高。"""
        if v > 0.5:
            raise ValueError(f"LLM temperature {v} > 0.5 会导致推荐不稳定")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例配置。"""
    return Settings()

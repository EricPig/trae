"""Redis 缓存层。

架构职责：
  - 缓存准入判定结果（key: locality_level + evidence_level，命中即跳过 DB 查询）
  - 缓存 locality_score 计算结果
  - 缓存推荐结果列表（带约束 hash）
  - 缓存 RAG 证据链（dish_id 级，数据不变更则永久缓存）

设计原则：
  - 缓存失效只影响延迟（回退 DB 查询），不影响正确性
  - 缓存键设计避免冲突：每类缓存独立 key 前缀
  - 不做缓存穿透保护（T0 阶段低并发足够），T1 后补充 Bloom Filter
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from src.config import get_settings


def _hash_key(*parts: Any) -> str:
    """将任意参数序列化为稳定的哈希 key。"""
    raw = json.dumps([str(p) for p in parts], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class CacheKeys:
    """所有缓存键集中定义（避免散落）。"""

    # 准入层
    admission = lambda l, e: f"adj:admission:{l}:{e}"

    # 排序层
    score = lambda l, e, y: f"adj:score:{l}:{e}:{y or 'None'}"

    # 推荐结果（约束 + 地理粒度）
    recommendation = lambda constraint_hash, geo: f"rec:{constraint_hash}:{geo}"

    # RAG 证据链
    evidence = lambda dish_id: f"rag:evidence:{dish_id}"

    # LLM 约束提取
    constraint = lambda query_hash: f"llm:constraint:{query_hash}"


class RecommendationCache:
    """推荐结果缓存（同步实现，便于测试 + FastAPI 同步路径）。"""

    def __init__(self, redis_client: Optional[Any] = None) -> None:
        self.redis = redis_client  # Optional：None 时自动降级为无缓存
        self.settings = get_settings()

    async def get(self, key: str) -> Optional[bytes]:
        if self.redis is None:
            return None
        try:
            return await self.redis.get(key)
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        if self.redis is None:
            return True
        try:
            import json as _json

            if not isinstance(value, (str, bytes)):
                value = _json.dumps(value, default=str)
            ttl = ttl_seconds or self.settings.cache_ttl_recommendation_sec
            await self.redis.setex(key, ttl, value)
            return True
        except Exception:
            return False

    async def get_admission(self, locality_level: str, evidence_level: str) -> Optional[dict]:
        key = CacheKeys.admission(locality_level, evidence_level)
        raw = await self.get(key)
        if raw:
            import json

            return json.loads(raw)
        return None

    async def set_admission(self, locality_level: str, evidence_level: str, result: dict) -> None:
        key = CacheKeys.admission(locality_level, evidence_level)
        await self.set(key, result, ttl_seconds=3600)

    async def get_recommendations(
        self, constraints: dict, geo: str
    ) -> Optional[list[dict]]:
        ch = _hash_key(constraints)
        key = CacheKeys.recommendation(ch, geo)
        raw = await self.get(key)
        if raw:
            import json

            return json.loads(raw)
        return None

    async def set_recommendations(
        self, constraints: dict, geo: str, results: list[dict]
    ) -> None:
        ch = _hash_key(constraints)
        key = CacheKeys.recommendation(ch, geo)
        await self.set(key, results, ttl_seconds=self.settings.cache_ttl_recommendation_sec)

"""Pydantic Schema —— API 请求/响应模型。

职责：
  - API 入参校验（防止注入/滥用）
  - API 出参格式（与前端契约）
  - 敏感字段脱敏（用户画像不返回原始数据）
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# 请求模型
# ============================================================================


class RecommendRequest(BaseModel):
    """推荐查询请求。"""

    city: Optional[str] = Field(default=None, max_length=100, description="城市名，如 '成都'")
    cuisine: Optional[str] = Field(default=None, max_length=100, description="菜系，如 '川菜'")
    dietary_restrictions: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="忌口/过敏列表，如 ['花生', '牛奶']",
    )
    exclude_chain: bool = Field(default=True, description="排除连锁（默认 true）")
    max_items: int = Field(default=10, ge=1, le=50, description="最多返回条数")

    @field_validator("city", "cuisine")
    @classmethod
    def strip_noise(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        # 防止 SQL/HTML 注入（简单防护层）
        dangerous = ["--", ";", "<", ">", "{{", "}}", "__import__", "DROP TABLE"]
        for d in dangerous:
            if d.lower() in v.lower():
                raise ValueError(f"非法字符: {d}")
        return v if v else None


class ChatRequest(BaseModel):
    """AI 对话请求。"""

    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = Field(default=None, max_length=100)
    user_restrictions: list[str] = Field(default_factory=list, max_length=10)
    max_rounds: int = Field(default=4, ge=1, le=6, description="最大收敛轮次（架构约束 ≤ 4）")


class SearchRequest(BaseModel):
    """发现页/开放式搜索。"""

    city: Optional[str] = Field(default=None, max_length=100)
    max_items: int = Field(default=20, ge=1, le=50)


class DishDetailRequest(BaseModel):
    dish_id: str = Field(..., max_length=36)


class EventRequest(BaseModel):
    """行为埋点事件。"""

    user_hash: str = Field(..., max_length=64, pattern=r"^[a-f0-9]{64}$")
    event_name: str = Field(..., max_length=100)
    entity_id: Optional[str] = Field(default=None, max_length=36)
    properties: dict = Field(default_factory=dict)


# ============================================================================
# 响应模型
# ============================================================================


class DishCard(BaseModel):
    """单条菜品卡片（列表/推荐用）。"""

    dish_id: str
    name: str
    evidence_tag: str = Field(description="🟢/🟡/🔴")
    locality_score: float
    locality_level: str
    presentation: str = Field(description="best/priority/standard/folded")
    source_name: str
    verified_at: Optional[datetime] = None
    cuisine_name: Optional[str] = None
    geo_name: Optional[str] = None


class RecommendResponse(BaseModel):
    """推荐查询响应。"""

    recommendations: list[DishCard]
    count: int
    notes: list[str] = Field(
        default_factory=list,
        description="诚实降级提示（如 '部分信息可能未及时更新'）",
    )
    disclaimer: str = Field(
        default="推荐结果带来源和核验时间，但数据源覆盖度有限。请结合自身情况判断。",
        description="能力档位声明（固定模板）",
    )


class DishDetailResponse(BaseModel):
    """菜品详情页。"""

    dish_id: str
    name: str
    description: Optional[str]
    cuisine_name: Optional[str]
    geo_name: Optional[str]

    # ---- 核心架构字段 ----
    locality_level: str
    cuisine_evidence_level: str
    locality_score: float
    admission_result: str

    # ---- 过敏原（安全敏感）----
    common_allergens: list[str]
    allergen_info_complete: bool

    # ---- 数据源 ----
    source_name: str
    source_version: Optional[str]
    verified_at: datetime
    data_conflict_note: Optional[str] = None

    # ---- 展示层 ----
    presentation: str
    evidence_tag: str


class ChatResponse(BaseModel):
    """AI 对话响应。"""

    text: str
    recommendations: list[DishCard]
    honesty_flags: list[str] = Field(default_factory=list)
    capability_statement: str
    commercial_disclosure: str
    conversation_id: Optional[str] = None
    is_final: bool = True  # 是否已收敛


class HealthResponse(BaseModel):
    status: str = "ok"
    architecture_assertions: dict[str, str] = {}

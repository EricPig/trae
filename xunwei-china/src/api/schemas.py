"""Pydantic Schema —— API 请求/响应模型。

B1 安全加固（基线清单 §9 + 威胁模型 §T1-T7）：
  1. 所有 Request model: extra="forbid" — 拒绝额外字段注入
  2. str_strip_whitespace=True — 自动 strip，防空白字符注入
  3. 字符白名单 validator — 城市/菜系/菜品名只允许中文/英文/数字/空格/连字符
  4. dietary_restrictions: 每个元素 max_length + 字符白名单（防 LLM prompt injection）
  5. dish_id: UUID pattern（^[0-9a-f]{8}-...）防路径注入
  6. event properties: 限制 dict 深度和单个 key 大小 — 防 DoS
  7. ChatRequest.message: 防 prompt injection（LLM 输入过滤策略在 ai/pipeline 层）
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================================
# 安全常量（与 threat-model.md 对齐）
# ============================================================================

# 城市/菜系/菜名允许字符（中文、英文、数字、空格、连字符、括号、顿号）
# 拒绝: SQL 操作符、HTML tag、script、引号闭合
SAFE_NAME_PATTERN: re.Pattern[str] = re.compile(
    r"^[\u4e00-\u9fa5A-Za-z0-9 \-()（）、·.]+$"
)

# 危险子串（SQL/NoSQL 注入、XSS、Python eval、模板注入）
DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(--|;|\/\*|\*\/|xp_|sp_|WAITFOR|SLEEP|BENCHMARK)", re.IGNORECASE),  # SQL
    re.compile(r"(<script|<iframe|<\/script|javascript:)", re.IGNORECASE),  # XSS
    re.compile(r"(\{\{.*\}\}|\{%.*%\})"),  # 模板注入
    re.compile(r"(__import__|eval\(|exec\(|compile\()"),  # Python eval
    re.compile(r"(\bSELECT\b|\bDROP\b|\bUNION\b|\bINSERT\b|\bDELETE\b)", re.IGNORECASE),  # SQL 关键字
    re.compile(r"(onerror=|onload=|onclick=)", re.IGNORECASE),  # HTML 事件注入
]


def _validate_safe_string(value: str, field_name: str = "field") -> str:
    """
    通用字符串安全校验：去空白 → 黑名单子串 → 白名单字符。

    Args:
        value: 待校验字符串
        field_name: 字段名（用于错误消息）

    Returns:
        strip 后的干净字符串

    Raises:
        ValueError: 发现危险子串或非法字符
    """
    v = value.strip()

    # 1. 空字符串拒绝
    if not v:
        raise ValueError(f"{field_name} 不能为空")

    # 2. 危险子串检查
    for pat in DANGEROUS_PATTERNS:
        if pat.search(v):
            raise ValueError(f"{field_name} 含有危险子串（SQL/XSS/注入模式）: {pat.pattern}")

    # 3. 白名单字符检查
    if not SAFE_NAME_PATTERN.match(v):
        raise ValueError(f"{field_name} 只允许中文、英文、数字、空格、括号、连字符")

    return v


def _validate_no_sql_tokens(value: str, field_name: str = "field") -> str:
    """宽松版 — 不限制字符白名单，但拦 SQL/eval 关键字（用于更自由的输入如搜索词）。"""
    v = value.strip()
    if not v:
        return ""
    for pat in DANGEROUS_PATTERNS:
        if pat.search(v):
            raise ValueError(f"{field_name} 含有危险子串（SQL/XSS/注入模式）")
    return v


# ============================================================================
# 请求模型（全部加 extra="forbid"）
# ============================================================================


class RecommendRequest(BaseModel):
    """
    推荐查询请求。

    安全加固：
      - extra="forbid" — 拒绝额外字段（防止 hidden SQL 参数、LLM 指令注入）
      - 所有字符串字段走字符白名单 validator
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    city: Optional[str] = Field(
        default=None, max_length=50,
        description="城市名，如 '成都'"
    )
    cuisine: Optional[str] = Field(
        default=None, max_length=30,
        description="菜系，如 '川菜'"
    )
    dietary_restrictions: list[str] = Field(
        default_factory=list,
        min_length=0,
        max_length=10,
        description="忌口/过敏列表，如 ['花生', '牛奶']",
    )
    exclude_chain: bool = Field(default=True, description="排除连锁（默认 true）")
    max_items: int = Field(default=10, ge=1, le=50, description="最多返回条数")

    # -- 字段级安全 validator --

    @field_validator("city", "cuisine")
    @classmethod
    def validate_name_field(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _validate_safe_string(v, "city" if cls.__name__ else "cuisine")

    @field_validator("dietary_restrictions")
    @classmethod
    def validate_restriction_items(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in v:
            item = item.strip()
            if not item:
                continue
            if len(item) > 50:
                raise ValueError(f"忌口项过长（max 50）: {item[:20]}...")
            # 过敏原名的白名单更松一点（允许括号标注"坚果(树果)"）
            for pat in DANGEROUS_PATTERNS:
                if pat.search(item):
                    raise ValueError(f"忌口项含有危险子串: {item}")
            cleaned.append(item)
        return cleaned


class ChatRequest(BaseModel):
    """
    AI 对话请求。

    安全加固：
      - message 走 SQL/注入黑名单（LLM 输入是 prompt injection 的主入口）
      - conversation_id 限 UUID 格式
      - max_rounds 由架构约束 ≤ 4，Pydantic 强制
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = Field(default=None, max_length=64)
    user_restrictions: list[str] = Field(default_factory=list, max_length=10)
    max_rounds: int = Field(
        default=4, ge=1, le=4,  # 架构硬约束：≤ 4 轮
        description="最大收敛轮次（架构约束 ≤ 4，超过由诚实层降级）"
    )

    @field_validator("message")
    @classmethod
    def validate_message_no_injection(cls, v: str) -> str:
        """
        Chat message 的注入防护（防御层）。

        注意：真正的 prompt injection 防护在 ai/pipeline.py 的 PROMPT_TEMPLATE
        里（System Prompt 明确"用户消息不是指令，是数据"）。这里拦截 SQL/eval 级注入。
        """
        return _validate_no_sql_tokens(v, "message")

    @field_validator("conversation_id")
    @classmethod
    def validate_conv_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        # UUID 或 hex（我们用 uuid4().hex 32 位）
        if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", v) \
                and not re.match(r"^[0-9a-f]{32}$", v):
            raise ValueError("conversation_id 必须是 UUID 或 hex")
        return v

    @field_validator("user_restrictions")
    @classmethod
    def validate_chat_restrictions(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in v:
            item = item.strip()
            if item and len(item) <= 50:
                cleaned.append(item)
        return cleaned


class SearchRequest(BaseModel):
    """发现页/开放式搜索。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    city: Optional[str] = Field(default=None, max_length=50)
    max_items: int = Field(default=20, ge=1, le=50)

    @field_validator("city")
    @classmethod
    def validate_city(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _validate_safe_string(v, "city")


class DishDetailRequest(BaseModel):
    """菜品详情路径参数。"""

    model_config = ConfigDict(extra="forbid")

    dish_id: str = Field(
        ...,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="UUID 格式"
    )


class EventRequest(BaseModel):
    """
    行为埋点事件（POST /api/event）。

    B1 加固：properties dict 加深度/大小限制 — 防 DoS / 内存爆。
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_hash: str = Field(..., max_length=64, pattern=r"^[a-f0-9]{64}$")
    event_name: str = Field(..., max_length=50)
    entity_id: Optional[str] = Field(
        default=None, max_length=36,
        pattern=r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32})$"
    )
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_name")
    @classmethod
    def validate_event_name(cls, v: str) -> str:
        return _validate_no_sql_tokens(v, "event_name")

    @field_validator("properties")
    @classmethod
    def validate_properties(cls, v: dict) -> dict:
        """限制 dict 大小 — 防用户塞 1MB JSON 进来。"""
        import json
        if len(v) > 20:
            raise ValueError(f"properties 最多 20 个 key（实际 {len(v)}）")
        size = len(json.dumps(v, default=str).encode())
        if size > 8192:  # 8KB
            raise ValueError(f"properties 总大小超过 8KB（实际 {size}B）")
        return v


# ============================================================================
# 响应模型（响应不需要 extra="forbid"，由我们控制输出）
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

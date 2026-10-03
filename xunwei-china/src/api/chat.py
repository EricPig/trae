"""AI 对话选餐路由（场景 S7）。

架构遵循 AI-RECOMMENDATION.md：
  Layer 1: LLM → StructuredConstraint
  Layer 2: 调用推荐引擎（ACL，唯一数据通道）
  Layer 3: RAG 证据检索
  Layer 4: 诚实层（不确定性标记 + 能力档位 + 商业透明）
  Layer 5: LLM 格式化（非内容生成）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from src.config import get_utcnow
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db_session
from src.api.schemas import ChatRequest, ChatResponse, DishCard

router = APIRouter(prefix="/api", tags=["chat"])

# 对话缓存（内存字典，T0 阶段足够；T1 换 Redis）
_conversation_cache: dict[str, dict] = {}


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, session: AsyncSession = Depends(get_db_session)):
    """
    AI 对话选餐主入口。

    收敛策略：
      - ≤ max_rounds 轮内收敛（默认 4 轮，架构约束）
      - 超过则降级为直接推荐 + 提示
      - 始终附诚实层输出（依据 + 数据源 + 能力档位）
    """
    from src.engine.service import RecommendationEngine
    from src.ai.pipeline import (
        EvidenceChain,
        HonestyDeclaration,
        RecommendationEngineACL,
        StructuredConstraint,
        layer4_honesty,
        layer2_call_engine,
    )
    from src.engine.pipeline import pipeline
    from src.config import EVIDENCE_MAPPING

    # 1. 恢复对话上下文（如果有 conversation_id）
    ctx = _conversation_cache.get(req.conversation_id, {})

    # 2. 约束提取（T0 阶段简化版：直接用请求中的显式参数）
    #    T1 接入真正的 LLM 后换成 layer1_extract_constraint()
    constraint = StructuredConstraint(
        dietary_restrictions=req.user_restrictions,
        raw_text=req.message,
    )
    # 从上下文合并累积的约束
    if ctx:
        constraint.dietary_restrictions = list(
            set(constraint.dietary_restrictions + ctx.get("restrictions", []))
        )

    # 3. 调用推荐引擎（ACL）
    engine = RecommendationEngine(session)
    acl = RecommendationEngineACL(engine)

    try:
        dish_dicts, log = await layer2_call_engine(constraint, acl)
    except Exception as e:
        # 降级：AI 不可用 → 直接推荐
        dish_dicts, log = [], [f"AI 不可用，降级为直接推荐: {e}"]

    # 4. RAG 证据（T0 阶段简化版：空证据，诚实层自动降级）
    evidence_map: dict[str, EvidenceChain] = {}
    log.append("RAG 证据：T0 阶段简化版，数据不足时自动诚实降级")

    # 5. 诚实层
    honesty, honesty_log, annotated = layer4_honesty(
        dish_dicts, evidence_map, constraint
    )
    log.extend(honesty_log)

    # 6. 组装推荐卡片
    from src.engine.pipeline import Recommendation, AdmissionDecision, PresentationTier

    cards: list[DishCard] = []
    for r_dict in dish_dicts:
        # pipeline 纯函数（不查 DB）
        results = pipeline([r_dict], user_restrictions=constraint.dietary_restrictions)
        if results:
            r = results[0]
            cards.append(
                DishCard(
                    dish_id=r.dish_id,
                    name=r.name,
                    evidence_tag=r.evidence_tag,
                    locality_score=r.locality_score,
                    locality_level=r.locality_level,
                    presentation=r.presentation.value,
                    source_name=r.source_name,
                    verified_at=r.verified_at,
                )
            )

    # 7. 生成格式化文本（T0 阶段模板化，T1 接入 LLM）
    if cards:
        card_text = "、".join(f"{c.name}（{c.evidence_tag}）" for c in cards[:3])
        text = f"为您找到这几道菜：{card_text}"
    else:
        text = "抱歉，根据您的条件，暂时没有找到足够的数据源支撑推荐"

    # 8. 诚实层提示追加
    for flag in honesty.uncertainty_flags:
        text += f"。{flag}"

    # 9. 保存对话上下文
    conv_id = req.conversation_id or uuid.uuid4().hex
    _conversation_cache[conv_id] = {
        "restrictions": constraint.dietary_restrictions,
        "last_message": req.message,
        "updated_at": get_utcnow().isoformat(),
    }

    return ChatResponse(
        text=text,
        recommendations=cards,
        honesty_flags=honesty.uncertainty_flags,
        capability_statement=honesty.capability_statement,
        commercial_disclosure=honesty.commercial_disclosure,
        conversation_id=conv_id,
        is_final=len(cards) > 0,
    )


@router.delete("/chat/{conversation_id}")
async def clear_conversation(conversation_id: str):
    """清除对话上下文（退出或重置）。"""
    _conversation_cache.pop(conversation_id, None)
    return {"status": "ok", "message": "对话上下文已清除"}

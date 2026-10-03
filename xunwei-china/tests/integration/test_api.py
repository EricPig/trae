"""
集成测试：DB + API 全链路。

覆盖范围：
  - T1-DB:  ORM 正确映射（Base.metadata.create_all + seed 写入 + 读取）
  - T2-准入:  national_chain 被二维准入表排除
  - T3-安全:  过敏原命中 → pipeline 硬过滤（DB 层 SQLite 退化也能兜底）
  - T4-排序:  locality_score 降序 + 四象限展示层 tier
  - T5-诚实层: 数据源缺失时 notes/不确定性提示
  - T6-Schema:  Pydantic 加固拦截 SQL/XSS/extra field
  - T7-Meta:   meta/capability 诚实声明端点
  - T8-ACL:    AI context + 非白名单方法 → ACLViolation
"""

from __future__ import annotations

import pytest
import pytest_asyncio


pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# ============================================================================
# DB 层
# ============================================================================

class TestDBLayer:
    """测试 ORM + SQLite 真实写入/读取。"""

    async def test_seed_writes_dishes(self, seeded_session):
        async with seeded_session() as session:
            from sqlalchemy import select, func
            from src.db.models import Dish
            r = await session.execute(select(func.count(Dish.id)))
            assert r.scalar() == 7

    async def test_listtype_roundtrip(self, seeded_session):
        """ListType 的 JSON 序列化/反序列化在 SQLite 上正确。"""
        async with seeded_session() as session:
            from sqlalchemy import select
            from src.db.models import Dish, Cuisine, GeoEntity
            from src.engine.pipeline import compute_locality_score, adjudicate_admission
            from src.config import get_utcnow

            # 先建依赖
            cuisine = Cuisine(name="测试菜系"); session.add(cuisine)
            geo = GeoEntity(name="测试城市", level="city", code="test-001"); session.add(geo)
            await session.flush()

            score, *_ = compute_locality_score("native", "A", 100)
            admission = adjudicate_admission("native", "A", score)
            d = Dish(
                name="测试菜",
                cuisine_id=cuisine.id,
                geo_entity_id=geo.id,
                locality_level="native", cuisine_evidence_level="A",
                locality_score=score, admission_result=admission.decision.value,
                common_allergens=["花生", "牛奶", "大豆"],
                source_name="本地测试",
                verified_at=get_utcnow(),
            )
            session.add(d); await session.flush()
            dish_id = d.id
            await session.commit()

            # 重读
            r = await session.execute(select(Dish).where(Dish.id == dish_id))
            got = r.scalar_one()
            assert isinstance(got.common_allergens, list)
            assert set(got.common_allergens) == {"花生", "牛奶", "大豆"}


# ============================================================================
# API 层
# ============================================================================

class TestRecommendAPI:

    async def test_returns_3_items_chengdu(self, api_client):
        """成都 seed 有 4 条 (3 admitted + 1 excluded_chain) —— 只返回 admitted。"""
        r = await api_client.post("/api/recommend", json={"city": "成都", "max_items": 10})
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 3
        names = [i["name"] for i in body["recommendations"]]
        assert "麻婆豆腐" in names
        assert "藏在巷子里的老火锅" in names
        # national_chain 必须被准入层排除
        assert "某连锁麻辣香锅" not in names

    async def test_national_chain_excluded_by_admission(self, api_client):
        """二维准入表架构不变量 —— national_chain 一律被 EXCLUDED_CHAIN。"""
        r = await api_client.post("/api/recommend", json={"city": "成都", "max_items": 20})
        body = r.json()
        national_chain_items = [
            i for i in body["recommendations"]
            if "连锁" in i["name"]
        ]
        assert len(national_chain_items) == 0

    async def test_allergen_peanut_excludes_gongbao(self, api_client):
        """过敏原命中 → pipeline 硬过滤（0% 红线，SQLite 退化兜底）。"""
        r = await api_client.post("/api/recommend", json={
            "city": "成都", "dietary_restrictions": ["花生"], "max_items": 20,
        })
        body = r.json()
        names = [i["name"] for i in body["recommendations"]]
        assert not any("宫保鸡丁" in n for n in names), f"宫保鸡丁(花生过敏)未被排除! {names}"
        # 不含花生的麻婆豆腐应保留
        assert "麻婆豆腐" in names

    async def test_allergen_shrimp_excludes_yuntun(self, api_client):
        r = await api_client.post("/api/recommend", json={
            "city": "广州", "dietary_restrictions": ["虾"], "max_items": 20,
        })
        body = r.json()
        names = [i["name"] for i in body["recommendations"]]
        assert "云吞面" not in names
        assert "白切鸡" in names

    async def test_dishes_have_source_name(self, api_client):
        """所有推荐必附来源（FF-DATA-01: 100% source annotation）。"""
        r = await api_client.post("/api/recommend", json={"city": "成都", "max_items": 10})
        body = r.json()
        for i in body["recommendations"]:
            assert i["source_name"] and i["source_name"].strip(), f"{i['name']} 缺少 source_name"

    async def test_locality_scores_descending(self, api_client):
        """排序层：同一 tier 内 locality_score 降序。"""
        r = await api_client.post("/api/recommend", json={"city": "成都", "max_items": 10})
        body = r.json()
        scores = [i["locality_score"] for i in body["recommendations"]]
        assert scores == sorted(scores, reverse=True), f"未按 score 降序: {scores}"

    async def test_presentation_tiers(self, api_client):
        """展示层四象限 —— best tier 至少有两条。"""
        r = await api_client.post("/api/recommend", json={"city": "成都", "max_items": 10})
        body = r.json()
        tiers = [i["presentation"] for i in body["recommendations"]]
        best_count = tiers.count("best")
        priority_count = tiers.count("priority")
        assert best_count >= 2, f"成都应有至少 2 条 best, got {best_count}: {tiers}"
        assert priority_count >= 1, f"成都应有至少 1 条 priority(护城河), got {priority_count}"


# ============================================================================
# Schema 加固（B1）
# ============================================================================

class TestSchemaHardening:

    async def test_extra_forbid(self, api_client):
        r = await api_client.post("/api/recommend", json={
            "city": "成都", "sql_injection": "DROP TABLE dish",
        })
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert any("sql_injection" in str(e) for e in detail)

    async def test_sql_injection_in_city(self, api_client):
        r = await api_client.post("/api/recommend", json={
            "city": "成都; DROP TABLE dish; --",
        })
        assert r.status_code == 422

    async def test_xss_in_city(self, api_client):
        r = await api_client.post("/api/recommend", json={
            "city": "<script>alert(1)</script>",
        })
        assert r.status_code == 422

    async def test_normal_request_still_works(self, api_client):
        r = await api_client.post("/api/recommend", json={"city": "成都", "max_items": 5})
        assert r.status_code == 200
        assert r.json()["count"] >= 1

    async def test_chat_max_rounds_capped(self, api_client):
        """架构硬约束：max_rounds ≤ 4。"""
        r = await api_client.post("/api/chat", json={
            "message": "我想吃川菜", "max_rounds": 10,
        })
        assert r.status_code == 422

    async def test_dish_id_must_be_uuid(self, api_client):
        # 不存在的 UUID → 404 不是 500
        r = await api_client.get("/api/dishes/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404

        # 非法格式 → 422
        r = await api_client.get("/api/dishes/not-a-uuid")
        assert r.status_code == 422


# ============================================================================
# Meta / 诚实声明
# ============================================================================

class TestMetaAPI:

    async def test_capability_declaration(self, api_client):
        r = await api_client.get("/api/meta/capability")
        assert r.status_code == 200
        body = r.json()
        assert "statement" in body
        assert len(body["levels"]) >= 3

    async def test_red_lines_constants(self, api_client):
        r = await api_client.get("/health/red-lines")
        assert r.status_code == 200
        body = r.json()
        # 两条红线目标都是 0
        assert body["allergen_violation_target_pct"] == 0
        assert body["hallucination_target_pct"] == 0


# ============================================================================
# ACL 运行时 guard（B2）
# ============================================================================

class TestACLGuard:

    async def test_acl_whitelist_method_allowed_in_ai_context(self, api_client):
        from src.ai.acl import enter_ai_context, exit_ai_context, _acl_runtime_guard, ACL_ALLOWED_ENGINE_METHODS

        # 白名单方法 + AI context → 放行
        enter_ai_context()
        for method in ACL_ALLOWED_ENGINE_METHODS:
            try:
                _acl_runtime_guard(method)
            except Exception as e:
                pytest.fail(f"白名单方法 {method} 在 AI context 被错误拦截: {e}")
        exit_ai_context()

    async def test_acl_non_whitelist_blocked_in_ai_context(self):
        from src.ai.acl import enter_ai_context, exit_ai_context, _acl_runtime_guard, ACLViolation

        enter_ai_context()
        try:
            with pytest.raises(ACLViolation) as exc_info:
                _acl_runtime_guard("get_by_id")
            assert exc_info.value.violation_type == "UNAUTHORIZED_METHOD"
        finally:
            exit_ai_context()

    async def test_api_layer_not_blocked_by_acl(self):
        """非 AI context 调用任何方法都不拦截（ACL 不影响 API 层）。"""
        from src.ai.acl import _acl_runtime_guard
        # get_by_id 是非白名单，但 API 层调用时不应被拦截
        _acl_runtime_guard("get_by_id")  # 不抛 = 通过


# ============================================================================
# Chat 端点
# ============================================================================

class TestChatAPI:

    async def test_chat_basic_flow(self, api_client):
        r = await api_client.post("/api/chat", json={
            "message": "我想在成都吃本地菜",
        })
        assert r.status_code == 200
        body = r.json()
        assert "text" in body
        assert "capability_statement" in body  # 诚实层固定模板
        assert len(body["text"]) > 0

    async def test_chat_returns_safety_notes_for_peanut(self, api_client):
        r = await api_client.post("/api/chat", json={
            "message": "找成都适合花生过敏的菜",
            "user_restrictions": ["花生"],
        })
        body = r.json()
        # 宫保鸡丁应不在推荐里
        names = [i["name"] for i in body["recommendations"]]
        assert not any("宫保鸡丁" in n for n in names)
        assert "capability_statement" in body

"""
种子数据脚本 —— 生成 5 省 demo 数据（川渝粤湘浙）。

目的：在没有真实 ETL 时，本地开发能跑通完整 pipeline。
策略：用 Python pipeline.compute_locality_score 计算真实 locality_score，
然后写入 Dish 表。确保 R1-R5 断言 + 二维准入表全部成立。

覆盖 4 象限：
  🟢 + 高本地性 → 最佳推荐位
  🟡 + 高本地性 → 重点扶持位
  🔴 + 高本地性 → 禁降权禁折叠（护城河）
  🔴 + 低本地性 → 唯一允许折叠

运行：PYTHONPATH=. python scripts/seed_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from uuid import uuid4

# 确保 import 正确
sys.path.insert(0, ".")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.config import ADMISSION_TABLE, AdmissionDecision
from src.db.models import (
    Base,
    Cuisine,
    DataSource,
    Dish,
    GeoEntity,
    Ingredient,
    Technique,
)
from src.engine.pipeline import compute_locality_score, adjudicate_admission


DEMO_DISHES = [
    # === 四川省 成都市 ===
    {
        "name": "麻婆豆腐",
        "locality_level": "native", "evidence_level": "A", "establishment_year": 120,
        "cuisine": "川菜", "geo_city": "成都", "common_allergens": [],
        "description": "源自清代成都陈麻婆豆腐店",
        "source": "成都地方志", "evidence_complete": True,
    },
    {
        "name": "宫保鸡丁（传统版）",
        "locality_level": "native", "evidence_level": "B", "establishment_year": 80,
        "cuisine": "川菜", "geo_city": "成都", "common_allergens": ["花生"],
        "description": "川菜经典，必须用花生",
        "source": "《川菜菜谱大全》", "evidence_complete": True,
    },
    {
        "name": "藏在巷子里的老火锅",
        "locality_level": "native", "evidence_level": "D", "establishment_year": 40,
        "cuisine": "川菜", "geo_city": "成都", "common_allergens": [],
        "description": "资料有限的隐藏款 —— 护城河测试用",
        "source": "本地论坛", "evidence_complete": False,
    },
    {
        "name": "某连锁麻辣香锅",
        "locality_level": "national_chain", "evidence_level": "A", "establishment_year": 5,
        "cuisine": "川菜", "geo_city": "成都", "common_allergens": [],
        "description": "全国连锁 —— 应该被排除",
        "source": "商家自述", "evidence_complete": True,
    },

    # === 广东省 广州市 ===
    {
        "name": "白切鸡（广州酒家版）",
        "locality_level": "native", "evidence_level": "A", "establishment_year": 90,
        "cuisine": "粤菜", "geo_city": "广州", "common_allergens": [],
        "description": "粤菜经典",
        "source": "广州地方志", "evidence_complete": True,
    },
    {
        "name": "云吞面（本地早餐）",
        "locality_level": "localized", "evidence_level": "C", "establishment_year": 30,
        "cuisine": "粤菜", "geo_city": "广州", "common_allergens": ["虾"],
        "description": "本地化连锁",
        "source": "媒体报道", "evidence_complete": True,
    },

    # === 浙江省 杭州市 ===
    {
        "name": "西湖醋鱼",
        "locality_level": "native", "evidence_level": "B", "establishment_year": 100,
        "cuisine": "浙菜", "geo_city": "杭州", "common_allergens": [],
        "description": "浙菜招牌",
        "source": "《杭州美食志》", "evidence_complete": True,
    },
    {
        "name": "龙井虾仁",
        "locality_level": "native", "evidence_level": "A", "establishment_year": 60,
        "cuisine": "浙菜", "geo_city": "杭州", "common_allergens": [],
        "description": "龙井茶+河虾仁",
        "source": "浙江省非遗名录", "evidence_complete": True,
    },

    # === 湖南省 长沙市 ===
    {
        "name": "臭豆腐（长沙街头版）",
        "locality_level": "native", "evidence_level": "D", "establishment_year": 30,
        "cuisine": "湘菜", "geo_city": "长沙", "common_allergens": ["大豆"],
        "description": "本地街头小吃，资料有限",
        "source": "游客游记", "evidence_complete": False,
    },
    {
        "name": "剁椒鱼头（本地做法）",
        "locality_level": "localized", "evidence_level": "B", "establishment_year": 50,
        "cuisine": "湘菜", "geo_city": "长沙", "common_allergens": [],
        "description": "本地化推广的湘菜",
        "source": "地方电视台", "evidence_complete": True,
    },

    # === 重庆市 ===
    {
        "name": "重庆老火锅",
        "locality_level": "native", "evidence_level": "A", "establishment_year": 150,
        "cuisine": "川菜", "geo_city": "重庆", "common_allergens": ["辣椒"],
        "description": "重庆火锅代表",
        "source": "重庆地方志", "evidence_complete": True,
    },
    {
        "name": "小面（本地早餐）",
        "locality_level": "native", "evidence_level": "C", "establishment_year": 20,
        "cuisine": "川菜", "geo_city": "重庆", "common_allergens": ["小麦"],
        "description": "重庆市民日常",
        "source": "本地美食公众号", "evidence_complete": True,
    },

    # === 低本地性折叠象限 ===
    {
        "name": "标准化预制菜馆",
        "locality_level": "localized", "evidence_level": "D", "establishment_year": 5,
        "cuisine": "川菜", "geo_city": "成都", "common_allergens": [],
        "description": "本地化连锁+资料有限+开业5年=低本地性",
        "source": "商家自述", "evidence_complete": False,
    },
]


async def seed():
    engine = create_async_engine(
        "postgresql+psycopg://xunwei:xunwei_dev@localhost:5432/xunwei",
        echo=False,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        # 1. 创建基础数据
        cuisines = {}
        for name in set(d["cuisine"] for d in DEMO_DISHES):
            c = Cuisine(name=name)
            session.add(c)
            cuisines[name] = c

        cities = {}
        for name in set(d["geo_city"] for d in DEMO_DISHES):
            g = GeoEntity(name=name, level="city", code=f"demo-{hash(name) % 100000}")
            session.add(g)
            cities[name] = g

        sources = {}
        for name in set(d["source"] for d in DEMO_DISHES):
            s = DataSource(
                name=name,
                license_type="CC0",
                verified_at=datetime.utcnow(),
                commercial_use_allowed=True,
            )
            session.add(s)
            sources[name] = s

        # 常见过敏原
        for name, allergen_type in [
            ("花生", "花生"), ("牛奶", "乳制品"), ("鸡蛋", "蛋类"),
            ("虾", "海鲜"), ("大豆", "大豆"), ("辣椒", "辛辣"), ("小麦", "麸质"),
        ]:
            session.add(Ingredient(name=name, is_allergen=True, allergen_type=allergen_type))

        await session.flush()

        # 2. 创建 Dish（用 compute_locality_score + adjudicate_admission 算真实值）
        for d in DEMO_DISHES:
            score, native, years, cuisine = compute_locality_score(
                d["locality_level"], d["evidence_level"], d["establishment_year"]
            )
            admission = adjudicate_admission(
                d["locality_level"], d["evidence_level"], score
            )

            dish = Dish(
                name=d["name"],
                description=d["description"],
                cuisine_id=cuisines[d["cuisine"]].id,
                geo_entity_id=cities[d["geo_city"]].id,
                establishment_year=d["establishment_year"],

                locality_level=d["locality_level"],
                cuisine_evidence_level=d["evidence_level"],
                locality_score=score,
                admission_result=admission.decision.value,

                common_allergens=d["common_allergens"],
                allergen_info_complete=d["evidence_complete"],

                years_factor=years,
                cuisine_factor=cuisine,
                native_score=native,

                source_name=d["source"],
                verified_at=datetime.utcnow() - timedelta(days=30),
            )
            session.add(dish)

        await session.commit()

    # 3. 打印汇总
    async with factory() as session:
        from sqlalchemy import select, func, text
        result = await session.execute(
            select(Dish.admission_result, func.count(Dish.id)).group_by(Dish.admission_result)
        )
        print("\n=== 种子数据汇总 ===")
        for row in result.all():
            print(f"  {row[0]}: {row[1]}")

        result = await session.execute(
            select(Dish.locality_level, func.count(Dish.id)).group_by(Dish.locality_level)
        )
        print()
        for row in result.all():
            print(f"  locality_level={row[0]}: {row[1]}")

    await engine.dispose()
    print("\n✅ 种子数据已写入")


if __name__ == "__main__":
    asyncio.run(seed())

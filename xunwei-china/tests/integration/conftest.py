"""集成测试 fixture —— FastAPI TestClient + SQLite + seed 数据。"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select

# 让 scripts/ 目录可见（seed_demo 用）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ---------------------------------------------------------------------------
# SQLite fixture（每个用例独立 DB 文件，隔离）
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def sqlite_session() -> async_sessionmaker[AsyncSession]:
    """每测试一个临时 SQLite 文件，避免 fixture 间数据泄漏。"""
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name
    url = f"sqlite+aiosqlite:///{db_path}"

    from src.db.models import Base

    engine = create_async_engine(
        url,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    yield factory

    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# seed fixture —— 复用 seed_demo.py 的逻辑但用 fixture 引擎
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def seeded_session(sqlite_session) -> async_sessionmaker[AsyncSession]:
    """
    在 sqlite_session 的基础上写入 demo 数据。

    直接内联 seed 逻辑（不跑 scripts/seed_demo.py），避免进程级单例冲突。
    """
    from src.db.models import Base, Cuisine, Dish, GeoEntity, DataSource, Ingredient
    from src.engine.pipeline import compute_locality_score, adjudicate_admission
    from src.config import get_utcnow

    DEMO_DISHES = [
        {"name": "麻婆豆腐", "locality_level": "native", "evidence_level": "A",
         "establishment_year": 120, "cuisine": "川菜", "geo_city": "成都",
         "common_allergens": [], "source": "成都地方志", "evidence_complete": True,
         "description": "源自清代成都陈麻婆豆腐店"},
        {"name": "宫保鸡丁", "locality_level": "native", "evidence_level": "B",
         "establishment_year": 80, "cuisine": "川菜", "geo_city": "成都",
         "common_allergens": ["花生"], "source": "《川菜菜谱大全》", "evidence_complete": True,
         "description": "川菜经典"},
        {"name": "藏在巷子里的老火锅", "locality_level": "native", "evidence_level": "D",
         "establishment_year": 40, "cuisine": "川菜", "geo_city": "成都",
         "common_allergens": [], "source": "本地论坛", "evidence_complete": False,
         "description": "资料有限的隐藏款"},
        {"name": "某连锁麻辣香锅", "locality_level": "national_chain", "evidence_level": "A",
         "establishment_year": 5, "cuisine": "川菜", "geo_city": "成都",
         "common_allergens": [], "source": "商家自述", "evidence_complete": True,
         "description": "全国连锁 —— 应该被排除"},
        {"name": "白切鸡", "locality_level": "native", "evidence_level": "A",
         "establishment_year": 90, "cuisine": "粤菜", "geo_city": "广州",
         "common_allergens": [], "source": "广州地方志", "evidence_complete": True,
         "description": "粤菜经典"},
        {"name": "云吞面", "locality_level": "localized", "evidence_level": "C",
         "establishment_year": 30, "cuisine": "粤菜", "geo_city": "广州",
         "common_allergens": ["虾"], "source": "媒体报道", "evidence_complete": True,
         "description": "本地化连锁"},
        {"name": "重庆老火锅", "locality_level": "native", "evidence_level": "A",
         "establishment_year": 150, "cuisine": "川菜", "geo_city": "重庆",
         "common_allergens": ["辣椒"], "source": "重庆地方志", "evidence_complete": True,
         "description": "重庆火锅代表"},
    ]

    async with sqlite_session() as session:
        cuisines = {}
        for n in sorted({d["cuisine"] for d in DEMO_DISHES}):
            c = Cuisine(name=n); session.add(c); cuisines[n] = c

        cities = {}
        for n in sorted({d["geo_city"] for d in DEMO_DISHES}):
            g = GeoEntity(name=n, level="city", code=f"demo-{abs(hash(n)) % 100000:05d}")
            session.add(g); cities[n] = g

        sources = {}
        for n in sorted({d["source"] for d in DEMO_DISHES}):
            s = DataSource(name=n, license_type="CC0", verified_at=get_utcnow(),
                           commercial_use_allowed=True)
            session.add(s); sources[n] = s

        # 关键：flush 让 SQLAlchemy 分配主键 —— 否则 cuisines[n].id 是 None
        await session.flush()

        now = get_utcnow()
        for d in DEMO_DISHES:
            score, native, years, cuisine = compute_locality_score(
                d["locality_level"], d["evidence_level"], d["establishment_year"])
            admission = adjudicate_admission(
                d["locality_level"], d["evidence_level"], score)
            dish = Dish(
                name=d["name"], description=d["description"],
                cuisine_id=cuisines[d["cuisine"]].id,
                geo_entity_id=cities[d["geo_city"]].id,
                establishment_year=d["establishment_year"],
                locality_level=d["locality_level"],
                cuisine_evidence_level=d["evidence_level"],
                locality_score=score,
                admission_result=admission.decision.value,
                common_allergens=d["common_allergens"],
                allergen_info_complete=d["evidence_complete"],
                years_factor=years, cuisine_factor=cuisine, native_score=native,
                source_name=d["source"],
                verified_at=now - timedelta(days=30),
            )
            session.add(dish)

        await session.commit()

    return sqlite_session


# ---------------------------------------------------------------------------
# FastAPI TestClient fixture —— 用 seeded DB 覆盖 get_db_session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def api_client(seeded_session):
    """
    httpx AsyncClient，指向 FastAPI app，DB session 覆盖为 seeded_session。

    关键技巧：FastAPI 的 dependency_overrides 能替换掉路由里的 get_db_session。
    """
    from sqlalchemy.ext.asyncio import AsyncSession
    from src.api.main import app
    from src.db.connection import get_db_session
    from src.db.models import Base

    # 覆盖依赖注入 —— 让所有 get_db_session 路由都用我们的 seeded_session
    factory = seeded_session

    async def _get_override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db_session] = _get_override

    import httpx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()

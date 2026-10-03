"""数据库连接（SQLAlchemy 2.0 async）。

B3 降级设计：PostgreSQL 不可用时**自动回退 SQLite**（aiosqlite）。
- 开发/测试环境：优先 SQLite（无外部依赖即可跑通）
- 生产环境：强制 PostgreSQL（架构设计用 PostgreSQL ARRAY / CTE / 地理子查询）

回退机制：get_engine() 尝试 ping PostgreSQL，失败则打印 WARNING 并切换。
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings

# dev 数据库文件位置
_DEV_DB = Path(__file__).resolve().parent.parent.parent / "data" / "xunwei_dev.db"

# 全局单例（线程安全）
_engine: Optional[AsyncEngine] = None
_used_sqlite: bool = False


def _dev_db_url() -> str:
    """本地开发用 SQLite URL（aiosqlite async）。"""
    _DEV_DB.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{_DEV_DB}"


def _to_async_url(url: str) -> str:
    """sync URL → async。"""
    if url.startswith("postgresql://") and "psycopg" not in url:
        return url.replace("postgresql://", "postgresql+psycopg://")
    return url


def _try_ping_pg(url: str) -> bool:
    """同步 ping PostgreSQL（只用于启动时判定，不用于 runtime）。"""
    try:
        import psycopg
        # 把 async URL 转回 sync psycopg 3
        sync_url = url.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(sync_url, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"[xw] ⚠️  PostgreSQL ping failed ({e}) — falling back to SQLite", file=sys.stderr)
        return False


def get_engine(force_sqlite: bool = False) -> AsyncEngine:
    """
    创建异步引擎（单例，导入时缓存）。

    Args:
        force_sqlite: 强制使用 SQLite（用于单元测试）
    """
    global _engine, _used_sqlite
    if _engine is not None:
        return _engine

    settings = get_settings()

    if force_sqlite or settings.environment in ("test", "sqlite"):
        url = _dev_db_url()
        _used_sqlite = True
    else:
        pg_url = _to_async_url(settings.postgres_url)
        if _try_ping_pg(pg_url):
            url = pg_url
            _used_sqlite = False
        else:
            url = _dev_db_url()
            _used_sqlite = True

    if _used_sqlite:
        print(f"[xw] ✅ Using SQLite dev DB: {url}", file=sys.stderr)
        # SQLite: 单连接 + WAL + foreign keys
        _engine = create_async_engine(
            url,
            echo=settings.debug,
            future=True,
            connect_args={
                "check_same_thread": False,
                "timeout": 30,
            },
        )
    else:
        print(f"[xw] ✅ Using PostgreSQL: {url}", file=sys.stderr)
        _engine = create_async_engine(
            url,
            echo=settings.debug,
            future=True,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )

    return _engine


def using_sqlite() -> bool:
    """当前连接的是 SQLite 还是 PostgreSQL。"""
    get_engine()  # 确保已初始化
    return _used_sqlite


def reset_engine() -> None:
    """测试时重置单例。"""
    global _engine, _used_sqlite
    _engine = None
    _used_sqlite = False


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = get_engine()
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入用。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session

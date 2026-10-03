"""数据库连接（SQLAlchemy 2.0 async）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings


def _to_async_url(url: str) -> str:
    """将 sync URL 转为 async（psycopg 3 原生 async）。"""
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+psycopg://")  # psycopg 3 已支持 async
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://")
    return url


def get_engine() -> AsyncEngine:
    """创建异步引擎（单例，导入时缓存）。"""
    settings = get_settings()
    url = _to_async_url(settings.postgres_url)
    return create_async_engine(
        url,
        echo=settings.debug,
        future=True,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """创建 session 工厂。"""
    engine = get_engine()
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入用。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session

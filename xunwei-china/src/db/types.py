"""Dialect-aware 类型映射层。

Staff Engineer 设计：PostgreSQL 用原生 ARRAY/JSONB/UUID，
SQLite（aiosqlite）回退到 TEXT(JSON) / String ，开发/测试环境可用。

架构不变量：**Python 层 API 不变**（list[dict] 读写），
数据库层自动适配 dialect。
"""

from __future__ import annotations

import json
from typing import Any, List
from uuid import UUID, uuid4

from sqlalchemy import String, Text, TypeDecorator, func
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.types import JSON as SAJSON


# ======================================================================
# 类型选择器（导入时一次性判定 dialect）
# ======================================================================


def _pg_available() -> bool:
    try:
        from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY  # noqa: F401
        return True
    except ImportError:
        return False


def _sqlite_available() -> bool:
    try:
        import aiosqlite  # noqa: F401
        return True
    except ImportError:
        return False


_PG_OK = _pg_available()
_SQLITE_OK = _sqlite_available()


# ======================================================================
# 类型装饰器：统一 Python API，底层 dialect 自动适配
# ======================================================================


class ListType(TypeDecorator):
    """PostgreSQL: ARRAY(String); SQLite: JSON TEXT 存 list。"""

    impl = Text
    cache_ok = True

    def __init__(self, item_type: type = str):
        self.item_type = item_type
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            # 用原生 ARRAY —— 保持 GIN 索引 + ARRAY && 语法
            return postgresql.ARRAY(String(), dimensions=1)
        else:
            # SQLite / 其他：TEXT 存 JSON
            return Text()

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # ARRAY 直接传 list
        # SQLite: → JSON string
        return json.dumps(list(value), ensure_ascii=False)

    def process_result_value(self, value: Any, dialect) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return value  # postgresql ARRAY 原生返回 list
        # SQLite: 反序列化
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []


class JSONDictType(TypeDecorator):
    """PostgreSQL: JSONB; SQLite: TEXT(JSON)。"""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return postgresql.JSONB()
        else:
            return Text()

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # JSONB 直接传 dict
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value: Any, dialect) -> Any:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}


class UUID_Type(TypeDecorator):
    """PostgreSQL: UUID; SQLite: String(36)。"""

    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return postgresql.UUID(as_uuid=True)
        return String(36)

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if isinstance(value, UUID):
            return value if dialect.name == "postgresql" else str(value)
        if isinstance(value, str):
            return UUID(value) if dialect.name == "postgresql" else value
        return value

    def process_result_value(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql" and isinstance(value, UUID):
            return value
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                return value
        return value

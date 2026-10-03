"""
统一路由注册层（Experience 2374399）。

所有路由模块在这里集中注册，带 /api 前缀。
每个模块独立文件 + 独立 tag，易于单独测试和替换。

新增路由模块只需：
  1. 在 src/api/ 下创建新 router
  2. 在 REGISTRY 里加一行
  3. 自动挂到 FastAPI app
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import APIRouter, FastAPI


@dataclass
class RouteModule:
    """注册表条目。"""

    name: str
    router_factory: Callable[[], APIRouter]  # 延迟创建（避免 import 循环）
    # 可选覆盖
    prefix: str | None = None
    tags: list[str] | None = None
    enabled: bool = True


# ============================================================================
# 路由注册表
# ============================================================================


def _build_recommend():
    from src.api.recommend import router
    return router


def _build_chat():
    from src.api.chat import router
    return router


def _build_favorites():
    from src.api.favorites import router
    return router


def _build_profile():
    from src.api.profile import router
    return router


def _build_meta():
    from src.api.meta import router
    return router


# 注册顺序：核心推荐 → AI → 用户数据 → 元数据
REGISTRY: list[RouteModule] = [
    RouteModule("recommend", _build_recommend, tags=["推荐"]),
    RouteModule("chat", _build_chat, tags=["AI 对话"]),
    RouteModule("favorites", _build_favorites, tags=["清单收藏"]),
    RouteModule("profile", _build_profile, tags=["用户画像"]),
    RouteModule("meta", _build_meta, tags=["元数据"]),
]


# ============================================================================
# 注册到 FastAPI app
# ============================================================================


def register_all(app: FastAPI) -> list[str]:
    """
    将所有已启用的路由模块注册到 app。

    返回注册成功的模块名列表（便于启动时日志输出）。
    """
    registered: list[str] = []

    for mod in REGISTRY:
        if not mod.enabled:
            continue
        try:
            router = mod.router_factory()
            # 每个模块的 router 可以自己设 prefix；也可以在 registry 覆盖
            if mod.prefix is not None:
                router.prefix = mod.prefix
            if mod.tags:
                # APIRouter 构造时已设 tags，这里做补充
                if not router.tags:
                    router.tags = mod.tags
                else:
                    router.tags.extend(mod.tags)
            app.include_router(router)
            registered.append(mod.name)
        except Exception as e:
            # 可降级（Experience 建议：可降级策略 + 明确告警）
            import sys
            print(f"[xw] ⚠️  路由模块 {mod.name} 注册失败: {e}", file=sys.stderr)
            # 不 raise —— 让其他模块继续注册

    return registered

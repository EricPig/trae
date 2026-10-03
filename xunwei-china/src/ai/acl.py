"""
ACL（Anti-Corruption Layer）物理隔离层。

架构设计遵循 AI-RECOMMENDATION.md §6：
  1. 架构层：AI 进程不配 DB 连接池 → 物理上不能直连
  2. 代码层：AI 模块不得 import sqlalchemy / psycopg → 静态扫描 + runtime guard
  3. 运行时：engine.service 白名单 guard → 只有 3 个通道开放

这是 AI 子系统最重要的架构不变量之一。
FF-ARCH-03: 推荐引擎与 AI 子系统物理隔离（0% 绕过率）
FF-ARCH-04: AI 不直连 DB（0% 数据库客户端 import）
"""

from __future__ import annotations

import sys
from contextvars import ContextVar
from functools import wraps
from typing import Callable


# ============================================================================
# ACL 白名单：AI 层**唯一允许**调用的 RecommendationEngine 方法
# 任何不在此列表中的方法被 AI 层调用 → ACLViolation
# ============================================================================

ACL_ALLOWED_ENGINE_METHODS: frozenset[str] = frozenset({
    "recommend",           # 候选列表 + 完整 pipeline 判定
    "search_discover",     # 发现页（同上，pipeline 会走）
    "get_evidence_batch",  # 证据链（唯一的 DB 读通道）
})


# ============================================================================
# AI 上下文标记（用 ContextVar —— asyncio 协程安全）
# ============================================================================

# 当前代码是否在 AI 模块内执行（用于区分 API 层 vs AI 层调用）
_AI_CONTEXT: ContextVar[bool] = ContextVar("acl_ai_context", default=False)


def enter_ai_context() -> None:
    """AI 层入口调用：标记当前协程为 AI 上下文。"""
    _AI_CONTEXT.set(True)


def exit_ai_context() -> None:
    """AI 层退出调用：清除标记（一般不需要，协程结束自动清理）。"""
    _AI_CONTEXT.set(False)


def _is_in_ai_context() -> bool:
    """当前是否在 AI 上下文（contextvar 检测 + 调用栈 fallback）。"""
    if _AI_CONTEXT.get():
        return True
    # Fallback：调用栈中是否有 src.ai.* 模块
    try:
        frame = sys._getframe(2)
        while frame is not None:
            module_name = frame.f_globals.get("__name__", "")
            if module_name.startswith("src.ai") and module_name != "src.ai.acl":
                return True
            frame = frame.f_back
    except (ValueError, AttributeError):
        pass
    return False


# ============================================================================
# 违规定义
# ============================================================================

class ACLViolation(Exception):
    """ACL 违规：AI 层试图绕过推荐引擎直连 DB。"""

    def __init__(self, violation_type: str, detail: str) -> None:
        super().__init__(f"[ACL-VIOLATION] {violation_type}: {detail}")
        self.violation_type = violation_type
        self.detail = detail


def _acl_runtime_guard(func_name: str) -> None:
    """
    运行时白名单检查。

    如果检测到 AI 层在调用非白名单方法 → 抛 ACLViolation。
    这是代码层物理隔离的最后一道防线。
    """
    if func_name not in ACL_ALLOWED_ENGINE_METHODS:
        if _is_in_ai_context():
            # B4 Prometheus 打点（ACL 绕过 = 安全红线事件）
            try:
                from src.analytics.metrics import xw_acl_violations
                xw_acl_violations.labels(violation_type="UNAUTHORIZED_METHOD").inc()
            except ImportError:
                pass

            raise ACLViolation(
                "UNAUTHORIZED_METHOD",
                f"AI 层试图调用非白名单方法 RecommendationEngine.{func_name}()。"
                f"ACL 白名单只有: {sorted(ACL_ALLOWED_ENGINE_METHODS)}",
            )


# ============================================================================
# Decorator
# ============================================================================

def acl_guard(func: Callable) -> Callable:
    """
    ACL 白名单 decorator —— 挂在 RecommendationEngine 公开方法上。

    工作方式：
      1. 方法被调用时，检测当前是否在 AI 上下文
      2. 如果是 AI 层调用，检查方法名是否在 ACL_ALLOWED_ENGINE_METHODS 中
      3. 不在 → 抛 ACLViolation（硬错误，阻止执行）
      4. 在 或 不是 AI 层 → 放行

    注意：这个 decorator 是**守卫式**的，它不会拦截正常的 API 层调用。
    它只拦截「AI 层调用非白名单方法」这种违规场景。
    """

    func_name = func.__name__

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        _acl_runtime_guard(func_name)
        return await func(*args, **kwargs)

    return async_wrapper


def acl_whitelist_only(func: Callable) -> Callable:
    """
    显式标记：这个方法**只允许白名单**调用。

    与 acl_guard 配套，让代码可读性更强。
    语义是「即使 API 层也不应该直接调这个方法」—— 目前没有这样的方法，
    留作未来扩展。
    """
    func._acl_whitelisted = True  # type: ignore[attr-defined]
    return func


# ============================================================================
# 进程级 import 断言（FastAPI startup 时跑一次）
# ============================================================================

FORBIDDEN_AI_IMPORTS: tuple[str, ...] = ("sqlalchemy", "psycopg", "aiosqlite")


def verify_ai_no_forbidden_imports() -> None:
    """
    进程级断言：确保 AI 模块没有 import 数据库客户端库。

    这是 FF-ARCH-04 的 runtime 版本。推荐在 FastAPI startup 时调用一次。
    如果 src.ai.* 模块已加载且含有 sqlalchemy/psycopg/aiosqlite → 抛错。

    注意：由于 Python import 的传播性，这里做的是尽力而为的检查。
    真正的防护在 CI 静态扫描中。
    """
    for module_name in list(sys.modules.keys()):
        if (
            module_name.startswith("src.ai")
            and not module_name.startswith("src.ai.acl")
        ):
            module = sys.modules[module_name]
            for forbidden in FORBIDDEN_AI_IMPORTS:
                # 检查模块顶层 namespace 里有没有
                if hasattr(module, forbidden):
                    raise ACLViolation(
                        "FORBIDDEN_IMPORT",
                        f"AI 模块 {module_name} 含有禁止的 import: {forbidden}",
                    )

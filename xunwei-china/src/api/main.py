"""FastAPI 主入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import get_settings


# 内部日志（详细错误只进日志，不回客户端）
_logger = logging.getLogger("xw.api")


# ============================================================================
# 生命周期
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时验证架构不变量。"""
    settings = get_settings()
    print(f"[xw] 启动: env={settings.environment}, log_level={settings.log_level}")

    # 启动时跑基线断言（R1-R5）—— 架构不变量必须在进程开始时就成立
    from scripts.verify_s0_weights import run_assertions

    assertions = run_assertions()
    all_pass = all(a.passed for a in assertions)
    if not all_pass:
        failed = [a.name for a in assertions if not a.passed]
        print(f"[xw] ❌ 架构断言失败: {failed}")
        print("[xw] 进程启动被拒绝 —— 架构不变量被破坏")
        raise SystemExit(1)
    print(f"[xw] ✅ 架构断言 R1-R5 全部通过")

    # B2 ACL: 启动时验证 AI 模块没有 forbidden imports
    try:
        from src.ai.acl import verify_ai_no_forbidden_imports
        verify_ai_no_forbidden_imports()
        print("[xw] ✅ ACL 进程级断言通过")
    except Exception as e:
        print(f"[xw] ⚠️ ACL 启动检查: {e}")

    yield

    print("[xw] 关闭")


# ============================================================================
# App
# ============================================================================


app = FastAPI(
    title="寻味中国 · 可核验的地方美食 AI 推荐平台",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Prometheus /metrics —— 直接用 FastAPI endpoint 返回，避免 mount 导致的 307 重定向
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

# 注册路由（统一注册层 —— src/api/router.py）
from src.api.router import register_all

_registered = register_all(app)
print(f"[xw] 路由模块已注册: {_registered}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# 中间件：请求追踪 + 延迟测量 + 错误脱敏
# ============================================================================


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    import time as _t
    import uuid as _u
    from src.analytics.metrics import (
        xw_request_duration, xw_requests_total, xw_exceptions,
    )

    start = _t.time()
    method = request.method
    path = request.url.path or "/"

    try:
        response = await call_next(request)
    except Exception as exc:
        # B1 安全加固：错误脱敏 —— 详细堆栈只进服务器日志，不回客户端
        _logger.exception(f"Unhandled exception on {method} {path}")
        xw_exceptions.labels(endpoint=path, exception_type=type(exc).__name__).inc()
        response = JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error", "request_id": _u.uuid4().hex[:12]},
        )

    latency = _t.time() - start
    status = response.status_code

    # Prometheus 指标采集
    xw_request_duration.labels(method=method, path=path, status=str(status)).observe(latency)
    xw_requests_total.labels(method=method, path=path, status=str(status)).inc()

    response.headers["X-Request-ID"] = _u.uuid4().hex[:12]
    response.headers["X-Latency-MS"] = f"{latency * 1000:.1f}"
    return response


# ============================================================================
# 端点
# ============================================================================


@app.get("/")
async def root():
    """根路径 → 前端首页（静态文件兜底）。"""
    from pathlib import Path
    from fastapi.responses import FileResponse
    fe = Path(__file__).parent.parent.parent / "frontend" / "index.html"
    if fe.exists():
        return FileResponse(fe, media_type="text/html")
    return {
        "name": "寻味中国",
        "tagline": "可核验的地方美食 AI 推荐平台",
        "version": "0.1.0",
    }


# 静态文件 mount 移到文件最末尾（所有 API 路由之后）


@app.get("/health")
async def health():
    """健康检查 + 架构不变量状态。"""
    from scripts.verify_s0_weights import run_assertions

    assertions = run_assertions()
    return {
        "status": "ok",
        "architecture_assertions": {
            a.name: "passed" if a.passed else "FAILED" for a in assertions
        },
    }


@app.get("/health/red-lines")
async def red_lines():
    """架构红线状态。"""
    from src.config import (
        SAFETY_VIOLATION_TARGET,
        HALLUCINATION_TARGET,
        SOURCE_ANNOTATION_TARGET,
    )

    return {
        "allergen_violation_target_pct": SAFETY_VIOLATION_TARGET,
        "hallucination_target_pct": HALLUCINATION_TARGET,
        "source_annotation_target_pct": SOURCE_ANNOTATION_TARGET,
        "note": "这些是架构级常量，运行时通过 FF-SAFE-01/02 和 FF-DATA-01 守护",
    }


@app.post("/api/event")
async def track_event(payload: "EventRequest"):
    """
    行为埋点接收端点。

    B1 加固：用 EventRequest schema 强校验，杜绝裸 dict 注入。
    fire-and-forget —— 实际生产应写入 Redis Stream / Kafka
    """
    # 这里只做骨架，实际异步队列接入由 analytics worker 处理
    return {
        "status": "accepted",
        "event_name": payload.event_name,
        "note": "fire-and-forget，实际写入由 worker 处理",
    }


# 延迟 import 避免循环依赖
from src.api.schemas import EventRequest  # noqa: E402


# ============================================================================
# 静态文件兜底（最后注册，确保 API 路由优先匹配）
# ============================================================================

from pathlib import Path as _Path
from fastapi.staticfiles import StaticFiles
import os as _os

_fe_dir = str(_Path(__file__).parent.parent.parent / "frontend")

# 404 fallback 中间件：当 API 路由返回 404 时，尝试 serve 前端静态文件
@app.middleware("http")
async def _frontend_fallback(request: Request, call_next):
    response = await call_next(request)
    if response.status_code == 404 and request.method in ("GET", "HEAD"):
        fe_path = _Path(_fe_dir) / request.url.path.lstrip("/")
        if fe_path.is_file():
            from fastapi.responses import FileResponse
            return FileResponse(fe_path)
        # / → index.html
        index = _Path(_fe_dir) / "index.html"
        if index.is_file() and request.url.path in ("", "/", "/index.html"):
            from fastapi.responses import FileResponse
            return FileResponse(index)
    return response

print(f"[xw] ✅ 前端静态文件兜底已就绪: {_fe_dir}")

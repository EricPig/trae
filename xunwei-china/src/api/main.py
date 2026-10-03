"""FastAPI 主入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import get_settings


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# 中间件：请求追踪 + 延迟测量
# ============================================================================


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    start = __import__("time").time()
    try:
        response = await call_next(request)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    latency_ms = (__import__("time").time() - start) * 1000
    response.headers["X-Request-ID"] = __import__("uuid").uuid4().hex[:12]
    response.headers["X-Latency-MS"] = f"{latency_ms:.1f}"
    return response


# ============================================================================
# 端点
# ============================================================================


@app.get("/")
async def root():
    return {
        "name": "寻味中国",
        "tagline": "可核验的地方美食 AI 推荐平台",
        "version": "0.1.0",
        "positioning": "做「菜品的知识与出处」，不做「商户的评分与揭黑」",
    }


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
async def track_event(payload: dict):
    """
    行为埋点接收端点。

    fire-and-forget —— 实际生产应写入 Redis Stream / Kafka
    MVP 阶段可直接写入数据库（同步）
    """
    # 这里只做骨架，实际异步队列接入由 analytics worker 处理
    return {"status": "accepted", "note": "fire-and-forget，实际写入由 worker 处理"}

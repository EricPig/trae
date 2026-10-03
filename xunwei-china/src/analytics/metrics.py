"""
Prometheus Metrics —— 寻味中国后端核心指标。

指标设计原则：
  1. 覆盖架构不变量可观测：过敏原红线（FF-SAFE-01）、ACL 绕过（FF-ARCH-03）、准入层排除
  2. FastAPI middleware 自动采集 HTTP 请求延迟/状态码
  3. 业务层手动打点：pipeline 各阶段通过率/耗时、AI 诚实层降级次数

命名规范（Prometheus）：xw_{entity}_{metric}
  - xw_request_duration_seconds: HTTP 请求耗时 Histogram
  - xw_requests_total: HTTP 请求计数 Counter (by method/path/status)
  - xw_pipeline_admission_total: 准入层各结果计数 (admitted/excluded_chain/rejected_evidence/etc.)
  - xw_pipeline_safety_filter_total: 安全层各原因排除数 (allergen_miss/unknown_completeness/etc.)
  - xw_pipeline_locality_score_bucket: locality_score 分布 Histogram
  - xw_chat_honesty_flags_total: AI 诚实层各降级触发次数
  - xw_acl_violations_total: ACL runtime guard 拦截次数
  - xw_exceptions_total: 未捕获异常总数
  - xw_db_queries_total: DB 查询次数 Counter

Grafana 仪表盘将基于这些指标构建红线路径（FF-SAFE-01 直接对应 xw_pipeline_safety_filter_total{reason="allergen_miss"} 不应有任何命中）。
"""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    make_wsgi_app,
    REGISTRY,
)


# ---------------------------------------------------------------------------
# HTTP 层（middleware 自动采集）
# ---------------------------------------------------------------------------

xw_request_duration = Histogram(
    "xw_request_duration_seconds",
    "HTTP 请求总耗时（端到端）",
    ["method", "path", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

xw_requests_total = Counter(
    "xw_requests_total",
    "HTTP 请求计数",
    ["method", "path", "status"],
)


# ---------------------------------------------------------------------------
# Pipeline 层（业务语义）
# ---------------------------------------------------------------------------

xw_pipeline_admission = Counter(
    "xw_pipeline_admission_total",
    "准入层判定结果（二维准入表 + evidence）",
    ["decision"],  # admitted / excluded_chain / rejected_evidence
)

xw_pipeline_safety_filter = Counter(
    "xw_pipeline_safety_filter_total",
    "安全层排除原因（FF-SAFE-01 红线守护）",
    ["reason"],  # allergen_miss / unknown_completeness / expired_source
)

xw_pipeline_locality_score = Histogram(
    "xw_pipeline_locality_score_bucket",
    "locality_score 分布（0-100）",
    buckets=(0, 20, 40, 50, 60, 70, 80, 90, 100),
)

xw_pipeline_duration = Histogram(
    "xw_pipeline_duration_seconds",
    "推荐 pipeline 总耗时（DB 查询 + 四阶段 pipeline）",
    ["city"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)


# ---------------------------------------------------------------------------
# AI 层（诚实 + ACL）
# ---------------------------------------------------------------------------

xw_chat_honesty_flags = Counter(
    "xw_chat_honesty_flags_total",
    "AI 诚实层各降级类型触发次数",
    ["flag"],  # source_missing / evidence_insufficient / data_conflict
)

xw_chat_rounds = Counter(
    "xw_chat_rounds_total",
    "AI 对话收敛轮次（超过 4 轮架构硬上限应看诚实层 notes）",
    ["rounds"],
)

xw_acl_violations = Counter(
    "xw_acl_violations_total",
    "ACL runtime guard 拦截次数（FF-ARCH-03 守护）",
    ["violation_type"],  # UNAUTHORIZED_METHOD / FORBIDDEN_IMPORT
)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

xw_exceptions = Counter(
    "xw_exceptions_total",
    "未捕获异常计数（按 endpoint 分组）",
    ["endpoint", "exception_type"],
)


# ---------------------------------------------------------------------------
# DB 层
# ---------------------------------------------------------------------------

xw_db_queries = Counter(
    "xw_db_queries_total",
    "数据库查询计数",
    ["operation"],  # select / insert / update
)

xw_db_query_duration = Histogram(
    "xw_db_query_duration_seconds",
    "单次 DB 查询耗时",
    ["operation"],
    buckets=(0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1),
)


# ---------------------------------------------------------------------------
# FastAPI WSGI endpoint
# ---------------------------------------------------------------------------

def get_prometheus_asgi_app():
    """返回 ASGI 适配器（prometheus_client 提供 WSGI，需要 starlette adapter）。"""
    from starlette.middleware.wsgi import WSGIMiddleware
    return WSGIMiddleware(make_wsgi_app(REGISTRY))

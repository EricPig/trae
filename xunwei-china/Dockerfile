# =============================================================================
# 寻味中国 · 生产 Dockerfile
# =============================================================================
#
# 构建:   docker build -t xunwei-china:latest .
# 运行:   docker run -d --name xunwei -p 8765:8765 -v $(pwd)/data:/app/data xunwei-china
# 或 compose: docker compose up -d (已有 dev postgres+redis)
#
# 设计:
#   - 多阶段构建：builder 装依赖 → runtime 只拷贝产物
#   - 非 root 用户运行（安全）
#   - SQLite DB 目录挂卷（数据不丢）
#   - 静态前端通过 FastAPI 404 fallback 直接 serve（同 origin 无跨域）
#   - 内置 seed demo，首次启动自动有数据
# =============================================================================

FROM python:3.14-slim AS builder

WORKDIR /build

# 系统依赖（编译 psycopg / pgvector 等）
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 先拷贝依赖声明，利用 Docker 层缓存
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install -e .

# ---- runtime ----
FROM python:3.14-slim

LABEL org.opencontainers.image.title="寻味中国" \
      org.opencontainers.image.description="可核验的地方美食 AI 推荐平台" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.source="https://github.com/xunwei-china"

# 非 root 用户
RUN groupadd -r xunwei && useradd -r -g xunwei -d /app -s /sbin/nologin xunwei

WORKDIR /app

# 从 builder 拷贝已安装的 Python 包
COPY --from=builder /install /usr/local

# 项目源码（除 .git/node_modules/.pytest_cache）
COPY src/          ./src/
COPY scripts/      ./scripts/
COPY frontend/     ./frontend/
COPY data/         ./data/
COPY pyproject.toml ./

# 创建运行时目录
RUN mkdir -p run logs && chown -R xunwei:xunwei /app

USER xunwei

# 端口 & 健康检查
EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/health').read()" || exit 1

ENV XW_ENV=development \
    XW_PORT=8765 \
    PYTHONUNBUFFERED=1

# entrypoint：如果 data/ 为空，先 seed；然后启动 uvicorn
ENTRYPOINT ["/bin/bash", "-c", "\
    if [ -z \"$(ls -A data/*.db 2>/dev/null)\" ]; then \
      echo '[xw] 首次启动，执行 seed_demo...'; \
      PYTHONPATH=. python scripts/seed_demo.py --force-sqlite || echo '[xw] seed 跳过'; \
    fi; \
    exec python -m uvicorn src.api.main:app \
      --host 0.0.0.0 --port ${XW_PORT:-8765} \
      --workers ${XW_WORKERS:-2} --loop uvloop; \
"]

#!/usr/bin/env bash
# =============================================================================
# 寻味中国 · 一键部署脚本
# =============================================================================
#
# 用法:
#   ./scripts/deploy.sh install           # 安装依赖 + 初始化 DB + seed
#   ./scripts/deploy.sh start              # 后台启动（nohup）
#   ./scripts/deploy.sh stop               # 停止
#   ./scripts/deploy.sh restart            # 重启
#   ./scripts/deploy.sh verify             # 健康检查 + pytest
#   ./scripts/deploy.sh logs               # 查看运行日志（tail -f）
#   ./scripts/deploy.sh status             # 进程状态
#   ./scripts/deploy.sh doctor             # 环境诊断（Python/端口/依赖）
#   ./scripts/deploy.sh uninstall          # 停服务 + 清理 venv（保留 data/）
#   ./scripts/deploy.sh all                # install → start → verify 一条龙
#
# 环境变量（全部可选）:
#   PORT=8765                # 服务端口
#   ENV=development          # development | production | sqlite
#   PYTHON=python3           # Python 解释器
#   VENV=.venv               # venv 目录
#   DATA_DIR=./data          # SQLite DB 目录
#   LOG_FILE=./logs/xunwei.log
#   WORKERS=4                # uvicorn worker 数（prod 模式）
#
# 设计原则:
#   - 单脚本收敛，只这一个文件
#   - 裸机（nohup / systemd）+ Docker 两套都支持
#   - SQLite 零依赖启动，PostgreSQL 可用时自动切换
#   - 关键步骤显式返回码 + 状态汇总，避免 set -e 掩盖问题
# =============================================================================

set -u

# -----------------------------------------------------------------------------
# 0. 全局配置
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

: "${PORT:=8765}"
: "${ENV:=development}"
: "${PYTHON:=python3}"
: "${VENV:=.venv}"
: "${DATA_DIR:=data}"
: "${LOG_FILE:=logs/xunwei.log}"
: "${WORKERS:=4}"

PID_FILE="run/xunwei.pid"
HOST="0.0.0.0"

declare -a FAILED_STEPS=()
ALL_PASS=true

# -----------------------------------------------------------------------------
# 1. 工具函数
# -----------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
fail()    { echo -e "${RED}[FAIL]${RESET}  $*"; FAILED_STEPS+=("$*"); ALL_PASS=false; }
step()    { echo ""; echo -e "${BOLD}══════════════════════════════════════════${RESET}"; echo -e "${BOLD}  $*${RESET}"; echo -e "${BOLD}══════════════════════════════════════════${RESET}"; }

# 关键步骤：执行后检查退出码，失败则记录
run_step() {
  local name="$1"; shift
  info "→ $name"
  if "$@"; then
    ok "$name"
    return 0
  else
    fail "$name"
    return 1
  fi
}

require_port_free() {
  local port="$1"
  if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
    local pid
    pid=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K[0-9]+' | head -1)
    if [ -n "$pid" ]; then
      warn "端口 ${port} 被 PID=${pid} 占用（可能是之前的 xunwei 实例）"
      return 1
    fi
  fi
  return 0
}

wait_for_port() {
  local port="$1"
  local max_wait="${2:-30}"
  local i=0
  while [ $i -lt $max_wait ]; do
    if curl -s -o /dev/null "http://localhost:${port}/health" 2>/dev/null; then
      return 0
    fi
    sleep 1; i=$((i+1))
  done
  return 1
}

# -----------------------------------------------------------------------------
# 2. 子命令：doctor —— 环境诊断
# -----------------------------------------------------------------------------
cmd_doctor() {
  step "环境诊断"

  # Python
  local py_ok=false
  if command -v "$PYTHON" &>/dev/null; then
    local py_ver
    py_ver=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local py_maj=${py_ver%.*}
    local py_min=${py_ver#*.}
    if [ "$py_maj" -ge 3 ] && [ "$py_min" -ge 11 ]; then
      ok "Python ${py_ver} (≥3.11 满足)"
      py_ok=true
    else
      fail "Python ${py_ver} (需要 ≥3.11)"
    fi
  else
    fail "未找到 ${PYTHON}，请先安装 Python 3.11+"
  fi

  # pip
  command -v pip3 &>/dev/null && ok "pip3 可用" || warn "pip3 未找到（系统包可能用 python -m pip）"

  # 项目根目录
  [ -f "$PROJECT_ROOT/pyproject.toml" ] && ok "项目根目录识别: $PROJECT_ROOT" || fail "未找到 pyproject.toml，目录结构异常"

  # 端口
  require_port_free "$PORT" && ok "端口 ${PORT} 空闲" || warn "端口 ${PORT} 被占用（停旧实例或改 PORT）"

  # sqlite3
  command -v sqlite3 &>/dev/null && ok "sqlite3 CLI 可用" || warn "sqlite3 CLI 未找到（不影响运行，仅影响手工 DB 操作）"

  # 磁盘
  local avail
  avail=$(df -BM "$PROJECT_ROOT" | awk 'NR==2{print $4}' | tr -d 'M')
  [ "${avail:-0}" -gt 100 ] && ok "磁盘空间 ${avail}MB (≥100MB)" || warn "磁盘空间不足 ${avail}MB"

  # venv / 依赖（非致命）
  if [ -d "$PROJECT_ROOT/$VENV" ]; then
    ok "venv 已存在 ($VENV)"
  else
    warn "venv 不存在，执行 'install' 命令创建"
  fi

  echo ""
  [ "$ALL_PASS" = true ] && echo -e "${GREEN}✅ 环境诊断通过${RESET}" || echo -e "${YELLOW}⚠️  有 ${#FAILED_STEPS[@]} 项可改进${RESET}"
}

# -----------------------------------------------------------------------------
# 3. 子命令：install —— 安装 + DB 初始化 + seed
# -----------------------------------------------------------------------------
cmd_install() {
  step "依赖安装 & DB 初始化"

  cd "$PROJECT_ROOT" || return 1

  # 创建必要目录
  mkdir -p run logs "$DATA_DIR"
  ok "目录就绪: run/ logs/ $DATA_DIR/"

  # venv
  if [ ! -d "$VENV" ]; then
    run_step "创建 venv ($VENV)" "$PYTHON" -m venv "$VENV" || return 1
  else
    ok "venv 已存在"
  fi

  # shellcheck disable=SC1091
  source "$VENV/bin/activate"

  run_step "pip install（可编辑模式 + 生产依赖）" pip install -e "." 2>&1 | tail -5 || return 1

  # DB 初始化（SQLite 自动创建）
  run_step "DB schema 初始化 (SQLite)" "$PYTHON" -c "
import os, sys
sys.path.insert(0, '.')
os.environ.setdefault('XW_ENV', 'development')
from src.db.connection import get_engine, using_sqlite
import asyncio, sqlalchemy as sa
from src.db.models import Base
async def init():
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f'✅ DB 初始化完成, using_sqlite={using_sqlite()}')
asyncio.run(init())
" || {
    warn "schema 初始化失败，可能 DB 已存在。尝试跳过..."
  }

  # seed demo
  if [ -f "scripts/seed_demo.py" ]; then
    run_step "种子数据 (seed_demo)" "$PYTHON" scripts/seed_demo.py 2>&1 | tail -5 || warn "seed 失败（可能已有数据）"
  fi

  echo ""
  echo -e "${GREEN}✅ 安装完成${RESET}"
  echo "   下一步: ./scripts/deploy.sh start"
}

# -----------------------------------------------------------------------------
# 4. 子命令：start —— 后台启动
# -----------------------------------------------------------------------------
cmd_start() {
  step "启动服务"

  cd "$PROJECT_ROOT" || return 1

  # 停掉可能残留的旧实例
  if [ -f "$PID_FILE" ]; then
    local old_pid
    old_pid=$(cat "$PID_FILE")
    if kill -0 "$old_pid" 2>/dev/null; then
      warn "发现残留 PID=${old_pid}，先停止"
      kill "$old_pid" 2>/dev/null
      sleep 2
    fi
    rm -f "$PID_FILE"
  fi
  require_port_free "$PORT" || {
    fail "端口 ${PORT} 仍被占用，无法启动"
    return 1
  }

  # venv
  if [ -d "$VENV" ]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
  else
    fail "venv 不存在，先执行 install"
    return 1
  fi

  mkdir -p "$(dirname "$LOG_FILE")" run

  # uvicorn 参数
  local extra_args=()
  if [ "$ENV" = "production" ]; then
    extra_args+=(--workers "$WORKERS" --loop uvloop)
  fi

  # 启动
  info "启动 uvicorn (ENV=$ENV, PORT=$PORT, PID_FILE=$PID_FILE)"
  nohup "$PYTHON" -m uvicorn src.api.main:app \
    --host "$HOST" \
    --port "$PORT" \
    "${extra_args[@]}" \
    >> "$LOG_FILE" 2>&1 &

  local new_pid=$!
  echo "$new_pid" > "$PID_FILE"
  ok "进程 PID=${new_pid}"

  # 等待就绪
  info "等待健康检查..."
  if wait_for_port "$PORT" 30; then
    ok "服务就绪 → http://localhost:${PORT}/"
  else
    fail "30 秒内未就绪，检查日志: tail -f $LOG_FILE"
    cat "$LOG_FILE" | tail -20
    return 1
  fi
}

# -----------------------------------------------------------------------------
# 5. 子命令：stop / restart / status
# -----------------------------------------------------------------------------
_cmd_read_pid() {
  [ -f "$PID_FILE" ] && cat "$PID_FILE"
}

cmd_stop() {
  step "停止服务"
  local pid
  pid=$(_cmd_read_pid)
  if [ -z "$pid" ]; then
    warn "无 PID 文件，尝试按端口 kill"
    pid=$(ss -tlnp 2>/dev/null | grep ":${PORT} " | grep -oP 'pid=\K[0-9]+' | head -1)
  fi
  if [ -z "$pid" ]; then
    ok "未找到运行中的实例"
    return 0
  fi
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
      warn "SIGTERM 未生效，发送 SIGKILL"
      kill -9 "$pid" 2>/dev/null
    fi
    ok "已停止 PID=${pid}"
  else
    warn "PID=${pid} 不存在，清理 PID 文件"
  fi
  rm -f "$PID_FILE"
}

cmd_restart() { cmd_stop; sleep 1; cmd_start; }

cmd_status() {
  local pid
  pid=$(_cmd_read_pid)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo -e "${GREEN}● 运行中${RESET}  PID=${pid}  PORT=${PORT}  ENV=${ENV}"
    local mem cpu
    mem=$(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.1fMB", $1/1024}')
    cpu=$(ps -o %cpu= -p "$pid" 2>/dev/null | awk '{print $1"%"}')
    echo "  内存: ${mem:-?}  CPU: ${cpu:-?}"
    curl -s http://localhost:${PORT}/health 2>/dev/null && echo ""
  else
    echo -e "${RED}● 已停止${RESET}"
    [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
  fi
}

cmd_logs() {
  local f="$LOG_FILE"
  [ -f "$f" ] || { echo "日志文件不存在: $f"; return 1; }
  tail -f "$f"
}

# -----------------------------------------------------------------------------
# 6. 子命令：verify —— 健康检查 + pytest
# -----------------------------------------------------------------------------
cmd_verify() {
  step "健康检查 & 回归测试"

  # 1. /health
  info "→ GET /health"
  local health
  health=$(curl -s http://localhost:${PORT}/health 2>/dev/null)
  if echo "$health" | grep -q '"status":\s*"ok"'; then
    ok "health ok"
  else
    fail "health 异常: ${health:0:120}"
  fi

  # 2. /api/meta/capability
  info "→ GET /api/meta/capability"
  local cap
  cap=$(curl -s http://localhost:${PORT}/api/meta/capability 2>/dev/null)
  if echo "$cap" | grep -q '"levels"'; then
    ok "capability ok ($(echo "$cap" | grep -o '"level"' | wc -l) 个档位)"
  else
    fail "capability 异常"
  fi

  # 3. /api/recommend
  info "→ POST /api/recommend (成都)"
  local rec
  rec=$(curl -s -X POST http://localhost:${PORT}/api/recommend \
    -H 'Content-Type: application/json' \
    -d '{"city":"成都"}' 2>/dev/null)
  local rec_count
  rec_count=$(echo "$rec" | python3 -c "import json,sys;print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo 0)
  [ "$rec_count" -gt 0 ] && ok "recommend ok (count=${rec_count})" || fail "recommend 异常"

  # 4. 前端首页
  info "→ GET /index.html"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:${PORT}/index.html 2>/dev/null)
  [ "$code" = "200" ] && ok "前端首页 ok (200)" || fail "前端首页 HTTP ${code}"

  # 5. pytest
  if [ -d "$VENV" ]; then
    info "→ pytest 全量回归"
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
    local pytest_out
    pytest_out=$(PYTHONPATH=. python -m pytest tests/ -q 2>&1)
    local pytest_last
    pytest_last=$(echo "$pytest_out" | tail -1)
    if echo "$pytest_last" | grep -q "passed"; then
      ok "pytest ${pytest_last}"
    else
      fail "pytest: ${pytest_last}"
      echo "$pytest_out" | tail -10
    fi
  else
    warn "venv 不存在，跳过 pytest"
  fi

  # 6. 汇总
  echo ""
  step "部署验证汇总"
  echo "  通过: 见上方 ✅"
  echo "  失败: ${#FAILED_STEPS[@]} 项"
  for s in "${FAILED_STEPS[@]}"; do
    echo "    ❌ $s"
  done

  echo ""
  if [ "$ALL_PASS" = true ]; then
    echo -e "${GREEN}🎉 部署验证全通过！${RESET}"
    echo -e "   ${CYAN}访问:${RESET} http://localhost:${PORT}/"
    echo -e "   ${CYAN}API 文档:${RESET} http://localhost:${PORT}/docs"
    return 0
  else
    echo -e "${RED}⚠️  有 ${#FAILED_STEPS[@]} 项失败，请检查日志${RESET}"
    return 1
  fi
}

# -----------------------------------------------------------------------------
# 7. 子命令：uninstall —— 停服务 + 清理 venv
# -----------------------------------------------------------------------------
cmd_uninstall() {
  step "卸载"
  cmd_stop

  cd "$PROJECT_ROOT" || return 1

  echo ""
  read -r -p "确认删除 venv ($VENV)? [y/N] " ans
  case "$ans" in
    [Yy]*)
      rm -rf "$VENV" && ok "已删除 $VENV" || fail "删除 venv 失败"
      ;;
    *) ok "跳过 venv 删除" ;;
  esac

  echo ""
  read -r -p "删除 SQLite 数据 ($DATA_DIR/*.db)? [y/N] " ans
  case "$ans" in
    [Yy]*)
      rm -f "$DATA_DIR"/*.db "$DATA_DIR"/*.db-wal "$DATA_DIR"/*.db-shm && ok "已清空" || warn "无 DB 文件"
      ;;
    *) ok "保留数据" ;;
  esac

  rm -f run/xunwei.pid run/*.pid 2>/dev/null
  echo -e "${GREEN}✅ 卸载完成${RESET}（日志 logs/ 目录未删除）"
}

# -----------------------------------------------------------------------------
# 8. 子命令：all —— 一条龙
# -----------------------------------------------------------------------------
cmd_all() {
  step "一条龙部署 (install → start → verify)"
  cmd_install || true
  cmd_start   || true
  cmd_verify  || true
}

# -----------------------------------------------------------------------------
# 9. 入口分发
# -----------------------------------------------------------------------------
_usage() {
  cat <<EOF
用法: $0 <command>

命令:
  install     依赖安装 + DB 初始化 + seed
  start       后台启动
  stop        停止
  restart     重启
  status      进程状态
  logs        查看运行日志
  verify      健康检查 + pytest
  doctor      环境诊断
  uninstall   卸载
  all         install → start → verify

环境变量: PORT ENV PYTHON VENV DATA_DIR LOG_FILE WORKERS

示例:
  PORT=9000 ENV=production $0 start
  $0 all           # 一条龙
EOF
}

case "${1:-}" in
  install)   cmd_install   ;;
  start)     cmd_start     ;;
  stop)      cmd_stop      ;;
  restart)   cmd_restart   ;;
  status)    cmd_status    ;;
  logs)      cmd_logs      ;;
  verify)    cmd_verify    ;;
  doctor)    cmd_doctor    ;;
  uninstall) cmd_uninstall ;;
  all)       cmd_all       ;;
  *)         _usage; exit 1 ;;
esac

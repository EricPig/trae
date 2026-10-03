# 寻味中国 · 可核验的地方美食 AI 推荐平台

> **做「菜品的知识与出处」，不做「商户的评分与揭黑」。**

## 快速开始

```bash
# 1. 启动依赖
docker compose up -d

# 2. 安装依赖
pip install -e ".[dev]"

# 3. 验证架构不变量
PYTHONPATH=. python scripts/verify_s0_weights.py

# 4. 跑单元测试（25 个）
PYTHONPATH=. python -m pytest tests/unit/ -v

# 5. 启动 API
uvicorn src.api.main:app --reload --port 8000
# → http://localhost:8000/health  （含架构断言状态）
```

## 项目结构

```
xunwei-china/
├── architecture/            # 📐 架构设计文档
│   ├── ADR-001-system-overview.md     # 核心架构决策
│   ├── SYSTEM-MAP.md                  # 系统拓扑 + 数据流
│   ├── BOUNDED-CONTEXTS.md            # DDD 限界上下文
│   ├── FITNESS-FUNCTIONS.md           # 24 条架构不变量
│   ├── AI-RECOMMENDATION.md           # AI 诚实推荐设计
│   └── RISK-REGISTER.md               # 15 个风险登记
├── src/
│   ├── config/              # 配置 + 架构常量（红线硬编码）
│   │   ├── constants.py     # 🔴 不可修改：S0 权重表、二维准入表、断言
│   │   └── settings.py      # 环境变量加载（pydantic-settings）
│   ├── db/                  # PostgreSQL + SQLAlchemy 2.0
│   │   ├── models.py        # 核心 ORM（Dish, Admission, Safety 等）
│   │   └── connection.py    # 异步引擎 + session 工厂
│   ├── engine/              # 🧠 推荐引擎（核心）
│   │   └── pipeline.py      # 准入 → 安全 → 排序 → 展示 四合一
│   ├── ai/                  # 🤖 AI 推荐子系统
│   │   └── pipeline.py      # Layer 1-5 + ACL（Anti-Corruption Layer）
│   ├── adapters/            # Redis 缓存层
│   ├── analytics/           # 行为埋点 + WDCU
│   ├── profile/             # 用户画像（敏感数据）
│   └── api/                 # FastAPI 主入口
├── scripts/
│   └── verify_s0_weights.py # 基线清单回归断言 R1–R5
├── tests/unit/              # 25 个单元测试
└── docker-compose.yml
```

## 核心架构

### 两层分离（基线清单 §8）

```
准入层 ─ 二维条件（locality_level × evidence_level + 差异化阈值）
            ↓ 候选池
排序层 ─ 单标量 locality_score（60/25/15 权重表）
            ↓ 排序结果
展示层 ─ 四象限规则矩阵（🔴+高本地性 = 禁降权禁折叠）
```

### 安全红线（架构级常量）

| 红线 | 值 | 守护 |
|------|-----|------|
| 过敏原违反率 | **= 0%** | 召回层硬过滤 + 静态断言 + 每日扫描 |
| 门店事实幻觉率 | **= 0%** | ACL 阻止 AI 直连 DB + RAG 强制检索 |
| 来源标注率 | **= 100%** | 数据源模型强制 source_name |
| 推荐 P95 | **≤ 1.2s** | Redis 缓存 + 降级策略 |

### 架构不变量（pre-commit 守护）

```
✅ R1 连锁 locality_score 最高 < 50（实测 49.75）
✅ R2 native ≤20 年 locality_score 恒 ≥ 60（实测 79.25）
✅ R3 native + C/D + ≥20 年 ≥ 60（实测 82.38）
✅ R4 native 全区间 ≥ 60（实测 79.41）
✅ R5 连锁越线年份 ≥ 92（未越线，安全）
```

## 为什么是这个架构

| 问题 | 解法 | 来源 |
|------|------|------|
| 单标量排序无法同时保护隐藏款和淘汰连锁 | 两层分离（准入层二维 + 排序层单标量）| 基线清单 §8：861 组 Pareto 穷举无可行解 |
| 过敏原违反是致命错误 | 召回层硬过滤（不进入候选集）| 产品全案 §2.5：一票否决 |
| AI 编造事实 | ACL 阻止直连 DB + RAG 强制检索 + 诚实层 | AI-RECOMMENDATION.md |
| 🔴 资料不全条目会被折叠（竞品失败路径）| 🔴 + 高本地性 → 禁折叠禁降权 | 基线清单 §1.5 裁决 1 |

## 开发流程

```bash
# pre-commit：跑 R1-R5
pre-commit run verify-s0

# 架构断言（启动时自动跑）
PYTHONPATH=. python scripts/verify_s0_weights.py

# 单元测试（含架构层断言）
PYTHONPATH=. python -m pytest tests/unit/ -v

# 变更准入/排序参数后必须跑
PYTHONPATH=. python -c "from scripts.verify_s0_weights import run_assertions; exit(0 if all(a.passed for a in run_assertions()) else 1)"
```

## 下一步

- [ADR-002] HMAC 过敏原方案三选一
- [ADR-003] 推荐引擎 FastAPI 接口
- [ADR-004] 向量库选型 + Alembic 迁移
- [Gate 4] 开源数据 ETL 接入 + 许可证审计

---

**产品定位**：寻味中国 · 把中国地方美食做成可核验的裁决。

**一句话边界**：做「菜品的知识与出处」，不做「商户的评分与揭黑」。

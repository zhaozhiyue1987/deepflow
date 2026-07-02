# DeepFlow — 功能架构与技术架构文档

> 本文档基于对 DeerFlow + A2A Gateway 扩展的完整代码通读整理而成，涵盖功能架构、技术架构、核心模块、数据流与安全设计。

---

## 1. 项目概述

DeepFlow 是基于 [ByteDance DeerFlow](https://github.com/bytedance/deer-flow/) 的本地化部署版本，核心扩展了 **A2A (Agent-to-Agent) Gateway/Registry** 能力，使 DeerFlow 中的原生智能体和外部第三方 A2A 智能体能够：

- 对外发布符合 A2A 协议的 Agent Card 和 Task 端点
- 被外部调度器（Scheduler）跨系统发现与调用
- 在统一网关层实现注册、鉴权、任务转发与生命周期管理

**部署地址：** http://localhost:2026  
**仓库：** https://github.com/zhaozhiyue1987/deepflow

---

## 2. 功能架构

### 2.1 整体功能架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              外部调度器 / Scheduler                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                        │
│  │  Discovery   │  │   Agent Card │  │  Task Invoke │                        │
│  │  /registry   │  │   /card      │  │  /tasks      │                        │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                        │
└─────────┼─────────────────┼─────────────────┼────────────────────────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DeerFlow A2A Gateway (Nginx 2026)                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Auth Middleware  ──  CSRF Middleware  ──  Rate Limit (预留)          │   │
│  │  • 公开路径放行 (registry/card)                                      │   │
│  │  • A2A Bearer Task 绕过 Session Auth                                 │   │
│  │  • A2A Bearer Task 绕过 CSRF (外部调度器无 Cookie)                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│  ┌───────────────────────────┼──────────────────────────────────────────┐   │
│  │                           ▼                                          │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │                    A2A Protocol Router                         │  │   │
│  │  │  /api/a2a/registry        ──  公开发现 (native + external)     │  │   │
│  │  │  /api/a2a/agents/{n}/card ──  公开 Agent Card                  │  │   │
│  │  │  /api/a2a/agents/{n}/tasks──  Bearer 鉴权 + 任务执行/转发       │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  │                           │                                          │   │
│  │         ┌─────────────────┼─────────────────┐                        │   │
│  │         ▼                 ▼                 ▼                        │   │
│  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────────┐            │   │
│  │  │   Native    │   │  External   │   │  Upstream A2A   │            │   │
│  │  │   Agent     │   │   Agent     │   │   Service       │            │   │
│  │  │  (Phase B)  │   │   (Relay)   │   │                 │            │   │
│  │  └─────────────┘   └─────────────┘   └─────────────────┘            │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
          │                                    │
          ▼                                    ▼
┌─────────────────────────┐      ┌─────────────────────────────────────────┐
│   DeerFlow Native Agent │      │      External A2A Management API        │
│   Runtime (LangGraph)   │      │  /api/a2a/external-agents               │
│                         │      │    • POST   ── 注册外部智能体            │
│  ┌─────────────────┐    │      │    • GET    ── 列出已注册               │
│  │  Thread/Run     │    │      │    • GET /{n} ── 详情                  │
│  │  Orchestration  │    │      │    • PUT /{n} ── 更新                  │
│  │  assistant_id   │    │      │    • DELETE/{n} ── 删除                │
│  │  = agent_name   │    │      │    • POST /{n}/a2a/enable  ── 启用    │
│  └─────────────────┘    │      │    • POST /{n}/a2a/disable ── 禁用    │
│                         │      │    • POST /{n}/a2a/rotate  ── 轮换令牌│
└─────────────────────────┘      └─────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DeerFlow Web UI (Next.js 3000)                        │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  /workspace/agents                                                   │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │ AgentGallery (原生 + 外部智能体统一列表)                        │  │   │
│  │  │  • Register External A2A 按钮 + Dialog                         │  │   │
│  │  │  • AgentCard: 启用/禁用/轮换 A2A、复制 Card URL/Task URL/Token  │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 功能模块说明

#### 模块 1：A2A Protocol Router (`a2a.py`)

公开 A2A 协议端点，无需 DeerFlow 登录态即可访问 registry 和 card，task 端点通过 Bearer Token 鉴权。

| 端点 | 方法 | 鉴权 | 说明 |
|------|------|------|------|
| `/api/a2a/registry` | GET | 无 | 发现所有已启用的 native + external agent |
| `/api/a2a/agents/{name}/card` | GET | 无 | 获取 Agent Card（网关重写 URL） |
| `/api/a2a/agents/{name}/tasks` | POST | Bearer | 执行任务：native → DeerFlow run，external → 上游转发 |

**Native Task 执行流程 (Phase B)：**
1. 提取 A2A message text parts
2. 生成 thread ID，构建 `RunCreateRequest`（`assistant_id=agent_name`）
3. 临时设置 synthetic internal user 到 `request.state.user`
4. 调用 `start_run()` 创建并启动 run
5. 等待完成：`wait_for_run_completion()` + 503 fallback 直接 await task
6. 从 checkpoint 提取最后一条 assistant message 作为 result
7. 返回 A2A 格式：`{task_id, agent_name, source, status, result}`

**External Task 转发流程：**
1. 从上游 Agent Card 获取 task URL
2. SSRF 安全检查
3. 携带上游 Bearer Token（如配置）转发请求
4. 返回上游响应（状态码/结果透传）

#### 模块 2：External A2A Management (`a2a_external_agents.py`)

管理用户拥有的外部 A2A 智能体。

**数据模型：**
```
ExternalAgentRecord
  owner_user_id      # 用户隔离
  name               # 唯一标识符
  display_name       # 展示名称
  description        # 描述
  enabled            # 是否启用 A2A 发布
  upstream_card_url  # 上游 Agent Card URL
  upstream_auth_type # none | bearer
  upstream_auth_token# 上游 Token（加密存储）
  upstream_card      # 缓存的上游 Card 内容
  token_hash         # 网关 Token SHA-256 Hash
  token_prefix       # Token 前缀（用于展示）
```

**持久化存储：**
- 文件：`DEER_FLOW_HOME/a2a_registry.json`
- 结构：`{external_agents: [...], native_publications: [...]}`
- 内存缓存 + 延迟加载 + 变更自动保存

**SSRF 保护：**
- 拒绝 `file://` 协议
- 拒绝 localhost / loopback / private / link-local / reserved / multicast / unspecified IP
- DNS 解析后二次 IP 检查

#### 模块 3：Native Agent A2A Publication (`agents.py` + store helpers)

原生 DeerFlow agent 的 A2A 发布管理。

**数据模型：**
```
NativePublicationRecord
  owner_user_id   # 用户隔离
  name            # agent 名称
  description     # 描述
  enabled         # 是否发布
  token_hash      # 网关 Token SHA-256 Hash
  token_prefix    # Token 前缀
```

**管理端点：**
- `POST /api/agents/{name}/a2a/enable` — 生成 Token，启用发布
- `POST /api/agents/{name}/a2a/disable` — 禁用发布
- `POST /api/agents/{name}/a2a/rotate` — 轮换 Token

**Agent Response 扩展：** `/api/agents` 和 `/api/agents/{name}` 返回 A2A 状态字段（`enabled`, `card_url`, `task_url`, `token_prefix`），前端刷新后状态不丢失。

#### 模块 4：Frontend A2A Management UI

**AgentGallery (`agent-gallery.tsx`)：**
- 统一展示原生 + 外部 agent 卡片
- "Register External A2A" 按钮 → Dialog 表单
- 表单字段：name, display_name, description, upstream_card_url, upstream_auth_type, upstream_auth_token
- Dialog 关闭时清理 `pointer-events: none` 残留（Radix modal 兼容修复）

**AgentCard (`agent-card.tsx`)：**
- Source 标签（Native/External）+ Health 状态
- A2A 操作区：Enable / Disable / Rotate Token
- 一次性 Token 展示（amber 高亮区域）
- Copy 按钮：Card URL / Task URL / Token
- TruncatedTooltip：自动检测文本截断，hover 显示完整内容

**State Management (`hooks.ts` + `api.ts`)：**
- TanStack Query：`useAgents()`, `useExternalA2AAgents()`
- Mutations：`useEnableAgentA2A()`, `useEnableExternalA2AAgent()`, ...
- 成功自动 invalidate queries，UI 自动刷新

---

## 3. 技术架构

### 3.1 后端技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 框架 | FastAPI + Starlette | API 路由、中间件、请求生命周期 |
| 运行时 | Python 3.12 + uv | 依赖管理、虚拟环境 |
| Agent 编排 | LangGraph | Thread/Run 编排、Checkpoint 持久化 |
| 通信 | httpx | 异步 HTTP 客户端（上游 A2A 调用） |
| 配置 | Pydantic + YAML | 请求体验证、Agent 配置存储 |
| 安全 | secrets + hashlib | Token 生成（`secrets.token_urlsafe`）、SHA-256 存储 |

### 3.2 前端技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 框架 | Next.js 16 + React 19 | App Router、Server Components |
| 语言 | TypeScript 5.8 | 类型安全 |
| 样式 | Tailwind CSS 4 + Shadcn UI | Utility-first + 组件库 |
| 状态 | TanStack Query 5 | 服务端状态管理、缓存、自动刷新 |
| 测试 | Rstest + jsdom + RTL | 单元测试（106 backend + 388 frontend tests） |

### 3.3 部署架构

```
┌─────────────────────────────────────────────────────┐
│                    Docker Compose                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │    Nginx    │  │   Frontend  │  │   Gateway   │  │
│  │   :2026     │  │   :3000     │  │   :8001     │  │
│  │             │  │  Next.js    │  │  FastAPI    │  │
│  │ 反向代理     │  │  Dev Server │  │  + LangGraph│  │
│  │ / → frontend│  │             │  │             │  │
│  │ /api →gateway│  │             │  │  .venv 持久化│  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│         │                                    │       │
│         └────────────────────────────────────┘       │
│                      共享网络                         │
│              deer-flow-dev (192.168.200.0/24)        │
└─────────────────────────────────────────────────────┘
```

**关键卷挂载（开发模式）：**
- `backend/` → 热重载代码
- `config.yaml` → 模型配置
- `skills/` → 技能定义
- `gateway-venv` → 持久化 Python 虚拟环境
- `gateway-uv-cache` → uv 缓存

### 3.4 安全架构

```
┌─────────────────────────────────────────────────────────────┐
│                      请求进入 Nginx:2026                     │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  AuthMiddleware (全局)                                      │
│  ├─ 公开路径？→ 直接放行 (registry, card, health, docs...)   │
│  ├─ A2A Bearer Task？→ 跳过 Session Auth，进入 A2A Router   │
│  └─ 其他路径？→ 验证 Session Cookie / JWT                   │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  CSRFMiddleware (全局)                                      │
│  ├─ GET/HEAD/OPTIONS/TRACE？→ 放行                          │
│  ├─ A2A Bearer Task？→ 跳过（外部调度器无 Cookie）            │
│  ├─ Auth 端点？→ Origin 校验                                │
│  └─ 其他 POST/PUT/DELETE/PATCH？→ Double Submit Cookie      │
│     (csrf_token cookie + X-CSRF-Token header)               │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  A2A Router                                                 │
│  ├─ registry/card → 无鉴权，公开返回                         │
│  └─ tasks → Bearer Token 校验                               │
│     • 提取 Authorization: Bearer <token>                     │
│     • SHA-256 比对存储的 token_hash                          │
│     • 失败返回 401 a2a_token_invalid                         │
└─────────────────────────────────────────────────────────────┘
```

**Token 安全设计：**
- 生成：`a2a_{secrets.token_urlsafe(32)}`
- 存储：仅存储 SHA-256 hash，明文只返回一次（enable/rotate 响应）
- 传输：HTTPS（生产环境）
- 前缀：`token_prefix = token[:12]`，用于日志和 UI 展示，不泄露完整 Token

---

## 4. 核心模块代码映射

### 4.1 后端模块

| 文件 | 职责 |
|------|------|
| `backend/app/gateway/routers/a2a.py` | 公开 A2A 协议端点：registry、card、task（native 执行 + external 转发） |
| `backend/app/gateway/routers/a2a_external_agents.py` | 外部 A2A CRUD + 启用/禁用/轮换 + SSRF 保护 + 持久化存储 |
| `backend/app/gateway/routers/agents.py` | 原生 Agent CRUD + A2A 发布管理 |
| `backend/app/gateway/auth_middleware.py` | 全局认证中间件：公开路径放行、A2A Bearer 任务绕过 |
| `backend/app/gateway/csrf_middleware.py` | 全局 CSRF 中间件：双提交 Cookie、A2A 任务豁免 |

### 4.2 前端模块

| 文件 | 职责 |
|------|------|
| `frontend/src/components/workspace/agents/agent-gallery.tsx` | Agent 统一列表 + 外部 A2A 注册 Dialog |
| `frontend/src/components/workspace/agents/agent-card.tsx` | 单个 Agent 卡片：A2A 操作 UI、Token 展示、Copy |
| `frontend/src/core/agents/api.ts` | Agent API 封装：原生 CRUD + 外部 A2A + A2A 发布操作 |
| `frontend/src/core/agents/hooks.ts` | TanStack Query hooks：查询 + 变更 + 自动刷新 |
| `frontend/src/core/agents/types.ts` | TypeScript 类型定义：Agent、ExternalA2AAgent、A2AAgentCard |

### 4.3 测试模块

| 文件 | 职责 |
|------|------|
| `backend/tests/test_a2a_phase_a_durability_native_publish.py` | Phase A：持久化、原生发布、registry/card、secret 不泄露 |
| `backend/tests/test_a2a_phase_b_native_task.py` | Phase B：native A2A task → DeerFlow thread/run 映射 |
| `backend/tests/test_a2a_end_to_end.py` | 端到端：external 全生命周期 + native 全生命周期 + registry 混合 |
| `backend/tests/test_csrf_middleware.py` | CSRF 回归：A2A bearer 跳过、无 bearer 仍需 CSRF |
| `backend/tests/test_auth_middleware.py` | Auth 回归：A2A 公开路径、A2A bearer 绕过 session |
| `frontend/tests/unit/components/workspace/agents/agent-card.test.tsx` | AgentCard A2A 操作 UI 测试 |
| `frontend/tests/unit/components/workspace/agents/agent-gallery.test.tsx` | Gallery 外部注册 Dialog 测试 |

---

## 5. 数据流

### 5.1 Native Agent A2A Task 数据流

```
外部调度器
    │ POST /api/a2a/agents/{name}/tasks
    │ Authorization: Bearer <gateway_token>
    ▼
┌─────────────┐
│   Nginx     │
└──────┬──────┘
       ▼
┌─────────────┐     ┌─────────────┐
│AuthMiddleware│────→│ 公开？放行   │
│             │     │ A2A Bearer？│ 跳过 Session
└──────┬──────┘     └─────────────┘
       ▼
┌─────────────┐     ┌─────────────┐
│CSRFMiddleware│────→│ A2A Bearer？│ 跳过 CSRF
└──────┬──────┘     └─────────────┘
       ▼
┌─────────────┐
│  a2a.py     │ 验证 gateway_token (SHA-256 比对)
│  /tasks     │
└──────┬──────┘
       ▼
┌─────────────────┐
│ _execute_native │
│    _task        │
└──────┬──────────┘
       │ 1. 提取 A2A message text
       │ 2. 生成 thread_id
       │ 3. 构建 RunCreateRequest (assistant_id=agent_name)
       │ 4. 设置 synthetic user → request.state.user
       ▼
┌─────────────────┐
│   start_run()   │ 创建 DeerFlow Run
└──────┬──────────┘
       ▼
┌─────────────────┐
│wait_for_run_completion│ 等待 Run 完成
└──────┬──────────┘
       ▼
┌─────────────────┐
│  checkpoint     │ 提取最后 assistant message
│  aget_tuple()   │
└──────┬──────────┘
       ▼
┌─────────────────┐
│  A2A Response   │ {task_id, agent_name, source, status, result}
└─────────────────┘
```

### 5.2 External Agent A2A Task 数据流

```
外部调度器
    │ POST /api/a2a/agents/{name}/tasks
    │ Authorization: Bearer <gateway_token>
    ▼
┌─────────────┐
│  a2a.py     │ 验证 gateway_token
│  /tasks     │
└──────┬──────┘
       ▼
┌─────────────────┐
│forward_external │
│  _task_to_      │
│   _upstream     │
└──────┬──────────┘
       │ 1. 从 upstream_card 获取 task URL
       │ 2. SSRF 安全检查
       │ 3. 携带 upstream_auth_token（如配置）
       ▼
┌─────────────────┐
│  httpx.Async    │ POST 上游 task URL
│    Client       │
└──────┬──────────┘
       ▼
┌─────────────────┐
│  Upstream A2A   │ 执行实际任务
│   Service       │
└──────┬──────────┘
       ▼
┌─────────────────┐
│  A2A Response   │ {task_id, agent_name, source, upstream_task_id, status, result}
└─────────────────┘
```

---

## 6. API 端点总览

### 6.1 A2A Protocol (公开)

| 方法 | 端点 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/a2a/registry` | 无 | 发现所有已发布 agent |
| GET | `/api/a2a/agents/{name}/card` | 无 | 获取 Agent Card |
| POST | `/api/a2a/agents/{name}/tasks` | Bearer | 执行任务 |

### 6.2 External A2A Management (需登录)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/a2a/external-agents` | 列出已注册的外部 agent |
| POST | `/api/a2a/external-agents` | 注册外部 agent |
| GET | `/api/a2a/external-agents/{name}` | 获取详情 |
| PUT | `/api/a2a/external-agents/{name}` | 更新 |
| DELETE | `/api/a2a/external-agents/{name}` | 删除 |
| POST | `/api/a2a/external-agents/{name}/a2a/enable` | 启用 A2A 发布（返回一次性 Token） |
| POST | `/api/a2a/external-agents/{name}/a2a/disable` | 禁用 A2A 发布 |
| POST | `/api/a2a/external-agents/{name}/a2a/rotate` | 轮换 Token（返回新 Token） |

### 6.3 Native Agent Management (需登录)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/agents` | 列出原生 agent（含 A2A 状态） |
| POST | `/api/agents` | 创建原生 agent |
| GET | `/api/agents/{name}` | 获取详情（含 A2A 状态） |
| PUT | `/api/agents/{name}` | 更新 |
| DELETE | `/api/agents/{name}` | 删除 |
| POST | `/api/agents/{name}/a2a/enable` | 启用 A2A 发布（返回一次性 Token） |
| POST | `/api/agents/{name}/a2a/disable` | 禁用 A2A 发布 |
| POST | `/api/agents/{name}/a2a/rotate` | 轮换 Token |

---

## 7. 已知限制与后续方向

| 优先级 | 事项 | 说明 |
|--------|------|------|
| P1 | `request.state.user` synthetic internal | Native task 执行时临时设置 synthetic user，生产环境需更优雅的内部调用机制 |
| P2 | Stream bridge fallback | 无 stream bridge 时 fallback 直接 `await task`，行为可能与完整路径不同 |
| P3 | Result 提取依赖 LangChain 格式 | 从 checkpoint 提取 assistant message 依赖标准格式，自定义 message 可能不兼容 |
| P4 | 数据库持久化 | 当前使用 JSON 文件存储，高并发场景需迁移到数据库 |
| P5 | Token 过期机制 | 当前 Token 无 TTL，需补充过期/自动轮换机制 |
| P6 | Rate Limiting | 未实现 A2A 端点限流 |
| P7 | 上游健康检查 | External agent 无定期健康检查，health_status 为静态值 |

---

## 8. 文件结构

```
deepflow/
├── .trae/
│   ├── skills/sdd-tdd-workflow/     # SDD+TDD workflow skill
│   └── rules/sdd-tdd-strict-rule.md # always-on project rule
├── deer-flow/
│   ├── backend/
│   │   ├── app/gateway/
│   │   │   ├── routers/
│   │   │   │   ├── a2a.py                    # A2A 协议路由
│   │   │   │   ├── a2a_external_agents.py    # 外部 A2A 管理
│   │   │   │   └── agents.py                 # 原生 Agent + A2A 发布
│   │   │   ├── auth_middleware.py            # 认证中间件
│   │   │   └── csrf_middleware.py            # CSRF 中间件
│   │   └── tests/
│   │       ├── test_a2a_phase_a_*.py         # Phase A 测试
│   │       ├── test_a2a_phase_b_*.py         # Phase B 测试
│   │       ├── test_a2a_end_to_end.py        # 端到端测试
│   │       ├── test_csrf_middleware.py       # CSRF 回归测试
│   │       └── test_auth_middleware.py       # Auth 回归测试
│   ├── frontend/
│   │   ├── src/components/workspace/agents/
│   │   │   ├── agent-card.tsx                # Agent 卡片 UI
│   │   │   └── agent-gallery.tsx             # Agent 列表 + 注册 Dialog
│   │   └── src/core/agents/
│   │       ├── api.ts                        # Agent API 封装
│   │       ├── hooks.ts                      # TanStack Query hooks
│   │       └── types.ts                      # TypeScript 类型
│   ├── docker/
│   │   └── docker-compose-dev.yaml           # Docker 开发部署配置
│   ├── config.yaml                           # 模型配置（Volcengine Ark）
│   └── .env                                  # 环境变量（API Key）
├── docs/
│   ├── sdd-tdd/                              # SDD/TDD 文档集
│   └── knowledge/deer-flow-local-deploy.md   # 部署知识文档
├── README.md                                 # 项目 README
└── ARCHITECTURE.md                           # 本文档
```

---

*文档版本：v1.0 | 基于代码版本：Phase A + B 完成 | 测试覆盖：Backend 106 passed, Frontend 388 passed*

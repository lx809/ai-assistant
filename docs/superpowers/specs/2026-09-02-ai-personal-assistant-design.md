# AI 私人助手 — 设计文档

日期：2026-09-02
状态：待用户审阅

## 1. 目标与定位

做一个本地运行的 AI 私人助手：用户通过浏览器网页与它对话，它能结合用户私有知识库回答、帮用户记录想法、抓取网页存入知识库，并记住跨对话的长期信息。

第一版定位为**单用户、本地使用**。不追求多账号、云端部署与复杂外部集成，重点是把「对话 + 长期记忆 + RAG + MCP 工具」这条技术链路完整、可调试地跑通。

## 2. 范围

### MVP 包含

- FastAPI 后端，托管本地 Web 前端（Vue 3 构建产物）
- 浏览器聊天页，SSE 流式回答
- 单 Agent 核心（LangChain 工具调用型 Agent）
- 对话模型走 DeepSeek 云端 API（OpenAI 兼容协议）
- RAG：本地文档解析、切块、本地嵌入、向量检索，回答展示检索来源
- 文档导入：网页上传 + 扫描 `knowledge/` 文件夹
- 长期记忆：SQLite 结构化记忆条目，对话前注入、对话后提炼、网页可查看/编辑/删除
- MCP：首批两个工具（记笔记、网页文章抓取入库）实现为本地 MCP Server，Agent 通过 MCP 客户端使用
- 会话历史持久化，可在网页查看历史对话

### 明确不做（第一版）

- 日历、提醒、待办等第三方工具
- 多 Agent 编排
- 账号系统与多用户
- 语音交互
- Docker 化部署
- 移动端适配

## 3. 技术栈

| 层 | 选型 | 说明 |
| --- | --- | --- |
| 后端框架 | FastAPI | HTTP 服务、文档上传、静态托管 |
| Agent 编排 | LangChain | 工具调用型单 Agent、流式事件 |
| 对话模型 | DeepSeek API（`deepseek-chat`） | OpenAI 兼容接口，密钥存 `.env` |
| 嵌入模型 | `sentence-transformers` + `BAAI/bge-small-zh-v1.5` | 本地运行，优先 GPU，失败自动 CPU |
| 向量库 | Chroma（本地持久化） | 存储文档切片向量 |
| 关系存储 | SQLite | 会话、消息、记忆条目、文档索引 |
| MCP | Python 标准 MCP 服务端 + `langchain-mcp-adapters` | 首批本地 MCP Server，后续可扩展 |
| 前端 | Vue 3 + Vite + TypeScript | 开发期独立 dev server，生产构建后由 FastAPI 托管 |
| 文档解析 | pypdf、python-docx、Markdown/纯文本 | PDF、Word、Markdown、TXT |
| 依赖管理 | uv（后端）、npm（前端） | |

## 4. 总体架构

```
浏览器（Vue 3）
   │  HTTP / SSE 事件流（fetch 流式读取）
   ▼
FastAPI 服务层
  /api/chat、/api/documents/*、/api/memory/*、/api/conversations/*
   │
   ▼
Agent 核心（LangChain 单 Agent，DeepSeek）
   │  注册工具，经 astream_events 推送
   ├── RAG 检索工具    → Chroma 向量库 ← 本地嵌入模型
   ├── 长期记忆工具     → SQLite
   ├── 笔记写入工具 ──┐
   ├── 网页抓取工具 ──┤ → MCP Client（langchain-mcp-adapters）
   └── 预留更多工具 ──┘ → 本地 MCP Server（FastMCP）
                            │ 写入
                            ▼
                      knowledge/ 文件夹
                            │ 触发后台索引
                            ▼
                  解析 → 切块 → 嵌入 → 写入 Chroma
```

### 数据流（一次典型对话）

1. 用户在网页发送消息，前端发起 `POST /api/chat`，以流式方式读取事件。
2. 后端载入该会话最近历史，并向 Agent 注入长期记忆摘要。
3. Agent 自主决定是否调用工具：
   - 回答需要私人资料 → 调 RAG 检索工具；
   - 用户要求记录 → 调笔记工具；
   - 用户给链接要求保存 → 调网页抓取工具。
4. 每个工具的开始/结束、RAG 命中来源均以事件实时推给前端。
5. 最终回答以 `token` 事件逐字流式返回。
6. 对话结束后异步执行：
   - 消息与摘要写入 SQLite；
   - 调用一次独立的 DeepSeek 请求，克制地提炼可长期记忆的事实并写入记忆表。
7. 新写入 `knowledge/` 的文档在后台完成切片与索引，不阻塞当前对话。

## 5. 仓库结构

```
ai-assistant/
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py            # FastAPI 入口、静态托管、后台任务
│   │   ├── config.py          # 配置加载（.env）
│   │   ├── api/
│   │   │   ├── chat.py        # /api/chat 流式接口
│   │   │   ├── documents.py
│   │   │   ├── memory.py
│   │   │   ├── conversations.py
│   │   │   └── health.py
│   │   ├── agent/
│   │   │   ├── core.py        # Agent 构建与事件流
│   │   │   └── prompt.py
│   │   ├── rag/
│   │   │   ├── parser.py      # 各格式解析
│   │   │   ├── chunker.py
│   │   │   ├── embedder.py
│   │   │   ├── indexer.py     # 后台索引任务
│   │   │   └── retriever.py
│   │   ├── memory/
│   │   │   ├── store.py       # SQLite 读写
│   │   │   ├── extractor.py   # 对话后事实提炼
│   │   │   └── injector.py    # 对话前记忆注入
│   │   ├── mcp_client.py      # 启动并桥接 MCP Server
│   │   ├── db.py              # SQLite 连接与迁移
│   │   └── events.py          # SSE 事件结构
│   ├── mcp_server/
│   │   ├── server.py          # FastMCP Server 入口
│   │   └── tools/
│   │       ├── notes.py       # notes.create
│   │       └── web.py         # web.save
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts         # dev 代理 /api → 127.0.0.1:8000
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── lib/stream.ts      # SSE 事件流读取与解析
│       ├── lib/api.ts
│       ├── views/ChatView.vue
│       ├── views/MemoryView.vue
│       └── components/
│           ├── ChatMessage.vue
│           ├── ToolTrace.vue
│           ├── SourceCard.vue
│           ├── ConversationList.vue
│           └── MemoryPanel.vue
├── knowledge/                 # 原始文档目录（运行时生成）
├── data/
│   ├── assistant.db           # SQLite
│   ├── vectorstore/           # Chroma 持久化
│   └── logs/                  # 运行日志
├── mcp_config.json            # MCP Server 配置（服务器列表与启动参数）
└── docs/
    └── superpowers/specs/
```

## 6. 组件设计

### 6.1 FastAPI 服务层

接口约定：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 生产模式托管前端构建产物（SPA fallback） |
| POST | `/api/chat` | 发起对话，返回 SSE 事件流 |
| GET | `/api/conversations` | 会话列表 |
| GET | `/api/conversations/{id}` | 会话详情与消息 |
| POST | `/api/documents/upload` | multipart 上传文档，进入后台索引 |
| POST | `/api/documents/scan` | 扫描 `knowledge/` 中未入库文档 |
| GET | `/api/documents` | 文档与索引状态列表 |
| DELETE | `/api/documents/{id}` | 删除文档及对应向量 |
| GET | `/api/memory/entries` | 查看长期记忆 |
| PUT | `/api/memory/entries/{id}` | 编辑记忆条目 |
| DELETE | `/api/memory/entries/{id}` | 删除记忆条目 |
| GET | `/api/health` | 健康检查（含 MCP/嵌入模型可用性） |

### 6.2 Agent 核心

- LangChain 工具调用型单 Agent；对话模型为配置成 DeepSeek 的 OpenAI 兼容 `ChatOpenAI`。
- 通过 `astream_events` 将事件转发给 API 层，再转成统一 SSE 事件输出。
- Agent 的工具集合由配置决定：RAG 检索、笔记、网页抓取、记忆读写（记忆读写工具 v1 仅在对话中处理显式记忆请求，自动提炼走独立后台任务）。
- 系统提示词固定助手人设与行为规则：需要知识先检索、不编造来源、工具失败要如实说明。

### 6.3 流式事件协议

`POST /api/chat` 的响应为 `text/event-stream`，每行 `event: <type>` + `data: <json>`。

事件类型：

| type | 载荷要点 | 说明 |
| --- | --- | --- |
| `session_start` | `conversation_id` | 会话建立 |
| `memory_loaded` | `summary` | 已注入的长期记忆摘要 |
| `tool_start` | `tool`、`arguments` | 工具开始 |
| `tool_end` | `tool`、`ok`、`summary` | 工具结束与结果摘要 |
| `sources` | 命中片段数组 | RAG 检索结果，每项含文档 id、标题、路径、摘要、相似度 |
| `token` | `text` | 回答增量 |
| `done` | — | 回答结束 |
| `error` | `message` | 可恢复或致命错误 |

前端使用 `fetch` + `ReadableStream` 读取（支持 POST 且便于携带消息体），解析同上格式。

### 6.4 RAG 服务

- 支持格式：Markdown、TXT、PDF、Word。
- 解析：各格式专用解析器统一产出纯文本与元数据（标题、来源路径）。
- 切块：按段落切分，单块约 500 字，相邻块重叠约 10%；长文档优先按 Markdown 标题切分。
- 嵌入：`BAAI/bge-small-zh-v1.5`（首次运行下载缓存），优先 CUDA，不可用自动回落 CPU。
- 向量库：Chroma 持久化至 `data/vectorstore`；切片元数据记录 `document_id`、`source_path`、`content_hash`。
- 检索：默认取 top-5 相关块，带相似度分数返回给 Agent 与前端。
- 去重与更新：以 `content_hash` 判断文档是否变化；同文档重新入库时先删旧向量。
- 索引任务：文档解析/嵌入在后台线程或 FastAPI `BackgroundTasks` 中执行，完成后更新 `documents.status`。

### 6.5 长期记忆

SQLite 表 `memory_entries`：

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `type` | `identity` / `preference` / `ongoing` / `decision` / `general` |
| `content` | 记忆文本 |
| `created_at` / `updated_at` | 时间戳 |
| `source_conversation_id` | 来源会话（可空） |
| `manual` | 是否为用户手动添加（自动提炼的不覆盖手动条目） |

机制：

- **注入**：对话开始时取最近且未删除的记忆条目，压缩为摘要注入系统提示词。
- **提炼**：对话结束后调用一次独立 DeepSeek 请求，输出候选记忆；系统提示词要求克制（只存高置信度、有长期价值的事实），默认不重复已有内容；新条目写入前按语义比对已有条目去重。
- **管理**：网页可查看、编辑、删除；删除即永久移除，不再注入。

### 6.6 MCP 桥接与首批工具

- 本地 MCP Server 用 Python 标准 MCP 库（FastMCP）实现，由后端进程作为 stdio 子进程拉起。
- Agent 通过 `langchain-mcp-adapters` 的客户端把 MCP 工具桥接为 Agent 工具。
- MCP Server 配置独立成文件，未来新增第三方 Server（日历、文件等）只需追加配置。
- 工具写入文档后，若返回结果中包含位于知识根目录内的文件路径，后端登记该文件并调度后台索引；上传与手动扫描走同一索引入口。

首批两个工具：

1. `notes.create(title, content, tags?)`
   - 写入 `knowledge/notes/YYYY/MM/` 下的 Markdown 文件，文件名用标题加时间戳生成；
   - 写完后通知后端触发该文档索引。
2. `web.save(url, title?)`
   - 抓取 URL 正文，清洗为 Markdown 保存到 `knowledge/web/`；
   - 抓取失败返回明确原因（超时、非 HTML、无法访问）。

### 6.7 前端（Vue 3）

- 页面：`ChatView`（主聊天页，含会话历史侧栏，可新建/切换/查看历史对话）、`MemoryView`（长期记忆管理）。
- 组件：
  - `ChatMessage`：用户/助手消息气泡，助手回答流式更新；
  - `ToolTrace`：单条回答的可折叠过程面板（工具调用序列、耗时、结果摘要）；
  - `SourceCard`：RAG 命中来源，可展开查看摘要与打开本地文件路径；
  - `ConversationList`：会话列表与切换入口；
  - `MemoryPanel`：记忆条目列表、编辑、删除。
- `lib/stream.ts` 负责发起请求、解析事件、按类型分发；组件通过订阅回调更新状态。
- 样式：简洁明快的本地聊天界面；不做复杂 UI 框架，纯 CSS 足够。

## 7. 会话与消息存储

SQLite 表 `conversations`、`messages`：

- `conversations(id, created_at, updated_at, title, summary)`
- `messages(id, conversation_id, role, content, created_at)`
  - `role`：`user` / `assistant` / `tool` / `system`
  - 工具调用细节可存为 JSON 内容，用于界面与排障展示，不重新注入模型上下文。

模型上下文仅使用会话内的 `user`/`assistant` 消息。

## 8. 配置与运行

`backend/.env`：

```dotenv
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
KNOWLEDGE_DIR=../knowledge
DATA_DIR=../data
MCP_CONFIG=../mcp_config.json
HOST=127.0.0.1
PORT=8000
```

开发运行：

1. 后端：`cd backend && uv sync && uvicorn app.main:app --reload --port 8000`
2. 前端：`cd frontend && npm install && npm run dev`
3. 浏览器打开 Vite 地址；Vite 将 `/api/*` 代理到 `127.0.0.1:8000`。

生产式运行：

1. `cd frontend && npm run build`
2. FastAPI 托管 `frontend/dist`，仅访问 `http://127.0.0.1:8000`。

## 9. 错误处理与健壮性

- DeepSeek 请求失败：自动重试一次；仍失败则发送 `error` 事件并在界面友好提示。
- 工具失败：事件流中标记 `ok=false`，Agent 可换方式继续或如实告知用户，不中断整个回答。
- 上传与扫描：限制单文件大小与允许类型；解析失败记录到文档状态，不阻塞其他任务。
- 客户端断开：取消生成任务，已产生的对话消息仍保存。
- 日志：后端写入 `data/logs/`，记录 Agent 决策、工具调用、API 错误，便于调试。
- 启动自检：检查 DeepSeek 配置、MCP Server 连通性、嵌入模型是否可用，缺失项在 `/api/health` 中报告。

## 10. 安全与隐私

- 服务只绑定 `127.0.0.1`，无外部暴露；不做登录（本地单用户）。
- DeepSeek API Key 只存 `.env`，不进入代码仓库（`.gitignore` 排除）。
- 文件路径统一经知识根目录校验，防止穿越写入。
- 网页抓取仅限用户显式给出链接；限制响应大小与超时。
- 长期记忆、会话与文档均存本机；用户可随时在界面查看、编辑、删除记忆与文档。

## 11. 测试策略

后端（pytest）：

- 单元：文档解析器（含 PDF/Word 样例）、切块器、嵌入与向量库读写、记忆存储与去重、SSE 事件序列化。
- 组件：MCP Server 工具直接调用（笔记创建、网页抓取用本地样例服务器模拟）。
- 集成：使用模拟模型跑通「对话 → 检索 → sources 事件 → 回答」链路，验证事件顺序与字段；真实 DeepSeek 调用仅作为可选标记测试。
- API：TestClient 覆盖上传、扫描、记忆增删改、健康检查。

前端（Vitest，最小范围）：

- `stream.ts` 对事件流的解析与分发。

## 12. 主要风险与对策

| 风险 | 对策 |
| --- | --- |
| LangChain Agent 行为不稳定、循环调用工具 | 限制最大工具调用轮数；工具结果超长时截断摘要；事件面板暴露每轮决策便于观察 |
| 自动记忆提炼产生噪音或重复 | 克制型系统提示词 + 语义去重 + 网页可删可改 |
| 本地嵌入首次下载模型慢 | 启动时提供模型就绪状态；首次可在启动脚本中预下载 |
| PDF/Word 解析质量参差 | 解析失败不阻断，状态面板可见；后续可换更强解析器 |
| SSE 与 Vue 状态同步出错 | 事件协议单一来源，前端统一在 `stream.ts` 归一化后分发 |

## 13. 验收标准

1. `uvicorn` + `npm run dev` 后可在浏览器与助手完成多轮流式对话。
2. 对话中能看到工具调用过程；回答引用知识时展示并点击来源。
3. 通过网页或拖拽上传 Markdown/TXT/PDF/Word 后，能就其内容提问并得到带来源的回答。
4. 对助手说「记住我叫 XXX / 我喜欢简洁回答」，重启服务后新会话仍能体现该记忆；记忆可在网页查看与删除。
5. 对助手说「记一条笔记」，`knowledge/notes/` 出现 Markdown 文件，随后可被 RAG 检索。
6. 给助手一个本地可达的网页链接并让它保存，抓取正文入库后可被检索。
7. 断网/密钥无效等场景出现清晰错误提示，服务不崩溃。


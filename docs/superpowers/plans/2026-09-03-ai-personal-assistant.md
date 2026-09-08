# AI 私人助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个本地运行的 AI 私人助手 MVP：Vue 3 网页流式聊天 + FastAPI 后端 + LangChain 单 Agent + DeepSeek 对话 + 本地 RAG + 长期记忆 + MCP 笔记/网页工具。

**Architecture:** FastAPI 提供 REST 与 SSE 接口；Agent 核心用 LangChain v1 `create_agent` 编排 DeepSeek 模型与工具；RAG 用本地 sentence-transformers 嵌入 + Chroma；记忆与会话存 SQLite；首批笔记/网页工具实现为本地 FastMCP stdio Server，经 `langchain-mcp-adapters` 接入 Agent。Vue 3 + Vite 前端通过 fetch 流读取 SSE 事件并渲染。

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, LangChain v1, langchain-openai, langchain-mcp-adapters, FastMCP, chromadb, sentence-transformers, pypdf, python-docx, beautifulsoup4, httpx, SQLite；Node 20+, Vue 3, Vite, TypeScript, Vitest。

**Spec:** [2026-09-02-ai-personal-assistant-design.md](../specs/2026-09-02-ai-personal-assistant-design.md)

## Global Constraints

- 服务只绑定 `127.0.0.1`，单用户，无鉴权。
- DeepSeek API Key 只存 `backend/.env`，不得写入代码与测试。
- 所有用户文档、向量库、数据库、日志只写入 `knowledge/`、`data/`。
- 上传/写入路径必须限制在 `settings.knowledge_dir` 内，禁止路径穿越。
- 嵌入模型：`BAAI/bge-small-zh-v1.5`，无 GPU 时自动回退 CPU。
- 对话模型：DeepSeek，`deepseek-chat`，base url `https://api.deepseek.com`。
- 后端 Python >= 3.11；前端 Node >= 20；Windows 10/11 + Chrome/Edge 最新。
- RAG 切片约 500 字、重叠约 10%；默认 top-5。
- Agent 为单 Agent，限制最大工具调用轮数（graph 默认 stop-condition + 后端事件层限制 12 轮后中断）。
- MCP 工具命名：`notes_create`、`web_save`（MCP 工具名允许 `_`，不使用 `.`）。
- 每个 Task 结束必须提交一次 git commit；默认从 `backend/` 目录运行 pytest。
- 前端生产构建产物由 FastAPI 在 `/` 托管，SPA fallback 到 `index.html`。

---

## File Structure

```
backend/
  pyproject.toml
  .env.example
  app/__init__.py
  app/main.py
  app/config.py
  app/db.py
  app/storage.py            # SQLite：会话/消息/文档/记忆仓库
  app/events.py             # SSE 事件序列化
  app/rag/__init__.py
  app/rag/parser.py
  app/rag/chunker.py
  app/rag/embedder.py
  app/rag/vectorstore.py
  app/rag/indexer.py
  app/memory/service.py
  app/mcp_client.py
  app/agent/service.py      # 真实 Agent：DeepSeek + RAG + MCP
  app/api/__init__.py
  app/api/health.py
  app/api/chat.py
  app/api/conversations.py
  app/api/documents.py
  app/api/memory.py
  mcp_server/__init__.py
  mcp_server/server.py
  tests/conftest.py
  tests/test_health.py
  tests/test_storage.py
  tests/test_rag.py
  tests/test_documents_api.py
  tests/test_memory_api.py
  tests/test_mcp_server.py
  tests/test_agent.py
  tests/test_chat_api.py
  tests/test_conversations_api.py
frontend/
  package.json
  vite.config.ts
  tsconfig.json
  index.html
  src/main.ts
  src/App.vue
  src/lib/stream.ts
  src/lib/api.ts
  src/lib/stream.test.ts
  src/views/ChatView.vue
  src/views/DocumentsView.vue
  src/views/MemoryView.vue
  src/components/ChatMessage.vue
  src/components/ToolTrace.vue
  src/components/SourceCard.vue
  src/components/ConversationList.vue
  src/components/MemoryPanel.vue
  src/style.css
mcp_config.json               # 首次运行时自动生成；用户可编辑
knowledge/                    # 运行时创建
data/                         # 运行时创建
README.md
```

## Interface Contract

跨任务稳定接口（各 Task 的“Interfaces”引用此处，签名以此为准）：

```python
# app/config.py
class Settings:  # pydantic-settings
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    embedding_model: str
    knowledge_dir: Path
    data_dir: Path
    db_path: Path
    mcp_config_path: Path
def get_settings() -> Settings

# app/db.py
def init_db(db_path: Path) -> None
def connect(db_path: Path) -> sqlite3.Connection

# app/storage.py —— 四个数据类仓库，均接受 sqlite3.Connection 或 db_path
class ConversationRepo:
    def create(self) -> str
    def append_message(self, conversation_id: str, role: str, content: str) -> int
    def list_messages(self, conversation_id: str) -> list[dict]
    def list_conversations(self, limit: int = 50) -> list[dict]
    def get(self, conversation_id: str) -> dict | None
    def touch(self, conversation_id: str) -> None

class MemoryRepo:
    def list_entries(self) -> list[dict]
    def create_entry(self, type_: str, content: str, source_conversation_id: str | None = None, manual: bool = False) -> int
    def update_entry(self, entry_id: int, content: str, type_: str) -> bool
    def delete_entry(self, entry_id: int) -> bool
    def summary(self) -> str

class DocumentRepo:
    def register(self, filename: str, path: str, file_type: str, content_hash: str) -> int
    def set_status(self, doc_id: int, status: str, chunk_count: int | None = None, error: str | None = None) -> None
    def list_documents(self) -> list[dict]
    def get_by_path(self, path: str) -> dict | None
    def delete(self, doc_id: int) -> None

# app/rag/vectorstore.py
@dataclass
class Source:
    document_id: int
    title: str
    path: str
    excerpt: str
    score: float

class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...

class SentenceTransformerEmbedder:
    def __init__(self, model_name: str): ...

class VectorStore:
    def __init__(self, persist_dir: Path, embedder: Embedder): ...
    def replace_document(self, document_id: int, chunks: list[str], source_path: str) -> int: ...
    def delete_document(self, document_id: int) -> None: ...
    def search(self, query: str, top_k: int = 5) -> list[Source]: ...

# app/agent/service.py
class AgentService:
    def __init__(self, settings: Settings): ...
    async def stream(self, conversation_id: str | None, message: str, emit) -> str
        # emit(event_type: str, payload: dict) -> Awaitable[None]

# SSE 事件（app/events.py）
def sse_frame(event_type: str, payload: dict) -> str
```

前端事件类型与后端一致：`session_start` / `memory_loaded` / `tool_start` / `tool_end` / `sources` / `token` / `done` / `error`。

---
### Task 1: 后端脚手架、配置与健康检查

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/db.py`
- Create: `backend/app/events.py`
- Create: `backend/app/main.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/health.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: 无（项目首个任务）。
- Produces: `get_settings() -> Settings`、`init_db(db_path)`、`sse_frame(event_type, payload) -> str`、FastAPI `app` 与 `GET /api/health`。

- [ ] **Step 1: 创建测试**

创建 `backend/tests/conftest.py`：

```python
import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """每个测试使用独立的数据目录，避免污染真实数据。"""
    monkeypatch.setenv("KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "test.db"))
    monkeypatch.setenv("MCP_CONFIG_PATH", str(tmp_path / "mcp_config.json"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

创建 `backend/tests/test_health.py`：

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_ok():
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "deepseek_configured" in body
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend; pytest tests/test_health.py -v`
Expected: FAIL，`ModuleNotFoundError: app`

- [ ] **Step 3: 创建依赖与运行文件**

创建 `backend/pyproject.toml`：

```toml
[project]
name = "ai-assistant-backend"
version = "0.1.0"
description = "AI 私人助手后端"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic-settings>=2.7",
    "langchain>=1.0",
    "langchain-openai>=1.0",
    "langchain-mcp-adapters>=0.3",
    "fastmcp>=2.0",
    "chromadb>=0.6",
    "sentence-transformers>=3.4",
    "pypdf>=5.1",
    "python-docx>=1.1",
    "beautifulsoup4>=4.12",
    "httpx>=0.27",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "anyio>=4.5",
    "reportlab>=4.2",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

创建 `backend/.env.example`：

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
HOST=127.0.0.1
PORT=8000
```

创建空包文件：

```bash
New-Item -ItemType Directory -Force backend/app/api, backend/tests | Out-Null
New-Item -ItemType File -Force backend/app/__init__.py, backend/app/api/__init__.py | Out-Null
```

创建 `backend/app/config.py`：

```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    knowledge_dir: Path = PROJECT_DIR / "knowledge"
    data_dir: Path = PROJECT_DIR / "data"
    db_path: Path = PROJECT_DIR / "data" / "assistant.db"
    mcp_config_path: Path = PROJECT_DIR / "mcp_config.json"
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

创建 `backend/app/db.py`：

```python
import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.execute("SELECT 1")
```

创建 `backend/app/events.py`：

```python
import json


def sse_frame(event_type: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n"
```

创建 `backend/app/api/health.py`：

```python
from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "deepseek_configured": bool(settings.deepseek_api_key),
        "knowledge_dir": str(settings.knowledge_dir),
        "embedding_model": settings.embedding_model,
        "mcp_config_exists": settings.mcp_config_path.exists(),
    }
```

创建 `backend/app/main.py`：

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.config import get_settings
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)
    yield


app = FastAPI(title="AI 私人助手", lifespan=lifespan)
app.include_router(health.router)
```

- [ ] **Step 4: 安装依赖并运行测试**

Run: `cd backend; uv sync --group dev; uv run pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/ && git commit -m "feat: scaffold backend with settings and health check"
```
### Task 2: SQLite 模式与会话/文档/记忆仓库

**Files:**
- Modify: `backend/app/db.py`（加入建表 SQL）
- Create: `backend/app/storage.py`
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Consumes: `connect(db_path)`、`init_db(db_path)`（Task 1）。
- Produces: `ConversationRepo`、`MemoryRepo`、`DocumentRepo`，签名见 Interface Contract。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_storage.py`：

```python
from app.config import get_settings
from app.db import init_db
from app.storage import ConversationRepo, DocumentRepo, MemoryRepo


def test_conversation_roundtrip():
    settings = get_settings()
    init_db(settings.db_path)
    repo = ConversationRepo(settings.db_path)
    conv_id = repo.create()
    repo.append_message(conv_id, "user", "你好")
    repo.append_message(conv_id, "assistant", "你好，我是助手")

    convs = repo.list_conversations()
    assert convs[0]["id"] == conv_id
    assert [m["role"] for m in repo.list_messages(conv_id)] == ["user", "assistant"]


def test_memory_and_document_repos():
    settings = get_settings()
    init_db(settings.db_path)
    memory = MemoryRepo(settings.db_path)
    memory.create_entry("preference", "喜欢简洁回答", manual=True)
    entries = memory.list_entries()
    assert len(entries) == 1
    assert "喜欢简洁回答" in memory.summary()
    assert memory.delete_entry(entries[0]["id"]) is True
    assert memory.list_entries() == []

    docs = DocumentRepo(settings.db_path)
    doc_id = docs.register("a.md", "a.md", "md", "hash-1")
    docs.set_status(doc_id, "completed", chunk_count=2)
    row = docs.get_by_path("a.md")
    assert row["status"] == "completed"
    assert row["chunk_count"] == 2
    assert len(docs.list_documents()) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL，`ModuleNotFoundError: app.storage`

- [ ] **Step 3: 实现建表与仓库**

更新 `backend/app/db.py`：文件整体为

```python
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '新对话',
    summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    file_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    content_hash TEXT,
    chunk_count INTEGER,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL DEFAULT 'general',
    content TEXT NOT NULL,
    source_conversation_id TEXT,
    manual INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
```

创建 `backend/app/storage.py`（文件整体）:

```python
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.db import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationRepo:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def create(self) -> str:
        conv_id = uuid4().hex
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversations (id, created_at, updated_at) VALUES (?, ?, ?)",
                (conv_id, now, now),
            )
        return conv_id

    def append_message(self, conversation_id: str, role: str, content: str) -> int:
        now = _now()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conversation_id, role, content, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ?, "
                "title = CASE WHEN ? = 'user' THEN substr(?, 1, 30) ELSE title END WHERE id = ?",
                (now, role, content, conversation_id),
            )
            return int(cur.lastrowid)

    def list_messages(self, conversation_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_conversations(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, summary, created_at, updated_at FROM conversations "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get(self, conversation_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, title, summary, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def touch(self, conversation_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), conversation_id))


class MemoryRepo:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def list_entries(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, type, content, source_conversation_id, manual, created_at, updated_at "
                "FROM memory_entries ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def create_entry(self, type_: str, content: str, source_conversation_id: str | None = None, manual: bool = False) -> int:
        now = _now()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO memory_entries (type, content, source_conversation_id, manual, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (type_, content, source_conversation_id, 1 if manual else 0, now, now),
            )
            return int(cur.lastrowid)

    def update_entry(self, entry_id: int, content: str, type_: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE memory_entries SET content = ?, type = ?, updated_at = ? WHERE id = ?",
                (content, type_, _now(), entry_id),
            )
            return cur.rowcount > 0

    def delete_entry(self, entry_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
            return cur.rowcount > 0

    def summary(self) -> str:
        rows = self.list_entries()[:50]
        if not rows:
            return ""
        lines = [f"- [{r['type']}] {r['content']}" for r in rows]
        return "关于用户的长期记忆：\n" + "\n".join(lines)


class DocumentRepo:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def register(self, filename: str, path: str, file_type: str, content_hash: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO documents (filename, path, file_type, content_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (filename, path, file_type, content_hash, _now()),
            )
            return int(cur.lastrowid)

    def set_status(self, doc_id: int, status: str, chunk_count: int | None = None, error: str | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE documents SET status = ?, chunk_count = ?, error = ? WHERE id = ?",
                (status, chunk_count, error, doc_id),
            )

    def list_documents(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, filename, path, file_type, status, content_hash, chunk_count, error, created_at "
                "FROM documents ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_by_path(self, path: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, filename, path, file_type, status, content_hash, chunk_count, error, created_at "
                "FROM documents WHERE path = ?",
                (path,),
            ).fetchone()
        return dict(row) if row else None

    def delete(self, doc_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
```

- [ ] **Step 4: 运行测试**

Run: `cd backend; uv run pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/db.py backend/app/storage.py backend/tests/test_storage.py && git commit -m "feat: sqlite schema and repositories"
```
### Task 3: 文档解析与切片

**Files:**
- Create: `backend/app/rag/__init__.py`
- Create: `backend/app/rag/parser.py`
- Create: `backend/app/rag/chunker.py`
- Test: `backend/tests/test_rag.py`

**Interfaces:**
- Consumes: 无（仅标准库 + pypdf + python-docx）。
- Produces: `parse_document(path: Path) -> str`、`split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_rag.py`：

```python
from pathlib import Path

import docx

from app.rag.chunker import split_text
from app.rag.parser import parse_document

def test_parse_markdown_and_txt(tmp_path):
    md = tmp_path / "note.md"
    md.write_text("# 标题\n\n正文内容", encoding="utf-8")
    assert "# 标题" in parse_document(md)


def test_parse_pdf(tmp_path):
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "sample.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 700, "Hello PDF")
    c.save()
    text = parse_document(pdf)
    assert "Hello PDF" in text


def test_parse_docx(tmp_path):
    docx_path = tmp_path / "sample.docx"
    d = docx.Document()
    d.add_paragraph("这是 Word 段落")
    d.save(str(docx_path))
    assert "这是 Word 段落" in parse_document(docx_path)


def test_split_text_returns_nonempty_chunks():
    text = "\n".join(f"第 {i} 段：生活需要一点随机数字 {i} " * 3 for i in range(60))
    chunks = split_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(c.strip() for c in chunks)
    assert sum(len(c) for c in chunks) > len(text) // 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend; uv run pytest tests/test_rag.py -v`
Expected: FAIL，`ModuleNotFoundError: app.rag`

- [ ] **Step 3: 实现解析与切片**

创建 `backend/app/rag/__init__.py`（空文件）。

创建 `backend/app/rag/parser.py`：

```python
from pathlib import Path

import docx
from pypdf import PdfReader


def _read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_docx(path: Path) -> str:
    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def parse_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".docx":
        return _parse_docx(path)
    if suffix in {".md", ".markdown", ".txt"}:
        return _read_utf8(path)
    raise ValueError(f"不支持的文件类型: {suffix}")
```

创建 `backend/app/rag/chunker.py`：

```python
import re


def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """按长度切片，切片边界尽量落在换行处；相邻块重叠 overlap 字符。"""
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + chunk_size // 2, end)
            if cut != -1 and end - cut < 200:
                end = cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_rag.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/rag backend/tests/test_rag.py && git commit -m "feat: document parser and chunker"
```

### Task 4: 本地嵌入与向量库

**Files:**
- Create: `backend/app/rag/embedder.py`
- Create: `backend/app/rag/vectorstore.py`
- Test: `backend/tests/test_vectorstore.py`

**Interfaces:**
- Consumes: `split_text`（Task 3）；`Settings.embedding_model`。
- Produces: `SentenceTransformerEmbedder`、`VectorStore.replace_document`、`VectorStore.delete_document`、`VectorStore.search`、`Source`（见 Interface Contract）。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_vectorstore.py`：

```python
from dataclasses import dataclass

from app.rag.vectorstore import Source, VectorStore


@dataclass
class FakeEmbedder:
    def _vec(self, text: str) -> list[float]:
        total = sum(ord(ch) for ch in text)
        return [float((total + i * 7) % 10) / 10.0 for i in range(8)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def test_vector_store_roundtrip(tmp_path):
    store = VectorStore(tmp_path / "chroma", FakeEmbedder())
    count = store.replace_document(1, ["番茄炒蛋需要鸡蛋和番茄", "长期记忆存于 SQLite"], "/k/a.md")
    assert count == 2

    hits = store.search("怎么做番茄炒蛋", top_k=1)
    assert len(hits) == 1
    assert hits[0].document_id == 1
    assert "番茄" in hits[0].excerpt

    store.replace_document(1, ["更新后的内容"], "/k/a.md")
    hits = store.search("怎么做番茄炒蛋", top_k=1)
    assert hits[0].excerpt == "更新后的内容"

    store.delete_document(1)
    assert store.search("番茄炒蛋", top_k=5) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend; uv run pytest tests/test_vectorstore.py -v`
Expected: FAIL，`ModuleNotFoundError: app.rag.vectorstore`

- [ ] **Step 3: 实现嵌入器与向量库**

创建 `backend/app/rag/embedder.py`：

```python
import threading

import torch


class SentenceTransformerEmbedder:
    """本地 sentence-transformers 嵌入器；GPU 可用时优先，否则 CPU。"""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _ensure_model(self):
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from sentence_transformers import SentenceTransformer

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = SentenceTransformer(self.model_name, device=device)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._ensure_model()
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        self._ensure_model()
        vector = self._model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
        return vector.tolist()
```

创建 `backend/app/rag/vectorstore.py`：

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import chromadb


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


@dataclass
class Source:
    document_id: int
    title: str
    path: str
    excerpt: str
    score: float


class VectorStore:
    def __init__(self, persist_dir: Path, embedder: Embedder):
        persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.collection = self.client.get_or_create_collection(
            name="documents", metadata={"hnsw:space": "cosine"}
        )
        self.embedder = embedder

    def replace_document(self, document_id: int, chunks: list[str], source_path: str) -> int:
        self.delete_document(document_id)
        if not chunks:
            return 0
        embeddings = self.embedder.embed_documents(chunks)
        ids = [f"doc-{document_id}-chunk-{i}" for i in range(len(chunks))]
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=[
                {"document_id": document_id, "source_path": source_path, "title": Path(source_path).name}
            ] * len(chunks),
        )
        return len(chunks)

    def delete_document(self, document_id: int) -> None:
        try:
            result = self.collection.get(where={"document_id": document_id})
        except Exception:
            return
        ids = result.get("ids") or []
        if ids:
            self.collection.delete(ids=ids)

    def search(self, query: str, top_k: int = 5) -> list[Source]:
        if self.collection.count() == 0 or top_k <= 0:
            return []
        result = self.collection.query(
            query_embeddings=[self.embedder.embed_query(query)],
            n_results=min(top_k, self.collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        sources: list[Source] = []
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for i in range(len(ids)):
            meta = metadatas[i] or {}
            sources.append(
                Source(
                    document_id=int(meta.get("document_id", 0)),
                    title=str(meta.get("title", "")),
                    path=str(meta.get("source_path", "")),
                    excerpt=str(documents[i])[:300],
                    score=round(1.0 - float(distances[i]), 4),
                )
            )
        return sources
```

- [ ] **Step 4: 运行测试**

Run: `cd backend; uv run pytest tests/test_vectorstore.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/rag/embedder.py backend/app/rag/vectorstore.py backend/tests/test_vectorstore.py && git commit -m "feat: local embedder and chroma vector store"
```
### Task 5: 文档索引器与文档 API

**Files:**
- Create: `backend/app/rag/indexer.py`
- Create: `backend/app/api/documents.py`
- Modify: `backend/app/main.py`（注册 documents router）
- Test: `backend/tests/test_documents_api.py`

**Interfaces:**
- Consumes: `DocumentRepo`（Task 2）、`parse_document`/`split_text`（Task 3）、`VectorStore`（Task 4）。
- Produces: `Indexer(settings, vectorstore=None).index_path(path) -> dict`、`POST/GET/DELETE /api/documents`、`POST /api/documents/scan`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_documents_api.py`：

```python
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import init_db
from app.main import app
from app.storage import DocumentRepo


def _fake_index(self, path: Path) -> dict:
    settings = get_settings()
    init_db(settings.db_path)
    docs = DocumentRepo(settings.db_path)
    content = path.read_text(encoding="utf-8", errors="replace")
    import hashlib
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    existing = docs.get_by_path(str(path))
    doc_id = existing["id"] if existing else docs.register(path.name, str(path), path.suffix.lstrip("."), digest)
    docs.set_status(doc_id, "completed", chunk_count=1)
    return {"id": doc_id, "status": "completed"}


def test_upload_list_and_delete(monkeypatch, tmp_path):
    monkeypatch.setattr("app.rag.indexer.Indexer.index_path", _fake_index)
    settings = get_settings()
    init_db(settings.db_path)

    with TestClient(app) as client:
        upload = client.post(
            "/api/documents/upload",
            files={"file": ("hello.md", "# 你好".encode("utf-8"), "text/markdown")},
        )
        assert upload.status_code == 200
        body = upload.json()
        assert body["status"] == "queued"

        listed = client.get("/api/documents").json()
        assert len(listed) == 1
        doc_id = listed[0]["id"]
        assert listed[0]["status"] == "completed"

        deleted = client.delete(f"/api/documents/{doc_id}")
        assert deleted.status_code == 200
        assert client.get("/api/documents").json() == []


def test_scan_ignores_unsupported_and_tracks_new_files(monkeypatch, tmp_path):
    settings = get_settings()
    init_db(settings.db_path)
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    (settings.knowledge_dir / "a.md").write_text("内容", encoding="utf-8")
    (settings.knowledge_dir / "b.exe").write_bytes(b"xx")
    calls = []

    def tracking_index(self, path):
        calls.append(Path(path).name)
        return {"status": "completed"}

    monkeypatch.setattr("app.rag.indexer.Indexer.index_path", tracking_index)
    with TestClient(app) as client:
        resp = client.post("/api/documents/scan")
    assert resp.status_code == 200
    assert "a.md" in [Path(p).name for p in resp.json()["scanned"]]
    assert not any(Path(p).suffix == ".exe" for p in resp.json()["scanned"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend; uv run pytest tests/test_documents_api.py -v`
Expected: FAIL，`404 Not Found`（router 未注册）

- [ ] **Step 3: 实现索引器**

创建 `backend/app/rag/indexer.py`：

```python
import hashlib
from pathlib import Path

from app.config import Settings
from app.rag.chunker import split_text
from app.rag.embedder import SentenceTransformerEmbedder
from app.rag.parser import parse_document
from app.rag.vectorstore import VectorStore
from app.storage import DocumentRepo

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf", ".docx"}


class Indexer:
    def __init__(self, settings: Settings, vectorstore: VectorStore | None = None):
        self.settings = settings
        self.repo = DocumentRepo(settings.db_path)
        self._vectorstore = vectorstore
        self._store: VectorStore | None = None

    def _ensure_store(self) -> VectorStore:
        if self._store is None:
            persist_dir = self.settings.data_dir / "vectorstore"
            self._store = self._vectorstore or VectorStore(
                persist_dir, SentenceTransformerEmbedder(self.settings.embedding_model)
            )
        return self._store

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def index_path(self, path: Path) -> dict:
        path = Path(path).resolve()
        text = parse_document(path)
        chunks = split_text(text)
        digest = self._content_hash(text)
        existing = self.repo.get_by_path(str(path))
        if existing and existing["status"] == "completed" and existing["content_hash"] == digest:
            return {"id": existing["id"], "status": existing["status"]}

        doc_id = existing["id"] if existing else self.repo.register(
            path.name, str(path), path.suffix.lstrip(".").lower(), digest
        )
        self.repo.set_status(doc_id, "indexing")
        try:
            chunk_count = self._ensure_store().replace_document(doc_id, chunks, str(path))
            self.repo.set_status(doc_id, "completed", chunk_count=chunk_count)
        except Exception as exc:  # 单文档失败不影响其他任务
            self.repo.set_status(doc_id, "failed", error=str(exc))
            raise
        return {"id": doc_id, "status": "completed", "chunk_count": chunk_count}
```

创建 `backend/app/api/documents.py`：

```python
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from app.config import Settings, get_settings
from app.rag.indexer import Indexer, SUPPORTED_SUFFIXES
from app.storage import DocumentRepo

router = APIRouter(prefix="/api/documents", tags=["documents"])
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _safe_filename(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "_", name) or "upload"


@router.post("/upload")
async def upload_document(file: UploadFile, background: BackgroundTasks) -> dict:
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {suffix or '未知'}")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 20MB 限制")
    if not raw.strip():
        raise HTTPException(status_code=400, detail="文件为空")

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    folder = settings.knowledge_dir / "uploads" / datetime.now().strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{stamp}-{_safe_filename(file.filename)}"
    destination.write_bytes(raw)
    background.add_task(_index_background, destination, settings)
    return {"filename": file.filename, "path": str(destination), "status": "queued"}


def _index_background(path: Path, settings: Settings) -> None:
    Indexer(settings).index_path(path)


@router.post("/scan")
def scan_knowledge(background: BackgroundTasks) -> dict:
    settings = get_settings()
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    files = [p for p in settings.knowledge_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]
    for path in files:
        background.add_task(_index_background, path, settings)
    return {"scanned": [str(p) for p in files]}


@router.get("")
def list_documents() -> list[dict]:
    return DocumentRepo(get_settings().db_path).list_documents()


@router.delete("/{doc_id}")
def delete_document(doc_id: int) -> dict:
    settings = get_settings()
    docs = DocumentRepo(settings.db_path)
    target = next((d for d in docs.list_documents() if d["id"] == doc_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    indexer = Indexer(settings)
    try:
        indexer._ensure_store().delete_document(doc_id)
    except Exception:
        pass
    docs.delete(doc_id)
    path = Path(target["path"])
    if path.is_relative_to(settings.knowledge_dir):
        path.unlink(missing_ok=True)
    return {"ok": True}
```

- [ ] **Step 4: 注册 documents router**

`main.py` 的 import 与注册改为：

```python
from app.api import documents, health
app.include_router(documents.router)
```

- [ ] **Step 5: 运行测试**

Run: `cd backend; uv run pytest tests/test_documents_api.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/rag/indexer.py backend/app/api/documents.py backend/app/main.py backend/tests/test_documents_api.py && git commit -m "feat: document indexer and documents api"
```
### Task 6: 长期记忆服务与记忆 API

**Files:**
- Create: `backend/app/memory/__init__.py`
- Create: `backend/app/memory/service.py`
- Create: `backend/app/api/memory.py`
- Modify: `backend/app/main.py`（注册 memory router）
- Test: `backend/tests/test_memory_api.py`

**Interfaces:**
- Consumes: `MemoryRepo`（Task 2）、`Settings`/`get_settings`（Task 1）。
- Produces: `summarize(repo) -> str`、`MemoryExtractor(settings).extract_and_save(conversation_id, user_text, assistant_text) -> int`、`_extract_json_array(content: str) -> list[dict]`、`GET/PUT/DELETE /api/memory/entries`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_memory_api.py`：

```python
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import init_db
from app.main import app
from app.memory.service import _extract_json_array, MemoryExtractor
from app.storage import MemoryRepo


def test_extract_json_array_handles_code_fence():
    raw = '```json\n[{"type": "identity", "content": "我叫小明"}]\n```'
    items = _extract_json_array(raw)
    assert items[0]["content"] == "我叫小明"


def test_memory_crud_api():
    settings = get_settings()
    init_db(settings.db_path)
    with TestClient(app) as client:
        resp = client.get("/api/memory/entries")
        assert resp.status_code == 200 and resp.json() == []

        repo = MemoryRepo(settings.db_path)
        entry_id = repo.create_entry("preference", "喜欢简洁回答", manual=True)

        resp = client.get("/api/memory/entries")
        assert resp.json()[0]["content"] == "喜欢简洁回答"

        resp = client.put(f"/api/memory/entries/{entry_id}", json={"content": "喜欢中文回答", "type": "preference"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "喜欢中文回答"

        resp = client.delete(f"/api/memory/entries/{entry_id}")
        assert resp.status_code == 200
        assert client.get("/api/memory/entries").json() == []


def test_extractor_skips_without_api_key(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    extractor = MemoryExtractor(settings)
    count = extractor.extract_and_save("conv1", "记住我叫小明", "好的，我叫小明。")
    assert count == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend; uv run pytest tests/test_memory_api.py -v`
Expected: FAIL，`ModuleNotFoundError: app.memory`

- [ ] **Step 3: 实现记忆服务**

创建 `backend/app/memory/__init__.py`（空）。

创建 `backend/app/memory/service.py`：

```python
import json
import re
from typing import Any

from langchain_openai import ChatOpenAI

from app.config import Settings
from app.storage import MemoryRepo

ALLOWED_TYPES = {"identity", "preference", "ongoing", "decision", "general"}


def summarize(repo: MemoryRepo) -> str:
    return repo.summary()


def _extract_json_array(content: str) -> list[dict]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    match = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


class MemoryExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract_and_save(self, conversation_id: str, user_text: str, assistant_text: str) -> int:
        """对话结束后提炼长期记忆。无 API Key 时静默跳过，返回 0。"""
        if not self.settings.deepseek_api_key:
            return 0
        repo = MemoryRepo(self.settings.db_path)
        existing = [entry["content"] for entry in repo.list_entries()]
        existing_block = "\n".join(f"- {text}" for text in existing) or "（无）"
        prompt = (
            "从下面的对话中提炼值得长期记住的用户事实。"
            "只输出 JSON 数组，不要输出其他文字。每项格式为 {\"type\": \"identity|preference|ongoing|decision|general\", \"content\": \"一句话\"}。"
            "原则：只保存高置信度、有长期价值的内容；如果某条与已记忆内容含义重复，就丢弃它；不要保存随口的闲聊。\n\n"
            f"已有记忆：\n{existing_block}\n\n"
            f"对话：\n用户：{user_text[:2000]}\n助手：{assistant_text[:2000]}"
        )
        model = ChatOpenAI(
            model=self.settings.deepseek_model,
            api_key=self.settings.deepseek_api_key,
            base_url=self.settings.deepseek_base_url,
            temperature=0,
        )
        response = model.invoke([{"role": "user", "content": prompt}])
        saved = 0
        for item in _extract_json_array(str(response.content)):
            type_ = str(item.get("type", "general"))
            content = str(item.get("content", "")).strip()
            if type_ not in ALLOWED_TYPES or not content or len(content) > 200:
                continue
            if content in existing or content in [e["content"] for e in repo.list_entries()]:
                continue
            repo.create_entry(type_, content, source_conversation_id=conversation_id, manual=False)
            existing.append(content)
            saved += 1
        return saved
```

- [ ] **Step 4: 实现记忆 API 并注册**

创建 `backend/app/api/memory.py`：

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.memory.service import ALLOWED_TYPES
from app.storage import MemoryRepo

router = APIRouter(prefix="/api/memory", tags=["memory"])


class EntryUpdate(BaseModel):
    type: str
    content: str


@router.get("/entries")
def list_entries() -> list[dict]:
    return MemoryRepo(get_settings().db_path).list_entries()


@router.put("/entries/{entry_id}")
def update_entry(entry_id: int, payload: EntryUpdate) -> dict:
    if payload.type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"type 必须是 {sorted(ALLOWED_TYPES)} 之一")
    repo = MemoryRepo(get_settings().db_path)
    if not repo.update_entry(entry_id, payload.content.strip(), payload.type):
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    return next(e for e in repo.list_entries() if e["id"] == entry_id)


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int) -> dict:
    if not MemoryRepo(get_settings().db_path).delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    return {"ok": True}
```

`backend/app/main.py` 的 import 与注册行改为：

```python
from app.api import documents, health, memory
app.include_router(memory.router)
```

- [ ] **Step 5: 运行测试**

Run: `cd backend; uv run pytest tests/test_memory_api.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/memory backend/app/api/memory.py backend/app/main.py backend/tests/test_memory_api.py && git commit -m "feat: memory service and api"
```
### Task 7: 本地 MCP Server（笔记与网页保存）

**Files:**
- Create: `backend/mcp_server/__init__.py`
- Create: `backend/mcp_server/server.py`
- Test: `backend/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `Settings.knowledge_dir`。
- Produces: FastMCP stdio Server 进程（`python backend/mcp_server/server.py --knowledge-dir <dir>`），暴露工具 `notes_create`、`web_save`；模块纯函数 `_notes_create(title, content, tags) -> dict`、`_web_save(url, title=None, client=None) -> dict`，返回 JSON 中含 `saved_file` 绝对路径。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_mcp_server.py`：

```python
import httpx

from app.config import get_settings

import mcp_server.server as server


def test_notes_create_writes_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "KNOWLEDGE_DIR", tmp_path)
    result = server._notes_create("测试笔记", "这是正文", tags=["demo"])
    saved = result["saved_file"]
    assert tmp_path in saved.parents
    assert saved.suffix == ".md"
    content = saved.read_text(encoding="utf-8")
    assert "# 测试笔记" in content
    assert "这是正文" in content


def test_web_save_extracts_article(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "KNOWLEDGE_DIR", tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><head><title>示例</title></head><body><article>"
                 "<h1>标题</h1><p>第一段内容</p><p>第二段内容</p></article></body></html>",
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = server._web_save("https://example.com/a", title="自定义标题", client=client)
    saved = result["saved_file"]
    assert saved.suffix == ".md"
    text = saved.read_text(encoding="utf-8")
    assert "自定义标题" in text
    assert "第一段内容" in text
    assert "第二段内容" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend; uv run pytest tests/test_mcp_server.py -v`
Expected: FAIL，`ModuleNotFoundError: mcp_server`

- [ ] **Step 3: 实现 MCP Server**

创建 `backend/mcp_server/__init__.py`（空）。

创建 `backend/mcp_server/server.py`：

```python
import argparse
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastmcp import FastMCP

KNOWLEDGE_DIR = Path(".")

_SAFE_NAME = re.compile(r"[\\/:*?\"<>|]+")


def _safe_title(title: str) -> str:
    cleaned = _SAFE_NAME.sub("_", title.strip()).strip(" .")
    return cleaned or "untitled"


def _write_markdown(subdir: str, title: str, body: str) -> dict:
    now = datetime.now()
    folder = KNOWLEDGE_DIR / subdir / now.strftime("%Y/%m")
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{now.strftime('%Y%m%d%H%M%S')}-{_safe_title(title)}.md"
    path = folder / filename
    path.write_text(f"# {title}\n\n{body.strip()}\n", encoding="utf-8")
    return {"status": "created", "title": title, "saved_file": str(path.resolve())}


def _notes_create(title: str, content: str, tags: list[str] | None = None) -> dict:
    """把用户口述/总结内容写成 Markdown 笔记并存入知识库。"""
    tags_block = ""
    if tags:
        tags_block = "\n\n标签：" + "、".join(tags)
    return _write_markdown("notes", title, content + tags_block)


def _web_save(url: str, title: str | None = None, client: httpx.Client | None = None) -> dict:
    """抓取网页正文，清洗后保存为 Markdown 到知识库。"""
    close_client = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        if "text/html" not in resp.headers.get("content-type", ""):
            return {"status": "failed", "error": "目标不是 HTML 页面"}
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        page_title = (soup.find("title").get_text(strip=True) if soup.find("title") else "") or urlparse(url).hostname or "网页"
        final_title = title or page_title
        article = soup.find("article") or soup.body or soup
        blocks = []
        for node in article.find_all(["h1", "h2", "h3", "p", "li", "blockquote"]):
            text = node.get_text(" ", strip=True)
            if text and len(text) > 1:
                prefix = "" if node.name in {"p", "li"} else f"**{text}**\n\n" if node.name.startswith("h") else "> "
                blocks.append(prefix + text)
        if not blocks:
            text = article.get_text("\n", strip=True)
            if text:
                blocks = [text]
        body = f"原文：{url}\n\n" + "\n\n".join(blocks)
        return _write_markdown("web", final_title, body)
    except httpx.HTTPError as exc:
        return {"status": "failed", "error": f"抓取失败: {exc}"}
    finally:
        if close_client:
            client.close()


mcp = FastMCP("assistant-tools")
mcp.tool(name="notes_create")(_notes_create)
mcp.tool(name="web_save")(_web_save)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-dir", required=True, type=Path)
    args = parser.parse_args()
    global KNOWLEDGE_DIR
    KNOWLEDGE_DIR = args.knowledge_dir.expanduser().resolve()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试**

Run: `cd backend; uv run pytest tests/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/mcp_server backend/tests/test_mcp_server.py && git commit -m "feat: local mcp server for notes and web save"
```
### Task 8: Agent 服务（DeepSeek + RAG + MCP）

**Files:**
- Create: `backend/app/mcp_client.py`
- Create: `backend/app/agent/__init__.py`
- Create: `backend/app/agent/service.py`
- Test: `backend/tests/test_agent.py`

**Interfaces:**
- Consumes: `Settings`（Task 1）、各 Repo（Task 2）、`VectorStore`/`SentenceTransformerEmbedder`（Task 4）、`MemoryExtractor`（Task 6）、MCP Server（Task 7）。
- Produces: `load_mcp_config(settings) -> dict`、`extract_saved_file(output) -> str | None`、`extract_sources(output) -> list[dict]`、`normalize_event(raw) -> tuple[str, dict] | None`、`AgentService(settings).stream(conversation_id, message, emit) -> str`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_agent.py`：

```python
import asyncio
from pathlib import Path

from app.agent.service import AgentService, extract_saved_file, extract_sources, normalize_event
from app.mcp_client import load_mcp_config
from app.config import get_settings


def test_load_mcp_config_creates_default_file(tmp_path):
    settings = get_settings()
    config = load_mcp_config(settings)
    assert settings.mcp_config_path.exists()
    assert "assistant_tools" in config
    assert config["assistant_tools"]["transport"] == "stdio"


def test_extract_helpers():
    assert extract_saved_file('{"saved_file": "D:/k/a.md", "ok": true}') == "D:/k/a.md"
    assert extract_saved_file("没有路径") is None
    payload = {"sources": [{"document_id": 1, "title": "a.md", "path": "/k/a.md", "excerpt": "x", "score": 0.9}]}
    assert extract_sources(payload) == payload["sources"]


def test_normalize_events():
    start = {"event": "on_tool_start", "name": "notes_create", "data": {"input": {"title": "x"}}}
    assert normalize_event(start) == ("tool_start", {"tool": "notes_create", "arguments": {"title": "x"}})

    stream = {
        "event": "on_chat_model_stream",
        "data": {"chunk": type("C", (), {"content": "你好"})()},
    }
    assert normalize_event(stream) == ("token", {"text": "你好"})

    unknown = {"event": "on_custom_event"}
    assert normalize_event(unknown) is None


async def test_mcp_tools_connect_and_write(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_dir", tmp_path)
    config = load_mcp_config(settings)
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(config)
    tools = await client.get_tools()
    note_tool = next(t for t in tools if "notes_create" in t.name)
    output = await note_tool.ainvoke({"title": "集成测试", "content": "正文", "tags": []})
    saved = extract_saved_file(str(output))
    assert saved is not None
    saved_path = Path(saved)
    assert str(tmp_path) in saved
    assert saved_path.exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend; uv run pytest tests/test_agent.py -v`
Expected: FAIL，`ModuleNotFoundError: app.mcp_client`

- [ ] **Step 3: 实现 MCP 配置加载**

创建 `backend/app/mcp_client.py`：

```python
import json
import sys
from pathlib import Path

from app.config import Settings

SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"


def _default_config(settings: Settings) -> dict:
    return {
        "assistant_tools": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(SERVER_SCRIPT), "--knowledge-dir", str(settings.knowledge_dir)],
        }
    }


def load_mcp_config(settings: Settings) -> dict:
    """读取 mcp_config.json；缺失或缺少默认 server 时创建/补全默认条目，不覆盖用户已有条目。"""
    default = _default_config(settings)
    path = settings.mcp_config_path
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            config = {}
    else:
        config = {}
    if "assistant_tools" not in config:
        config["assistant_tools"] = default["assistant_tools"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config
```

- [ ] **Step 4: 实现 Agent 服务**

创建 `backend/app/agent/__init__.py`（空）。

创建 `backend/app/agent/service.py`：

```python
import asyncio
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Awaitable, Callable

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import Settings
from app.mcp_client import load_mcp_config
from app.memory.service import MemoryExtractor, summarize
from app.rag.embedder import SentenceTransformerEmbedder
from app.rag.indexer import Indexer
from app.rag.vectorstore import VectorStore
from app.storage import ConversationRepo, MemoryRepo

Emit = Callable[[str, dict], Awaitable[None]]
MAX_MEMORY_TEXT = 3000


def extract_saved_file(output: object) -> str | None:
    text = str(output)
    match = re.search(r'"saved_file"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else None


def extract_sources(output: object) -> list[dict]:
    if isinstance(output, dict):
        sources = output.get("sources", [])
        return sources if isinstance(sources, list) else []
    text = str(output)
    try:
        data = json.loads(text)
        sources = data.get("sources", [])
        return sources if isinstance(sources, list) else []
    except (json.JSONDecodeError, AttributeError):
        return []


def normalize_event(raw: dict) -> tuple[str, dict] | None:
    """把 LangChain 事件转为前端事件；无关事件返回 None。"""
    event = raw.get("event")
    data = raw.get("data", {})
    if event == "on_tool_start":
        return "tool_start", {"tool": raw.get("name"), "arguments": data.get("input")}
    if event == "on_tool_end":
        output = data.get("output")
        sources = extract_sources(output)
        payload: dict = {"tool": raw.get("name"), "ok": True, "summary": str(output)[:500]}
        if sources:
            payload["sources"] = sources
        return "tool_end", payload
    if event == "on_chat_model_stream":
        chunk = data.get("chunk")
        content = getattr(chunk, "content", None)
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            text = ""
        if not text:
            return None
        return "token", {"text": text}
    return None


def _system_prompt(memory_text: str) -> str:
    rules = (
        "你是用户的私人 AI 助手。行为规则：\n"
        "1. 回答要自然、准确、简洁；需要用户资料时先调用 rag_search 检索，不要编造来源。\n"
        "2. 用户明确要求记录或提供链接要求保存时，调用 notes_create 或 web_save。\n"
        "3. 工具失败时如实告知用户，不要假装成功。\n"
    )
    memory = memory_text[:MAX_MEMORY_TEXT]
    return rules + ("\n长期记忆：\n" + memory if memory else "")


class AgentService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._vectorstore: VectorStore | None = None

    def _ensure_vectorstore(self) -> VectorStore:
        if self._vectorstore is None:
            persist_dir = self.settings.data_dir / "vectorstore"
            embedder = SentenceTransformerEmbedder(self.settings.embedding_model)
            self._vectorstore = VectorStore(persist_dir, embedder)
        return self._vectorstore

    def _build_rag_tool(self):
        @tool
        def rag_search(query: str) -> dict:
            """从用户私有知识库检索与问题最相关的内容片段。"""
            hits = self._ensure_vectorstore().search(query, top_k=5)
            context = "\n\n".join(
                f"[{i + 1}] {h.excerpt}\n来源：{h.path}" for i, h in enumerate(hits)
            ) or "知识库中暂未找到相关内容。"
            return {"context": context, "sources": [asdict(h) for h in hits]}

        return rag_search

    async def stream(self, conversation_id: str | None, message: str, emit: Emit) -> str:
        """执行一次 Agent 对话，通过 emit 推送 SSE 事件；返回助手回答全文。"""
        settings = self.settings
        convs = ConversationRepo(settings.db_path)
        mem_repo = MemoryRepo(settings.db_path)
        memory_text = summarize(mem_repo)

        conv_id = conversation_id
        if not conv_id or convs.get(conv_id) is None:
            conv_id = convs.create()
        await emit("session_start", {"conversation_id": conv_id})
        await emit("memory_loaded", {"summary": memory_text})
        convs.append_message(conv_id, "user", message)

        model = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.7,
            timeout=60,
        )
        history = convs.list_messages(conv_id)
        langchain_messages = [
            ({"role": "human", "content": m["content"]} if m["role"] == "user" else {"role": "ai", "content": m["content"]})
            for m in history
        ]
        client = MultiServerMCPClient(load_mcp_config(settings))
        mcp_tools = await client.get_tools()
        agent = create_agent(
            model,
            tools=[self._build_rag_tool(), *mcp_tools],
            system_prompt=_system_prompt(memory_text),
        )

        answer_parts: list[str] = []
        saved_files: list[str] = []
        last_error: Exception | None = None
        for attempt in (0, 1):
            answer_parts.clear()
            try:
                async for raw in agent.astream_events(
                    {"messages": langchain_messages}, version="v2"
                ):
                    normalized = normalize_event(raw)
                    if normalized is None:
                        continue
                    event_type, payload = normalized
                    await emit(event_type, payload)
                    if event_type == "token":
                        answer_parts.append(payload["text"])
                    elif event_type == "tool_end":
                        saved = extract_saved_file(payload.get("summary", ""))
                        if saved:
                            saved_files.append(saved)
                        if payload.get("sources"):
                            await emit("sources", {"sources": payload["sources"]})
                break
            except Exception as exc:  # 重试一次；第二次失败则上报
                last_error = exc
                if attempt == 1:
                    await emit("error", {"message": f"模型调用失败: {exc}"})

        answer = "".join(answer_parts).strip()
        if not answer:
            answer = "（抱歉，这次没有生成有效回答）"
        convs.append_message(conv_id, "assistant", answer)
        await emit("done", {})

        if settings.deepseek_api_key:
            extractor = MemoryExtractor(settings)
            asyncio.create_task(
                asyncio.to_thread(extractor.extract_and_save, conv_id, message, answer)
            )
        indexer = Indexer(settings)
        for path_text in set(saved_files):
            path = Path(path_text)
            if path.is_relative_to(settings.knowledge_dir):
                asyncio.create_task(asyncio.to_thread(indexer.index_path, path))
        return answer
```

- [ ] **Step 5: 运行测试（离线；不调用 DeepSeek）**

Run: `cd backend; uv run pytest tests/test_agent.py -v`
Expected: PASS（最后一个 MCP 集成测试会在本机拉起 stdio MCP Server）

- [ ] **Step 6: 提交**

```bash
git add backend/app/mcp_client.py backend/app/agent backend/tests/test_agent.py && git commit -m "feat: langchain agent service with rag and mcp tools"
```
### Task 9: 流式对话 API（SSE）

**Files:**
- Create: `backend/app/api/chat.py`
- Modify: `backend/app/main.py`（注册 chat router 并在 lifespan 创建 `AgentService`）
- Test: `backend/tests/test_chat_api.py`

**Interfaces:**
- Consumes: `AgentService`（Task 8）、`sse_frame`（Task 1）。
- Produces: `POST /api/chat`（`text/event-stream`）。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_chat_api.py`：

```python
import asyncio

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import init_db
from app.events import sse_frame
from app.main import app
from app.api.chat import get_agent_service


class FakeAgentService:
    async def stream(self, conversation_id, message, emit):
        await emit("session_start", {"conversation_id": "fake-conv"})
        await emit("token", {"text": "你好"})
        await emit("done", {})
        return "你好"


def test_chat_stream_returns_sse_events():
    settings = get_settings()
    init_db(settings.db_path)
    app.dependency_overrides[get_agent_service] = lambda: FakeAgentService()
    try:
        with TestClient(app) as client:
            resp = client.post("/api/chat", json={"conversation_id": None, "message": "在吗"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "event: session_start" in resp.text
        assert '"text": "你好"' in resp.text
        assert "event: done" in resp.text
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend; uv run pytest tests/test_chat_api.py -v`
Expected: FAIL，`404 Not Found`

- [ ] **Step 3: 实现 chat router**

创建 `backend/app/api/chat.py`：

```python
import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.service import AgentService
from app.config import get_settings
from app.events import sse_frame

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=20000)


def get_agent_service(request: Request) -> AgentService:
    return request.app.state.agent_service


async def _event_source(conversation_id: str | None, message: str, agent: AgentService):
    queue: asyncio.Queue[str] = asyncio.Queue()

    async def emit(event_type: str, payload: dict) -> None:
        queue.put_nowait(sse_frame(event_type, payload))

    runner = asyncio.create_task(agent.stream(conversation_id, message, emit))
    try:
        while True:
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                if runner.done():
                    break
                continue
            yield frame
            if runner.done() and queue.empty():
                break
    finally:
        if not runner.done():
            runner.cancel()


@router.post("/chat")
async def chat(payload: ChatRequest, agent: AgentService = Depends(get_agent_service)):
    return StreamingResponse(
        _event_source(payload.conversation_id, payload.message, agent),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

`backend/app/main.py` 需要做两处修改：

```python
from app.agent.service import AgentService
from app.api import chat, documents, health, memory
from app.api.chat import get_agent_service

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)
    app.state.agent_service = AgentService(settings)
    yield

app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(memory.router)
```

- [ ] **Step 4: 运行测试**

Run: `cd backend; uv run pytest tests/test_chat_api.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/chat.py backend/app/main.py backend/tests/test_chat_api.py && git commit -m "feat: sse chat endpoint"
```

### Task 10: 会话历史 API

**Files:**
- Create: `backend/app/api/conversations.py`
- Modify: `backend/app/main.py`（注册 conversations router）
- Test: `backend/tests/test_conversations_api.py`

**Interfaces:**
- Consumes: `ConversationRepo`（Task 2）。
- Produces: `GET /api/conversations`、`GET /api/conversations/{id}`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_conversations_api.py`：

```python
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import init_db
from app.main import app
from app.storage import ConversationRepo


def test_conversation_list_and_detail():
    settings = get_settings()
    init_db(settings.db_path)
    repo = ConversationRepo(settings.db_path)
    conv_id = repo.create()
    repo.append_message(conv_id, "user", "记录一下：明天开会")
    repo.append_message(conv_id, "assistant", "已记录。")

    with TestClient(app) as client:
        listed = client.get("/api/conversations").json()
        assert listed[0]["id"] == conv_id

        detail = client.get(f"/api/conversations/{conv_id}").json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]

        missing = client.get("/api/conversations/nope")
        assert missing.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend; uv run pytest tests/test_conversations_api.py -v`
Expected: FAIL，`404 Not Found`

- [ ] **Step 3: 实现会话 API**

创建 `backend/app/api/conversations.py`：

```python
from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.storage import ConversationRepo

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
def list_conversations() -> list[dict]:
    return ConversationRepo(get_settings().db_path).list_conversations()


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str) -> dict:
    repo = ConversationRepo(get_settings().db_path)
    conversation = repo.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    conversation["messages"] = repo.list_messages(conversation_id)
    return conversation
```

`backend/app/main.py` 修改 import 与注册：

```python
from app.api import chat, conversations, documents, health, memory
app.include_router(conversations.router)
```

- [ ] **Step 4: 运行测试**

Run: `cd backend; uv run pytest tests/test_conversations_api.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/conversations.py backend/app/main.py backend/tests/test_conversations_api.py && git commit -m "feat: conversations history api"
```
### Task 11: 前端脚手架与 SSE 解析

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/style.css`
- Create: `frontend/src/lib/stream.ts`
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/stream.test.ts`
- Create: `frontend/src/views/ChatView.vue`（临时占位）
- Create: `frontend/src/views/MemoryView.vue`（临时占位）
- Test: `frontend/src/lib/stream.test.ts`（Vitest）

**Interfaces:**
- Consumes: FastAPI `POST /api/chat` SSE 协议（Task 9）、REST API（Task 5/6/10）。
- Produces: `parseSseBuffer(buffer: string) -> { frames: SseEvent[]; rest: string }`、`readChatStream(response, onEvent)`、`api.ts` 客户端函数、Vue 应用入口。

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/lib/stream.test.ts`：

```typescript
import { describe, expect, it } from "vitest";
import { parseSseBuffer, type SseEvent } from "./stream";

describe("parseSseBuffer", () => {
  it("解析完整帧并保留半帧", () => {
    const input =
      'event: token\ndata: {"text":"你"}\n\nevent: token\ndata: {"text":"好"}';
    const result = parseSseBuffer(input);
    expect(result.frames).toHaveLength(2);
    expect(result.frames[0]).toEqual<SseEvent>({ event: "token", data: { text: "你" } });
    expect(result.rest).toBe("");
  });

  it("保留未结束的半帧", () => {
    const result = parseSseBuffer('event: token\ndata: {"text"');
    expect(result.frames).toHaveLength(0);
    expect(result.rest).toContain('"text"');
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend; npm install; npx vitest run src/lib/stream.test.ts`
Expected: FAIL，模块解析失败

- [ ] **Step 3: 创建前端配置与源码**

创建 `frontend/package.json`：

```json
{
  "name": "ai-assistant-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "vue": "^3.5.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.2.0",
    "typescript": "^5.6.0",
    "vite": "^6.0.0",
    "vitest": "^2.1.0"
  }
}
```

创建 `frontend/vite.config.ts`：

```typescript
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
```

创建 `frontend/tsconfig.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "jsx": "preserve",
    "skipLibCheck": true,
    "types": ["vite/client"]
  },
  "include": ["src/**/*.ts", "src/**/*.vue"]
}
```

创建 `frontend/index.html`：

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI 私人助手</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

创建 `frontend/src/lib/stream.ts`：

```typescript
export interface SseEvent {
  event: string;
  data: unknown;
}

export function parseSseBuffer(buffer: string): { frames: SseEvent[]; rest: string } {
  const frames: SseEvent[] = [];
  let rest = buffer;
  while (true) {
    const separator = rest.indexOf("\n\n");
    if (separator === -1) break;
    const block = rest.slice(0, separator);
    rest = rest.slice(separator + 2);
    const lines = block.replace(/\r/g, "").split("\n");
    let event = "message";
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (dataLines.length === 0) continue;
    let data: unknown;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      data = dataLines.join("\n");
    }
    frames.push({ event, data });
  }
  return { frames, rest };
}

export async function readChatStream(
  response: Response,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) throw new Error("浏览器不支持流式读取");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const onAbort = () => {
    void reader.cancel();
  };
  signal?.addEventListener("abort", onAbort);
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseBuffer(buffer);
      buffer = parsed.rest;
      for (const frame of parsed.frames) onEvent(frame);
    }
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }
}
```

创建 `frontend/src/lib/api.ts`：

```typescript
export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
}

export interface ChatResponse {
  message: string;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status}: ${body.slice(0, 200)}`);
  }
  return (await resp.json()) as T;
}

export const api = {
  listConversations(): Promise<ConversationSummary[]> {
    return request("/api/conversations");
  },
  listMemory(): Promise<Record<string, unknown>[]> {
    return request("/api/memory/entries");
  },
  chat(message: string, conversationId: string | null): Promise<Response> {
    return fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, message }),
    });
  },
};
```

创建 `frontend/src/main.ts`：

```typescript
import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";

createApp(App).mount("#app");
```

创建 `frontend/src/App.vue`（临时导航）：

```vue
<script setup lang="ts">
import ChatView from "./views/ChatView.vue";
import MemoryView from "./views/MemoryView.vue";
import { ref } from "vue";

const tab = ref<"chat" | "memory">("chat");
</script>

<template>
  <div class="app-shell">
    <nav class="topnav">
      <button :class="{ active: tab === 'chat' }" @click="tab = 'chat'">对话</button>
      <button :class="{ active: tab === 'memory' }" @click="tab = 'memory'">长期记忆</button>
    </nav>
    <ChatView v-if="tab === 'chat'" />
    <MemoryView v-else />
  </div>
</template>
```

创建临时占位 `frontend/src/views/ChatView.vue`：

```vue
<template>
  <main class="view-placeholder">对话视图（Task 12 实现）</main>
</template>
```

创建临时占位 `frontend/src/views/MemoryView.vue`：

```vue
<template>
  <main class="view-placeholder">长期记忆视图（Task 13 实现）</main>
</template>
```

创建 `frontend/src/style.css`：

```css
:root {
  color-scheme: light;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --border: #e3e6ea;
  --text: #1f2328;
  --muted: #6b7280;
  --accent: #2563eb;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
}
.app-shell { height: 100vh; display: flex; flex-direction: column; }
.topnav { display: flex; gap: 8px; padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--border); }
.topnav button { border: 0; background: transparent; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-size: 14px; }
.topnav button.active { background: var(--accent); color: white; }
.view-placeholder { flex: 1; display: grid; place-items: center; color: var(--muted); }
```

- [ ] **Step 4: 运行测试并构建**

Run: `cd frontend; npm install; npx vitest run src/lib/stream.test.ts; npm run build`
Expected: PASS；`dist/` 生成

- [ ] **Step 5: 提交**

```bash
git add frontend/ && git commit -m "feat: vue frontend scaffold with sse parser"
```
### Task 12: 聊天视图、过程面板与来源展示

**Files:**
- Create: `frontend/src/types.ts`
- Modify: `frontend/src/views/ChatView.vue`（替换占位）
- Create: `frontend/src/components/ChatMessage.vue`
- Create: `frontend/src/components/ToolTrace.vue`
- Create: `frontend/src/components/SourceCard.vue`
- Create: `frontend/src/components/ConversationList.vue`

**Interfaces:**
- Consumes: `api.ts`、`readChatStream`（Task 11）、`GET /api/conversations/{id}`（Task 10）。
- Produces: 可用的主聊天视图（不依赖组件测试；验证方式为 `npm run build` + 手工运行）。

- [ ] **Step 1: 创建共享类型**

创建 `frontend/src/types.ts`：

```typescript
export interface ToolStep {
  name: string;
  arguments?: unknown;
  summary?: string;
  status: "running" | "done" | "failed";
}

export interface Source {
  document_id: number;
  title: string;
  path: string;
  excerpt: string;
  score: number;
}

export interface Message {
  id?: number;
  role: "user" | "assistant";
  content: string;
  tools?: ToolStep[];
  sources?: Source[];
  done?: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
}
```

- [ ] **Step 2: 创建基础组件**

创建 `frontend/src/components/ToolTrace.vue`：

```vue
<script setup lang="ts">
import type { ToolStep } from "../types";

defineProps<{ tools: ToolStep[] }>();
</script>

<template>
  <details v-if="tools.length" class="tool-trace">
    <summary>过程（{{ tools.length }} 次工具调用）</summary>
    <ol>
      <li v-for="(step, i) in tools" :key="i" class="tool-step">
        <span class="tool-name">{{ step.name }}</span>
        <span class="tool-status" :class="step.status">{{ step.status }}</span>
        <div v-if="step.summary" class="tool-summary">{{ step.summary.slice(0, 300) }}</div>
      </li>
    </ol>
  </details>
</template>

<style scoped>
.tool-trace { border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; margin-top: 8px; background: #fafbfc; }
.tool-step { margin: 4px 0; }
.tool-status { font-size: 12px; margin-left: 6px; }
.tool-status.running { color: #b45309; }
.tool-status.done { color: #15803d; }
.tool-status.failed { color: #b91c1c; }
.tool-summary { color: var(--muted); font-size: 12px; white-space: pre-wrap; word-break: break-all; }
</style>
```

创建 `frontend/src/components/SourceCard.vue`：

```vue
<script setup lang="ts">
import type { Source } from "../types";

defineProps<{ source: Source }>();
</script>

<template>
  <details class="source-card">
    <summary>{{ source.title }}（相似度 {{ source.score }}）</summary>
    <p class="source-path">{{ source.path }}</p>
    <blockquote>{{ source.excerpt }}</blockquote>
  </details>
</template>

<style scoped>
.source-card { border-left: 3px solid var(--accent); background: #f0f6ff; border-radius: 6px; padding: 6px 10px; margin-top: 6px; font-size: 13px; }
.source-path { color: var(--muted); word-break: break-all; }
blockquote { margin: 4px 0 0; color: #374151; white-space: pre-wrap; }
</style>
```

创建 `frontend/src/components/ChatMessage.vue`：

```vue
<script setup lang="ts">
import type { Message } from "../types";
import ToolTrace from "./ToolTrace.vue";
import SourceCard from "./SourceCard.vue";

defineProps<{ message: Message }>();
</script>

<template>
  <article class="message" :class="message.role">
    <div class="bubble">{{ message.content }}</div>
    <template v-if="message.role === 'assistant'">
      <SourceCard v-for="(source, i) in message.sources" :key="i" :source="source" />
      <ToolTrace v-if="message.tools && message.tools.length" :tools="message.tools" />
    </template>
  </article>
</template>

<style scoped>
.message { display: flex; flex-direction: column; margin: 14px 0; max-width: 820px; }
.message.user { align-items: flex-end; }
.bubble { white-space: pre-wrap; line-height: 1.7; padding: 10px 14px; border-radius: 12px; max-width: 100%; word-break: break-word; }
.message.user .bubble { background: var(--accent); color: white; border-bottom-right-radius: 2px; }
.message.assistant .bubble { background: var(--panel); border: 1px solid var(--border); border-bottom-left-radius: 2px; }
</style>
```

创建 `frontend/src/components/ConversationList.vue`：

```vue
<script setup lang="ts">
import type { ConversationSummary } from "../types";

defineProps<{ conversations: ConversationSummary[]; activeId: string | null }>();
const emit = defineEmits<{
  select: [id: string];
  create: [];
}>();
</script>

<template>
  <aside class="conv-sidebar">
    <button class="new-conv" @click="emit('create')">＋ 新对话</button>
    <button
      v-for="conv in conversations"
      :key="conv.id"
      class="conv-item"
      :class="{ active: conv.id === activeId }"
      @click="emit('select', conv.id)"
    >
      {{ conv.title }}
    </button>
  </aside>
</template>

<style scoped>
.conv-sidebar { width: 240px; border-right: 1px solid var(--border); background: var(--panel); padding: 12px; display: flex; flex-direction: column; gap: 6px; overflow-y: auto; }
.new-conv { border: 1px dashed var(--border); background: transparent; padding: 8px; border-radius: 8px; cursor: pointer; }
.conv-item { text-align: left; border: 0; background: transparent; padding: 8px; border-radius: 8px; cursor: pointer; font-size: 14px; }
.conv-item:hover { background: #f0f1f3; }
.conv-item.active { background: #e7efff; color: var(--accent); }
</style>
```

- [ ] **Step 3: 实现 ChatView**

替换 `frontend/src/views/ChatView.vue`：

```vue
<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api } from "../lib/api";
import { readChatStream } from "../lib/stream";
import type { ConversationSummary, Message, Source, ToolStep } from "../types";
import ChatMessage from "../components/ChatMessage.vue";
import ConversationList from "../components/ConversationList.vue";

const conversations = ref<ConversationSummary[]>([]);
const activeId = ref<string | null>(null);
const messages = ref<Message[]>([]);
const input = ref("");
const busy = ref(false);
const errorText = ref("");

let currentAssistant: Message | null = null;

function addMessage(role: "user" | "assistant", content = ""): Message {
  const message: Message = { role, content };
  if (role === "assistant") {
    message.tools = [];
    message.sources = [];
    message.done = false;
    currentAssistant = message;
  }
  messages.value.push(message);
  return message;
}

function ensureCurrentAssistant(): Message {
  if (!currentAssistant || currentAssistant.done) {
    return addMessage("assistant");
  }
  return currentAssistant;
}

async function refreshConversations(): Promise<void> {
  conversations.value = await api.listConversations();
}

function startNew(): void {
  activeId.value = null;
  messages.value = [];
  currentAssistant = null;
}

async function openConversation(id: string): Promise<void> {
  activeId.value = id;
  messages.value = [];
  const resp = await fetch(`/api/conversations/${id}`);
  if (!resp.ok) return;
  const data = (await resp.json()) as { messages: Message[] };
  messages.value = data.messages.map((m) => ({ ...m, tools: [], sources: [], done: true }));
}

async function send(): Promise<void> {
  const text = input.value.trim();
  if (!text || busy.value) return;
  input.value = "";
  busy.value = true;
  errorText.value = "";
  addMessage("user", text);
  try {
    const response = await api.chat(text, activeId.value);
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
    await readChatStream(response, (frame) => {
      const payload = frame.data as Record<string, unknown>;
      if (frame.event === "session_start") {
        activeId.value = String(payload.conversation_id);
        void refreshConversations();
      } else if (frame.event === "token") {
        ensureCurrentAssistant().content += String(payload.text ?? "");
      } else if (frame.event === "tool_start") {
        ensureCurrentAssistant().tools?.push({
          name: String(payload.tool),
          arguments: payload.arguments,
          status: "running",
        } as ToolStep);
      } else if (frame.event === "tool_end") {
        const tools = ensureCurrentAssistant().tools ?? [];
        const step = tools[tools.length - 1];
        if (step) {
          step.status = payload.ok === false ? "failed" : "done";
          step.summary = String(payload.summary ?? "");
        }
      } else if (frame.event === "sources") {
        const list = (payload.sources as Source[]) ?? [];
        ensureCurrentAssistant().sources?.push(...list);
      } else if (frame.event === "error") {
        errorText.value = String(payload.message ?? "发生未知错误");
        if (currentAssistant) currentAssistant.done = true;
      } else if (frame.event === "done") {
        if (currentAssistant) currentAssistant.done = true;
      }
    });
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error);
  } finally {
    if (currentAssistant) currentAssistant.done = true;
    currentAssistant = null;
    busy.value = false;
  }
}

onMounted(refreshConversations);
</script>

<template>
  <main class="chat-layout">
    <ConversationList
      :conversations="conversations"
      :active-id="activeId"
      @create="startNew"
      @select="openConversation"
    />
    <section class="chat-main">
      <div class="messages">
        <ChatMessage v-for="(message, i) in messages" :key="i" :message="message" />
      </div>
      <p v-if="errorText" class="chat-error">{{ errorText }}</p>
      <form class="input-row" @submit.prevent="send">
        <textarea v-model="input" rows="2" placeholder="和你的私人助手聊聊…" @keydown.enter.exact.prevent="send" />
        <button :disabled="busy || !input.trim()">{{ busy ? "思考中…" : "发送" }}</button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.chat-layout { flex: 1; display: flex; min-height: 0; }
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.messages { flex: 1; overflow-y: auto; padding: 0 24px; display: flex; flex-direction: column; }
.chat-error { color: #b91c1c; padding: 0 24px; }
.input-row { display: flex; gap: 10px; padding: 14px 24px; border-top: 1px solid var(--border); background: var(--panel); }
textarea { flex: 1; resize: none; border: 1px solid var(--border); border-radius: 10px; padding: 10px; font: inherit; }
button { border: 0; background: var(--accent); color: white; padding: 0 20px; border-radius: 10px; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
```

- [ ] **Step 4: 验证构建**

Run: `cd frontend; npm run build`
Expected: 构建成功（TypeScript 无错误、`dist/` 生成）

- [ ] **Step 5: 提交**

```bash
git add frontend/src && git commit -m "feat: chat view with tool trace and sources"
```
### Task 13: 长期记忆管理视图

**Files:**
- Modify: `frontend/src/views/MemoryView.vue`（替换占位）
- Create: `frontend/src/components/MemoryPanel.vue`

**Interfaces:**
- Consumes: `GET/PUT/DELETE /api/memory/entries`（Task 6）、`api.listMemory()`（Task 11）。
- Produces: 可查看/编辑/删除长期记忆的界面。

- [ ] **Step 1: 实现 MemoryPanel**

创建 `frontend/src/components/MemoryPanel.vue`：

```vue
<script setup lang="ts">
import { ref } from "vue";

interface MemoryEntry {
  id: number;
  type: string;
  content: string;
  manual: number;
}

defineProps<{ entries: MemoryEntry[] }>();
const emit = defineEmits<{ save: [id: number, content: string]; remove: [id: number] }>();
const editingId = ref<number | null>(null);
const draft = ref("");
</script>

<template>
  <div class="memory-list">
    <article v-for="entry in entries" :key="entry.id" class="memory-row">
      <div class="memory-meta">
        <span class="type-badge">{{ entry.type }}</span>
        <span v-if="entry.manual" class="manual-badge">手动</span>
      </div>
      <template v-if="editingId === entry.id">
        <textarea v-model="draft" rows="2"></textarea>
        <div class="row-actions">
          <button @click="emit('save', entry.id, draft); editingId = null">保存</button>
          <button class="ghost" @click="editingId = null">取消</button>
        </div>
      </template>
      <template v-else>
        <p>{{ entry.content }}</p>
        <div class="row-actions">
          <button class="ghost" @click="editingId = entry.id; draft = entry.content">编辑</button>
          <button class="danger" @click="emit('remove', entry.id)">删除</button>
        </div>
      </template>
    </article>
    <p v-if="entries.length === 0" class="empty">还没有长期记忆。对助手说“记住……”即可添加。</p>
  </div>
</template>

<style scoped>
.memory-list { display: flex; flex-direction: column; gap: 10px; }
.memory-row { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; }
.memory-meta { display: flex; gap: 8px; margin-bottom: 4px; }
.type-badge { font-size: 12px; background: #e7efff; color: var(--accent); border-radius: 6px; padding: 2px 8px; }
.manual-badge { font-size: 12px; background: #eef2f6; color: var(--muted); border-radius: 6px; padding: 2px 8px; }
textarea { width: 100%; border: 1px solid var(--border); border-radius: 8px; padding: 8px; font: inherit; }
.row-actions { display: flex; gap: 8px; margin-top: 8px; }
button { border: 0; background: var(--accent); color: white; border-radius: 6px; padding: 6px 12px; cursor: pointer; }
button.ghost { background: transparent; color: var(--accent); border: 1px solid var(--border); }
button.danger { background: transparent; color: #b91c1c; border: 1px solid #fecaca; }
.empty { color: var(--muted); text-align: center; }
</style>
```

- [ ] **Step 2: 实现 MemoryView**

替换 `frontend/src/views/MemoryView.vue`：

```vue
<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../lib/api";
import MemoryPanel from "../components/MemoryPanel.vue";

interface MemoryEntry {
  id: number;
  type: string;
  content: string;
  manual: number;
}

const entries = ref<MemoryEntry[]>([]);
const errorText = ref("");

async function refresh(): Promise<void> {
  entries.value = (await api.listMemory()) as MemoryEntry[];
}

async function saveEntry(id: number, content: string): Promise<void> {
  const type = entries.value.find((e) => e.id === id)?.type ?? "general";
  const resp = await fetch(`/api/memory/entries/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, content }),
  });
  if (!resp.ok) errorText.value = "保存失败";
  await refresh();
}

async function removeEntry(id: number): Promise<void> {
  const resp = await fetch(`/api/memory/entries/${id}`, { method: "DELETE" });
  if (!resp.ok) errorText.value = "删除失败";
  await refresh();
}

onMounted(refresh);
</script>

<template>
  <main class="memory-view">
    <h1>长期记忆</h1>
    <p class="hint">助手会把这些内容在每次对话开始时注入；可随时编辑或删除。</p>
    <p v-if="errorText" class="memory-error">{{ errorText }}</p>
    <MemoryPanel :entries="entries" @save="saveEntry" @remove="removeEntry" />
  </main>
</template>

<style scoped>
.memory-view { flex: 1; overflow-y: auto; padding: 24px; max-width: 860px; width: 100%; margin: 0 auto; }
h1 { font-size: 20px; }
.hint { color: var(--muted); }
.memory-error { color: #b91c1c; }
</style>
```

- [ ] **Step 3: 验证构建**

Run: `cd frontend; npm run build`
Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src && git commit -m "feat: memory management view"
```
### Task 14: 知识库文档管理视图

**Files:**
- Create: `frontend/src/views/DocumentsView.vue`
- Modify: `frontend/src/App.vue`（新增“知识库”标签）
- Modify: `frontend/src/lib/api.ts`（新增文档接口封装）

**Interfaces:**
- Consumes: `POST/GET/DELETE /api/documents`、`POST /api/documents/scan`（Task 5）。
- Produces: 上传/扫描/删除/查看索引状态的文档界面。

- [ ] **Step 1: 扩展 api.ts**

在 `frontend/src/lib/api.ts` 末尾补充类型与函数：

```typescript
export interface DocumentItem {
  id: number;
  filename: string;
  path: string;
  file_type: string;
  status: string;
  chunk_count: number | null;
  error: string | null;
}

export const documentsApi = {
  list(): Promise<DocumentItem[]> {
    return request("/api/documents");
  },
  upload(file: File): Promise<{ status: string }> {
    const form = new FormData();
    form.append("file", file);
    return request("/api/documents/upload", { method: "POST", body: form });
  },
  scan(): Promise<{ scanned: string[] }> {
    return request("/api/documents/scan", { method: "POST" });
  },
  remove(id: number): Promise<{ ok: boolean }> {
    return request(`/api/documents/${id}`, { method: "DELETE" });
  },
};
```

- [ ] **Step 2: 实现 DocumentsView**

创建 `frontend/src/views/DocumentsView.vue`：

```vue
<script setup lang="ts">
import { onMounted, ref } from "vue";
import { documentsApi, type DocumentItem } from "../lib/api";

const items = ref<DocumentItem[]>([]);
const uploading = ref(false);
const scanning = ref(false);
const messageText = ref("");
const fileInput = ref<HTMLInputElement | null>(null);

async function refresh(): Promise<void> {
  items.value = await documentsApi.list();
}

async function uploadFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  uploading.value = true;
  messageText.value = "";
  try {
    await documentsApi.upload(file);
    messageText.value = `已加入索引队列：${file.name}`;
    await refresh();
  } catch (error) {
    messageText.value = error instanceof Error ? error.message : "上传失败";
  } finally {
    uploading.value = false;
    if (fileInput.value) fileInput.value.value = "";
  }
}

async function scan(): Promise<void> {
  scanning.value = true;
  messageText.value = "";
  try {
    const result = await documentsApi.scan();
    messageText.value = `已扫描 ${result.scanned.length} 个文件`;
    await refresh();
  } finally {
    scanning.value = false;
  }
}

async function remove(id: number): Promise<void> {
  await documentsApi.remove(id);
  await refresh();
}

onMounted(refresh);
</script>

<template>
  <main class="docs-view">
    <h1>知识库</h1>
    <div class="toolbar">
      <input ref="fileInput" type="file" :disabled="uploading" @change="uploadFile" />
      <button :disabled="scanning" @click="scan">{{ scanning ? "扫描中…" : "扫描 knowledge/ 文件夹" }}</button>
    </div>
    <p v-if="messageText" class="docs-message">{{ messageText }}</p>
    <table v-if="items.length">
      <thead>
        <tr><th>文件名</th><th>类型</th><th>状态</th><th>切片数</th><th></th></tr>
      </thead>
      <tbody>
        <tr v-for="doc in items" :key="doc.id">
          <td :title="doc.path">{{ doc.filename }}</td>
          <td>{{ doc.file_type }}</td>
          <td :class="doc.status">{{ doc.status }}</td>
          <td>{{ doc.chunk_count ?? "-" }}</td>
          <td><button class="danger" @click="remove(doc.id)">删除</button></td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty">还没有文档。上传文件，或把文件放进 knowledge/ 后点击扫描。</p>
  </main>
</template>

<style scoped>
.docs-view { flex: 1; overflow-y: auto; padding: 24px; max-width: 960px; width: 100%; margin: 0 auto; }
h1 { font-size: 20px; }
.toolbar { display: flex; gap: 12px; align-items: center; margin: 12px 0; flex-wrap: wrap; }
button { border: 0; background: var(--accent); color: white; border-radius: 8px; padding: 8px 14px; cursor: pointer; }
button.danger { background: transparent; color: #b91c1c; border: 1px solid #fecaca; }
button:disabled { opacity: 0.6; }
table { width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
td.status.completed { color: #15803d; }
td.status.failed { color: #b91c1c; }
td.status.indexing, td.status.pending { color: #b45309; }
.docs-message { color: #15803d; }
.empty { color: var(--muted); }
</style>
```

- [ ] **Step 3: 更新 App 导航**

更新 `frontend/src/App.vue` 为三个标签：

```vue
<script setup lang="ts">
import ChatView from "./views/ChatView.vue";
import DocumentsView from "./views/DocumentsView.vue";
import MemoryView from "./views/MemoryView.vue";
import { ref } from "vue";

const tab = ref<"chat" | "documents" | "memory">("chat");
</script>

<template>
  <div class="app-shell">
    <nav class="topnav">
      <button :class="{ active: tab === 'chat' }" @click="tab = 'chat'">对话</button>
      <button :class="{ active: tab === 'documents' }" @click="tab = 'documents'">知识库</button>
      <button :class="{ active: tab === 'memory' }" @click="tab = 'memory'">长期记忆</button>
    </nav>
    <ChatView v-if="tab === 'chat'" />
    <DocumentsView v-else-if="tab === 'documents'" />
    <MemoryView v-else />
  </div>
</template>
```

- [ ] **Step 4: 验证构建**

Run: `cd frontend; npm run build`
Expected: 构建成功

- [ ] **Step 5: 提交**

```bash
git add frontend/src && git commit -m "feat: knowledge documents view"
```
### Task 15: 生产托管、README 与整体验收

**Files:**
- Modify: `backend/app/main.py`（托管 `frontend/dist` + SPA fallback）
- Create: `backend/tests/test_static.py`
- Create: `README.md`
- Create: `.env.example` 已在 Task 1（无需新建）

**Interfaces:**
- Consumes: 所有后端路由；`frontend/dist`（Task 11-14 构建产物）。
- Produces: 一条命令启动的完整应用与验收指引。

- [ ] **Step 1: 写测试**

创建 `backend/tests/test_static.py`：

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

pytestmark = pytest.mark.skipif(not (DIST / "index.html").exists(), reason="前端未构建")


def test_spa_served_when_dist_exists():
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
```

- [ ] **Step 2: 更新 main.py 的静态托管**

在 `backend/app/main.py` 末尾追加：

```python
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse

from app.config import BACKEND_DIR

FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"
if (FRONTEND_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_relative_to(FRONTEND_DIST.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
```

注意：此代码引用 `StaticFiles`，把 `from fastapi.staticfiles import StaticFiles` 也加到 import 区。`app.include_router` 的调用必须保持在 spa_fallback 之前（现有文件顺序已经满足）。

- [ ] **Step 3: 构建前端并运行全部后端测试**

Run:
```bash
cd frontend; npm run build
cd ../backend; uv run pytest -v
```
Expected: 全部 PASS（`test_static.py` 会真正检查 `/` 返回 HTML）

- [ ] **Step 4: 编写 README**

创建根目录 `README.md`：

````markdown
# AI 私人助手

本地运行的 AI 私人助手：Vue 3 网页流式聊天 + FastAPI + LangChain 单 Agent + DeepSeek + 本地 RAG + 长期记忆 + MCP 工具。

## 环境要求

- Windows 10/11；Python 3.11+；Node 20+；uv
- DeepSeek API Key（在 https://platform.deepseek.com 获取）
- 首次运行会联网下载本地嵌入模型 `BAAI/bge-small-zh-v1.5`

## 启动（开发模式）

```bash
cd backend
Copy-Item .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY
uv sync --group dev
uv run uvicorn app.main:app --reload --port 8000
```

另开终端：

```bash
cd frontend
npm install
npm run dev
# 浏览器打开 http://127.0.0.1:5173
```

## 启动（生产/单地址模式）

```bash
cd frontend && npm run build
cd ../backend && uv run uvicorn app.main:app --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

## 测试

```bash
cd backend && uv run pytest -v
cd frontend && npx vitest run
```

## 使用提示

- 对话：直接聊天；回答引用知识库时会显示来源卡片与工具调用过程。
- 知识库：在“知识库”页上传 Markdown/TXT/PDF/Word，或把文件放进 `knowledge/` 后点扫描。
- 长期记忆：对助手说“记住我叫 XX / 我喜欢简洁回答”，随后可在“长期记忆”页查看、编辑、删除。
- MCP：笔记与网页抓取由本地 MCP Server 提供；新增第三方 MCP Server 时编辑根目录 `mcp_config.json`。

## 数据位置

- 原始文档：`knowledge/`
- SQLite（会话/消息/记忆）：`data/assistant.db`
- 向量库：`data/vectorstore`
- 日志/临时数据：`data/`
````

- [ ] **Step 5: 提交**

```bash
git add README.md backend/app/main.py backend/tests/test_static.py && git commit -m "feat: static hosting, readme and acceptance suite"
```

### Task 16: 全链路验收（手动清单，最终任务）

**Files:** 无（仅验收）。

- [ ] **Step 1: 启动前后端并完成验收**

按 README 启动后逐项验证：

1. 浏览器打开 `http://127.0.0.1:8000`（或 Vite 5173），完成多轮流式对话。
2. 对话中能看到工具调用；知识回答能展开来源。
3. “知识库”页上传一个 Markdown/PDF，随后提问其内容并看到来源。
4. 对助手说“记住我叫测试员 / 我喜欢简洁回答”；重启服务后新会话仍体现记忆，并可在“长期记忆”页删除。
5. 对助手说“记一条笔记：明天下午三点开会”，确认 `knowledge/notes/` 出现 Markdown 并可被检索。
6. 让助手保存一个可达网页链接，确认正文入库并可被检索。
7. 断开网络或填入错误 Key，确认出现清晰错误提示且服务不崩溃。

- [ ] **Step 2: 记录结果并提交**

如全部通过，在 README 追加“验收记录”小节并提交：

```bash
git add README.md && git commit -m "docs: record manual acceptance results"
```










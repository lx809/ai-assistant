import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# 对话仓库，负责对话相关的数据库操作
# 包括创建对话、追加消息、列出对话、获取对话详情、更新对话更新时间、删除对话等
class ConversationRepo:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return connect(self.db_path)

    # 创建对话，默认返回新对话的ID
    def create(self) -> str:
        conv_id = uuid4().hex
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversations (id, created_at, updated_at) VALUES (?, ?, ?)",
                (conv_id, now, now),
            )
        return conv_id

    # 追加消息到对话，如果消息是用户消息，更新对话标题为消息内容的前30个字符，否则保持标题不变
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

    # 列出对话中的所有消息
    # 按创建时间升序排序
    def list_messages(self, conversation_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # 列出所有对话
    # 按更新时间降序排序
    def list_conversations(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, title, summary, created_at, updated_at FROM conversations "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # 根据对话ID获取对话详情
    def get(self, conversation_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, title, summary, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    # 更新对话的更新时间，将对话的放在最前面
    def touch(self, conversation_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), conversation_id))

    # 删除对话，包括对话中的所有消息
    def delete_conversation(self, conversation_id: str) -> bool:
        with self._conn() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cur.rowcount > 0


# 记忆仓库，负责记忆相关的数据库操作
# 包括列出所有记忆、创建记忆、更新记忆、删除记忆、生成记忆摘要等
class MemoryRepo:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return connect(self.db_path)

    # 列出所有记忆
    # 按更新时间倒序排序
    def list_entries(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, type, content, source_conversation_id, manual, created_at, updated_at "
                "FROM memory_entries ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # 创建记忆
    # 创建新的记忆条目
    def create_entry(self, type_: str, content: str, source_conversation_id: str | None = None, manual: bool = False) -> int:
        now = _now()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO memory_entries (type, content, source_conversation_id, manual, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (type_, content, source_conversation_id, 1 if manual else 0, now, now),
            )
            return int(cur.lastrowid)

    # 更新记忆
    # 更新指定记忆条目的的内容和类型
    def update_entry(self, entry_id: int, content: str, type_: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE memory_entries SET content = ?, type = ?, updated_at = ? WHERE id = ?",
                (content, type_, _now(), entry_id),
            )
            return cur.rowcount > 0

    # 删除记忆
    # 删除指定记忆条目
    def delete_entry(self, entry_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
            return cur.rowcount > 0

    # 生成记忆摘要
    # 从最近50条记忆中提取类型和内容，生成一个简单的文本摘要
    # 每个记忆条目占一行，格式为"[类型] 内容"
    # 摘要以"关于用户的长期记忆："开头
    def summary(self) -> str:
        rows = self.list_entries()[:50]
        if not rows:
            return ""
        lines = [f"- [{r['type']}] {r['content']}" for r in rows]
        return "关于用户的长期记忆：\n" + "\n".join(lines)


# 文档仓库，负责文档相关的数据库操作
# 包括注册文档、设置文档状态、列出文档、根据文档路径获取文档详情、删除文档等
class DocumentRepo:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return connect(self.db_path)

    # 注册文档
    # 注册新的文档条目
    # 包含文件名、路径、文件类型、内容哈希值、创建时间
    # 返回文档ID
    def register(self, filename: str, path: str, file_type: str, content_hash: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO documents (filename, path, file_type, content_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (filename, path, file_type, content_hash, _now()),
            )
            return int(cur.lastrowid)

    # 设置文档状态
    # 更新指定文档条目的状态、分块数量和错误信息
    # 可选参数：状态、分块数量、错误信息
    def set_status(self, doc_id: int, status: str, chunk_count: int | None = None, error: str | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE documents SET status = ?, chunk_count = ?, error = ? WHERE id = ?",
                (status, chunk_count, error, doc_id),
            )

    # 列出所有文档
    # 按创建时间倒序排序
    def list_documents(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, filename, path, file_type, status, content_hash, chunk_count, error, created_at "
                "FROM documents ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # 根据文档路径获取文档详情
    # 返回指定文档条目的详细信息
    def get_by_path(self, path: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, filename, path, file_type, status, content_hash, chunk_count, error, created_at "
                "FROM documents WHERE path = ?",
                (path,),
            ).fetchone()
        return dict(row) if row else None
    
    # 删除文档
    # 删除指定文档条目
    def delete(self, doc_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


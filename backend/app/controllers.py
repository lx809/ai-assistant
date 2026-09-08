import asyncio
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.agent import AgentService
from app.config import get_settings
from app.models import ConversationRepo, DocumentRepo, MemoryRepo
from app.services.memory import ALLOWED_TYPES
from app.services.rag import Indexer, SUPPORTED_SUFFIXES

logger = logging.getLogger(__name__)


# 生成 SSE 帧，用于实时更新前端
# 包含事件类型和 JSON 数据
# 返回格式化的字符串
def _sse_frame(event_type: str, payload: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------- 公共依赖 ----------

# 从请求中获取智能体服务实例
# 返回智能体服务实例
def get_agent_service(request: Request) -> AgentService:
    return request.app.state.agent_service

# 处理 SSE 请求，返回智能体的实时输出
# 包含对话ID、用户消息、智能体服务实例
# 返回异步生成器，每次迭代生成一个 SSE 帧
async def _event_source(conversation_id: str | None, message: str, agent: AgentService):
    queue: asyncio.Queue[str] = asyncio.Queue()
    started = time.perf_counter()

    async def emit(event_type: str, payload: dict) -> None:
        if event_type == "error":
            logger.error("对话流发生错误事件: conversation=%s message=%s", payload.get("message"), message[:50])
        queue.put_nowait(_sse_frame(event_type, payload))

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
    except asyncio.CancelledError:
        logger.warning("客户端断开，终止对话流: conversation=%s", conversation_id)
        raise
    finally:
        if not runner.done():
            runner.cancel()
            logger.warning("对话流被提前取消: conversation=%s 耗时=%.1fs", conversation_id, time.perf_counter() - started)

# 定义聊天请求模型
# 包含对话ID和用户消息
class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=20000)


# ---------- Health ----------

# 健康检查路由
# 返回服务状态、配置信息、知识库目录、嵌入模型、 MCP 配置是否存在
health_router = APIRouter(prefix="/api", tags=["health"])


@health_router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "deepseek_configured": bool(settings.deepseek_api_key),
        "knowledge_dir": str(settings.knowledge_dir),
        "embedding_model": settings.embedding_model,
        "mcp_config_exists": settings.mcp_config_path.exists(),
    }


# ---------- Documents ----------

# 文档路由，负责上传、扫描、列出和删除文档
# 包括上传文档、扫描知识库、列出文档、删除文档等操作
documents_router = APIRouter(prefix="/api/documents", tags=["documents"])
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# 安全文件名处理函数，确保文件名符合要求
# 包含文件名、后缀、时间戳、随机数等
# 返回安全处理后的文件名
def _safe_filename(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "_", name) or "upload"

# 后台索引文档函数，负责将文档内容索引到向量数据库中
def _index_background(path: Path, settings) -> None:
    Indexer(settings).index_path(path)

# 上传文档路由
# 接收上传的文件，检查文件类型、大小、内容等
# 返回上传文件的路径和状态信息
@documents_router.post("/upload")
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

# 扫描知识库路由
# 递归扫描知识库目录，将所有支持的文件索引到向量数据库中
# 返回扫描到的文件路径列表
@documents_router.post("/scan")
def scan_knowledge(background: BackgroundTasks) -> dict:
    settings = get_settings()
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    files = [p for p in settings.knowledge_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]
    for path in files:
        background.add_task(_index_background, path, settings)
    return {"scanned": [str(p) for p in files]}

# 列出文档路由
# 返回所有文档的列表
@documents_router.get("")
def list_documents() -> list[dict]:
    return DocumentRepo(get_settings().db_path).list_documents()

# 删除文档路由
# 接收文档ID，删除对应文档
# 返回删除成功的确认信息
@documents_router.delete("/{doc_id}")
def delete_document(doc_id: int) -> dict:
    settings = get_settings()
    docs = DocumentRepo(settings.db_path)
    target = next((d for d in docs.list_documents() if d["id"] == doc_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    indexer = Indexer(settings)
    indexer.delete_document(doc_id)
    path = Path(target["path"])
    if path.is_relative_to(settings.knowledge_dir):
        path.unlink(missing_ok=True)
    return {"ok": True}


# ---------- Memory ----------

# 记忆路由，负责列出、更新和删除记忆条目
# 包括列出记忆条目、更新记忆条目、删除记忆条目等操作
memory_router = APIRouter(prefix="/api/memory", tags=["memory"])

# 记忆条目更新模型，定义更新记忆条目的请求参数
# 包含记忆条目类型和内容
class EntryUpdate(BaseModel):
    type: str
    content: str

# 列出记忆条目路由
# 返回所有记忆条目的列表
@memory_router.get("/entries")
def list_entries() -> list[dict]:
    return MemoryRepo(get_settings().db_path).list_entries()

# 更新记忆条目路由
# 接收记忆条目ID和更新内容，更新对应记忆条目
# 返回更新后的记忆条目
# 如果记忆条目不存在，返回 404 错误
@memory_router.put("/entries/{entry_id}")
def update_entry(entry_id: int, payload: EntryUpdate) -> dict:
    if payload.type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"type 必须是 {sorted(ALLOWED_TYPES)} 之一")
    repo = MemoryRepo(get_settings().db_path)
    if not repo.update_entry(entry_id, payload.content.strip(), payload.type):
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    return next(e for e in repo.list_entries() if e["id"] == entry_id)

# 删除记忆条目路由
# 接收记忆条目ID，删除对应记忆条目
# 返回删除成功的确认信息
# 如果记忆条目不存在，返回 404 错误
@memory_router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int) -> dict:
    if not MemoryRepo(get_settings().db_path).delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    return {"ok": True}


# ---------- Conversations ----------

# 会话路由，负责列出、获取和删除会话
# 包括列出会话、获取会话、删除会话等操作
conversations_router = APIRouter(prefix="/api/conversations", tags=["conversations"])

# 列出会话路由
# 返回所有会话的列表
@conversations_router.get("")
def list_conversations() -> list[dict]:
    return ConversationRepo(get_settings().db_path).list_conversations()


# 获取会话路由
# 接收会话ID，返回对应会话的详细信息
# 如果会话不存在，返回 404 错误
@conversations_router.get("/{conversation_id}")
def get_conversation(conversation_id: str) -> dict:
    repo = ConversationRepo(get_settings().db_path)
    conversation = repo.get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    conversation["messages"] = repo.list_messages(conversation_id)
    return conversation


# ---------- Chat ----------

# 聊天路由，负责与智能体进行对话
# 包括发送消息、接收回复等操作
chat_router = APIRouter(prefix="/api", tags=["chat"])

# 发送消息路由
# 接收会话ID和消息内容，发送消息到智能体
# 返回智能体的回复流
@chat_router.post("/chat")
async def chat(payload: ChatRequest, agent: AgentService = Depends(get_agent_service)):
    logger.info(
        "对话请求: conversation=%s 消息长度=%d",
        payload.conversation_id or "新会话",
        len(payload.message),
    )
    return StreamingResponse(
        _event_source(payload.conversation_id, payload.message, agent),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# 删除会话路由
# 接收会话ID，删除对应会话
# 返回删除成功的确认信息
# 如果会话不存在，返回 404 错误
@conversations_router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    repo = ConversationRepo(get_settings().db_path)
    if not repo.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    logger.info("会话已删除: %s", conversation_id)
    return {"ok": True}

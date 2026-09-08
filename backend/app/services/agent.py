import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Awaitable, Callable

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.logging_setup import timed_step
from app.models import ConversationRepo, MemoryRepo
from app.services.memory import MemoryExtractor, summarize
from app.services.rag import Indexer, SentenceTransformerEmbedder, VectorStore

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict], Awaitable[None]]
MAX_MEMORY_TEXT = 3000
SERVER_SCRIPT = Path(__file__).resolve().parent.parent.parent / "mcp_server" / "server.py"


# ---------- 模型配置 ----------
# 创建 ChatOpenAI 模型实例
def _create_chat_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.7,
        timeout=60,
        streaming=True,
    )


# ---------- MCP 配置 ----------
# 创建默认 MCP 配置
def _default_mcp_config(settings: Settings) -> dict:
    return {
        "assistant_tools": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(SERVER_SCRIPT), "--knowledge-dir", str(settings.knowledge_dir)],
        }
    }

# 加载 MCP 配置
# 读取 mcp_config.json；缺失或缺少默认 server 时创建/补全默认条目，不覆盖用户已有条目。
def load_mcp_config(settings: Settings) -> dict:
    """读取 mcp_config.json；缺失或缺少默认 server 时创建/补全默认条目，不覆盖用户已有条目。"""
    default = _default_mcp_config(settings)
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


# ---------- 工具结果解析 ----------

def _iter_json_strings(obj: object):
    """递归收集工具调用结果对象中的 JSON 文本候选（如 MCP 内容块的 text 字段）。"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "text" and isinstance(value, str):
                yield value
            yield from _iter_json_strings(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_json_strings(item)
    elif isinstance(obj, str):
        yield obj

def extract_saved_file(output: object) -> str | None:
    """从 MCP 工具返回内容中提取 saved_file（优先按 JSON 解析，避免转义反斜杠）。"""
    if isinstance(output, dict) and isinstance(output.get("saved_file"), str):
        return output["saved_file"]
    for candidate in _iter_json_strings(output):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        found = _find_saved_file(data)
        if found:
            return found
    for candidate in _iter_json_strings(output):
        match = re.search(r'"saved_file"\s*:\s*"([^"]+)"', candidate)
        if match:
            return match.group(1)
    return None

def _find_saved_file(obj: object) -> str | None:
    """递归查找工具调用结果对象中的 saved_file 字段。"""
    if isinstance(obj, dict):
        if isinstance(obj.get("saved_file"), str):
            return obj["saved_file"]
        for value in obj.values():
            found = _find_saved_file(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_saved_file(item)
            if found:
                return found
    return None


def extract_sources(output: object) -> list[dict]:
    """从 MCP 工具返回内容中提取 sources 字段（优先按 JSON 解析）。避免递归调用。"""
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


# 生成系统提示词
# 包含行为规则、长期记忆
def _system_prompt(memory_text: str) -> str:
    rules = (
        "你是用户的私人 AI 助手。行为规则：\n"
        "1. 回答要自然、准确、简洁；需要用户资料时先调用 rag_search 检索，不要编造来源。\n"
        "2. 用户明确要求记录或提供链接要求保存时，调用 notes_create 或 web_save。\n"
        "3. 工具失败时如实告知用户，不要假装成功。\n"
    )
    memory = memory_text[:MAX_MEMORY_TEXT]
    return rules + ("\n长期记忆：\n" + memory if memory else "")


# ---------- 后台任务（带日志的异常兜底） ----------

async def _extract_memory_logged(extractor: MemoryExtractor, conv_id: str, message: str, answer: str) -> None:
    try:
        start = time.perf_counter()
        saved = await asyncio.to_thread(extractor.extract_and_save, conv_id, message, answer)
        if saved:
            logger.info("记忆提炼完成: conversation=%s 新增=%d 用时=%.2fs", conv_id, saved, time.perf_counter() - start)
        else:
            logger.debug("记忆提炼: 无新增条目 conversation=%s 用时=%.2fs", conv_id, time.perf_counter() - start)
    except Exception:
        logger.exception("记忆提炼失败: conversation=%s", conv_id)


async def _index_file_logged(indexer: Indexer, path: Path) -> None:
    try:
        start = time.perf_counter()
        result = await asyncio.to_thread(indexer.index_path, path)
        logger.info("文件索引完成: %s -> %s 用时=%.2fs", path.name, result, time.perf_counter() - start)
    except Exception:
        logger.exception("文件索引失败: %s", path)


# ---------- Agent 服务 ----------
# 包含工具调用、系统提示词生成、对话管理等功能
class AgentService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._vectorstore: VectorStore | None = None
        self._mcp_client: MultiServerMCPClient | None = None
        self._mcp_tools: list | None = None
        self._mcp_lock = asyncio.Lock()

    async def _ensure_mcp_tools(self) -> list:
        """获取 MCP 工具列表，建立后缓存在服务实例上复用，避免每条消息重新 spawn 子进程。"""
        async with self._mcp_lock:
            if self._mcp_tools is not None:
                return self._mcp_tools
            with timed_step(logger, "MCP 连接建立(子进程启动+工具加载)"):
                client = MultiServerMCPClient(load_mcp_config(self.settings))
                tools = await client.get_tools()
            self._mcp_client = client
            self._mcp_tools = tools
        logger.info("MCP 工具缓存就绪: 工具=%s", [t.name for t in tools])
        return tools

    def _reset_mcp_cache(self) -> None:
        self._mcp_client = None
        self._mcp_tools = None

    async def warm_up(self) -> None:
        """应用启动时后台预热 MCP 连接，让首条消息不必等待子进程启动。"""
        try:
            await self._ensure_mcp_tools()
        except Exception:
            logger.warning("MCP 预热失败，将在首次对话时重试", exc_info=True)
            self._reset_mcp_cache()

    # 确保向量数据库已初始化
    # 仅在需要时加载，避免重复加载
    def _ensure_vectorstore(self) -> VectorStore:
        if self._vectorstore is None:
            persist_dir = self.settings.data_dir / "vectorstore"
            embedder = SentenceTransformerEmbedder(self.settings.embedding_model)
            self._vectorstore = VectorStore(persist_dir, embedder)
        return self._vectorstore

    # 构建 rag_search 工具
    # 用于从用户私有知识库检索与问题最相关的内容片段
    # 包含上下文、来源等信息
    # 可选参数：查询字符串
    # 返回：包含上下文、来源等信息的字典
    def _build_rag_tool(self):
        @tool
        async def rag_search(query: str) -> dict:
            """从用户私有知识库检索与问题最相关的内容片段。"""
            store = self._ensure_vectorstore()
            # 嵌入模型加载与检索是重同步操作，放入线程执行，避免阻塞事件循环导致 SSE 停发
            hits = await asyncio.to_thread(store.search, query, 5)
            context = "\n\n".join(
                f"[{i + 1}] {h.excerpt}\n来源：{h.path}" for i, h in enumerate(hits)
            ) or "知识库中暂未找到相关内容。"
            return {"context": context, "sources": [asdict(h) for h in hits]}

        return rag_search

    # 执行一次 Agent 对话
    # 通过 emit 推送 SSE 事件；返回助手回答全文
    # 可选参数：对话ID、用户消息
    # 返回：助手回答全文
    # 异常：如果对话ID不存在则抛出异常
    async def stream(self, conversation_id: str | None, message: str, emit: Emit) -> str:
        """执行一次 Agent 对话，通过 emit 推送 SSE 事件；返回助手回答全文。"""
        settings = self.settings
        with timed_step(logger, "上下文构建: conversation=%s", conversation_id or "新会话"):
            convs = ConversationRepo(settings.db_path)
            mem_repo = MemoryRepo(settings.db_path)
            memory_text = summarize(mem_repo)

            conv_id = conversation_id
            if not conv_id or convs.get(conv_id) is None:
                conv_id = convs.create()
            await emit("session_start", {"conversation_id": conv_id})
            await emit("memory_loaded", {"summary": memory_text})
            convs.append_message(conv_id, "user", message)

            model = _create_chat_model(settings)
            history = convs.list_messages(conv_id)
            langchain_messages = [
                (
                    {"role": "human", "content": m["content"]}
                    if m["role"] == "user"
                    else {"role": "ai", "content": m["content"]}
                )
                for m in history
            ]
        with timed_step(logger, "Agent 构建: conversation=%s", conv_id):
            try:
                mcp_tools = await self._ensure_mcp_tools()
            except Exception:
                logger.warning("MCP 工具加载失败，重置缓存后重试: conversation=%s", conv_id, exc_info=True)
                self._reset_mcp_cache()
                try:
                    mcp_tools = await self._ensure_mcp_tools()
                except Exception:
                    logger.exception("MCP 工具加载仍失败: conversation=%s", conv_id)
                    await emit("error", {"message": "MCP 工具加载失败，请检查 mcp_config.json 或重启服务"})
                    return ""
            agent = create_agent(
                model,
                tools=[self._build_rag_tool(), *mcp_tools],
                system_prompt=_system_prompt(memory_text),
            )

        answer_parts: list[str] = []
        saved_files: list[str] = []
        stream_start = time.perf_counter()
        first_token_at: float | None = None
        retry_count = 0
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
                        if first_token_at is None:
                            first_token_at = time.perf_counter() - stream_start
                        answer_parts.append(payload["text"])
                    elif event_type == "tool_end":
                        saved = extract_saved_file(raw.get("data", {}).get("output"))
                        if saved:
                            saved_files.append(saved)
                        if payload.get("sources"):
                            await emit("sources", {"sources": payload["sources"]})
                break
            except Exception as exc:  # 重试一次；第二次失败则上报
                if attempt == 0:
                    retry_count = 1
                    logger.warning("模型调用失败，准备重试: conversation=%s error=%s", conv_id, exc)
                else:
                    logger.exception("模型调用重试仍失败: conversation=%s", conv_id)
                    await emit("error", {"message": f"模型调用失败: {exc}"})

        answer = "".join(answer_parts).strip()
        if not answer:
            answer = "（抱歉，这次没有生成有效回答）"
        convs.append_message(conv_id, "assistant", answer)
        logger.info(
            "对话完成: conversation=%s 回答长度=%d 总耗时=%.2fs 首token=%.2fs 重试=%d次",
            conv_id,
            len(answer),
            time.perf_counter() - stream_start,
            first_token_at if first_token_at is not None else -1.0,
            retry_count,
        )
        await emit("done", {})

        if settings.deepseek_api_key:
            extractor = MemoryExtractor(settings)
            asyncio.create_task(_extract_memory_logged(extractor, conv_id, message, answer))
        indexer = Indexer(settings)
        for path_text in set(saved_files):
            path = Path(path_text)
            if path.is_relative_to(settings.knowledge_dir):
                asyncio.create_task(_index_file_logged(indexer, path))
        return answer







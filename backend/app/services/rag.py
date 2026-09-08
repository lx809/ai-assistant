import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import chromadb
import docx
import httpx
from pypdf import PdfReader

from app.config import Settings
from app.models import DocumentRepo

logger = logging.getLogger(__name__)


# ---------- 文档解析 ----------

# 读取 UTF-8 文本文件，".md", ".markdown", ".txt" 格式
# 返回文件内容
def _read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

# 解析 PDF 文档
# 返回文档内容
def _parse_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)

# 解析 DOCX 文档
# 返回文档内容
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


# ---------- 切块 ----------

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


# ---------- 嵌入 ----------

class SentenceTransformerEmbedder:
    """本地 sentence-transformers 嵌入器；GPU 可用时优先，否则 CPU。"""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    # 确保模型已加载
    # 仅在需要时加载，避免重复加载
    def _ensure_model(self):
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from modelscope import snapshot_download
            from sentence_transformers import SentenceTransformer

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model_path = self.model_name
            if not Path(self.model_name).exists():
                model_path = snapshot_download(model_id="BAAI/bge-large-zh-v1.5")
            self._model = SentenceTransformer(str(model_path), device=device)

    # 对文档列表进行嵌入
    # 返回嵌入后的向量列表
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._ensure_model()
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]

    # 对查询进行嵌入
    # 返回嵌入后的向量
    def embed_query(self, text: str) -> list[float]:
        self._ensure_model()
        vector = self._model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
        return vector.tolist()


# ---------- 向量库 ----------

class SiliconFlowEmbedder:
    """硅基流动云端嵌入（OpenAI 兼容 /embeddings 接口），本地零模型零显存。"""

    def __init__(self, api_key: str, model: str, base_url: str, batch_size: int = 32):
        self.model = model
        self.batch_size = batch_size
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )

    # 单批次请求，429/5xx 指数退避重试
    def _request(self, texts: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._client.post("/embeddings", json={"model": self.model, "input": texts})
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                data = sorted(resp.json()["data"], key=lambda item: item["index"])
                return [item["embedding"] for item in data]
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2**attempt)
        raise RuntimeError(f"嵌入 API 调用失败: {last_error}")

    # 对文档列表进行嵌入（自动分批）
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        start = time.perf_counter()
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            vectors.extend(self._request(texts[i : i + self.batch_size]))
        logger.info("嵌入 API: 模型=%s 文本=%d 用时=%.2fs", self.model, len(texts), time.perf_counter() - start)
        return vectors

    # 对查询进行嵌入
    def embed_query(self, text: str) -> list[float]:
        return self._request([text])[0]


# 嵌入器协议，定义了嵌入文档和查询的方法
class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def build_embedder(settings: Settings) -> Embedder:
    """按配置选择嵌入器：配置了硅基流动密钥则用云端 API，否则回退本地模型。"""
    if settings.siliconflow_api_key:
        return SiliconFlowEmbedder(
            api_key=settings.siliconflow_api_key,
            model=settings.embedding_model,
            base_url=settings.embedding_api_base,
        )
    return SentenceTransformerEmbedder(settings.embedding_model)


# 文档来源，包含文档ID、标题、路径、摘要、分数
@dataclass
class Source:
    document_id: int
    title: str
    path: str
    excerpt: str
    score: float


# 向量存储，负责存储和检索文档向量
# 包括添加文档、删除文档、搜索文档等操作
class VectorStore:
    def __init__(self, persist_dir: Path, embedder: Embedder):
        persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.collection = self.client.get_or_create_collection(
            name="documents", metadata={"hnsw:space": "cosine"}
        )
        self.embedder = embedder

    # 替换文档向量
    # 删除旧向量，添加新向量
    # 返回新向量数量
    # 可选参数：文档ID、文档分块列表、文档路径
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

    # 删除文档向量
    # 删除指定文档的所有向量
    def delete_document(self, document_id: int) -> None:
        try:
            result = self.collection.get(where={"document_id": document_id})
        except Exception:
            return
        ids = result.get("ids") or []
        if ids:
            self.collection.delete(ids=ids)

    @staticmethod
    def delete_document_vectors(persist_dir: Path, document_id: int) -> None:
        """不加载嵌入模型，仅按文档 ID 清理向量（供删除文档使用）。"""
        client = chromadb.PersistentClient(path=str(persist_dir))
        try:
            collection = client.get_collection("documents")
        except Exception:
            return
        try:
            result = collection.get(where={"document_id": document_id})
        except Exception:
            return
        ids = result.get("ids") or []
        if ids:
            collection.delete(ids=ids)

    # 搜索文档向量
    # 返回与查询最相似的文档向量列表
    # 可选参数：查询文本、返回结果数量
    # 可选返回值：文档来源列表
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


# ---------- 索引 ----------

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf", ".docx"}

# 文档索引器，负责索引文档
# 包括解析文档、分块文档、嵌入文档、添加文档向量等操作
class Indexer:
    def __init__(self, settings: Settings, vectorstore: VectorStore | None = None):
        self.settings = settings
        self.repo = DocumentRepo(settings.db_path)
        self._vectorstore = vectorstore
        self._store: VectorStore | None = None

    # 确保向量存储存在
    # 如果不存在，创建一个新的向量存储
    # 返回向量存储实例
    def _ensure_store(self) -> VectorStore:
        if self._store is None:
            persist_dir = self.settings.data_dir / "vectorstore"
            self._store = self._vectorstore or VectorStore(persist_dir, build_embedder(self.settings))
        return self._store

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    # 索引文档路径
    # 解析文档、分块文档、嵌入文档、添加文档向量
    # 返回文档ID和状态
    # 可选参数：文档路径
    def index_path(self, path: Path) -> dict:
        path = Path(path).resolve()
        text = parse_document(path)
        chunks = split_text(text)
        digest = self._content_hash(text)
        existing = self.repo.get_by_path(str(path))
        if existing and existing["status"] == "completed" and existing["content_hash"] == digest:
            logger.debug("文件未变化，跳过索引: %s", path.name)
            return {"id": existing["id"], "status": existing["status"]}

        doc_id = existing["id"] if existing else self.repo.register(
            path.name, str(path), path.suffix.lstrip(".").lower(), digest
        )
        self.repo.set_status(doc_id, "indexing")
        try:
            chunk_count = self._ensure_store().replace_document(doc_id, chunks, str(path))
            self.repo.set_status(doc_id, "completed", chunk_count=chunk_count)
            logger.info("文档索引完成: %s chunks=%d", path.name, chunk_count)
        except Exception as exc:  # 单文档失败不影响其他任务
            self.repo.set_status(doc_id, "failed", error=str(exc))
            logger.exception("文档索引失败: %s", path.name)
            raise
        return {"id": doc_id, "status": "completed", "chunk_count": chunk_count}

    # 删除文档
    # 删除指定文档条目
    # 可选参数：文档ID
    def delete_document(self, doc_id: int) -> None:
        persist_dir = self.settings.data_dir / "vectorstore"
        try:
            VectorStore.delete_document_vectors(persist_dir, doc_id)
        except Exception:
            pass
        self.repo.delete(doc_id)









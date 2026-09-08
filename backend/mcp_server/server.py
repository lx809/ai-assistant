import argparse
import logging
import re
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastmcp import FastMCP

KNOWLEDGE_DIR = Path(".")

# MCP 子进程通过 stdio 通信，日志只能写文件，绝不能进 stdout/stderr 协议通道
# server.py 位于 backend/mcp_server/ 下，三级 parent 即项目根目录
_log_dir = Path(__file__).resolve().parent.parent.parent / "data" / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("mcp_server")
logger.setLevel(logging.INFO)
_file_handler = RotatingFileHandler(
    _log_dir / "mcp_server.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
logger.addHandler(_file_handler)
logger.propagate = False

_SAFE_NAME = re.compile(r"[\\/:*?\"<>|]+")


# 安全标题处理函数，移除特殊字符并确保标题不为空
def _safe_title(title: str) -> str:
    cleaned = _SAFE_NAME.sub("_", title.strip()).strip(" .")
    return cleaned or "untitled"


# 写入 Markdown 文件函数，将标题和内容写入指定子目录的文件中
# 文件名格式为 YYYYMMDDHHMMSS-标题.md
def _write_markdown(subdir: str, title: str, body: str) -> dict:
    now = datetime.now()
    folder = KNOWLEDGE_DIR / subdir / now.strftime("%Y/%m")
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{now.strftime('%Y%m%d%H%M%S')}-{_safe_title(title)}.md"
    path = folder / filename
    path.write_text(f"# {title}\n\n{body.strip()}\n", encoding="utf-8")
    logger.info("文件已写入: %s", path)
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
            logger.warning("web_save 失败: 非HTML页面 url=%s", url)
            return {"status": "failed", "error": "目标不是 HTML 页面"}
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        title_tag = soup.find("title")
        page_title = (title_tag.get_text(strip=True) if title_tag else "") or urlparse(url).hostname or "网页"
        final_title = title or page_title
        article = soup.find("article") or soup.body or soup
        blocks = []
        for node in article.find_all(["h1", "h2", "h3", "p", "li", "blockquote"]):
            text = node.get_text(" ", strip=True)
            if text and len(text) > 1:
                if node.name.startswith("h"):
                    blocks.append(f"**{text}**\n\n")
                elif node.name == "blockquote":
                    blocks.append(f"> {text}")
                else:
                    blocks.append(text)
        if not blocks:
            text = article.get_text("\n", strip=True)
            if text:
                blocks = [text]
        body = f"原文：{url}\n\n" + "\n\n".join(blocks)
        return _write_markdown("web", final_title, body)
    except httpx.HTTPError as exc:
        logger.warning("web_save 抓取失败: url=%s error=%s", url, exc)
        return {"status": "failed", "error": f"抓取失败: {exc}"}
    finally:
        if close_client:
            client.close()


def _web_save_mcp(url: str, title: str | None = None) -> dict:
    """抓取网页正文并保存（MCP 对外签名，不含测试注入参数）。"""
    return _web_save(url, title=title)


# 创建 FastMCP 应用实例
# 包含 notes_create 和 web_save 工具
mcp = FastMCP("assistant-tools")
mcp.tool(name="notes_create")(_notes_create)
mcp.tool(name="web_save")(_web_save_mcp)

# 主函数，解析命令行参数并启动 FastMCP 应用
# 接收知识库目录路径作为参数
# 初始化知识库目录并启动 FastMCP 应用
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-dir", required=True, type=Path)
    args = parser.parse_args()
    global KNOWLEDGE_DIR
    KNOWLEDGE_DIR = args.knowledge_dir.expanduser().resolve()
    logger.info("MCP server 启动: knowledge_dir=%s", KNOWLEDGE_DIR)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()


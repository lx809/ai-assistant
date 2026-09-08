from pathlib import Path

import httpx

import mcp_server.server as server


def test_notes_create_writes_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "KNOWLEDGE_DIR", tmp_path)
    result = server._notes_create("测试笔记", "这是正文", tags=["demo"])
    saved = result["saved_file"]
    saved_path = Path(saved)
    assert tmp_path in saved_path.parents
    assert saved_path.suffix == ".md"
    content = saved_path.read_text(encoding="utf-8")
    assert "# 测试笔记" in content
    assert "这是正文" in content


def test_web_save_extracts_article(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "KNOWLEDGE_DIR", tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>示例</title></head><body><article>"
                 "<h1>标题</h1><p>第一段内容</p><p>第二段内容</p></article></body></html>",
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = server._web_save("https://example.com/a", title="自定义标题", client=client)
    saved = result["saved_file"]
    saved_path = Path(saved)
    assert saved_path.suffix == ".md"
    text = saved_path.read_text(encoding="utf-8")
    assert "自定义标题" in text
    assert "第一段内容" in text
    assert "第二段内容" in text


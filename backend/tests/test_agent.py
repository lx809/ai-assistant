import asyncio
from pathlib import Path

from app.services.agent import AgentService, extract_saved_file, extract_sources, normalize_event
from app.services.agent import load_mcp_config
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

    class FakeChunk:
        content = "你好"

    stream = {"event": "on_chat_model_stream", "data": {"chunk": FakeChunk()}}
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
    saved = extract_saved_file(output)
    assert saved is not None
    saved_path = Path(saved)
    assert str(tmp_path) in saved
    assert saved_path.exists()





def test_create_chat_model_enables_streaming(monkeypatch):
    from app.services.agent import _create_chat_model
    from app.config import get_settings

    # 不依赖宿主机环境变量中配置的真实密钥
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    get_settings.cache_clear()
    model = _create_chat_model(get_settings())
    assert getattr(model, "streaming", False) is True
    get_settings.cache_clear()

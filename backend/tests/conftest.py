import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """每个测试使用独立的数据目录，避免污染真实数据。"""
    monkeypatch.setenv("KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "test.db"))
    monkeypatch.setenv("MCP_CONFIG_PATH", str(tmp_path / "mcp_config.json"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "data" / "logs"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()



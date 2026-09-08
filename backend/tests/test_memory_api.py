from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import init_db
from app.main import app
from app.services.memory import _extract_json_array, MemoryExtractor
from app.models import MemoryRepo


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



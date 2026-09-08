from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import init_db
from app.main import app
from app.controllers import get_agent_service


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



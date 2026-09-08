from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import init_db
from app.main import app
from app.models import ConversationRepo


def test_conversation_list_and_detail():
    settings = get_settings()
    init_db(settings.db_path)
    repo = ConversationRepo(settings.db_path)
    conv_id = repo.create()
    repo.append_message(conv_id, "user", "记录一下：明天开会")
    repo.append_message(conv_id, "assistant", "已记录。")

    with TestClient(app) as client:
        listed = client.get("/api/conversations").json()
        assert listed[0]["id"] == conv_id

        detail = client.get(f"/api/conversations/{conv_id}").json()
        assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]

        missing = client.get("/api/conversations/nope")
        assert missing.status_code == 404




def test_delete_conversation_api():
    settings = get_settings()
    init_db(settings.db_path)
    repo = ConversationRepo(settings.db_path)
    conv_id = repo.create()
    repo.append_message(conv_id, "user", "要被删除的消息")

    with TestClient(app) as client:
        resp = client.delete(f"/api/conversations/{conv_id}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert client.get("/api/conversations").json() == []

        missing = client.delete("/api/conversations/not-exist")
        assert missing.status_code == 404

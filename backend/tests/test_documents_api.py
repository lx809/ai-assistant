import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import init_db
from app.main import app
from app.models import DocumentRepo


def _fake_index(self, path: Path) -> dict:
    settings = get_settings()
    init_db(settings.db_path)
    docs = DocumentRepo(settings.db_path)
    content = path.read_text(encoding="utf-8", errors="replace")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    existing = docs.get_by_path(str(path))
    doc_id = existing["id"] if existing else docs.register(path.name, str(path), path.suffix.lstrip("."), digest)
    docs.set_status(doc_id, "completed", chunk_count=1)
    return {"id": doc_id, "status": "completed"}


def test_upload_list_and_delete(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.rag.Indexer.index_path", _fake_index)
    settings = get_settings()
    init_db(settings.db_path)

    with TestClient(app) as client:
        upload = client.post(
            "/api/documents/upload",
            files={"file": ("hello.md", "# 你好".encode("utf-8"), "text/markdown")},
        )
        assert upload.status_code == 200
        body = upload.json()
        assert body["status"] == "queued"

        listed = client.get("/api/documents").json()
        assert len(listed) == 1
        doc_id = listed[0]["id"]
        assert listed[0]["status"] == "completed"

        deleted = client.delete(f"/api/documents/{doc_id}")
        assert deleted.status_code == 200
        assert client.get("/api/documents").json() == []


def test_scan_ignores_unsupported_and_tracks_new_files(monkeypatch, tmp_path):
    settings = get_settings()
    init_db(settings.db_path)
    settings.knowledge_dir.mkdir(parents=True, exist_ok=True)
    (settings.knowledge_dir / "a.md").write_text("内容", encoding="utf-8")
    (settings.knowledge_dir / "b.exe").write_bytes(b"xx")
    calls = []

    def tracking_index(self, path):
        calls.append(Path(path).name)
        return {"status": "completed"}

    monkeypatch.setattr("app.services.rag.Indexer.index_path", tracking_index)
    with TestClient(app) as client:
        resp = client.post("/api/documents/scan")
    assert resp.status_code == 200
    assert "a.md" in [Path(p).name for p in resp.json()["scanned"]]
    assert not any(Path(p).suffix == ".exe" for p in resp.json()["scanned"])



from pathlib import Path

import pytest
from fastapi.testclient import TestClient

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

pytestmark = pytest.mark.skipif(not (DIST / "index.html").exists(), reason="前端未构建")


def test_spa_served_when_dist_exists():
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]

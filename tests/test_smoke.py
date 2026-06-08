from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app, backplane


def test_healthz():
    with patch.object(backplane, "ping", AsyncMock(return_value=None)):
        with TestClient(app) as client:
            res = client.get("/healthz")
            assert res.status_code == 200
            assert res.json()["ok"] is True
            assert res.json()["redis"] == "up"

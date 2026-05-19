"""서버 startup 중 DB 초기화 실패 방어 테스트."""

from fastapi.testclient import TestClient

from stocks.server import app as app_module


def test_mockstocks_starts_without_db(monkeypatch):
    """DB 초기화가 실패해도 Cloud Run startup probe 대상인 앱 기동은 성공해야 한다."""

    def broken_init_db():
        raise TimeoutError("db startup timeout")

    monkeypatch.setattr(app_module, "init_db", broken_init_db)

    app = app_module.create_app()
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

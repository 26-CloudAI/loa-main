"""서버 startup 중 DB 초기화 실패 방어 테스트."""

import sys
from pathlib import Path

import firebase_admin
from firebase_admin import credentials
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


def _import_app(monkeypatch):
    """Firebase credentials 파일이 없는 로컬 테스트 환경에서도 app 모듈을 import한다."""

    monkeypatch.setattr(credentials, "Certificate", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(firebase_admin, "initialize_app", lambda *_args, **_kwargs: None)

    from src.arena.server import app as app_module

    return app_module


def test_battleroyale_starts_without_db(monkeypatch):
    """DB 초기화가 실패해도 Cloud Run startup probe 대상인 앱 기동은 성공해야 한다."""

    def broken_init_db():
        raise TimeoutError("db startup timeout")

    app_module = _import_app(monkeypatch)
    monkeypatch.setattr(app_module, "init_db", broken_init_db)

    app = app_module.create_app()
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_battleroyale_db_api_returns_503_when_db_unavailable(monkeypatch):
    """DB 없이 기동한 상태에서 DB 의존 API는 KeyError 대신 명확한 503을 반환한다."""

    def broken_init_db():
        raise TimeoutError("db startup timeout")

    app_module = _import_app(monkeypatch)
    monkeypatch.setattr(app_module, "init_db", broken_init_db)

    app = app_module.create_app()
    with TestClient(app) as client:
        response = client.get("/api/rankings")

    assert response.status_code == 503
    assert response.json()["detail"] == "DB를 사용할 수 없습니다."

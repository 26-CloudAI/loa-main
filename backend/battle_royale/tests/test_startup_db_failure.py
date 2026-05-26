"""서버 startup 중 DB 초기화 실패 방어 테스트."""

import sys
import threading
import time
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


def test_battleroyale_readiness_recovers_after_db_recovery(monkeypatch, tmp_path):
    """startup DB init이 실패해도, 이후 DB가 살아나면 백그라운드 재시도로
    readiness(db_ok)가 자동 복구되어야 한다 (영구 503 latch 방지)."""

    app_module = _import_app(monkeypatch)

    from src.arena.server import settings as settings_module
    monkeypatch.setattr(settings_module, "DB_RETRY_INTERVAL_SEC", 0.05)

    real_init_db = app_module.init_db
    calls = {"n": 0}

    def flaky_init_db(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("db startup timeout")
        # 시도마다 별도 파일을 써서 동시 재시도 간 sqlite 잠금 경합을 피한다
        return real_init_db(str(tmp_path / f"recover_{calls['n']}.db"))

    monkeypatch.setattr(app_module, "init_db", flaky_init_db)

    app = app_module.create_app()
    with TestClient(app) as client:
        # 첫 init은 실패 → readiness falsy
        assert app.state.db_ok() is False

        # 백그라운드 재시도가 성공할 때까지 대기
        deadline = time.time() + 5.0
        while time.time() < deadline and not app.state.db_ok():
            time.sleep(0.05)

        assert app.state.db_ok() is True
        # DB 의존 API도 503 → 200 으로 회복
        assert client.get("/api/rankings").status_code == 200


def test_battleroyale_late_init_does_not_rerun_cleanup(monkeypatch, tmp_path):
    """첫 init 시도가 멈춰 있는 동안 재시도가 승자가 되고(미완료 게임 정리 1회), 멈춘
    첫 시도가 뒤늦게 끝나도 정리를 재실행하지 않아야 한다 — destructive 정리가 라이브
    게임을 server_restart로 망가뜨리는 것 방지. (정리는 승자 연결로 단 1회)"""

    app_module = _import_app(monkeypatch)

    from src.arena.server import settings as settings_module
    monkeypatch.setattr(settings_module, "DB_INIT_TIMEOUT_SEC", 0.2)
    monkeypatch.setattr(settings_module, "DB_RETRY_INTERVAL_SEC", 0.05)

    cleanup_calls = {"n": 0}

    def counting_cleanup(self):
        cleanup_calls["n"] += 1
        return 0

    monkeypatch.setattr(app_module.GameRepository, "cleanup_stale_games", counting_cleanup)

    real_init_db = app_module.init_db
    gate = threading.Event()
    lock = threading.Lock()
    calls = {"n": 0}

    def slow_init_db(*_args, **_kwargs):
        with lock:
            calls["n"] += 1
            n = calls["n"]
        if n == 1:
            gate.wait(timeout=10)  # 첫 시도는 늦게 끝남 (패자)
        return real_init_db(str(tmp_path / f"db_{n}.db"))

    monkeypatch.setattr(app_module, "init_db", slow_init_db)

    app = app_module.create_app()
    with TestClient(app) as client:
        # 첫 시도가 멈춰 있어도(gate 미해제) 재시도로 복구
        deadline = time.time() + 5.0
        while time.time() < deadline and not app.state.db_ok():
            time.sleep(0.05)
        assert app.state.db_ok() is True
        assert cleanup_calls["n"] == 1  # 승자 1회만

        # 멈춘 첫 시도 해제 → 늦게 끝나도(패자) cleanup 재실행 안 함
        gate.set()
        time.sleep(0.3)
        assert cleanup_calls["n"] == 1
        assert app.state.db_ok() is True

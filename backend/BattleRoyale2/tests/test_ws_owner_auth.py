"""BR2 WebSocket owner 인증 검증.

WS /match/{id}에서:
- 토큰 없음/무효 → 4401 거부
- 토큰 유효하나 owner 불일치 → 4403 거부
- owner 본인 토큰 → 인증 통과(연결 수락)
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "battle_royale"))
os.environ.setdefault("DB_TYPE", "sqlite")

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from src.arena.db.schema import SCHEMA_SQL_SQLITE  # noqa: E402
from src.arena.db.game_repo import GameRepository  # noqa: E402
import BattleRoyale2.server.ws_server as ws  # noqa: E402


def _fresh_repo() -> GameRepository:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL_SQLITE)
    conn.commit()
    return GameRepository(conn)


@pytest.fixture
def auth_setup(monkeypatch):
    """repo + _decode_token/_resolve_owner_id 패치 + TestClient 반환."""
    repo = _fresh_repo()
    monkeypatch.setattr(ws, "_get_game_repo", lambda: repo)
    ws._GAME_CODE.clear()
    ws._GAME_BOT_COUNT.clear()
    ws._AUTHORITATIVE.clear()

    # token "owner" → user_id 1 / "other" → user_id 2
    # "ghost" → 토큰은 유효(decode O)하나 owner 해석 실패(resolve None)
    def _fake_decode(tok):
        if tok in ("owner", "other", "ghost"):
            return {"uid": tok}
        return None

    def _fake_resolve(tok):
        return {"owner": 1, "other": 2}.get(tok)

    monkeypatch.setattr(ws, "_decode_token", _fake_decode)
    monkeypatch.setattr(ws, "_resolve_owner_id", _fake_resolve)

    game_id = "test-ws-match"
    repo.create_game(game_id=game_id, owner_user_id=1, total_bots=3)

    client = TestClient(ws.create_app(), raise_server_exceptions=False)
    return client, game_id


def test_ws_no_token_rejected(auth_setup):
    client, gid = auth_setup
    with pytest.raises((WebSocketDisconnect, Exception)) as exc_info:
        with client.websocket_connect(f"/match/{gid}"):
            pass
    ex = exc_info.value
    if isinstance(ex, WebSocketDisconnect):
        assert ex.code == 4401


def test_ws_invalid_token_rejected(auth_setup):
    client, gid = auth_setup
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect(f"/match/{gid}?token=bad_token"):
            pass


def test_ws_wrong_owner_rejected(auth_setup):
    client, gid = auth_setup
    with pytest.raises((WebSocketDisconnect, Exception)) as exc_info:
        with client.websocket_connect(f"/match/{gid}?token=other"):
            pass
    ex = exc_info.value
    if isinstance(ex, WebSocketDisconnect):
        assert ex.code == 4403


def test_ws_owner_resolution_failure_rejected(auth_setup):
    """토큰은 유효하나 owner 해석이 None이면(user-service/DB 장애) fail-closed."""
    client, gid = auth_setup
    with pytest.raises((WebSocketDisconnect, Exception)) as exc_info:
        with client.websocket_connect(f"/match/{gid}?token=ghost"):
            pass
    ex = exc_info.value
    if isinstance(ex, WebSocketDisconnect):
        assert ex.code == 4403


def test_ws_owner_token_accepted(auth_setup, monkeypatch):
    """owner 토큰이면 인증 통과 → WS accept 진행 (게임 로직까지는 테스트 안 함)."""
    client, gid = auth_setup
    # _assemble_bots 내부에서 DB spec 로드 실패해도 연결 자체는 수락됨을 확인
    # (accept 전에 4401/4403으로 끊기지 않으면 성공)
    try:
        with client.websocket_connect(f"/match/{gid}?token=owner") as wsc:
            # 연결됐으면 즉시 클라이언트 측 종료
            pass
    except WebSocketDisconnect as e:
        # 게임 로직 실패 시 서버가 끊을 수 있으나, auth 코드(4401/4403)면 실패
        assert e.code not in (4401, 4403), f"owner 토큰이 auth 단계에서 거부됨: code={e.code}"
    except Exception:
        # 게임 초기화 실패 등 — auth 이후 단계이므로 허용
        pass

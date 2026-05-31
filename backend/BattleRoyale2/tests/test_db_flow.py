"""BattleRoyale2 DB 플로우 테스트 (SQLite).

검증:
- POST /api/games 인증 없으면 401
- DB 불가 시 503 (fail-open 안 함)
- owner 는 토큰으로 결정, body.owner_user_id 무시
- config_json 영속 + _load_game_spec 복원
- _db_on_start: user bot is_ai_filler=False / AI True
- _db_on_end: finished 저장 + 중복 MATCH_END 무시

실행: cd backend && python -m pytest BattleRoyale2/tests/test_db_flow.py -q
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]          # .../backend
sys.path.insert(0, str(_BACKEND))                       # BattleRoyale2.*
sys.path.insert(0, str(_BACKEND / "battle_royale"))     # src.arena.*
os.environ.setdefault("DB_TYPE", "sqlite")

from fastapi.testclient import TestClient  # noqa: E402

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
def repo(monkeypatch):
    r = _fresh_repo()
    monkeypatch.setattr(ws, "_get_game_repo", lambda: r)
    # 로컬 테스트는 dev 컨텍스트 — _make_user_bot이 InProcessBot2를 쓰도록
    # (secure-by-default fail-closed는 ENV=production에서만 적용).
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("BOT_RUNNER_URL", raising=False)
    # 인메모리 스펙 캐시 초기화 (테스트 격리)
    ws._GAME_CODE.clear()
    ws._GAME_BOT_COUNT.clear()
    ws._AUTHORITATIVE.clear()
    return r


@pytest.fixture
def client(repo, monkeypatch):
    # 토큰 "valid" → owner_id 1, 그 외 None (firebase 우회)
    monkeypatch.setattr(ws, "_resolve_owner_id", lambda tok: 1 if tok == "valid" else None)
    return TestClient(ws.create_app())


def _auth(tok="valid"):
    return {"Authorization": f"Bearer {tok}"}


def test_create_requires_auth(client):
    res = client.post("/api/games", json={"bots": []})
    assert res.status_code == 401


def test_create_503_when_db_unavailable(repo, monkeypatch):
    monkeypatch.setattr(ws, "_resolve_owner_id", lambda tok: 1 if tok == "valid" else None)
    monkeypatch.setattr(ws, "_get_game_repo", lambda: None)
    c = TestClient(ws.create_app())
    res = c.post("/api/games", json={"bots": []}, headers=_auth())
    assert res.status_code == 503


def test_create_owner_from_token_ignores_body(client, repo):
    body = {
        "owner_user_id": 9999,  # 조작 시도 — 무시돼야 함
        "bots": [{"bot_id": "my_bot", "name": "내봇", "code": "class Bot(BattleRoyale2DBot):\n def get_action(self,s): return {}"}],
        "bot_count": 5,
    }
    res = client.post("/api/games", json=body, headers=_auth())
    assert res.status_code == 201
    gid = res.json()["game_id"]
    game = repo.get_game(gid)
    assert game is not None
    assert game.owner_user_id == 1          # 토큰 사용자
    assert game.owner_user_id != 9999       # body 무시


def test_config_json_persist_and_load(client, repo):
    body = {
        "bots": [{"bot_id": "my_bot", "name": "내봇", "code": "class Bot(BattleRoyale2DBot):\n def get_action(self,s): return {}"}],
        "bot_count": 6,
    }
    gid = client.post("/api/games", json=body, headers=_auth()).json()["game_id"]
    # 인메모리 캐시 비우고 DB(config_json) 에서 복원되는지
    ws._GAME_CODE.clear()
    ws._GAME_BOT_COUNT.clear()
    user_bots, bot_count = ws._load_game_spec(gid)
    assert bot_count == 6
    assert [b["bot_id"] for b in user_bots] == ["my_bot"]


def test_db_on_start_participant_flags(client, repo):
    body = {
        "bots": [{"bot_id": "my_bot", "name": "내봇", "code": "class Bot(BattleRoyale2DBot):\n def get_action(self,s): return {}"}],
        "bot_count": 3,
    }
    gid = client.post("/api/games", json=body, headers=_auth()).json()["game_id"]
    sess = ws.MatchSession(ws=None, match_id=gid)
    sess.bots, sess.bot_spec = sess._assemble_bots(seed=42)
    sess._db_on_start()
    parts = {p.bot_name: p.is_ai_filler for p in repo.get_participants(gid)}
    assert parts.get("내봇") is False          # 유저 봇
    ai_flags = [v for k, v in parts.items() if k != "내봇"]
    assert len(ai_flags) == 2 and all(ai_flags)  # AI 채움 2마리 모두 filler


def test_load_game_spec_jsonb_dict(repo, monkeypatch):
    """PostgreSQL(JSONB)에서 psycopg2 가 config_json 을 dict 로 디코드해 돌려주는 경우,
    _load_game_spec 가 json.loads 대신 dict 를 그대로 사용해야 한다 (회귀: 유저봇 유실 버그)."""
    monkeypatch.setattr(ws, "_get_game_repo", lambda: repo)
    ws._GAME_CODE.clear()
    ws._GAME_BOT_COUNT.clear()

    class _Cur:
        def fetchone(self):
            # JSONB → 이미 파싱된 dict (str 아님)
            return {"config_json": {"user_bots": [{"bot_id": "pg_bot", "name": "PG봇"}], "bot_count": 7}}

    monkeypatch.setattr(repo, "_execute", lambda *a, **k: _Cur())
    user_bots, bot_count = ws._load_game_spec("any-gid")
    assert bot_count == 7
    assert [b["bot_id"] for b in user_bots] == ["pg_bot"]


def test_db_on_end_finished_guard(client, repo):
    body = {"bots": [{"bot_id": "my_bot", "name": "내봇", "code": "class Bot(BattleRoyale2DBot):\n def get_action(self,s): return {}"}], "bot_count": 2}
    gid = client.post("/api/games", json=body, headers=_auth()).json()["game_id"]
    sess = ws.MatchSession(ws=None, match_id=gid)
    sess.bots, sess.bot_spec = sess._assemble_bots(seed=1)
    sess._db_on_start()
    end_payload = {"duration": 180.0, "reason": "last_standing", "rankings": [
        {"bot_name": "내봇", "rank": 1, "score": 100.0, "kills": 2, "minerals_mined": 3, "survival_ticks": 1800},
    ]}
    sess._db_on_end(end_payload)
    g = repo.get_game(gid)
    assert g.status == "finished"
    assert g.end_reason == "last_standing"
    assert g.final_tick == 180   # duration(180초) 그대로 저장 — ×10 제거 회귀 가드 (≤200)
    # 중복 MATCH_END — finished 가드로 reason 안 바뀜
    sess._db_on_end({"duration": 99.0, "reason": "max_ticks", "rankings": []})
    g2 = repo.get_game(gid)
    assert g2.end_reason == "last_standing"


def test_db_on_abandon_finalizes_running_game(client, repo):
    """권위 WS가 MATCH_END 없이 끊기면(_db_on_abandon) running 게임을 종료 확정해
    목록에 '진행 중'으로 영구 잔존하지 않게 한다."""
    body = {"bots": [{"bot_id": "my_bot", "name": "내봇", "code": "class Bot(BattleRoyale2DBot):\n def get_action(self,s): return {}"}], "bot_count": 2}
    gid = client.post("/api/games", json=body, headers=_auth()).json()["game_id"]
    sess = ws.MatchSession(ws=None, match_id=gid)
    sess.bots, sess.bot_spec = sess._assemble_bots(seed=1)
    sess._db_on_start()
    assert repo.get_game(gid).status == "running"
    sess.last_tick = 1700                # 클라 프레임 틱(~10/초)
    sess._db_on_abandon()
    g = repo.get_game(gid)
    assert g.status == "finished"        # 더 이상 진행 중 아님
    assert g.end_reason == "abandoned"
    assert g.final_tick == 170           # 초로 환산(÷10) → ~200 스케일 (≤200)


def test_db_on_abandon_does_not_overwrite_finished(client, repo):
    """MATCH_END로 정상 종료된 게임은 이후 disconnect의 _db_on_abandon이 덮어쓰지 않는다."""
    body = {"bots": [{"bot_id": "my_bot", "name": "내봇", "code": "class Bot(BattleRoyale2DBot):\n def get_action(self,s): return {}"}], "bot_count": 2}
    gid = client.post("/api/games", json=body, headers=_auth()).json()["game_id"]
    sess = ws.MatchSession(ws=None, match_id=gid)
    sess.bots, sess.bot_spec = sess._assemble_bots(seed=1)
    sess._db_on_start()
    sess._db_on_end({"duration": 180.0, "reason": "last_standing", "rankings": []})
    assert repo.get_game(gid).status == "finished"
    sess.last_tick = 5
    sess._db_on_abandon()                # 이미 finished → no-op
    g = repo.get_game(gid)
    assert g.status == "finished"
    assert g.end_reason == "last_standing"   # abandoned 로 안 바뀜

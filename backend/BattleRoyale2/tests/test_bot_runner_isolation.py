"""BR2 유저 봇이 bot-runner 격리로 라우팅되는지 검증.

핵심: 프로덕션에서 유저 코드를 game-server Pod에서 직접 exec(InProcessBot2)하지 않고
bot-runner(RemoteBattleRoyale2BotAdapter)로 보내야 한다 (critical RCE 차단).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]          # .../backend
sys.path.insert(0, str(_BACKEND))                       # BattleRoyale2.*
sys.path.insert(0, str(_BACKEND / "battle_royale"))     # src.arena.*
os.environ.setdefault("DB_TYPE", "sqlite")

import BattleRoyale2.server.ws_server as ws  # noqa: E402
from BattleRoyale2.server.remote_bot import RemoteBattleRoyale2BotAdapter  # noqa: E402
from BattleRoyale2.server.inprocess_bot import InProcessBot2  # noqa: E402

_CODE = "class Bot(BattleRoyale2DBot):\n def get_action(self, s): return {}"


def test_make_user_bot_uses_remote_when_runner_url(monkeypatch):
    monkeypatch.setenv("BOT_RUNNER_URL", "http://bot-runner:8001")
    bot = ws._make_user_bot("b", _CODE)
    assert isinstance(bot, RemoteBattleRoyale2BotAdapter)


def test_make_user_bot_refuses_inprocess_in_production(monkeypatch):
    monkeypatch.delenv("BOT_RUNNER_URL", raising=False)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("BOT_RUNNER_REQUIRED", "true")
    with pytest.raises(RuntimeError):
        ws._make_user_bot("b", _CODE)


def test_make_user_bot_inprocess_allowed_in_dev(monkeypatch):
    monkeypatch.delenv("BOT_RUNNER_URL", raising=False)
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("BOT_RUNNER_REQUIRED", "false")
    bot = ws._make_user_bot("b", _CODE)
    assert isinstance(bot, InProcessBot2)


def test_assemble_bots_routes_user_bot_to_remote(monkeypatch):
    monkeypatch.setenv("BOT_RUNNER_URL", "http://bot-runner:8001")
    monkeypatch.setattr(
        ws, "_load_game_spec",
        lambda mid: ([{"bot_id": "u1", "name": "내봇", "code": _CODE}], 3),
    )
    sess = ws.MatchSession(ws=None, match_id="m1")
    bots, spec = sess._assemble_bots(seed=1)
    assert isinstance(bots["u1"], RemoteBattleRoyale2BotAdapter)   # 유저 봇 = 격리
    ai_ids = [b for b in bots if b != "u1"]
    assert len(ai_ids) == 2                                        # AI 채움 2마리

"""보스전(#4) 백엔드 토대 테스트 — 보스 로스터 조립 + boss_rules + 무회귀.

검증:
- 보스 게임 _assemble_bots: 보스(1) + 유저 challenger + AI 채움 = 다대일 균형(BOSS_MODE_DEFAULT_BOT_COUNT).
- send_match_config 가 MATCH_CONFIG.boss_rules 동봉 (보스 stat 강화 + 매치 길이 + 슬롯 정책).
- 일반(battleroyale2) 매치는 보스 미포함 — 회귀 방지.
- 난이도 키는 한국어 "하/중/상", stat 배수는 상 > 중 > 하.
"""
from __future__ import annotations

import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_BACKEND, "battle_royale"))

import BattleRoyale2.server.ws_server as ws  # noqa: E402
from BattleRoyale2.rules import boss_mode as boss_rules_mod  # noqa: E402
from BattleRoyale2.server.ws_server import MatchSession  # noqa: E402


class _FakeWS:
    async def send_text(self, *_a, **_k):
        pass


def _session(mid: str) -> MatchSession:
    return MatchSession(_FakeWS(), mid)


def test_boss_roster_includes_boss_user_bots_and_ai_fillers():
    """다대일 균형: 보스 1 + 유저봇 + AI 채움 = BOSS_MODE_DEFAULT_BOT_COUNT."""
    mid = "bosstest_roster"
    ws._GAME_CODE[mid] = [{
        "bot_id": "challenger", "name": "도전자",
        "code": "class Bot:\n    def get_action(self, s):\n        return {}\n",
    }]
    ws._GAME_BOT_COUNT[mid] = boss_rules_mod.BOSS_MODE_DEFAULT_BOT_COUNT
    ws._GAME_BOSS[mid] = {"difficulty": "중"}
    try:
        bots, spec = _session(mid)._assemble_bots(seed=1)
        ids = [bid for bid, _ in spec]

        # 보스 + 유저 봇 포함
        assert "boss" in bots and "boss" in ids
        assert "challenger" in bots

        # 보스 + 유저 + AI 채움 = target_bot_count 보장
        assert len(spec) == boss_rules_mod.BOSS_MODE_DEFAULT_BOT_COUNT

        # AI 채움 슬롯 활성 (보스 + 유저 1마리만 있을 때 채움 = target - 2)
        ai_ids = [bid for bid in ids if bid.startswith("ai_")]
        expected_fill = boss_rules_mod.BOSS_MODE_DEFAULT_BOT_COUNT - 2
        assert len(ai_ids) == expected_fill

        # 보스 display name 은 클래스 DISPLAY_NAME (예: "보스(중)")
        boss_label = dict(spec)["boss"]
        assert boss_label.startswith("보스")
    finally:
        ws._GAME_CODE.pop(mid, None)
        ws._GAME_BOT_COUNT.pop(mid, None)
        ws._GAME_BOSS.pop(mid, None)


def test_boss_rules_payload_structure_by_difficulty():
    """boss_mode_rules 페이로드 — 한국어 키, 다대일 슬롯 정책, stat 강화 일관성."""
    for diff in ("하", "중", "상"):
        r = boss_rules_mod.boss_mode_rules(diff)
        assert r["version"] == 2
        assert r["difficulty"] == diff
        assert r["duration_sec"] == boss_rules_mod.BOSS_MODE_DURATION_SEC

        slots = r["slots"]
        assert slots["boss_count"] == 1
        assert slots["user_max"] == boss_rules_mod.BOSS_MAX_USER_BOTS
        assert slots["ai_fillers_enabled"] is True
        assert slots["target_bot_count"] == boss_rules_mod.BOSS_MODE_DEFAULT_BOT_COUNT

        assert r["boss_stat_overrides"] == boss_rules_mod.BOSS_STAT_MULTIPLIERS[diff]


def test_boss_stat_difficulty_ordering():
    """난이도별 stat 강화 배수: 상 > 중 > 하 (다대일 균형 보존)."""
    hp = {d: boss_rules_mod.BOSS_STAT_MULTIPLIERS[d]["max_hp_mult"] for d in ("하", "중", "상")}
    assert hp["상"] > hp["중"] > hp["하"]

    atk = {d: boss_rules_mod.BOSS_STAT_MULTIPLIERS[d]["atk_mult"] for d in ("하", "중", "상")}
    assert atk["상"] > atk["중"] > atk["하"]


def test_normal_match_has_no_boss():
    """일반(battleroyale2) 매치 무회귀 — 보스 봇/룰 미포함."""
    mid = "normaltest_noboss"
    ws._GAME_CODE[mid] = [{
        "bot_id": "u1", "name": "u1",
        "code": "class Bot:\n    def get_action(self, s):\n        return {}\n",
    }]
    ws._GAME_BOT_COUNT[mid] = 4
    try:
        bots, spec = _session(mid)._assemble_bots(seed=1)
        assert "boss" not in bots and "boss" not in [b for b, _ in spec]
    finally:
        ws._GAME_CODE.pop(mid, None)
        ws._GAME_BOT_COUNT.pop(mid, None)
        ws._GAME_BOSS.pop(mid, None)


def test_boss_user_bot_limit_constant():
    """보스전 유저봇 상한 — 한국어 키 / 다대일 균형 디자인."""
    assert boss_rules_mod.BOSS_MAX_USER_BOTS == 3
    assert set(boss_rules_mod.BOSS_STAT_MULTIPLIERS.keys()) == {"하", "중", "상"}

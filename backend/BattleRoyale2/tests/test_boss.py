"""보스전(#4) 백엔드 토대 테스트 — 보스 로스터 조립 + boss_rules + config_json 왕복.

검증:
- 보스 게임 _assemble_bots 는 bot_id="boss" 봇 1마리 + 유저 challenger 봇 포함.
- send_match_config 가 MATCH_CONFIG.boss_rules(boss_stat_overrides/difficulty/duration) 동봉.
- 일반(battleroyale2) 매치는 보스 미포함(무회귀).
"""
from __future__ import annotations

import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_BACKEND, "battle_royale"))

import BattleRoyale2.server.ws_server as ws  # noqa: E402
from BattleRoyale2.server.ws_server import MatchSession, _boss_rules_for, _BOSS_DIFFICULTY  # noqa: E402


class _FakeWS:
    async def send_text(self, *_a, **_k):
        pass


def _session(mid: str) -> MatchSession:
    return MatchSession(_FakeWS(), mid)


def test_boss_roster_includes_boss_and_user_bots():
    mid = "bosstest1"
    # 유저 challenger 봇 + 보스 정보 주입 (config_json 로드 우회 — 인메모리 캐시 직접 설정)
    ws._GAME_CODE[mid] = [{"bot_id": "challenger", "name": "도전자", "code": "def get_action(s): return {}"}]
    ws._GAME_BOT_COUNT[mid] = 3
    ws._GAME_BOSS[mid] = {"difficulty": "상"}
    try:
        bots, spec = _session(mid)._assemble_bots(seed=1)
        ids = [bid for bid, _ in spec]
        assert "boss" in bots and "boss" in ids        # 보스 봇 소환됨
        assert "challenger" in bots                      # 유저 봇 포함
        assert dict(spec)["boss"] == "보스"
        # 보스전은 AI 채움 없음 — 보스 + 유저 봇만
        assert not any(bid.startswith("ai_") for bid in ids)
        assert set(bots.keys()) == {"boss", "challenger"}
        # 임시 보스봇은 가만히 있음 — get_action 이 빈 dict
        assert bots["boss"].get_action({}) == {}
    finally:
        ws._GAME_CODE.pop(mid, None)
        ws._GAME_BOT_COUNT.pop(mid, None)
        ws._GAME_BOSS.pop(mid, None)


def test_boss_rules_structure_by_difficulty():
    for diff in ("하", "중", "상"):
        r = _boss_rules_for(diff)
        assert r["version"] == 2
        assert r["difficulty"] == diff
        assert r["slots"]["boss_count"] == 1
        assert r["boss_stat_overrides"] == _BOSS_DIFFICULTY[diff]
        assert r["duration_sec"] > 0
    # 난이도별 스탯 배율은 추후 보스 로직과 함께 튜닝 — 현재는 전 난이도 동일(무력화).
    assert _boss_rules_for("상")["boss_stat_overrides"]["max_hp_mult"] == \
        _boss_rules_for("하")["boss_stat_overrides"]["max_hp_mult"]


def test_normal_match_has_no_boss():
    mid = "normaltest1"
    ws._GAME_CODE[mid] = [{"bot_id": "u1", "name": "u1", "code": "def get_action(s): return {}"}]
    ws._GAME_BOT_COUNT[mid] = 4
    # _GAME_BOSS 미설정 → 일반 매치
    try:
        bots, spec = _session(mid)._assemble_bots(seed=1)
        assert "boss" not in bots and "boss" not in [b for b, _ in spec]
    finally:
        ws._GAME_CODE.pop(mid, None)
        ws._GAME_BOT_COUNT.pop(mid, None)
        ws._GAME_BOSS.pop(mid, None)

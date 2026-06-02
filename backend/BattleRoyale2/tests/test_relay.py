"""C2 관전 릴레이 테스트 — 권위 세션 FRAME 이 관전 세션으로 중계되는지(catch-up + live).

검증:
- 관전자가 합류하면 그 전까지 누적된 init + frame 을 순서대로 받는다(catch-up, 델타 복원용).
- 합류 후 권위 세션이 보낸 새 FRAME 이 실시간 중계된다(live tail).
- 관전 세션은 시뮬을 시작하지 않는다(ROLE=spectator).
"""
from __future__ import annotations

import os
import sys

# 프레임 기록용 StateStore(src.arena...)가 path 에 있어야 함 → battle_royale 추가.
_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_BACKEND, "battle_royale"))

import asyncio  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import BattleRoyale2.server.ws_server as ws  # noqa: E402
from BattleRoyale2.server.ws_server import app, PROTOCOL_VERSION  # noqa: E402

MATCH = "relaytest"


def test_get_state_store_async_lazy_cached():
    """_get_state_store 는 async-lazy. USE_REDIS=false 면 InMemory, 반복 호출 시 같은 인스턴스 캐시."""
    # 모듈 전역 초기화 (다른 테스트가 이미 store 를 띄웠을 수 있으므로 격리)
    ws._STATE_STORE = None
    ws._STATE_STORE_TRIED = False
    ws._STATE_STORE_LOCK = None

    async def _run():
        s1 = await ws._get_state_store()
        s2 = await ws._get_state_store()
        return s1, s2

    s1, s2 = asyncio.run(_run())
    from src.arena.server.redis_manager import InMemoryStateStore
    assert isinstance(s1, InMemoryStateStore)   # USE_REDIS 미설정 → InMemory
    assert s1 is s2                              # 1회 초기화 후 캐시


def test_spectator_catchup_and_live_relay():
    client = TestClient(app)
    # 1) 권위(러너) 연결 — 첫 연결이라 authoritative. HELLO 없이 바로 프레임 기록 가능.
    with client.websocket_connect(f"/match/{MATCH}") as runner:
        runner.send_json({"type": "FRAME_INIT", "data": {"map_size": [10, 10], "coins": [{"id": 1, "pos": [1, 1]}]}})
        runner.send_json({"type": "FRAME", "tick": 1, "data": {"time": 0.1, "bots": []}})

        # 2) 관전자 합류
        with client.websocket_connect(f"/match/{MATCH}") as spec:
            spec.send_json({"type": "HELLO", "data": {"version": PROTOCOL_VERSION}})

            # ROLE=spectator 통보
            role = spec.receive_json()
            assert role["type"] == "ROLE" and role["data"]["role"] == "spectator"

            # catch-up: 누적된 init + frame(tick1) 을 순서대로
            m_init = spec.receive_json()
            assert m_init["type"] == "FRAME_INIT"
            assert m_init["data"]["coins"][0]["id"] == 1

            m_f1 = spec.receive_json()
            assert m_f1["type"] == "FRAME" and m_f1["tick"] == 1

            # 3) live tail: 합류 후 권위가 보낸 새 프레임이 실시간 중계
            runner.send_json({"type": "FRAME", "tick": 2, "data": {"time": 0.2, "bots": []}})
            m_f2 = spec.receive_json()
            assert m_f2["type"] == "FRAME" and m_f2["tick"] == 2


def test_late_spectator_gets_full_history():
    """더 늦게 합류한 관전자는 그동안의 모든 프레임을 받아야 함(델타 복원)."""
    client = TestClient(app)
    mid = "relaylate"
    with client.websocket_connect(f"/match/{mid}") as runner:
        runner.send_json({"type": "FRAME_INIT", "data": {"map_size": [10, 10]}})
        for t in range(1, 6):
            runner.send_json({"type": "FRAME", "tick": t, "data": {"time": t * 0.1}})

        with client.websocket_connect(f"/match/{mid}") as spec:
            spec.send_json({"type": "HELLO", "data": {"version": PROTOCOL_VERSION}})
            assert spec.receive_json()["type"] == "ROLE"
            assert spec.receive_json()["type"] == "FRAME_INIT"
            ticks = [spec.receive_json()["tick"] for _ in range(5)]
            assert ticks == [1, 2, 3, 4, 5]

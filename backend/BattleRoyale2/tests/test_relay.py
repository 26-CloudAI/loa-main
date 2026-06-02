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


def test_pubsub_relay_delivers_frames_and_end():
    """멀티 인스턴스 경로: 권위가 발행한 frame/end 신호를 구독 루프가 받아 로컬 관전자에 중계.
    InMemoryPubSubBroker 를 강제 주입해 Redis 없이 발행→구독→pump 배선을 단일 프로세스로 검증."""
    from src.arena.server.redis_manager import InMemoryStateStore, InMemoryPubSubBroker

    class _Spec:
        """_pump_spectator / _broadcast_match_end 가 쓰는 최소 인터페이스만 가진 가짜 관전자."""
        def __init__(self):
            self.relay_idx = 0
            self._relay_lock = None
            self.got = []

        async def send(self, m):
            self.got.append(m)

    async def _run():
        mid = "pubsubtest"
        # store/pubsub 를 InMemory 로 강제 주입 (Redis 경로와 동일한 코드 흐름)
        ws._STATE_STORE = InMemoryStateStore()
        ws._STATE_STORE_TRIED = True
        ws._PUBSUB = InMemoryPubSubBroker()
        ws._PUBSUB_TRIED = True
        ws._SUB_TASKS.clear()
        ws._SPECTATORS.pop(mid, None)
        spec = _Spec()
        ws._SPECTATORS.setdefault(mid, set()).add(spec)
        try:
            await ws._ensure_subscriber(mid)
            await asyncio.sleep(0)              # 구독 큐 등록 양보
            store = ws._STATE_STORE
            await store.append_replay_frame(mid, {"kind": "init", "data": {"map_size": [5, 5]}})
            await ws._relay_frame(mid)          # broker is not None → 발행
            await store.append_replay_frame(mid, {"kind": "frame", "tick": 1, "data": {"t": 0.1}})
            await ws._relay_frame(mid)
            await ws._relay_match_end(mid, {"reason": "last_standing"})
            for _ in range(20):                 # 구독 루프 전달 대기
                await asyncio.sleep(0)
            return list(spec.got)
        finally:
            task = ws._SUB_TASKS.pop(mid, None)
            if task is not None:
                task.cancel()
            ws._SPECTATORS.pop(mid, None)
            # 전역 상태 복원 (다른 테스트가 USE_REDIS=false 직접 경로를 쓰도록)
            ws._PUBSUB = None
            ws._PUBSUB_TRIED = False
            ws._STATE_STORE = None
            ws._STATE_STORE_TRIED = False

    got = asyncio.run(_run())
    types = [m["type"] for m in got]
    assert "FRAME_INIT" in types
    assert any(m.get("type") == "FRAME" and m.get("tick") == 1 for m in got)
    assert any(m.get("type") == "MATCH_END" for m in got)


def test_distributed_authority_election():
    """멀티 인스턴스 권위 선출: 원자적 SET NX 로 단 하나만 권위, compare-and-delete 로
    남의 권위는 해제 못 함. fake Redis 로 SET NX/eval(CAS) 시맨틱을 검증."""
    class _FakeRedis:
        def __init__(self):
            self.store = {}

        async def set(self, k, v, nx=False, ex=None):
            if nx and k in self.store:
                return None
            self.store[k] = v
            return True

        async def get(self, k):
            return self.store.get(k)

        async def expire(self, k, ttl):
            return True

        async def eval(self, script, numkeys, key, arg):
            # _AUTH_RELEASE_LUA: 소유자 일치 시에만 삭제
            if self.store.get(key) == arg:
                self.store.pop(key, None)
                return 1
            return 0

    async def _run():
        ws._REDIS = _FakeRedis()
        ws._REDIS_TRIED = True
        mid = "authtest"
        try:
            a = await ws._try_acquire_authority(mid, "ownerA")
            b = await ws._try_acquire_authority(mid, "ownerB")   # 이미 점유 → 거절
            await ws._release_authority(mid, "ownerB")           # 남의 권위 해제 시도 → 무효
            c_blocked = await ws._try_acquire_authority(mid, "ownerC")
            await ws._release_authority(mid, "ownerA")           # 진짜 소유자 해제
            c_ok = await ws._try_acquire_authority(mid, "ownerC")
            return a, b, c_blocked, c_ok
        finally:
            ws._REDIS = None
            ws._REDIS_TRIED = False
            ws._AUTHORITATIVE.pop(mid, None)

    a, b, c_blocked, c_ok = asyncio.run(_run())
    assert a is True            # 첫 획득
    assert b is False           # 이미 점유 → 거절
    assert c_blocked is False   # 남의 권위는 해제 안 됨 → 여전히 점유
    assert c_ok is True         # 진짜 소유자 해제 후 획득 가능

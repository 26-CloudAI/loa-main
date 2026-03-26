"""
AI Arena — 서버 레이어 테스트

외부 의존성(Redis, FastAPI, uvicorn) 없이 실행 가능한 테스트:
  1. 스키마 직렬화
  2. 인메모리 StateStore / PubSubBroker
  3. GameSession 라이프사이클 (인메모리)
  4. GameRegistry
  5. SpectatorManager (모킹된 WebSocket)
"""

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arena.server.config import ServerConfig, DEFAULT_SERVER_CONFIG
from src.arena.server.schemas import (
    GameStatus,
    GameInfo,
    GameResultResponse,
    TickBroadcast,
    EventBroadcast,
    WSMessageType,
    make_game_start_message,
    make_game_end_message,
    make_error_message,
)
from src.arena.server.redis_manager import InMemoryStateStore, InMemoryPubSubBroker
from src.arena.server.game_session import GameSession, GameRegistry
from src.arena.bot_interface import BotInterface


# ──────────────────────────────────────────────
#  테스트 헬퍼
# ──────────────────────────────────────────────

def run_async(coro):
    """테스트에서 async 함수를 실행."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class SimpleDummyBot(BotInterface):
    def __init__(self, bot_id: str, action: str = "STAY"):
        self._bot_id = bot_id
        self._action = action

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        return self._action


# ──────────────────────────────────────────────
#  1. 스키마 직렬화
# ──────────────────────────────────────────────

class TestSchemas(unittest.TestCase):
    def test_game_info_to_dict(self):
        info = GameInfo(
            game_id="abc",
            status=GameStatus.RUNNING,
            current_tick=42,
            total_bots=5,
            alive_bots=3,
            bot_ids=["a", "b", "c"],
        )
        d = info.to_dict()
        self.assertEqual(d["game_id"], "abc")
        self.assertEqual(d["status"], "running")
        self.assertEqual(d["current_tick"], 42)

    def test_tick_broadcast_to_dict(self):
        tb = TickBroadcast(
            tick=10,
            bots=[{"id": "a", "x": 5, "y": 5}],
            minerals=[],
            zone_boundary=0,
            alive_count=1,
            leaderboard=[],
        )
        d = tb.to_dict()
        self.assertEqual(d["type"], "tick")
        self.assertEqual(d["data"]["tick"], 10)

    def test_event_broadcast_to_dict(self):
        eb = EventBroadcast(tick=5, event_type="kill", actor_id="a", target_id="b")
        d = eb.to_dict()
        self.assertEqual(d["type"], "event")
        self.assertEqual(d["data"]["event_type"], "kill")

    def test_game_start_message(self):
        msg = make_game_start_message("g1", ["a", "b"])
        self.assertEqual(msg["type"], "game_start")
        self.assertEqual(msg["data"]["bot_ids"], ["a", "b"])

    def test_game_end_message(self):
        msg = make_game_end_message("g1", "last_standing", [{"rank": 1, "id": "a"}])
        self.assertEqual(msg["type"], "game_end")

    def test_error_message(self):
        msg = make_error_message("뭔가 잘못됐다")
        self.assertEqual(msg["type"], "error")

    def test_game_status_enum(self):
        self.assertEqual(GameStatus.WAITING.value, "waiting")
        self.assertEqual(GameStatus.FINISHED.value, "finished")


# ──────────────────────────────────────────────
#  2. 인메모리 StateStore
# ──────────────────────────────────────────────

class TestInMemoryStateStore(unittest.TestCase):
    def test_save_and_get(self):
        async def _test():
            store = InMemoryStateStore()
            await store.save_game_state("g1", {"tick": 42})
            result = await store.get_game_state("g1")
            self.assertEqual(result["tick"], 42)

        run_async(_test())

    def test_get_nonexistent(self):
        async def _test():
            store = InMemoryStateStore()
            result = await store.get_game_state("nope")
            self.assertIsNone(result)

        run_async(_test())

    def test_save_result(self):
        async def _test():
            store = InMemoryStateStore()
            await store.save_game_result("g1", {"winner": "bot_a"})
            result = await store.get_game_result("g1")
            self.assertEqual(result["winner"], "bot_a")

        run_async(_test())

    def test_delete(self):
        async def _test():
            store = InMemoryStateStore()
            await store.save_game_state("g1", {"tick": 1})
            await store.save_game_result("g1", {"done": True})
            await store.delete_game("g1")
            self.assertIsNone(await store.get_game_state("g1"))
            self.assertIsNone(await store.get_game_result("g1"))

        run_async(_test())

    def test_list_games(self):
        async def _test():
            store = InMemoryStateStore()
            await store.save_game_state("g1", {})
            await store.save_game_state("g2", {})
            games = await store.list_games()
            self.assertEqual(set(games), {"g1", "g2"})

        run_async(_test())


# ──────────────────────────────────────────────
#  3. 인메모리 PubSubBroker
# ──────────────────────────────────────────────

class TestInMemoryPubSub(unittest.TestCase):
    def test_publish_and_subscribe(self):
        async def _test():
            broker = InMemoryPubSubBroker()
            received = []

            async def subscriber():
                async for msg in broker.subscribe("ch1"):
                    received.append(msg)
                    if len(received) >= 2:
                        break

            # 구독자를 태스크로 시작
            task = asyncio.create_task(subscriber())
            await asyncio.sleep(0.01)  # 구독자가 등록될 시간

            await broker.publish("ch1", {"a": 1})
            await broker.publish("ch1", {"a": 2})

            await asyncio.wait_for(task, timeout=1.0)

            self.assertEqual(len(received), 2)
            self.assertEqual(received[0]["a"], 1)
            self.assertEqual(received[1]["a"], 2)

        run_async(_test())

    def test_no_cross_channel(self):
        async def _test():
            broker = InMemoryPubSubBroker()
            received = []

            async def subscriber():
                async for msg in broker.subscribe("ch1"):
                    received.append(msg)
                    break

            task = asyncio.create_task(subscriber())
            await asyncio.sleep(0.01)

            # 다른 채널에 발행 → ch1에 도달 안 함
            await broker.publish("ch2", {"wrong": True})
            await asyncio.sleep(0.05)
            self.assertEqual(len(received), 0)

            # 올바른 채널
            await broker.publish("ch1", {"right": True})
            await asyncio.wait_for(task, timeout=1.0)
            self.assertEqual(len(received), 1)
            self.assertTrue(received[0]["right"])

        run_async(_test())


# ──────────────────────────────────────────────
#  4. GameSession
# ──────────────────────────────────────────────

class TestGameSession(unittest.TestCase):
    def _make_session(self, tick_interval=0.001):
        store = InMemoryStateStore()
        pubsub = InMemoryPubSubBroker()
        config = DEFAULT_SERVER_CONFIG

        from src.arena.config import GameConfig, MapConfig, BotConfig, ZoneConfig
        small_game = GameConfig(
            max_ticks=20,
            map=MapConfig(width=10, height=10, initial_mineral_count=5,
                          center_zone_size=4, rare_zone_size=3),
            bot=BotConfig(initial_energy=100, max_bots=10, spawn_margin=3),
            zone=ZoneConfig(phase1_end=15, phase2_end=18,
                            phase2_shrink_interval=5, phase2_damage=3,
                            phase3_shrink_interval=3, phase3_damage=3),
        )

        session = GameSession(
            game_id="test_game",
            state_store=store,
            pubsub=pubsub,
            server_config=config,
            game_config=small_game,
            tick_interval=tick_interval,
            seed=42,
        )
        return session, store, pubsub

    def test_initial_status_is_waiting(self):
        session, _, _ = self._make_session()
        self.assertEqual(session.status, GameStatus.WAITING)

    def test_register_bots(self):
        session, _, _ = self._make_session()
        session.register_bot(SimpleDummyBot("a"))
        session.register_bot(SimpleDummyBot("b"))
        info = session.get_info()
        self.assertEqual(info.total_bots, 2)

    def test_cannot_register_after_start(self):
        async def _test():
            session, _, _ = self._make_session()
            session.register_bots([SimpleDummyBot("a"), SimpleDummyBot("b")])
            await session.start()
            with self.assertRaises(RuntimeError):
                session.register_bot(SimpleDummyBot("c"))
            await session.wait_until_done()

        run_async(_test())

    def test_game_runs_to_completion(self):
        async def _test():
            session, store, pubsub = self._make_session(tick_interval=0.001)

            bots = [
                SimpleDummyBot("a", "STAY"),
                SimpleDummyBot("b", "STAY"),
            ]
            session.register_bots(bots)
            await session.start()
            await session.wait_until_done()

            self.assertEqual(session.status, GameStatus.FINISHED)

            # 결과가 저장되었는지
            result = await store.get_game_result("test_game")
            self.assertIsNotNone(result)
            self.assertIn("rankings", result)

        run_async(_test())

    def test_pubsub_receives_messages(self):
        async def _test():
            session, store, pubsub = self._make_session(tick_interval=0.001)

            received = []

            async def listener():
                async for msg in pubsub.subscribe(session.tick_channel):
                    received.append(msg)
                    if msg.get("type") == "game_end":
                        break

            bots = [SimpleDummyBot("a"), SimpleDummyBot("b")]
            session.register_bots(bots)

            listener_task = asyncio.create_task(listener())
            await asyncio.sleep(0.01)

            await session.start()
            await asyncio.wait_for(listener_task, timeout=5.0)

            # game_start + 여러 tick + game_end
            types = [m.get("type") for m in received]
            self.assertIn("game_start", types)
            self.assertIn("game_end", types)
            self.assertIn("tick", types)

        run_async(_test())

    def test_force_stop(self):
        async def _test():
            session, _, _ = self._make_session(tick_interval=0.1)  # 느린 틱
            session.register_bots([SimpleDummyBot("a"), SimpleDummyBot("b")])
            await session.start()

            await asyncio.sleep(0.05)
            await session.stop()

            self.assertEqual(session.status, GameStatus.FINISHED)

        run_async(_test())


# ──────────────────────────────────────────────
#  5. GameRegistry
# ──────────────────────────────────────────────

class TestGameRegistry(unittest.TestCase):
    def test_create_and_list(self):
        store = InMemoryStateStore()
        pubsub = InMemoryPubSubBroker()
        registry = GameRegistry(store, pubsub, DEFAULT_SERVER_CONFIG)

        s1 = registry.create_game(seed=1)
        s2 = registry.create_game(seed=2)

        games = registry.list_games()
        self.assertEqual(len(games), 2)

    def test_get_game(self):
        store = InMemoryStateStore()
        pubsub = InMemoryPubSubBroker()
        registry = GameRegistry(store, pubsub, DEFAULT_SERVER_CONFIG)

        session = registry.create_game()
        found = registry.get_game(session.game_id)
        self.assertIs(found, session)

    def test_get_nonexistent(self):
        store = InMemoryStateStore()
        pubsub = InMemoryPubSubBroker()
        registry = GameRegistry(store, pubsub, DEFAULT_SERVER_CONFIG)

        self.assertIsNone(registry.get_game("nope"))

    def test_cleanup_finished(self):
        async def _test():
            store = InMemoryStateStore()
            pubsub = InMemoryPubSubBroker()
            registry = GameRegistry(store, pubsub, DEFAULT_SERVER_CONFIG)

            s1 = registry.create_game()
            s2 = registry.create_game()
            s1.status = GameStatus.FINISHED

            removed = await registry.cleanup_finished()
            self.assertEqual(removed, 1)
            self.assertEqual(len(registry.list_games()), 1)

        run_async(_test())


if __name__ == "__main__":
    unittest.main(verbosity=2)

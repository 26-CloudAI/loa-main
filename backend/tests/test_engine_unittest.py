"""
AI Arena — 핵심 엔진 테스트 (unittest 기반)
pytest 없이 표준 라이브러리만으로 동작.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arena.bot_interface import BotInterface
from src.arena.config import GameConfig, MapConfig, BotConfig, ZoneConfig
from src.arena.engine import GameEngine
from src.arena.types import Action, GameOverReason, Position, Mineral
from src.arena.zone import ZoneManager


# ──────────────────────────────────────────────
#  테스트 헬퍼
# ──────────────────────────────────────────────

class DummyBot(BotInterface):
    def __init__(self, bot_id: str, action: str = "STAY"):
        self._bot_id = bot_id
        self._action = action
        self.action_history: list[dict] = []

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        self.action_history.append(state)
        return self._action

    def set_action(self, action: str) -> None:
        self._action = action


def make_small_config(**overrides) -> GameConfig:
    map_cfg = overrides.pop("map", MapConfig(
        width=10, height=10, initial_mineral_count=10,
        center_zone_size=4, rare_zone_size=3,
    ))
    bot_cfg = overrides.pop("bot", BotConfig(
        initial_energy=100, max_bots=10, spawn_margin=3, vision_radius=2,
    ))
    zone_cfg = overrides.pop("zone", ZoneConfig(
        phase1_end=50, phase2_end=80,
        phase2_shrink_interval=10, phase2_damage=3,
        phase3_shrink_interval=5, phase3_damage=3,
    ))
    return GameConfig(max_ticks=100, map=map_cfg, bot=bot_cfg, zone=zone_cfg, **overrides)


# ──────────────────────────────────────────────
#  1. 기본 틱 루프
# ──────────────────────────────────────────────

class TestBasicTick(unittest.TestCase):
    def setUp(self):
        self.config = make_small_config()

    def test_init(self):
        engine = GameEngine([DummyBot("a"), DummyBot("b")], config=self.config, seed=42)
        self.assertEqual(len(engine.bots), 2)
        self.assertEqual(engine.tick, 0)
        self.assertFalse(engine.game_over)

    def test_tick_increments(self):
        engine = GameEngine([DummyBot("a"), DummyBot("b")], config=self.config, seed=42)
        engine.process_tick()
        self.assertEqual(engine.tick, 1)

    def test_bots_receive_state(self):
        bot_a = DummyBot("a")
        engine = GameEngine([bot_a, DummyBot("b")], config=self.config, seed=42)
        engine.process_tick()

        self.assertEqual(len(bot_a.action_history), 1)
        state = bot_a.action_history[0]
        for key in ("tick", "my_bot", "vision", "zone_bounds", "leaderboard"):
            self.assertIn(key, state)
        self.assertEqual(state["my_bot"]["id"], "a")

    def test_no_bots_raises(self):
        with self.assertRaises(ValueError):
            GameEngine([], config=self.config)


# ──────────────────────────────────────────────
#  2. 에너지 시스템
# ──────────────────────────────────────────────

class TestEnergy(unittest.TestCase):
    def setUp(self):
        self.config = make_small_config()

    def test_stay_cost(self):
        engine = GameEngine([DummyBot("a", "STAY"), DummyBot("b")], config=self.config, seed=42)
        initial = engine.bots["a"].energy
        engine.process_tick()
        self.assertEqual(engine.bots["a"].energy, initial - self.config.action_cost.stay)

    def test_move_cost(self):
        engine = GameEngine([DummyBot("a", "MOVE_DOWN"), DummyBot("b")], config=self.config, seed=42)
        initial = engine.bots["a"].energy
        engine.process_tick()
        self.assertEqual(engine.bots["a"].energy, initial - self.config.action_cost.move)

    def test_zero_energy_death(self):
        engine = GameEngine([DummyBot("a", "STAY"), DummyBot("b")], config=self.config, seed=42)
        engine.bots["a"].energy = 1
        engine.process_tick()
        self.assertFalse(engine.bots["a"].alive)


# ──────────────────────────────────────────────
#  3. 이동
# ──────────────────────────────────────────────

class TestMovement(unittest.TestCase):
    def setUp(self):
        self.config = make_small_config()

    def test_move_changes_position(self):
        engine = GameEngine([DummyBot("a", "MOVE_RIGHT"), DummyBot("b")], config=self.config, seed=42)
        old_x = engine.bots["a"].position.x
        engine.process_tick()
        self.assertEqual(engine.bots["a"].position.x, old_x + 1)

    def test_move_out_of_bounds_stays(self):
        engine = GameEngine([DummyBot("a", "MOVE_LEFT"), DummyBot("b")], config=self.config, seed=42)
        engine.bots["a"].position = Position(0, 0)
        engine.process_tick()
        self.assertEqual(engine.bots["a"].position.x, 0)

    def test_all_directions(self):
        deltas = {
            "MOVE_UP": (0, -1), "MOVE_DOWN": (0, 1),
            "MOVE_LEFT": (-1, 0), "MOVE_RIGHT": (1, 0),
        }
        for action, (dx, dy) in deltas.items():
            engine = GameEngine([DummyBot("a", action), DummyBot("b")], config=self.config, seed=42)
            engine.bots["a"].position = Position(5, 5)
            engine.process_tick()
            self.assertEqual(engine.bots["a"].position.x, 5 + dx, f"{action} x 이동 실패")
            self.assertEqual(engine.bots["a"].position.y, 5 + dy, f"{action} y 이동 실패")


# ──────────────────────────────────────────────
#  4. 전투 메커니즘
# ──────────────────────────────────────────────

class TestCombat(unittest.TestCase):
    def setUp(self):
        self.config = make_small_config()

    def test_attack_hit(self):
        engine = GameEngine(
            [DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "STAY")],
            config=self.config, seed=42,
        )
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)

        engine.process_tick()

        self.assertEqual(engine.bots["a"].energy, 100 - self.config.action_cost.attack)
        expected_b = 100 - self.config.action_cost.stay - self.config.combat.attack_damage
        self.assertEqual(engine.bots["b"].energy, expected_b)

    def test_attack_miss(self):
        engine = GameEngine(
            [DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "STAY")],
            config=self.config, seed=42,
        )
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(8, 8)

        engine.process_tick()

        self.assertEqual(engine.bots["a"].energy, 100 - self.config.action_cost.attack)
        self.assertEqual(engine.bots["b"].energy, 100 - self.config.action_cost.stay)

    def test_shield_reduces_damage(self):
        engine = GameEngine(
            [DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "SHIELD")],
            config=self.config, seed=42,
        )
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)

        engine.process_tick()

        reduced_dmg = self.config.combat.attack_damage // 2
        expected_b = 100 - self.config.action_cost.shield - reduced_dmg
        self.assertEqual(engine.bots["b"].energy, expected_b)

    def test_mutual_attack(self):
        engine = GameEngine(
            [DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "ATTACK_LEFT")],
            config=self.config, seed=42,
        )
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)

        engine.process_tick()

        expected = 100 - self.config.action_cost.attack - self.config.combat.attack_damage
        self.assertEqual(engine.bots["a"].energy, expected)
        self.assertEqual(engine.bots["b"].energy, expected)

    def test_kill_count(self):
        engine = GameEngine(
            [DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "STAY")],
            config=self.config, seed=42,
        )
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)
        engine.bots["b"].energy = 20

        engine.process_tick()

        self.assertFalse(engine.bots["b"].alive)
        self.assertEqual(engine.bots["a"].kills, 1)


# ──────────────────────────────────────────────
#  5. 채굴
# ──────────────────────────────────────────────

class TestMining(unittest.TestCase):
    def setUp(self):
        self.config = make_small_config()

    def test_mine_success(self):
        engine = GameEngine([DummyBot("a", "MINE"), DummyBot("b")], config=self.config, seed=42)
        pos = engine.bots["a"].position
        engine.grid._minerals[pos.as_tuple()] = Mineral(position=pos, rare=False)

        engine.process_tick()

        self.assertEqual(engine.bots["a"].score, self.config.mine.normal_points)
        self.assertEqual(engine.bots["a"].minerals_mined, 1)

    def test_mine_empty_wastes_energy(self):
        engine = GameEngine([DummyBot("a", "MINE"), DummyBot("b")], config=self.config, seed=42)
        engine.bots["a"].position = Position(9, 9)
        engine.grid._minerals.pop((9, 9), None)

        initial = engine.bots["a"].energy
        engine.process_tick()

        self.assertEqual(engine.bots["a"].energy, initial - self.config.action_cost.mine)
        self.assertEqual(engine.bots["a"].score, 0)

    def test_contested_split(self):
        engine = GameEngine(
            [DummyBot("a", "MINE"), DummyBot("b", "MINE")],
            config=self.config, seed=42,
        )
        shared_pos = Position(5, 5)
        engine.bots["a"].position = shared_pos
        engine.bots["b"].position = Position(5, 5)
        engine.grid._minerals[(5, 5)] = Mineral(position=shared_pos, rare=False)

        engine.process_tick()

        expected = self.config.mine.normal_points * self.config.mine.contested_split
        self.assertEqual(engine.bots["a"].score, expected)
        self.assertEqual(engine.bots["b"].score, expected)

    def test_rare_mineral(self):
        engine = GameEngine([DummyBot("a", "MINE"), DummyBot("b")], config=self.config, seed=42)
        pos = engine.bots["a"].position
        engine.grid._minerals[pos.as_tuple()] = Mineral(position=pos, rare=True)

        engine.process_tick()

        self.assertEqual(engine.bots["a"].score, self.config.mine.rare_points)


# ──────────────────────────────────────────────
#  6. 자기장
# ──────────────────────────────────────────────

class TestZone(unittest.TestCase):
    def test_no_damage_phase1(self):
        config = make_small_config()
        zone = ZoneManager(config)
        zone.update(30)
        self.assertEqual(zone.boundary, 0)

    def test_phase2_shrinks(self):
        config = make_small_config()
        zone = ZoneManager(config)
        zone.update(70)
        # (70 - 50) // 10 = 2
        self.assertEqual(zone.boundary, 2)

    def test_zone_damage_outside(self):
        config = make_small_config()
        engine = GameEngine([DummyBot("a", "STAY"), DummyBot("b")], config=config, seed=42)
        engine.zone.current_shrink = 3
        engine.zone.boundary = 3
        engine.zone.bounds = (3, 3, 6, 6)
        engine.tick = 55
        engine.bots["a"].position = Position(0, 0)

        initial = engine.bots["a"].energy
        engine.process_tick()

        expected = initial - config.action_cost.stay - config.zone.phase2_damage
        self.assertEqual(engine.bots["a"].energy, expected)

    def test_zone_no_damage_inside(self):
        config = make_small_config()
        engine = GameEngine([DummyBot("a", "STAY"), DummyBot("b")], config=config, seed=42)
        engine.zone.current_shrink = 2
        engine.zone.boundary = 2
        engine.zone.bounds = (2, 2, 7, 7)
        engine.tick = 55
        engine.bots["a"].position = Position(5, 5)

        initial = engine.bots["a"].energy
        engine.process_tick()

        self.assertEqual(engine.bots["a"].energy, initial - config.action_cost.stay)


# ──────────────────────────────────────────────
#  7. 승리 조건
# ──────────────────────────────────────────────

class TestWinCondition(unittest.TestCase):
    def setUp(self):
        self.config = make_small_config()

    def test_last_standing(self):
        engine = GameEngine(
            [DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "STAY")],
            config=self.config, seed=42,
        )
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)
        engine.bots["b"].energy = 10

        engine.process_tick()

        self.assertTrue(engine.game_over)
        self.assertEqual(engine.game_result.reason, GameOverReason.LAST_STANDING)

    def test_max_ticks(self):
        engine = GameEngine(
            [DummyBot("a"), DummyBot("b")],
            config=self.config, seed=42,
        )
        engine.bots["a"].energy = 9999
        engine.bots["b"].energy = 9999

        result = engine.run_full_game()

        self.assertEqual(result.reason, GameOverReason.MAX_TICKS)

    def test_minerals_depleted(self):
        engine = GameEngine(
            [DummyBot("a"), DummyBot("b")],
            config=self.config, seed=42,
        )
        for mineral in engine.grid._minerals.values():
            mineral.mined_at_tick = 0

        # 재생 안 되게 확률을 0으로 못 바꾸니, 직접 available 확인
        # 모든 광물이 mined 상태 → all_minerals_depleted = True
        engine.process_tick()

        self.assertTrue(engine.game_over)
        self.assertEqual(engine.game_result.reason, GameOverReason.ALL_MINERALS_DEPLETED)


# ──────────────────────────────────────────────
#  8. 예외 처리
# ──────────────────────────────────────────────

class TestExceptionHandling(unittest.TestCase):
    def setUp(self):
        self.config = make_small_config()

    def test_invalid_action(self):
        engine = GameEngine(
            [DummyBot("a", "GARBAGE"), DummyBot("b")],
            config=self.config, seed=42,
        )
        initial = engine.bots["a"].energy
        engine.process_tick()
        # 잘못된 액션 → STAY
        self.assertEqual(engine.bots["a"].energy, initial - self.config.action_cost.stay)

    def test_crash_bot(self):
        class CrashBot(BotInterface):
            @property
            def bot_id(self): return "crash"
            def get_action(self, state): raise RuntimeError("BOOM")

        engine = GameEngine(
            [CrashBot(), DummyBot("b")],
            config=self.config, seed=42,
        )
        initial = engine.bots["crash"].energy
        engine.process_tick()
        self.assertEqual(engine.bots["crash"].energy, initial - self.config.action_cost.stay)
        self.assertTrue(engine.bots["crash"].alive)


# ──────────────────────────────────────────────
#  9. 랭킹
# ──────────────────────────────────────────────

class TestRankings(unittest.TestCase):
    def test_sorted_by_score(self):
        config = make_small_config()
        engine = GameEngine([DummyBot("a"), DummyBot("b")], config=config, seed=42)

        engine.bots["a"].score = 50
        engine.bots["a"].kills = 2
        engine.bots["a"].survival_ticks = 100

        engine.bots["b"].score = 200
        engine.bots["b"].survival_ticks = 100

        rankings = engine.get_rankings()
        self.assertEqual(rankings[0]["id"], "b")
        self.assertEqual(rankings[0]["rank"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

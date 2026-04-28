"""
AI Arena — 엣지케이스 및 통합 테스트

1. 공격/이동/실드/채굴 비용 사망 시 행동 무효화
2. 동시 킬 처리
3. 자기장 경계 정확성
4. 광물 재생
5. 시야 5x5
6. 게임 종료 조건
7. 대규모 시뮬레이션
8. 전체 파이프라인 (DB → 엔진 → 랭킹)
"""

import sys
import random
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.arena.bot_interface import BotInterface
from src.arena.config import GameConfig, MapConfig, BotConfig, ZoneConfig, ActionCost, CombatConfig, MineConfig
from src.arena.engine import GameEngine
from src.arena.types import Action, GameOverReason, Position, Mineral
from src.arena.zone import ZoneManager
from src.arena.vision import build_bot_state
from src.arena.grid import Grid, generate_spawn_positions
from src.arena.db.schema import init_db
from src.arena.db.user_repo import UserRepository
from src.arena.db.bot_repo import BotRepository
from src.arena.db.game_repo import GameRepository
from src.arena.auth.auth_service import generate_salt, hash_password
from src.arena.ranking.repository import RankingRepository, SeasonRepository, init_ranking_tables


class DummyBot(BotInterface):
    def __init__(self, bot_id, action="STAY"):
        self._id = bot_id
        self._action = action

    @property
    def bot_id(self):
        return self._id

    def get_action(self, state):
        return self._action


def small_cfg(**kw):
    return GameConfig(
        max_ticks=kw.get("max_ticks", 100),
        map=kw.get("map", MapConfig(width=10, height=10, initial_mineral_count=10,
                                     center_zone_size=4, rare_zone_size=3)),
        bot=kw.get("bot", BotConfig(initial_energy=100, max_bots=100, spawn_margin=3)),
        zone=kw.get("zone", ZoneConfig(phase1_end=50, phase2_end=80,
                                        phase2_shrink_interval=10, phase2_damage=3,
                                        phase3_shrink_interval=5, phase3_damage=3)),
    )


# ── 1. 비용 사망 시 행동 무효화 ──

class TestAttackCostDeath(unittest.TestCase):
    def test_attacker_dies_from_cost_no_damage(self):
        cfg = small_cfg()
        engine = GameEngine([DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "STAY")], config=cfg, seed=42)
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)
        engine.bots["a"].energy = 5  # 공격 비용 = 5 → 사망

        engine.process_tick()

        self.assertFalse(engine.bots["a"].alive)
        self.assertEqual(engine.bots["b"].energy, 100 - cfg.action_cost.stay)

    def test_attacker_6_energy_can_attack(self):
        cfg = small_cfg()
        engine = GameEngine([DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "STAY")], config=cfg, seed=42)
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)
        engine.bots["a"].energy = 6

        engine.process_tick()

        self.assertTrue(engine.bots["a"].alive)
        self.assertEqual(engine.bots["b"].energy, 100 - cfg.action_cost.stay - cfg.combat.attack_damage)


class TestMoveCostDeath(unittest.TestCase):
    def test_dies_from_move_stays_in_place(self):
        cfg = small_cfg()
        engine = GameEngine([DummyBot("a", "MOVE_RIGHT"), DummyBot("b")], config=cfg, seed=42)
        engine.bots["a"].position = Position(3, 3)
        engine.bots["a"].energy = 2

        engine.process_tick()

        self.assertFalse(engine.bots["a"].alive)
        self.assertEqual(engine.bots["a"].position.x, 3)

    def test_3_energy_can_move(self):
        cfg = small_cfg()
        engine = GameEngine([DummyBot("a", "MOVE_RIGHT"), DummyBot("b")], config=cfg, seed=42)
        engine.bots["a"].position = Position(3, 3)
        engine.bots["a"].energy = 3

        engine.process_tick()

        self.assertTrue(engine.bots["a"].alive)
        self.assertEqual(engine.bots["a"].position.x, 4)


class TestShieldCostDeath(unittest.TestCase):
    def test_shield_cost_death_no_shield(self):
        cfg = small_cfg()
        engine = GameEngine([DummyBot("a", "SHIELD"), DummyBot("b")], config=cfg, seed=42)
        engine.bots["a"].energy = 3

        engine.process_tick()

        self.assertFalse(engine.bots["a"].alive)
        self.assertFalse(engine.bots["a"].shield_active)


class TestMineCostDeath(unittest.TestCase):
    def test_mine_cost_death_no_points(self):
        cfg = small_cfg()
        engine = GameEngine([DummyBot("a", "MINE"), DummyBot("b")], config=cfg, seed=42)
        pos = engine.bots["a"].position
        engine.grid._minerals[pos.as_tuple()] = Mineral(position=pos, rare=False)
        engine.bots["a"].energy = 3

        engine.process_tick()

        self.assertFalse(engine.bots["a"].alive)
        self.assertEqual(engine.bots["a"].score, 0)


# ── 2. 동시 킬 ──

class TestSimultaneousKill(unittest.TestCase):
    def test_both_die(self):
        cfg = small_cfg()
        engine = GameEngine(
            [DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "ATTACK_LEFT"), DummyBot("c")],
            config=cfg, seed=42,
        )
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)
        engine.bots["a"].energy = 30
        engine.bots["b"].energy = 30

        engine.process_tick()

        self.assertFalse(engine.bots["a"].alive)
        self.assertFalse(engine.bots["b"].alive)

    def test_chain_attack(self):
        cfg = small_cfg()
        engine = GameEngine(
            [DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "ATTACK_RIGHT"), DummyBot("c", "STAY")],
            config=cfg, seed=42,
        )
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)
        engine.bots["c"].position = Position(5, 3)

        engine.process_tick()

        self.assertEqual(engine.bots["a"].energy, 95)    # -5 공격비용
        self.assertEqual(engine.bots["b"].energy, 70)    # -5 공격비용 -25 피격
        self.assertEqual(engine.bots["c"].energy, 74)    # -1 STAY -25 피격


# ── 3. 자기장 경계 ──

class TestZoneBoundary(unittest.TestCase):
    def test_exact_boundary(self):
        cfg = small_cfg()
        zone = ZoneManager(cfg)
        zone.boundary = 2
        self.assertTrue(zone.is_outside_safe_zone(Position(1, 5)))
        self.assertFalse(zone.is_outside_safe_zone(Position(2, 5)))

    def test_corners_outside(self):
        cfg = small_cfg()
        zone = ZoneManager(cfg)
        zone.boundary = 1
        for pos in [Position(0, 0), Position(9, 9), Position(0, 9), Position(9, 0)]:
            self.assertTrue(zone.is_outside_safe_zone(pos))


# ── 4. 광물 재생 ──

class TestMineralRegen(unittest.TestCase):
    def test_mined_not_available(self):
        cfg = small_cfg()
        grid = Grid(cfg, random.Random(42))
        pos = next(iter(grid._minerals.keys()))
        grid.mark_mined(pos[0], pos[1], tick=0)
        self.assertIsNone(grid.get_mineral(pos[0], pos[1]))

    def test_regen_with_100_percent(self):
        cfg = small_cfg(map=MapConfig(
            width=10, height=10, initial_mineral_count=10,
            center_zone_size=4, rare_zone_size=3,
            mineral_regen_delay=5, mineral_regen_chance=1.0,
        ))
        grid = Grid(cfg, random.Random(42))
        pos = next(iter(grid._minerals.keys()))
        grid.mark_mined(pos[0], pos[1], tick=0)

        regenerated = grid.try_regen_minerals(current_tick=10)
        self.assertGreater(len(regenerated), 0)


# ── 5. 시야 ──

class TestVision(unittest.TestCase):
    def test_5x5_grid(self):
        cfg = small_cfg()
        engine = GameEngine([DummyBot("a"), DummyBot("b")], config=cfg, seed=42)
        engine.bots["a"].position = Position(5, 5)
        state = build_bot_state(engine.bots["a"], engine.bots, engine.grid, engine.zone, cfg, 0)
        grid = state["vision"]["grid"]
        self.assertEqual(len(grid), 5)
        self.assertEqual(len(grid[0]), 5)
        self.assertEqual(grid[2][2], "ME")

    def test_enemy_visible_adjacent(self):
        cfg = small_cfg()
        engine = GameEngine([DummyBot("a"), DummyBot("b")], config=cfg, seed=42)
        engine.bots["a"].position = Position(5, 5)
        engine.bots["b"].position = Position(6, 5)
        state = build_bot_state(engine.bots["a"], engine.bots, engine.grid, engine.zone, cfg, 0)
        self.assertEqual(state["vision"]["grid"][2][3], "bot_enemy")

    def test_enemy_outside_vision_hidden(self):
        cfg = small_cfg()
        engine = GameEngine([DummyBot("a"), DummyBot("b")], config=cfg, seed=42)
        engine.bots["a"].position = Position(0, 0)
        engine.bots["b"].position = Position(9, 9)
        state = build_bot_state(engine.bots["a"], engine.bots, engine.grid, engine.zone, cfg, 0)
        for row in state["vision"]["grid"]:
            self.assertNotIn("bot_enemy", row)


# ── 6. 게임 종료 ──

class TestGameEndConditions(unittest.TestCase):
    def test_no_crash_after_game_over(self):
        cfg = small_cfg(max_ticks=5)
        engine = GameEngine([DummyBot("a"), DummyBot("b")], config=cfg, seed=42)
        engine.bots["a"].energy = 9999
        engine.bots["b"].energy = 9999
        result = engine.run_full_game()
        self.assertTrue(engine.game_over)
        self.assertEqual(engine.process_tick(), [])

    def test_all_dead_simultaneously(self):
        cfg = small_cfg()
        engine = GameEngine(
            [DummyBot("a", "ATTACK_RIGHT"), DummyBot("b", "ATTACK_LEFT")],
            config=cfg, seed=42,
        )
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)
        engine.bots["a"].energy = 30
        engine.bots["b"].energy = 30
        engine.process_tick()
        self.assertTrue(engine.game_over)
        self.assertEqual(engine.game_result.reason, GameOverReason.LAST_STANDING)


# ── 7. 대규모 ──

class TestLargeScale(unittest.TestCase):
    def test_20_bots_no_crash(self):
        bots = [DummyBot(f"bot_{i:02d}", random.choice(["STAY", "MOVE_UP", "MINE"]))
                for i in range(20)]
        cfg = GameConfig(
            max_ticks=200,
            map=MapConfig(width=50, height=50, initial_mineral_count=100,
                          center_zone_size=20, rare_zone_size=8),
            bot=BotConfig(initial_energy=100, max_bots=100, spawn_margin=10),
        )
        result = GameEngine(bots, config=cfg, seed=42).run_full_game()
        self.assertIsNotNone(result)
        self.assertEqual(len(result.rankings), 20)

    def test_spawn_no_overlap(self):
        cfg = GameConfig(
            map=MapConfig(width=50, height=50, initial_mineral_count=10,
                          center_zone_size=10, rare_zone_size=5),
            bot=BotConfig(spawn_margin=10),
        )
        positions = generate_spawn_positions(cfg, 20, random.Random(42))
        self.assertEqual(len({(p.x, p.y) for p in positions}), 20)


# ── 8. 전체 파이프라인 ──

class TestFullPipeline(unittest.TestCase):
    def setUp(self):
        self.conn = init_db(":memory:")
        init_ranking_tables(self.conn)
        self.users = UserRepository(self.conn)
        self.bots_repo = BotRepository(self.conn)
        self.games_repo = GameRepository(self.conn)
        self.seasons = SeasonRepository(self.conn)
        self.rankings = RankingRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_end_to_end(self):
        # 유저 생성
        salt1, salt2 = generate_salt(), generate_salt()
        u1 = self.users.create("alice", "Alice", hash_password("pw", salt1), salt1)
        u2 = self.users.create("bob", "Bob", hash_password("pw", salt2), salt2)

        # 봇 등록
        b1 = self.bots_repo.create(u1.id, "alice_bot", "def action(s): return 'MINE'")
        b2 = self.bots_repo.create(u2.id, "bob_bot", "def action(s): return 'STAY'")

        # 시즌 생성
        season = self.seasons.create_season("시즌 1")

        # 게임 엔진 실행
        class CodeBot(BotInterface):
            def __init__(self, bid, code):
                self._id = bid
                ns = {}
                exec(code, {"__builtins__": __builtins__}, ns)
                self._fn = ns["action"]

            @property
            def bot_id(self):
                return self._id

            def get_action(self, state):
                try:
                    return self._fn(state)
                except Exception:
                    return "STAY"

        engine = GameEngine(
            [CodeBot(b1.name, b1.code), CodeBot(b2.name, b2.code)],
            config=small_cfg(max_ticks=30),
            seed=42,
        )
        result = engine.run_full_game()

        # 게임 기록
        game_id = "game_001"
        self.games_repo.create_game(game_id, 2, seed=42)
        self.games_repo.update_game_started(game_id)
        self.games_repo.update_game_finished(game_id, result.final_tick, result.reason.value)

        # 랭킹 반영
        bot_map = {b1.name: b1.id, b2.name: b2.id}
        participants = [
            {
                "bot_id": bot_map[r["id"]],
                "final_rank": r["rank"],
                "kills": r["kills"],
                "minerals_mined": r["minerals_mined"],
                "survival_ticks": r["survival_ticks"],
            }
            for r in result.rankings
            if r["id"] in bot_map
        ]
        changes = self.rankings.process_game_results(game_id, season.id, participants)

        # 검증
        self.assertEqual(len(changes), 2)
        winner = next(c for c in changes if c.final_rank == 1)
        self.assertGreater(winner.rating_after, winner.rating_before)

        game_rec = self.games_repo.get_game(game_id)
        self.assertEqual(game_rec.status, "finished")

        stats = self.rankings.get_bot_stats(winner.player_id, season.id)
        self.assertEqual(stats["games_played"], 1)
        self.assertEqual(stats["wins"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

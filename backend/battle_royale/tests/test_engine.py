"""
AI Arena — 게임 엔진 핵심 테스트

테스트 범주:
  1. 기본 틱 루프 동작
  2. 에너지 시스템 (행동별 비용)
  3. 이동 및 경계 처리
  4. 전투 메커니즘 (일반 공격, 빗나감, 실드, 동시 공격)
  5. 채굴 및 경합 처리
  6. 자기장 데미지
  7. 승리 조건 (섬멸, 타임리밋, 광물 소진)
  8. 예외/악성 입력 처리
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest

from core.config import GameConfig, MapConfig, BotConfig, ZoneConfig, ActionCost
from core.engine import GameEngine
from core.types import Action, GameOverReason, Position, Bot
from core.zone import ZoneManager
from core.grid import Grid

from conftest import DummyBot, ScriptedBot, make_small_config

# ──────────────────────────────────────────────
#  1. 기본 틱 루프
# ──────────────────────────────────────────────

class TestBasicTick:
    def test_engine_initializes_with_bots(self, small_config):
        bots = [DummyBot("a"), DummyBot("b")]
        engine = GameEngine(bots, config=small_config, seed=42)
        assert len(engine.bots) == 2
        assert engine.tick == 0
        assert not engine.game_over

    def test_tick_increments(self, small_config):
        bots = [DummyBot("a"), DummyBot("b")]
        engine = GameEngine(bots, config=small_config, seed=42)
        engine.process_tick()
        assert engine.tick == 1

    def test_bots_receive_state(self, small_config):
        bot_a = DummyBot("a")
        bot_b = DummyBot("b")
        engine = GameEngine([bot_a, bot_b], config=small_config, seed=42)
        engine.process_tick()

        assert len(bot_a.action_history) == 1
        state = bot_a.action_history[0]
        assert "tick" in state
        assert "my_bot" in state
        assert "vision" in state
        assert "zone_bounds" in state
        assert "leaderboard" in state
        assert state["my_bot"]["id"] == "a"

    def test_no_bots_raises(self, small_config):
        with pytest.raises(ValueError):
            GameEngine([], config=small_config)


# ──────────────────────────────────────────────
#  2. 에너지 시스템
# ──────────────────────────────────────────────

class TestEnergy:
    def test_stay_costs_energy(self, small_config):
        bot = DummyBot("a", action="STAY")
        engine = GameEngine([bot, DummyBot("b")], config=small_config, seed=42)
        initial = engine.bots["a"].energy
        engine.process_tick()
        assert engine.bots["a"].energy == initial - small_config.action_cost.stay

    def test_move_costs_energy(self, small_config):
        bot = DummyBot("a", action="MOVE_DOWN")
        engine = GameEngine([bot, DummyBot("b")], config=small_config, seed=42)
        initial = engine.bots["a"].energy
        engine.process_tick()
        assert engine.bots["a"].energy == initial - small_config.action_cost.move

    def test_zero_energy_kills_bot(self, small_config):
        bot = DummyBot("a", action="STAY")
        engine = GameEngine([bot, DummyBot("b")], config=small_config, seed=42)
        engine.bots["a"].energy = 1
        engine.process_tick()
        assert not engine.bots["a"].alive


# ──────────────────────────────────────────────
#  3. 이동
# ──────────────────────────────────────────────

class TestMovement:
    def test_move_changes_position(self, small_config):
        bot = DummyBot("a", action="MOVE_RIGHT")
        engine = GameEngine([bot, DummyBot("b")], config=small_config, seed=42)
        old_x = engine.bots["a"].position.x
        engine.process_tick()
        assert engine.bots["a"].position.x == old_x + 1

    def test_move_out_of_bounds_clamps(self, small_config):
        bot = DummyBot("a", action="MOVE_LEFT")
        engine = GameEngine([bot, DummyBot("b")], config=small_config, seed=42)
        engine.bots["a"].position = Position(0, 0)
        engine.process_tick()
        # 경계 밖이면 위치 변경 안 됨, 에너지만 소모
        assert engine.bots["a"].position.x == 0

    def test_all_four_directions(self, small_config):
        directions = {
            "MOVE_UP": (0, -1),
            "MOVE_DOWN": (0, 1),
            "MOVE_LEFT": (-1, 0),
            "MOVE_RIGHT": (1, 0),
        }
        for action_str, (dx, dy) in directions.items():
            bot = DummyBot("a", action=action_str)
            engine = GameEngine([bot, DummyBot("b")], config=small_config, seed=42)
            engine.bots["a"].position = Position(5, 5)
            engine.process_tick()
            assert engine.bots["a"].position.x == 5 + dx
            assert engine.bots["a"].position.y == 5 + dy


# ──────────────────────────────────────────────
#  4. 전투 메커니즘
# ──────────────────────────────────────────────

class TestCombat:
    def test_attack_hit(self, small_config):
        attacker = DummyBot("a", action="ATTACK_RIGHT")
        target = DummyBot("b", action="STAY")
        engine = GameEngine([attacker, target], config=small_config, seed=42)

        # 봇을 인접하게 배치
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)

        initial_b = engine.bots["b"].energy
        engine.process_tick()

        # 공격자: -5, 피격자: -25
        assert engine.bots["a"].energy == 100 - small_config.action_cost.attack
        assert engine.bots["b"].energy == initial_b - small_config.combat.attack_damage - small_config.action_cost.stay

    def test_attack_miss(self, small_config):
        attacker = DummyBot("a", action="ATTACK_RIGHT")
        target = DummyBot("b", action="STAY")
        engine = GameEngine([attacker, target], config=small_config, seed=42)

        # 봇을 떨어뜨려 놓기
        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(8, 8)

        engine.process_tick()

        # 공격 비용만 소모, 상대는 STAY 비용만
        assert engine.bots["a"].energy == 100 - small_config.action_cost.attack
        assert engine.bots["b"].energy == 100 - small_config.action_cost.stay

    def test_shield_reduces_damage(self, small_config):
        attacker = DummyBot("a", action="ATTACK_RIGHT")
        defender = DummyBot("b", action="SHIELD")
        engine = GameEngine([attacker, defender], config=small_config, seed=42)

        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)

        engine.process_tick()

        # 실드: 25 // 2 = 12 데미지
        expected_b = 100 - small_config.action_cost.shield - (small_config.combat.attack_damage // 2)
        assert engine.bots["b"].energy == expected_b

    def test_mutual_attack(self, small_config):
        bot_a = DummyBot("a", action="ATTACK_RIGHT")
        bot_b = DummyBot("b", action="ATTACK_LEFT")
        engine = GameEngine([bot_a, bot_b], config=small_config, seed=42)

        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)

        engine.process_tick()

        # 양쪽 모두: -5 (공격비용) + -25 (피격)
        expected = 100 - small_config.action_cost.attack - small_config.combat.attack_damage
        assert engine.bots["a"].energy == expected
        assert engine.bots["b"].energy == expected

    def test_kill_awards_kill_count(self, small_config):
        attacker = DummyBot("a", action="ATTACK_RIGHT")
        target = DummyBot("b", action="STAY")
        engine = GameEngine([attacker, target], config=small_config, seed=42)

        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)
        engine.bots["b"].energy = 20  # 한 방에 죽을 에너지

        engine.process_tick()

        assert not engine.bots["b"].alive
        assert engine.bots["a"].kills == 1


# ──────────────────────────────────────────────
#  5. 채굴
# ──────────────────────────────────────────────

class TestMining:
    def test_mine_on_mineral_gives_points(self, small_config):
        miner = DummyBot("a", action="MINE")
        engine = GameEngine([miner, DummyBot("b")], config=small_config, seed=42)

        # 봇 위치에 광물 강제 배치
        from core.types import Mineral
        pos = engine.bots["a"].position
        engine.grid._minerals[pos.as_tuple()] = Mineral(position=pos, rare=False)

        engine.process_tick()

        assert engine.bots["a"].score == small_config.mine.normal_points
        assert engine.bots["a"].minerals_mined == 1

    def test_mine_on_empty_wastes_energy(self, small_config):
        miner = DummyBot("a", action="MINE")
        engine = GameEngine([miner, DummyBot("b")], config=small_config, seed=42)

        # 광물 없는 위치로 이동
        engine.bots["a"].position = Position(9, 9)
        # 해당 위치 광물 제거
        engine.grid._minerals.pop((9, 9), None)

        initial_energy = engine.bots["a"].energy
        engine.process_tick()

        assert engine.bots["a"].energy == initial_energy - small_config.action_cost.mine
        assert engine.bots["a"].score == 0

    def test_contested_mining_splits_points(self, small_config):
        miner_a = DummyBot("a", action="MINE")
        miner_b = DummyBot("b", action="MINE")
        engine = GameEngine([miner_a, miner_b], config=small_config, seed=42)

        # 같은 위치에 배치
        shared_pos = Position(5, 5)
        engine.bots["a"].position = shared_pos
        engine.bots["b"].position = Position(5, 5)

        from core.types import Mineral
        engine.grid._minerals[(5, 5)] = Mineral(position=shared_pos, rare=False)

        engine.process_tick()

        expected_each = small_config.mine.normal_points * small_config.mine.contested_split
        assert engine.bots["a"].score == expected_each
        assert engine.bots["b"].score == expected_each

    def test_rare_mineral_gives_more_points(self, small_config):
        miner = DummyBot("a", action="MINE")
        engine = GameEngine([miner, DummyBot("b")], config=small_config, seed=42)

        from core.types import Mineral
        pos = engine.bots["a"].position
        engine.grid._minerals[pos.as_tuple()] = Mineral(position=pos, rare=True)

        engine.process_tick()

        assert engine.bots["a"].score == small_config.mine.rare_points


# ──────────────────────────────────────────────
#  6. 자기장
# ──────────────────────────────────────────────

class TestZone:
    def test_no_damage_in_phase1(self):
        config = make_small_config(
            zone=ZoneConfig(phase1_end=50, phase2_end=80,
                            phase2_shrink_interval=10, phase2_damage=3,
                            phase3_shrink_interval=5, phase3_damage=3)
        )
        zone = ZoneManager(config)
        zone.update(30)
        assert zone.boundary == 0
        assert zone.get_zone_damage(30) == 0

    def test_phase2_shrinks(self):
        config = make_small_config(
            zone=ZoneConfig(phase1_end=50, phase2_end=80,
                            phase2_shrink_interval=10, phase2_damage=3,
                            phase3_shrink_interval=5, phase3_damage=3)
        )
        zone = ZoneManager(config)
        zone.update(70)
        # 70 - 50 = 20틱 경과 → 20 // 10 = 2칸 수축
        assert zone.boundary == 2

    def test_zone_damage_applied_to_outside_bots(self, small_config):
        bot = DummyBot("a", action="STAY")
        engine = GameEngine([bot, DummyBot("b")], config=small_config, seed=42)

        # 자기장이 활성화된 상태로 만들기
        engine.zone.current_shrink = 3
        engine.zone.boundary = 3
        engine.zone.bounds = (3, 3, 6, 6)
        engine.tick = 55  # phase2 구간
        engine.bots["a"].position = Position(0, 0)  # 경계 밖

        initial = engine.bots["a"].energy
        engine.process_tick()

        zone_dmg = small_config.zone.phase2_damage
        stay_cost = small_config.action_cost.stay
        assert engine.bots["a"].energy == initial - stay_cost - zone_dmg

    def test_zone_safe_inside(self, small_config):
        bot = DummyBot("a", action="STAY")
        engine = GameEngine([bot, DummyBot("b")], config=small_config, seed=42)

        engine.zone.current_shrink = 2
        engine.zone.boundary = 2
        engine.zone.bounds = (2, 2, 7, 7)
        engine.tick = 55
        engine.bots["a"].position = Position(5, 5)  # 안전 구역

        initial = engine.bots["a"].energy
        engine.process_tick()

        # STAY 비용만 차감, 자기장 데미지 없음
        assert engine.bots["a"].energy == initial - small_config.action_cost.stay


# ──────────────────────────────────────────────
#  7. 승리 조건
# ──────────────────────────────────────────────

class TestWinCondition:
    def test_last_standing(self, small_config):
        attacker = DummyBot("a", action="ATTACK_RIGHT")
        target = DummyBot("b", action="STAY")
        engine = GameEngine([attacker, target], config=small_config, seed=42)

        engine.bots["a"].position = Position(3, 3)
        engine.bots["b"].position = Position(4, 3)
        engine.bots["b"].energy = 10

        engine.process_tick()

        assert engine.game_over
        assert engine.game_result is not None
        assert engine.game_result.reason == GameOverReason.LAST_STANDING

    def test_max_ticks(self, small_config):
        bot_a = DummyBot("a", action="STAY")
        bot_b = DummyBot("b", action="STAY")
        engine = GameEngine([bot_a, bot_b], config=small_config, seed=42)

        # 에너지를 충분히 높여서 자연사 방지
        engine.bots["a"].energy = 9999
        engine.bots["b"].energy = 9999

        result = engine.run_full_game()

        assert result.reason == GameOverReason.MAX_TICKS
        assert result.final_tick == small_config.max_ticks

    def test_all_minerals_depleted(self, small_config):
        bot_a = DummyBot("a", action="STAY")
        bot_b = DummyBot("b", action="STAY")
        engine = GameEngine([bot_a, bot_b], config=small_config, seed=42)

        # 모든 광물 제거
        for key, mineral in engine.grid._minerals.items():
            mineral.mined_at_tick = 0
        # 재생 확률도 0으로 (재생 안 되게)
        engine.grid.config = GameConfig(
            map=MapConfig(
                width=10, height=10,
                initial_mineral_count=10,
                mineral_regen_chance=0.0,
            )
        )

        engine.process_tick()

        assert engine.game_over
        assert engine.game_result.reason == GameOverReason.ALL_MINERALS_DEPLETED


# ──────────────────────────────────────────────
#  8. 예외 처리
# ──────────────────────────────────────────────

class TestExceptionHandling:
    def test_invalid_action_becomes_stay(self, small_config):
        bot = DummyBot("a", action="INVALID_ACTION")
        engine = GameEngine([bot, DummyBot("b")], config=small_config, seed=42)

        initial = engine.bots["a"].energy
        engine.process_tick()

        # 잘못된 액션 → STAY 처리
        assert engine.bots["a"].energy == initial - small_config.action_cost.stay

    def test_exception_in_bot_becomes_stay(self, small_config):
        class CrashBot(DummyBot):
            def get_action(self, state):
                raise RuntimeError("봇 크래시!")

        bot = CrashBot("a")
        engine = GameEngine([bot, DummyBot("b")], config=small_config, seed=42)

        initial = engine.bots["a"].energy
        engine.process_tick()

        # 예외 → STAY 처리
        assert engine.bots["a"].energy == initial - small_config.action_cost.stay
        assert engine.bots["a"].alive  # 한 턴 STAY로 죽진 않음


# ──────────────────────────────────────────────
#  9. 랭킹 계산
# ──────────────────────────────────────────────

class TestRankings:
    def test_rankings_sorted_by_final_score(self, small_config):
        bot_a = DummyBot("a")
        bot_b = DummyBot("b")
        engine = GameEngine([bot_a, bot_b], config=small_config, seed=42)

        engine.bots["a"].score = 50
        engine.bots["a"].kills = 2
        engine.bots["a"].survival_ticks = 100

        engine.bots["b"].score = 200
        engine.bots["b"].kills = 0
        engine.bots["b"].survival_ticks = 100

        rankings = engine.get_rankings()
        assert rankings[0]["id"] == "b"
        assert rankings[1]["id"] == "a"
        assert rankings[0]["rank"] == 1

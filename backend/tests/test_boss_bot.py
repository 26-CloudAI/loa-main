"""
RLBossBot 전용 테스트 모음

테스트 범주:
  1. 초기화 / 가중치 로드·저장
  2. StateEncoder — 특징 벡터 정확성
  3. LinearQNet — Q값 계산 & TD 업데이트
  4. StrategyRouter — 하드 오버라이드 규칙
  5. RewardCalculator — 보상 계산
  6. RLBossBot 통합 — get_action() + 온라인 학습
  7. 다양한 상대 봇 조합 시나리오
  8. 훈련 개선 검증 (학습이 실제로 가중치를 바꾸는지)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.arena.config import DEFAULT_CONFIG
from src.arena.engine import GameEngine
from src.arena.types import Action

from bots.rl_boss_bot import (
    ACTIONS,
    ALPHA,
    ENERGY_ATTACK_MIN,
    ENERGY_CRITICAL,
    ENERGY_HIGH,
    ENERGY_LOW,
    ENERGY_MINE_COST,
    GAMMA,
    IDX_ATTACK_DOWN,
    IDX_ATTACK_LEFT,
    IDX_ATTACK_RIGHT,
    IDX_ATTACK_UP,
    IDX_MINE,
    IDX_MOVE_DOWN,
    IDX_MOVE_LEFT,
    IDX_MOVE_RIGHT,
    IDX_MOVE_UP,
    IDX_SHIELD,
    IDX_STAY,
    N_ACTIONS,
    N_FEATURES,
    PHASE1_END,
    PHASE2_END,
    ExperienceBuffer,
    LinearQNet,
    RewardCalculator,
    RLBossBot,
    StateEncoder,
    StrategyRouter,
    _build_initial_weights,
)
from bots.herbivore import HerbivoreBot
from bots.mad_dog import MadDogBot
from bots.camper import CamperBot

# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

def _make_empty_grid() -> list[list[str]]:
    """5×5 빈 시야 그리드 생성."""
    return [["empty"] * 5 for _ in range(5)]


def _make_state(
    tick: int = 1,
    energy: int = 100,
    score: float = 0.0,
    pos_x: int = 50,
    pos_y: int = 50,
    zone_boundary: int = 0,  # 마진 정수 → 내부에서 zone_bounds 튜플로 변환
    grid: list[list[str]] | None = None,
    leaderboard: list[dict] | None = None,
    bot_id: str = "boss_rl",
) -> dict:
    """테스트용 최소 state 딕셔너리 생성."""
    # zone_bounds: (min_x, min_y, max_x, max_y) — 엔진 실제 포맷
    safe_min = zone_boundary
    safe_max = 99 - zone_boundary
    return {
        "tick": tick,
        "my_bot": {
            "id": bot_id,
            "position": [pos_x, pos_y],
            "energy": energy,
            "score": score,
        },
        "vision": {"grid": grid if grid is not None else _make_empty_grid()},
        "zone_bounds": (safe_min, safe_min, safe_max, safe_max),
        "leaderboard": leaderboard or [{"id": bot_id, "rank": 1}],
    }


def _zero_weights() -> list[list[float]]:
    return [[0.0] * N_ACTIONS for _ in range(N_FEATURES)]


# ---------------------------------------------------------------------------
# 1. 초기화 / 가중치 저장·로드
# ---------------------------------------------------------------------------

class TestInitAndWeights:
    def test_default_init(self):
        bot = RLBossBot(bot_id="test", weights_path=Path("/nonexistent_path_xyz.json"))
        assert bot.bot_id == "test"
        w = bot.get_weights()
        assert len(w) == N_FEATURES
        assert all(len(row) == N_ACTIONS for row in w)

    def test_initial_weights_not_all_zero(self):
        """초기 가중치가 전부 0이면 학습이 시작 안 됨 — 적어도 일부는 0이 아니어야 함."""
        bot = RLBossBot(bot_id="test", weights_path=Path("/nonexistent_path_xyz.json"))
        flat = [v for row in bot.get_weights() for v in row]
        assert any(v != 0.0 for v in flat)

    def test_set_and_get_weights_roundtrip(self):
        bot = RLBossBot(bot_id="test", weights_path=Path("/nonexistent_path_xyz.json"))
        new_w = _zero_weights()
        new_w[0][0] = 9.99
        bot.set_weights(new_w)
        got = bot.get_weights()
        assert got[0][0] == pytest.approx(9.99)

    def test_set_weights_deep_copy(self):
        """set_weights 후 원본을 변경해도 내부 상태에 영향 없어야 함."""
        bot = RLBossBot(bot_id="test", weights_path=Path("/nonexistent_path_xyz.json"))
        new_w = _zero_weights()
        bot.set_weights(new_w)
        new_w[0][0] = 999.0
        assert bot.get_weights()[0][0] == pytest.approx(0.0)

    def test_set_weights_wrong_shape_raises(self):
        bot = RLBossBot(bot_id="test", weights_path=Path("/nonexistent_path_xyz.json"))
        with pytest.raises(ValueError):
            bot.set_weights([[0.0] * N_ACTIONS for _ in range(N_FEATURES - 1)])

    def test_save_and_load_weights(self, tmp_path):
        bot = RLBossBot(bot_id="test", weights_path=Path("/nonexistent_path_xyz.json"))
        new_w = _zero_weights()
        new_w[5][3] = 1.234
        bot.set_weights(new_w)

        save_path = tmp_path / "weights.json"
        bot.save_weights(save_path)
        assert save_path.exists()

        bot2 = RLBossBot(bot_id="test2", weights_path=save_path)
        assert bot2.get_weights()[5][3] == pytest.approx(1.234)

    def test_load_weights_returns_false_on_missing(self, tmp_path):
        bot = RLBossBot(bot_id="test", weights_path=Path("/nonexistent_path_xyz.json"))
        result = bot.load_weights(tmp_path / "nonexistent.json")
        assert result is False

    def test_saved_json_has_correct_schema(self, tmp_path):
        bot = RLBossBot(bot_id="test", weights_path=Path("/nonexistent_path_xyz.json"))
        save_path = tmp_path / "w.json"
        bot.save_weights(save_path)
        data = json.loads(save_path.read_text())
        assert data["n_features"] == N_FEATURES
        assert data["n_actions"] == N_ACTIONS
        assert len(data["weights"]) == N_FEATURES


# ---------------------------------------------------------------------------
# 2. StateEncoder
# ---------------------------------------------------------------------------

class TestStateEncoder:
    def setup_method(self):
        self.enc = StateEncoder()

    def test_output_length(self):
        state = _make_state()
        phi = self.enc.encode(state)
        assert len(phi) == N_FEATURES

    def test_empty_grid_vision_all_zero(self):
        state = _make_state()
        phi = self.enc.encode(state)
        # 처음 25개 (시야): 빈 셀 → 0.0
        assert all(v == pytest.approx(0.0) for v in phi[:25])

    def test_enemy_in_grid_encodes_negative(self):
        grid = _make_empty_grid()
        grid[2][3] = "bot_enemy"   # 오른쪽 인접 칸
        state = _make_state(grid=grid)
        phi = self.enc.encode(state)
        # flat index 13 (row 2, col 3) = -1.0
        assert phi[13] == pytest.approx(-1.0)

    def test_mineral_in_adj_flag_set(self):
        grid = _make_empty_grid()
        grid[2][3] = "mineral"    # 오른쪽 인접
        state = _make_state(grid=grid)
        phi = self.enc.encode(state)
        assert phi[32] == pytest.approx(1.0)  # mineral_in_adj

    def test_rare_mineral_flags(self):
        grid = _make_empty_grid()
        grid[1][2] = "mineral_rare"  # 위쪽 인접
        state = _make_state(grid=grid)
        phi = self.enc.encode(state)
        assert phi[33] == pytest.approx(1.0)  # mineral_rare_in_adj
        assert phi[32] == pytest.approx(1.0)  # mineral_in_adj도 세트
        assert phi[34] == pytest.approx(1.0)  # mineral_in_vision

    def test_enemy_in_vision_flag(self):
        grid = _make_empty_grid()
        grid[0][0] = "bot_enemy"   # 시야 내 비인접
        state = _make_state(grid=grid)
        phi = self.enc.encode(state)
        assert phi[31] == pytest.approx(1.0)  # enemy_in_vision
        assert phi[30] == pytest.approx(0.0)  # enemy_in_adj는 아님

    def test_energy_norm_clamped_to_1(self):
        state = _make_state(energy=9999)
        phi = self.enc.encode(state)
        assert phi[25] == pytest.approx(1.0)

    def test_bias_always_one(self):
        state = _make_state()
        phi = self.enc.encode(state)
        assert phi[37] == pytest.approx(1.0)

    def test_in_zone_flag_set_when_out_of_safe_area(self):
        # zone_boundary=10 → safe 10..89, pos_x=5는 위험 구역
        state = _make_state(pos_x=5, pos_y=50, zone_boundary=10)
        phi = self.enc.encode(state)
        assert phi[35] == pytest.approx(1.0)

    def test_in_zone_flag_clear_when_safe(self):
        state = _make_state(pos_x=50, pos_y=50, zone_boundary=10)
        phi = self.enc.encode(state)
        assert phi[35] == pytest.approx(0.0)

    def test_leaderboard_rank_norm(self):
        state = _make_state(
            bot_id="boss",
            leaderboard=[{"id": "boss", "rank": 5}],
        )
        phi = self.enc.encode(state)
        assert phi[36] == pytest.approx(0.5)  # 5 / 10 = 0.5


# ---------------------------------------------------------------------------
# 3. LinearQNet
# ---------------------------------------------------------------------------

class TestLinearQNet:
    def test_q_values_zero_weights(self):
        net = LinearQNet(_zero_weights())
        phi = [1.0] * N_FEATURES
        q = net.q_values(phi)
        assert all(v == pytest.approx(0.0) for v in q)
        assert len(q) == N_ACTIONS

    def test_q_values_single_weight(self):
        w = _zero_weights()
        w[0][IDX_MINE] = 2.0
        net = LinearQNet(w)
        phi = [0.0] * N_FEATURES
        phi[0] = 1.0
        q = net.q_values(phi)
        assert q[IDX_MINE] == pytest.approx(2.0)
        assert all(q[i] == pytest.approx(0.0) for i in range(N_ACTIONS) if i != IDX_MINE)

    def test_td_update_changes_weight(self):
        w = _zero_weights()
        net = LinearQNet(w)
        phi = [0.0] * N_FEATURES
        phi[0] = 1.0
        # target=1.0, current Q=0.0 → delta=1.0 → W[0][MINE] += alpha*1*1
        net.update(phi, IDX_MINE, target=1.0, alpha=ALPHA)
        assert net.W[0][IDX_MINE] == pytest.approx(ALPHA)

    def test_td_update_decreases_on_negative_error(self):
        w = _zero_weights()
        w[0][IDX_MINE] = 1.0
        net = LinearQNet(w)
        phi = [0.0] * N_FEATURES
        phi[0] = 1.0
        # target=0.0, current Q=1.0 → delta=-1 → weight 감소
        net.update(phi, IDX_MINE, target=0.0, alpha=ALPHA)
        assert net.W[0][IDX_MINE] < 1.0

    def test_update_only_affects_target_action_column(self):
        w = _zero_weights()
        net = LinearQNet(w)
        phi = [1.0] * N_FEATURES
        net.update(phi, IDX_MINE, target=10.0, alpha=ALPHA)
        for a in range(N_ACTIONS):
            if a != IDX_MINE:
                assert all(net.W[f][a] == pytest.approx(0.0) for f in range(N_FEATURES))

    def test_weights_deep_copy_on_init(self):
        w = _zero_weights()
        net = LinearQNet(w)
        w[0][0] = 999.0
        assert net.W[0][0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 4. StrategyRouter 하드 오버라이드 규칙
# ---------------------------------------------------------------------------

class TestStrategyRouter:
    def setup_method(self):
        import random
        self.rng = random.Random(0)
        self.router = StrategyRouter(self.rng, epsilon_override=0.0)  # 탐색 없음

    def _base_state(self, **kwargs) -> dict:
        return _make_state(**kwargs)

    def test_mine_when_on_mineral(self):
        state = self._base_state(energy=50)
        q = [0.0] * N_ACTIONS
        idx = self.router.select_action(q, state, tick=1, on_mineral=True)
        assert idx == IDX_MINE

    def test_no_mine_when_energy_too_low(self):
        """에너지가 MINE_COST 이하면 광물 위에 있어도 하드 MINE 하지 않음."""
        state = self._base_state(energy=ENERGY_MINE_COST - 1)
        q = [0.0] * N_ACTIONS
        idx = self.router.select_action(q, state, tick=1, on_mineral=True)
        assert idx != IDX_MINE

    def test_shield_when_energy_critical_no_adjacent_mineral(self):
        state = self._base_state(energy=ENERGY_CRITICAL)
        q = [0.0] * N_ACTIONS
        idx = self.router.select_action(q, state, tick=1, on_mineral=False)
        assert idx == IDX_SHIELD

    def test_move_toward_mineral_when_energy_critical(self):
        """위기 에너지지만 인접 광물 있으면 이동해야 함."""
        grid = _make_empty_grid()
        grid[1][2] = "mineral"   # 위쪽 인접 (MOVE_UP 방향)
        state = self._base_state(energy=ENERGY_CRITICAL, grid=grid)
        q = [0.0] * N_ACTIONS
        idx = self.router.select_action(q, state, tick=1, on_mineral=False)
        assert idx == IDX_MOVE_UP

    def test_zone_escape_toward_center(self):
        """자기장 안에 있으면 중앙 방향으로 이동."""
        # pos_x=2, safe_min=10 → 오른쪽으로 이동해야 함
        state = self._base_state(pos_x=2, pos_y=50, zone_boundary=10)
        q = [0.0] * N_ACTIONS
        idx = self.router.select_action(q, state, tick=50, on_mineral=False)
        assert idx == IDX_MOVE_RIGHT

    def test_attack_when_adjacent_enemy_high_energy(self):
        """에너지 여유 있고 오른쪽 인접에 적 → 오른쪽 공격."""
        grid = _make_empty_grid()
        grid[2][3] = "bot_enemy"
        state = self._base_state(energy=ENERGY_HIGH + 1, grid=grid)
        q = [0.0] * N_ACTIONS
        idx = self.router.select_action(q, state, tick=100, on_mineral=False)
        assert idx == IDX_ATTACK_RIGHT

    def test_attack_masked_when_no_enemy(self):
        """인접 칸에 적 없으면 공격 Q값이 마스킹(-10)으로 낮아져야 함.
        MOVE_UP Q=5.0 vs ATTACK_RIGHT Q=0.0-10=-10 → 이동 선택"""
        state = self._base_state(energy=100)
        q = [0.0] * N_ACTIONS
        q[IDX_MOVE_UP] = 5.0   # 이동이 적보다 높음
        # ATTACK_RIGHT 는 마스킹 -10.0 적용 → -10.0 으로 선택 안 됨
        idx = self.router.select_action(q, state, tick=1, on_mineral=False)
        assert idx != IDX_ATTACK_RIGHT

    def test_mine_masked_when_not_on_mineral(self):
        """광물 위에 없으면 MINE Q값이 마스킹(-8)으로 낮아져야 함.
        MOVE_UP Q=5.0 vs MINE Q=0.0-8=-8 → 이동 선택"""
        state = self._base_state(energy=100)
        q = [0.0] * N_ACTIONS
        q[IDX_MOVE_UP] = 5.0   # 이동이 MINE 보다 높음
        idx = self.router.select_action(q, state, tick=1, on_mineral=False)
        assert idx != IDX_MINE

    def test_epsilon_zero_returns_best_q(self):
        """epsilon=0이면 항상 조정된 Q값 최대 액션 반환."""
        state = self._base_state(energy=100)
        q = [0.0] * N_ACTIONS
        q[IDX_MOVE_UP] = 999.0
        idx = self.router.select_action(q, state, tick=1, on_mineral=False)
        assert idx == IDX_MOVE_UP


# ---------------------------------------------------------------------------
# 5. RewardCalculator
# ---------------------------------------------------------------------------

class TestRewardCalculator:
    def setup_method(self):
        self.calc = RewardCalculator()

    def test_positive_reward_on_score_increase(self):
        prev = _make_state(score=0.0, energy=100)
        curr = _make_state(score=10.0, energy=100)
        r = self.calc.compute(prev, curr, IDX_MINE)
        assert r > 0.0

    def test_negative_reward_on_energy_loss(self):
        prev = _make_state(score=0.0, energy=100)
        curr = _make_state(score=0.0, energy=50)
        r = self.calc.compute(prev, curr, IDX_STAY)
        assert r < 0.0

    def test_penalty_in_zone(self):
        prev = _make_state(score=0.0, energy=100, pos_x=50, pos_y=50, zone_boundary=0)
        # 자기장 boundary=20, pos_x=5 → 위험 구역
        curr = _make_state(score=0.0, energy=100, pos_x=5, pos_y=50, zone_boundary=20)
        r_zone = self.calc.compute(prev, curr, IDX_STAY)

        curr_safe = _make_state(score=0.0, energy=100, pos_x=50, pos_y=50, zone_boundary=20)
        r_safe = self.calc.compute(prev, curr_safe, IDX_STAY)
        assert r_zone < r_safe

    def test_stay_action_penalty(self):
        prev = _make_state(score=0.0, energy=100)
        curr = _make_state(score=0.0, energy=99)
        r_stay = self.calc.compute(prev, curr, IDX_STAY)
        r_move = self.calc.compute(prev, curr, IDX_MOVE_UP)
        assert r_stay < r_move

    def test_critical_energy_penalty(self):
        prev = _make_state(energy=100)
        curr_critical = _make_state(energy=ENERGY_CRITICAL)
        r_critical = self.calc.compute(prev, curr_critical, IDX_MOVE_UP)

        curr_ok = _make_state(energy=50)
        r_ok = self.calc.compute(prev, curr_ok, IDX_MOVE_UP)
        assert r_critical < r_ok


# ---------------------------------------------------------------------------
# 6. ExperienceBuffer
# ---------------------------------------------------------------------------

class TestExperienceBuffer:
    def test_push_and_len(self):
        buf = ExperienceBuffer(maxlen=10)
        phi = [0.0] * N_FEATURES
        for _ in range(5):
            buf.push(phi, IDX_MINE, 0.1, phi)
        assert len(buf) == 5

    def test_maxlen_overflow(self):
        buf = ExperienceBuffer(maxlen=3)
        phi = [0.0] * N_FEATURES
        for _ in range(10):
            buf.push(phi, IDX_MINE, 0.1, phi)
        assert len(buf) == 3

    def test_sample_returns_correct_count(self):
        buf = ExperienceBuffer(maxlen=50)
        phi = [0.0] * N_FEATURES
        for _ in range(20):
            buf.push(phi, IDX_MINE, 0.1, phi)
        samples = buf.sample(5)
        assert len(samples) == 5

    def test_sample_limited_by_buffer_size(self):
        buf = ExperienceBuffer(maxlen=50)
        phi = [0.0] * N_FEATURES
        buf.push(phi, IDX_MINE, 0.1, phi)
        samples = buf.sample(100)
        assert len(samples) == 1


# ---------------------------------------------------------------------------
# 7. RLBossBot 통합 — get_action() & 온라인 학습
# ---------------------------------------------------------------------------

class TestRLBossBotIntegration:
    def _make_boss(self, epsilon: float = 0.0) -> RLBossBot:
        return RLBossBot(
            bot_id="boss_rl",
            seed=0,
            weights_path=Path("/nonexistent_xyz.json"),
            epsilon_override=epsilon,
        )

    def test_get_action_returns_valid_string(self):
        boss = self._make_boss()
        state = _make_state()
        action = boss.get_action(state)
        assert action in [a.value for a in Action]

    def test_get_action_multiple_ticks_consistent(self):
        boss = self._make_boss()
        for tick in range(1, 10):
            state = _make_state(tick=tick)
            action = boss.get_action(state)
            assert isinstance(action, str)

    def test_weights_change_after_enough_ticks(self):
        """충분한 틱 후 TD 업데이트로 가중치가 바뀌어야 한다."""
        boss = self._make_boss(epsilon=0.0)
        initial_w = [row[:] for row in boss.get_weights()]

        # 11틱 이상 호출해야 버퍼가 차서 업데이트됨
        for tick in range(1, 20):
            state = _make_state(tick=tick, score=float(tick))
            boss.get_action(state)

        final_w = boss.get_weights()
        changed = any(
            final_w[f][a] != pytest.approx(initial_w[f][a])
            for f in range(N_FEATURES) for a in range(N_ACTIONS)
        )
        assert changed, "TD 업데이트 후 가중치가 전혀 안 바뀜"

    def test_mine_action_on_mineral_cell(self):
        """현재 칸에 광물이 있으면 MINE을 반환해야 한다 (하드 오버라이드)."""
        boss = self._make_boss(epsilon=0.0)
        # 첫 get_action 호출로 이동 방향 기억시키기
        grid = _make_empty_grid()
        grid[2][3] = "mineral"   # 오른쪽 인접
        state1 = _make_state(grid=grid, energy=80)
        boss.get_action(state1)  # MOVE_RIGHT 선택 → _on_mineral=True

        # 다음 틱: 광물 위에 있으므로 MINE
        grid2 = _make_empty_grid()
        grid2[2][2] = "mineral"   # 현재 위치 셀 (중앙)은 사실 grid가 상대적이므로
        state2 = _make_state(tick=2, energy=80)
        # _on_mineral 플래그가 True면 MINE 반환
        action = boss.get_action(state2)
        # 실제로 _on_mineral이 세트된 경우에만 MINE — 이미 이전 틱에서 세트됨
        assert action == Action.MINE.value

    def test_shield_when_energy_critical(self):
        boss = self._make_boss(epsilon=0.0)
        state = _make_state(energy=ENERGY_CRITICAL)
        action = boss.get_action(state)
        assert action == Action.SHIELD.value

    def test_spawn_position_in_center_region(self):
        import random as _random
        from src.arena.grid import Grid
        boss = self._make_boss()
        grid = Grid(DEFAULT_CONFIG, _random.Random(0))
        pos = boss.get_spawn_position(grid)
        assert pos is not None
        x, y = pos
        assert 35 <= x <= 65
        assert 35 <= y <= 65

    def test_full_game_runs_without_error(self):
        """보스봇 + 상대봇 1판 완주 — 예외 없이 끝나야 함."""
        boss = RLBossBot(bot_id="boss_rl", seed=0, weights_path=Path("/nonexistent_xyz.json"))
        opponents = [HerbivoreBot("herb_0", seed=1), MadDogBot("mad_0", seed=2)]
        engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=99)
        result = engine.run_full_game()
        assert result is not None
        assert result.rankings is not None


# ---------------------------------------------------------------------------
# 8. 다양한 상대 봇 조합 시나리오
# ---------------------------------------------------------------------------

class TestBossBotScenarios:
    """여러 상대 조합으로 보스봇 게임을 돌려보는 시나리오 테스트."""

    OPPONENTS_COMBOS = [
        [HerbivoreBot],
        [MadDogBot],
        [CamperBot],
        [HerbivoreBot, MadDogBot],
        [HerbivoreBot, CamperBot],
        [MadDogBot, CamperBot],
        [HerbivoreBot, MadDogBot, CamperBot],
        [HerbivoreBot, HerbivoreBot, MadDogBot, CamperBot],
    ]

    @pytest.mark.parametrize("opponent_classes", OPPONENTS_COMBOS)
    def test_boss_survives_at_least_one_tick(self, opponent_classes):
        """보스봇이 최소 1틱 이상 살아남아야 한다."""
        boss = RLBossBot(bot_id="boss_rl", seed=42, weights_path=Path("/nonexistent_xyz.json"))
        opponents = [cls(f"{cls.__name__}_{i}", seed=i) for i, cls in enumerate(opponent_classes)]
        engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=7)
        result = engine.run_full_game()

        boss_entry = next((e for e in result.rankings if e["id"] == "boss_rl"), None)
        assert boss_entry is not None
        assert boss_entry["survival_ticks"] >= 1

    @pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
    def test_boss_vs_full_lobby_multiple_seeds(self, seed):
        """다른 시드에서도 보스봇이 정상 동작해야 한다."""
        boss = RLBossBot(bot_id="boss_rl", seed=seed, weights_path=Path("/nonexistent_xyz.json"))
        opponents = [
            HerbivoreBot("h0", seed=seed + 10),
            MadDogBot("m0", seed=seed + 20),
            CamperBot("c0", seed=seed + 30),
        ]
        engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=seed)
        result = engine.run_full_game()
        assert len(result.rankings) >= 1

    def test_boss_score_above_zero_against_herbivores(self):
        """초식봇만 상대할 때 보스봇은 점수를 1점 이상 얻어야 한다."""
        boss = RLBossBot(bot_id="boss_rl", seed=42, weights_path=Path("/nonexistent_xyz.json"))
        opponents = [HerbivoreBot(f"h{i}", seed=i) for i in range(3)]
        engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=0)
        result = engine.run_full_game()

        boss_entry = next((e for e in result.rankings if e["id"] == "boss_rl"), None)
        assert boss_entry is not None
        assert boss_entry["final_score"] > 0.0


# ---------------------------------------------------------------------------
# 9. 훈련 개선 검증 — 10 에피소드 미니 훈련
# ---------------------------------------------------------------------------

class TestTrainingImprovement:
    def test_weights_diverge_after_training(self):
        """
        단일 보스 인스턴스로 5 에피소드 훈련 후 가중치가 초기값과 달라야 한다.
        (train_boss_bot.py 방식과 동일하게 같은 인스턴스 재사용)
        """
        import random as _random

        rng = _random.Random(0)
        boss = RLBossBot(
            bot_id="boss_rl",
            seed=0,
            weights_path=Path("/nonexistent_xyz.json"),
            epsilon_override=0.3,
        )
        initial_w = [row[:] for row in boss.get_weights()]

        for ep in range(5):
            ep_seed = rng.randint(0, 10000)
            opponents = [
                HerbivoreBot(f"h{ep}", seed=ep_seed + 1),
                MadDogBot(f"m{ep}", seed=ep_seed + 2),
            ]
            engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=ep_seed)
            engine.run_full_game()
            # train_boss_bot.py 방식: 같은 인스턴스 계속 사용 (가중치 누적)

        final_w = boss.get_weights()
        total_change = sum(
            abs(final_w[f][a] - initial_w[f][a])
            for f in range(N_FEATURES) for a in range(N_ACTIONS)
        )
        assert total_change > 0.01, f"가중치 총 변화량이 너무 작음: {total_change}"

    def test_weight_persistence_via_file(self, tmp_path):
        """저장 → 로드 후에도 학습된 가중치가 유지되어야 한다."""
        import random as _random

        rng = _random.Random(1)
        boss = RLBossBot(
            bot_id="boss_rl",
            seed=1,
            weights_path=Path("/nonexistent_xyz.json"),
            epsilon_override=0.3,
        )

        for ep in range(5):
            ep_seed = rng.randint(0, 10000)
            opponents = [MadDogBot(f"m{ep}", seed=ep_seed + 5)]
            engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=ep_seed)
            engine.run_full_game()

        save_path = tmp_path / "trained.json"
        boss.save_weights(save_path)

        boss2 = RLBossBot(bot_id="boss2", seed=99, weights_path=save_path)
        assert boss.get_weights() == boss2.get_weights()

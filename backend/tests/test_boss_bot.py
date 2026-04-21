"""
RLBossBot (DQN) 테스트 모음

범주:
  1. 초기화 / 체크포인트 저장·로드
  2. StateEncoder — 특징 벡터 정확성
  3. DQNetwork — 순전파 & 역전파
  4. ReplayBuffer
  5. RewardCalculator
  6. RLBossBot 통합 — get_action() + 온라인 학습
  7. 다양한 상대 봇 조합 시나리오
  8. 훈련 개선 검증
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pytest

from src.arena.config import DEFAULT_CONFIG
from src.arena.engine import GameEngine
from src.arena.types import Action

from bots.rl_boss_bot import (
    ACTIONS,
    ALPHA,
    BUFFER_SIZE,
    ENERGY_CRITICAL,
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
    MAX_TICKS,
    N_ACTIONS,
    N_FEATURES,
    N_HIDDEN,
    DQNetwork,
    ReplayBuffer,
    RewardCalculator,
    RLBossBot,
    StateEncoder,
)
from bots.herbivore import HerbivoreBot
from bots.mad_dog import MadDogBot
from bots.camper import CamperBot


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

_NONEXISTENT_PATH = Path("/tmp/_boss_bot_test_nonexistent_xyz.json")


def _make_empty_grid() -> list[list[str]]:
    return [["empty"] * 5 for _ in range(5)]


def _make_state(
    tick: int = 1,
    energy: int = 100,
    score: float = 0.0,
    pos_x: int = 50,
    pos_y: int = 50,
    zone_boundary: int = 0,
    grid: list[list[str]] | None = None,
    leaderboard: list[dict] | None = None,
    bot_id: str = "boss_rl",
) -> dict:
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


def _make_boss(epsilon: float = 0.0, seed: int = 0) -> RLBossBot:
    return RLBossBot(
        bot_id="boss_rl",
        seed=seed,
        weights_path=_NONEXISTENT_PATH,
        epsilon_override=epsilon,
    )


# ---------------------------------------------------------------------------
# 1. 초기화 / 체크포인트 저장·로드
# ---------------------------------------------------------------------------

class TestInitAndCheckpoint:
    def test_default_init(self):
        boss = _make_boss()
        assert boss.bot_id == "boss_rl"
        d = boss.get_weights()
        assert isinstance(d, dict)
        assert np.array(d["W1"]).shape == (N_FEATURES, N_HIDDEN)
        assert np.array(d["b1"]).shape == (N_HIDDEN,)
        assert np.array(d["W2"]).shape == (N_HIDDEN, N_ACTIONS)
        assert np.array(d["b2"]).shape == (N_ACTIONS,)

    def test_initial_weights_nonzero(self):
        """Xavier 초기화로 가중치는 전부 0이 아니어야 함."""
        boss = _make_boss()
        d = boss.get_weights()
        assert np.any(np.array(d["W1"]) != 0.0)
        assert np.any(np.array(d["W2"]) != 0.0)

    def test_set_and_get_weights_roundtrip(self):
        boss = _make_boss()
        d = boss.get_weights()
        d["W1"] = [[0.0] * N_HIDDEN for _ in range(N_FEATURES)]
        d["W1"][0][0] = 9.99
        boss.set_weights(d)
        got = boss.get_weights()
        assert got["W1"][0][0] == pytest.approx(9.99)

    def test_save_and_load_checkpoint(self, tmp_path):
        boss = _make_boss()
        d = boss.get_weights()
        d["W1"][5][3] = 1.234
        boss.set_weights(d)

        save_path = tmp_path / "weights.json"
        boss.save_weights(save_path)
        assert save_path.exists()

        boss2 = RLBossBot(bot_id="boss2", weights_path=save_path)
        assert boss2.get_weights()["W1"][5][3] == pytest.approx(1.234)

    def test_load_weights_returns_false_on_missing(self, tmp_path):
        boss = _make_boss()
        result = boss.load_weights(tmp_path / "nonexistent.json")
        assert result is False

    def test_saved_json_has_correct_schema(self, tmp_path):
        boss = _make_boss()
        save_path = tmp_path / "w.json"
        boss.save_weights(save_path)
        data = json.loads(save_path.read_text())
        assert data["n_features"] == N_FEATURES
        assert data["n_hidden"] == N_HIDDEN
        assert data["n_actions"] == N_ACTIONS
        assert "online" in data
        assert "target" in data


# ---------------------------------------------------------------------------
# 2. StateEncoder
# ---------------------------------------------------------------------------

class TestStateEncoder:
    def setup_method(self):
        self.enc = StateEncoder()

    def test_output_length(self):
        phi = self.enc.encode(_make_state())
        assert len(phi) == N_FEATURES

    def test_empty_grid_vision_all_zero(self):
        phi = self.enc.encode(_make_state())
        assert all(v == pytest.approx(0.0) for v in phi[:25])

    def test_enemy_in_grid_encodes_negative(self):
        grid = _make_empty_grid()
        grid[2][3] = "bot_enemy"
        phi = self.enc.encode(_make_state(grid=grid))
        # flat index = row * 5 + col = 2 * 5 + 3 = 13
        assert phi[13] == pytest.approx(-1.0)

    def test_mineral_in_adj_flag_set(self):
        grid = _make_empty_grid()
        grid[2][3] = "mineral"
        phi = self.enc.encode(_make_state(grid=grid))
        assert phi[32] == pytest.approx(1.0)  # mineral_in_adj

    def test_rare_mineral_flags(self):
        grid = _make_empty_grid()
        grid[1][2] = "mineral_rare"
        phi = self.enc.encode(_make_state(grid=grid))
        assert phi[33] == pytest.approx(1.0)  # mineral_rare_in_adj
        assert phi[32] == pytest.approx(1.0)  # mineral_in_adj
        assert phi[34] == pytest.approx(1.0)  # mineral_in_vision

    def test_enemy_in_vision_flag(self):
        grid = _make_empty_grid()
        grid[0][0] = "bot_enemy"
        phi = self.enc.encode(_make_state(grid=grid))
        assert phi[31] == pytest.approx(1.0)  # enemy_in_vision
        assert phi[30] == pytest.approx(0.0)  # enemy_in_adj

    def test_energy_norm_clamped_to_1(self):
        phi = self.enc.encode(_make_state(energy=9999))
        assert phi[25] == pytest.approx(1.0)

    def test_bias_always_one(self):
        phi = self.enc.encode(_make_state())
        assert phi[37] == pytest.approx(1.0)

    def test_in_zone_flag_set_when_out_of_safe_area(self):
        phi = self.enc.encode(_make_state(pos_x=5, pos_y=50, zone_boundary=10))
        assert phi[35] == pytest.approx(1.0)

    def test_in_zone_flag_clear_when_safe(self):
        phi = self.enc.encode(_make_state(pos_x=50, pos_y=50, zone_boundary=10))
        assert phi[35] == pytest.approx(0.0)

    def test_leaderboard_rank_norm(self):
        state = _make_state(
            bot_id="boss",
            leaderboard=[{"id": "boss", "rank": 5}],
        )
        phi = self.enc.encode(state)
        assert phi[36] == pytest.approx(0.5)  # 5 / 10


# ---------------------------------------------------------------------------
# 3. DQNetwork
# ---------------------------------------------------------------------------

class TestDQNetwork:
    def test_forward_output_shape(self):
        net = DQNetwork(seed=0)
        phi = np.zeros(N_FEATURES, dtype=np.float32)
        q = net.forward(phi)
        assert q.shape == (N_ACTIONS,)

    def test_forward_zero_input_equals_b2(self):
        """phi=0이면 은닉층도 0이므로 Q = b2 (초기값 0)."""
        net = DQNetwork(seed=0)
        phi = np.zeros(N_FEATURES, dtype=np.float32)
        q = net.forward(phi)
        assert np.allclose(q, net.b2)

    def test_update_single_changes_weights(self):
        net = DQNetwork(seed=0)
        phi = np.ones(N_FEATURES, dtype=np.float32)
        w2_before = net.W2.copy()
        net.update_single(phi, IDX_MINE, td_target=1.0, alpha=ALPHA)
        assert not np.allclose(net.W2, w2_before)

    def test_update_single_returns_td_error(self):
        net = DQNetwork(seed=0)
        phi = np.zeros(N_FEATURES, dtype=np.float32)
        # Q=b2[IDX_MINE]=0, target=1 → delta=1
        delta = net.update_single(phi, IDX_MINE, td_target=1.0, alpha=ALPHA)
        assert delta == pytest.approx(1.0, abs=1e-5)

    def test_update_batch_returns_loss(self):
        net = DQNetwork(seed=0)
        B = 4
        phis = np.ones((B, N_FEATURES), dtype=np.float32)
        actions = np.array([IDX_MINE] * B, dtype=np.int32)
        targets = np.ones(B, dtype=np.float32)
        loss = net.update_batch(phis, actions, targets, ALPHA)
        assert loss >= 0.0

    def test_copy_from_syncs_weights(self):
        a = DQNetwork(seed=0)
        b = DQNetwork(seed=1)
        assert not np.allclose(a.W1, b.W1)
        b.copy_from(a)
        assert np.allclose(a.W1, b.W1)
        assert np.allclose(a.W2, b.W2)

    def test_serialize_roundtrip(self):
        a = DQNetwork(seed=0)
        d = a.to_dict()
        b = DQNetwork(seed=99)
        b.from_dict(d)
        assert np.allclose(a.W1, b.W1)
        assert np.allclose(a.W2, b.W2)
        assert b.shape_ok()


# ---------------------------------------------------------------------------
# 4. ReplayBuffer
# ---------------------------------------------------------------------------

class TestReplayBuffer:
    def test_push_and_len(self):
        buf = ReplayBuffer(maxlen=10)
        phi = np.zeros(N_FEATURES, dtype=np.float32)
        for _ in range(5):
            buf.push(phi, IDX_MINE, 0.1, phi, False)
        assert len(buf) == 5

    def test_maxlen_overflow(self):
        buf = ReplayBuffer(maxlen=3)
        phi = np.zeros(N_FEATURES, dtype=np.float32)
        for _ in range(10):
            buf.push(phi, IDX_MINE, 0.1, phi, False)
        assert len(buf) == 3

    def test_sample_returns_correct_count(self):
        buf = ReplayBuffer(maxlen=50)
        phi = np.zeros(N_FEATURES, dtype=np.float32)
        for _ in range(20):
            buf.push(phi, IDX_MINE, 0.1, phi, False)
        samples = buf.sample(5)
        assert len(samples) == 5

    def test_sample_limited_by_buffer_size(self):
        buf = ReplayBuffer(maxlen=50)
        phi = np.zeros(N_FEATURES, dtype=np.float32)
        buf.push(phi, IDX_MINE, 0.1, phi, False)
        samples = buf.sample(100)
        assert len(samples) == 1

    def test_serialize_roundtrip(self):
        buf = ReplayBuffer(maxlen=10)
        phi = np.ones(N_FEATURES, dtype=np.float32)
        buf.push(phi, IDX_MINE, 0.5, phi, False)
        data = buf.to_list()

        buf2 = ReplayBuffer(maxlen=10)
        buf2.from_list(data)
        assert len(buf2) == 1


# ---------------------------------------------------------------------------
# 5. RewardCalculator
# ---------------------------------------------------------------------------

class TestRewardCalculator:
    def setup_method(self):
        self.calc = RewardCalculator()

    def test_positive_reward_on_score_increase(self):
        prev = _make_state(score=0.0, energy=100)
        curr = _make_state(score=10.0, energy=100)
        r = self.calc.compute_tick(prev, curr, IDX_MINE)
        assert r > 0.0

    def test_kill_reward_on_big_score_jump(self):
        prev = _make_state(score=0.0, energy=100)
        curr = _make_state(score=30.0, energy=100)  # score_delta=30 ≥ 25 → kill
        r = self.calc.compute_tick(prev, curr, IDX_ATTACK_RIGHT)
        assert r >= 10.0

    def test_negative_reward_on_energy_loss(self):
        prev = _make_state(score=0.0, energy=100)
        curr = _make_state(score=0.0, energy=50)
        r = self.calc.compute_tick(prev, curr, IDX_STAY)
        assert r < 0.0

    def test_penalty_in_zone(self):
        prev = _make_state(score=0.0, energy=100, pos_x=50, pos_y=50, zone_boundary=0)
        curr_danger = _make_state(score=0.0, energy=100, pos_x=5, pos_y=50, zone_boundary=20)
        curr_safe = _make_state(score=0.0, energy=100, pos_x=50, pos_y=50, zone_boundary=20)
        r_danger = self.calc.compute_tick(prev, curr_danger, IDX_STAY)
        r_safe = self.calc.compute_tick(prev, curr_safe, IDX_STAY)
        assert r_danger < r_safe

    def test_stay_action_penalty(self):
        prev = _make_state(score=0.0, energy=100)
        curr = _make_state(score=0.0, energy=99)
        r_stay = self.calc.compute_tick(prev, curr, IDX_STAY)
        r_move = self.calc.compute_tick(prev, curr, IDX_MOVE_UP)
        assert r_stay < r_move

    def test_critical_energy_penalty_is_stronger(self):
        prev = _make_state(energy=100)
        curr_critical = _make_state(energy=20)    # ≤ ENERGY_CRITICAL_THR
        curr_low = _make_state(energy=60)         # ≤ ENERGY_LOW_THR
        curr_ok = _make_state(energy=120)
        r_critical = self.calc.compute_tick(prev, curr_critical, IDX_MOVE_UP)
        r_low = self.calc.compute_tick(prev, curr_low, IDX_MOVE_UP)
        r_ok = self.calc.compute_tick(prev, curr_ok, IDX_MOVE_UP)
        assert r_critical < r_low < r_ok

    def test_episode_end_first_place_is_positive(self):
        r = RewardCalculator.compute_episode_end(rank=1, n_bots=4)
        assert r > 0.0

    def test_episode_end_last_place_is_negative(self):
        r = RewardCalculator.compute_episode_end(rank=4, n_bots=4)
        assert r < 0.0


# ---------------------------------------------------------------------------
# 6. RLBossBot 통합
# ---------------------------------------------------------------------------

class TestRLBossBotIntegration:
    def test_get_action_returns_valid_action(self):
        boss = _make_boss()
        action = boss.get_action(_make_state())
        assert action in [a.value for a in Action]

    def test_get_action_multiple_ticks(self):
        boss = _make_boss()
        for tick in range(1, 10):
            action = boss.get_action(_make_state(tick=tick))
            assert action in [a.value for a in Action]

    def test_shield_when_energy_critical(self):
        """ENERGY_CRITICAL 이하 + 인접 광물/적 없음 → 실드 하드코딩."""
        boss = _make_boss(epsilon=0.0)
        action = boss.get_action(_make_state(energy=ENERGY_CRITICAL))
        assert action == Action.SHIELD.value

    def test_zone_escape_toward_center(self):
        """자기장 안이면 중앙 방향으로 이동."""
        boss = _make_boss(epsilon=0.0)
        # pos_x=5, safe_min=10 → 오른쪽(x 증가) 방향 이동
        state = _make_state(pos_x=5, pos_y=50, zone_boundary=10, tick=80)
        action = boss.get_action(state)
        assert action == Action.MOVE_RIGHT.value

    def test_mine_after_moving_onto_mineral(self):
        """인접 광물로 이동한 다음 틱에는 광물 위에 있으므로 MINE (하드 오버라이드)."""
        boss = _make_boss(epsilon=0.0)
        # _on_mineral 플래그를 직접 세트 (guided vs Q-net 랜덤성 회피)
        boss._on_mineral = True
        action = boss.get_action(_make_state(tick=1, energy=100))
        assert action == Action.MINE.value

    def test_choose_spawn_returns_valid_position(self):
        boss = _make_boss()
        map_info = {
            "width": 100,
            "height": 100,
            "minerals": [
                {"x": 50, "y": 50, "rare": True},
                {"x": 20, "y": 30, "rare": False},
            ],
        }
        pos = boss.choose_spawn(map_info)
        assert pos is not None
        x, y = pos
        assert 0 <= x < 100
        assert 0 <= y < 100

    def test_full_game_runs_without_error(self):
        boss = RLBossBot(bot_id="boss_rl", seed=0, weights_path=_NONEXISTENT_PATH)
        opponents = [HerbivoreBot("herb_0", seed=1), MadDogBot("mad_0", seed=2)]
        engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=99)
        result = engine.run_full_game()
        assert result is not None
        assert result.rankings is not None

    def test_reset_for_episode_clears_tick_state(self):
        boss = _make_boss(epsilon=0.0)
        boss.get_action(_make_state())
        # reset 후 내부 상태 초기화
        boss.reset_for_episode()
        # 여전히 정상 동작해야 함
        action = boss.get_action(_make_state())
        assert action in [a.value for a in Action]


# ---------------------------------------------------------------------------
# 7. 상대 봇 조합 시나리오
# ---------------------------------------------------------------------------

class TestBossBotScenarios:
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
        boss = RLBossBot(bot_id="boss_rl", seed=42, weights_path=_NONEXISTENT_PATH)
        opponents = [cls(f"{cls.__name__}_{i}", seed=i)
                     for i, cls in enumerate(opponent_classes)]
        engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=7)
        result = engine.run_full_game()

        boss_entry = next((e for e in result.rankings if e["id"] == "boss_rl"), None)
        assert boss_entry is not None
        assert boss_entry["survival_ticks"] >= 1

    @pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
    def test_boss_vs_full_lobby_multiple_seeds(self, seed):
        boss = RLBossBot(bot_id="boss_rl", seed=seed, weights_path=_NONEXISTENT_PATH)
        opponents = [
            HerbivoreBot("h0", seed=seed + 10),
            MadDogBot("m0", seed=seed + 20),
            CamperBot("c0", seed=seed + 30),
        ]
        engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=seed)
        result = engine.run_full_game()
        assert len(result.rankings) >= 1

    def test_boss_score_above_zero_against_herbivores(self):
        boss = RLBossBot(bot_id="boss_rl", seed=42, weights_path=_NONEXISTENT_PATH)
        opponents = [HerbivoreBot(f"h{i}", seed=i) for i in range(3)]
        engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=0)
        result = engine.run_full_game()

        boss_entry = next((e for e in result.rankings if e["id"] == "boss_rl"), None)
        assert boss_entry is not None
        assert boss_entry["final_score"] > 0.0


# ---------------------------------------------------------------------------
# 8. 훈련 개선 검증
# ---------------------------------------------------------------------------

class TestTrainingImprovement:
    def test_weights_diverge_after_training(self):
        """여러 에피소드 훈련 후 online network 가중치가 초기값과 달라야 한다."""
        rng = random.Random(0)
        boss = RLBossBot(
            bot_id="boss_rl",
            seed=0,
            weights_path=_NONEXISTENT_PATH,
            epsilon_override=0.3,
        )
        initial_w1 = np.array(boss.get_weights()["W1"], dtype=np.float32).copy()

        # 여러 에피소드: 버퍼가 MIN_BUFFER_LEARN(500)을 넘어서야 실제 학습 발생
        for ep in range(6):
            ep_seed = rng.randint(0, 10000)
            opponents = [
                HerbivoreBot(f"h{ep}", seed=ep_seed + 1),
                MadDogBot(f"m{ep}", seed=ep_seed + 2),
            ]
            engine = GameEngine([boss] + opponents, config=DEFAULT_CONFIG, seed=ep_seed)
            engine.run_full_game()
            boss.on_episode_done(rank=1, n_bots=3)
            boss.reset_for_episode()

        final_w1 = np.array(boss.get_weights()["W1"], dtype=np.float32)
        total_change = float(np.sum(np.abs(final_w1 - initial_w1)))
        assert total_change > 0.01, f"가중치 변화량이 너무 작음: {total_change}"

    def test_weight_persistence_via_file(self, tmp_path):
        """저장 → 로드 후에도 학습된 가중치가 유지되어야 한다."""
        boss = _make_boss(epsilon=0.3, seed=1)

        # 몇 번 학습 스텝 유발 (리플레이 버퍼에 수동으로 채워 학습 발동)
        phi = np.ones(N_FEATURES, dtype=np.float32)
        for _ in range(600):  # MIN_BUFFER_LEARN=500 초과
            boss._buffer.push(phi, IDX_MINE, 0.1, phi, False)
        for _ in range(10):
            boss._learn()

        save_path = tmp_path / "trained.json"
        boss.save_weights(save_path)

        boss2 = RLBossBot(bot_id="boss2", seed=99, weights_path=save_path)

        w1_a = np.array(boss.get_weights()["W1"])
        w1_b = np.array(boss2.get_weights()["W1"])
        assert np.allclose(w1_a, w1_b)

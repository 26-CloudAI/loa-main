"""
RLBossBot — Deep Q-Network (DQN) 기반 보스 봇
=================================================

학습 알고리즘:
  DQN (Deep Q-Network) — Mnih et al. 2015 구조를 numpy로 직접 구현.
  - Online Network  : 행동 선택 + 역전파 학습
  - Target Network  : 안정적인 TD target 계산 (TARGET_UPDATE_FREQ마다 sync)
  - Experience Replay: 최근 BUFFER_SIZE개 경험 중 BATCH_SIZE개 랜덤 샘플

상태 벡터 (N_FEATURES = 43):
  - 시야 25개 : 5×5 grid 셀을 연속값으로 인코딩
  - 스칼라 18개:
      energy/1000, score/500, tick/200,
      left_margin/50, right_margin/50, top_margin/50, bottom_margin/50,  (zone 4방향 거리)
      dist_zone_center/100,
      enemy_in_adj, enemy_in_vision, nearest_enemy_energy/250,  (+ 에너지 정보)
      mineral_in_adj, mineral_rare_in_adj, mineral_in_vision,
      danger_zone, rank_norm, kills_norm, bias

액션 (N_ACTIONS = 19, 8방향 이동/공격)
"""

from __future__ import annotations

import json
import logging
import random
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np

from core.bot_interface import BotInterface
from core.types import Action

_DEFAULT_WEIGHTS_PATH = Path(__file__).parent / "trained_weights.json"

# ---------------------------------------------------------------------------
# 액션 상수
# ---------------------------------------------------------------------------

ACTIONS = list(Action)
N_ACTIONS = len(ACTIONS)

IDX_STAY               = ACTIONS.index(Action.STAY)
IDX_MOVE_UP            = ACTIONS.index(Action.MOVE_UP)
IDX_MOVE_DOWN          = ACTIONS.index(Action.MOVE_DOWN)
IDX_MOVE_LEFT          = ACTIONS.index(Action.MOVE_LEFT)
IDX_MOVE_RIGHT         = ACTIONS.index(Action.MOVE_RIGHT)
IDX_MOVE_UP_LEFT       = ACTIONS.index(Action.MOVE_UP_LEFT)
IDX_MOVE_UP_RIGHT      = ACTIONS.index(Action.MOVE_UP_RIGHT)
IDX_MOVE_DOWN_LEFT     = ACTIONS.index(Action.MOVE_DOWN_LEFT)
IDX_MOVE_DOWN_RIGHT    = ACTIONS.index(Action.MOVE_DOWN_RIGHT)
IDX_MINE               = ACTIONS.index(Action.MINE)
IDX_ATTACK_UP          = ACTIONS.index(Action.ATTACK_UP)
IDX_ATTACK_DOWN        = ACTIONS.index(Action.ATTACK_DOWN)
IDX_ATTACK_LEFT        = ACTIONS.index(Action.ATTACK_LEFT)
IDX_ATTACK_RIGHT       = ACTIONS.index(Action.ATTACK_RIGHT)
IDX_ATTACK_UP_LEFT     = ACTIONS.index(Action.ATTACK_UP_LEFT)
IDX_ATTACK_UP_RIGHT    = ACTIONS.index(Action.ATTACK_UP_RIGHT)
IDX_ATTACK_DOWN_LEFT   = ACTIONS.index(Action.ATTACK_DOWN_LEFT)
IDX_ATTACK_DOWN_RIGHT  = ACTIONS.index(Action.ATTACK_DOWN_RIGHT)
IDX_SHIELD             = ACTIONS.index(Action.SHIELD)

CELL_ENCODING: dict[str, float] = {
    "empty":        0.0,
    "mineral":      0.5,
    "mineral_rare": 1.0,
    "ME":           0.2,
    "bot_enemy":   -1.0,
    "wall":        -0.5,
    "zone":        -0.8,
}

MAX_TICKS = 400  # boss_battle_config: max_ticks=400

# 게임 상수 (config.py 동기화)
_ATTACK_DAMAGE  = 25    # CombatConfig.attack_damage
_ATTACK_COST    = 5     # ActionCost.attack
# 주의: types.py Bot.apply_damage는 shield 시 damage//2 적용.
#       config.shield_reduction=1.0은 현재 코드에서 미사용 (불일치).

# 에너지 임계값
ENERGY_CRITICAL  = 30   # 극위기: flee/라스트힛 강제
_LASTBIT_HP      = _ATTACK_DAMAGE  # 상대 에너지 이하면 한 방 처치

# 자기장 예측 (boss_battle_config 기준)
_ZONE_P2_START   = 151  # boss_battle_config: phase1_end=150
_ZONE_BUFFER     = 2    # 경계에서 N칸 이내 미리 중앙으로

# 광물 메모리 만료
_MIN_EXPIRE_TICKS = 80

# 인접 방향
_ADJ_DIRS = [
    (0,  -1, IDX_MOVE_UP,         IDX_ATTACK_UP),
    (0,   1, IDX_MOVE_DOWN,       IDX_ATTACK_DOWN),
    (-1,  0, IDX_MOVE_LEFT,       IDX_ATTACK_LEFT),
    (1,   0, IDX_MOVE_RIGHT,      IDX_ATTACK_RIGHT),
    (-1, -1, IDX_MOVE_UP_LEFT,    IDX_ATTACK_UP_LEFT),
    (1,  -1, IDX_MOVE_UP_RIGHT,   IDX_ATTACK_UP_RIGHT),
    (-1,  1, IDX_MOVE_DOWN_LEFT,  IDX_ATTACK_DOWN_LEFT),
    (1,   1, IDX_MOVE_DOWN_RIGHT, IDX_ATTACK_DOWN_RIGHT),
]
_CX, _CY = 2, 2
_ADJ_CELL_COORDS = frozenset((_CX + dx, _CY + dy) for dx, dy, _, _ in _ADJ_DIRS)
_MOVE_TO_DELTA: dict[int, tuple[int, int]] = {
    move_idx: (dx, dy) for dx, dy, move_idx, _ in _ADJ_DIRS
}

_DIAG_RATIO = 0.4


def _move_idx_toward(ddx: int, ddy: int) -> int:
    if ddx == 0 and ddy == 0:
        return IDX_STAY
    ax, ay = abs(ddx), abs(ddy)
    if ax > 0 and ay > 0 and min(ax, ay) / max(ax, ay) >= _DIAG_RATIO:
        if ddx > 0 and ddy < 0: return IDX_MOVE_UP_RIGHT
        if ddx < 0 and ddy < 0: return IDX_MOVE_UP_LEFT
        if ddx > 0 and ddy > 0: return IDX_MOVE_DOWN_RIGHT
        return IDX_MOVE_DOWN_LEFT
    if ax >= ay:
        return IDX_MOVE_RIGHT if ddx > 0 else IDX_MOVE_LEFT
    return IDX_MOVE_DOWN if ddy > 0 else IDX_MOVE_UP


# DQN 하이퍼파라미터
N_FEATURES        = 43
N_HIDDEN1         = 256   # B 트랙: torch 학습기와 구조 일치 (43→256→128→19)
N_HIDDEN2         = 128
ALPHA             = 0.001
GAMMA             = 0.95
BATCH_SIZE        = 64
BUFFER_SIZE       = 10000
TARGET_UPDATE_FREQ = 100
MIN_BUFFER_LEARN  = 500
EPSILON_START     = 1.0
EPSILON_MIN       = 0.05
EPSILON_DECAY     = 0.992
EXPLOIT_GUIDE_PROB = 0.25
GCS_UPLOAD_INTERVAL = 5

# numpy 학습 deprecate flag (B 트랙: torch 학습기 train_boss_parallel.py 만 사용)
# True 로 바꾸면 update_batch 가 NotImplementedError 발생.
# 서빙·평가 시에는 _NUMPY_TRAINING_ENABLED=False 유지 → _learn() no-op.
_NUMPY_TRAINING_ENABLED = False


# ---------------------------------------------------------------------------
# DQNetwork — numpy 3층 MLP (43 → 256 → 128 → 19)
# torch 학습기와 동일 구조. 학습은 torch 가 담당, 여기는 추론 전용.
# 가중치 변환: scripts/tools/convert_torch_to_numpy.py
# ---------------------------------------------------------------------------

class DQNetwork:
    def __init__(self, seed: Optional[int] = None):
        rng = np.random.default_rng(seed)
        # He init (ReLU)
        self.W1 = rng.standard_normal((N_FEATURES, N_HIDDEN1)).astype(np.float32) \
                  * np.sqrt(2.0 / N_FEATURES)
        self.b1 = np.zeros(N_HIDDEN1, dtype=np.float32)
        self.W2 = rng.standard_normal((N_HIDDEN1, N_HIDDEN2)).astype(np.float32) \
                  * np.sqrt(2.0 / N_HIDDEN1)
        self.b2 = np.zeros(N_HIDDEN2, dtype=np.float32)
        self.W3 = rng.standard_normal((N_HIDDEN2, N_ACTIONS)).astype(np.float32) \
                  * np.sqrt(2.0 / N_HIDDEN2)
        self.b3 = np.zeros(N_ACTIONS, dtype=np.float32)

    def forward(self, phi: np.ndarray) -> np.ndarray:
        h1 = np.maximum(0.0, phi @ self.W1 + self.b1)
        h2 = np.maximum(0.0, h1  @ self.W2 + self.b2)
        return h2 @ self.W3 + self.b3

    def update_batch(self, phis: np.ndarray, actions: np.ndarray,
                     td_targets: np.ndarray, alpha: float) -> float:
        """numpy 학습은 B 트랙에서 deprecate.
        torch 학습기(train_boss_parallel.py)가 학습 → convert_torch_to_numpy 로 변환."""
        if _NUMPY_TRAINING_ENABLED:
            raise NotImplementedError(
                "numpy 학습은 deprecate됨. 3층 MLP backprop 필요 시 직접 구현하거나 "
                "torch 학습기(train_boss_parallel.py)를 사용하세요."
            )
        # 서빙·평가 컨텍스트: 호출되어도 조용히 통과 (loss=0 반환)
        return 0.0

    def copy_from(self, other: "DQNetwork") -> None:
        self.W1 = other.W1.copy()
        self.b1 = other.b1.copy()
        self.W2 = other.W2.copy()
        self.b2 = other.b2.copy()
        self.W3 = other.W3.copy()
        self.b3 = other.b3.copy()

    def to_dict(self) -> dict:
        return {
            "W1": self.W1.tolist(), "b1": self.b1.tolist(),
            "W2": self.W2.tolist(), "b2": self.b2.tolist(),
            "W3": self.W3.tolist(), "b3": self.b3.tolist(),
        }

    def from_dict(self, d: dict) -> None:
        self.W1 = np.array(d["W1"], dtype=np.float32)
        self.b1 = np.array(d["b1"], dtype=np.float32)
        self.W2 = np.array(d["W2"], dtype=np.float32)
        self.b2 = np.array(d["b2"], dtype=np.float32)
        self.W3 = np.array(d["W3"], dtype=np.float32)
        self.b3 = np.array(d["b3"], dtype=np.float32)

    def shape_ok(self) -> bool:
        return (self.W1.shape == (N_FEATURES, N_HIDDEN1)
                and self.b1.shape == (N_HIDDEN1,)
                and self.W2.shape == (N_HIDDEN1, N_HIDDEN2)
                and self.b2.shape == (N_HIDDEN2,)
                and self.W3.shape == (N_HIDDEN2, N_ACTIONS)
                and self.b3.shape == (N_ACTIONS,))


# ---------------------------------------------------------------------------
# StateEncoder — 43 features
# ---------------------------------------------------------------------------

class StateEncoder:
    """게임 state를 N_FEATURES=43 특징 벡터로 변환."""

    def encode(self, state: dict) -> np.ndarray:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        tick = state["tick"]
        safe_min_x, safe_min_y, safe_max_x, safe_max_y = state["zone_bounds"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        score = my["score"]
        kills = my.get("kills", 0)
        leaderboard = state.get("leaderboard", [])
        other_bots = state.get("other_bots", [])

        # ── 시야 인코딩 (25) ────────────────────────────────────────────
        vision_feats: list[float] = []
        enemy_in_adj = mineral_in_adj = mineral_rare_in_adj = 0.0
        enemy_in_vision = mineral_in_vision = 0.0

        for gy in range(5):
            for gx in range(5):
                cell = grid[gy][gx]
                vision_feats.append(CELL_ENCODING.get(cell, 0.0))
                if gy == _CY and gx == _CX:
                    continue
                is_adj = (gx, gy) in _ADJ_CELL_COORDS
                if cell == "bot_enemy":
                    enemy_in_vision = 1.0
                    if is_adj:
                        enemy_in_adj = 1.0
                elif cell == "mineral_rare":
                    mineral_in_vision = 1.0
                    if is_adj:
                        mineral_rare_in_adj = 1.0
                        mineral_in_adj = 1.0
                elif cell == "mineral":
                    mineral_in_vision = 1.0
                    if is_adj:
                        mineral_in_adj = 1.0

        # ── zone 정보 ───────────────────────────────────────────────────
        # 경계까지 거리(4방향) — zone 방향 정보 제공
        left_margin   = max(0, pos_x - safe_min_x)
        right_margin  = max(0, safe_max_x - pos_x)
        top_margin    = max(0, pos_y - safe_min_y)
        bottom_margin = max(0, safe_max_y - pos_y)
        zone_cx = (safe_min_x + safe_max_x) // 2
        zone_cy = (safe_min_y + safe_max_y) // 2
        dist_zone_center = abs(pos_x - zone_cx) + abs(pos_y - zone_cy)
        danger_zone = 1.0 if (
            pos_x < safe_min_x or pos_x > safe_max_x
            or pos_y < safe_min_y or pos_y > safe_max_y
        ) else 0.0

        # ── 시야 내 가장 가까운 적 에너지 ─────────────────────────────
        nearest_enemy_energy = 0.0
        if other_bots:
            nearest = min(
                other_bots,
                key=lambda b: abs(b["position"][0] - pos_x) + abs(b["position"][1] - pos_y),
            )
            nearest_enemy_energy = min(nearest["energy"] / 250.0, 1.0)

        # ── rank 정규화 ─────────────────────────────────────────────────
        # state["my_bot"] 키는 "bot_id" — "id"로 조회하면 항상 ""가 되어
        # 리더보드 매칭이 실패하는 버그를 수정한다.
        my_id = my.get("bot_id", my.get("id", ""))
        rank_norm = 1.0
        for entry in leaderboard:
            if entry.get("id") == my_id or entry.get("bot_id") == my_id:
                rank_norm = min(entry.get("rank", len(leaderboard)) / 10.0, 1.0)
                break

        # ── 스칼라 18개 ─────────────────────────────────────────────────
        scalar_feats = [
            min(energy / 1000.0, 1.0),              # max_energy 기준 정규화
            min(score / 500.0, 1.0),
            tick / MAX_TICKS,
            min(left_margin   / 50.0, 1.0),         # zone 4방향 거리
            min(right_margin  / 50.0, 1.0),
            min(top_margin    / 50.0, 1.0),
            min(bottom_margin / 50.0, 1.0),
            min(dist_zone_center / 100.0, 1.0),     # zone 중앙까지 거리
            enemy_in_adj,
            enemy_in_vision,
            nearest_enemy_energy,                    # 가장 가까운 적 에너지
            mineral_in_adj,
            mineral_rare_in_adj,
            mineral_in_vision,
            danger_zone,                             # zone 밖이면 1.0
            rank_norm,
            min(kills / 5.0, 1.0),                  # 킬 수 정규화
            1.0,                                     # bias
        ]

        return np.array(vision_feats + scalar_feats, dtype=np.float32)


# ---------------------------------------------------------------------------
# ReplayBuffer
# ---------------------------------------------------------------------------

class ReplayBuffer:
    def __init__(self, maxlen: int = BUFFER_SIZE):
        self._buf: deque[tuple] = deque(maxlen=maxlen)

    def push(self, phi, action, reward, phi_next, done):
        self._buf.append((phi, action, reward, phi_next, done))

    def sample(self, n: int) -> list[tuple]:
        return random.sample(self._buf, min(n, len(self._buf)))

    def __len__(self) -> int:
        return len(self._buf)

    def to_list(self) -> list:
        return [
            [phi.tolist(), action, reward, phi_next.tolist(), done]
            for phi, action, reward, phi_next, done in self._buf
        ]

    def from_list(self, data: list) -> None:
        self._buf.clear()
        for phi_l, action, reward, phi_next_l, done in data:
            self._buf.append((
                np.array(phi_l, dtype=np.float32),
                action, reward,
                np.array(phi_next_l, dtype=np.float32),
                done,
            ))


# ---------------------------------------------------------------------------
# RewardCalculator
# ---------------------------------------------------------------------------

class RewardCalculator:
    """
    보상 설계 (v4, 2026-05-26):
      - 킬 (kill_delta)       : +100.0 × delta  (직접 kills 필드 사용)
      - 일반 채굴 (score_delta): +0.15 / 점     (v3 0.3 → 반감, mining 편향 완화)
      - 에너지 회복           : +0.02 / 에너지
      - 에너지 위험           : -1.0 (LOW) / -3.0 (CRITICAL)
      - 자기장 내             : -4.0 / 틱
      - 유효 이동 (zone 안)   : +0.1
      - STAY                  : -0.4
      - 헛 SHIELD (적 미인접) : -0.5
      - 에피소드 순위         : 1위 +150 / 2위 +15 / 3위 -10 / 4위+ -20×(rank-3)
                                (v3 1위 +50 → +150: top2 편향 해소, win 추구 강화)
    """

    ENERGY_LOW_THR      = 80
    ENERGY_CRITICAL_THR = 40

    def compute_tick(self, prev_state: dict, curr_state: dict,
                     action_idx: int) -> float:
        prev_my = prev_state["my_bot"]
        curr_my = curr_state["my_bot"]
        safe_min_x, safe_min_y, safe_max_x, safe_max_y = curr_state["zone_bounds"]
        cx, cy = curr_my["position"]
        reward = 0.0

        # ── 킬 보상 (kill_delta 직접 사용, 휴리스틱 폴백) ──────────────
        kill_delta = curr_my.get("kills", 0) - prev_my.get("kills", 0)
        if kill_delta > 0:
            reward += 100.0 * kill_delta
        else:
            score_delta = curr_my["score"] - prev_my["score"]
            if score_delta >= 25:
                reward += 100.0  # kill 휴리스틱
            elif score_delta > 0:
                reward += score_delta * 0.15

        # ── 에너지 변화 ────────────────────────────────────────────────
        energy_delta = curr_my["energy"] - prev_my["energy"]
        reward += energy_delta * 0.02

        # ── 에너지 위험 패널티 ─────────────────────────────────────────
        e = curr_my["energy"]
        if e <= self.ENERGY_CRITICAL_THR:
            reward -= 3.0
        elif e <= self.ENERGY_LOW_THR:
            reward -= 1.0

        # ── 자기장 내 패널티 ────────────────────────────────────────────
        in_zone = (safe_min_x <= cx <= safe_max_x and safe_min_y <= cy <= safe_max_y)
        if not in_zone:
            reward -= 4.0

        # ── 이동/정체 보상 ──────────────────────────────────────────────
        if action_idx in _MOVE_TO_DELTA:
            # zone 안에서만 이동 보상 (zone 밖 도망은 보상 없음)
            if in_zone:
                reward += 0.1
        elif action_idx == IDX_STAY:
            reward -= 0.4

        # ── 헛 SHIELD 패널티 (적 인접 없는데 SHIELD) ────────────────────
        if action_idx == IDX_SHIELD:
            prev_grid = prev_state["vision"]["grid"]
            has_adj_enemy = any(
                prev_grid[_CY + dy][_CX + dx] == "bot_enemy"
                for dx, dy, _, _ in _ADJ_DIRS
            )
            if not has_adj_enemy:
                reward -= 0.5

        return reward

    @staticmethod
    def compute_episode_end(rank: int, n_bots: int) -> float:
        if rank == 1:
            return 150.0
        # n=2 환경(boss_mode_solo)에서 rank=2 는 꼴찌 = 패배. 강한 패널티.
        if n_bots == 2:
            return -50.0
        table = {2: 15.0, 3: -10.0}
        return table.get(rank, -20.0 * (rank - 3))


# ---------------------------------------------------------------------------
# RLBossBot
# ---------------------------------------------------------------------------

class RLBossBot(BotInterface):
    """
    DQN 기반 보스 봇.
    에피소드 간 학습 지속:
      - 같은 인스턴스 유지, reset_for_episode()로 틱 상태만 초기화
      - 가중치·버퍼·epsilon은 에피소드 간 유지
    """

    def __init__(
        self,
        bot_id: str,
        seed: Optional[int] = None,
        weights_path=None,
        epsilon_override: Optional[float] = None,
    ):
        self._bot_id = bot_id
        self._rng    = random.Random(seed)
        self._encoder = StateEncoder()
        self._reward_calc = RewardCalculator()

        self._online = DQNetwork(seed=seed)
        self._target = DQNetwork(seed=seed)
        self._target.copy_from(self._online)
        self._buffer = ReplayBuffer(BUFFER_SIZE)

        self._step_count    = 0
        self._episode_count = 0

        self._epsilon = epsilon_override if epsilon_override is not None \
                        else EPSILON_START
        self._epsilon_override = epsilon_override

        self._prev_phi:        Optional[np.ndarray] = None
        self._prev_action_idx: Optional[int]        = None
        self._prev_state:      Optional[dict]       = None
        self._on_mineral:      bool                 = False

        # 광물 메모리: {(x, y): (cell_type, last_seen_tick)}
        self._mineral_memory: dict[tuple[int, int], tuple[str, int]] = {}

        load_path = Path(weights_path) if weights_path is not None \
                    else _DEFAULT_WEIGHTS_PATH
        if load_path.exists():
            self._load_checkpoint(load_path)

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        """희귀 광물 인접 칸에 스폰. 광물 정보를 메모리에 미리 저장(tick=0)."""
        w = map_info.get("width", 100)
        h = map_info.get("height", 100)
        minerals = map_info.get("minerals", [])

        for m in minerals:
            cell_type = "mineral_rare" if m["rare"] else "mineral"
            self._mineral_memory[(m["x"], m["y"])] = (cell_type, 0)

        rare = [(m["x"], m["y"]) for m in minerals if m["rare"]]
        if rare:
            tx, ty = self._rng.choice(rare)
            offsets = [(1, 0), (-1, 0), (0, 1), (0, -1)]
            self._rng.shuffle(offsets)
            for dx, dy in offsets:
                nx, ny = tx + dx, ty + dy
                if 0 <= nx < w and 0 <= ny < h:
                    return (nx, ny)
            return (tx, ty)

        return (
            self._rng.randint(w // 2 - 15, w // 2 + 15),
            self._rng.randint(h // 2 - 15, h // 2 + 15),
        )

    # -----------------------------------------------------------------------
    # 핵심 의사결정
    # -----------------------------------------------------------------------

    def get_action(self, state: dict) -> str:
        my     = state["my_bot"]
        pos_x, pos_y = my["position"]
        grid   = state["vision"]["grid"]
        energy = my["energy"]
        tick   = state.get("tick", 0)
        other_bots = state.get("other_bots", [])
        safe_min_x, safe_min_y, safe_max_x, safe_max_y = state["zone_bounds"]

        # ── 광물 메모리 업데이트 (stale 만료 포함) ─────────────────────
        for gy in range(5):
            for gx in range(5):
                mx  = pos_x + (gx - _CX)
                my_y = pos_y + (gy - _CY)
                cell = grid[gy][gx]
                if cell in ("mineral", "mineral_rare"):
                    self._mineral_memory[(mx, my_y)] = (cell, tick)
                elif cell == "empty":
                    self._mineral_memory.pop((mx, my_y), None)
        # 오래된 기억 만료
        self._mineral_memory = {
            k: v for k, v in self._mineral_memory.items()
            if tick - v[1] <= _MIN_EXPIRE_TICKS
        }

        phi = self._encoder.encode(state)

        # ── TD 업데이트 ──────────────────────────────────────────────────
        if self._prev_state is not None and self._prev_phi is not None:
            reward = self._reward_calc.compute_tick(
                self._prev_state, state, self._prev_action_idx or IDX_STAY
            )
            self._buffer.push(
                self._prev_phi,
                self._prev_action_idx or IDX_STAY,
                reward,
                phi,
                False,
            )
            self._learn()

        # ── 하드코딩 규칙 ────────────────────────────────────────────────

        # 1. 자기장 탈출 / 예측 이동 (phase2+ 경계 버퍼)
        in_danger = (
            pos_x < safe_min_x or pos_x > safe_max_x
            or pos_y < safe_min_y or pos_y > safe_max_y
        )
        if not in_danger and tick >= _ZONE_P2_START:
            buf = _ZONE_BUFFER
            if (pos_x - safe_min_x < buf or safe_max_x - pos_x < buf or
                    pos_y - safe_min_y < buf or safe_max_y - pos_y < buf):
                in_danger = True

        if in_danger:
            action_idx = self._toward_safe(
                pos_x, pos_y, safe_min_x, safe_max_x, safe_min_y, safe_max_y
            )

        # 2. 에너지 극위기 → 라스트힛 or flee (SHIELD 대신)
        elif energy <= ENERGY_CRITICAL:
            lastbit = self._lastbit_idx(grid, pos_x, pos_y, energy, other_bots)
            if lastbit is not None:
                action_idx = lastbit
            elif self._adj_enemy_exists(grid):
                action_idx = self._flee_idx(
                    grid, pos_x, pos_y,
                    safe_min_x, safe_max_x, safe_min_y, safe_max_y
                )
            else:
                # 인접 적 없으면 가까운 광물로 이동, 없으면 STAY
                action_idx = self._emergency_mine_idx(grid, pos_x, pos_y)

        # 3. 발밑 광물 강제 채굴 (라스트힛 기회 없을 때만)
        elif self._on_mineral:
            lastbit = self._lastbit_idx(grid, pos_x, pos_y, energy, other_bots)
            if lastbit is not None:
                action_idx = lastbit
            else:
                action_idx = IDX_MINE

        # 4. 나머지 → DQN
        else:
            action_idx = self._select_dqn(
                phi, grid, pos_x, pos_y,
                safe_min_x, safe_max_x, safe_min_y, safe_max_y,
            )

        # 다음 칸 광물 있으면 기억 (다음 틱 MINE 예약)
        if action_idx in _MOVE_TO_DELTA:
            dx, dy = _MOVE_TO_DELTA[action_idx]
            target_cell = grid[_CY + dy][_CX + dx]
            self._on_mineral = target_cell in ("mineral", "mineral_rare")
        else:
            self._on_mineral = False

        self._prev_state      = state
        self._prev_phi        = phi
        self._prev_action_idx = action_idx

        return ACTIONS[action_idx]

    # -----------------------------------------------------------------------
    # 전투 헬퍼
    # -----------------------------------------------------------------------

    def _adj_enemy_exists(self, grid: list) -> bool:
        return any(
            grid[_CY + dy][_CX + dx] == "bot_enemy"
            for dx, dy, _, _ in _ADJ_DIRS
        )

    def _lastbit_idx(
        self, grid: list, pos_x: int, pos_y: int,
        energy: int, other_bots: list
    ) -> Optional[int]:
        """인접 적 중 한 방에 처치 가능한 적 공격 인덱스. 없으면 None.
        engine은 ATTACK_COST 차감 후 energy<=0이면 사망 처리하면서 공격을
        취소한다. 따라서 공격이 실제로 적중하려면 energy > ATTACK_COST가
        필요하다 (>= 가 아니라 >)."""
        if energy <= _ATTACK_COST:
            return None
        pos_to_e = {
            (b["position"][0], b["position"][1]): b["energy"]
            for b in other_bots
        }
        for dx, dy, _, atk_idx in _ADJ_DIRS:
            if grid[_CY + dy][_CX + dx] == "bot_enemy":
                e = pos_to_e.get((pos_x + dx, pos_y + dy), 999)
                if e <= _LASTBIT_HP:
                    return atk_idx
        return None

    def _flee_idx(
        self, grid: list, pos_x: int, pos_y: int,
        min_x: int, max_x: int, min_y: int, max_y: int
    ) -> int:
        """인접 적에게서 zone 안으로 이탈하는 이동 인덱스."""
        for dx, dy, move_idx, _ in _ADJ_DIRS:
            if grid[_CY + dy][_CX + dx] == "bot_enemy":
                flee_dx, flee_dy = -dx, -dy
                nx, ny = pos_x + flee_dx, pos_y + flee_dy
                if min_x <= nx <= max_x and min_y <= ny <= max_y:
                    return _move_idx_toward(flee_dx, flee_dy)
                # zone 탈출 위험 → 중앙 방향
                cx = (min_x + max_x) // 2
                cy = (min_y + max_y) // 2
                return _move_idx_toward(cx - pos_x, cy - pos_y)
        return IDX_STAY

    def _emergency_mine_idx(self, grid: list, pos_x: int, pos_y: int) -> int:
        """에너지 위기 시 가장 가까운 광물로 이동. 없으면 STAY."""
        # 발밑
        if grid[_CY][_CX] in ("mineral", "mineral_rare"):
            return IDX_MINE
        # 인접
        for dx, dy, move_idx, _ in _ADJ_DIRS:
            if grid[_CY + dy][_CX + dx] in ("mineral", "mineral_rare"):
                return move_idx
        # 시야 내 가장 가까운
        best_dist, best_idx = 999, IDX_STAY
        for gy in range(5):
            for gx in range(5):
                if grid[gy][gx] in ("mineral", "mineral_rare"):
                    d = abs(gx - _CX) + abs(gy - _CY)
                    if d < best_dist:
                        best_dist = d
                        best_idx = _move_idx_toward(gx - _CX, gy - _CY)
        if best_idx != IDX_STAY:
            return best_idx
        # 기억 속 광물
        if self._mineral_memory:
            closest = min(
                self._mineral_memory,
                key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y),
            )
            return _move_idx_toward(closest[0] - pos_x, closest[1] - pos_y)
        return IDX_STAY

    # -----------------------------------------------------------------------
    # DQN 행동 선택
    # -----------------------------------------------------------------------

    def _select_dqn(
        self,
        phi: np.ndarray,
        grid: list,
        pos_x: int, pos_y: int,
        min_x: int, max_x: int,
        min_y: int, max_y: int,
    ) -> int:
        if self._rng.random() < self._epsilon:
            if self._rng.random() < 0.70:
                guided = self._guided_action(grid, pos_x, pos_y, min_x, max_x, min_y, max_y)
                if guided is not None:
                    return guided
            return self._rng.choice(self._valid_actions(grid))

        if self._rng.random() < EXPLOIT_GUIDE_PROB:
            guided = self._guided_action(grid, pos_x, pos_y, min_x, max_x, min_y, max_y)
            if guided is not None:
                return guided

        q = self._online.forward(phi).copy()
        # invalid action 마스킹
        for dx, dy, _, attack_idx in _ADJ_DIRS:
            if grid[_CY + dy][_CX + dx] != "bot_enemy":
                q[attack_idx] -= 1e6
        if not self._on_mineral:
            q[IDX_MINE] -= 1e6

        return int(np.argmax(q))

    def _guided_action(
        self, grid: list,
        pos_x: int, pos_y: int,
        min_x: int, max_x: int,
        min_y: int, max_y: int,
    ) -> Optional[int]:
        """도메인 지식 기반 탐색 행동."""
        adj = self._adj_cells(grid)

        # 인접 rare mineral 이동
        for dx, dy, move_idx, _, cell in adj:
            if cell == "mineral_rare":
                return move_idx

        # 인접 적 공격 (80% 확률)
        if self._rng.random() < 0.8:
            for dx, dy, _, attack_idx, cell in adj:
                if cell == "bot_enemy":
                    return attack_idx

        # 시야 내 광물 방향
        best, best_score = None, float("inf")
        for gy in range(5):
            for gx in range(5):
                cell = grid[gy][gx]
                if cell not in ("mineral", "mineral_rare"):
                    continue
                ddx, ddy = gx - _CX, gy - _CY
                dist = abs(ddx) + abs(ddy)
                if dist == 0:
                    continue
                prio = dist - (2 if cell == "mineral_rare" else 0)
                if prio < best_score:
                    best_score = prio
                    best = (ddx, ddy)
        if best is not None:
            return _move_idx_toward(*best)

        # 메모리 광물 방향 (zone 안 광물만)
        if self._mineral_memory:
            mem_best, mem_score = None, float("inf")
            for (mx, my_c), (cell_type, _) in self._mineral_memory.items():
                # zone 밖 광물 추적 방지
                if not (min_x <= mx <= max_x and min_y <= my_c <= max_y):
                    continue
                dist = abs(mx - pos_x) + abs(my_c - pos_y)
                if dist == 0:
                    continue
                prio = dist - (3 if cell_type == "mineral_rare" else 0)
                if prio < mem_score:
                    mem_score = prio
                    mem_best = (mx - pos_x, my_c - pos_y)
            if mem_best is not None:
                return _move_idx_toward(*mem_best)

        return None

    def _valid_actions(self, grid: list) -> list[int]:
        valid = [
            IDX_STAY,
            IDX_MOVE_UP, IDX_MOVE_DOWN, IDX_MOVE_LEFT, IDX_MOVE_RIGHT,
            IDX_MOVE_UP_LEFT, IDX_MOVE_UP_RIGHT,
            IDX_MOVE_DOWN_LEFT, IDX_MOVE_DOWN_RIGHT,
            IDX_SHIELD,
        ]
        for dx, dy, _, attack_idx, cell in self._adj_cells(grid):
            if cell == "bot_enemy":
                valid.append(attack_idx)
        if self._on_mineral:
            valid.append(IDX_MINE)
        return valid

    @staticmethod
    def _adj_cells(grid: list) -> list[tuple]:
        return [
            (dx, dy, move_idx, attack_idx, grid[_CY + dy][_CX + dx])
            for dx, dy, move_idx, attack_idx in _ADJ_DIRS
        ]

    # -----------------------------------------------------------------------
    # 학습
    # -----------------------------------------------------------------------

    def _learn(self) -> None:
        # B 트랙: numpy 학습 deprecate. 서빙·평가 시 매 step 호출되어도 no-op.
        # 학습은 torch 학습기(train_boss_parallel.py)가 담당,
        # 결과를 convert_torch_to_numpy 로 변환하여 trained_weights.json 갱신.
        if not _NUMPY_TRAINING_ENABLED:
            return
        if len(self._buffer) < MIN_BUFFER_LEARN:
            return
        # 옛 2층 backprop 코드는 3층 구조와 호환되지 않으므로 여기서 raise.
        # (실제로 도달하려면 _NUMPY_TRAINING_ENABLED=True 명시 + numpy 학습 재구현 필요)
        raise NotImplementedError(
            "numpy 학습 backprop 미구현 (3층 MLP). "
            "torch 학습기(train_boss_parallel.py)를 사용하세요."
        )

    # -----------------------------------------------------------------------
    # 에피소드 관리
    # -----------------------------------------------------------------------

    def reset_for_episode(self) -> None:
        self._prev_phi        = None
        self._prev_action_idx = None
        self._prev_state      = None
        self._on_mineral      = False
        self._mineral_memory  = {}

    def on_episode_done(self, rank: int, n_bots: int) -> None:
        if self._prev_phi is not None:
            final_reward = RewardCalculator.compute_episode_end(rank, n_bots)
            dummy_phi = np.zeros(N_FEATURES, dtype=np.float32)
            self._buffer.push(
                self._prev_phi,
                self._prev_action_idx or IDX_STAY,
                final_reward,
                dummy_phi,
                True,
            )
            # 에피소드 종료 보상으로 2번만 학습 (기존 4번 → 분산 감소)
            for _ in range(2):
                self._learn()

        self._episode_count += 1

        if self._epsilon_override is None:
            self._epsilon = max(EPSILON_MIN, self._epsilon * EPSILON_DECAY)

        self.save_weights(save_buffer=False)

        if self._episode_count % GCS_UPLOAD_INTERVAL == 0:
            try:
                from src.arena import gcs_weights
                if gcs_weights.enabled():
                    ok = gcs_weights.upload(_DEFAULT_WEIGHTS_PATH)
                    if not ok:
                        import logging
                        logging.getLogger(__name__).warning(
                            "RLBossBot GCS 업로드 실패 (ep=%d)", self._episode_count
                        )
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "RLBossBot GCS 업로드 예외 (ep=%d): %s", self._episode_count, exc
                )

    # -----------------------------------------------------------------------
    # 하드코딩 헬퍼
    # -----------------------------------------------------------------------

    @staticmethod
    def _toward_safe(pos_x, pos_y, min_x, max_x, min_y, max_y) -> int:
        cx = (min_x + max_x) // 2
        cy = (min_y + max_y) // 2
        return _move_idx_toward(cx - pos_x, cy - pos_y)

    # -----------------------------------------------------------------------
    # 체크포인트
    # -----------------------------------------------------------------------

    def save_weights(self, path=None, save_buffer: bool = True) -> None:
        save_path = Path(path) if path is not None else _DEFAULT_WEIGHTS_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version":       4,
            "n_features":    N_FEATURES,
            "n_hidden1":     N_HIDDEN1,
            "n_hidden2":     N_HIDDEN2,
            "n_actions":     N_ACTIONS,
            "step_count":    self._step_count,
            "episode_count": self._episode_count,
            "epsilon":       self._epsilon,
            "online":        self._online.to_dict(),
            "target":        self._target.to_dict(),
            "buffer":        self._buffer.to_list() if save_buffer else [],
        }
        # Atomic write: tmp file + rename. SIGTERM/SIGKILL 도중에도
        # 최종 파일은 항상 완전한 JSON 상태를 유지한다.
        import os, tempfile
        fd, tmp_path = tempfile.mkstemp(
            prefix=save_path.name + ".",
            suffix=".tmp",
            dir=str(save_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, save_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_checkpoint(self, path: Path) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # B 트랙: v4 = 43→256→128→19 3층 MLP. v3 이하 구버전은 무시.
            if data.get("version") != 4:
                import logging
                logging.getLogger(__name__).warning(
                    "RLBossBot: checkpoint version %s 무시 (v4 필요, 재학습으로 회복)",
                    data.get("version"),
                )
                return
            if (data.get("n_features")  != N_FEATURES
                    or data.get("n_hidden1") != N_HIDDEN1
                    or data.get("n_hidden2") != N_HIDDEN2
                    or data.get("n_actions")  != N_ACTIONS):
                return
            tmp_online = DQNetwork()
            tmp_target = DQNetwork()
            tmp_online.from_dict(data["online"])
            tmp_target.from_dict(data["target"])
            if not tmp_online.shape_ok() or not tmp_target.shape_ok():
                return
            self._online.copy_from(tmp_online)
            self._target.copy_from(tmp_target)
            self._step_count    = data.get("step_count", 0)
            self._episode_count = data.get("episode_count", 0)
            if self._epsilon_override is None:
                self._epsilon = data.get("epsilon", EPSILON_START)
            buf_data = data.get("buffer", [])
            if buf_data:
                self._buffer.from_list(buf_data)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "체크포인트 로드 실패 (%s): %s", path, exc
            )

    # 하위 호환 API
    def get_weights(self) -> dict:
        return self._online.to_dict()

    def set_weights(self, d: dict) -> None:
        self._online.from_dict(d)
        self._target.copy_from(self._online)

    def load_weights(self, path=None) -> bool:
        load_path = Path(path) if path is not None else _DEFAULT_WEIGHTS_PATH
        if not load_path.exists():
            return False
        self._load_checkpoint(load_path)
        return True

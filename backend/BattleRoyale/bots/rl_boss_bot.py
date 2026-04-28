"""
RLBossBot — Deep Q-Network (DQN) 기반 보스 봇
=================================================

학습 알고리즘:
  DQN (Deep Q-Network) — Mnih et al. 2015 구조를 numpy로 직접 구현.
  - Online Network  : 행동 선택 + 역전파 학습
  - Target Network  : 안정적인 TD target 계산 (TARGET_UPDATE_FREQ마다 sync)
  - Experience Replay: 최근 BUFFER_SIZE개 경험 중 BATCH_SIZE개 랜덤 샘플

학습 지속성:
  trained_weights.json 에 신경망 가중치(W1,b1,W2,b2) + 학습 통계를 저장.
  서버를 재시작해도 이전 학습을 이어받는다.

하드코딩 규칙 (최소화):
  1. 자기장 탈출 — 너무 명확한 생존 규칙이라 RL이 배울 필요 없음
  2. 에너지 극위기(ENERGY_CRITICAL 이하) — 실드로 즉시 방어
  나머지 모든 결정(이동 방향, 공격, 채굴, 추격, 도망)은 DQN이 결정.

상태 벡터 (N_FEATURES = 38):
  - 시야 25개 : 5×5 grid 셀을 연속값으로 인코딩
  - 스칼라 13개: energy, score, tick, zone_margin, dist_center,
                 enemy_in_adj, enemy_in_vision, mineral_in_adj,
                 mineral_rare_in_adj, mineral_in_vision,
                 is_in_zone, rank_norm, bias

액션 (N_ACTIONS = 11):
  STAY, MOVE_UP, MOVE_DOWN, MOVE_LEFT, MOVE_RIGHT,
  MINE, ATTACK_UP, ATTACK_DOWN, ATTACK_LEFT, ATTACK_RIGHT, SHIELD
"""

from __future__ import annotations

import json
import random
import sys
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np

from src.arena.bot_interface import BotInterface
from src.arena.types import Action

_DEFAULT_WEIGHTS_PATH = Path(__file__).parent / "trained_weights.json"

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

ACTIONS = list(Action)
N_ACTIONS = len(ACTIONS)

IDX_STAY        = ACTIONS.index(Action.STAY)
IDX_MOVE_UP     = ACTIONS.index(Action.MOVE_UP)
IDX_MOVE_DOWN   = ACTIONS.index(Action.MOVE_DOWN)
IDX_MOVE_LEFT   = ACTIONS.index(Action.MOVE_LEFT)
IDX_MOVE_RIGHT  = ACTIONS.index(Action.MOVE_RIGHT)
IDX_MINE        = ACTIONS.index(Action.MINE)
IDX_ATTACK_UP   = ACTIONS.index(Action.ATTACK_UP)
IDX_ATTACK_DOWN = ACTIONS.index(Action.ATTACK_DOWN)
IDX_ATTACK_LEFT = ACTIONS.index(Action.ATTACK_LEFT)
IDX_ATTACK_RIGHT = ACTIONS.index(Action.ATTACK_RIGHT)
IDX_SHIELD      = ACTIONS.index(Action.SHIELD)

CELL_ENCODING: dict[str, float] = {
    "empty":        0.0,
    "mineral":      0.5,
    "mineral_rare": 1.0,
    "ME":           0.0,
    "bot_enemy":   -1.0,
    "wall":        -0.5,
    "zone":        -0.8,
}

MAX_TICKS = 200

# 에너지 임계값 (초기 에너지 250 기준)
ENERGY_CRITICAL  = 30    # 극위기: 하드코딩 실드
ENERGY_MINE_COST = 3

# 인접 방향
_ADJ_DIRS = [
    (0, -1, IDX_MOVE_UP,    IDX_ATTACK_UP),
    (0,  1, IDX_MOVE_DOWN,  IDX_ATTACK_DOWN),
    (-1, 0, IDX_MOVE_LEFT,  IDX_ATTACK_LEFT),
    (1,  0, IDX_MOVE_RIGHT, IDX_ATTACK_RIGHT),
]
_CX, _CY = 2, 2
_ADJ_CELL_COORDS = frozenset((_CX + dx, _CY + dy) for dx, dy, _, _ in _ADJ_DIRS)
_MOVE_TO_DELTA: dict[int, tuple[int, int]] = {
    move_idx: (dx, dy) for dx, dy, move_idx, _ in _ADJ_DIRS
}
_OPPOSITE_MOVE = {
    IDX_MOVE_UP:    IDX_MOVE_DOWN,
    IDX_MOVE_DOWN:  IDX_MOVE_UP,
    IDX_MOVE_LEFT:  IDX_MOVE_RIGHT,
    IDX_MOVE_RIGHT: IDX_MOVE_LEFT,
}

# DQN 하이퍼파라미터
N_FEATURES       = 38
N_HIDDEN         = 64
ALPHA            = 0.001     # 신경망 학습률
GAMMA            = 0.95      # 할인율
BATCH_SIZE       = 64        # 미니배치 크기
BUFFER_SIZE      = 10000     # 리플레이 버퍼 최대 크기
TARGET_UPDATE_FREQ = 100     # target network 동기화 주기 (스텝 수)
MIN_BUFFER_LEARN = 500       # 이 수 이상 쌓여야 학습 시작
EPSILON_START    = 1.0       # 탐색 시작값 (처음엔 무조건 탐색)
EPSILON_MIN      = 0.05      # 최소 탐색률
EPSILON_DECAY    = 0.992     # 에피소드마다 곱해지는 감쇠율 (약 360ep에 MIN 도달)
EXPLOIT_GUIDE_PROB = 0.25    # 착취 시에도 guided exploration 유지 확률


# ---------------------------------------------------------------------------
# DQNetwork — numpy 2층 MLP
# ---------------------------------------------------------------------------

class DQNetwork:
    """
    2층 완전연결 신경망.
      입력  : phi (N_FEATURES,)
      은닉층: ReLU(phi @ W1 + b1)  shape (N_HIDDEN,)
      출력  : Q값   (N_ACTIONS,)

    역전파: 선택한 액션에 대해서만 gradient 적용 (off-policy Q-learning).
    """

    def __init__(self, seed: Optional[int] = None):
        rng = np.random.default_rng(seed)
        # Xavier 초기화
        self.W1 = rng.standard_normal((N_FEATURES, N_HIDDEN)).astype(np.float32) \
                  * np.sqrt(2.0 / N_FEATURES)
        self.b1 = np.zeros(N_HIDDEN, dtype=np.float32)
        self.W2 = rng.standard_normal((N_HIDDEN, N_ACTIONS)).astype(np.float32) \
                  * np.sqrt(2.0 / N_HIDDEN)
        self.b2 = np.zeros(N_ACTIONS, dtype=np.float32)

    # ---- 순전파 --------------------------------------------------------

    def forward(self, phi: np.ndarray) -> np.ndarray:
        """phi: (N_FEATURES,) → Q값: (N_ACTIONS,)"""
        h = np.maximum(0.0, phi @ self.W1 + self.b1)
        return h @ self.W2 + self.b2

    def hidden(self, phi: np.ndarray) -> np.ndarray:
        """은닉층 활성화값 반환 (역전파에서 재사용)."""
        return np.maximum(0.0, phi @ self.W1 + self.b1)

    # ---- 역전파 --------------------------------------------------------

    def update_single(self, phi: np.ndarray, action: int,
                      td_target: float, alpha: float) -> float:
        """
        단일 경험에 대한 역전파.
        반환: TD 오차 (디버그용)
        """
        h = np.maximum(0.0, phi @ self.W1 + self.b1)
        q = h @ self.W2 + self.b2

        delta = td_target - q[action]   # TD 오차

        # --- W2, b2 gradient (action 열만) ---
        self.W2[:, action] += alpha * delta * h
        self.b2[action]    += alpha * delta

        # --- h에 대한 gradient ---
        dh = delta * self.W2[:, action]

        # --- ReLU gradient ---
        dh_relu = dh * (h > 0.0)

        # --- W1, b1 gradient ---
        self.W1 += alpha * np.outer(phi, dh_relu)
        self.b1 += alpha * dh_relu

        return float(delta)

    def update_batch(self, phis: np.ndarray, actions: np.ndarray,
                     td_targets: np.ndarray, alpha: float) -> float:
        """
        미니배치 역전파 (평균 gradient).
        phis    : (B, N_FEATURES)
        actions : (B,) int
        td_targets: (B,) float
        """
        B = len(phis)
        h = np.maximum(0.0, phis @ self.W1 + self.b1)        # (B, N_HIDDEN)
        q = h @ self.W2 + self.b2                             # (B, N_ACTIONS)

        # 선택된 액션의 Q값만 추출
        q_a = q[np.arange(B), actions]                       # (B,)
        deltas = td_targets - q_a                             # (B,)

        total_loss = float(np.mean(deltas ** 2))

        # --- W2, b2 gradient ---
        for i in range(B):
            self.W2[:, actions[i]] += (alpha / B) * deltas[i] * h[i]
            self.b2[actions[i]]    += (alpha / B) * deltas[i]

        # --- W1, b1 gradient (벡터화) ---
        dh = np.zeros_like(h)                                 # (B, N_HIDDEN)
        for i in range(B):
            dh[i] = deltas[i] * self.W2[:, actions[i]]
        dh_relu = dh * (h > 0.0)                              # (B, N_HIDDEN)

        self.W1 += (alpha / B) * phis.T @ dh_relu
        self.b1 += (alpha / B) * dh_relu.mean(axis=0)

        return total_loss

    # ---- 가중치 동기화 / 직렬화 ----------------------------------------

    def copy_from(self, other: "DQNetwork") -> None:
        """다른 네트워크의 가중치를 복사 (target network 업데이트)."""
        self.W1 = other.W1.copy()
        self.b1 = other.b1.copy()
        self.W2 = other.W2.copy()
        self.b2 = other.b2.copy()

    def to_dict(self) -> dict:
        return {
            "W1": self.W1.tolist(),
            "b1": self.b1.tolist(),
            "W2": self.W2.tolist(),
            "b2": self.b2.tolist(),
        }

    def from_dict(self, d: dict) -> None:
        self.W1 = np.array(d["W1"], dtype=np.float32)
        self.b1 = np.array(d["b1"], dtype=np.float32)
        self.W2 = np.array(d["W2"], dtype=np.float32)
        self.b2 = np.array(d["b2"], dtype=np.float32)

    def shape_ok(self) -> bool:
        return (self.W1.shape == (N_FEATURES, N_HIDDEN)
                and self.b1.shape == (N_HIDDEN,)
                and self.W2.shape == (N_HIDDEN, N_ACTIONS)
                and self.b2.shape == (N_ACTIONS,))


# ---------------------------------------------------------------------------
# StateEncoder
# ---------------------------------------------------------------------------

class StateEncoder:
    """게임 state를 고정 길이(N_FEATURES=38) 특징 벡터로 변환."""

    def encode(self, state: dict) -> np.ndarray:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        tick = state["tick"]
        safe_min_x, safe_min_y, safe_max_x, safe_max_y = state["zone_bounds"]
        zone_margin = safe_min_x
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        score = my["score"]
        leaderboard = state.get("leaderboard", [])

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

        is_in_zone = 1.0 if (
            pos_x < safe_min_x or pos_x > safe_max_x
            or pos_y < safe_min_y or pos_y > safe_max_y
        ) else 0.0

        my_id = my.get("id", "")
        rank_norm = 1.0
        for entry in leaderboard:
            if entry.get("id") == my_id or entry.get("bot_id") == my_id:
                rank_norm = min(entry.get("rank", len(leaderboard)) / 10.0, 1.0)
                break

        scalar_feats = [
            min(energy / 250.0, 1.0),
            min(score / 500.0, 1.0),
            tick / MAX_TICKS,
            min(zone_margin / 50.0, 1.0),
            min((abs(pos_x - 50) + abs(pos_y - 50)) / 100.0, 1.0),
            enemy_in_adj,
            enemy_in_vision,
            mineral_in_adj,
            mineral_rare_in_adj,
            mineral_in_vision,
            is_in_zone,
            rank_norm,
            1.0,  # bias
        ]

        return np.array(vision_feats + scalar_feats, dtype=np.float32)


# ---------------------------------------------------------------------------
# ReplayBuffer
# ---------------------------------------------------------------------------

class ReplayBuffer:
    """(phi, action, reward, phi_next, done) 순환 버퍼."""

    def __init__(self, maxlen: int = BUFFER_SIZE):
        self._buf: deque[tuple] = deque(maxlen=maxlen)

    def push(self, phi: np.ndarray, action: int, reward: float,
             phi_next: np.ndarray, done: bool) -> None:
        self._buf.append((phi, action, reward, phi_next, done))

    def sample(self, n: int) -> list[tuple]:
        return random.sample(self._buf, min(n, len(self._buf)))

    def __len__(self) -> int:
        return len(self._buf)

    def to_list(self) -> list:
        """직렬화용: numpy 배열을 list로 변환."""
        result = []
        for phi, action, reward, phi_next, done in self._buf:
            result.append([phi.tolist(), action, reward, phi_next.tolist(), done])
        return result

    def from_list(self, data: list) -> None:
        """역직렬화: list를 numpy 배열로 복원."""
        self._buf.clear()
        for phi_l, action, reward, phi_next_l, done in data:
            self._buf.append((
                np.array(phi_l, dtype=np.float32),
                action,
                reward,
                np.array(phi_next_l, dtype=np.float32),
                done,
            ))


# ---------------------------------------------------------------------------
# RewardCalculator
# ---------------------------------------------------------------------------

class RewardCalculator:
    """
    틱 단위 보상과 에피소드 종료 보상을 계산한다.

    보상 설계:
      - 킬 (score ≥25 급증)  : +10.0
      - 일반 채굴 (score 증가): +0.3 / 점
      - 에너지 회복          : +0.02 / 에너지
      - 에너지 위험          : -1.0 (LOW) / -3.0 (CRITICAL)
      - 자기장 내            : -4.0 / 틱
      - 이동                 : +0.1 (탐색 장려)
      - STAY                 : -0.4 (정체 억제)
      - 에피소드 종료 순위   : 1위 +30 / 2위 +10 / 3위 -5 / 4위+ -15
    """

    ENERGY_LOW_THR      = 80
    ENERGY_CRITICAL_THR = 40

    def compute_tick(
        self,
        prev_state: dict,
        curr_state: dict,
        action_idx: int,
    ) -> float:
        prev_my = prev_state["my_bot"]
        curr_my = curr_state["my_bot"]
        safe_min_x, safe_min_y, safe_max_x, safe_max_y = curr_state["zone_bounds"]
        cx, cy = curr_my["position"]

        reward = 0.0

        # 점수 변화
        score_delta = curr_my["score"] - prev_my["score"]
        if score_delta >= 25:
            reward += 10.0      # 킬 보상
        elif score_delta > 0:
            reward += score_delta * 0.3

        # 에너지 변화
        energy_delta = curr_my["energy"] - prev_my["energy"]
        reward += energy_delta * 0.02

        # 에너지 위험 패널티
        e = curr_my["energy"]
        if e <= self.ENERGY_CRITICAL_THR:
            reward -= 3.0
        elif e <= self.ENERGY_LOW_THR:
            reward -= 1.0

        # 자기장 내 패널티
        if cx < safe_min_x or cx > safe_max_x or cy < safe_min_y or cy > safe_max_y:
            reward -= 4.0

        # 이동 보상 / STAY 패널티
        if action_idx in (IDX_MOVE_UP, IDX_MOVE_DOWN, IDX_MOVE_LEFT, IDX_MOVE_RIGHT):
            reward += 0.1
        elif action_idx == IDX_STAY:
            reward -= 0.4

        return reward

    @staticmethod
    def compute_episode_end(rank: int, n_bots: int) -> float:
        """에피소드 종료 시 순위 기반 보상."""
        table = {1: 30.0, 2: 10.0, 3: -5.0}
        return table.get(rank, -15.0 * (rank - 3))


# ---------------------------------------------------------------------------
# RLBossBot
# ---------------------------------------------------------------------------

class RLBossBot(BotInterface):
    """
    DQN 기반 보스 봇.

    에피소드 간 학습 지속:
      - 같은 인스턴스를 유지하며 reset_for_episode() 로 틱 상태만 초기화
      - 가중치·버퍼·epsilon은 에피소드 간 유지
      - save_weights() 로 파일에 저장 → 서버 재시작 후에도 이어받기
    """

    def __init__(
        self,
        bot_id: str,
        seed: Optional[int] = None,
        weights_path: Optional[str | Path] = None,
        epsilon_override: Optional[float] = None,
    ):
        self._bot_id = bot_id
        self._rng    = random.Random(seed)
        self._encoder = StateEncoder()
        self._reward_calc = RewardCalculator()

        # 신경망
        self._online = DQNetwork(seed=seed)
        self._target = DQNetwork(seed=seed)
        self._target.copy_from(self._online)

        # 리플레이 버퍼
        self._buffer = ReplayBuffer(BUFFER_SIZE)

        # 학습 카운터
        self._step_count    = 0      # 총 학습 스텝 수
        self._episode_count = 0      # 총 에피소드 수

        # Epsilon (에피소드마다 감쇠)
        self._epsilon = epsilon_override if epsilon_override is not None \
                        else EPSILON_START
        self._epsilon_override = epsilon_override

        # 이전 틱 데이터 (에피소드 리셋 시 초기화)
        self._prev_phi:        Optional[np.ndarray] = None
        self._prev_action_idx: Optional[int]        = None
        self._prev_state:      Optional[dict]       = None
        self._on_mineral:      bool                 = False

        # 광물 메모리 (에피소드 리셋 시 초기화)
        self._mineral_memory: dict[tuple[int, int], str] = {}

        # 가중치 로드 (이전 학습 이어받기)
        load_path = Path(weights_path) if weights_path is not None \
                    else _DEFAULT_WEIGHTS_PATH
        if load_path.exists():
            self._load_checkpoint(load_path)

    # -----------------------------------------------------------------------
    # BotInterface 구현
    # -----------------------------------------------------------------------

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        """희귀 광물 인접 칸에 스폰. 광물 정보를 메모리에 미리 저장."""
        w = map_info.get("width", 100)
        h = map_info.get("height", 100)
        minerals = map_info.get("minerals", [])

        for m in minerals:
            cell_type = "mineral_rare" if m["rare"] else "mineral"
            self._mineral_memory[(m["x"], m["y"])] = cell_type

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

    def get_action(self, state: dict) -> str:
        my    = state["my_bot"]
        pos_x, pos_y = my["position"]
        grid  = state["vision"]["grid"]
        energy = my["energy"]
        safe_min_x, safe_min_y, safe_max_x, safe_max_y = state["zone_bounds"]

        # 시야로 광물 메모리 업데이트
        for gy in range(5):
            for gx in range(5):
                mx = pos_x + (gx - _CX)
                my_y = pos_y + (gy - _CY)
                cell = grid[gy][gx]
                if cell in ("mineral", "mineral_rare"):
                    self._mineral_memory[(mx, my_y)] = cell
                elif cell == "empty":
                    self._mineral_memory.pop((mx, my_y), None)

        phi = self._encoder.encode(state)

        # ── TD 업데이트 (이전 틱 데이터 있을 때) ──────────────────────
        if self._prev_state is not None and self._prev_phi is not None:
            reward = self._reward_calc.compute_tick(
                self._prev_state, state, self._prev_action_idx or IDX_STAY
            )
            self._buffer.push(
                self._prev_phi,
                self._prev_action_idx or IDX_STAY,
                reward,
                phi,
                False,  # 게임 중 done=False
            )
            self._learn()

        # ── 하드코딩 규칙 (최소한만) ──────────────────────────────────

        # 1. 자기장 탈출
        in_danger = (
            pos_x < safe_min_x or pos_x > safe_max_x
            or pos_y < safe_min_y or pos_y > safe_max_y
        )
        if in_danger:
            action_idx = self._toward_safe(
                pos_x, pos_y, safe_min_x, safe_max_x, safe_min_y, safe_max_y
            )
        # 2. 에너지 극위기 → 실드
        elif energy <= ENERGY_CRITICAL:
            action_idx = IDX_SHIELD
        # 3. 현재 위치에 광물 → 채굴 (DQN이 이동 후 채굴을 배우도록 보조)
        elif self._on_mineral:
            action_idx = IDX_MINE
        # 4. 나머지 모든 결정은 DQN (epsilon-greedy)
        else:
            action_idx = self._select_dqn(phi, grid, pos_x, pos_y,
                                          safe_min_x, safe_max_x,
                                          safe_min_y, safe_max_y)  # type: ignore[arg-type]

        # 이동 목적지에 광물 있으면 기억 (다음 틱 MINE용)
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
        """
        Epsilon-greedy + Guided exploration.

        탐색(epsilon) 구간을 두 단계로 나눈다:
          - 70%: guided random — 광물/적 방향을 우선 탐색 (도메인 지식 활용)
          - 30%: pure random   — 완전 랜덤 (다양성 확보)
        착취 구간: Q값 최대화 (실행 불가 액션 마스킹)
        """
        if random.random() < self._epsilon:
            # guided random: 광물/적 방향 우선
            if random.random() < 0.70:
                guided = self._guided_action(grid, pos_x, pos_y)
                if guided is not None:
                    return guided
            # pure random
            return self._rng.choice(self._valid_actions(grid))

        # 착취: Q-net 우선, guided exploration을 25% 백업으로 유지
        # (Q-net이 아직 약한 초반부터 안정적인 성능 보장)
        if random.random() < EXPLOIT_GUIDE_PROB:
            guided = self._guided_action(grid, pos_x, pos_y)
            if guided is not None:
                return guided

        q = self._online.forward(phi).copy()

        for _, _, _, attack_idx, cell in self._adj_cells(grid):
            if cell != "bot_enemy":
                q[attack_idx] -= 1e6
        if not self._on_mineral:
            q[IDX_MINE] -= 1e6

        return int(np.argmax(q))

    def _guided_action(self, grid: list, pos_x: int, pos_y: int) -> Optional[int]:
        """
        도메인 지식 기반 탐색 행동 선택.
        광물·적을 향한 이동을 우선 시도하고, 없으면 None 반환.
        """
        adj = self._adj_cells(grid)

        # 인접 희귀 광물 이동
        for _, _, move_idx, _, cell in adj:
            if cell == "mineral_rare":
                return move_idx

        # 인접 적이 있으면 공격 (절반 확률)
        if random.random() < 0.5:
            for _, _, _, attack_idx, cell in adj:
                if cell == "bot_enemy":
                    return attack_idx

        # 시야 내 광물 방향
        best: Optional[tuple[int, int]] = None
        best_score = float("inf")
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
            ddx, ddy = best
            return (IDX_MOVE_RIGHT if ddx > 0 else IDX_MOVE_LEFT) \
                   if abs(ddx) >= abs(ddy) \
                   else (IDX_MOVE_DOWN if ddy > 0 else IDX_MOVE_UP)

        # 메모리 기반 광물 방향
        if self._mineral_memory:
            mem_best: Optional[tuple[int, int]] = None
            mem_best_score = float("inf")
            for (mx, my), cell_type in self._mineral_memory.items():
                dist = abs(mx - pos_x) + abs(my - pos_y)
                if dist == 0:
                    continue
                prio = dist - (3 if cell_type == "mineral_rare" else 0)
                if prio < mem_best_score:
                    mem_best_score = prio
                    mem_best = (mx - pos_x, my - pos_y)
            if mem_best is not None:
                ddx, ddy = mem_best
                return (IDX_MOVE_RIGHT if ddx > 0 else IDX_MOVE_LEFT) \
                       if abs(ddx) >= abs(ddy) \
                       else (IDX_MOVE_DOWN if ddy > 0 else IDX_MOVE_UP)

        return None

    def _valid_actions(self, grid: list) -> list[int]:
        """실행 가능한 액션 목록 (마스킹 포함 탐색용)."""
        valid = [IDX_STAY, IDX_MOVE_UP, IDX_MOVE_DOWN,
                 IDX_MOVE_LEFT, IDX_MOVE_RIGHT, IDX_SHIELD]
        for _, _, _, attack_idx, cell in self._adj_cells(grid):
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
        """버퍼에서 미니배치를 샘플해 online network를 업데이트."""
        if len(self._buffer) < MIN_BUFFER_LEARN:
            return

        batch = self._buffer.sample(BATCH_SIZE)
        phis       = np.array([e[0] for e in batch], dtype=np.float32)
        actions    = np.array([e[1] for e in batch], dtype=np.int32)
        rewards    = np.array([e[2] for e in batch], dtype=np.float32)
        phis_next  = np.array([e[3] for e in batch], dtype=np.float32)
        dones      = np.array([e[4] for e in batch], dtype=np.float32)

        # TD target: r + γ * max_a Q_target(s', a)  (done이면 r만)
        q_next = self._target.forward(phis_next[0])   # placeholder
        td_targets = np.zeros(BATCH_SIZE, dtype=np.float32)
        for i in range(BATCH_SIZE):
            q_next = self._target.forward(phis_next[i])
            td_targets[i] = rewards[i] + (1.0 - dones[i]) * GAMMA * float(np.max(q_next))

        self._online.update_batch(phis, actions, td_targets, ALPHA)
        self._step_count += 1

        # Target network 주기적 동기화
        if self._step_count % TARGET_UPDATE_FREQ == 0:
            self._target.copy_from(self._online)

    # -----------------------------------------------------------------------
    # 에피소드 관리
    # -----------------------------------------------------------------------

    def reset_for_episode(self) -> None:
        """
        새 에피소드 시작 시 틱 상태만 초기화.
        가중치·버퍼·epsilon은 유지한다.
        """
        self._prev_phi        = None
        self._prev_action_idx = None
        self._prev_state      = None
        self._on_mineral      = False
        self._mineral_memory  = {}

    def on_episode_done(self, rank: int, n_bots: int) -> None:
        """
        에피소드 종료 시 최종 보상 처리 + epsilon 감쇠.
        rank: 이번 에피소드 최종 순위 (1이 1등)
        """
        # 마지막 전이에 종료 보상 추가
        if self._prev_phi is not None:
            final_reward = RewardCalculator.compute_episode_end(rank, n_bots)
            dummy_phi = np.zeros(N_FEATURES, dtype=np.float32)
            self._buffer.push(
                self._prev_phi,
                self._prev_action_idx or IDX_STAY,
                final_reward,
                dummy_phi,
                True,   # done=True
            )
            # 종료 보상으로 즉시 학습
            for _ in range(4):
                self._learn()

        self._episode_count += 1

        # Epsilon 감쇠 (override 없을 때만)
        if self._epsilon_override is None:
            self._epsilon = max(EPSILON_MIN,
                                self._epsilon * EPSILON_DECAY)

    # -----------------------------------------------------------------------
    # 하드코딩 헬퍼 (최소한만)
    # -----------------------------------------------------------------------

    @staticmethod
    def _toward_safe(
        pos_x: int, pos_y: int,
        min_x: int, max_x: int,
        min_y: int, max_y: int,
    ) -> int:
        cx = (min_x + max_x) // 2
        cy = (min_y + max_y) // 2
        dx = cx - pos_x
        dy = cy - pos_y
        if abs(dx) >= abs(dy):
            return IDX_MOVE_RIGHT if dx > 0 else IDX_MOVE_LEFT
        return IDX_MOVE_DOWN if dy > 0 else IDX_MOVE_UP

    # -----------------------------------------------------------------------
    # 체크포인트 저장 / 로드 (학습 지속성)
    # -----------------------------------------------------------------------

    def save_weights(self, path: Optional[str | Path] = None) -> None:
        """
        현재 신경망 가중치 + 학습 통계 + 버퍼를 JSON으로 저장.
        다음 서버 실행 시 자동으로 이어받는다.
        """
        save_path = Path(path) if path is not None else _DEFAULT_WEIGHTS_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version":        2,
            "n_features":     N_FEATURES,
            "n_hidden":       N_HIDDEN,
            "n_actions":      N_ACTIONS,
            "step_count":     self._step_count,
            "episode_count":  self._episode_count,
            "epsilon":        self._epsilon,
            "online":         self._online.to_dict(),
            "target":         self._target.to_dict(),
            "buffer":         self._buffer.to_list(),
        }
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _load_checkpoint(self, path: Path) -> None:
        """체크포인트 파일에서 가중치를 로드한다."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if data.get("version") != 2:
                return  # 구버전 파일은 무시

            if (data.get("n_features") != N_FEATURES
                    or data.get("n_hidden") != N_HIDDEN
                    or data.get("n_actions") != N_ACTIONS):
                return

            self._online.from_dict(data["online"])
            self._target.from_dict(data["target"])

            if not self._online.shape_ok() or not self._target.shape_ok():
                self._target.copy_from(self._online)
                return

            self._step_count    = data.get("step_count", 0)
            self._episode_count = data.get("episode_count", 0)

            # epsilon: override 없을 때만 파일 값 사용
            if self._epsilon_override is None:
                self._epsilon = data.get("epsilon", EPSILON_START)

            # 버퍼 복원 (있으면)
            buf_data = data.get("buffer", [])
            if buf_data:
                self._buffer.from_list(buf_data)

        except Exception:
            pass  # 로드 실패 시 새 가중치로 시작

    # 하위 호환 API
    def get_weights(self) -> dict:
        return self._online.to_dict()

    def set_weights(self, d: dict) -> None:
        self._online.from_dict(d)
        self._target.copy_from(self._online)

    def load_weights(self, path: Optional[str | Path] = None) -> bool:
        load_path = Path(path) if path is not None else _DEFAULT_WEIGHTS_PATH
        if not load_path.exists():
            return False
        self._load_checkpoint(load_path)
        return True

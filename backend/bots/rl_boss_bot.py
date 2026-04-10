"""
RL Boss Bot — 강화학습 기반 보스 봇
=========================================

설계 철학:
  순수 Python 표준 라이브러리(+numpy 선택적)만으로 RL과 유사한 동작을 구현한다.
  외부 ML 프레임워크 없이 "가중치 내장 선형 Q-근사기" 구조를 채택하여,
  사전 학습된 가중치를 하드코딩하되 게임 중 온라인 업데이트(빠른 TD 학습)를 지원한다.

핵심 모듈:
  1. StateEncoder   — 5×5 시야 + 스칼라 정보를 고정 길이 특징 벡터로 변환
  2. LinearQNet     — 특징 × 가중치 행렬 내적으로 각 액션의 Q값 추정
  3. StrategyRouter — 게임 페이즈 / 에너지 / 위협 레벨에 따라 탐색 vs 착취 결정
  4. RLBossBot      — BotInterface 구현체, 매 틱 get_action() 호출

RL 알고리즘:
  - 온라인 TD(0) Q-Learning (표 대신 선형 근사기 사용)
  - 엡실론-그리디 탐색 (초반 높음 → 후반 낮음, 게임 틱 기준)
  - 보상 함수: 채굴 점수, 킬, 에너지 변화, 생존, 자기장 페널티 반영
  - 가중치 업데이트: w += alpha * delta * grad  (단일 스텝 SGD)

사전 설정 가중치:
  게임 지식 기반으로 수작업으로 튜닝한 "좋은 초기값"을 내장.
  런타임에 TD 업데이트가 쌓이면서 점점 실전에 적응한다.
"""

from __future__ import annotations

import json
import random
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Optional

from src.arena.bot_interface import BotInterface
from src.arena.types import Action

# 학습된 가중치 기본 경로 (train_boss_bot.py가 저장하는 위치)
_DEFAULT_WEIGHTS_PATH = Path(__file__).parent / "trained_weights.json"

# ---------------------------------------------------------------------------
# 상수 정의
# ---------------------------------------------------------------------------

ACTIONS = list(Action)
N_ACTIONS = len(ACTIONS)   # 11

# 액션 인덱스 상수
IDX_STAY       = ACTIONS.index(Action.STAY)
IDX_MOVE_UP    = ACTIONS.index(Action.MOVE_UP)
IDX_MOVE_DOWN  = ACTIONS.index(Action.MOVE_DOWN)
IDX_MOVE_LEFT  = ACTIONS.index(Action.MOVE_LEFT)
IDX_MOVE_RIGHT = ACTIONS.index(Action.MOVE_RIGHT)
IDX_MINE       = ACTIONS.index(Action.MINE)
IDX_ATTACK_UP  = ACTIONS.index(Action.ATTACK_UP)
IDX_ATTACK_DOWN  = ACTIONS.index(Action.ATTACK_DOWN)
IDX_ATTACK_LEFT  = ACTIONS.index(Action.ATTACK_LEFT)
IDX_ATTACK_RIGHT = ACTIONS.index(Action.ATTACK_RIGHT)
IDX_SHIELD     = ACTIONS.index(Action.SHIELD)

# 5×5 시야 셀 인코딩 (연속값)
CELL_ENCODING = {
    "empty": 0.0,
    "mineral": 0.5,
    "mineral_rare": 1.0,
    "ME": 0.0,          # 중앙(자기 위치)은 항상 0으로 처리
    "bot_enemy": -1.0,
    "wall": -0.5,
    "zone": -0.8,
}

# 게임 페이즈 경계 (config 수치 기준)
PHASE1_END = 75
PHASE2_END = 150
MAX_TICKS = 200

# 에너지 임계값
ENERGY_CRITICAL = 15    # 위기: 무조건 생존 최우선
ENERGY_LOW = 30         # 낮음: 적극적 채굴
ENERGY_HIGH = 70        # 여유: 공격 가능

# 채굴 최소 에너지 (config ActionCost.mine = 3)
ENERGY_MINE_COST = 3
# 공격 최소 에너지 (config ActionCost.attack = 5)
ENERGY_ATTACK_MIN = 20

# 특징 벡터 차원: 시야 25 + 스칼라 13 = 38
N_FEATURES = 38

# 학습 하이퍼파라미터
ALPHA = 0.01        # 학습률
GAMMA = 0.95        # 할인율
EPSILON_START = 0.15
EPSILON_END = 0.02

# 인접 방향 정의 (dx, dy) — 이동 인덱스, 공격 인덱스 매핑
# grid 접근: grid[cy + dy][cx + dx]
_ADJ_DIRS = [
    (0, -1, IDX_MOVE_UP,    IDX_ATTACK_UP),    # 위
    (0,  1, IDX_MOVE_DOWN,  IDX_ATTACK_DOWN),  # 아래
    (-1, 0, IDX_MOVE_LEFT,  IDX_ATTACK_LEFT),  # 왼
    (1,  0, IDX_MOVE_RIGHT, IDX_ATTACK_RIGHT), # 오른
]

# 시야 중심 좌표 (5×5 고정)
_CX, _CY = 2, 2

# 인접 4칸 (gx, gy) 집합 — encode() 단일 패스 안에서 인접 여부 O(1) 판별
_ADJ_CELL_COORDS = frozenset(((_CX + dx, _CY + dy) for dx, dy, _, _ in _ADJ_DIRS))

# 이동 액션 인덱스 → (dx, dy) 매핑 — get_action() hot-path 선형 탐색 제거
_MOVE_TO_DELTA: dict[int, tuple[int, int]] = {
    move_idx: (dx, dy) for dx, dy, move_idx, _ in _ADJ_DIRS
}

# ---------------------------------------------------------------------------
# 수작업 튜닝된 초기 Q-가중치
# ---------------------------------------------------------------------------
# shape: (N_FEATURES, N_ACTIONS) = (38, 11)
# 행 순서: [시야 25개(row-major), 스칼라 13개]
#
# 스칼라 특징 인덱스 (25번 이후):
#   25: energy_norm          (0~1)
#   26: score_norm           (상대적)
#   27: tick_norm            (0~1)
#   28: zone_boundary_norm   (0~1)
#   29: dist_to_center_norm  (0~1)
#   30: enemy_in_adj         (0/1)
#   31: enemy_in_vision      (0/1)
#   32: mineral_in_adj       (0/1)
#   33: mineral_rare_in_adj  (0/1)
#   34: mineral_in_vision    (0/1)
#   35: is_in_zone           (0/1) — 자기장 안에 있으면 1
#   36: leaderboard_rank_norm (0~1, 낮을수록 상위)
#   37: bias                 (상수 1.0)

def _build_initial_weights() -> list[list[float]]:
    """
    사전 지식 기반 초기 가중치 행렬을 생성한다.
    shape: (N_FEATURES, N_ACTIONS)
    """
    W = [[0.0] * N_ACTIONS for _ in range(N_FEATURES)]

    # energy_norm(25): 에너지 높을수록 이동/공격 선호, 낮으면 채굴/실드
    W[25][IDX_MOVE_UP]      = 0.4
    W[25][IDX_MOVE_DOWN]    = 0.4
    W[25][IDX_MOVE_LEFT]    = 0.4
    W[25][IDX_MOVE_RIGHT]   = 0.4
    W[25][IDX_ATTACK_UP]    = 0.8
    W[25][IDX_ATTACK_DOWN]  = 0.8
    W[25][IDX_ATTACK_LEFT]  = 0.8
    W[25][IDX_ATTACK_RIGHT] = 0.8
    W[25][IDX_MINE]         = -0.3  # 에너지 많으면 채굴보다 공격
    W[25][IDX_SHIELD]       = -0.4

    # tick_norm(27): 후반일수록 공격적
    W[27][IDX_ATTACK_UP]    = 0.5
    W[27][IDX_ATTACK_DOWN]  = 0.5
    W[27][IDX_ATTACK_LEFT]  = 0.5
    W[27][IDX_ATTACK_RIGHT] = 0.5
    W[27][IDX_MOVE_UP]      = 0.2

    # zone_boundary_norm(28): 자기장이 클수록 이동 필요
    W[28][IDX_MOVE_UP]    = 0.6
    W[28][IDX_MOVE_DOWN]  = 0.6
    W[28][IDX_MOVE_LEFT]  = 0.6
    W[28][IDX_MOVE_RIGHT] = 0.6
    W[28][IDX_STAY]       = -1.0

    # dist_to_center_norm(29): 중앙에서 멀수록 이동 선호
    W[29][IDX_MOVE_UP]    = 0.3
    W[29][IDX_MOVE_DOWN]  = 0.3
    W[29][IDX_MOVE_LEFT]  = 0.3
    W[29][IDX_MOVE_RIGHT] = 0.3

    # enemy_in_adj(30): 인접 적 있으면 공격 선호
    W[30][IDX_ATTACK_UP]    = 1.5
    W[30][IDX_ATTACK_DOWN]  = 1.5
    W[30][IDX_ATTACK_LEFT]  = 1.5
    W[30][IDX_ATTACK_RIGHT] = 1.5
    W[30][IDX_SHIELD]       = 0.6

    # enemy_in_vision(31): 시야 내 적 → 이동(추적)
    W[31][IDX_MOVE_UP]    = 0.4
    W[31][IDX_MOVE_DOWN]  = 0.4
    W[31][IDX_MOVE_LEFT]  = 0.4
    W[31][IDX_MOVE_RIGHT] = 0.4

    # mineral_in_adj(32): 인접 광물 → 이동 방향 선호 (다음 틱 MINE)
    W[32][IDX_MOVE_UP]    = 0.8
    W[32][IDX_MOVE_DOWN]  = 0.8
    W[32][IDX_MOVE_LEFT]  = 0.8
    W[32][IDX_MOVE_RIGHT] = 0.8
    W[32][IDX_MINE]       = 0.3
    W[32][IDX_STAY]       = -0.5

    # mineral_rare_in_adj(33): 희귀 광물 → 강하게 이동 선호
    W[33][IDX_MOVE_UP]    = 1.5
    W[33][IDX_MOVE_DOWN]  = 1.5
    W[33][IDX_MOVE_LEFT]  = 1.5
    W[33][IDX_MOVE_RIGHT] = 1.5
    W[33][IDX_MINE]       = 0.5

    # mineral_in_vision(34): 시야 내 광물 → 이동
    W[34][IDX_MOVE_UP]    = 0.3
    W[34][IDX_MOVE_DOWN]  = 0.3
    W[34][IDX_MOVE_LEFT]  = 0.3
    W[34][IDX_MOVE_RIGHT] = 0.3

    # is_in_zone(35): 자기장 안에 있으면 STAY/MINE 강한 페널티, 이동 보너스
    W[35][IDX_STAY]       = -2.0
    W[35][IDX_MOVE_UP]    = 1.0
    W[35][IDX_MOVE_DOWN]  = 1.0
    W[35][IDX_MOVE_LEFT]  = 1.0
    W[35][IDX_MOVE_RIGHT] = 1.0
    W[35][IDX_MINE]       = -0.5

    # leaderboard_rank_norm(36): 순위 낮으면(값 높으면) 적극적 행동
    W[36][IDX_ATTACK_UP]    = 0.4
    W[36][IDX_ATTACK_DOWN]  = 0.4
    W[36][IDX_ATTACK_LEFT]  = 0.4
    W[36][IDX_ATTACK_RIGHT] = 0.4
    W[36][IDX_MINE]         = 0.3

    # bias(37): 기본 선호도
    W[37][IDX_MINE] = 0.1   # 채굴 약간 선호 (점수 확보)
    W[37][IDX_STAY] = -0.2  # STAY 약간 비선호

    # 시야 셀 기반 가중치 — 인접 4칸 인덱스:
    # 위(dy=-1): grid[1][2] → flat index 7
    # 아래(dy=+1): grid[3][2] → flat index 17
    # 왼(dx=-1): grid[2][1] → flat index 11
    # 오른(dx=+1): grid[2][3] → flat index 13
    #
    # 적(-1.0) × W < 0 → 공격 Q값 상승을 위해 W < 0 설정
    W[7][IDX_ATTACK_UP]    = -1.5
    W[17][IDX_ATTACK_DOWN] = -1.5
    W[11][IDX_ATTACK_LEFT] = -1.5
    W[13][IDX_ATTACK_RIGHT] = -1.5

    # 광물(0.5/1.0) × W > 0 → 이동 Q값 상승을 위해 W > 0 설정
    W[7][IDX_MOVE_UP]    = 0.8
    W[17][IDX_MOVE_DOWN] = 0.8
    W[11][IDX_MOVE_LEFT] = 0.8
    W[13][IDX_MOVE_RIGHT] = 0.8

    return W


def _load_weights_from_file(path: Path) -> Optional[list[list[float]]]:
    """JSON 파일에서 가중치를 로드. 실패 시 None 반환."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        weights = data["weights"]
        if len(weights) != N_FEATURES or any(len(row) != N_ACTIONS for row in weights):
            return None
        return weights
    except Exception:
        return None


# ---------------------------------------------------------------------------
# StateEncoder
# ---------------------------------------------------------------------------

class StateEncoder:
    """
    게임 state 딕셔너리를 고정 길이(N_FEATURES=38) 특징 벡터로 변환.
    모든 값은 [-1, 1] 범위로 정규화.
    """

    def encode(self, state: dict) -> list[float]:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        tick = state["tick"]
        zone_boundary = state["zone_boundary"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        score = my["score"]
        leaderboard = state.get("leaderboard", [])

        # 시야 25개 특징 + 인접/전체 분석을 단일 패스로 처리
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

        # 자기장 내부 여부: 경계 안쪽(safe zone 밖)에 있으면 1
        # zone_boundary는 안전 영역의 최소/최대 좌표 마진값
        is_in_zone = 0.0
        if zone_boundary > 0:
            safe_min = zone_boundary
            safe_max = 99 - zone_boundary
            if (pos_x < safe_min or pos_x > safe_max
                    or pos_y < safe_min or pos_y > safe_max):
                is_in_zone = 1.0

        # 리더보드 순위 정규화
        my_id = my.get("id", "")
        rank_norm = 1.0
        for entry in leaderboard:
            if entry.get("id") == my_id or entry.get("bot_id") == my_id:
                rank = entry.get("rank", len(leaderboard))
                rank_norm = min(rank / 10.0, 1.0)
                break

        scalar_feats = [
            min(energy / 100.0, 1.0),            # 25: energy_norm
            min(score / 500.0, 1.0),              # 26: score_norm
            tick / MAX_TICKS,                     # 27: tick_norm
            min(zone_boundary / 50.0, 1.0),       # 28: zone_boundary_norm
            min((abs(pos_x - 50) + abs(pos_y - 50)) / 100.0, 1.0),  # 29: dist_to_center_norm
            enemy_in_adj,                         # 30
            enemy_in_vision,                      # 31
            mineral_in_adj,                       # 32
            mineral_rare_in_adj,                  # 33
            mineral_in_vision,                    # 34
            is_in_zone,                           # 35
            rank_norm,                            # 36
            1.0,                                  # 37: bias
        ]

        return vision_feats + scalar_feats  # 총 38개


# ---------------------------------------------------------------------------
# LinearQNet
# ---------------------------------------------------------------------------

class LinearQNet:
    """
    선형 Q-함수 근사기.
    Q(s, a) = W[:,a] · phi(s)

    가중치 W: (N_FEATURES, N_ACTIONS) 크기의 2D 리스트.
    TD(0) 업데이트: W[:,a] += alpha * delta * phi(s)
    """

    def __init__(self, weights: list[list[float]]):
        self.W: list[list[float]] = [row[:] for row in weights]

    def q_values(self, phi: list[float]) -> list[float]:
        """모든 액션에 대한 Q값 반환."""
        return [
            sum(phi[i] * self.W[i][a] for i in range(N_FEATURES))
            for a in range(N_ACTIONS)
        ]

    def update(self, phi: list[float], action_idx: int, target: float, alpha: float) -> None:
        """
        TD 업데이트 (단일 스텝 SGD).
        delta = target - Q(s, a)
        W[:,a] += alpha * delta * phi
        """
        current_q = sum(phi[i] * self.W[i][action_idx] for i in range(N_FEATURES))
        step = alpha * (target - current_q)
        col = action_idx
        for i in range(N_FEATURES):
            self.W[i][col] += step * phi[i]


# ---------------------------------------------------------------------------
# StrategyRouter
# ---------------------------------------------------------------------------

class StrategyRouter:
    """
    게임 페이즈, 에너지, 위협 수준에 따라 Q값에 전략적 보정을 추가하고
    엡실론-그리디로 최종 액션을 선택한다.
    """

    def __init__(self, rng: random.Random, epsilon_override: Optional[float] = None):
        self._rng = rng
        self._epsilon_override = epsilon_override

    def select_action(
        self,
        q_values: list[float],
        state: dict,
        tick: int,
        on_mineral: bool,
    ) -> int:
        """
        Q값 + 전략 오버라이드 + 엡실론-그리디로 액션 인덱스 반환.

        on_mineral: 현재 위치에 광물이 있으면 True (MINE 하드 오버라이드용)
        """
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        zone_boundary = state["zone_boundary"]

        adjusted = q_values[:]

        # 인접 4칸을 한 번만 읽어 이후 규칙에서 재활용
        adj = [(dx, dy, move_idx, attack_idx, grid[_CY + dy][_CX + dx])
               for dx, dy, move_idx, attack_idx in _ADJ_DIRS]

        # ------------------------------------------------------------------
        # 1. 현재 위치에 광물 있으면 즉시 MINE (에너지 여유 있을 때)
        # ------------------------------------------------------------------
        if on_mineral and energy > ENERGY_MINE_COST:
            return IDX_MINE

        # ------------------------------------------------------------------
        # 2. 위기 생존 규칙 (에너지 극도로 낮을 때)
        # ------------------------------------------------------------------
        if energy <= ENERGY_CRITICAL:
            for _, _, move_idx, _, cell in adj:
                if cell in ("mineral", "mineral_rare"):
                    return move_idx
            return IDX_SHIELD

        # ------------------------------------------------------------------
        # 3. 자기장 탈출 규칙 (높은 우선순위)
        # ------------------------------------------------------------------
        if zone_boundary > 0:
            safe_min = zone_boundary
            safe_max = 99 - zone_boundary
            in_zone = (
                pos_x < safe_min or pos_x > safe_max
                or pos_y < safe_min or pos_y > safe_max
            )
            if in_zone:
                return self._toward_center(pos_x, pos_y, safe_min, safe_max)

        # ------------------------------------------------------------------
        # 4. 인접 적 공격 (에너지 여유 있을 때) & 5. 인접 광물 Q값 보정
        # ------------------------------------------------------------------
        for _, _, move_idx, attack_idx, cell in adj:
            if cell == "bot_enemy" and energy >= ENERGY_ATTACK_MIN:
                if energy >= ENERGY_HIGH:
                    return attack_idx
                adjusted[attack_idx] += 2.0
            elif cell == "mineral_rare":
                adjusted[move_idx] += 3.0
            elif cell == "mineral":
                adjusted[move_idx] += 1.5

        # 원거리 시야 내 가장 유리한 광물 방향 보정
        best_dir = self._find_best_mineral_direction(grid)
        if best_dir is not None:
            ddx, ddy = best_dir
            target_move = (IDX_MOVE_RIGHT if ddx > 0 else IDX_MOVE_LEFT) if abs(ddx) >= abs(ddy) \
                else (IDX_MOVE_DOWN if ddy > 0 else IDX_MOVE_UP)
            adjusted[target_move] += 0.6

        # ------------------------------------------------------------------
        # 6. 페이즈 기반 전략 조정
        # ------------------------------------------------------------------
        if tick <= PHASE1_END:
            # 초반: 채굴 우선, 공격 억제
            adjusted[IDX_MINE] += 0.3
            for idx in (IDX_ATTACK_UP, IDX_ATTACK_DOWN, IDX_ATTACK_LEFT, IDX_ATTACK_RIGHT):
                adjusted[idx] -= 0.3

        elif tick <= PHASE2_END:
            # 중반: 중앙에서 멀면 이동 보너스
            if abs(pos_x - 50) > 20 or abs(pos_y - 50) > 20:
                for idx in (IDX_MOVE_UP, IDX_MOVE_DOWN, IDX_MOVE_LEFT, IDX_MOVE_RIGHT):
                    adjusted[idx] += 0.2

        else:
            # 후반: 공격적, STAY 페널티
            for idx in (IDX_ATTACK_UP, IDX_ATTACK_DOWN, IDX_ATTACK_LEFT, IDX_ATTACK_RIGHT):
                adjusted[idx] += 0.5
            for idx in (IDX_MOVE_UP, IDX_MOVE_DOWN, IDX_MOVE_LEFT, IDX_MOVE_RIGHT):
                adjusted[idx] += 0.3
            adjusted[IDX_STAY] -= 0.5

        # ------------------------------------------------------------------
        # 7. 실행 불가 액션 마스킹
        # ------------------------------------------------------------------
        for _, _, _, attack_idx, cell in adj:
            if cell != "bot_enemy":
                adjusted[attack_idx] -= 10.0

        # 현재 위치에 광물 없으면 MINE 강하게 억제
        # (광물 위에 있을 때는 1번 규칙에서 이미 처리됨)
        if not on_mineral:
            adjusted[IDX_MINE] -= 8.0

        # ------------------------------------------------------------------
        # 8. 엡실론-그리디
        # ------------------------------------------------------------------
        epsilon = self._get_epsilon(tick)
        if self._rng.random() < epsilon:
            # 탐색: Q값 상위 3개 중 랜덤 (마스킹 적용된 값 기준)
            top3 = sorted(range(N_ACTIONS), key=lambda i: adjusted[i], reverse=True)[:3]
            return self._rng.choice(top3)

        return max(range(N_ACTIONS), key=lambda i: adjusted[i])

    def _get_epsilon(self, tick: int) -> float:
        """틱이 증가할수록 탐색 확률 감소. epsilon_override가 있으면 고정값 사용."""
        if self._epsilon_override is not None:
            return self._epsilon_override
        progress = tick / MAX_TICKS
        return EPSILON_START + (EPSILON_END - EPSILON_START) * progress

    def _toward_center(self, pos_x: int, pos_y: int, safe_min: int, safe_max: int) -> int:
        """안전 영역 중심 방향으로의 이동 액션 인덱스 반환."""
        center = (safe_min + safe_max) // 2
        dx = center - pos_x
        dy = center - pos_y
        if abs(dx) >= abs(dy):
            return IDX_MOVE_RIGHT if dx > 0 else IDX_MOVE_LEFT
        return IDX_MOVE_DOWN if dy > 0 else IDX_MOVE_UP

    def _find_best_mineral_direction(
        self, grid: list[list[str]]
    ) -> Optional[tuple[int, int]]:
        """
        시야(5×5) 내에서 가장 가까운 광물(희귀 우선) 방향을 (dx, dy)로 반환.
        현재 위치(중심) 포함, 없으면 None.
        """
        best: Optional[tuple[int, int]] = None
        best_score = float("inf")

        for gy in range(5):
            for gx in range(5):
                cell = grid[gy][gx]
                if cell not in ("mineral", "mineral_rare"):
                    continue
                ddx = gx - _CX
                ddy = gy - _CY
                dist = abs(ddx) + abs(ddy)
                if dist == 0:
                    continue
                # 희귀 광물은 거리 2 감소 효과 (우선순위 부여)
                prio = dist - (2 if cell == "mineral_rare" else 0)
                if prio < best_score:
                    best_score = prio
                    best = (ddx, ddy)

        return best


# ---------------------------------------------------------------------------
# 경험 버퍼 (deque 기반, O(1) 삽입/삭제)
# ---------------------------------------------------------------------------

class ExperienceBuffer:
    """(phi, action_idx, reward, phi_next) 튜플을 저장하는 경량 순환 버퍼."""

    def __init__(self, maxlen: int = 300):
        self._buf: deque[tuple] = deque(maxlen=maxlen)

    def push(self, phi: list[float], action_idx: int, reward: float,
             phi_next: list[float]) -> None:
        self._buf.append((phi, action_idx, reward, phi_next))

    def sample(self, n: int) -> list[tuple]:
        k = min(n, len(self._buf))
        return random.sample(self._buf, k)

    def __len__(self) -> int:
        return len(self._buf)


# ---------------------------------------------------------------------------
# 보상 함수
# ---------------------------------------------------------------------------

class RewardCalculator:
    """이전 틱 대비 변화를 분석해 스칼라 보상을 계산한다."""

    def compute(
        self,
        prev_state: dict,
        curr_state: dict,
        action_idx: int,
    ) -> float:
        prev_my = prev_state["my_bot"]
        curr_my = curr_state["my_bot"]
        curr_zone = curr_state["zone_boundary"]
        cx, cy = curr_my["position"]

        reward = 0.0

        # 점수 증가 → 긍정 보상 (채굴/킬 모두 반영)
        score_delta = curr_my["score"] - prev_my["score"]
        reward += score_delta * 0.1

        # 에너지 증가 → 소폭 긍정 (채굴 에너지 회복 포함)
        energy_delta = curr_my["energy"] - prev_my["energy"]
        reward += energy_delta * 0.05

        # 에너지 위험 구간 페널티
        curr_energy = curr_my["energy"]
        if curr_energy <= ENERGY_CRITICAL:
            reward -= 2.0
        elif curr_energy <= ENERGY_LOW:
            reward -= 0.5

        # 자기장 안에 있으면 페널티
        if curr_zone > 0:
            safe_min = curr_zone
            safe_max = 99 - curr_zone
            if cx < safe_min or cx > safe_max or cy < safe_min or cy > safe_max:
                reward -= 3.0

        # STAY 반복 페널티 (탐색 장려)
        if action_idx == IDX_STAY:
            reward -= 0.1

        return reward


# ---------------------------------------------------------------------------
# RLBossBot — 메인 봇 클래스
# ---------------------------------------------------------------------------

class RLBossBot(BotInterface):
    """
    강화학습 기반 보스 봇.

    내장된 사전 학습 가중치 + 온라인 TD(0) 업데이트로
    게임이 진행될수록 상황에 적응한다.
    """

    def __init__(
        self,
        bot_id: str,
        seed: Optional[int] = None,
        weights_path: Optional[str | Path] = None,
        epsilon_override: Optional[float] = None,
    ):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._epsilon_override = epsilon_override

        self._encoder = StateEncoder()

        # 가중치 로드 순서: 지정 경로 → 기본 경로 → 수작업 초기값
        initial_weights = _build_initial_weights()
        load_path = Path(weights_path) if weights_path is not None else _DEFAULT_WEIGHTS_PATH
        if load_path.exists():
            loaded = _load_weights_from_file(load_path)
            if loaded is not None:
                initial_weights = loaded

        self._qnet = LinearQNet(initial_weights)
        self._router = StrategyRouter(self._rng, epsilon_override=epsilon_override)
        self._reward_calc = RewardCalculator()
        self._buffer = ExperienceBuffer(maxlen=300)

        # 이전 틱 저장
        self._prev_state: Optional[dict] = None
        self._prev_phi: Optional[list[float]] = None
        self._prev_action_idx: Optional[int] = None

        # 현재 위치에 광물이 있는지 추적
        # 이동 액션 후 대상 칸 타입을 기억해 다음 틱 MINE 하드 오버라이드에 활용
        self._on_mineral: bool = False

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        tick = state["tick"]
        my = state["my_bot"]
        grid = state["vision"]["grid"]

        phi = self._encoder.encode(state)

        if self._prev_state is not None and self._prev_phi is not None:
            reward = self._reward_calc.compute(
                self._prev_state, state, self._prev_action_idx or IDX_STAY
            )
            self._buffer.push(
                self._prev_phi,
                self._prev_action_idx or IDX_STAY,
                reward,
                phi,
            )
            if len(self._buffer) >= 10:
                self._td_update(phi, reward)

        q_vals = self._qnet.q_values(phi)
        action_idx = self._router.select_action(q_vals, state, tick, self._on_mineral)

        if action_idx in _MOVE_TO_DELTA:
            dx, dy = _MOVE_TO_DELTA[action_idx]
            target_cell = grid[_CY + dy][_CX + dx]
            self._on_mineral = target_cell in ("mineral", "mineral_rare")
        else:
            self._on_mineral = False

        self._prev_state = state
        self._prev_phi = phi
        self._prev_action_idx = action_idx

        return ACTIONS[action_idx]

    def _td_update(self, phi_next: list[float], reward: float) -> None:
        """최근 경험 + 현재 전이에 대해 TD(0) 업데이트 수행."""
        if self._prev_phi is not None and self._prev_action_idx is not None:
            q_next_max = max(self._qnet.q_values(phi_next))
            td_target = reward + GAMMA * q_next_max
            self._qnet.update(self._prev_phi, self._prev_action_idx, td_target, ALPHA)

        # 버퍼에서 소수의 과거 경험 리플레이 (안정성 향상)
        if len(self._buffer) >= 20:
            for s_phi, s_action, s_reward, s_phi_next in self._buffer.sample(4):
                q_next_max = max(self._qnet.q_values(s_phi_next))
                td_target = s_reward + GAMMA * q_next_max
                self._qnet.update(s_phi, s_action, td_target, ALPHA * 0.5)

    def get_spawn_position(self, grid) -> Optional[tuple[int, int]]:
        """맵 중앙 근처(30×30 구역)에 스폰하여 초반 자원 접근성을 확보한다."""
        w = grid.width
        center_min = w // 2 - 15
        center_max = w // 2 + 15
        return (
            self._rng.randint(center_min, center_max),
            self._rng.randint(center_min, center_max),
        )

    # ------------------------------------------------------------------
    # 가중치 저장 / 로드 공개 API
    # ------------------------------------------------------------------

    def get_weights(self) -> list[list[float]]:
        """현재 Q-가중치 행렬을 반환 (깊은 복사)."""
        return [row[:] for row in self._qnet.W]

    def set_weights(self, weights: list[list[float]]) -> None:
        """외부에서 학습된 가중치를 적용한다 (깊은 복사)."""
        if len(weights) != N_FEATURES or any(len(row) != N_ACTIONS for row in weights):
            raise ValueError(
                f"가중치 shape 불일치: 기대 ({N_FEATURES}, {N_ACTIONS}), "
                f"입력 ({len(weights)}, {len(weights[0]) if weights else '?'})"
            )
        self._qnet.W = [row[:] for row in weights]

    def save_weights(self, path: Optional[str | Path] = None) -> None:
        """현재 Q-가중치를 JSON 파일로 저장."""
        save_path = Path(path) if path is not None else _DEFAULT_WEIGHTS_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "n_features": N_FEATURES,
            "n_actions": N_ACTIONS,
            "actions": ACTIONS,
            "weights": self._qnet.W,
        }
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def load_weights(self, path: Optional[str | Path] = None) -> bool:
        """
        JSON 파일에서 Q-가중치를 로드한다.
        성공하면 True, 파일 없거나 오류면 False.
        """
        load_path = Path(path) if path is not None else _DEFAULT_WEIGHTS_PATH
        loaded = _load_weights_from_file(load_path)
        if loaded is None:
            return False
        self.set_weights(loaded)
        return True

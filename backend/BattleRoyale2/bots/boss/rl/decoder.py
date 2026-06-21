"""20 디스크리트 액션 → BR2 7키 액션 dict.

옛 backend/battle_royale/.../rl_boss_bot.py 는 19개 디스크리트 액션 (STAY + 8방향 이동 +
8방향 공격 + SHIELD + MINE) 였다. BR2 는 MINE 없고 대신 pickup/dash/guard 가 있으므로
20개로 재정의:

  0       : STAY (제자리, 아무것도)
  1..8    : MOVE 8방향 (move_dir + aim_dir 동일 방향)
  9..16   : ATTACK 8방향 (제자리, attack + aim_dir)
  17      : GUARD (제자리, guard)
  18      : DASH (마지막 이동 방향으로 dash + 같은 방향 이동)
  19      : PICKUP (제자리, pickup)

modifier (다른 액션과 동시 가능):
  - use_potion : 디코더가 룰 기반으로 자동 추가 (has_potion + hp 낮음).
    학습 부담 줄이고 옛 보스 트리와 일관.

8방향 단위벡터 (0=동, 시계방향):
"""
from __future__ import annotations

import math
from typing import Any

ACTION_DIM: int = 20

# 8방향 단위벡터 (정규화). 옛 DIRECTION_DELTA 와 동일 순서:
# E, SE, S, SW, W, NW, N, NE 가 아닌, 옛 코드는 UP/DOWN/LEFT/RIGHT + 대각선.
# BR2 좌표계: x 오른쪽+, y 아래+ (Godot). 8방향:
#   0=RIGHT  (+1,  0)
#   1=DOWN_R (+0.7,+0.7)
#   2=DOWN   ( 0, +1)
#   3=DOWN_L (-0.7,+0.7)
#   4=LEFT   (-1,  0)
#   5=UP_L   (-0.7,-0.7)
#   6=UP     ( 0, -1)
#   7=UP_R   (+0.7,-0.7)
_SQ = 1.0 / math.sqrt(2.0)
DIR_VECTORS: list[tuple[float, float]] = [
    (1.0, 0.0),
    (_SQ, _SQ),
    (0.0, 1.0),
    (-_SQ, _SQ),
    (-1.0, 0.0),
    (-_SQ, -_SQ),
    (0.0, -1.0),
    (_SQ, -_SQ),
]

# 디스크리트 액션 인덱스 범위
A_STAY = 0
A_MOVE_BASE = 1     # 1..8
A_ATTACK_BASE = 9   # 9..16
A_GUARD = 17
A_DASH = 18
A_PICKUP = 19


def zero_action() -> dict[str, Any]:
    return {
        "move_dir": [0.0, 0.0],
        "aim_dir": [1.0, 0.0],
        "attack": False,
        "guard": False,
        "dash": False,
        "pickup": False,
        "use_potion": False,
    }


def decode_action(action_idx: int, state: dict[str, Any], last_move: tuple[float, float] = (1.0, 0.0)) -> dict[str, Any]:
    """action_idx (0..ACTION_DIM-1) + state → 7키 dict.

    Args:
        action_idx: 정책망 argmax 또는 sample.
        state: BR2 state — use_potion 룰 판단용 (self.hp/has_potion).
        last_move: 직전 틱 move_dir — DASH(18) 액션 시 사용.
    """
    a = zero_action()
    if not (0 <= action_idx < ACTION_DIM):
        # 안전 폴백 (STAY)
        action_idx = A_STAY

    if action_idx == A_STAY:
        pass
    elif A_MOVE_BASE <= action_idx <= A_MOVE_BASE + 7:
        dx, dy = DIR_VECTORS[action_idx - A_MOVE_BASE]
        a["move_dir"] = [dx, dy]
        a["aim_dir"] = [dx, dy]
    elif A_ATTACK_BASE <= action_idx <= A_ATTACK_BASE + 7:
        dx, dy = DIR_VECTORS[action_idx - A_ATTACK_BASE]
        a["aim_dir"] = [dx, dy]
        a["attack"] = True
    elif action_idx == A_GUARD:
        a["guard"] = True
    elif action_idx == A_DASH:
        dx, dy = last_move if last_move != (0.0, 0.0) else (1.0, 0.0)
        n = math.hypot(dx, dy) or 1.0
        a["move_dir"] = [dx / n, dy / n]
        a["aim_dir"] = [dx / n, dy / n]
        a["dash"] = True
    elif action_idx == A_PICKUP:
        a["pickup"] = True

    # modifier: 룰 기반 포션 사용 (옛 보스도 hp 낮으면 자동)
    me = state.get("self", {}) or {}
    if me.get("has_potion") and int(me.get("hp", 0)) <= 100:
        a["use_potion"] = True

    return a


def encode_action(action_dict: dict[str, Any]) -> int:
    """역방향: BR2 action dict → action_idx (학습용 demo data 변환에 사용 가능).

    유실 정보:
        - move_dir 가 정확히 8방향이 아니면 가장 가까운 방향으로 스냅.
        - guard+attack 동시 등 복합 액션은 attack 우선.
    """
    if action_dict.get("attack"):
        ax, ay = action_dict.get("aim_dir", [1.0, 0.0])
        return A_ATTACK_BASE + _nearest_dir(float(ax), float(ay))
    if action_dict.get("dash"):
        return A_DASH
    if action_dict.get("guard"):
        return A_GUARD
    if action_dict.get("pickup"):
        return A_PICKUP
    mx, my = action_dict.get("move_dir", [0.0, 0.0])
    mx, my = float(mx), float(my)
    if abs(mx) < 1e-6 and abs(my) < 1e-6:
        return A_STAY
    return A_MOVE_BASE + _nearest_dir(mx, my)


def _nearest_dir(dx: float, dy: float) -> int:
    """벡터에 가장 가까운 8방향 인덱스."""
    angle = math.atan2(dy, dx)  # [-pi, pi]
    # 8 슬라이스 (각 45도 = pi/4)
    idx = int(round((angle / (math.pi / 4.0)))) % 8
    return idx


__all__ = ["decode_action", "encode_action", "zero_action",
           "ACTION_DIM", "DIR_VECTORS",
           "A_STAY", "A_MOVE_BASE", "A_ATTACK_BASE", "A_GUARD", "A_DASH", "A_PICKUP"]

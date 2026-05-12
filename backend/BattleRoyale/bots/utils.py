"""
AI Arena — 봇 공용 유틸리티

세 봇(herbivore, mad_dog, camper) 모두에서 쓰이는 공통 상수와 헬퍼 함수.
"""

from src.arena.types import Action, CellType

# 시야 중심 (5×5 고정)
CX, CY = 2, 2

# 인접 8칸 정의 — (dx, dy, move_action, attack_action)
ADJACENT_DIRS = [
    (0,  -1, Action.MOVE_UP,         Action.ATTACK_UP),
    (0,   1, Action.MOVE_DOWN,       Action.ATTACK_DOWN),
    (-1,  0, Action.MOVE_LEFT,       Action.ATTACK_LEFT),
    (1,   0, Action.MOVE_RIGHT,      Action.ATTACK_RIGHT),
    (-1, -1, Action.MOVE_UP_LEFT,    Action.ATTACK_UP_LEFT),
    (1,  -1, Action.MOVE_UP_RIGHT,   Action.ATTACK_UP_RIGHT),
    (-1,  1, Action.MOVE_DOWN_LEFT,  Action.ATTACK_DOWN_LEFT),
    (1,   1, Action.MOVE_DOWN_RIGHT, Action.ATTACK_DOWN_RIGHT),
]

# 이동 액션 목록 (8방향)
MOVE_ACTIONS = [
    Action.MOVE_UP, Action.MOVE_DOWN, Action.MOVE_LEFT, Action.MOVE_RIGHT,
    Action.MOVE_UP_LEFT, Action.MOVE_UP_RIGHT, Action.MOVE_DOWN_LEFT, Action.MOVE_DOWN_RIGHT,
]

# 대각선 이동 허용 최소 비율 (짧은 축 / 긴 축)
# 0.4 이상이면 대각선, 미만이면 단축 이동
_DIAG_RATIO = 0.4


def move_toward(dx: int, dy: int, on_spot: str = Action.STAY) -> str:
    """
    (dx, dy) 방향으로 이동하는 8방향 액션을 반환.
    두 축 비율이 충분하면 대각선 이동. 원점이면 on_spot 반환.
    """
    if dx == 0 and dy == 0:
        return on_spot

    ax, ay = abs(dx), abs(dy)

    # 대각선: 짧은 축이 긴 축의 _DIAG_RATIO 이상일 때
    if ax > 0 and ay > 0 and min(ax, ay) / max(ax, ay) >= _DIAG_RATIO:
        if dx > 0 and dy < 0:
            return Action.MOVE_UP_RIGHT
        if dx < 0 and dy < 0:
            return Action.MOVE_UP_LEFT
        if dx > 0 and dy > 0:
            return Action.MOVE_DOWN_RIGHT
        return Action.MOVE_DOWN_LEFT

    # 단축 이동
    if ax >= ay:
        return Action.MOVE_RIGHT if dx > 0 else Action.MOVE_LEFT
    return Action.MOVE_DOWN if dy > 0 else Action.MOVE_UP


def flee(enemy_dx: int, enemy_dy: int) -> str:
    """적 방향의 반대로 도망가는 8방향 액션을 반환."""
    return move_toward(-enemy_dx, -enemy_dy, on_spot=Action.STAY)

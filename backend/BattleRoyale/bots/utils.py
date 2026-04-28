"""
AI Arena — 봇 공용 유틸리티

세 봇(herbivore, mad_dog, camper) 모두에서 쓰이는 공통 상수와 헬퍼 함수.
"""

from src.arena.types import Action, CellType

# 시야 중심 (5×5 고정)
CX, CY = 2, 2

# 인접 4칸 정의 — (dx, dy, move_action, attack_action)
ADJACENT_DIRS = [
    (0, -1, Action.MOVE_UP,    Action.ATTACK_UP),
    (0,  1, Action.MOVE_DOWN,  Action.ATTACK_DOWN),
    (-1, 0, Action.MOVE_LEFT,  Action.ATTACK_LEFT),
    (1,  0, Action.MOVE_RIGHT, Action.ATTACK_RIGHT),
]

# 이동 액션 목록
MOVE_ACTIONS = [Action.MOVE_UP, Action.MOVE_DOWN, Action.MOVE_LEFT, Action.MOVE_RIGHT]


def move_toward(dx: int, dy: int, on_spot: str = Action.STAY) -> str:
    """(dx, dy) 방향으로 이동하는 액션을 반환. 원점이면 on_spot 반환."""
    if dx == 0 and dy == 0:
        return on_spot
    if abs(dx) >= abs(dy):
        return Action.MOVE_RIGHT if dx > 0 else Action.MOVE_LEFT
    return Action.MOVE_DOWN if dy > 0 else Action.MOVE_UP


def flee(enemy_dx: int, enemy_dy: int) -> str:
    """적 방향의 반대로 도망가는 액션을 반환."""
    if abs(enemy_dx) >= abs(enemy_dy):
        return Action.MOVE_LEFT if enemy_dx > 0 else Action.MOVE_RIGHT
    return Action.MOVE_UP if enemy_dy > 0 else Action.MOVE_DOWN

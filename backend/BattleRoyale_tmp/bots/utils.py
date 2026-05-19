"""
AI Arena - Shared bot utilities (8-directional movement support).
"""

from src.arena.types import Action, CellType

# Vision center (5x5 grid)
CX, CY = 2, 2

# Adjacent 8 cells: (dx, dy, move_action, attack_action)
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

# 8-directional move action list
MOVE_ACTIONS = [
    Action.MOVE_UP, Action.MOVE_DOWN, Action.MOVE_LEFT, Action.MOVE_RIGHT,
    Action.MOVE_UP_LEFT, Action.MOVE_UP_RIGHT, Action.MOVE_DOWN_LEFT, Action.MOVE_DOWN_RIGHT,
]

# Diagonal threshold: use diagonal if short-axis / long-axis >= this ratio
_DIAG_RATIO = 0.4


def move_toward(dx: int, dy: int, on_spot: str = Action.STAY) -> str:
    """Return 8-directional move action toward (dx, dy). Returns on_spot if at origin."""
    if dx == 0 and dy == 0:
        return on_spot

    ax, ay = abs(dx), abs(dy)

    # Use diagonal when both axes are significant
    if ax > 0 and ay > 0 and min(ax, ay) / max(ax, ay) >= _DIAG_RATIO:
        if dx > 0 and dy < 0:
            return Action.MOVE_UP_RIGHT
        if dx < 0 and dy < 0:
            return Action.MOVE_UP_LEFT
        if dx > 0 and dy > 0:
            return Action.MOVE_DOWN_RIGHT
        return Action.MOVE_DOWN_LEFT

    # Single-axis move
    if ax >= ay:
        return Action.MOVE_RIGHT if dx > 0 else Action.MOVE_LEFT
    return Action.MOVE_DOWN if dy > 0 else Action.MOVE_UP


def flee(enemy_dx: int, enemy_dy: int) -> str:
    """Return 8-directional move action away from the enemy."""
    return move_toward(-enemy_dx, -enemy_dy, on_spot=Action.STAY)

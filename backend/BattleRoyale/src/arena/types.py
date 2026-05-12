"""
AI Arena - Core data types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Action(str, Enum):
    """19 actions available per tick (8-directional movement and attack)."""
    STAY = "STAY"
    MOVE_UP = "MOVE_UP"
    MOVE_DOWN = "MOVE_DOWN"
    MOVE_LEFT = "MOVE_LEFT"
    MOVE_RIGHT = "MOVE_RIGHT"
    MOVE_UP_LEFT = "MOVE_UP_LEFT"
    MOVE_UP_RIGHT = "MOVE_UP_RIGHT"
    MOVE_DOWN_LEFT = "MOVE_DOWN_LEFT"
    MOVE_DOWN_RIGHT = "MOVE_DOWN_RIGHT"
    MINE = "MINE"
    ATTACK_UP = "ATTACK_UP"
    ATTACK_DOWN = "ATTACK_DOWN"
    ATTACK_LEFT = "ATTACK_LEFT"
    ATTACK_RIGHT = "ATTACK_RIGHT"
    ATTACK_UP_LEFT = "ATTACK_UP_LEFT"
    ATTACK_UP_RIGHT = "ATTACK_UP_RIGHT"
    ATTACK_DOWN_LEFT = "ATTACK_DOWN_LEFT"
    ATTACK_DOWN_RIGHT = "ATTACK_DOWN_RIGHT"
    SHIELD = "SHIELD"


# Direction -> coordinate delta (4 cardinal + 4 diagonal)
DIRECTION_DELTA: dict[str, tuple[int, int]] = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
    "UP_LEFT": (-1, -1),
    "UP_RIGHT": (1, -1),
    "DOWN_LEFT": (-1, 1),
    "DOWN_RIGHT": (1, 1),
}

MOVE_ACTIONS = {
    Action.MOVE_UP, Action.MOVE_DOWN, Action.MOVE_LEFT, Action.MOVE_RIGHT,
    Action.MOVE_UP_LEFT, Action.MOVE_UP_RIGHT, Action.MOVE_DOWN_LEFT, Action.MOVE_DOWN_RIGHT,
}
ATTACK_ACTIONS = {
    Action.ATTACK_UP, Action.ATTACK_DOWN, Action.ATTACK_LEFT, Action.ATTACK_RIGHT,
    Action.ATTACK_UP_LEFT, Action.ATTACK_UP_RIGHT, Action.ATTACK_DOWN_LEFT, Action.ATTACK_DOWN_RIGHT,
}

# Sorted longest-first so "UP_LEFT" matches before "LEFT"
_SORTED_DIRECTIONS = sorted(DIRECTION_DELTA.keys(), key=len, reverse=True)


def action_to_direction(action: Action) -> Optional[str]:
    """MOVE_UP -> 'UP', ATTACK_UP_LEFT -> 'UP_LEFT', etc. Returns None if no direction."""
    name = action.value
    for direction in _SORTED_DIRECTIONS:
        if name.endswith(direction):
            return direction
    return None


class CellType(str, Enum):
    EMPTY = "empty"
    MINERAL = "mineral"
    MINERAL_RARE = "mineral_rare"
    ME = "ME"
    BOT_ENEMY = "bot_enemy"
    WALL = "wall"
    ZONE_DANGER = "zone"


@dataclass
class Position:
    x: int
    y: int

    def moved(self, dx: int, dy: int) -> Position:
        return Position(self.x + dx, self.y + dy)

    def distance_to(self, other: Position) -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Position):
            return NotImplemented
        return self.x == other.x and self.y == other.y

    def __hash__(self) -> int:
        return hash((self.x, self.y))

    def as_tuple(self) -> tuple[int, int]:
        return (self.x, self.y)


@dataclass
class Mineral:
    position: Position
    rare: bool = False
    mined_at_tick: Optional[int] = None

    @property
    def is_available(self) -> bool:
        return self.mined_at_tick is None


@dataclass
class Bot:
    id: str
    position: Position
    energy: int = 100
    max_energy: int = 100
    score: float = 0.0
    shield_active: bool = False
    alive: bool = True
    kills: int = 0
    survival_ticks: int = 0
    minerals_mined: int = 0

    def apply_damage(self, damage: int) -> int:
        if self.shield_active:
            actual = damage // 2
        else:
            actual = damage
        self.energy -= actual
        if self.energy <= 0:
            self.alive = False
        return actual

    def deduct_energy(self, cost: int) -> None:
        self.energy -= cost
        if self.energy <= 0:
            self.alive = False

    def gain_energy(self, amount: int) -> None:
        self.energy = min(self.max_energy, self.energy + amount)


class GameOverReason(str, Enum):
    MAX_TICKS = "max_ticks"
    LAST_STANDING = "last_standing"
    ALL_MINERALS_DEPLETED = "all_minerals_depleted"


@dataclass
class GameResult:
    reason: GameOverReason
    final_tick: int
    rankings: list[dict] = field(default_factory=list)


@dataclass
class TickEvent:
    tick: int
    event_type: str
    actor_id: Optional[str] = None
    target_id: Optional[str] = None
    detail: str = ""

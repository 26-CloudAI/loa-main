"""
AI Arena — 핵심 데이터 타입
게임 엔진 전체에서 사용하는 데이터 구조 정의.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Action(str, Enum):
    """봇이 매 틱 반환할 수 있는 11가지 행동."""
    STAY = "STAY"
    MOVE_UP = "MOVE_UP"
    MOVE_DOWN = "MOVE_DOWN"
    MOVE_LEFT = "MOVE_LEFT"
    MOVE_RIGHT = "MOVE_RIGHT"
    MINE = "MINE"
    ATTACK_UP = "ATTACK_UP"
    ATTACK_DOWN = "ATTACK_DOWN"
    ATTACK_LEFT = "ATTACK_LEFT"
    ATTACK_RIGHT = "ATTACK_RIGHT"
    SHIELD = "SHIELD"


# 방향 → 좌표 변위 매핑
DIRECTION_DELTA: dict[str, tuple[int, int]] = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}

# Action → 방향 추출 (MOVE_UP → "UP", ATTACK_LEFT → "LEFT")
MOVE_ACTIONS = {Action.MOVE_UP, Action.MOVE_DOWN, Action.MOVE_LEFT, Action.MOVE_RIGHT}
ATTACK_ACTIONS = {Action.ATTACK_UP, Action.ATTACK_DOWN, Action.ATTACK_LEFT, Action.ATTACK_RIGHT}


def action_to_direction(action: Action) -> Optional[str]:
    """MOVE_UP → 'UP', ATTACK_LEFT → 'LEFT' 등. 방향 없는 액션은 None."""
    name = action.value
    for direction in DIRECTION_DELTA:
        if name.endswith(direction):
            return direction
    return None


class CellType(str, Enum):
    """시야 격자에서 사용하는 셀 타입."""
    EMPTY = "empty"
    MINERAL = "mineral"
    MINERAL_RARE = "mineral_rare"
    ME = "ME"
    BOT_ENEMY = "bot_enemy"
    WALL = "wall"           # v1.1 지형 확장용 (현재 미사용)
    ZONE_DANGER = "zone"    # 자기장 영역 표시


@dataclass
class Position:
    """2D 격자 좌표. (0,0)은 좌상단."""
    x: int
    y: int

    def moved(self, dx: int, dy: int) -> Position:
        return Position(self.x + dx, self.y + dy)

    def distance_to(self, other: Position) -> int:
        """맨해튼 거리."""
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
    """맵 위의 광물 하나."""
    position: Position
    rare: bool = False
    mined_at_tick: Optional[int] = None   # 채굴된 틱 (재생 타이머용)

    @property
    def is_available(self) -> bool:
        return self.mined_at_tick is None


@dataclass
class Bot:
    """게임 내 봇 하나의 상태."""
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
        """
        데미지를 적용하고 실제 적용된 양을 반환.
        실드가 활성화되어 있으면 50% 감소.
        """
        if self.shield_active:
            actual = damage // 2
        else:
            actual = damage
        self.energy -= actual
        if self.energy <= 0:
            self.alive = False
        return actual

    def deduct_energy(self, cost: int) -> None:
        """에너지를 차감. 0 이하가 되면 사망 처리."""
        self.energy -= cost
        if self.energy <= 0:
            self.alive = False

    def gain_energy(self, amount: int) -> None:
        """에너지를 회복. 최대치를 넘지 않는다."""
        self.energy = min(self.max_energy, self.energy + amount)


class GameOverReason(str, Enum):
    """게임 종료 사유."""
    MAX_TICKS = "max_ticks"
    LAST_STANDING = "last_standing"
    ALL_MINERALS_DEPLETED = "all_minerals_depleted"


@dataclass
class GameResult:
    """게임 종료 시 최종 결과."""
    reason: GameOverReason
    final_tick: int
    rankings: list[dict] = field(default_factory=list)


@dataclass
class TickEvent:
    """한 틱에서 발생한 이벤트 로그."""
    tick: int
    event_type: str      # "kill", "mine", "attack", "zone_damage", "death" 등
    actor_id: Optional[str] = None
    target_id: Optional[str] = None
    detail: str = ""

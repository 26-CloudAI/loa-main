"""
초식동물 (Herbivore) — 채굴 전용 봇
전략: 시야 내 광물을 찾아 이동 → 채굴. 적 발견 시 반대 방향으로 회피.
"""

from __future__ import annotations

import random

from src.arena.bot_interface import BotInterface
from src.arena.types import Action, CellType
from bots.utils import CX, CY, ADJACENT_DIRS, MOVE_ACTIONS, move_toward, flee

_ENEMY = CellType.BOT_ENEMY
_MINERAL = CellType.MINERAL
_MINERAL_RARE = CellType.MINERAL_RARE
_FLEE_THRESHOLD = 2  # 이 거리 이하의 적은 즉시 회피


class HerbivoreBot(BotInterface):
    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._on_mineral = False

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        grid = state["vision"]["grid"]

        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # 가까운 적 발견 시 도주
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == _ENEMY:
                    enemy_dx = dx - CX
                    enemy_dy = dy - CY
                    if abs(enemy_dx) + abs(enemy_dy) <= _FLEE_THRESHOLD:
                        return flee(enemy_dx, enemy_dy)

        # 인접 광물 → 이동 후 다음 틱 채굴
        for adx, ady, move, _ in ADJACENT_DIRS:
            cell = grid[CY + ady][CX + adx]
            if cell in (_MINERAL, _MINERAL_RARE):
                self._on_mineral = True
                return move

        # 시야 내 가장 가까운 광물로 이동 (희귀 광물 우선)
        best = None
        best_prio = 999
        for dy in range(5):
            for dx in range(5):
                cell = grid[dy][dx]
                if cell in (_MINERAL, _MINERAL_RARE):
                    dist = abs(dx - CX) + abs(dy - CY)
                    prio = dist - (1 if cell == _MINERAL_RARE else 0)
                    if prio < best_prio:
                        best_prio = prio
                        best = (dx - CX, dy - CY)

        if best:
            return move_toward(*best)

        return self._rng.choice(MOVE_ACTIONS)

    def get_spawn_position(self, grid: 'Grid') -> tuple[int, int] | None:
        """희귀 광물 군락 근처에 스폰."""
        rare = [(x, y) for x, y, is_rare in grid.get_all_mineral_positions() if is_rare]
        if not rare:
            return None
        tx, ty = self._rng.choice(rare)
        for _ in range(10):
            sx = tx + self._rng.randint(-2, 2)
            sy = ty + self._rng.randint(-2, 2)
            if grid.is_in_bounds(sx, sy):
                return (sx, sy)
        return (tx, ty)

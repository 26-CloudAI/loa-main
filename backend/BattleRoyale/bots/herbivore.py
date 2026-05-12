"""
Herbivore - Mining bot with 8-directional movement.
"""

from __future__ import annotations

import random

from src.arena.bot_interface import BotInterface
from src.arena.types import Action, CellType
from bots.utils import CX, CY, ADJACENT_DIRS, MOVE_ACTIONS, move_toward, flee

_ENEMY = CellType.BOT_ENEMY
_MINERAL = CellType.MINERAL
_MINERAL_RARE = CellType.MINERAL_RARE
_FLEE_THRESHOLD = 2


class HerbivoreBot(BotInterface):
    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._on_mineral = False
        self._memory: dict[tuple[int, int], str] = {}

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> tuple[int, int] | None:
        rare = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]
        if not rare:
            return None
        tx, ty = self._rng.choice(rare)
        offsets = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        self._rng.shuffle(offsets)
        w, h = map_info["width"], map_info["height"]
        for dx, dy in offsets:
            nx, ny = tx + dx, ty + dy
            if 0 <= nx < w and 0 <= ny < h:
                return (nx, ny)
        return (tx, ty)

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        pos_x, pos_y = my["position"]
        grid = state["vision"]["grid"]

        # 1. 메모리 업데이트
        for dy in range(5):
            for dx in range(5):
                map_x, map_y = pos_x + (dx - CX), pos_y + (dy - CY)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(map_x, map_y)] = cell
                elif cell == "empty":
                    self._memory.pop((map_x, map_y), None)

        # 2. 이전 틱에 광물 칸으로 이동했으면 채굴
        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # 3. 체비쇼프 거리 2 이내 적 -> 8방향 도주
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == _ENEMY:
                    enemy_dx = dx - CX
                    enemy_dy = dy - CY
                    if max(abs(enemy_dx), abs(enemy_dy)) <= _FLEE_THRESHOLD:
                        return flee(enemy_dx, enemy_dy)

        # 4. 인접 8칸 광물 -> 이동
        for adx, ady, move, _ in ADJACENT_DIRS:
            cell = grid[CY + ady][CX + adx]
            if cell in (_MINERAL, _MINERAL_RARE):
                self._on_mineral = True
                return move

        # 5. 시야 내 가장 가까운 광물 (체비쇼프 거리, 희귀 우선)
        best = None
        best_prio = 999
        for dy in range(5):
            for dx in range(5):
                cell = grid[dy][dx]
                if cell in (_MINERAL, _MINERAL_RARE):
                    dist = max(abs(dx - CX), abs(dy - CY))
                    prio = dist - (1 if cell == _MINERAL_RARE else 0)
                    if prio < best_prio:
                        best_prio = prio
                        best = (dx - CX, dy - CY)

        if best:
            return move_toward(*best)

        # 6. 기억 속 가장 가까운 광물
        if self._memory:
            best_mem = None
            best_mem_dist = 999
            for (mx, my), m_type in self._memory.items():
                dist = abs(mx - pos_x) + abs(my - pos_y)
                prio = dist - (1 if m_type == "mineral_rare" else 0)
                if prio < best_mem_dist:
                    best_mem_dist = prio
                    best_mem = (mx - pos_x, my - pos_y)
            if best_mem:
                return move_toward(*best_mem)

        # 7. 랜덤 8방향 탐색
        return self._rng.choice(MOVE_ACTIONS)

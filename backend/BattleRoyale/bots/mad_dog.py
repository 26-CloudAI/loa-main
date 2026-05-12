"""
Mad Dog - Combat bot with 8-directional movement and attack.

Logic:
1. Emergency mining if energy <= 40
2. Attack any enemy in adjacent 8 cells (including diagonals)
3. Chase closest enemy (Chebyshev distance)
4. Opportunistic mining if energy < 300
5. Move toward map center (50, 50) to find enemies
6. Random 8-direction roam
"""

from __future__ import annotations

import random

from src.arena.bot_interface import BotInterface
from src.arena.types import Action, CellType
from bots.utils import CX, CY, ADJACENT_DIRS, MOVE_ACTIONS, move_toward

_ENEMY = CellType.BOT_ENEMY
_MINERAL = CellType.MINERAL
_MINERAL_RARE = CellType.MINERAL_RARE


class MadDogBot(BotInterface):
    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._memory: dict[tuple[int, int], str] = {}

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> tuple[int, int] | None:
        rare = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]
        if not rare:
            return (map_info["width"] // 2, map_info["height"] // 2)

        best_center, best_count = None, 0
        for rx, ry in rare:
            count = sum(1 for ox, oy in rare if abs(ox - rx) + abs(oy - ry) <= 10)
            if count > best_count:
                best_count, best_center = count, (rx, ry)

        tx, ty = best_center  # type: ignore[misc]
        w, h = map_info["width"], map_info["height"]
        dist = self._rng.randint(6, 10)
        dx, dy = self._rng.choice([(dist, 0), (-dist, 0), (0, dist), (0, -dist)])
        return (max(0, min(w - 1, tx + dx)), max(0, min(h - 1, ty + dy)))

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        cx, cy = 2, 2

        # Memory update
        for dy in range(5):
            for dx in range(5):
                map_x, map_y = pos_x + (dx - cx), pos_y + (dy - cy)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(map_x, map_y)] = cell
                elif cell == "empty":
                    self._memory.pop((map_x, map_y), None)

        # Emergency mining
        if energy <= 40:
            return self._emergency_mine(grid, cx, cy, pos_x, pos_y)

        # Attack adjacent 8 cells (including diagonals)
        for adx, ady, _, attack_action in ADJACENT_DIRS:
            row, col = cy + ady, cx + adx
            if 0 <= row < 5 and 0 <= col < 5 and grid[row][col] == "bot_enemy":
                return attack_action.value

        # Chase closest enemy (Chebyshev distance)
        closest = None
        closest_dist = 999
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == _ENEMY:
                    dist = max(abs(dx - CX), abs(dy - CY))
                    if dist < closest_dist:
                        closest_dist = dist
                        closest = (dx - CX, dy - CY)

        if closest:
            return move_toward(*closest)

        # Opportunistic mining
        if energy < 300:
            if (pos_x, pos_y) in self._memory:
                self._memory.pop((pos_x, pos_y), None)
                return "MINE"

            closest_mineral = None
            closest_min_dist = 999
            for dy in range(5):
                for dx in range(5):
                    if grid[dy][dx] in ("mineral", "mineral_rare"):
                        dist = max(abs(dx - cx), abs(dy - cy))
                        if dist < closest_min_dist:
                            closest_min_dist = dist
                            closest_mineral = (dx - cx, dy - cy)
            if closest_mineral:
                return move_toward(*closest_mineral)

        # Move toward map center
        center_dx = 50 - pos_x
        center_dy = 50 - pos_y
        if abs(center_dx) > 3 or abs(center_dy) > 3:
            return move_toward(center_dx, center_dy)

        return self._rng.choice(MOVE_ACTIONS)

    def _emergency_mine(self, grid: list, cx: int, cy: int, pos_x: int, pos_y: int) -> str:
        if (pos_x, pos_y) in self._memory:
            self._memory.pop((pos_x, pos_y), None)
            return "MINE"

        for adx, ady, move_action, _ in ADJACENT_DIRS:
            row, col = cy + ady, cx + adx
            if 0 <= row < 5 and 0 <= col < 5:
                if grid[row][col] in ("mineral", "mineral_rare"):
                    return move_action.value

        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] in ("mineral", "mineral_rare"):
                    return move_toward(dx - cx, dy - cy)

        if self._memory:
            best_mem = None
            best_mem_dist = 999
            for (mx, my) in self._memory.keys():
                dist = abs(mx - pos_x) + abs(my - pos_y)
                if dist < best_mem_dist:
                    best_mem_dist = dist
                    best_mem = (mx - pos_x, my - pos_y)
            if best_mem:
                return move_toward(*best_mem)

        return "SHIELD"

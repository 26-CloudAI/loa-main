"""
Camper - Survival/edge-farming bot with 8-directional movement.

Logic:
1. Zone avoidance (top priority): flee opposite zone direction
2. Combat avoidance: SHIELD if adjacent enemy, flee if within distance 2
3. Inferred danger: move to center if unexpected energy loss detected
4. Active farming: mine on current cell, move toward nearest mineral
5. Edge patrol: clockwise patrol along map border
"""

from __future__ import annotations

import random

from core.bot_interface import BotInterface
from core.types import Action, CellType
from bots.utils import CX, CY, ADJACENT_DIRS, MOVE_ACTIONS, move_toward, flee

_ENEMY = CellType.BOT_ENEMY
_MINERAL = CellType.MINERAL
_MINERAL_RARE = CellType.MINERAL_RARE
_ENERGY_SHIELD_MIN = 20
_ZONE_MARGIN = 2


class CamperBot(BotInterface):
    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._memory: dict[tuple[int, int], str] = {}
        self._last_energy = 100
        self._last_action = "STAY"

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> tuple[int, int] | None:
        w, h = map_info["width"], map_info["height"]
        rare = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]
        corners = [(5, 5), (w - 6, 5), (5, h - 6), (w - 6, h - 6)]
        if not rare:
            return self._rng.choice(corners)

        def min_dist_to_rare(cx: int, cy: int) -> int:
            return min(abs(cx - rx) + abs(cy - ry) for rx, ry in rare)

        return max(corners, key=lambda c: min_dist_to_rare(c[0], c[1]))

    def get_action(self, state: dict) -> str:
        action = self._determine_action(state)
        self._last_action = action
        return action

    def _determine_action(self, state: dict) -> str:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        cx, cy = 2, 2

        # Infer hidden danger from unexpected energy loss
        danger_inferred = False
        cost_map = {
            "STAY": 1, "MINE": 3, "SHIELD": 3,
            "MOVE_UP": 2, "MOVE_DOWN": 2, "MOVE_LEFT": 2, "MOVE_RIGHT": 2,
            "MOVE_UP_LEFT": 2, "MOVE_UP_RIGHT": 2, "MOVE_DOWN_LEFT": 2, "MOVE_DOWN_RIGHT": 2,
            "ATTACK_UP": 5, "ATTACK_DOWN": 5, "ATTACK_LEFT": 5, "ATTACK_RIGHT": 5,
            "ATTACK_UP_LEFT": 5, "ATTACK_UP_RIGHT": 5, "ATTACK_DOWN_LEFT": 5, "ATTACK_DOWN_RIGHT": 5,
        }
        expected_loss = cost_map.get(self._last_action, 1)
        if energy < self._last_energy:
            if (self._last_energy - energy) > expected_loss:
                danger_inferred = True
        else:
            gain = energy - self._last_energy
            if gain in (4, 19):
                danger_inferred = True
        self._last_energy = energy

        # Memory update
        for dy in range(5):
            for dx in range(5):
                map_x, map_y = pos_x + (dx - cx), pos_y + (dy - cy)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(map_x, map_y)] = cell
                elif cell == "empty":
                    self._memory.pop((map_x, map_y), None)

        # 1. Zone avoidance (top priority)
        zone_dx, zone_dy, zone_count = 0, 0, 0
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == "zone":
                    zone_dx += (dx - cx)
                    zone_dy += (dy - cy)
                    zone_count += 1
        if zone_count > 0:
            return flee(zone_dx, zone_dy)

        # 2. Enemy avoidance (Chebyshev distance)
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == _ENEMY:
                    dist = max(abs(dx - CX), abs(dy - CY))
                    if dist == 1:
                        return Action.SHIELD if energy > _ENERGY_SHIELD_MIN else flee(dx - CX, dy - CY)
                    if dist == 2:
                        return flee(dx - CX, dy - CY)

        # 3. Hidden danger
        if danger_inferred:
            return move_toward(50 - pos_x, 50 - pos_y)

        # 4. Active farming
        if (pos_x, pos_y) in self._memory:
            self._memory.pop((pos_x, pos_y), None)
            return "MINE"

        closest_mineral = None
        closest_dist = 999
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] in ("mineral", "mineral_rare"):
                    dist = max(abs(dx - cx), abs(dy - cy))
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_mineral = (dx - cx, dy - cy)
        if closest_mineral:
            return move_toward(*closest_mineral)

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

        # 5. Clockwise edge patrol
        if pos_x <= 20 and pos_y < 80:
            return "MOVE_DOWN"
        if pos_y >= 80 and pos_x < 80:
            return "MOVE_RIGHT"
        if pos_x >= 80 and pos_y > 20:
            return "MOVE_UP"
        if pos_y <= 20 and pos_x > 20:
            return "MOVE_LEFT"

        return move_toward(15 - pos_x, 15 - pos_y)

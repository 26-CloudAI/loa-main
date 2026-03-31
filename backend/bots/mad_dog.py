"""
미친개 (Mad Dog) — 전투 전용 봇
전략: 시야 내 적을 감지하면 추적 → 인접하면 공격. 적이 없으면 중앙으로 이동.
"""

from __future__ import annotations

import random

from src.arena.bot_interface import BotInterface


class MadDogBot(BotInterface):
    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        cx, cy = 2, 2  # 시야 중심

        # 에너지 낮으면 광물 찾아서 회복 시도
        if energy <= 15:
            return self._emergency_mine(grid, cx, cy)

        # 인접 4칸에 적 → 즉시 공격
        adjacent_attacks = [
            (0, -1, "ATTACK_UP"),
            (0, 1, "ATTACK_DOWN"),
            (-1, 0, "ATTACK_LEFT"),
            (1, 0, "ATTACK_RIGHT"),
        ]
        for adx, ady, attack in adjacent_attacks:
            if grid[cy + ady][cx + adx] == "bot_enemy":
                return attack

        # 시야 내 가장 가까운 적 방향으로 추적
        closest_enemy = None
        closest_dist = 999
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == "bot_enemy":
                    dist = abs(dx - cx) + abs(dy - cy)
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_enemy = (dx - cx, dy - cy)

        if closest_enemy:
            return self._move_toward(*closest_enemy)

        # 적이 없으면 맵 중앙으로 이동 (적을 만날 확률 높임)
        center_dx = 50 - pos_x
        center_dy = 50 - pos_y
        if abs(center_dx) > 3 or abs(center_dy) > 3:
            return self._move_toward(center_dx, center_dy)

        # 중앙 근처면 배회
        return self._rng.choice(["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"])

    def get_spawn_position(self, grid: 'Grid') -> tuple[int, int] | None:
        """맵의 중앙 (45-55 사이)에 스폰하여 교전 확률을 높입니다."""
        center_min = 45
        center_max = 55
        x = self._rng.randint(center_min, center_max)
        y = self._rng.randint(center_min, center_max)
        return (x, y)

    def _move_toward(self, dx: int, dy: int) -> str:
        if dx == 0 and dy == 0:
            return "STAY"
        if abs(dx) >= abs(dy):
            return "MOVE_RIGHT" if dx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if dy > 0 else "MOVE_UP"

    def _emergency_mine(self, grid: list, cx: int, cy: int) -> str:
        """에너지 위기 시 인접 광물 채굴 시도."""
        adjacent = [
            (0, -1, "MOVE_UP"),
            (0, 1, "MOVE_DOWN"),
            (-1, 0, "MOVE_LEFT"),
            (1, 0, "MOVE_RIGHT"),
        ]
        for adx, ady, move in adjacent:
            if grid[cy + ady][cx + adx] in ("mineral", "mineral_rare"):
                return move
        return "SHIELD"  # 광물도 없으면 방어

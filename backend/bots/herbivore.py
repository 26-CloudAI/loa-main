"""
초식동물 (Herbivore) — 채굴 전용 봇
전략: 시야 내 광물을 찾아 이동 → 채굴. 적 발견 시 반대 방향으로 회피.
"""

from __future__ import annotations

import random

from src.arena.bot_interface import BotInterface


class HerbivoreBot(BotInterface):
    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._on_mineral = False  # 이전 틱에서 광물 칸으로 이동했는지

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        grid = state["vision"]["grid"]
        cx, cy = 2, 2  # 시야 중심 (5×5)

        # 이전 틱에서 광물 칸으로 이동 → 이번 틱에 채굴
        if self._on_mineral:
            self._on_mineral = False
            return "MINE"

        # 시야 내 적 감지 → 도주 우선
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == "bot_enemy":
                    enemy_dx = dx - cx
                    enemy_dy = dy - cy
                    if abs(enemy_dx) + abs(enemy_dy) <= 2:
                        return self._flee(enemy_dx, enemy_dy)

        # 인접 4칸에 광물 → 이동 후 다음 틱 채굴
        adjacent = [
            (0, -1, "MOVE_UP"),
            (0, 1, "MOVE_DOWN"),
            (-1, 0, "MOVE_LEFT"),
            (1, 0, "MOVE_RIGHT"),
        ]
        for adx, ady, move in adjacent:
            cell = grid[cy + ady][cx + adx]
            if cell in ("mineral", "mineral_rare"):
                self._on_mineral = True
                return move

        # 시야 내 가장 가까운 광물 방향으로 이동
        best = None
        best_dist = 999
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] in ("mineral", "mineral_rare"):
                    dist = abs(dx - cx) + abs(dy - cy)
                    # 희귀 광물 우선
                    prio = dist - (1 if grid[dy][dx] == "mineral_rare" else 0)
                    if prio < best_dist:
                        best_dist = prio
                        best = (dx - cx, dy - cy)

        if best:
            return self._move_toward(*best)

        # 광물 없으면 랜덤 탐색
        return self._rng.choice(["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"])

    def _move_toward(self, dx: int, dy: int) -> str:
        if abs(dx) >= abs(dy):
            return "MOVE_RIGHT" if dx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if dy > 0 else "MOVE_UP"

    def _flee(self, enemy_dx: int, enemy_dy: int) -> str:
        if abs(enemy_dx) >= abs(enemy_dy):
            return "MOVE_LEFT" if enemy_dx > 0 else "MOVE_RIGHT"
        return "MOVE_UP" if enemy_dy > 0 else "MOVE_DOWN"

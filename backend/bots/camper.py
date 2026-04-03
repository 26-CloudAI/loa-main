"""
존버 (Camper) — 회피 + 후반 진입 봇
전략: 초반에는 에너지를 아끼며 외곽에서 서성이고,
      적이 가까우면 실드/회피, 자기장 수축 시 점진적으로 중앙 이동.
      후반에 남은 에너지로 채굴하여 점수 확보.
"""

from __future__ import annotations

import random

from src.arena.bot_interface import BotInterface


class CamperBot(BotInterface):
    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        tick = state["tick"]
        zone_bounds = state["zone_bounds"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        cx, cy = 2, 2  # 시야 중심

        # 인접 적 감지 → 실드 또는 회피
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == "bot_enemy":
                    dist = abs(dx - cx) + abs(dy - cy)
                    if dist == 1:
                        # 바로 옆 → 실드 (에너지 여유 있으면)
                        if energy > 20:
                            return "SHIELD"
                        return self._flee(dx - cx, dy - cy)
                    if dist == 2:
                        return self._flee(dx - cx, dy - cy)

        # 자기장 회피: 안전 경계 안으로 이동
        if zone_bounds[0] > 0 or zone_bounds[1] > 0 or zone_bounds[2] < 99 or zone_bounds[3] < 99:
            safe_min_x = zone_bounds[0] + 2
            safe_min_y = zone_bounds[1] + 2
            safe_max_x = zone_bounds[2] - 2
            safe_max_y = zone_bounds[3] - 2

            if pos_x < safe_min_x:
                return "MOVE_RIGHT"
            if pos_x > safe_max_x:
                return "MOVE_LEFT"
            if pos_y < safe_min_y:
                return "MOVE_DOWN"
            if pos_y > safe_max_y:
                return "MOVE_UP"

        # 후반 (300틱 이후) → 채굴 모드
        if tick >= 250:
            adjacent = [
                (0, -1, "MOVE_UP"),
                (0, 1, "MOVE_DOWN"),
                (-1, 0, "MOVE_LEFT"),
                (1, 0, "MOVE_RIGHT"),
            ]
            for adx, ady, move in adjacent:
                cell = grid[cy + ady][cx + adx]
                if cell in ("mineral", "mineral_rare"):
                    return move

            # 시야 내 광물 방향으로 이동
            for dy in range(5):
                for dx in range(5):
                    if grid[dy][dx] in ("mineral", "mineral_rare"):
                        return self._move_toward(dx - cx, dy - cy)

        # 초반: 에너지 절약 (STAY) 하되, 에너지가 60 이하로 떨어지면 굶어 죽지 않기 위해 파밍 시작
        if tick < 100:
            if energy > 60:
                return "STAY"
            # 에너지가 60 이하이면 랜덤 탐색 로직으로 자연스럽게 넘어감

        # 중반: 느린 탐색
        if self._rng.random() < 0.3:
            return self._rng.choice(
                ["MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"]
            )
        return "STAY"

    def _move_toward(self, dx: int, dy: int) -> str:
        if dx == 0 and dy == 0:
            return "MINE"
        if abs(dx) >= abs(dy):
            return "MOVE_RIGHT" if dx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if dy > 0 else "MOVE_UP"

    def _flee(self, enemy_dx: int, enemy_dy: int) -> str:
        if abs(enemy_dx) >= abs(enemy_dy):
            return "MOVE_LEFT" if enemy_dx > 0 else "MOVE_RIGHT"
        return "MOVE_UP" if enemy_dy > 0 else "MOVE_DOWN"

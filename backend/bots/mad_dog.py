"""
미친개 (Mad Dog) — 전투 전용 봇
전략: 시야 내 적을 감지하면 추적 → 인접하면 공격. 적이 없으면 중앙으로 이동.
"""

from __future__ import annotations

import random

from src.arena.bot_interface import BotInterface
from src.arena.types import Action, CellType
from bots.utils import CX, CY, ADJACENT_DIRS, MOVE_ACTIONS, move_toward

_ENEMY = CellType.BOT_ENEMY
_MINERAL = CellType.MINERAL
_MINERAL_RARE = CellType.MINERAL_RARE
_ENERGY_CRITICAL = 15  # 이 에너지 이하이면 긴급 채굴 모드
_MAP_CENTER = 50        # 맵 중앙 좌표 (100×100 기준)
_CENTER_RADIUS = 3      # 이 범위 안에 있으면 중앙 근처로 간주


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

        if energy <= _ENERGY_CRITICAL:
            return self._emergency_mine(grid)

        # 인접 적 → 즉시 공격
        for adx, ady, _, attack in ADJACENT_DIRS:
            if grid[CY + ady][CX + adx] == _ENEMY:
                return attack

        # 시야 내 가장 가까운 적 추적
        closest = None
        closest_dist = 999
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == _ENEMY:
                    dist = abs(dx - CX) + abs(dy - CY)
                    if dist < closest_dist:
                        closest_dist = dist
                        closest = (dx - CX, dy - CY)

        if closest:
            return move_toward(*closest)

        # 적 없으면 맵 중앙으로 이동
        center_dx = _MAP_CENTER - pos_x
        center_dy = _MAP_CENTER - pos_y
        if abs(center_dx) > _CENTER_RADIUS or abs(center_dy) > _CENTER_RADIUS:
            return move_toward(center_dx, center_dy)

        return self._rng.choice(MOVE_ACTIONS)

    def get_spawn_position(self, grid: 'Grid') -> tuple[int, int] | None:
        """맵 중앙에 스폰하여 교전 확률을 높인다."""
        x = self._rng.randint(45, 55)
        y = self._rng.randint(45, 55)
        return (x, y)

    def _emergency_mine(self, grid: list) -> str:
        """에너지 위기 시 인접 광물로 이동. 없으면 실드."""
        for adx, ady, move, _ in ADJACENT_DIRS:
            if grid[CY + ady][CX + adx] in (_MINERAL, _MINERAL_RARE):
                return move
        return Action.SHIELD

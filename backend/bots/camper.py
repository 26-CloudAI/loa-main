"""
존버 (Camper) — 회피 + 후반 진입 봇
전략: 초반에는 에너지를 아끼며 외곽에서 서성이고,
      적이 가까우면 실드/회피, 자기장 수축 시 점진적으로 중앙 이동.
      후반에 남은 에너지로 채굴하여 점수 확보.
"""

from __future__ import annotations

import random

from src.arena.bot_interface import BotInterface
from src.arena.types import Action, CellType
from bots.utils import CX, CY, ADJACENT_DIRS, MOVE_ACTIONS, move_toward, flee

_ENEMY = CellType.BOT_ENEMY
_MINERAL = CellType.MINERAL
_MINERAL_RARE = CellType.MINERAL_RARE
_ENERGY_SHIELD_MIN = 20   # 실드 사용 최소 에너지
_PHASE_LATE = 250          # 후반 채굴 모드 시작 틱
_PHASE_EARLY_END = 100     # 초반 STAY 모드 종료 틱
_ZONE_MARGIN = 2           # 자기장 경계 여유 칸


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
        zone_boundary = state["zone_boundary"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]

        # 인접 적 → 실드 또는 회피
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == _ENEMY:
                    dist = abs(dx - CX) + abs(dy - CY)
                    if dist == 1:
                        return Action.SHIELD if energy > _ENERGY_SHIELD_MIN else flee(dx - CX, dy - CY)
                    if dist == 2:
                        return flee(dx - CX, dy - CY)

        # 자기장 안전 경계 안으로 이동
        if zone_boundary > 0:
            safe_min = zone_boundary + _ZONE_MARGIN
            safe_max = 99 - zone_boundary - _ZONE_MARGIN
            if pos_x < safe_min: return Action.MOVE_RIGHT
            if pos_x > safe_max: return Action.MOVE_LEFT
            if pos_y < safe_min: return Action.MOVE_DOWN
            if pos_y > safe_max: return Action.MOVE_UP

        # 후반 → 채굴 모드
        if tick >= _PHASE_LATE:
            for adx, ady, move, _ in ADJACENT_DIRS:
                if grid[CY + ady][CX + adx] in (_MINERAL, _MINERAL_RARE):
                    return move
            for dy in range(5):
                for dx in range(5):
                    if grid[dy][dx] in (_MINERAL, _MINERAL_RARE):
                        return move_toward(dx - CX, dy - CY, on_spot=Action.MINE)

        if tick < _PHASE_EARLY_END:
            return Action.STAY

        # 중반: 간헐적 탐색
        if self._rng.random() < 0.3:
            return self._rng.choice(MOVE_ACTIONS)
        return Action.STAY

    def get_spawn_position(self, grid: 'Grid') -> tuple[int, int] | None:
        """네 코너 중 하나에 스폰."""
        w, h = grid.width, grid.height
        margin = 5
        corners = [
            (margin, margin),
            (w - 1 - margin, margin),
            (margin, h - 1 - margin),
            (w - 1 - margin, h - 1 - margin),
        ]
        return self._rng.choice(corners)

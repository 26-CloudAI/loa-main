"""
초식동물 (Herbivore) — 채굴 전용 봇
전략: 시야와 기억을 활용해 광물을 찾아다니며, 적을 만나면 무조건 도주한다.

[상세 로직]
1. 직전 틱에 광물 칸으로 이동했다면 즉시 `MINE` (채굴) 수행
2. 시야(거리 2 이내)에 적이 감지되면 적의 반대 방향으로 최우선 회피
3. 인접 칸에 광물이 보이면 이동 (이동 후 다음 틱에 1번 로직으로 채굴)
4. 시야 내에 광물이 보이면 가장 가까운 광물(희귀 광물 우선) 방향으로 추적
5. 시야에 광물이 없다면, 이전에 기억해둔 광물 좌표로 이동
6. 아무것도 없으면 무작위 4방향 탐색
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
        self._on_mineral = False  # 이전 틱에서 광물 칸으로 이동했는지
        self._memory: dict[tuple[int, int], str] = {}  # 발견한 광물 위치 기억

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> tuple[int, int] | None:
        """희귀 광물 바로 옆에 스폰해 즉시 채굴 루틴 진입."""
        rare = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]
        if not rare:
            return None
        # 희귀 광물 중 랜덤하게 하나 선택 후 인접 칸에 스폰
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

        # 1. 시야 정보를 바탕으로 맵 기억(Memory) 업데이트
        for dy in range(5):
            for dx in range(5):
                map_x, map_y = pos_x + (dx - CX), pos_y + (dy - CY)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(map_x, map_y)] = cell
                elif cell == "empty":
                    # 빈 칸인 것을 확인했으면 기억에서 지움 (누군가 캤음)
                    self._memory.pop((map_x, map_y), None)

        # 이전 틱에서 광물 칸으로 이동 → 이번 틱에 채굴
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

        # 4. 시야에 광물이 없다면, 기억(Memory) 속 가장 가까운 광물로 이동
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
                return self._move_toward(*best_mem)

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

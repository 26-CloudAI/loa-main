"""
룰베이스 보스봇 (하/중 난이도)

RuleBossEasyBot   : 하 난이도 — 생존·채굴 중심, 소극적 전투
RuleBossMediumBot : 중 난이도 — 채굴+전투 균형, 시야 내 적극 추적
"""

from __future__ import annotations

import random
from typing import Optional

from src.arena.bot_interface import BotInterface
from bots.utils import CX, CY, ADJACENT_DIRS, MOVE_ACTIONS, move_toward, flee


class RuleBossEasyBot(BotInterface):
    """
    하 난이도 보스.
    전략: 광물 파밍으로 에너지 비축, 자기장 회피 최우선.
    인접 적에게만 방어적 공격 (에너지 충분할 때). 추적 없음.
    """

    def __init__(self, bot_id: str, seed: Optional[int] = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._memory: dict[tuple[int, int], str] = {}

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        """맵 중앙 근처 광물 밀집 구역에 스폰."""
        minerals = [(m["x"], m["y"]) for m in map_info["minerals"] if not m["rare"]]
        w, h = map_info["width"], map_info["height"]
        if not minerals:
            return None
        cx, cy = w // 2, h // 2
        minerals.sort(key=lambda m: abs(m[0] - cx) + abs(m[1] - cy))
        tx, ty = minerals[min(5, len(minerals) - 1)]
        return (
            max(3, min(w - 4, tx + self._rng.randint(-5, 5))),
            max(3, min(h - 4, ty + self._rng.randint(-5, 5))),
        )

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]

        # 메모리 업데이트
        for dy in range(5):
            for dx in range(5):
                mx, my_coord = pos_x + (dx - CX), pos_y + (dy - CY)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(mx, my_coord)] = cell
                elif cell == "empty":
                    self._memory.pop((mx, my_coord), None)

        # 1. 자기장 밖이면 중앙으로 이동
        zone_bounds = state.get("zone_bounds", (0, 0, 99, 99))
        min_x, min_y, max_x, max_y = zone_bounds
        if not (min_x <= pos_x <= max_x and min_y <= pos_y <= max_y):
            cx = (min_x + max_x) // 2
            cy = (min_y + max_y) // 2
            return move_toward(cx - pos_x, cy - pos_y)

        # 2. 에너지 위기 → 실드
        if energy <= 20:
            return "SHIELD"

        # 3. 발 아래 광물 즉시 채굴
        if grid[CY][CX] in ("mineral", "mineral_rare"):
            return "MINE"

        # 4. 에너지 충분할 때만 인접 적 공격
        if energy > 80:
            for adx, ady, _, atk in ADJACENT_DIRS:
                if grid[CY + ady][CX + adx] == "bot_enemy":
                    return atk

        # 5. 시야 내 광물로 이동 (희귀 우선)
        best, best_score = None, -1
        for dy in range(5):
            for dx in range(5):
                cell = grid[dy][dx]
                if cell == "mineral_rare":
                    score = 20
                elif cell == "mineral":
                    score = 5
                else:
                    continue
                dist = abs(dx - CX) + abs(dy - CY)
                s = score - dist
                if s > best_score:
                    best_score = s
                    best = (dx - CX, dy - CY)
        if best:
            return move_toward(*best, on_spot="MINE")

        # 6. 기억 속 광물 추적
        if self._memory:
            closest = min(
                self._memory.keys(),
                key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y),
            )
            return move_toward(closest[0] - pos_x, closest[1] - pos_y, on_spot="MINE")

        # 7. 랜덤 이동 (탐색)
        return self._rng.choice(MOVE_ACTIONS)


class RuleBossMediumBot(BotInterface):
    """
    중 난이도 보스.
    전략: 공격+채굴 균형. 시야 내 적 추적·교전, 희귀 광물 우선 파밍.
    마지막으로 본 적 위치를 기억해 지속 추적. 에너지 관리 (실드, 긴급 채굴).
    """

    def __init__(self, bot_id: str, seed: Optional[int] = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._memory: dict[tuple[int, int], str] = {}
        self._last_enemy_pos: Optional[tuple[int, int]] = None

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        """희귀 광물 클러스터 근처에 매복 스폰."""
        rare = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]
        w, h = map_info["width"], map_info["height"]
        if not rare:
            return (w // 2, h // 2)
        best_center = max(
            rare,
            key=lambda r: sum(
                1 for ox, oy in rare if abs(ox - r[0]) + abs(oy - r[1]) <= 8
            ),
        )
        dist = self._rng.randint(3, 7)
        dx, dy = self._rng.choice([(dist, 0), (-dist, 0), (0, dist), (0, -dist)])
        return (
            max(2, min(w - 3, best_center[0] + dx)),
            max(2, min(h - 3, best_center[1] + dy)),
        )

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]

        # 메모리 업데이트
        for dy in range(5):
            for dx in range(5):
                mx, my_coord = pos_x + (dx - CX), pos_y + (dy - CY)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(mx, my_coord)] = cell
                elif cell == "empty":
                    self._memory.pop((mx, my_coord), None)

        # 1. 자기장 밖이면 중앙으로 이동 (적 추적 리셋)
        zone_bounds = state.get("zone_bounds", (0, 0, 99, 99))
        min_x, min_y, max_x, max_y = zone_bounds
        if not (min_x <= pos_x <= max_x and min_y <= pos_y <= max_y):
            self._last_enemy_pos = None
            cx = (min_x + max_x) // 2
            cy = (min_y + max_y) // 2
            return move_toward(cx - pos_x, cy - pos_y)

        # 2. 에너지 위기 → 긴급 채굴 (적 인접 시에도 우선)
        if energy <= 40:
            self._last_enemy_pos = None
            return self._emergency_mine(grid, pos_x, pos_y)

        # 3. 에너지 낮음 → 인접 적 공격 후 실드
        if energy <= 60:
            for adx, ady, _, atk in ADJACENT_DIRS:
                if grid[CY + ady][CX + adx] == "bot_enemy":
                    return atk
            return "SHIELD"

        # 4. 발 아래 광물 즉시 채굴
        if grid[CY][CX] in ("mineral", "mineral_rare"):
            return "MINE"

        # 5. 인접 적 즉시 공격
        for adx, ady, _, atk in ADJACENT_DIRS:
            if grid[CY + ady][CX + adx] == "bot_enemy":
                return atk

        # 6. 시야 내 적 탐지 및 추적 (에너지 충분할 때)
        closest_enemy, closest_dist = None, 999
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == "bot_enemy":
                    dist = abs(dx - CX) + abs(dy - CY)
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_enemy = (dx - CX, dy - CY)
                        self._last_enemy_pos = (
                            pos_x + (dx - CX),
                            pos_y + (dy - CY),
                        )

        if closest_enemy and energy > 100:
            return move_toward(*closest_enemy)

        # 마지막 적 위치 기억으로 추적 (에너지 충분할 때)
        if self._last_enemy_pos and energy > 150:
            edx = self._last_enemy_pos[0] - pos_x
            edy = self._last_enemy_pos[1] - pos_y
            if abs(edx) + abs(edy) > 0:
                return move_toward(edx, edy)
            self._last_enemy_pos = None

        # 7. 희귀 광물 우선 파밍
        best, best_score = None, -1
        for dy in range(5):
            for dx in range(5):
                cell = grid[dy][dx]
                if cell == "mineral_rare":
                    score = 20
                elif cell == "mineral":
                    score = 5
                else:
                    continue
                dist = abs(dx - CX) + abs(dy - CY)
                s = score - dist
                if s > best_score:
                    best_score = s
                    best = (dx - CX, dy - CY)
        if best:
            return move_toward(*best, on_spot="MINE")

        # 8. 기억 속 희귀 광물 우선 추적
        if self._memory:
            rare_mem = {k: v for k, v in self._memory.items() if v == "mineral_rare"}
            target_mem = rare_mem if rare_mem else self._memory
            closest = min(
                target_mem.keys(),
                key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y),
            )
            return move_toward(closest[0] - pos_x, closest[1] - pos_y, on_spot="MINE")

        # 9. 맵 중앙으로 이동 (적 조우 확률 높이기)
        cdx, cdy = 50 - pos_x, 50 - pos_y
        if abs(cdx) > 5 or abs(cdy) > 5:
            return move_toward(cdx, cdy)

        return self._rng.choice(MOVE_ACTIONS)

    def _emergency_mine(self, grid: list, pos_x: int, pos_y: int) -> str:
        """에너지 위기 시 광물 채굴 또는 실드."""
        if grid[CY][CX] in ("mineral", "mineral_rare"):
            return "MINE"
        for adx, ady, mv, _ in ADJACENT_DIRS:
            if grid[CY + ady][CX + adx] in ("mineral", "mineral_rare"):
                return mv
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] in ("mineral", "mineral_rare"):
                    return move_toward(dx - CX, dy - CY, on_spot="MINE")
        if self._memory:
            closest = min(
                self._memory.keys(),
                key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y),
            )
            return move_toward(closest[0] - pos_x, closest[1] - pos_y, on_spot="MINE")
        return "SHIELD"

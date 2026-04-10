"""
미친개 (Mad Dog) — 전투 전용 봇
전략: 시야 내 적을 최우선으로 추적해 공격하며, 적이 없으면 맵 중앙을 장악하고 기회주의적으로 파밍한다.

[상세 로직]
1. 에너지 위기 관리: 에너지가 40 이하면 전투를 포기하고 인접/시야/기억 속 광물을 최우선으로 찾아 비상 채굴 시도 (광물도 없으면 `SHIELD`)
2. 근접 공격: 인접(거리 1) 칸에 적이 있으면 해당 방향으로 즉시 `ATTACK`
3. 적 추적: 시야 내에 적이 감지되면 가장 가까운 적 방향으로 이동
4. 기회주의적 채굴: 에너지가 300 미만이고 시야에 적이 없을 때, 현재 밟고 있는 칸에 광물이 있으면 채굴(`MINE`)하고 주변 광물로 이동
5. 중앙 장악 (사냥): 시야에 적이나 광물이 없거나 에너지가 300 이상이면 적을 찾기 위해 맵 중앙(50, 50)으로 이동
6. 기본: 무작위 4방향 배회
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
        self._memory: dict[tuple[int, int], str] = {}

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> tuple[int, int] | None:
        """희귀 광물 클러스터 주변에 매복 스폰 — 채굴봇을 사냥하기 위해 6~10칸 거리."""
        rare = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]
        if not rare:
            # 희귀 광물 없으면 맵 중앙 (적 조우 확률 최대화)
            return (map_info["width"] // 2, map_info["height"] // 2)

        # 밀집도가 가장 높은 희귀 광물 클러스터 찾기
        best_center, best_count = None, 0
        for rx, ry in rare:
            count = sum(1 for ox, oy in rare if abs(ox - rx) + abs(oy - ry) <= 10)
            if count > best_count:
                best_count, best_center = count, (rx, ry)

        tx, ty = best_center  # type: ignore[misc]
        w, h = map_info["width"], map_info["height"]
        # 클러스터 중심에서 6~10칸 떨어진 랜덤 방향으로 매복
        dist = self._rng.randint(6, 10)
        dx, dy = self._rng.choice([(dist, 0), (-dist, 0), (0, dist), (0, -dist)])
        return (max(0, min(w - 1, tx + dx)), max(0, min(h - 1, ty + dy)))

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        cx, cy = 2, 2  # 시야 중심

        # 메모리 업데이트
        for dy in range(5):
            for dx in range(5):
                map_x, map_y = pos_x + (dx - cx), pos_y + (dy - cy)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(map_x, map_y)] = cell
                elif cell == "empty":
                    self._memory.pop((map_x, map_y), None)

        # 에너지 낮으면 전투 포기하고 우선 광물 찾아서 회복 시도
        if energy <= 40:
            return self._emergency_mine(grid, cx, cy, pos_x, pos_y)

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

        # [추가] 기회주의적 채굴 (Opportunistic Mining)
        # 시야에 적이 없을 때, 이동하는 길에 에너지를 든든하게 유지합니다.
        # 단, 에너지가 300 이상이면 광물을 무시하고 적극적으로 적을 찾아 나섭니다.
        
        if energy < 300:
            # 1. 발 아래 광물이 있다면 즉시 채굴
            if (pos_x, pos_y) in self._memory:
                self._memory.pop((pos_x, pos_y), None)
                return "MINE"

            # 2. 전투 특화 봇이므로 동선 낭비를 막고 에너지를 아끼기 위해 '가장 가까운' 광물을 선택
            closest_mineral = None
            closest_min_dist = 999
            for dy in range(5):
                for dx in range(5):
                    if grid[dy][dx] in ("mineral", "mineral_rare"):
                        dist = abs(dx - cx) + abs(dy - cy)
                        if dist < closest_min_dist:
                            closest_min_dist = dist
                            closest_mineral = (dx - cx, dy - cy)
            if closest_mineral:
                return self._move_toward(*closest_mineral)

        # 적이 없으면 맵 중앙으로 이동 (적을 만날 확률 높임)
        center_dx = 50 - pos_x
        center_dy = 50 - pos_y
        if abs(center_dx) > 3 or abs(center_dy) > 3:
            return self._move_toward(center_dx, center_dy)

        return self._rng.choice(MOVE_ACTIONS)

    def _move_toward(self, dx: int, dy: int) -> str:
        if dx == 0 and dy == 0:
            return "MINE"  # 광물 위에 도착했을 때 대기하지 않고 즉시 캐도록 수정
        if abs(dx) >= abs(dy):
            return "MOVE_RIGHT" if dx > 0 else "MOVE_LEFT"
        return "MOVE_DOWN" if dy > 0 else "MOVE_UP"

    def _emergency_mine(self, grid: list, cx: int, cy: int, pos_x: int, pos_y: int) -> str:
        """에너지 위기 시 인접 광물 채굴 시도. 시야와 기억 활용."""
        
        # 발 아래 광물이 있다면 즉시 채굴
        if (pos_x, pos_y) in self._memory:
            self._memory.pop((pos_x, pos_y), None)
            return "MINE"
            
        adjacent = [
            (0, -1, "MOVE_UP"),
            (0, 1, "MOVE_DOWN"),
            (-1, 0, "MOVE_LEFT"),
            (1, 0, "MOVE_RIGHT"),
        ]
        for adx, ady, move in adjacent:
            if grid[cy + ady][cx + adx] in ("mineral", "mineral_rare"):
                return move
                
        # 시야 내 가장 가까운 광물 방향으로 추적
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] in ("mineral", "mineral_rare"):
                    return self._move_toward(dx - cx, dy - cy)
                    
        # 기억 속 광물 추적
        if self._memory:
            best_mem = None
            best_mem_dist = 999
            for (mx, my) in self._memory.keys():
                dist = abs(mx - pos_x) + abs(my - pos_y)
                if dist < best_mem_dist:
                    best_mem_dist = dist
                    best_mem = (mx - pos_x, my - pos_y)
            if best_mem:
                return self._move_toward(*best_mem)
                
        return "SHIELD"  # 광물도 없으면 방어

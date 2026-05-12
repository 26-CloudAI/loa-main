"""
존버 (Camper) — 생존/외곽 파밍 지향 봇
전략: 초반에는 맵 가장자리를 탐색하며 광물을 캐 에너지를 비축한다. 시야에 자기장이 감지되거나 피격(에너지 이상 감소)이 감지되면 최우선으로 도망치며, 교전은 무조건 피한다.

[상세 로직]
1. 자기장 회피 (최우선): 시야(5x5) 내에 `zone`이 보이면 무조건 자기장의 반대 방향으로 도주
2. 교전 회피: 인접(거리 1) 적 조우 시 에너지가 20 초과면 `SHIELD`, 그 외 거리 2 이내면 반대 방향으로 도주
3. 은폐된 위험 회피: 광물에 가려 자기장이 안 보이더라도 에너지 이상 감소폭을 통해 자기장 피해를 추론하고 중앙(50, 50)으로 대피
4. 적극적 파밍: 발 아래 광물은 즉시 캐고, 시야와 기억을 활용해 광물을 찾아 이동
5. 외곽 순찰: 주변에 아무것도 없으면 맵 가장자리를 따라 시계 방향으로 계속 이동하며 광물 탐색
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
        self._memory: dict[tuple[int, int], str] = {}
        self._last_energy = 100
        self._last_action = "STAY"

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> tuple[int, int] | None:
        """희귀 광물과 최대한 멀리 떨어진 맵 가장자리에 스폰 — 핫플레이스 회피."""
        w, h = map_info["width"], map_info["height"]
        rare = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]

        # 맵 4개 모서리 후보
        corners = [(5, 5), (w - 6, 5), (5, h - 6), (w - 6, h - 6)]

        if not rare:
            return self._rng.choice(corners)

        # 희귀 광물과의 최단 거리가 가장 큰 모서리 선택
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
        tick = state["tick"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        cx, cy = 2, 2  # 시야 중심
        
        # 피격/자기장 등 은폐된 위험 감지 (에너지 변화 추적)
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
            # 예상 코스트보다 에너지가 더 많이 닳았다면 (자기장 피해 or 피격)
            if (self._last_energy - energy) > expected_loss:
                danger_inferred = True
        else:
            # 채굴에 성공해서 에너지가 늘었어도, 증가폭이 기대치보다 낮으면 자기장 안에서 캔 것
            # 일반 채굴(+10) - 코스트(-3) - 자기장(-3) = 4
            # 희귀 채굴(+25) - 코스트(-3) - 자기장(-3) = 19
            gain = energy - self._last_energy
            if gain in (4, 19):
                danger_inferred = True

        self._last_energy = energy

        # 메모리 업데이트
        for dy in range(5):
            for dx in range(5):
                map_x, map_y = pos_x + (dx - cx), pos_y + (dy - cy)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(map_x, map_y)] = cell
                elif cell == "empty":
                    self._memory.pop((map_x, map_y), None)

        # 1. 시야 내 자기장(`zone`) 감지 시 최우선 회피 (자기장 반대 방향으로 도주)
        zone_dx, zone_dy = 0, 0
        zone_count = 0
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == "zone":
                    zone_dx += (dx - cx)
                    zone_dy += (dy - cy)
                    zone_count += 1
        
        if zone_count > 0:
            # 발견된 자기장 타일들의 평균적인 방향의 반대(flee)로 이동
            return self._flee(zone_dx, zone_dy)

        # 2. 인접/시야 내 적 감지 → 실드 또는 회피
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == _ENEMY:
                    dist = abs(dx - CX) + abs(dy - CY)
                    if dist == 1:
                        return Action.SHIELD if energy > _ENERGY_SHIELD_MIN else flee(dx - CX, dy - CY)
                    if dist == 2:
                        return flee(dx - CX, dy - CY)

        # 3. 보이지 않는 위험(광물에 가려진 자기장, 원거리 저격) 감지 시 중앙으로 대피
        if danger_inferred:
            return self._move_toward(50 - pos_x, 50 - pos_y)

        # 4. 적극적 파밍 (에너지 비축)
        # 발 아래 광물이 있다면 즉시 채굴
        if (pos_x, pos_y) in self._memory:
            self._memory.pop((pos_x, pos_y), None)
            return "MINE"

        # 시야 내 가장 가까운 광물 방향으로 이동
        closest_mineral = None
        closest_dist = 999
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] in ("mineral", "mineral_rare"):
                    dist = abs(dx - cx) + abs(dy - cy)
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_mineral = (dx - cx, dy - cy)
        if closest_mineral:
            return self._move_toward(*closest_mineral)

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

        # 5. 외곽 순찰 (맵 가장자리를 따라 시계 방향으로 크게 돌며 탐색)
        # 벽에 부딪혀 멈춰있는 것을 방지하고, 맵 테두리를 따라 끊임없이 이동하며 파밍합니다.
        if pos_x <= 20 and pos_y < 80:
            return "MOVE_DOWN"
        if pos_y >= 80 and pos_x < 80:
            return "MOVE_RIGHT"
        if pos_x >= 80 and pos_y > 20:
            return "MOVE_UP"
        if pos_y <= 20 and pos_x > 20:
            return "MOVE_LEFT"
            
        # 중앙 부근에 있다면 순찰 궤도(왼쪽 위 15, 15 부근)로 합류하기 위해 이동
        return self._move_toward(15 - pos_x, 15 - pos_y)

    def _move_toward(self, dx: int, dy: int) -> str:
        from bots.utils import move_toward
        return move_toward(dx, dy, on_spot="STAY")

    def _flee(self, enemy_dx: int, enemy_dy: int) -> str:
        from bots.utils import flee
        return flee(enemy_dx, enemy_dy)

"""
샘플 유저 봇 4종 — 보스봇 학습용 다양한 플레이 스타일 시뮬레이션 (8방향 대응)

실제 유저가 승리를 목표로 짤 법한 전략을 구현.
콜드스타트 봇보다 훨씬 위협적이라 보스봇이 더 유의미한 학습 신호를 받는다.

주의: vision grid 중심(grid[2][2])은 항상 "ME"를 반환하므로
      현재 위치의 광물 여부는 _on_mineral 플래그로 추적한다.
      (이전 틱에 광물 칸으로 이동했으면 다음 틱에 MINE 실행)
"""

from __future__ import annotations

import random
from typing import Optional

from core.bot_interface import BotInterface
from core.types import Action
from bots.utils import ADJACENT_DIRS, MOVE_ACTIONS, CX as _CX, CY as _CY, move_toward


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

_MOVE_TO_DELTA: dict[str, tuple[int, int]] = {
    mv: (dx, dy) for dx, dy, mv, _ in ADJACENT_DIRS
}


def _in_zone(pos_x: int, pos_y: int, zone_bounds: tuple) -> bool:
    min_x, min_y, max_x, max_y = zone_bounds
    return min_x <= pos_x <= max_x and min_y <= pos_y <= max_y


def _to_center(pos_x: int, pos_y: int, zone_bounds: tuple) -> str:
    min_x, min_y, max_x, max_y = zone_bounds
    cx, cy = (min_x + max_x) // 2, (min_y + max_y) // 2
    return move_toward(cx - pos_x, cy - pos_y)


def _update_on_mineral(action: str, grid: list) -> bool:
    """이동 방향 칸에 광물이 있으면 True (다음 틱 MINE 예약)."""
    delta = _MOVE_TO_DELTA.get(action)
    if delta is None:
        return False
    dx, dy = delta
    ny, nx = _CY + dy, _CX + dx
    if 0 <= ny < 5 and 0 <= nx < 5:
        return grid[ny][nx] in ("mineral", "mineral_rare")
    return False


def _best_mineral_dir(grid: list) -> Optional[tuple[int, int]]:
    """시야 내 최고 가치 광물 방향(dx, dy) 반환. 없으면 None."""
    best, best_s = None, -1
    for gy in range(5):
        for gx in range(5):
            if gy == _CY and gx == _CX:
                continue
            cell = grid[gy][gx]
            prio = 20 if cell == "mineral_rare" else (5 if cell == "mineral" else 0)
            if prio == 0:
                continue
            dist = abs(gx - _CX) + abs(gy - _CY)
            s = prio - dist
            if s > best_s:
                best_s, best = s, (gx - _CX, gy - _CY)
    return best


# ---------------------------------------------------------------------------
# 1. Duelist — 적 사냥 특화
#    8방향으로 적에게 빠르게 접근, 인접 8칸 모두 공격 가능
# ---------------------------------------------------------------------------

class DuelistBot(BotInterface):
    """적을 추적·처치하는 전투형 봇 (8방향)."""

    def __init__(self, bot_id: str, seed: Optional[int] = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._last_enemy: Optional[tuple[int, int]] = None
        self._memory: dict[tuple[int, int], str] = {}
        self._on_mineral = False

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        w, h = map_info["width"], map_info["height"]
        return (w // 2 + self._rng.randint(-10, 10),
                h // 2 + self._rng.randint(-10, 10))

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        grid = state["vision"]["grid"]
        zone_bounds = state.get("zone_bounds", (0, 0, 99, 99))

        if not _in_zone(pos_x, pos_y, zone_bounds):
            self._last_enemy = None
            self._on_mineral = False
            return _to_center(pos_x, pos_y, zone_bounds)

        if energy <= 25:
            self._on_mineral = False
            return Action.SHIELD

        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # 메모리 업데이트
        for gy in range(5):
            for gx in range(5):
                if gy == _CY and gx == _CX:
                    continue
                mx, my_c = pos_x + (gx - _CX), pos_y + (gy - _CY)
                cell = grid[gy][gx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(mx, my_c)] = cell
                elif cell == "empty":
                    self._memory.pop((mx, my_c), None)

        # 인접 8칸 적 즉시 공격
        if energy >= 40:
            for adx, ady, _, atk in ADJACENT_DIRS:
                nx, ny = _CX + adx, _CY + ady
                if 0 <= ny < 5 and 0 <= nx < 5 and grid[ny][nx] == "bot_enemy":
                    return atk

        # 시야 내 적 추적
        closest_enemy, closest_dist = None, 999
        for gy in range(5):
            for gx in range(5):
                if grid[gy][gx] == "bot_enemy":
                    dist = abs(gx - _CX) + abs(gy - _CY)
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_enemy = (gx - _CX, gy - _CY)
                        self._last_enemy = (pos_x + (gx - _CX), pos_y + (gy - _CY))

        if closest_enemy and energy >= 60:
            action = move_toward(*closest_enemy)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        if self._last_enemy and energy >= 80:
            edx, edy = self._last_enemy[0] - pos_x, self._last_enemy[1] - pos_y
            if abs(edx) + abs(edy) > 0:
                action = move_toward(edx, edy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action
            self._last_enemy = None

        best = _best_mineral_dir(grid)
        if best:
            action = move_toward(*best)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        if self._memory:
            closest = min(self._memory,
                          key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
            dx, dy = closest[0] - pos_x, closest[1] - pos_y
            if abs(dx) + abs(dy) > 0:
                action = move_toward(dx, dy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action

        cdx, cdy = 50 - pos_x, 50 - pos_y
        if abs(cdx) + abs(cdy) > 8:
            action = move_toward(cdx, cdy)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        action = self._rng.choice(MOVE_ACTIONS)
        self._on_mineral = _update_on_mineral(action, grid)
        return action


# ---------------------------------------------------------------------------
# 2. Optimizer — 효율 채굴 특화
#    8방향 이동으로 대각선 최단 경로 파밍
# ---------------------------------------------------------------------------

class OptimizerBot(BotInterface):
    """광물 채굴 효율을 극대화하는 경제형 봇 (8방향)."""

    def __init__(self, bot_id: str, seed: Optional[int] = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._memory: dict[tuple[int, int], str] = {}
        self._on_mineral = False

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        minerals = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]
        if not minerals:
            minerals = [(m["x"], m["y"]) for m in map_info["minerals"]]
        if minerals:
            tx, ty = self._rng.choice(minerals[:min(5, len(minerals))])
            return (max(1, tx - 2), max(1, ty - 2))
        return None

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        grid = state["vision"]["grid"]
        zone_bounds = state.get("zone_bounds", (0, 0, 99, 99))

        if not _in_zone(pos_x, pos_y, zone_bounds):
            self._on_mineral = False
            return _to_center(pos_x, pos_y, zone_bounds)

        if energy <= 20:
            self._on_mineral = False
            return Action.SHIELD

        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # 메모리 업데이트
        for gy in range(5):
            for gx in range(5):
                if gy == _CY and gx == _CX:
                    continue
                mx, my_c = pos_x + (gx - _CX), pos_y + (gy - _CY)
                cell = grid[gy][gx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(mx, my_c)] = cell
                elif cell == "empty":
                    self._memory.pop((mx, my_c), None)

        # 인접 적 → 8방향 회피
        enemy_dirs = [(adx, ady) for adx, ady, _, _ in ADJACENT_DIRS
                      if 0 <= _CY+ady < 5 and 0 <= _CX+adx < 5
                      and grid[_CY+ady][_CX+adx] == "bot_enemy"]
        if enemy_dirs and energy < 150:
            flee_dx = -sum(d[0] for d in enemy_dirs)
            flee_dy = -sum(d[1] for d in enemy_dirs)
            if flee_dx != 0 or flee_dy != 0:
                action = move_toward(flee_dx, flee_dy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action

        best = _best_mineral_dir(grid)
        if best:
            action = move_toward(*best)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        if self._memory:
            rare = {k: v for k, v in self._memory.items() if v == "mineral_rare"}
            target = rare if rare else self._memory
            closest = min(target, key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
            dx, dy = closest[0] - pos_x, closest[1] - pos_y
            if abs(dx) + abs(dy) > 0:
                action = move_toward(dx, dy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action

        action = self._rng.choice(MOVE_ACTIONS)
        self._on_mineral = _update_on_mineral(action, grid)
        return action


# ---------------------------------------------------------------------------
# 3. Adaptor — 게임 단계별 전략 전환
#    초반 채굴 → 중반 균형 → 후반 전투, 8방향으로 빠른 전략 전환
# ---------------------------------------------------------------------------

class AdaptorBot(BotInterface):
    """게임 단계에 따라 전략을 전환하는 적응형 봇 (8방향)."""

    def __init__(self, bot_id: str, seed: Optional[int] = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._memory: dict[tuple[int, int], str] = {}
        self._last_enemy: Optional[tuple[int, int]] = None
        self._on_mineral = False

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        minerals = [(m["x"], m["y"]) for m in map_info["minerals"] if not m["rare"]]
        w, h = map_info["width"], map_info["height"]
        if minerals:
            minerals.sort(key=lambda m: abs(m[0] - w//2) + abs(m[1] - h//2))
            tx, ty = minerals[0]
            return (max(1, min(w-2, tx + self._rng.randint(-3, 3))),
                    max(1, min(h-2, ty + self._rng.randint(-3, 3))))
        return None

    def _my_rank(self, state: dict) -> int:
        my_id = state["my_bot"].get("id", "")
        for entry in state.get("leaderboard", []):
            if entry.get("id") == my_id:
                return entry.get("rank", 99)
        return 99

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        grid = state["vision"]["grid"]
        zone_bounds = state.get("zone_bounds", (0, 0, 99, 99))
        tick = state.get("tick", 0)

        if not _in_zone(pos_x, pos_y, zone_bounds):
            self._last_enemy = None
            self._on_mineral = False
            return _to_center(pos_x, pos_y, zone_bounds)

        if energy <= 30:
            self._on_mineral = False
            return Action.SHIELD

        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # 메모리 업데이트
        for gy in range(5):
            for gx in range(5):
                if gy == _CY and gx == _CX:
                    continue
                mx, my_c = pos_x + (gx - _CX), pos_y + (gy - _CY)
                cell = grid[gy][gx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(mx, my_c)] = cell
                elif cell == "empty":
                    self._memory.pop((mx, my_c), None)

        phase = "farm" if tick < 60 else ("mix" if tick < 140 else "fight")

        if phase == "farm":
            # 적 인접 시 8방향 회피
            enemy_dirs = [(adx, ady) for adx, ady, _, _ in ADJACENT_DIRS
                          if 0 <= _CY+ady < 5 and 0 <= _CX+adx < 5
                          and grid[_CY+ady][_CX+adx] == "bot_enemy"]
            if enemy_dirs:
                flee_dx = -sum(d[0] for d in enemy_dirs)
                flee_dy = -sum(d[1] for d in enemy_dirs)
                if flee_dx != 0 or flee_dy != 0:
                    action = move_toward(flee_dx, flee_dy)
                    self._on_mineral = _update_on_mineral(action, grid)
                    return action
        else:
            # 균형/전투: 인접 8칸 공격
            if energy >= 60:
                for adx, ady, _, atk in ADJACENT_DIRS:
                    nx, ny = _CX + adx, _CY + ady
                    if 0 <= ny < 5 and 0 <= nx < 5 and grid[ny][nx] == "bot_enemy":
                        return atk

            for gy in range(5):
                for gx in range(5):
                    if grid[gy][gx] == "bot_enemy":
                        self._last_enemy = (pos_x + (gx - _CX), pos_y + (gy - _CY))
                        if phase == "fight" and energy >= 80 and self._my_rank(state) > 2:
                            action = move_toward(gx - _CX, gy - _CY)
                            self._on_mineral = _update_on_mineral(action, grid)
                            return action

            if self._last_enemy and phase == "fight" and energy >= 100:
                edx, edy = self._last_enemy[0] - pos_x, self._last_enemy[1] - pos_y
                if abs(edx) + abs(edy) > 0:
                    action = move_toward(edx, edy)
                    self._on_mineral = _update_on_mineral(action, grid)
                    return action
                self._last_enemy = None

        best = _best_mineral_dir(grid)
        if best:
            action = move_toward(*best)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        if self._memory:
            rare = {k: v for k, v in self._memory.items() if v == "mineral_rare"}
            target = rare if rare else self._memory
            closest = min(target, key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
            dx, dy = closest[0] - pos_x, closest[1] - pos_y
            if abs(dx) + abs(dy) > 0:
                action = move_toward(dx, dy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action

        action = self._rng.choice(MOVE_ACTIONS)
        self._on_mineral = _update_on_mineral(action, grid)
        return action


# ---------------------------------------------------------------------------
# 4. ShieldTank — 실드 소모전 특화
#    실드 쿨다운 사이클 + 8방향 인접 공격으로 근접전 극대화
# ---------------------------------------------------------------------------

class ShieldTankBot(BotInterface):
    """실드 사이클을 활용한 지구전 봇 (8방향)."""

    def __init__(self, bot_id: str, seed: Optional[int] = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._memory: dict[tuple[int, int], str] = {}
        self._shield_cd = 0
        self._last_enemy: Optional[tuple[int, int]] = None
        self._on_mineral = False

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        w, h = map_info["width"], map_info["height"]
        return (w // 2 + self._rng.randint(-5, 5),
                h // 2 + self._rng.randint(-5, 5))

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        grid = state["vision"]["grid"]
        zone_bounds = state.get("zone_bounds", (0, 0, 99, 99))

        self._shield_cd = max(0, self._shield_cd - 1)

        if not _in_zone(pos_x, pos_y, zone_bounds):
            self._on_mineral = False
            return _to_center(pos_x, pos_y, zone_bounds)

        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # 메모리 업데이트
        for gy in range(5):
            for gx in range(5):
                if gy == _CY and gx == _CX:
                    continue
                mx, my_c = pos_x + (gx - _CX), pos_y + (gy - _CY)
                cell = grid[gy][gx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(mx, my_c)] = cell
                elif cell == "empty":
                    self._memory.pop((mx, my_c), None)

        # 인접 8칸 적 → 실드 → 카운터
        enemy_adj = any(
            0 <= _CY+ady < 5 and 0 <= _CX+adx < 5
            and grid[_CY+ady][_CX+adx] == "bot_enemy"
            for adx, ady, _, _ in ADJACENT_DIRS
        )
        if enemy_adj:
            if self._shield_cd == 0 and energy >= 60:
                self._shield_cd = 3
                return Action.SHIELD
            if energy >= 40:
                for adx, ady, _, atk in ADJACENT_DIRS:
                    nx, ny = _CX + adx, _CY + ady
                    if 0 <= ny < 5 and 0 <= nx < 5 and grid[ny][nx] == "bot_enemy":
                        return atk

        # 에너지 부족 → 긴급 채굴
        if energy < 60:
            for adx, ady, mv, _ in ADJACENT_DIRS:
                nx, ny = _CX + adx, _CY + ady
                if 0 <= ny < 5 and 0 <= nx < 5 and grid[ny][nx] in ("mineral", "mineral_rare"):
                    self._on_mineral = True
                    return mv
            if self._memory:
                closest = min(self._memory,
                              key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
                dx, dy = closest[0] - pos_x, closest[1] - pos_y
                if abs(dx) + abs(dy) > 0:
                    action = move_toward(dx, dy)
                    self._on_mineral = _update_on_mineral(action, grid)
                    return action
            return Action.SHIELD

        # 적 추적
        for gy in range(5):
            for gx in range(5):
                if grid[gy][gx] == "bot_enemy":
                    ddx, ddy = gx - _CX, gy - _CY
                    self._last_enemy = (pos_x + ddx, pos_y + ddy)
                    if abs(ddx) + abs(ddy) <= 2:
                        action = move_toward(ddx, ddy)
                        self._on_mineral = _update_on_mineral(action, grid)
                        return action

        if self._last_enemy and energy >= 80:
            edx, edy = self._last_enemy[0] - pos_x, self._last_enemy[1] - pos_y
            if abs(edx) + abs(edy) > 0:
                action = move_toward(edx, edy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action
            self._last_enemy = None

        best = _best_mineral_dir(grid)
        if best:
            action = move_toward(*best)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        if self._memory:
            closest = min(self._memory,
                          key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
            dx, dy = closest[0] - pos_x, closest[1] - pos_y
            if abs(dx) + abs(dy) > 0:
                action = move_toward(dx, dy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action

        cdx, cdy = 50 - pos_x, 50 - pos_y
        if abs(cdx) + abs(cdy) > 6:
            action = move_toward(cdx, cdy)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        action = self._rng.choice(MOVE_ACTIONS)
        self._on_mineral = _update_on_mineral(action, grid)
        return action


# ---------------------------------------------------------------------------
# 외부에서 임포트할 봇 목록
# ---------------------------------------------------------------------------

SAMPLE_USER_BOTS: list[tuple[type, str]] = [
    (DuelistBot,    "유저_결투사"),
    (OptimizerBot,  "유저_최적화"),
    (AdaptorBot,    "유저_적응형"),
    (ShieldTankBot, "유저_탱커"),
]

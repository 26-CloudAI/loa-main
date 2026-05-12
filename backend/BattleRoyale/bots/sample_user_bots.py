"""
샘플 유저 봇 4종 — 보스봇 학습용 다양한 플레이 스타일 시뮬레이션

실제 유저가 승리를 목표로 짤 법한 전략을 구현.
콜드스타트 봇보다 훨씬 위협적이라 보스봇이 더 유의미한 학습 신호를 받는다.

주의: vision grid 중심(grid[2][2])은 항상 "ME"를 반환하므로
      현재 위치의 광물 여부는 _on_mineral 플래그로 추적한다.
      (이전 틱에 광물 칸으로 이동했으면 다음 틱에 MINE 실행)
"""

from __future__ import annotations

import random
from typing import Optional

from src.arena.bot_interface import BotInterface
from src.arena.types import Action


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

_CX, _CY = 2, 2  # 5×5 시야 중심

_DIRS_4 = [
    (0, -1, Action.MOVE_UP,    Action.ATTACK_UP),
    (0,  1, Action.MOVE_DOWN,  Action.ATTACK_DOWN),
    (-1, 0, Action.MOVE_LEFT,  Action.ATTACK_LEFT),
    (1,  0, Action.MOVE_RIGHT, Action.ATTACK_RIGHT),
]

_MOVE_TO_DELTA = {
    Action.MOVE_UP:    (0, -1),
    Action.MOVE_DOWN:  (0,  1),
    Action.MOVE_LEFT:  (-1, 0),
    Action.MOVE_RIGHT: (1,  0),
}


def _move_toward(dx: int, dy: int) -> str:
    if abs(dx) >= abs(dy):
        return Action.MOVE_RIGHT if dx > 0 else Action.MOVE_LEFT
    return Action.MOVE_DOWN if dy > 0 else Action.MOVE_UP


def _in_zone(pos_x, pos_y, zone_bounds) -> bool:
    min_x, min_y, max_x, max_y = zone_bounds
    return min_x <= pos_x <= max_x and min_y <= pos_y <= max_y


def _to_center(pos_x, pos_y, zone_bounds) -> str:
    min_x, min_y, max_x, max_y = zone_bounds
    cx, cy = (min_x + max_x) // 2, (min_y + max_y) // 2
    return _move_toward(cx - pos_x, cy - pos_y)


def _update_on_mineral(action: str, grid: list) -> bool:
    """이번 틱에 이동한 방향에 광물이 있으면 True (다음 틱 MINE 예약)."""
    delta = _MOVE_TO_DELTA.get(action)
    if delta is None:
        return False
    dx, dy = delta
    cell = grid[_CY + dy][_CX + dx]
    return cell in ("mineral", "mineral_rare")


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
# ---------------------------------------------------------------------------

class DuelistBot(BotInterface):
    """적을 추적·처치하는 전투형 봇."""

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

        # 존 밖 → 복귀
        if not _in_zone(pos_x, pos_y, zone_bounds):
            self._last_enemy = None
            self._on_mineral = False
            return _to_center(pos_x, pos_y, zone_bounds)

        # 에너지 위기 → 실드
        if energy <= 25:
            self._on_mineral = False
            return Action.SHIELD

        # 광물 위에 있으면 채굴
        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # 메모리 업데이트
        for dy in range(5):
            for dx in range(5):
                if dy == _CY and dx == _CX:
                    continue
                mx, my_c = pos_x + (dx - _CX), pos_y + (dy - _CY)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(mx, my_c)] = cell
                elif cell == "empty":
                    self._memory.pop((mx, my_c), None)

        # 인접 적 즉시 공격
        if energy >= 40:
            for adx, ady, _, atk in _DIRS_4:
                if grid[_CY + ady][_CX + adx] == "bot_enemy":
                    return atk

        # 시야 내 적 추적
        closest_enemy, closest_dist = None, 999
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == "bot_enemy":
                    dist = abs(dx - _CX) + abs(dy - _CY)
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_enemy = (dx - _CX, dy - _CY)
                        self._last_enemy = (pos_x + (dx - _CX), pos_y + (dy - _CY))

        if closest_enemy and energy >= 60:
            action = _move_toward(*closest_enemy)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        # 마지막 적 위치 추적
        if self._last_enemy and energy >= 80:
            edx = self._last_enemy[0] - pos_x
            edy = self._last_enemy[1] - pos_y
            if abs(edx) + abs(edy) > 0:
                action = _move_toward(edx, edy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action
            self._last_enemy = None

        # 광물 파밍 (에너지 낮거나 적 없을 때)
        best = _best_mineral_dir(grid)
        if best:
            action = _move_toward(*best)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        # 메모리 광물 추적
        if self._memory:
            closest = min(self._memory,
                          key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
            dx, dy = closest[0] - pos_x, closest[1] - pos_y
            if abs(dx) + abs(dy) > 0:
                action = _move_toward(dx, dy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action

        # 맵 중앙으로 (적 조우 확률 증가)
        cdx, cdy = 50 - pos_x, 50 - pos_y
        if abs(cdx) + abs(cdy) > 8:
            action = _move_toward(cdx, cdy)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        action = self._rng.choice([Action.MOVE_UP, Action.MOVE_DOWN,
                                   Action.MOVE_LEFT, Action.MOVE_RIGHT])
        self._on_mineral = _update_on_mineral(action, grid)
        return action


# ---------------------------------------------------------------------------
# 2. Optimizer — 효율 채굴 특화
# ---------------------------------------------------------------------------

class OptimizerBot(BotInterface):
    """광물 채굴 효율을 극대화하는 경제형 봇."""

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

        # 존 밖 → 복귀
        if not _in_zone(pos_x, pos_y, zone_bounds):
            self._on_mineral = False
            return _to_center(pos_x, pos_y, zone_bounds)

        # 에너지 극위기 → 실드
        if energy <= 20:
            self._on_mineral = False
            return Action.SHIELD

        # 광물 위에 있으면 채굴
        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # 메모리 업데이트
        for dy in range(5):
            for dx in range(5):
                if dy == _CY and dx == _CX:
                    continue
                mx, my_c = pos_x + (dx - _CX), pos_y + (dy - _CY)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(mx, my_c)] = cell
                elif cell == "empty":
                    self._memory.pop((mx, my_c), None)

        # 적이 인접하면 회피 (경제형이라 싸움 회피)
        enemy_dirs = [(adx, ady) for adx, ady, _, _ in _DIRS_4
                      if grid[_CY + ady][_CX + adx] == "bot_enemy"]
        if enemy_dirs and energy < 150:
            flee_dx = -sum(d[0] for d in enemy_dirs)
            flee_dy = -sum(d[1] for d in enemy_dirs)
            if flee_dx != 0 or flee_dy != 0:
                action = _move_toward(flee_dx, flee_dy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action

        # 시야 내 최고 가치 광물로 이동 (희귀 우선)
        best = _best_mineral_dir(grid)
        if best:
            action = _move_toward(*best)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        # 메모리 속 희귀 광물 추적
        if self._memory:
            rare = {k: v for k, v in self._memory.items() if v == "mineral_rare"}
            target = rare if rare else self._memory
            closest = min(target, key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
            dx, dy = closest[0] - pos_x, closest[1] - pos_y
            if abs(dx) + abs(dy) > 0:
                action = _move_toward(dx, dy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action

        action = self._rng.choice([Action.MOVE_UP, Action.MOVE_DOWN,
                                   Action.MOVE_LEFT, Action.MOVE_RIGHT])
        self._on_mineral = _update_on_mineral(action, grid)
        return action


# ---------------------------------------------------------------------------
# 3. Adaptor — 게임 단계별 전략 전환
# ---------------------------------------------------------------------------

class AdaptorBot(BotInterface):
    """초반 채굴 → 중반 균형 → 후반 전투로 전환하는 적응형 봇."""

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

        # 존 밖 → 복귀
        if not _in_zone(pos_x, pos_y, zone_bounds):
            self._last_enemy = None
            self._on_mineral = False
            return _to_center(pos_x, pos_y, zone_bounds)

        # 에너지 위기 → 실드
        if energy <= 30:
            self._on_mineral = False
            return Action.SHIELD

        # 광물 위에 있으면 채굴
        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # 메모리 업데이트
        for dy in range(5):
            for dx in range(5):
                if dy == _CY and dx == _CX:
                    continue
                mx, my_c = pos_x + (dx - _CX), pos_y + (dy - _CY)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(mx, my_c)] = cell
                elif cell == "empty":
                    self._memory.pop((mx, my_c), None)

        # 게임 단계 결정
        if tick < 60:
            phase = "farm"
        elif tick < 140:
            phase = "mix"
        else:
            phase = "fight"

        # --- 파밍 단계 ---
        if phase == "farm":
            # 적 인접 시 회피
            enemy_dirs = [(adx, ady) for adx, ady, _, _ in _DIRS_4
                          if grid[_CY + ady][_CX + adx] == "bot_enemy"]
            if enemy_dirs:
                flee_dx = -sum(d[0] for d in enemy_dirs)
                flee_dy = -sum(d[1] for d in enemy_dirs)
                if flee_dx != 0 or flee_dy != 0:
                    action = _move_toward(flee_dx, flee_dy)
                    self._on_mineral = _update_on_mineral(action, grid)
                    return action

        # --- 균형/전투 단계 ---
        else:
            if energy >= 60:
                for adx, ady, _, atk in _DIRS_4:
                    if grid[_CY + ady][_CX + adx] == "bot_enemy":
                        return atk

            for dy in range(5):
                for dx in range(5):
                    if grid[dy][dx] == "bot_enemy":
                        self._last_enemy = (pos_x + (dx - _CX), pos_y + (dy - _CY))
                        if phase == "fight" and energy >= 80 and self._my_rank(state) > 2:
                            action = _move_toward(dx - _CX, dy - _CY)
                            self._on_mineral = _update_on_mineral(action, grid)
                            return action

            if self._last_enemy and phase == "fight" and energy >= 100:
                edx = self._last_enemy[0] - pos_x
                edy = self._last_enemy[1] - pos_y
                if abs(edx) + abs(edy) > 0:
                    action = _move_toward(edx, edy)
                    self._on_mineral = _update_on_mineral(action, grid)
                    return action
                self._last_enemy = None

        # 공통: 시야 내 광물
        best = _best_mineral_dir(grid)
        if best:
            action = _move_toward(*best)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        # 메모리 광물
        if self._memory:
            rare = {k: v for k, v in self._memory.items() if v == "mineral_rare"}
            target = rare if rare else self._memory
            closest = min(target, key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
            dx, dy = closest[0] - pos_x, closest[1] - pos_y
            if abs(dx) + abs(dy) > 0:
                action = _move_toward(dx, dy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action

        action = self._rng.choice([Action.MOVE_UP, Action.MOVE_DOWN,
                                   Action.MOVE_LEFT, Action.MOVE_RIGHT])
        self._on_mineral = _update_on_mineral(action, grid)
        return action


# ---------------------------------------------------------------------------
# 4. ShieldTank — 실드 소모전 특화
# ---------------------------------------------------------------------------

class ShieldTankBot(BotInterface):
    """실드 사이클을 활용한 지구전 특화 봇."""

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

        # 존 밖 → 복귀
        if not _in_zone(pos_x, pos_y, zone_bounds):
            self._on_mineral = False
            return _to_center(pos_x, pos_y, zone_bounds)

        # 광물 위에 있으면 채굴
        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # 메모리 업데이트
        for dy in range(5):
            for dx in range(5):
                if dy == _CY and dx == _CX:
                    continue
                mx, my_c = pos_x + (dx - _CX), pos_y + (dy - _CY)
                cell = grid[dy][dx]
                if cell in ("mineral", "mineral_rare"):
                    self._memory[(mx, my_c)] = cell
                elif cell == "empty":
                    self._memory.pop((mx, my_c), None)

        # 적 인접: 실드 → 카운터 공격 사이클
        enemy_adj = any(grid[_CY + ady][_CX + adx] == "bot_enemy"
                        for adx, ady, _, _ in _DIRS_4)
        if enemy_adj:
            if self._shield_cd == 0 and energy >= 60:
                self._shield_cd = 3
                return Action.SHIELD
            if energy >= 40:
                for adx, ady, _, atk in _DIRS_4:
                    if grid[_CY + ady][_CX + adx] == "bot_enemy":
                        return atk

        # 에너지 낮으면 긴급 채굴
        if energy < 60:
            # 인접 광물로 이동 후 다음 틱 채굴
            for adx, ady, mv, _ in _DIRS_4:
                if grid[_CY + ady][_CX + adx] in ("mineral", "mineral_rare"):
                    self._on_mineral = True
                    return mv
            if self._memory:
                closest = min(self._memory,
                              key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
                dx, dy = closest[0] - pos_x, closest[1] - pos_y
                if abs(dx) + abs(dy) > 0:
                    action = _move_toward(dx, dy)
                    self._on_mineral = _update_on_mineral(action, grid)
                    return action
            return Action.SHIELD

        # 인접 적 공격
        for adx, ady, _, atk in _DIRS_4:
            if grid[_CY + ady][_CX + adx] == "bot_enemy":
                return atk

        # 적 추적
        for dy in range(5):
            for dx in range(5):
                if grid[dy][dx] == "bot_enemy":
                    ddx, ddy = dx - _CX, dy - _CY
                    self._last_enemy = (pos_x + ddx, pos_y + ddy)
                    if abs(ddx) + abs(ddy) <= 2:
                        action = _move_toward(ddx, ddy)
                        self._on_mineral = _update_on_mineral(action, grid)
                        return action

        if self._last_enemy and energy >= 80:
            edx = self._last_enemy[0] - pos_x
            edy = self._last_enemy[1] - pos_y
            if abs(edx) + abs(edy) > 0:
                action = _move_toward(edx, edy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action
            self._last_enemy = None

        # 광물 파밍
        best = _best_mineral_dir(grid)
        if best:
            action = _move_toward(*best)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        if self._memory:
            closest = min(self._memory,
                          key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
            dx, dy = closest[0] - pos_x, closest[1] - pos_y
            if abs(dx) + abs(dy) > 0:
                action = _move_toward(dx, dy)
                self._on_mineral = _update_on_mineral(action, grid)
                return action

        # 중앙 장악
        cdx, cdy = 50 - pos_x, 50 - pos_y
        if abs(cdx) + abs(cdy) > 6:
            action = _move_toward(cdx, cdy)
            self._on_mineral = _update_on_mineral(action, grid)
            return action

        action = self._rng.choice([Action.MOVE_UP, Action.MOVE_DOWN,
                                   Action.MOVE_LEFT, Action.MOVE_RIGHT])
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

"""
ClaudeBot — 보스전 하 난이도 대응 봇

핵심 전략:
  1. 희귀 광물 우선 채굴로 빠른 에너지 확보
  2. 보스가 인접 + 공격 가능 상태(에너지>60)일 때 완전 쉴드(100% 차단)
  3. 보스 에너지 낮아지면 역공격 + 라스트힛
  4. 자기장 안전 관리
"""

from __future__ import annotations

import random
from typing import Optional

from core.bot_interface import BotInterface
from core.types import Action, CellType
from bots.utils import CX, CY, ADJACENT_DIRS, MOVE_ACTIONS, move_toward, flee

_ENEMY    = CellType.BOT_ENEMY.value
_MIN      = CellType.MINERAL.value
_MIN_R    = CellType.MINERAL_RARE.value
_MINERALS = (_MIN, _MIN_R)

# 보스봇 하 난이도 임계값 (상대 예측용)
_BOSS_ATTACK_THR  = 60   # 보스가 공격하는 최소 에너지
_BOSS_HUNT_THR    = 100  # 보스가 추적 시작하는 에너지

# 내 전략 임계값
_MY_ATTACK_SAFE   = 50   # 내 최소 공격 에너지 (공격 후 여유분 확보)
_LASTBIT          = 25   # 상대 에너지 이하면 무조건 공격(한방컷)
_EMERGENCY_MINE   = 60   # 이 이하면 채굴 우선

_ZONE_BUFFER = 3  # 자기장 경계 N칸 이내면 중앙으로


class ClaudeBot(BotInterface):
    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id  = bot_id
        self._rng     = random.Random(seed)
        self._on_mineral = False
        self._memory: dict[tuple[int, int], str] = {}

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        """희귀 광물 군락 근처에 스폰."""
        rares = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]
        if not rares:
            return None
        tx, ty = self._rng.choice(rares)
        w, h = map_info["width"], map_info["height"]
        margin = 3
        for dx, dy in self._rng.sample(
            [(dx, dy) for dx in range(-2, 3) for dy in range(-2, 3)], 25
        ):
            nx, ny = tx + dx, ty + dy
            if margin <= nx < w - margin and margin <= ny < h - margin:
                return (nx, ny)
        return (tx, ty)

    def get_action(self, state: dict) -> str:
        my        = state["my_bot"]
        pos_x, pos_y = my["position"]
        energy    = my["energy"]
        grid      = state["vision"]["grid"]
        tick      = state["tick"]
        zone      = state.get("zone_bounds", (0, 0, 99, 99))
        other     = state.get("other_bots", [])

        # ── 맵 메모리 업데이트 ────────────────────────────────
        for dy in range(5):
            for dx in range(5):
                cell = grid[dy][dx]
                mx, my_ = pos_x + (dx - CX), pos_y + (dy - CY)
                if cell in _MINERALS:
                    self._memory[(mx, my_)] = cell
                elif cell == _ENEMY:
                    self._memory.pop((mx, my_), None)
                elif cell == "empty":
                    self._memory.pop((mx, my_), None)

        # ── 지난 틱 광물 위에 이동했으면 채굴 ─────────────────
        if self._on_mineral:
            self._on_mineral = False
            return Action.MINE

        # ── 자기장 위기: 안전구역 밖이거나 경계 근접 ────────────
        min_x, min_y, max_x, max_y = zone
        in_zone = min_x <= pos_x <= max_x and min_y <= pos_y <= max_y
        near_edge = (
            in_zone and (
                pos_x - min_x < _ZONE_BUFFER or max_x - pos_x < _ZONE_BUFFER or
                pos_y - min_y < _ZONE_BUFFER or max_y - pos_y < _ZONE_BUFFER
            )
            and tick >= 151  # boss_battle_config phase2 시작
        )
        if not in_zone or near_edge:
            cx = (min_x + max_x) // 2
            cy = (min_y + max_y) // 2
            return move_toward(cx - pos_x, cy - pos_y)

        # ── 인접 적 분석 ──────────────────────────────────────
        adj_enemies: list[tuple[int, int, str]] = []  # (dx, dy, attack_action)
        for dx, dy, move_act, attack_act in ADJACENT_DIRS:
            if grid[CY + dy][CX + dx] == _ENEMY:
                adj_enemies.append((dx, dy, attack_act))

        # 인접 적이 있을 때
        if adj_enemies:
            # 상대 에너지 조회 (other_bots 기반)
            enemy_energy_map = {
                (b["position"][0], b["position"][1]): b["energy"]
                for b in other
            }

            for edx, edy, attack_act in adj_enemies:
                enemy_pos = (pos_x + edx, pos_y + edy)
                enemy_nrg = enemy_energy_map.get(enemy_pos, 999)

                # 1) 라스트힛: 상대 에너지 25 이하 → 무조건 킬
                if enemy_nrg <= _LASTBIT and energy >= 5:
                    return attack_act

                # 2) 보스가 공격해올 것 같을 때(에너지>60) + 내 에너지 충분 → 쉴드
                if enemy_nrg > _BOSS_ATTACK_THR and energy >= 3:
                    return Action.SHIELD

                # 3) 보스 에너지 낮아서 공격 안 함 + 내 에너지 충분 → 공격
                if energy >= _MY_ATTACK_SAFE:
                    return attack_act

        # ── 에너지 위기: 채굴 우선 ────────────────────────────
        if energy < _EMERGENCY_MINE:
            mine_act = self._find_mine_action(grid, pos_x, pos_y)
            if mine_act:
                return mine_act
            # 광물이 없으면 현재 위치 채굴 시도
            return Action.STAY

        # ── 보스 시야 내 → 에너지 이점 있으면 추적, 없으면 채굴 ─
        boss_target = self._find_nearest_enemy(grid)
        if boss_target:
            bx, by = boss_target
            enemy_energy_map = {
                (b["position"][0], b["position"][1]): b["energy"]
                for b in other
            }
            boss_nrg = enemy_energy_map.get(
                (pos_x + bx, pos_y + by), 999
            )

            # 내가 에너지 우위이고 추적 거리가 가까우면 접근
            if energy > boss_nrg + 50 and abs(bx) + abs(by) <= 3:
                return move_toward(bx, by)

            # 보스가 추적 모드(에너지>100)고 나도 에너지 충분하면 기다리며 채굴
            if boss_nrg > _BOSS_HUNT_THR and energy < boss_nrg:
                mine_act = self._find_mine_action(grid, pos_x, pos_y)
                if mine_act:
                    return mine_act

        # ── 기본: 희귀 광물 우선 채굴 이동 ─────────────────────
        mine_act = self._find_mine_action(grid, pos_x, pos_y)
        if mine_act:
            return mine_act

        # 메모리 기반 이동
        if self._memory:
            best, best_d = None, 9999
            for (mx, my_), mtype in self._memory.items():
                d = abs(mx - pos_x) + abs(my_ - pos_y)
                # 희귀 광물 우선
                prio = d - (5 if mtype == _MIN_R else 0)
                if prio < best_d:
                    best_d, best = prio, (mx - pos_x, my_ - pos_y)
            if best:
                return move_toward(*best)

        return self._rng.choice(MOVE_ACTIONS)

    # ── 헬퍼 메서드 ───────────────────────────────────────────

    def _find_mine_action(self, grid, pos_x: int, pos_y: int) -> Optional[str]:
        """광물 인접 이동 또는 현재 위치 채굴. 희귀 우선."""
        # 현재 위치 광물
        if grid[CY][CX] in _MINERALS:
            return Action.MINE

        # 인접 희귀 광물 우선
        for dx, dy, move_act, _ in ADJACENT_DIRS:
            if grid[CY + dy][CX + dx] == _MIN_R:
                self._on_mineral = True
                return move_act

        # 인접 일반 광물
        for dx, dy, move_act, _ in ADJACENT_DIRS:
            if grid[CY + dy][CX + dx] == _MIN:
                self._on_mineral = True
                return move_act

        # 시야 내 가장 가까운 희귀 광물 방향
        best, best_d = None, 9999
        for gy in range(5):
            for gx in range(5):
                cell = grid[gy][gx]
                if cell in _MINERALS:
                    d = abs(gx - CX) + abs(gy - CY)
                    prio = d - (3 if cell == _MIN_R else 0)
                    if prio < best_d:
                        best_d, best = prio, (gx - CX, gy - CY)
        if best:
            return move_toward(*best)
        return None

    def _find_nearest_enemy(self, grid) -> Optional[tuple[int, int]]:
        """시야 내 가장 가까운 적 상대 위치 (dx, dy) 반환."""
        best, best_d = None, 9999
        for gy in range(5):
            for gx in range(5):
                if grid[gy][gx] == _ENEMY:
                    d = abs(gx - CX) + abs(gy - CY)
                    if d < best_d:
                        best_d, best = d, (gx - CX, gy - CY)
        return best

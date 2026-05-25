"""
룰베이스 보스봇 (하/중 난이도)

RuleBossEasyBot   : 하 난이도 — 에너지 확보 후 추적·전투, 위험 시 flee 이탈
RuleBossMediumBot : 중 난이도 — 공격 최우선, 라스트힛, 자기장 예측 이동
"""

from __future__ import annotations

import random
from typing import Optional

from core.bot_interface import BotInterface
from core.types import Action, CellType, DIRECTION_DELTA, action_to_direction
from bots.utils import CX, CY, ADJACENT_DIRS, MOVE_ACTIONS, move_toward, flee

# ── 셀 타입 상수 (CellType enum 기준) ─────────────────────────────────────────
_ENEMY    = CellType.BOT_ENEMY.value
_MIN      = CellType.MINERAL.value
_MIN_R    = CellType.MINERAL_RARE.value
_MINERALS = (_MIN, _MIN_R)

# ── 게임 설정 상수 (config.py 기준) ───────────────────────────────────────────
# 주의: types.py Bot.apply_damage는 shield 시 damage//2 적용.
#       config.shield_reduction=1.0은 현재 코드에서 미사용 (불일치 버그 별도 수정 필요).
_ATTACK_DAMAGE = 25   # CombatConfig.attack_damage
_ATTACK_COST   = 5    # ActionCost.attack
_LASTBIT       = _ATTACK_DAMAGE  # 상대 에너지 이 이하면 한 방 처치 → 무조건 공격

# ── 에너지 임계값 ──────────────────────────────────────────────────────────────
_EASY_ATTACK   = 60               # 하: 인접 적 공격 최소 에너지
_EASY_HUNT     = 120              # 하: 적 추적 시작 에너지
_EASY_EMERGENCY = 100             # 하: 긴급 채굴 에너지 (50→100: 광물 부족 전에 먼저 채굴)
_EASY_TIMEOUT  = 5                # 하: 적 시야 이탈 후 추적 포기 틱
_EASY_WANDER_INTERVAL = 30        # 하: 광물 없을 때 탐색 목표 갱신 주기

_MED_ATTACK    = 40               # 중: 인접 적 공격 최소 에너지
_MED_HUNT      = 70               # 중: 적 추적 시작 에너지
_MED_EMERGENCY = 40               # 중: 긴급 채굴 에너지
_MED_TIMEOUT   = 10               # 중: 적 시야 이탈 후 추적 포기 틱

# ── 자기장 예측 (boss_battle_config 기준) ─────────────────────────────────────
_ZONE_P2_START    = 151  # phase1_end=150
_ZONE_P3_START    = 321  # phase2_end=320
_ZONE_P2_INTERVAL = 8    # phase2_shrink_interval=8
_ZONE_P3_INTERVAL = 5    # phase3_shrink_interval=5
_ZONE_BUFFER      = 2   # 경계에서 N칸 이내면 미리 중앙으로

# ── 광물 메모리 만료 ───────────────────────────────────────────────────────────
_MIN_EXPIRE = 80    # 시야 밖 광물을 N틱 이상 지나면 stale 처리

# ── 인접 방향 빠른 조회 (모듈 레벨, 매 틱 생성 방지) ─────────────────────────
_ADJ_MAP: dict[tuple[int, int], tuple] = {
    (adx, ady): (mv, atk) for adx, ady, mv, atk in ADJACENT_DIRS
}


# ── 공통 유틸 ─────────────────────────────────────────────────────────────────

def _in_zone(x: int, y: int, zone: tuple) -> bool:
    return zone[0] <= x <= zone[2] and zone[1] <= y <= zone[3]


def _zone_center(zone: tuple) -> tuple[int, int]:
    return (zone[0] + zone[2]) // 2, (zone[1] + zone[3]) // 2


def _needs_zone_retreat(pos_x: int, pos_y: int, zone: tuple, tick: int) -> bool:
    """자기장 탈출 또는 예측 이동이 필요한지. Phase 2+ 경계 버퍼 포함."""
    min_x, min_y, max_x, max_y = zone
    if not (min_x <= pos_x <= max_x and min_y <= pos_y <= max_y):
        return True
    # Phase 2 이후: 경계 BUFFER 이내이면 미리 중앙으로 이동
    if tick >= _ZONE_P2_START:
        buf = _ZONE_BUFFER
        if (pos_x - min_x < buf or max_x - pos_x < buf or
                pos_y - min_y < buf or max_y - pos_y < buf):
            return True
    return False


def _safe_flee(adx: int, ady: int, pos_x: int, pos_y: int, zone: tuple) -> str:
    """적에게서 zone 안으로 이탈. zone 탈출 위험 시 zone 중앙 방향으로 대체."""
    zx, zy = _zone_center(zone)
    for candidate in (flee(adx, ady), move_toward(zx - pos_x, zy - pos_y)):
        direction = action_to_direction(candidate)
        if direction is None:
            continue
        fdx, fdy = DIRECTION_DELTA[direction]
        if _in_zone(pos_x + fdx, pos_y + fdy, zone):
            return candidate
    return Action.SHIELD.value


def _scan_grid(
    grid: list, pos_x: int, pos_y: int
) -> tuple[str, list, list, Optional[tuple[int, int]]]:
    """5×5 그리드를 한 번만 순회해서 (발밑셀, 인접적, 시야적, 최적광물상대좌표)를 반환."""
    foot = grid[CY][CX]
    adj_enemies: list[tuple] = []
    vis_enemies: list[tuple[int, int]] = []
    best_min: Optional[tuple[int, int]] = None
    best_min_score = -1

    for dy in range(5):
        for dx in range(5):
            cell = grid[dy][dx]
            rdx, rdy = dx - CX, dy - CY

            if cell == _ENEMY:
                vis_enemies.append((pos_x + rdx, pos_y + rdy))
                entry = _ADJ_MAP.get((rdx, rdy))
                if entry:
                    adj_enemies.append((rdx, rdy, entry[0], entry[1]))

            elif cell in _MINERALS:
                score = 20 if cell == _MIN_R else 5
                dist = abs(rdx) + abs(rdy)
                s = score - dist
                if s > best_min_score:
                    best_min_score = s
                    best_min = (rdx, rdy)

    return foot, adj_enemies, vis_enemies, best_min


def _update_mineral_mem(
    mem: dict, grid: list, pos_x: int, pos_y: int, tick: int
) -> None:
    """광물 메모리 업데이트. empty는 즉시 제거, _MIN_EXPIRE 틱 초과분 만료."""
    for dy in range(5):
        for dx in range(5):
            mx, my_c = pos_x + (dx - CX), pos_y + (dy - CY)
            cell = grid[dy][dx]
            if cell in _MINERALS:
                mem[(mx, my_c)] = (cell, tick)
            elif cell == "empty":
                mem.pop((mx, my_c), None)

    # stale 만료 (시야 밖 채굴된 광물 제거)
    for k in [k for k, (_, t) in mem.items() if tick - t > _MIN_EXPIRE]:
        del mem[k]


def _emergency_mine(
    grid: list, pos_x: int, pos_y: int, mem: dict, foot: str
) -> str:
    """에너지 위기: 가장 가까운 광물로 이동. 없으면 STAY(비용 1 절약)."""
    # 현재 위치가 광물 메모리에 있으면 채굴 (그리드에선 "ME"로 보임)
    if (pos_x, pos_y) in mem:
        mem.pop((pos_x, pos_y), None)
        return Action.MINE.value
    if foot in _MINERALS:
        return Action.MINE.value
    for adx, ady, mv, _ in ADJACENT_DIRS:
        if grid[CY + ady][CX + adx] in _MINERALS:
            return mv
    # 시야 내 가장 가까운 광물 (점수 아닌 거리 우선)
    best_dist, best_rel = 999, None
    for dy in range(5):
        for dx in range(5):
            if grid[dy][dx] in _MINERALS:
                d = abs(dx - CX) + abs(dy - CY)
                if d < best_dist:
                    best_dist = d
                    best_rel = (dx - CX, dy - CY)
    if best_rel:
        return move_toward(*best_rel, on_spot=Action.MINE.value)
    if mem:
        closest = min(mem, key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
        return move_toward(closest[0] - pos_x, closest[1] - pos_y, on_spot=Action.MINE.value)
    return Action.STAY.value


def _pick_attack(
    adj_enemies: list, pos_x: int, pos_y: int, pos_to_energy: dict
) -> str:
    """인접 적 중 에너지 가장 낮은 적 공격 방향 반환."""
    best_atk = adj_enemies[0][3]
    min_e = 9999
    for adx, ady, _, atk in adj_enemies:
        e = pos_to_energy.get((pos_x + adx, pos_y + ady), 500)
        if e < min_e:
            min_e = e
            best_atk = atk
    return best_atk


def _try_lastbit(
    adj_enemies: list, pos_x: int, pos_y: int, energy: int, pos_to_energy: dict
) -> Optional[str]:
    """인접 적 중 라스트힛 가능한 적 공격. 없으면 None.
    engine이 ATTACK_COST 차감 후 사망 판정하면서 공격을 취소하므로
    실제로 적중하려면 energy > ATTACK_COST이어야 한다."""
    if energy <= _ATTACK_COST:
        return None
    for adx, ady, _, atk in adj_enemies:
        if pos_to_energy.get((pos_x + adx, pos_y + ady), 999) <= _LASTBIT:
            return atk
    return None


# ── 하 난이도 ──────────────────────────────────────────────────────────────────

class RuleBossEasyBot(BotInterface):
    """
    하 난이도 보스.
    에너지 확보 후 적 추적·공격. 저에너지 + 인접 적이면 flee 이탈.
    라스트힛(상대 에너지 ≤ 25) 시 에너지 임계값 무시하고 공격.
    """

    def __init__(self, bot_id: str, seed: Optional[int] = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._mineral_mem: dict[tuple[int, int], tuple[str, int]] = {}
        self._last_enemy_pos: Optional[tuple[int, int]] = None
        self._enemy_lost_ticks = 0
        self._wander_target: Optional[tuple[int, int]] = None
        self._wander_set_tick: int = -_EASY_WANDER_INTERVAL
        self._pending_mine: bool = False  # 인접 광물로 이동한 다음 틱에 채굴

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        """희귀 광물 군락 근처에 스폰 (중 보스보다 약간 멀리 — 3~7칸)."""
        w, h = map_info["width"], map_info["height"]
        rare = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]
        if not rare:
            # 희귀 광물 없으면 맵 중앙 근처
            return (w // 2 + self._rng.randint(-5, 5), h // 2 + self._rng.randint(-5, 5))
        # 주변에 희귀 광물이 가장 많은 군락 중심 선택
        best = max(
            rare,
            key=lambda r: sum(1 for ox, oy in rare if abs(ox - r[0]) + abs(oy - r[1]) <= 8),
        )
        dist = self._rng.randint(3, 7)  # 중 보스(2~5)보다 조금 멀리
        dx, dy = self._rng.choice([(dist, 0), (-dist, 0), (0, dist), (0, -dist)])
        return (
            max(3, min(w - 4, best[0] + dx)),
            max(3, min(h - 4, best[1] + dy)),
        )

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        tick = state.get("tick", 0)
        other_bots = state.get("other_bots", [])

        foot, adj_enemies, vis_enemies, best_mineral = _scan_grid(grid, pos_x, pos_y)
        _update_mineral_mem(self._mineral_mem, grid, pos_x, pos_y, tick)

        zone = state.get("zone_bounds", (0, 0, 99, 99))
        pos_to_e = {(b["position"][0], b["position"][1]): b["energy"] for b in other_bots}

        # ── 0. 직전 틱에 광물 위로 이동했으면 채굴 ────────────────────────────
        if self._pending_mine:
            self._pending_mine = False
            # 현재 위치가 메모리에 있었다면 즉시 채굴, 아니면 주변 확인
            if (pos_x, pos_y) in self._mineral_mem or any(
                grid[CY + dy][CX + dx] in _MINERALS
                for dx, dy, _, _ in ADJACENT_DIRS
                if 0 <= CX + dx < 5 and 0 <= CY + dy < 5
            ):
                return Action.MINE.value
            # 직전 이동 목적지에 광물이 없었을 수도 있음 (재생 전) → 계속 진행

        # ── 1. 자기장 탈출 / 예측 이동 ────────────────────────────────────────
        if _needs_zone_retreat(pos_x, pos_y, zone, tick):
            self._last_enemy_pos = None
            self._enemy_lost_ticks = 0
            zx, zy = _zone_center(zone)
            return move_toward(zx - pos_x, zy - pos_y)

        # ── 2. 시야 내 적 위치 갱신 ──────────────────────────────────────────
        if vis_enemies:
            nearest = min(vis_enemies, key=lambda e: abs(e[0] - pos_x) + abs(e[1] - pos_y))
            self._last_enemy_pos = nearest
            self._enemy_lost_ticks = 0
        else:
            self._enemy_lost_ticks += 1
            if self._enemy_lost_ticks > _EASY_TIMEOUT:
                self._last_enemy_pos = None

        # ── 3. 인접 적 처리 ──────────────────────────────────────────────────
        if adj_enemies:
            # 라스트힛: 상대 에너지 ≤ LASTBIT이면 에너지 무관 공격
            lastbit = _try_lastbit(adj_enemies, pos_x, pos_y, energy, pos_to_e)
            if lastbit:
                return lastbit

            if energy >= _EASY_ATTACK:
                return _pick_attack(adj_enemies, pos_x, pos_y, pos_to_e)

            # 에너지 부족 → zone 안으로 flee
            adx, ady, _, _ = adj_enemies[0]
            return _safe_flee(adx, ady, pos_x, pos_y, zone)

        # ── 4. 긴급 채굴 ────────────────────────────────────────────────────
        if energy < _EASY_EMERGENCY:
            return _emergency_mine(grid, pos_x, pos_y, self._mineral_mem, foot)

        # ── 5. 발 아래 광물 채굴 (에너지 여유 없을 때) ───────────────────────
        if energy < _EASY_HUNT and foot in _MINERALS:
            return Action.MINE.value

        # ── 6. 적 추적 (에너지 충분, zone-safe 목적지) ───────────────────────
        if energy >= _EASY_HUNT and self._last_enemy_pos:
            tx, ty = self._last_enemy_pos
            if _in_zone(tx, ty, zone):
                edx, edy = tx - pos_x, ty - pos_y
                if abs(edx) + abs(edy) > 0:
                    return move_toward(edx, edy)
            self._last_enemy_pos = None

        # ── 7. 현재 위치 광물 채굴 (메모리 기반 — 그리드는 "ME"로 표시됨) ──────
        if (pos_x, pos_y) in self._mineral_mem:
            self._mineral_mem.pop((pos_x, pos_y), None)
            return Action.MINE.value

        # ── 8. 시야 내 광물 접근 ────────────────────────────────────────────
        if best_mineral:
            rdx, rdy = best_mineral
            dist = abs(rdx) + abs(rdy)
            if dist == 0:
                return Action.MINE.value
            if dist == 1:
                # 인접 — 이동 후 다음 틱 채굴
                self._pending_mine = True
            return move_toward(rdx, rdy)

        # ── 9. 기억 속 광물 추적 ────────────────────────────────────────────
        if self._mineral_mem:
            closest = min(
                self._mineral_mem,
                key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y),
            )
            cdx, cdy = closest[0] - pos_x, closest[1] - pos_y
            if abs(cdx) + abs(cdy) == 1:
                self._pending_mine = True
            return move_toward(cdx, cdy, on_spot=Action.MINE.value)

        # ── 10. 맵 탐색 이동 (광물 없을 때 새 구역 스윕) ──────────────────────
        min_x, min_y, max_x, max_y = zone
        at_target = (
            self._wander_target is not None
            and abs(self._wander_target[0] - pos_x) + abs(self._wander_target[1] - pos_y) < 5
        )
        if (self._wander_target is None
                or at_target
                or tick - self._wander_set_tick > _EASY_WANDER_INTERVAL):
            tx = self._rng.randint(min_x + 5, max(min_x + 6, max_x - 5))
            ty = self._rng.randint(min_y + 5, max(min_y + 6, max_y - 5))
            self._wander_target = (tx, ty)
            self._wander_set_tick = tick
        return move_toward(self._wander_target[0] - pos_x, self._wander_target[1] - pos_y)


# ── 중 난이도 ──────────────────────────────────────────────────────────────────

class RuleBossMediumBot(BotInterface):
    """
    중 난이도 보스.
    공격 최우선, 라스트힛, 저에너지 적 우선 타겟.
    자기장 예측 이동, zone-safe 추적, 복수 적 위치 기억.
    """

    def __init__(self, bot_id: str, seed: Optional[int] = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._mineral_mem: dict[tuple[int, int], tuple[str, int]] = {}
        # {id: (abs_pos, energy, lost_ticks)}
        self._enemy_mem: dict[str, tuple[tuple[int, int], int, int]] = {}

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        """희귀 광물 군락 근처에 매복 스폰."""
        w, h = map_info["width"], map_info["height"]
        rare = [(m["x"], m["y"]) for m in map_info["minerals"] if m["rare"]]
        if not rare:
            return (w // 2, h // 2)
        best = max(
            rare,
            key=lambda r: sum(1 for ox, oy in rare if abs(ox - r[0]) + abs(oy - r[1]) <= 8),
        )
        dist = self._rng.randint(2, 5)
        dx, dy = self._rng.choice([(dist, 0), (-dist, 0), (0, dist), (0, -dist)])
        return (
            max(2, min(w - 3, best[0] + dx)),
            max(2, min(h - 3, best[1] + dy)),
        )

    def get_action(self, state: dict) -> str:
        my = state["my_bot"]
        grid = state["vision"]["grid"]
        pos_x, pos_y = my["position"]
        energy = my["energy"]
        tick = state.get("tick", 0)
        other_bots = state.get("other_bots", [])

        foot, adj_enemies, vis_enemies, best_mineral = _scan_grid(grid, pos_x, pos_y)
        _update_mineral_mem(self._mineral_mem, grid, pos_x, pos_y, tick)
        self._update_enemy_mem(other_bots)

        zone = state.get("zone_bounds", (0, 0, 99, 99))
        pos_to_e = {(b["position"][0], b["position"][1]): b["energy"] for b in other_bots}

        # ── 1. 자기장 탈출 / 예측 이동 ────────────────────────────────────────
        if _needs_zone_retreat(pos_x, pos_y, zone, tick):
            zx, zy = _zone_center(zone)
            return move_toward(zx - pos_x, zy - pos_y)

        # ── 2. 인접 적 처리 (라스트힛·flee는 emergency보다 우선) ──────────────
        # 인접 전투 판단은 에너지 수준과 무관하게 항상 먼저 결정한다.
        # 라스트힛: 킬로 에너지 회수가 긴급 채굴보다 이득일 수 있음.
        # flee: 인접한 채 emergency mine하면 그대로 맞아 죽을 수 있음.
        if adj_enemies:
            lastbit = _try_lastbit(adj_enemies, pos_x, pos_y, energy, pos_to_e)
            if lastbit:
                return lastbit

            if energy >= _MED_ATTACK:
                return _pick_attack(adj_enemies, pos_x, pos_y, pos_to_e)

            # 에너지 부족 → flee (emergency mine보다 먼저 이탈)
            adx, ady, _, _ = adj_enemies[0]
            return _safe_flee(adx, ady, pos_x, pos_y, zone)

        # ── 3. 긴급 채굴 (인접 적 없을 때만) ────────────────────────────────
        if energy < _MED_EMERGENCY:
            return _emergency_mine(grid, pos_x, pos_y, self._mineral_mem, foot)

        # ── 4. 시야 내 적 추적 (에너지 충분, zone-safe) ───────────────────────
        if energy >= _MED_HUNT:
            target = self._pick_chase_target(other_bots, vis_enemies, pos_x, pos_y, zone)
            if target:
                edx, edy = target[0] - pos_x, target[1] - pos_y
                if abs(edx) + abs(edy) > 0:
                    return move_toward(edx, edy)

        # ── 5. 현재 위치 광물 채굴 (메모리 기반) ────────────────────────────
        if (pos_x, pos_y) in self._mineral_mem:
            self._mineral_mem.pop((pos_x, pos_y), None)
            return Action.MINE.value
        if foot in _MINERALS:
            return Action.MINE.value

        # ── 6. 기억 속 적 추적 (에너지 충분, zone-safe) ──────────────────────
        if energy >= _MED_HUNT and self._enemy_mem:
            mem_target = self._pick_memory_target(pos_x, pos_y, zone)
            if mem_target:
                edx, edy = mem_target[0] - pos_x, mem_target[1] - pos_y
                if abs(edx) + abs(edy) > 0:
                    return move_toward(edx, edy)

        # ── 7. 시야 내 광물 파밍 ────────────────────────────────────────────
        if best_mineral:
            rdx, rdy = best_mineral
            if abs(rdx) + abs(rdy) == 1:
                # 인접 → 이동 후 다음 틱 즉시 채굴을 위해 메모리 기반으로 처리
                pass  # move_toward 후 step 5에서 잡힘
            return move_toward(rdx, rdy, on_spot=Action.MINE.value)

        # ── 8. 기억 속 희귀 광물 우선 파밍 ─────────────────────────────────
        if self._mineral_mem:
            rare_m = {k: v for k, v in self._mineral_mem.items() if v[0] == _MIN_R}
            pool = rare_m if rare_m else self._mineral_mem
            closest = min(pool, key=lambda m: abs(m[0] - pos_x) + abs(m[1] - pos_y))
            return move_toward(closest[0] - pos_x, closest[1] - pos_y,
                               on_spot=Action.MINE.value)

        # ── 9. 자기장 중앙 공격 위치 확보 ───────────────────────────────────
        zx, zy = _zone_center(zone)
        if abs(zx - pos_x) + abs(zy - pos_y) > 5:
            return move_toward(zx - pos_x, zy - pos_y)
        return self._rng.choice(MOVE_ACTIONS)

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────────

    def _update_enemy_mem(self, other_bots: list) -> None:
        """시야 내 적 기억 갱신. 이탈 후 _MED_TIMEOUT틱 유지 후 삭제."""
        visible_ids: set[str] = set()
        for bot in other_bots:
            bid = bot["id"]
            self._enemy_mem[bid] = (
                (bot["position"][0], bot["position"][1]),
                bot["energy"],
                0,
            )
            visible_ids.add(bid)

        for bid in list(self._enemy_mem):
            if bid in visible_ids:
                continue
            pos, e, lost = self._enemy_mem[bid]
            if lost + 1 > _MED_TIMEOUT:
                del self._enemy_mem[bid]
            else:
                self._enemy_mem[bid] = (pos, e, lost + 1)

    def _pick_chase_target(
        self,
        other_bots: list,
        vis_enemies: list,
        pos_x: int,
        pos_y: int,
        zone: tuple,
    ) -> Optional[tuple[int, int]]:
        """시야 내 가장 취약한(저에너지·근거리) 적 위치. zone 밖 적은 무시."""
        if other_bots:
            best, best_score = None, -9999
            for bot in other_bots:
                bx, by = bot["position"]
                if not _in_zone(bx, by, zone):
                    continue
                dist = abs(bx - pos_x) + abs(by - pos_y)
                score = (1000 - bot["energy"]) - dist * 8
                if score > best_score:
                    best_score = score
                    best = (bx, by)
            return best

        # other_bots 없으면 grid의 가장 가까운 zone 내 적
        best, best_dist = None, 999
        for ex, ey in vis_enemies:
            if not _in_zone(ex, ey, zone):
                continue
            d = abs(ex - pos_x) + abs(ey - pos_y)
            if d < best_dist:
                best_dist = d
                best = (ex, ey)
        return best

    def _pick_memory_target(
        self, pos_x: int, pos_y: int, zone: tuple
    ) -> Optional[tuple[int, int]]:
        """기억 속 가장 취약한(저에너지·근거리·최근) 적. zone 밖 기억 무시."""
        best, best_score = None, -9999
        for bid, (bpos, benergy, lost) in self._enemy_mem.items():
            if not _in_zone(bpos[0], bpos[1], zone):
                continue
            dist = abs(bpos[0] - pos_x) + abs(bpos[1] - pos_y)
            # lost 패널티 강화: 오래될수록 신뢰도 급감
            score = (1000 - benergy) - dist * 6 - lost * 20
            if score > best_score:
                best_score = score
                best = bpos
        return best

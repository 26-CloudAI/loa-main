"""룰베이스 보스 공통 베이스 — 옛 rule_boss_bot.py 유틸·우선순위 트리 BR2 포팅.

매핑 원칙 (옛 → BR2):
- energy(max 999) → hp(max 200): 임계값 *절대값*을 유지 (옛 60 → BR2 60).
  비례 환산하면 의미가 깨짐 (옛 energy 60 ≒ "공격 가능한 여유" 인데 비례 환산 시 hp 12 = 거의 죽음).
- 옛 200 tick(20s) 매치 → BR2 1800 tick(180s): *시간 단위 임계값은 ×9*
  (TIMEOUT 5→45, MINERAL_EXPIRE 80→720, WANDER_INTERVAL 30→270).
- MINE 없음 → 코인은 위로 이동만 하면 자동 채집. 상자만 pickup.
- ATTACK_DAMAGE=25 한방킬 → BR2 적 hp ≤ 50 라스트힛.
- SHIELD → guard.
- vision.grid(5×5) → vision.enemies/nodes/chests (절대 좌표).
- zone_bounds(rect) → zone.active/center/radius + target_*.
"""
from __future__ import annotations

import math
import random
from typing import Any, Optional

from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot


# ── 게임 룰 명세 (Godot balance.gd 참조) ─────────────────────────────────
MELEE_RANGE = 60.0
RANGED_RANGE = 400.0
EDGE_MARGIN = 100.0
DEFAULT_MAP_W = 3000.0
DEFAULT_MAP_H = 3000.0

# ── 라스트힛 임계값 ──────────────────────────────────────────────────────
# 옛: _LASTBIT = _ATTACK_DAMAGE = 25 (에너지 max 999 중 한방킬). BR2 hp(max 200) 기준 ≤ 50.
LASTBIT_TARGET_HP = 50

# ── 자원 채집 인접 판정 ──────────────────────────────────────────────────
CHEST_INTERACT_RANGE = 38.0
NODE_INTERACT_RANGE = 28.0     # 코인 위로 이동만 하면 자동 채집되는 거리
SAFE_ZONE_MARGIN_PX = 30.0


def vec_norm(v: tuple[float, float]) -> tuple[float, float]:
    x, y = v
    length = math.hypot(x, y)
    if length < 1e-9:
        return (1.0, 0.0)
    return (x / length, y / length)


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def zero_action() -> dict[str, Any]:
    return {
        "move_dir": [0.0, 0.0],
        "aim_dir": [1.0, 0.0],
        "attack": False,
        "guard": False,
        "dash": False,
        "pickup": False,
        "use_potion": False,
    }


def extract_target_zone(zone: dict[str, Any]):
    """zone payload → (target_center | None, target_radius, target_eta)."""
    if not zone.get("active", False) or "target_center" not in zone:
        return None, 0.0, float("inf")
    tc = (float(zone["target_center"][0]), float(zone["target_center"][1]))
    return tc, float(zone.get("target_radius", 0.0)), float(zone.get("target_eta", float("inf")))


def in_target_zone(p, tc, tr: float, margin: float = SAFE_ZONE_MARGIN_PX) -> bool:
    if tc is None:
        return True
    return dist(p, tc) <= max(0.0, tr - margin)


def attack_range(has_ranged: bool) -> float:
    return RANGED_RANGE if has_ranged else MELEE_RANGE


class _RuleBossBase(BattleRoyale2DBot):
    """옛 rule_boss_bot.py 의 우선순위 트리를 BR2 인터페이스로 옮긴 공통 베이스.

    임계값은 *옛 base max_hp=200 기준 절대값* 으로 정의하고, runtime 에서 현재 보스의
    max_hp 에 비례 스케일한다. 다대일 환경에서 보스가 stat 강화되면 (예: max_hp=500
    @ Medium) 임계값도 함께 강화되어 옛 의사결정 의미가 보존된다.

    원본 boss_mode.BOSS_STAT_MULTIPLIERS 와 일관:
        Easy   max_hp×2.0 → ATTACK 120, HUNT 240, EMERGENCY 200
        Medium max_hp×2.5 → ATTACK 100, HUNT 175, EMERGENCY 100
        Hard   max_hp×3.0 → (RL 보스가 별도 정책 사용, 룰엔 무관)

    난이도별 임계값(서브클래스에서 오버라이드):
    - LOW_HP_POTION   포션 사용 hp 컷오프 (이하면 use_potion) — 옛 절대값
    - GUARD_HP        인접 적 + hp 이하면 attack 과 함께 guard
    - FLEE_HP         hp 이하면 적 인접 시 도주 모드
    - ATTACK_HP       인접 적 공격 최소 hp (이하면 flee 폴백)
    - HUNT_HP         적 추적 시작 hp (이상이어야 추적)
    - EMERGENCY_HP    hp 이하면 자원 채집 최우선 (옛 _emergency_mine)
    - ENEMY_LOST_TICKS  시야 이탈 후 적 기억 유지 (옛 _EASY_TIMEOUT * 9)
    - MINERAL_EXPIRE_TICKS  자원 위치 기억 유지 (옛 _MIN_EXPIRE * 9)
    - WANDER_INTERVAL_TICKS  탐색 목표 갱신 주기 (옛 _EASY_WANDER_INTERVAL * 9)
    - SPAWN_DIST_RANGE  스폰 시 희귀 클러스터에서의 거리 (옛 randint 범위)
    """

    # 임계값 (옛 base max_hp=200 기준 절대값) — 서브클래스에서 오버라이드
    LOW_HP_POTION: int = 100
    GUARD_HP: int = 50
    FLEE_HP: int = 30
    ATTACK_HP: int = 60       # 옛 _EASY_ATTACK
    HUNT_HP: int = 120        # 옛 _EASY_HUNT
    EMERGENCY_HP: int = 100   # 옛 _EASY_EMERGENCY
    BASE_MAX_HP_REF: int = 200   # 옛 기준 max_hp — 임계값 비율 스케일 baseline
    ENEMY_LOST_TICKS: int = 45      # 옛 _EASY_TIMEOUT(5) × 9
    MINERAL_EXPIRE_TICKS: int = 720  # 옛 _MIN_EXPIRE(80) × 9
    WANDER_INTERVAL_TICKS: int = 270  # 옛 _EASY_WANDER_INTERVAL(30) × 9
    SPAWN_DIST_RANGE: tuple[float, float] = (180.0, 380.0)  # 옛 randint(3,7) × 60px
    AGGRO_HUNT: bool = False  # Easy: 적극 추적 X (시야 이탈 후 추적 포기), Medium: True
    DISPLAY_NAME: str = "보스"

    def _scale(self, value: int, max_hp: int) -> int:
        """옛 절대값 임계값을 현재 max_hp 에 비례 스케일.
        예: ATTACK_HP=60 @ base=200 → max_hp=500 (Medium 보스) 시 150 으로 자동 강화."""
        if max_hp <= 0:
            return value
        return int(value * (max_hp / float(self.BASE_MAX_HP_REF)))

    def __init__(self, bot_id: str, seed: Optional[int] = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._map_info: dict[str, Any] = {}
        self._map_w: float = DEFAULT_MAP_W
        self._map_h: float = DEFAULT_MAP_H
        # 마지막으로 본 적 위치 (옛 _last_enemy_pos)
        self._last_enemy_pos: Optional[tuple[float, float]] = None
        self._enemy_lost_ticks: int = 0
        # 자원 메모리 — 시야 떠난 코인/상자 위치 기억 (옛 _mineral_mem)
        # {(pos): (kind: "node_rare"|"node"|"chest", last_seen_tick)}
        self._resource_mem: dict[tuple[float, float], tuple[str, int]] = {}
        # 탐색 목표 (옛 _wander_target)
        self._wander_target: Optional[tuple[float, float]] = None
        self._wander_set_tick: int = -10**9
        # 직전 틱 카운터 (state["time"] * 10 → tick 환산)
        self._last_tick: int = -1

    @property
    def bot_id(self) -> str:
        return self._bot_id

    # ─── 스폰 ─────────────────────────────────────────────────────────────
    def choose_spawn(self, map_info: dict[str, Any]) -> Optional[tuple[float, float]]:
        """옛 rule_boss_bot 스폰 로직 BR2 포팅 — 희귀 클러스터에서 적당 거리 매복."""
        self._map_info = map_info
        ms = map_info.get("map_size", [DEFAULT_MAP_W, DEFAULT_MAP_H])
        self._map_w = float(ms[0])
        self._map_h = float(ms[1])

        rc = map_info.get("rare_clusters", []) or []
        if not rc:
            return (self._map_w * 0.5 + self._rng.uniform(-200, 200),
                    self._map_h * 0.5 + self._rng.uniform(-200, 200))
        # 옛 "주변 희귀 군락 밀집도 최대" 위치 — BR2 cluster 좌표 8칸(=480px)이내 카운트.
        cluster_radius = 480.0
        best = max(
            rc,
            key=lambda r: sum(
                1 for ox, oy in rc
                if dist((float(r[0]), float(r[1])), (float(ox), float(oy))) <= cluster_radius
            ),
        )
        d = self._rng.uniform(*self.SPAWN_DIST_RANGE)
        angle = self._rng.choice([0.0, math.pi * 0.5, math.pi, math.pi * 1.5])
        sx = float(best[0]) + math.cos(angle) * d
        sy = float(best[1]) + math.sin(angle) * d
        sx = max(EDGE_MARGIN, min(self._map_w - EDGE_MARGIN, sx))
        sy = max(EDGE_MARGIN, min(self._map_h - EDGE_MARGIN, sy))
        return (sx, sy)

    # ─── 공통 유틸 ────────────────────────────────────────────────────────
    def _tick(self, state: dict) -> int:
        # BR2 state["time"] (sec) → 100ms 틱
        return int(float(state.get("time", 0.0)) * 10.0)

    def _clamp_move(self, move_dir, pos):
        """맵 경계 밖으로 향하는 성분 제거. 모두 0 되면 안쪽으로 강제."""
        mx, my = float(move_dir[0]), float(move_dir[1])
        px, py = pos
        had_intent = (mx != 0.0 or my != 0.0)
        if px < EDGE_MARGIN and mx < 0:
            mx = 0.0
        if px > self._map_w - EDGE_MARGIN and mx > 0:
            mx = 0.0
        if py < EDGE_MARGIN and my < 0:
            my = 0.0
        if py > self._map_h - EDGE_MARGIN and my > 0:
            my = 0.0
        if had_intent and mx == 0.0 and my == 0.0:
            cx = self._map_w * 0.5 - px
            cy = self._map_h * 0.5 - py
            n = math.hypot(cx, cy)
            if n > 1e-9:
                mx, my = cx / n, cy / n
        return [mx, my]

    def _safe_return(self, action, pos):
        action["move_dir"] = self._clamp_move(action["move_dir"], pos)
        return action

    def _update_resource_mem(self, vision: dict, tick: int) -> None:
        """시야 내 코인/상자 위치 기억. 옛 _update_mineral_mem 포팅."""
        # 시야 내 자원 갱신
        for n in vision.get("nodes", []):
            p = (float(n["pos"][0]), float(n["pos"][1]))
            kind = "node_rare" if n.get("rare") else "node"
            self._resource_mem[p] = (kind, tick)
        for c in vision.get("chests", []):
            p = (float(c["pos"][0]), float(c["pos"][1]))
            self._resource_mem[p] = ("chest", tick)
        # stale 만료
        expired = [p for p, (_, t) in self._resource_mem.items()
                   if tick - t > self.MINERAL_EXPIRE_TICKS]
        for p in expired:
            del self._resource_mem[p]

    def _update_enemy_tracking(self, vision: dict) -> list[dict]:
        """시야 내 적 위치/HP 갱신. 옛 _last_enemy_pos + enemy_mem 통합 단순화."""
        enemies = vision.get("enemies", []) or []
        if enemies:
            self._enemy_lost_ticks = 0
        else:
            self._enemy_lost_ticks += 1
            if self._enemy_lost_ticks > self.ENEMY_LOST_TICKS:
                self._last_enemy_pos = None
        return enemies

    # ─── 의사결정 단계별 헬퍼 (옛 우선순위 트리 매핑) ─────────────────────
    def _step_potion(self, action, me) -> None:
        """0단계: HP 낮으면 포션 (다른 행동과 동시). 임계값은 max_hp 비율 스케일."""
        max_hp = int(me.get("max_hp", self.BASE_MAX_HP_REF) or self.BASE_MAX_HP_REF)
        if me.get("has_potion") and int(me.get("hp", 0)) <= self._scale(self.LOW_HP_POTION, max_hp):
            action["use_potion"] = True

    def _step_zone_retreat(self, action, pos, zone) -> Optional[dict]:
        """1단계: 자기장 밖 → target_center 강제 진입. 적 기억 초기화."""
        tc, tr, _ = extract_target_zone(zone)
        if tc is not None and not in_target_zone(pos, tc, tr):
            self._last_enemy_pos = None
            self._enemy_lost_ticks = 0
            d = vec_norm((tc[0] - pos[0], tc[1] - pos[1]))
            action["move_dir"] = list(d)
            action["aim_dir"] = list(d)
            dash_cd = float(self._current_dash_cd)
            if dash_cd <= 0.0:
                action["dash"] = True
            return self._safe_return(action, pos)
        # 폴백: target 정보 없을 때 현재 zone 밖이면 현재 center 로
        if zone.get("active", False) and zone.get("damage", 0.0) > 0.0:
            zc = tuple(zone.get("center", [0.0, 0.0]))
            zr = float(zone.get("radius", 0.0))
            if dist(pos, zc) > zr:
                d = vec_norm((zc[0] - pos[0], zc[1] - pos[1]))
                action["move_dir"] = list(d)
                action["aim_dir"] = list(d)
                if self._current_dash_cd <= 0.0:
                    action["dash"] = True
                return self._safe_return(action, pos)
        return None

    def _step_adjacent_enemy(self, action, pos, hp, has_ranged, enemies, max_hp) -> Optional[dict]:
        """3단계: 사거리 안 적 — 라스트힛 / 공격 / flee 분기 (옛 트리).
        임계값은 max_hp 비율 스케일."""
        if not enemies:
            return None
        rng_atk = attack_range(has_ranged)
        in_range = [e for e in enemies if dist(pos, tuple(e["pos"])) <= rng_atk]
        if not in_range:
            return None

        attack_th = self._scale(self.ATTACK_HP, max_hp)
        guard_th = self._scale(self.GUARD_HP, max_hp)
        # 라스트힛 임계값도 보스가 강하면 더 큰 한방킬 가능 — 옛은 attack_damage=25.
        # BR2 보스 atk×1.2~1.6 강화되므로 라스트힛 임계값도 같이 비례.
        lastbit_th = int(LASTBIT_TARGET_HP * (max_hp / float(self.BASE_MAX_HP_REF)))

        # a. 라스트힛
        weakest = min(in_range, key=lambda e: int(e.get("hp", 999)))
        if int(weakest.get("hp", 999)) <= lastbit_th:
            epos = tuple(weakest["pos"])
            aim = vec_norm((epos[0] - pos[0], epos[1] - pos[1]))
            action["aim_dir"] = list(aim)
            action["attack"] = True
            return self._safe_return(action, pos)

        # b. 자기 hp >= ATTACK_HP → 공격 (저HP 적 우선)
        if hp >= attack_th:
            epos = tuple(weakest["pos"])
            aim = vec_norm((epos[0] - pos[0], epos[1] - pos[1]))
            action["aim_dir"] = list(aim)
            action["attack"] = True
            if hp <= guard_th and float(self._current_guard_cd) <= 0.0:
                action["guard"] = True
            return self._safe_return(action, pos)

        # c. hp 부족 → flee (zone-safe)
        nearest = min(in_range, key=lambda e: dist(pos, tuple(e["pos"])))
        epos = tuple(nearest["pos"])
        away = vec_norm((pos[0] - epos[0], pos[1] - epos[1]))
        action["move_dir"] = list(away)
        action["aim_dir"] = list(away)
        if float(self._current_dash_cd) <= 0.0:
            action["dash"] = True
        if float(self._current_guard_cd) <= 0.0:
            action["guard"] = True
        return self._safe_return(action, pos)

    def _step_emergency_resource(self, action, pos, vision) -> Optional[dict]:
        """4단계: 긴급 자원 채집 (옛 _emergency_mine). 발 아래 → 인접 → 시야 → 메모리."""
        # BR2 엔 발밑·인접 셀 개념이 없고, 위치만 가깝게 가면 자동 채집/픽업. 가장 가까운 자원으로.
        candidates = list(vision.get("nodes", [])) + list(vision.get("chests", []))
        if not candidates:
            # 메모리 폴백
            if self._resource_mem:
                closest_mem = min(self._resource_mem.keys(), key=lambda p: dist(pos, p))
                aim = vec_norm((closest_mem[0] - pos[0], closest_mem[1] - pos[1]))
                action["move_dir"] = list(aim)
                action["aim_dir"] = list(aim)
                return self._safe_return(action, pos)
            return None
        tgt = min(candidates, key=lambda r: dist(pos, tuple(r["pos"])))
        tpos = tuple(tgt["pos"])
        d = dist(pos, tpos)
        aim = vec_norm((tpos[0] - pos[0], tpos[1] - pos[1]))
        action["aim_dir"] = list(aim)
        if "rare" in tgt and d <= NODE_INTERACT_RANGE:
            # 코인은 위로 가면 자동 채집 — STAY (옛 STAY)
            action["move_dir"] = [0.0, 0.0]
        elif d <= CHEST_INTERACT_RANGE and "rare" not in tgt:
            # 상자 — pickup
            action["move_dir"] = [0.0, 0.0]
            action["pickup"] = True
        else:
            action["move_dir"] = list(aim)
        return self._safe_return(action, pos)

    def _step_hunt_enemy(self, action, pos, hp, enemies, vision, zone, max_hp) -> Optional[dict]:
        """6단계: 적 추적 (hp >= HUNT_HP, zone-safe). 임계값 스케일."""
        if hp < self._scale(self.HUNT_HP, max_hp):
            return None
        if not self.AGGRO_HUNT and not enemies:
            # Easy: 시야에서 사라지면 추적 포기 (옛 _last_enemy_pos 추적 안 함)
            return None

        tc, tr, _ = extract_target_zone(zone)
        # 시야 내 zone-safe 적 우선 (저HP·근거리 가중치 — 옛 _pick_chase_target)
        cand: list[tuple[tuple[float, float], int, float]] = []
        for e in enemies:
            ep = tuple(e["pos"])
            if not in_target_zone(ep, tc, tr, margin=0.0):
                continue
            cand.append((ep, int(e.get("hp", 200)), dist(pos, ep)))
        if not cand:
            # AGGRO_HUNT(중) 만 last_enemy_pos 추격
            if self.AGGRO_HUNT and self._last_enemy_pos is not None:
                ep = self._last_enemy_pos
                if in_target_zone(ep, tc, tr, margin=0.0):
                    aim = vec_norm((ep[0] - pos[0], ep[1] - pos[1]))
                    action["move_dir"] = list(aim)
                    action["aim_dir"] = list(aim)
                    return self._safe_return(action, pos)
                self._last_enemy_pos = None
            return None
        # 점수: 저HP + 근거리 우선 (옛 _pick_chase_target 식)
        ep, _, _ = min(cand, key=lambda c: (c[1] * 1.0) + c[2] * 0.5)
        self._last_enemy_pos = ep
        aim = vec_norm((ep[0] - pos[0], ep[1] - pos[1]))
        action["move_dir"] = list(aim)
        action["aim_dir"] = list(aim)
        return self._safe_return(action, pos)

    def _step_collect_resource(self, action, pos, vision, zone) -> Optional[dict]:
        """7/8단계: 시야 내 자원 (희귀 우선, zone-safe). 옛 _scan_grid best_mineral."""
        tc, tr, _ = extract_target_zone(zone)
        nodes = vision.get("nodes", []) or []
        chests = vision.get("chests", []) or []
        items = vision.get("items", []) or []

        # 옛 best_min 가중치: rare=20, normal=5 - dist (BR2 거리 단위 다르므로 점수만 보존)
        best = None
        best_score = -1e18
        for n in nodes:
            p = tuple(n["pos"])
            if not in_target_zone(p, tc, tr):
                continue
            score = (20 if n.get("rare") else 5) - dist(pos, p) * 0.01
            if score > best_score:
                best_score = score
                best = ("node", p, n)
        for c in chests:
            p = tuple(c["pos"])
            if not in_target_zone(p, tc, tr):
                continue
            score = 12 - dist(pos, p) * 0.01  # 상자 가치 ≈ 일반 코인보다 높고 희귀보다 낮음
            if score > best_score:
                best_score = score
                best = ("chest", p, c)
        for it in items:
            p = tuple(it["pos"])
            if not in_target_zone(p, tc, tr):
                continue
            score = 8 - dist(pos, p) * 0.01
            if score > best_score:
                best_score = score
                best = ("item", p, it)

        if best is None:
            return None
        kind, tpos, _payload = best
        d = dist(pos, tpos)
        aim = vec_norm((tpos[0] - pos[0], tpos[1] - pos[1]))
        action["aim_dir"] = list(aim)
        if kind == "chest" and d <= CHEST_INTERACT_RANGE:
            action["move_dir"] = [0.0, 0.0]
            action["pickup"] = True
        else:
            action["move_dir"] = list(aim)
        return self._safe_return(action, pos)

    def _step_memory_resource(self, action, pos, zone) -> Optional[dict]:
        """9단계: 기억 속 자원 추적 (옛 _mineral_mem 폴백). 희귀 우선."""
        if not self._resource_mem:
            return None
        tc, tr, _ = extract_target_zone(zone)
        rare_pool = {p: v for p, v in self._resource_mem.items() if v[0] == "node_rare"}
        pool = rare_pool if rare_pool else self._resource_mem
        # zone-safe 우선
        safe = {p: v for p, v in pool.items() if in_target_zone(p, tc, tr, margin=0.0)}
        target_pool = safe if safe else pool
        closest = min(target_pool.keys(), key=lambda p: dist(pos, p))
        aim = vec_norm((closest[0] - pos[0], closest[1] - pos[1]))
        action["move_dir"] = list(aim)
        action["aim_dir"] = list(aim)
        return self._safe_return(action, pos)

    def _step_wander(self, action, pos, zone, tick) -> dict:
        """10단계: 맵 탐색. 옛 _EASY_WANDER_INTERVAL 갱신."""
        tc, tr, _ = extract_target_zone(zone)
        center = tc if tc is not None else (self._map_w * 0.5, self._map_h * 0.5)
        radius = tr if tr > 0 else min(self._map_w, self._map_h) * 0.3

        need_new = (
            self._wander_target is None
            or tick - self._wander_set_tick > self.WANDER_INTERVAL_TICKS
            or dist(pos, self._wander_target) < 80.0
        )
        if need_new:
            # zone 안쪽 랜덤 (margin 100px)
            r = self._rng.uniform(0.0, max(50.0, radius - 100.0))
            ang = self._rng.uniform(0.0, 2 * math.pi)
            tx = max(EDGE_MARGIN, min(self._map_w - EDGE_MARGIN, center[0] + math.cos(ang) * r))
            ty = max(EDGE_MARGIN, min(self._map_h - EDGE_MARGIN, center[1] + math.sin(ang) * r))
            self._wander_target = (tx, ty)
            self._wander_set_tick = tick
        wt = self._wander_target
        aim = vec_norm((wt[0] - pos[0], wt[1] - pos[1]))
        action["move_dir"] = list(aim)
        action["aim_dir"] = list(aim)
        return self._safe_return(action, pos)

    def _step_chest_progress(self, action, pos, me) -> Optional[dict]:
        """상자 오픈 진행 중이면 자리 고수 (옛엔 없음 — BR2 룰)."""
        cp = float(me.get("chest_progress", 0.0))
        if 0.0 < cp < 1.0:
            action["move_dir"] = [0.0, 0.0]
            action["pickup"] = True
            return self._safe_return(action, pos)
        return None

    # ─── 메인 의사결정 — 옛 우선순위 트리 그대로 ─────────────────────────
    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        action = zero_action()
        me = state.get("self", {}) or {}
        pos = tuple(me.get("pos", [self._map_w * 0.5, self._map_h * 0.5]))
        hp = int(me.get("hp", 0))
        max_hp = int(me.get("max_hp", self.BASE_MAX_HP_REF) or self.BASE_MAX_HP_REF)
        has_ranged = bool(me.get("has_ranged", False))
        zone = state.get("zone", {}) or {}
        vision = state.get("vision", {}) or {}
        tick = self._tick(state)

        # 헬퍼에서 빠르게 접근하기 위한 캐시
        self._current_dash_cd = float(me.get("dash_cd", 0.0))
        self._current_guard_cd = float(me.get("guard_cd", 0.0))

        # 자원·적 기억 갱신
        self._update_resource_mem(vision, tick)
        enemies = self._update_enemy_tracking(vision)
        self._last_tick = tick

        # 임계값 스케일 캐시 (보스 강화 시 비율 보존)
        flee_th = self._scale(self.FLEE_HP, max_hp)
        emergency_th = self._scale(self.EMERGENCY_HP, max_hp)
        hunt_th = self._scale(self.HUNT_HP, max_hp)
        lastbit_th = int(LASTBIT_TARGET_HP * (max_hp / float(self.BASE_MAX_HP_REF)))

        # 0. 포션 (다른 액션과 동시 가능)
        self._step_potion(action, me)

        # 1. 자기장 탈출
        r = self._step_zone_retreat(action, pos, zone)
        if r is not None:
            return r

        # 2. 상자 오픈 진행 중 → 자리 고수
        r = self._step_chest_progress(action, pos, me)
        if r is not None:
            return r

        # 3. 인접/사거리 안 적: 라스트힛·공격·flee
        if enemies and hp <= flee_th:
            rng_atk = attack_range(has_ranged)
            in_range = [e for e in enemies if dist(pos, tuple(e["pos"])) <= rng_atk]
            weakest = min(in_range, key=lambda e: int(e.get("hp", 999))) if in_range else None
            if weakest and int(weakest.get("hp", 999)) <= lastbit_th:
                ep = tuple(weakest["pos"])
                aim = vec_norm((ep[0] - pos[0], ep[1] - pos[1]))
                action["aim_dir"] = list(aim)
                action["attack"] = True
                if self._current_guard_cd <= 0.0:
                    action["guard"] = True
                return self._safe_return(action, pos)
            nearest = min(enemies, key=lambda e: dist(pos, tuple(e["pos"])))
            ep = tuple(nearest["pos"])
            away = vec_norm((pos[0] - ep[0], pos[1] - ep[1]))
            action["move_dir"] = list(away)
            action["aim_dir"] = list(away)
            if self._current_dash_cd <= 0.0:
                action["dash"] = True
            if self._current_guard_cd <= 0.0:
                action["guard"] = True
            return self._safe_return(action, pos)

        r = self._step_adjacent_enemy(action, pos, hp, has_ranged, enemies, max_hp)
        if r is not None:
            return r

        # 4. 긴급 자원 (hp < EMERGENCY_HP)
        if hp < emergency_th:
            r = self._step_emergency_resource(action, pos, vision)
            if r is not None:
                return r

        # 5. 발 아래(가까운) 코인 채집
        if hp < hunt_th:
            nodes = vision.get("nodes", []) or []
            near_nodes = [n for n in nodes if dist(pos, tuple(n["pos"])) <= NODE_INTERACT_RANGE + 40]
            if near_nodes:
                tgt = min(near_nodes, key=lambda n: dist(pos, tuple(n["pos"])))
                aim = vec_norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
                action["move_dir"] = list(aim)
                action["aim_dir"] = list(aim)
                return self._safe_return(action, pos)

        # 6. 적 추적 (hp >= HUNT_HP)
        r = self._step_hunt_enemy(action, pos, hp, enemies, vision, zone, max_hp)
        if r is not None:
            return r

        # 7/8. 시야 내 자원 (희귀 우선, zone-safe)
        r = self._step_collect_resource(action, pos, vision, zone)
        if r is not None:
            return r

        # 9. 기억 속 자원 추적
        r = self._step_memory_resource(action, pos, zone)
        if r is not None:
            return r

        # 10. 맵 탐색 wander
        return self._step_wander(action, pos, zone, tick)


__all__ = ["_RuleBossBase", "LASTBIT_TARGET_HP"]

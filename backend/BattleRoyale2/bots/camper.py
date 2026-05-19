"""CamperBot — 초반 클러스터 회피로 스펙 모으고, 중후반부터 적극 교전.

전략 (우선순위 높음 → 낮음):
1. HP 낮고 포션 보유 → use_potion (다른 행동과 동시 가능)
2. 다음 자기장 (target_zone) 밖이면 target_center 로 이동
3. should_engage 판정 (시간 OR 원거리 보유 OR 공격력 16 이상)
   - 캠핑 모드 (False):
     * 적이 너무 가까우면 도망
     * 클러스터(rare/chest) 회피하며 스캐터된 상자/코인 파밍 (상자 우선)
     * 클러스터 안 자원은 무시
   - 교전 모드 (True):
     * 적 사거리 안 → 공격
     * 사거리 밖 → 추격
     * 적 없음 → 자원 채집 (다음 자기장 안 우선)
4. 폴백: target 중심
"""
from __future__ import annotations

import math
import random
from typing import Any

from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot


MELEE_RANGE = 60.0
RANGED_RANGE = 400.0
EDGE_MARGIN = 100.0


def _norm(v):
    x, y = v
    length = math.hypot(x, y)
    if length < 1e-9:
        return (1.0, 0.0)
    return (x / length, y / length)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _zero_action() -> dict[str, Any]:
    return {
        "move_dir": [0.0, 0.0],
        "aim_dir": [1.0, 0.0],
        "attack": False,
        "guard": False,
        "dash": False,
        "pickup": False,
        "use_potion": False,
    }


class CamperBot(BattleRoyale2DBot):
    """존버 봇 — 초반 캠핑 → 중후반 사냥."""

    LOW_HP_THRESHOLD = 80
    FLEE_RANGE = 140.0                # 캠핑 모드에서 적 회피 거리
    CLUSTER_AVOID_RADIUS = 250.0      # 이 안에 있는 자원은 캠핑 모드에서 무시
    CHEST_INTERACT_RANGE = 38.0
    SAFE_MARGIN_PX = 30.0

    # 교전 모드 전환 조건 (셋 중 하나라도 충족)
    ENGAGE_TIME_SEC = 80.0
    ENGAGE_BY_RANGED = True
    ENGAGE_ATK_THRESHOLD = 16         # base 6 + WEAPON_UP 2회

    CHASE_DASH_MIN_DIST = 100.0

    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._map_info: dict[str, Any] = {}
        self._clusters: list[tuple[float, float]] = []
        self._map_w = 3000.0
        self._map_h = 3000.0

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict[str, Any]) -> tuple[float, float] | None:
        self._map_info = map_info
        # 모든 클러스터 좌표 캐시 (회피 판정용)
        self._clusters = []
        for c in map_info.get("rare_clusters", []):
            self._clusters.append((float(c[0]), float(c[1])))
        for c in map_info.get("chest_clusters", []):
            self._clusters.append((float(c[0]), float(c[1])))

        # 존버는 클러스터 멀리, 첫 자기장 안쪽에 스폰 — 사람 없는 외곽 우선
        map_size = map_info.get("map_size", [3000.0, 3000.0])
        zone1_center = map_info.get("zone1_center")
        zone1_radius = float(map_info.get("zone1_radius", 0.0))
        mw, mh = float(map_size[0]), float(map_size[1])
        self._map_w = mw
        self._map_h = mh
        # 후보 점 N개 샘플링 → zone1 안 + 클러스터 멀리 인 점 중 가장 멀리 떨어진 곳
        best = None
        best_score = -1.0
        for _ in range(40):
            x = self._rng.uniform(150.0, mw - 150.0)
            y = self._rng.uniform(150.0, mh - 150.0)
            p = (x, y)
            if zone1_center is not None:
                zc = (float(zone1_center[0]), float(zone1_center[1]))
                if _dist(p, zc) > zone1_radius - 100.0:
                    continue
            min_cluster_d = min((_dist(p, c) for c in self._clusters), default=1e9)
            if min_cluster_d > best_score:
                best_score = min_cluster_d
                best = p
        return best

    # ---------- 내부 ----------
    @staticmethod
    def _extract_target_zone(zone):
        if not zone.get("active", False) or "target_center" not in zone:
            return None, 0.0, float("inf")
        tc = (float(zone["target_center"][0]), float(zone["target_center"][1]))
        return tc, float(zone.get("target_radius", 0.0)), float(zone.get("target_eta", float("inf")))

    def _in_target_zone(self, p, tc, tr: float) -> bool:
        if tc is None:
            return True
        return _dist(p, tc) <= max(0.0, tr - self.SAFE_MARGIN_PX)

    def _in_any_cluster(self, p) -> bool:
        for c in self._clusters:
            if _dist(p, c) < self.CLUSTER_AVOID_RADIUS:
                return True
        return False

    def _should_engage(self, sim_time: float, has_ranged: bool, atk: int) -> bool:
        if sim_time >= self.ENGAGE_TIME_SEC:
            return True
        if self.ENGAGE_BY_RANGED and has_ranged:
            return True
        if atk >= self.ENGAGE_ATK_THRESHOLD:
            return True
        return False

    def _attack_range(self, has_ranged: bool) -> float:
        return RANGED_RANGE if has_ranged else MELEE_RANGE

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

    def _pick_safer_target(self, pos, enemy_pos, vision, tc, tr, avoid_clusters: bool):
        """적에게서 멀어지면서 자원에 가까워지는 타겟. 캠핑 모드에선 클러스터 회피 추가."""
        candidates: list[tuple[float, float]] = []
        for c in vision.get("chests", []):
            p = (float(c["pos"][0]), float(c["pos"][1]))
            if avoid_clusters and self._in_any_cluster(p):
                continue
            if self._in_target_zone(p, tc, tr):
                candidates.append(p)
        for n in vision.get("nodes", []):
            p = (float(n["pos"][0]), float(n["pos"][1]))
            if avoid_clusters and self._in_any_cluster(p):
                continue
            if self._in_target_zone(p, tc, tr):
                candidates.append(p)
        for it in vision.get("items", []):
            p = (float(it["pos"][0]), float(it["pos"][1]))
            if self._in_target_zone(p, tc, tr):
                candidates.append(p)
        if not candidates:
            return None
        bot_to_enemy = _dist(pos, enemy_pos)
        best = None
        best_score = float("inf")
        for p in candidates:
            p_to_enemy = _dist(p, enemy_pos)
            if p_to_enemy <= bot_to_enemy + 20.0:
                continue
            d_self = _dist(pos, p)
            score = d_self - (p_to_enemy - bot_to_enemy) * 0.5
            if score < best_score:
                best_score = score
                best = p
        return best

    # ---------- 메인 ----------
    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        action = _zero_action()
        me = state.get("self", {})
        pos = tuple(me.get("pos", [0.0, 0.0]))
        hp = int(me.get("hp", 0))
        atk = int(me.get("atk", 0))
        has_potion = bool(me.get("has_potion", False))
        has_ranged = bool(me.get("has_ranged", False))
        dash_cd = float(me.get("dash_cd", 0.0))
        sim_time = float(state.get("time", 0.0))
        zone = state.get("zone", {})
        vision = state.get("vision", {})

        tc, tr, _eta = self._extract_target_zone(zone)

        # 1. HP 낮으면 포션
        if has_potion and hp < self.LOW_HP_THRESHOLD:
            action["use_potion"] = True

        # 2. 다음 자기장 밖 → target_center
        if tc is not None and not self._in_target_zone(pos, tc, tr):
            d = _norm((tc[0] - pos[0], tc[1] - pos[1]))
            action["move_dir"] = list(d)
            action["aim_dir"] = list(d)
            if dash_cd <= 0.0:
                action["dash"] = True
            return self._safe_return(action, pos)
        if zone.get("active", False) and zone.get("damage", 0.0) > 0.0:
            zc = tuple(zone.get("center", [0.0, 0.0]))
            zr = float(zone.get("radius", 0.0))
            if _dist(pos, zc) > zr:
                d = _norm((zc[0] - pos[0], zc[1] - pos[1]))
                action["move_dir"] = list(d)
                action["aim_dir"] = list(d)
                if dash_cd <= 0.0:
                    action["dash"] = True
                return self._safe_return(action, pos)

        # 2.5 상자 열기 진행 중이면 자리 고수 (피격 감수). 피격/도망 우선순위 무시.
        chest_progress = float(me.get("chest_progress", 0.0))
        if 0.0 < chest_progress < 1.0:
            action["move_dir"] = [0.0, 0.0]
            action["pickup"] = True
            return self._safe_return(action, pos)

        engage = self._should_engage(sim_time, has_ranged, atk)
        enemies = vision.get("enemies", [])

        if engage:
            return self._engage_action(action, pos, vision, has_ranged, dash_cd, tc, tr)
        else:
            return self._camp_action(action, pos, enemies, vision, dash_cd, tc, tr)

    # ---------- 캠핑 모드 ----------
    def _camp_action(self, action, pos, enemies, vision, dash_cd, tc, tr):
        # 적이 가까우면 회피 — 목표 기반(자원 쪽) 우선, 없으면 단순 away
        if enemies:
            nearest = min(enemies, key=lambda e: _dist(pos, tuple(e["pos"])))
            enemy_pos = tuple(nearest["pos"])
            d = _dist(pos, enemy_pos)
            if d < self.FLEE_RANGE:
                safe = self._pick_safer_target(pos, enemy_pos, vision, tc, tr, avoid_clusters=True)
                if safe is not None:
                    aim = _norm((safe[0] - pos[0], safe[1] - pos[1]))
                    action["move_dir"] = list(aim)
                    action["aim_dir"] = list(aim)
                    if dash_cd <= 0.0 and d < 90.0:
                        action["dash"] = True
                    return self._safe_return(action, pos)
                away = _norm((pos[0] - enemy_pos[0], pos[1] - enemy_pos[1]))
                action["move_dir"] = list(away)
                action["aim_dir"] = list(away)
                if dash_cd <= 0.0 and d < 90.0:
                    action["dash"] = True
                return self._safe_return(action, pos)

        # 1순위: 드롭 아이템 (방금 깐 상자에서 나온 거 우선).
        # 클러스터 필터 X — 자기 상자 옆에 떨어진 거라 위험 감수 가치 있음.
        items = vision.get("items", [])
        if items:
            valid = [i for i in items if self._in_target_zone(tuple(i["pos"]), tc, tr)]
            if valid:
                tgt = min(valid, key=lambda i: _dist(pos, tuple(i["pos"])))
                aim = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
                action["move_dir"] = list(aim)
                action["aim_dir"] = list(aim)
                return self._safe_return(action, pos)

        # 2순위: 클러스터 밖 상자 (스펙업 노림)
        chests = vision.get("chests", [])
        if chests:
            valid = [c for c in chests
                     if not self._in_any_cluster(tuple(c["pos"]))
                     and self._in_target_zone(tuple(c["pos"]), tc, tr)]
            if valid:
                tgt = min(valid, key=lambda c: _dist(pos, tuple(c["pos"])))
                return self._approach_or_pickup(action, pos, tuple(tgt["pos"]))

        # 3순위: 클러스터 밖 코인 (생존용 점수)
        nodes = vision.get("nodes", [])
        if nodes:
            valid = [n for n in nodes
                     if not self._in_any_cluster(tuple(n["pos"]))
                     and self._in_target_zone(tuple(n["pos"]), tc, tr)
                     and not n.get("rare", False)]
            if valid:
                tgt = min(valid, key=lambda n: _dist(pos, tuple(n["pos"])))
                aim = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
                action["move_dir"] = list(aim)
                action["aim_dir"] = list(aim)
                return self._safe_return(action, pos)

        # 폴백: 다음 자기장 → 첫 자기장 → 클러스터에서 가장 먼 점 순으로 향함.
        # 안전 페이즈(tc=None) 에서도 가만히 있지 않도록.
        fallback = self._camp_patrol_target(pos)
        if fallback is not None:
            aim = _norm((fallback[0] - pos[0], fallback[1] - pos[1]))
            action["move_dir"] = [aim[0] * 0.5, aim[1] * 0.5]
            action["aim_dir"] = list(aim)
            return self._safe_return(action, pos)
        return self._safe_return(action, pos)

    def _camp_patrol_target(self, pos):
        """안전 페이즈 / 자원 부재 시 캠퍼 봇이 향할 대체 목표.

        우선순위:
        1. 다음 자기장 target_center (있으면)
        2. zone1_center (match_info)
        3. 맵 중앙
        """
        # tc 는 호출자가 None 일 때만 진입하므로 1번은 건너뛰고 시작
        z1 = self._map_info.get("zone1_center")
        if z1 is not None:
            try:
                return (float(z1[0]), float(z1[1]))
            except (TypeError, IndexError):
                pass
        # 폴백 — 맵 중앙
        return (self._map_w * 0.5, self._map_h * 0.5)

    # ---------- 교전 모드 ----------
    def _engage_action(self, action, pos, vision, has_ranged, dash_cd, tc, tr):
        enemies = vision.get("enemies", [])
        if enemies:
            # 가장 HP 낮은 적 우선 (스나이프하기 좋은 사냥꾼 컨셉)
            target = min(enemies, key=lambda e: (int(e.get("hp", 999)), _dist(pos, tuple(e["pos"]))))
            epos = tuple(target["pos"])
            ed = _dist(pos, epos)
            aim = _norm((epos[0] - pos[0], epos[1] - pos[1]))
            atk_range = self._attack_range(has_ranged)

            if ed <= atk_range:
                action["aim_dir"] = list(aim)
                action["move_dir"] = [0.0, 0.0]
                action["attack"] = True
                return self._safe_return(action, pos)

            # 추격
            action["aim_dir"] = list(aim)
            action["move_dir"] = list(aim)
            if ed >= self.CHASE_DASH_MIN_DIST and dash_cd <= 0.0:
                action["dash"] = True
            return self._safe_return(action, pos)

        # 적 없으면 자원 채집 — 드롭 아이템 우선 (방금 깐 상자 옆 아이템 등)
        items = vision.get("items", [])
        if items:
            in_safe = [i for i in items if self._in_target_zone(tuple(i["pos"]), tc, tr)]
            pool_i = in_safe if in_safe else items
            tgt = min(pool_i, key=lambda i: _dist(pos, tuple(i["pos"])))
            aim = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
            action["move_dir"] = list(aim)
            action["aim_dir"] = list(aim)
            return self._safe_return(action, pos)

        chests = vision.get("chests", [])
        if chests:
            in_safe = [c for c in chests if self._in_target_zone(tuple(c["pos"]), tc, tr)]
            pool = in_safe if in_safe else chests
            if pool:
                tgt = min(pool, key=lambda c: _dist(pos, tuple(c["pos"])))
                return self._approach_or_pickup(action, pos, tuple(tgt["pos"]))

        nodes = vision.get("nodes", [])
        if nodes:
            in_safe = [n for n in nodes if self._in_target_zone(tuple(n["pos"]), tc, tr)]
            pool = in_safe if in_safe else nodes
            tgt = min(pool, key=lambda n: _dist(pos, tuple(n["pos"])))
            aim = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
            action["move_dir"] = list(aim)
            action["aim_dir"] = list(aim)
            return self._safe_return(action, pos)

        if tc is not None:
            aim = _norm((tc[0] - pos[0], tc[1] - pos[1]))
            action["move_dir"] = [aim[0] * 0.5, aim[1] * 0.5]
            action["aim_dir"] = list(aim)
        return self._safe_return(action, pos)

    def _approach_or_pickup(self, action, pos, target_pos):
        d = _dist(pos, target_pos)
        aim = _norm((target_pos[0] - pos[0], target_pos[1] - pos[1]))
        action["aim_dir"] = list(aim)
        if d <= self.CHEST_INTERACT_RANGE:
            action["move_dir"] = [0.0, 0.0]
            action["pickup"] = True
        else:
            action["move_dir"] = list(aim)
        return self._safe_return(action, pos)

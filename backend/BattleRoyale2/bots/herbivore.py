"""HerbivoreBot — 코인 채집형 샘플 봇 (자기장 사전 회피 버전).

전략 (우선순위 높음 → 낮음):
1. HP 낮은데 포션 보유 → 즉시 사용 (다른 행동과 동시 가능)
2. 다음 자기장 (target_zone) 밖이면 target_center 로 이동
   - 경계에서 왔다갔다 하지 않고 단계 종료 위치로 미리 이동
3. (폴백) target 정보 없으면 현재 자기장 밖일 때 현재 center 로 이동
4. 너무 가까운 적이 있으면 도망
   - 도망 방향이 target_zone 밖이면 자기장 안쪽으로 휘는 측면 회피
5. 시야 내 코인 — 다음 자기장 안 우선 (eta 짧으면 밖은 무시)
6. 시야 내 상자 — 다음 자기장 안 우선, 인접 시 pickup
7. 시야 내 드롭 아이템 — 다음 자기장 안 우선
8. 폴백: target 정보 있으면 그 중심으로 천천히, 없으면 매치 시작 클러스터로
"""
from __future__ import annotations

import math
import random
from typing import Any

from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot


def _norm(v: tuple[float, float]) -> tuple[float, float]:
    x, y = v
    length = math.hypot(x, y)
    if length < 1e-9:
        return (1.0, 0.0)
    return (x / length, y / length)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
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


EDGE_MARGIN = 100.0


class HerbivoreBot(BattleRoyale2DBot):
    """초식 봇 — 자원 채집과 생존 우선. 자기장 target 정보를 활용해 미리 안전 지점으로 이동."""

    LOW_HP_THRESHOLD = 80           # 200 max 중
    FLEE_RANGE = 120.0
    CHEST_INTERACT_RANGE = 38.0
    # eta 가 이 시간 이하면 안전 구역 밖 자원은 무시 (지금 가도 못 돌아옴)
    URGENT_ETA_SEC = 20.0
    # target zone 안쪽 마진 (안쪽일수록 더 안전)
    SAFE_MARGIN_PX = 30.0

    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._map_info: dict[str, Any] = {}
        self._map_w = 3000.0
        self._map_h = 3000.0

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict[str, Any]) -> tuple[float, float] | None:
        self._map_info = map_info
        ms = map_info.get("map_size", [3000.0, 3000.0])
        self._map_w = float(ms[0])
        self._map_h = float(ms[1])
        candidates: list[tuple[float, float]] = []
        for cluster in map_info.get("rare_clusters", []):
            candidates.append((float(cluster[0]), float(cluster[1])))
        if not candidates:
            for cluster in map_info.get("chest_clusters", []):
                candidates.append((float(cluster[0]), float(cluster[1])))
        if not candidates:
            return None
        cx, cy = self._rng.choice(candidates)
        return (cx + self._rng.uniform(-60.0, 60.0), cy + self._rng.uniform(-60.0, 60.0))

    # ---------- 내부 유틸 ----------
    @staticmethod
    def _extract_target_zone(zone: dict[str, Any]) -> tuple[tuple[float, float] | None, float, float]:
        """zone payload 에서 target_center / target_radius / target_eta 추출.

        Returns: (center or None, radius, eta_seconds)
        zone 비활성 또는 target_* 없음 → (None, 0.0, inf)
        """
        if not zone.get("active", False):
            return None, 0.0, float("inf")
        if "target_center" not in zone:
            return None, 0.0, float("inf")
        center = (float(zone["target_center"][0]), float(zone["target_center"][1]))
        radius = float(zone.get("target_radius", 0.0))
        eta = float(zone.get("target_eta", float("inf")))
        return center, radius, eta

    def _in_target_zone(self, p: tuple[float, float], tc, tr: float) -> bool:
        """p 가 다음 자기장 안에 있는지 (안쪽 마진 적용). tc 가 None 이면 어디든 True."""
        if tc is None:
            return True
        return _dist(p, tc) <= max(0.0, tr - self.SAFE_MARGIN_PX)

    def _can_visit_outside(self, eta: float) -> bool:
        return eta > self.URGENT_ETA_SEC

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

    def _pick_safer_target(self, pos, enemy_pos, vision, tc, tr):
        """적에게서 멀어지면서 자원에 가까워지는 타겟 좌표. 없으면 None.

        - 후보: 시야 내 상자/코인/아이템 중 target_zone 안에 있는 것
        - 적과의 거리가 봇의 현재 적-거리보다 더 먼 위치만
        - 점수: 봇과의 거리(가까울수록 좋음) − (적과 더 먼 만큼) × 0.5
        """
        candidates: list[tuple[float, float]] = []
        for c in vision.get("chests", []):
            p = (float(c["pos"][0]), float(c["pos"][1]))
            if self._in_target_zone(p, tc, tr):
                candidates.append(p)
        for n in vision.get("nodes", []):
            p = (float(n["pos"][0]), float(n["pos"][1]))
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
                continue   # 적과 더 가까워지는 타겟 제외
            d_self = _dist(pos, p)
            score = d_self - (p_to_enemy - bot_to_enemy) * 0.5
            if score < best_score:
                best_score = score
                best = p
        return best

    # ---------- 메인 의사결정 ----------
    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        action = _zero_action()
        me = state.get("self", {})
        pos = tuple(me.get("pos", [0.0, 0.0]))
        hp = int(me.get("hp", 0))
        has_potion = bool(me.get("has_potion", False))
        dash_cd = float(me.get("dash_cd", 0.0))
        zone = state.get("zone", {})
        vision = state.get("vision", {})

        target_center, target_radius, target_eta = self._extract_target_zone(zone)

        # 1. HP 낮은데 포션 보유 → 같은 틱에 사용
        if has_potion and hp < self.LOW_HP_THRESHOLD:
            action["use_potion"] = True

        # 2. 다음 자기장 밖이면 target_center 로 이동 (경계 왕복 방지 핵심)
        if target_center is not None and not self._in_target_zone(pos, target_center, target_radius):
            dir_to = _norm((target_center[0] - pos[0], target_center[1] - pos[1]))
            action["move_dir"] = list(dir_to)
            action["aim_dir"] = list(dir_to)
            if dash_cd <= 0.0:
                action["dash"] = True
            return self._safe_return(action, pos)

        # 3. 폴백: target 정보 없을 때 현재 자기장 밖이면 현재 center 로
        if zone.get("active", False) and zone.get("damage", 0.0) > 0.0:
            zc = tuple(zone.get("center", [0.0, 0.0]))
            zr = float(zone.get("radius", 0.0))
            if _dist(pos, zc) > zr:
                dir_to = _norm((zc[0] - pos[0], zc[1] - pos[1]))
                action["move_dir"] = list(dir_to)
                action["aim_dir"] = list(dir_to)
                if dash_cd <= 0.0:
                    action["dash"] = True
                return self._safe_return(action, pos)

        # 3.5 상자 열기 진행 중이면 자리 고수 (피격 감수). chest_progress > 0 인 동안엔 이동/도망 안 함.
        chest_progress = float(me.get("chest_progress", 0.0))
        if 0.0 < chest_progress < 1.0:
            action["move_dir"] = [0.0, 0.0]
            action["pickup"] = True
            return self._safe_return(action, pos)

        # 4. 너무 가까운 적 → 회피.
        # 우선: 자원(상자/코인/아이템) 중 적과 더 멀고 봇과 가까운 곳으로 향함 (목표 기반 회피 = 코너 갇힘 방지)
        # 폴백: 자원 없으면 기존 away/측면 로직
        enemies = vision.get("enemies", [])
        if enemies:
            nearest = min(enemies, key=lambda e: _dist(pos, tuple(e["pos"])))
            enemy_pos = tuple(nearest["pos"])
            d = _dist(pos, enemy_pos)
            if d < self.FLEE_RANGE:
                safe = self._pick_safer_target(pos, enemy_pos, vision, target_center, target_radius)
                if safe is not None:
                    aim = _norm((safe[0] - pos[0], safe[1] - pos[1]))
                    action["move_dir"] = list(aim)
                    action["aim_dir"] = list(aim)
                    if dash_cd <= 0.0 and d < 90.0:
                        action["dash"] = True
                    return self._safe_return(action, pos)
                # 폴백 — 적 반대로, 자기장 밖이면 측면
                away = _norm((pos[0] - enemy_pos[0], pos[1] - enemy_pos[1]))
                flee_target = (pos[0] + away[0] * 120.0, pos[1] + away[1] * 120.0)
                if target_center is not None and not self._in_target_zone(flee_target, target_center, target_radius):
                    perp_a = (-away[1], away[0])
                    perp_b = (away[1], -away[0])
                    cand_a = (pos[0] + perp_a[0] * 120.0, pos[1] + perp_a[1] * 120.0)
                    cand_b = (pos[0] + perp_b[0] * 120.0, pos[1] + perp_b[1] * 120.0)
                    away = perp_a if _dist(cand_a, target_center) < _dist(cand_b, target_center) else perp_b
                action["move_dir"] = list(away)
                action["aim_dir"] = list(away)
                if dash_cd <= 0.0 and d < 90.0:
                    action["dash"] = True
                return self._safe_return(action, pos)

        # 5. 드롭 아이템 — 자기 상자 옆에 떨어진 거 우선
        items = vision.get("items", [])
        if items:
            in_safe = [i for i in items if self._in_target_zone(tuple(i["pos"]), target_center, target_radius)]
            if in_safe:
                pool_i = in_safe
            elif self._can_visit_outside(target_eta):
                pool_i = items
            else:
                pool_i = []
            if pool_i:
                tgt = min(pool_i, key=lambda i: _dist(pos, tuple(i["pos"])))
                dir_to = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
                action["move_dir"] = list(dir_to)
                action["aim_dir"] = list(dir_to)
                return self._safe_return(action, pos)

        # 6. 코인 — 다음 자기장 안 우선. 시간 여유면 밖도 허용.
        nodes = vision.get("nodes", [])
        if nodes:
            in_safe = [n for n in nodes if self._in_target_zone(tuple(n["pos"]), target_center, target_radius)]
            if in_safe:
                pool = [n for n in in_safe if n.get("rare")] or in_safe
            elif self._can_visit_outside(target_eta):
                pool = [n for n in nodes if n.get("rare")] or nodes
            else:
                pool = []
            if pool:
                tgt = min(pool, key=lambda n: _dist(pos, tuple(n["pos"])))
                dir_to = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
                action["move_dir"] = list(dir_to)
                action["aim_dir"] = list(dir_to)
                return self._safe_return(action, pos)

        # 6. 상자 — 다음 자기장 안 우선, 인접 시 pickup
        chests = vision.get("chests", [])
        if chests:
            in_safe = [c for c in chests if self._in_target_zone(tuple(c["pos"]), target_center, target_radius)]
            if in_safe:
                pool = in_safe
            elif self._can_visit_outside(target_eta):
                pool = chests
            else:
                pool = []
            if pool:
                tgt = min(pool, key=lambda c: _dist(pos, tuple(c["pos"])))
                d = _dist(pos, tuple(tgt["pos"]))
                dir_to = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
                action["aim_dir"] = list(dir_to)
                if d <= self.CHEST_INTERACT_RANGE:
                    action["move_dir"] = [0.0, 0.0]
                    action["pickup"] = True
                else:
                    action["move_dir"] = list(dir_to)
                return self._safe_return(action, pos)

        # 8. 폴백: target 정보 있으면 그 중심으로 천천히, 없으면 매치 시작 클러스터로
        if target_center is not None:
            dir_to = _norm((target_center[0] - pos[0], target_center[1] - pos[1]))
            action["move_dir"] = [dir_to[0] * 0.5, dir_to[1] * 0.5]
            action["aim_dir"] = list(dir_to)
            return self._safe_return(action, pos)
        targets = self._map_info.get("chest_clusters", []) or self._map_info.get("rare_clusters", [])
        if targets:
            tgt = targets[0]
            dir_to = _norm((float(tgt[0]) - pos[0], float(tgt[1]) - pos[1]))
            action["move_dir"] = [dir_to[0] * 0.5, dir_to[1] * 0.5]
            action["aim_dir"] = list(dir_to)
        return self._safe_return(action, pos)

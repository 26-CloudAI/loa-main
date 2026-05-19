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

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict[str, Any]) -> tuple[float, float] | None:
        self._map_info = map_info
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
            return action

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
                return action

        # 4. 너무 가까운 적 → 도망. 도망 방향이 target_zone 밖이면 측면 회피.
        enemies = vision.get("enemies", [])
        if enemies:
            nearest = min(enemies, key=lambda e: _dist(pos, tuple(e["pos"])))
            d = _dist(pos, tuple(nearest["pos"]))
            if d < self.FLEE_RANGE:
                away = _norm((pos[0] - nearest["pos"][0], pos[1] - nearest["pos"][1]))
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
                return action

        # 5. 코인 — 다음 자기장 안 우선. 시간 여유면 밖도 허용.
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
                return action

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
                return action

        # 7. 드롭 아이템 — 다음 자기장 안 우선
        items = vision.get("items", [])
        if items:
            in_safe = [i for i in items if self._in_target_zone(tuple(i["pos"]), target_center, target_radius)]
            if in_safe:
                pool = in_safe
            elif self._can_visit_outside(target_eta):
                pool = items
            else:
                pool = []
            if pool:
                tgt = min(pool, key=lambda i: _dist(pos, tuple(i["pos"])))
                dir_to = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
                action["move_dir"] = list(dir_to)
                action["aim_dir"] = list(dir_to)
                return action

        # 8. 폴백: target 정보 있으면 그 중심으로 천천히, 없으면 매치 시작 클러스터로
        if target_center is not None:
            dir_to = _norm((target_center[0] - pos[0], target_center[1] - pos[1]))
            action["move_dir"] = [dir_to[0] * 0.5, dir_to[1] * 0.5]
            action["aim_dir"] = list(dir_to)
            return action
        targets = self._map_info.get("chest_clusters", []) or self._map_info.get("rare_clusters", [])
        if targets:
            tgt = targets[0]
            dir_to = _norm((float(tgt[0]) - pos[0], float(tgt[1]) - pos[1]))
            action["move_dir"] = [dir_to[0] * 0.5, dir_to[1] * 0.5]
            action["aim_dir"] = list(dir_to)
        return action

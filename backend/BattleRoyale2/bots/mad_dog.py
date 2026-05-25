"""MadDogBot — 공격형. 사거리 안에 적이 있으면 무조건 공격.

전략 (우선순위 높음 → 낮음):
1. HP 낮고 포션 보유 → use_potion (다른 행동과 동시 가능)
2. 다음 자기장 (target_zone) 밖이면 target_center 로 이동 — 죽으면 의미 없음
3. 시야 내 적이 사거리 안 (원거리 또는 근접) → 그 자리에서 공격
4. 시야 내 적이 사거리 밖 → 추격 (멀면 dash)
5. 적 없으면 다음 자기장 안 우선으로 상자 > 코인 파밍
6. 폴백: 다음 자기장 중심으로 천천히
"""
from __future__ import annotations

import math
import random
from typing import Any

from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot


# 룰 명세 동기 (Godot balance.gd 참조)
MELEE_RANGE = 60.0
RANGED_RANGE = 400.0
EDGE_MARGIN = 100.0


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


class MadDogBot(BattleRoyale2DBot):
    """미친개 봇 — 사거리 닿으면 무조건 공격, 못 닿으면 추격."""

    LOW_HP_THRESHOLD = 60        # 200 max 중 30%
    CHASE_DASH_MIN_DIST = 100.0  # 적이 이 이상 멀면 추격 시 dash
    CHEST_INTERACT_RANGE = 38.0
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
        # 미친개는 적이 많이 모일 곳에 가까이 스폰 — 희귀 코인 클러스터 우선
        candidates: list[tuple[float, float]] = []
        for c in map_info.get("rare_clusters", []):
            candidates.append((float(c[0]), float(c[1])))
        if not candidates:
            for c in map_info.get("chest_clusters", []):
                candidates.append((float(c[0]), float(c[1])))
        if not candidates:
            return None
        cx, cy = self._rng.choice(candidates)
        return (cx + self._rng.uniform(-50.0, 50.0), cy + self._rng.uniform(-50.0, 50.0))

    # ---------- 내부 유틸 ----------
    @staticmethod
    def _extract_target_zone(zone: dict[str, Any]):
        if not zone.get("active", False) or "target_center" not in zone:
            return None, 0.0, float("inf")
        tc = (float(zone["target_center"][0]), float(zone["target_center"][1]))
        return tc, float(zone.get("target_radius", 0.0)), float(zone.get("target_eta", float("inf")))

    def _in_target_zone(self, p, tc, tr: float) -> bool:
        if tc is None:
            return True
        return _dist(p, tc) <= max(0.0, tr - self.SAFE_MARGIN_PX)

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

    # ---------- 메인 의사결정 ----------
    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        action = _zero_action()
        me = state.get("self", {})
        pos = tuple(me.get("pos", [0.0, 0.0]))
        hp = int(me.get("hp", 0))
        has_potion = bool(me.get("has_potion", False))
        has_ranged = bool(me.get("has_ranged", False))
        dash_cd = float(me.get("dash_cd", 0.0))
        zone = state.get("zone", {})
        vision = state.get("vision", {})

        tc, tr, _eta = self._extract_target_zone(zone)

        # 1. HP 낮은데 포션 → 사용
        if has_potion and hp < self.LOW_HP_THRESHOLD:
            action["use_potion"] = True

        # 2. 다음 자기장 밖 → target_center 로 (생존 우선)
        if tc is not None and not self._in_target_zone(pos, tc, tr):
            d = _norm((tc[0] - pos[0], tc[1] - pos[1]))
            action["move_dir"] = list(d)
            action["aim_dir"] = list(d)
            if dash_cd <= 0.0:
                action["dash"] = True
            return self._safe_return(action, pos)

        # 폴백 (target 정보 없을 때 현재 zone 기준)
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

        # 2.5 상자 열기 진행 중이면 자리 고수 (피격 감수).
        chest_progress = float(me.get("chest_progress", 0.0))
        if 0.0 < chest_progress < 1.0:
            action["move_dir"] = [0.0, 0.0]
            action["pickup"] = True
            return self._safe_return(action, pos)

        # 3~4. 적 탐색
        enemies = vision.get("enemies", [])
        if enemies:
            # 가장 가까운 적 추격 (미친개스럽게)
            nearest = min(enemies, key=lambda e: _dist(pos, tuple(e["pos"])))
            epos = tuple(nearest["pos"])
            ed = _dist(pos, epos)
            aim = _norm((epos[0] - pos[0], epos[1] - pos[1]))
            atk_range = self._attack_range(has_ranged)

            # 사거리 안 → 공격 (제자리)
            if ed <= atk_range:
                action["aim_dir"] = list(aim)
                action["move_dir"] = [0.0, 0.0]
                action["attack"] = True
                return self._safe_return(action, pos)

            # 사거리 밖 → 추격
            action["aim_dir"] = list(aim)
            action["move_dir"] = list(aim)
            if ed >= self.CHASE_DASH_MIN_DIST and dash_cd <= 0.0:
                action["dash"] = True
            return self._safe_return(action, pos)

        # 5. 적 없음 → 자원 채집 (드롭 아이템 > 상자 > 코인). 다음 자기장 안 우선.
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
                d = _dist(pos, tuple(tgt["pos"]))
                aim = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
                action["aim_dir"] = list(aim)
                if d <= self.CHEST_INTERACT_RANGE:
                    action["move_dir"] = [0.0, 0.0]
                    action["pickup"] = True
                else:
                    action["move_dir"] = list(aim)
                return self._safe_return(action, pos)

        nodes = vision.get("nodes", [])
        if nodes:
            in_safe = [n for n in nodes if self._in_target_zone(tuple(n["pos"]), tc, tr)]
            pool_n = in_safe if in_safe else nodes
            tgt = min(pool_n, key=lambda n: _dist(pos, tuple(n["pos"])))
            aim = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
            action["move_dir"] = list(aim)
            action["aim_dir"] = list(aim)
            return self._safe_return(action, pos)

        # 6. 폴백: target 중심으로 천천히
        if tc is not None:
            aim = _norm((tc[0] - pos[0], tc[1] - pos[1]))
            action["move_dir"] = [aim[0] * 0.5, aim[1] * 0.5]
            action["aim_dir"] = list(aim)
            return self._safe_return(action, pos)
        targets = self._map_info.get("chest_clusters", []) or self._map_info.get("rare_clusters", [])
        if targets:
            t = targets[0]
            aim = _norm((float(t[0]) - pos[0], float(t[1]) - pos[1]))
            action["move_dir"] = [aim[0] * 0.5, aim[1] * 0.5]
            action["aim_dir"] = list(aim)
        return self._safe_return(action, pos)

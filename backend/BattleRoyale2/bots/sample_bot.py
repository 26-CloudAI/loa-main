"""HerbivoreBot — 코인 채집형 샘플 봇.

전략 (우선순위 높음 → 낮음):
1. HP 낮은데 포션 보유 → 즉시 사용
2. 자기장 밖이면 중심 방향으로 이동 (대시 가능 시 dash)
3. 시야 내 적이 너무 가까우면 (≤120px) 반대 방향으로 도망
4. 시야 내 희귀 코인 / 일반 코인 → 가까운 쪽으로 이동
5. 시야 내 상자 → 인접하면 pickup, 아니면 접근
6. 시야 내 아이템(드롭) → 이동해서 줍기
7. 그 외에는 매치 시작 정보의 클러스터 방향으로 천천히 배회

샘플이라 공격은 거의 안 하고, 자원 채집·생존 위주.
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
    """초식 봇 — 자원 채집과 생존을 우선시한다."""

    LOW_HP_THRESHOLD = 80           # 200 max 중
    FLEE_RANGE = 120.0
    CHEST_INTERACT_RANGE = 38.0

    def __init__(self, bot_id: str, seed: int | None = None):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._map_info: dict[str, Any] = {}

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict[str, Any]) -> tuple[float, float] | None:
        self._map_info = map_info
        # 희귀 코인 클러스터를 선호. 없으면 상자 클러스터, 없으면 None(랜덤)
        candidates: list[tuple[float, float]] = []
        for cluster in map_info.get("rare_clusters", []):
            candidates.append((float(cluster[0]), float(cluster[1])))
        if not candidates:
            for cluster in map_info.get("chest_clusters", []):
                candidates.append((float(cluster[0]), float(cluster[1])))
        if not candidates:
            return None
        cx, cy = self._rng.choice(candidates)
        # 클러스터 중심 ±60px 안에 스폰
        return (cx + self._rng.uniform(-60.0, 60.0), cy + self._rng.uniform(-60.0, 60.0))

    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        action = _zero_action()
        me = state.get("self", {})
        pos = tuple(me.get("pos", [0.0, 0.0]))
        hp = int(me.get("hp", 0))
        max_hp = int(me.get("max_hp", 1))
        has_potion = bool(me.get("has_potion", False))
        zone = state.get("zone", {})
        vision = state.get("vision", {})

        # 1. HP 낮은데 포션 보유 → 동시에 사용 (이동·공격과 같이 가능)
        if has_potion and hp < self.LOW_HP_THRESHOLD:
            action["use_potion"] = True

        # 2. 자기장 밖이면 중심으로 (DoT 활성일 때만)
        if zone.get("active", False) and zone.get("damage", 0.0) > 0.0:
            zc = tuple(zone.get("center", [0.0, 0.0]))
            zr = float(zone.get("radius", 0.0))
            if _dist(pos, zc) > zr:
                dir_to_center = _norm((zc[0] - pos[0], zc[1] - pos[1]))
                action["move_dir"] = list(dir_to_center)
                action["aim_dir"] = list(dir_to_center)
                if float(me.get("dash_cd", 0.0)) <= 0.0:
                    action["dash"] = True
                return action

        # 3. 너무 가까운 적이 있으면 도망
        enemies = vision.get("enemies", [])
        if enemies:
            nearest_enemy = min(enemies, key=lambda e: _dist(pos, tuple(e["pos"])))
            d = _dist(pos, tuple(nearest_enemy["pos"]))
            if d < self.FLEE_RANGE:
                away = _norm((pos[0] - nearest_enemy["pos"][0], pos[1] - nearest_enemy["pos"][1]))
                action["move_dir"] = list(away)
                action["aim_dir"] = list(away)
                if float(me.get("dash_cd", 0.0)) <= 0.0 and d < 90.0:
                    action["dash"] = True
                return action

        # 4. 시야 내 코인 (희귀 우선)
        nodes = vision.get("nodes", [])
        if nodes:
            rare = [n for n in nodes if n.get("rare")]
            target_pool = rare if rare else nodes
            tgt = min(target_pool, key=lambda n: _dist(pos, tuple(n["pos"])))
            dir_to = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
            action["move_dir"] = list(dir_to)
            action["aim_dir"] = list(dir_to)
            return action

        # 5. 시야 내 상자 — 인접하면 pickup, 아니면 접근
        chests = vision.get("chests", [])
        if chests:
            tgt = min(chests, key=lambda c: _dist(pos, tuple(c["pos"])))
            d = _dist(pos, tuple(tgt["pos"]))
            dir_to = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
            action["aim_dir"] = list(dir_to)
            if d <= self.CHEST_INTERACT_RANGE:
                action["move_dir"] = [0.0, 0.0]
                action["pickup"] = True
            else:
                action["move_dir"] = list(dir_to)
            return action

        # 6. 드롭 아이템 — 그냥 위 코인과 같은 방식
        items = vision.get("items", [])
        if items:
            tgt = min(items, key=lambda i: _dist(pos, tuple(i["pos"])))
            dir_to = _norm((tgt["pos"][0] - pos[0], tgt["pos"][1] - pos[1]))
            action["move_dir"] = list(dir_to)
            action["aim_dir"] = list(dir_to)
            return action

        # 7. 폴백: 매치 시작 시 알게 된 클러스터(상자 우선) 방향으로 천천히 이동
        targets = self._map_info.get("chest_clusters", []) or self._map_info.get("rare_clusters", [])
        if targets:
            tgt = targets[0]
            dir_to = _norm((float(tgt[0]) - pos[0], float(tgt[1]) - pos[1]))
            action["move_dir"] = [dir_to[0] * 0.5, dir_to[1] * 0.5]
            action["aim_dir"] = list(dir_to)
        return action

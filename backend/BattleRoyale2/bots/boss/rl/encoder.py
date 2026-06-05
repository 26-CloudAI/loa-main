"""BR2 state dict → 고정 길이 feature vector.

옛 backend/battle_royale/bots/boss/rl_boss_bot.py 의 StateEncoder(43-D, 5×5 grid 기반)
와는 다른 형식 — BR2는 연속 2D 라 ego-centric polar/relative 인코딩을 사용한다.

총 80차원 (round number for SIMD friendliness, padding 포함):
  self_core         (10) — hp_ratio, vel(2), atk/def/speed norm, 3 cd, has_potion/has_ranged
  self_meta         (3)  — pos_x/map_w, pos_y/map_h, time/duration
  enemy_top3        (18) — 가까운 적 3마리 × (rel_dx, rel_dy, dist_n, hp_ratio, guarding, has_ranged)
  node_top3         (12) — 가까운 코인 3개 × (rel_dx, rel_dy, dist_n, rare)
  chest_top2        (6)  — 가까운 상자 2개 × (rel_dx, rel_dy, dist_n)
  item_top2         (6)  — 가까운 드롭 아이템 2개 × (rel_dx, rel_dy, dist_n)
  projectile_top2   (10) — 가까운 투사체 2개 × (rel_dx, rel_dy, dist_n, vel_dx, vel_dy)
  zone              (9)  — active, rel_to_center(2), radius_n, damage, phase, target_rel(2), target_eta_n
  leaderboard_self  (1)  — 내 점수 / 1위 점수 (없으면 1.0)
  bias              (1)  — 상수 1.0 (네트워크 bias unit 대용)
  padding           (4)
  ─────────────────────
  total = 80
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

# 인코더 형상 — encoder/decoder/network 모두 이 값을 import.
FEATURE_DIM: int = 80

# 정규화 상수 (BR2 base. boss_mode 일 때도 map_size 는 동일하다고 가정)
MAP_W: float = 3000.0
MAP_H: float = 3000.0
MAP_DIAG: float = math.hypot(MAP_W, MAP_H)
MAX_HP: float = 200.0
MAX_ATK: float = 50.0
MAX_DEF: float = 30.0
MAX_SPEED: float = 300.0
MAX_CD: float = 3.0
ZONE_DAMAGE_NORM: float = 5.0
PROJECTILE_VEL_NORM: float = 500.0
DEFAULT_MATCH_DURATION: float = 360.0   # 보스 모드 기본 — encode 시 동적 override 가능

# 상위 K
K_ENEMIES: int = 3
K_NODES: int = 3
K_CHESTS: int = 2
K_ITEMS: int = 2
K_PROJECTILES: int = 2


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _dist_norm(dx: float, dy: float) -> float:
    """0~1 정규화 거리 (맵 대각선 기준)."""
    return min(1.0, math.hypot(dx, dy) / MAP_DIAG)


def _rel(x: float, y: float, ox: float, oy: float) -> tuple[float, float, float]:
    """ego-centric relative (dx, dy, dist_normalized). dx/dy 는 dist 로 정규화."""
    dx = ox - x
    dy = oy - y
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return (0.0, 0.0, 0.0)
    return (dx / d, dy / d, min(1.0, d / MAP_DIAG))


def encode_state(state: dict[str, Any], duration_sec: float = DEFAULT_MATCH_DURATION) -> np.ndarray:
    """BR2 state → np.ndarray shape=(FEATURE_DIM,) float32.

    Args:
        state: BR2 PROTOCOL.md §3.4 형식 state.
        duration_sec: 매치 길이(time 정규화용). 보스 모드면 360, 일반 180.
    """
    feat = np.zeros(FEATURE_DIM, dtype=np.float32)

    me = state.get("self", {}) or {}
    px, py = (float(v) for v in me.get("pos", [0.0, 0.0]))
    vx, vy = (float(v) for v in me.get("vel", [0.0, 0.0]))
    hp = float(me.get("hp", 0))
    max_hp = float(me.get("max_hp", MAX_HP) or MAX_HP)
    atk = float(me.get("atk", 0.0))
    def_ = float(me.get("def", 0.0))
    speed = float(me.get("speed", 0.0))
    attack_cd = float(me.get("attack_cd", 0.0))
    dash_cd = float(me.get("dash_cd", 0.0))
    guard_cd = float(me.get("guard_cd", 0.0))
    has_potion = 1.0 if me.get("has_potion") else 0.0
    has_ranged = 1.0 if me.get("has_ranged") else 0.0

    # self_core (10) — offsets 0..9
    feat[0] = _clamp(hp / max_hp, 0.0, 1.0)
    feat[1] = _clamp(vx / MAX_SPEED)
    feat[2] = _clamp(vy / MAX_SPEED)
    feat[3] = _clamp(atk / MAX_ATK, 0.0, 1.0)
    feat[4] = _clamp(def_ / MAX_DEF, 0.0, 1.0)
    feat[5] = _clamp(speed / MAX_SPEED, 0.0, 1.0)
    feat[6] = _clamp(attack_cd / MAX_CD, 0.0, 1.0)
    feat[7] = _clamp(dash_cd / MAX_CD, 0.0, 1.0)
    feat[8] = _clamp(guard_cd / MAX_CD, 0.0, 1.0)
    # 9: potion+ranged 압축
    feat[9] = has_potion + has_ranged * 2.0   # 0,1,2,3 4상태 코드

    # self_meta (3) — 10..12
    feat[10] = _clamp(px / MAP_W, 0.0, 1.0)
    feat[11] = _clamp(py / MAP_H, 0.0, 1.0)
    t = float(state.get("time", 0.0))
    feat[12] = _clamp(t / max(1.0, duration_sec), 0.0, 1.0)

    vision = state.get("vision", {}) or {}

    # enemy_top3 (18) — 13..30, 6 per enemy
    enemies = sorted(
        vision.get("enemies", []) or [],
        key=lambda e: (e["pos"][0] - px) ** 2 + (e["pos"][1] - py) ** 2,
    )[:K_ENEMIES]
    off = 13
    for e in enemies:
        ex, ey = float(e["pos"][0]), float(e["pos"][1])
        rdx, rdy, dn = _rel(px, py, ex, ey)
        feat[off + 0] = rdx
        feat[off + 1] = rdy
        feat[off + 2] = dn
        feat[off + 3] = _clamp(float(e.get("hp", 0)) / max_hp, 0.0, 1.0)
        feat[off + 4] = 1.0 if e.get("guarding") else 0.0
        feat[off + 5] = 1.0 if e.get("has_ranged") else 0.0
        off += 6
    off = 31   # 13 + 18

    # node_top3 (12) — 31..42, 4 per node
    nodes = sorted(
        vision.get("nodes", []) or [],
        key=lambda n: (n["pos"][0] - px) ** 2 + (n["pos"][1] - py) ** 2,
    )[:K_NODES]
    for n in nodes:
        nx, ny = float(n["pos"][0]), float(n["pos"][1])
        rdx, rdy, dn = _rel(px, py, nx, ny)
        feat[off + 0] = rdx
        feat[off + 1] = rdy
        feat[off + 2] = dn
        feat[off + 3] = 1.0 if n.get("rare") else 0.0
        off += 4
    off = 43

    # chest_top2 (6) — 43..48, 3 per chest
    chests = sorted(
        vision.get("chests", []) or [],
        key=lambda c: (c["pos"][0] - px) ** 2 + (c["pos"][1] - py) ** 2,
    )[:K_CHESTS]
    for c in chests:
        cx, cy = float(c["pos"][0]), float(c["pos"][1])
        rdx, rdy, dn = _rel(px, py, cx, cy)
        feat[off + 0] = rdx
        feat[off + 1] = rdy
        feat[off + 2] = dn
        off += 3
    off = 49

    # item_top2 (6) — 49..54, 3 per item
    items = sorted(
        vision.get("items", []) or [],
        key=lambda it: (it["pos"][0] - px) ** 2 + (it["pos"][1] - py) ** 2,
    )[:K_ITEMS]
    for it in items:
        ix, iy = float(it["pos"][0]), float(it["pos"][1])
        rdx, rdy, dn = _rel(px, py, ix, iy)
        feat[off + 0] = rdx
        feat[off + 1] = rdy
        feat[off + 2] = dn
        off += 3
    off = 55

    # projectile_top2 (10) — 55..64, 5 per projectile
    projectiles = sorted(
        vision.get("projectiles", []) or [],
        key=lambda p: (p["pos"][0] - px) ** 2 + (p["pos"][1] - py) ** 2,
    )[:K_PROJECTILES]
    for p in projectiles:
        ppx, ppy = float(p["pos"][0]), float(p["pos"][1])
        rdx, rdy, dn = _rel(px, py, ppx, ppy)
        feat[off + 0] = rdx
        feat[off + 1] = rdy
        feat[off + 2] = dn
        pvx, pvy = (float(v) for v in p.get("vel", [0.0, 0.0]))
        feat[off + 3] = _clamp(pvx / PROJECTILE_VEL_NORM)
        feat[off + 4] = _clamp(pvy / PROJECTILE_VEL_NORM)
        off += 5
    off = 65

    # zone (9) — 65..73
    zone = state.get("zone", {}) or {}
    if zone.get("active"):
        zc = zone.get("center", [MAP_W * 0.5, MAP_H * 0.5])
        zcx, zcy = float(zc[0]), float(zc[1])
        zradius = float(zone.get("radius", 0.0))
        zdamage = float(zone.get("damage", 0.0))
        zphase = float(zone.get("phase", 0.0))
        rdx, rdy, _ = _rel(px, py, zcx, zcy)
        feat[off + 0] = 1.0
        feat[off + 1] = rdx
        feat[off + 2] = rdy
        feat[off + 3] = _clamp(zradius / MAP_DIAG, 0.0, 1.0)
        feat[off + 4] = _clamp(zdamage / ZONE_DAMAGE_NORM, 0.0, 1.0)
        feat[off + 5] = _clamp(zphase / 5.0, 0.0, 1.0)
        tc = zone.get("target_center")
        if tc is not None:
            trdx, trdy, _ = _rel(px, py, float(tc[0]), float(tc[1]))
            feat[off + 6] = trdx
            feat[off + 7] = trdy
            feat[off + 8] = _clamp(float(zone.get("target_eta", 0.0)) / 60.0, 0.0, 1.0)
    # else: 모두 0
    off = 74

    # leaderboard_self (1) — 74
    lb = state.get("leaderboard", []) or []
    if lb:
        my_id = me.get("id") or me.get("bot_id")
        top_score = max((float(r.get("score", 0.0)) for r in lb), default=1.0) or 1.0
        my_score = 0.0
        for r in lb:
            if r.get("id") == my_id:
                my_score = float(r.get("score", 0.0))
                break
        feat[off] = _clamp(my_score / top_score, 0.0, 1.0)
    off = 75

    # bias (1) — 75
    feat[75] = 1.0
    # 76..79 padding (zeros) — 향후 feature 확장 여지

    return feat


__all__ = ["encode_state", "FEATURE_DIM", "DEFAULT_MATCH_DURATION"]

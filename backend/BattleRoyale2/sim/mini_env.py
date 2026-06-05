"""BR2 학습용 미니 시뮬 — 순수 Python.

Godot 실제 매치를 단순화한 환경. 학습 속도 우선 + 핵심 동역학 보존.
인코더 / 디코더 / 룰 보스가 받는 state dict 와 동일 형식 제공 (encoder.py 명세).

사용:
    env = BR2MiniEnv(seed=42, duration_sec=360.0, map_w=3000.0, map_h=3000.0)
    states = env.reset(bots=[
        {"id": "boss",   "stat": {"max_hp_mult": 2.0, "atk_mult": 1.2, ...}},
        {"id": "player", "stat": None},  # base stat
        {"id": "ai_0",   "stat": None},
    ])
    while not env.done:
        actions = {bid: bot.get_action(states[bid]) for bid, bot in bots.items()}
        states, rewards, done, info = env.step(actions)

설계 노트:
    - 좌표계: Godot 과 동일 (x 오른쪽+, y 아래+)
    - 액션 dict: {"move_dir": [x,y], "aim_dir": [x,y], "attack": bool, "guard": bool,
                  "dash": bool, "pickup": bool, "use_potion": bool}
    - 단위벡터 노름 1 가정 (디코더 출력 보장). 노름 0 이면 STAY.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Optional

# ── 게임 상수 (Godot balance.gd 추정 + boss_mode 룰) ─────────────────────
TICK_DT: float = 0.1               # 100ms 결정 틱
BASE_DURATION_SEC: float = 180.0
BOSS_DURATION_SEC: float = 360.0
MAP_W: float = 3000.0
MAP_H: float = 3000.0
EDGE_MARGIN: float = 50.0

# 봇 기본 stat
BASE_HP: int = 200
BASE_ATK: int = 10
BASE_DEF: int = 5
BASE_SPEED: float = 100.0          # px/s
BOT_RADIUS: float = 25.0

# 액션·전투
MELEE_RANGE: float = 60.0
RANGED_RANGE: float = 400.0
ATTACK_CD_SEC: float = 0.6
GUARD_CD_SEC: float = 2.0
GUARD_DURATION_SEC: float = 0.3
DASH_CD_SEC: float = 3.0
DASH_DURATION_SEC: float = 0.15
DASH_SPEED_MULT: float = 4.0
GUARD_DAMAGE_REDUCTION: float = 0.5

# 자원
NODE_PICKUP_RANGE: float = 30.0    # 코인 자동 채집 거리
CHEST_PICKUP_RANGE: float = 35.0
CHEST_OPEN_DURATION_SEC: float = 1.5
NODE_HEAL_NORMAL: int = 15
NODE_HEAL_RARE: int = 50
NODE_SCORE_NORMAL: int = 1
NODE_SCORE_RARE: int = 5
CHEST_SCORE: int = 10

# 포션
POTION_HEAL: int = 80
LOW_HP_RATIO_AUTO_POTION: float = 0.4

# 자기장 (boss 모드 phase)
# rules/boss_mode.py 와 일관: phase1_end=135s, phase2_end=288s, 매치 360s
ZONE_PHASE0_END: float = 30.0      # 0~30s: 비활성
ZONE_PHASE1_END: float = 135.0     # 30~135s: damage 1, radius 1500→900
ZONE_PHASE2_END: float = 288.0     # 135~288s: damage 2, radius 900→400
ZONE_PHASE3_END: float = 360.0     # 288~360s: damage 4, radius 400→100
ZONE_INITIAL_RADIUS: float = 1500.0
ZONE_PHASE1_END_RADIUS: float = 900.0
ZONE_PHASE2_END_RADIUS: float = 400.0
ZONE_PHASE3_END_RADIUS: float = 100.0
ZONE_DAMAGE_PHASE1: float = 1.0
ZONE_DAMAGE_PHASE2: float = 2.0
ZONE_DAMAGE_PHASE3: float = 4.0

# 자원 초기 분포
DEFAULT_RARE_CLUSTERS: int = 6
DEFAULT_CHEST_CLUSTERS: int = 6
DEFAULT_INITIAL_NODES: int = 400
RARE_FRACTION: float = 0.15
CLUSTER_RADIUS: float = 200.0


# ── helper ──────────────────────────────────────────────────────────────
def _norm2(v: tuple[float, float]) -> tuple[float, float]:
    x, y = v
    n = math.hypot(x, y)
    if n < 1e-9:
        return (0.0, 0.0)
    return (x / n, y / n)


def _clip_to_map(x: float, y: float) -> tuple[float, float]:
    x = max(EDGE_MARGIN, min(MAP_W - EDGE_MARGIN, x))
    y = max(EDGE_MARGIN, min(MAP_H - EDGE_MARGIN, y))
    return (x, y)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ── 엔티티 ──────────────────────────────────────────────────────────────
@dataclass
class BR2BotState:
    """봇 한 마리 상태. is_boss=True 면 stat 곱셈 적용된 강화 보스."""
    bot_id: str
    pos: tuple[float, float]
    vel: tuple[float, float] = (0.0, 0.0)
    last_move_dir: tuple[float, float] = (1.0, 0.0)
    hp: int = BASE_HP
    max_hp: int = BASE_HP
    atk: int = BASE_ATK
    def_: int = BASE_DEF
    speed: float = BASE_SPEED
    attack_cd: float = 0.0
    guard_cd: float = 0.0
    dash_cd: float = 0.0
    guard_until: float = 0.0       # 이 시각 이전엔 guarding=True
    dash_until: float = 0.0
    has_potion: bool = True
    has_ranged: bool = False
    chest_progress: float = 0.0
    chest_target_id: Optional[int] = None
    score: float = 0.0
    is_boss: bool = False
    is_dead: bool = False
    rank: int = 0                  # 최종 순위 (1이 1위)
    # 통계
    damage_dealt: float = 0.0
    damage_taken: float = 0.0
    nodes_collected: int = 0


@dataclass
class _Node:
    id: int
    pos: tuple[float, float]
    rare: bool
    alive: bool = True


@dataclass
class _Chest:
    id: int
    pos: tuple[float, float]
    alive: bool = True


@dataclass
class _Item:
    id: int
    pos: tuple[float, float]
    kind: str   # "potion" | "ranged"
    alive: bool = True


@dataclass
class BR2EpisodeResult:
    """매치 종료 결과 — 학습 reward 계산용."""
    ranks: dict[str, int]               # bot_id → 최종 순위(1=1위)
    n_bots: int                         # 총 봇 수
    final_score: dict[str, float]
    final_hp: dict[str, int]
    damage_dealt: dict[str, float]
    damage_taken: dict[str, float]
    nodes_collected: dict[str, int]
    duration_ticks: int


# ── 환경 ────────────────────────────────────────────────────────────────
class BR2MiniEnv:
    """BR2 보스 모드 미니 시뮬. 한 매치당 하나 인스턴스."""

    def __init__(
        self,
        seed: Optional[int] = None,
        duration_sec: float = BOSS_DURATION_SEC,
        n_rare_clusters: int = DEFAULT_RARE_CLUSTERS,
        n_chest_clusters: int = DEFAULT_CHEST_CLUSTERS,
        n_initial_nodes: int = DEFAULT_INITIAL_NODES,
    ):
        self._rng = random.Random(seed)
        self.duration_sec = duration_sec
        self.max_ticks = int(duration_sec / TICK_DT)
        self._n_rare_clusters = n_rare_clusters
        self._n_chest_clusters = n_chest_clusters
        self._n_initial_nodes = n_initial_nodes

        self.tick: int = 0
        self.bots: dict[str, BR2BotState] = {}
        self.nodes: list[_Node] = []
        self.chests: list[_Chest] = []
        self.items: list[_Item] = []
        self.zone_center: tuple[float, float] = (MAP_W * 0.5, MAP_H * 0.5)
        self.zone_radius: float = ZONE_INITIAL_RADIUS
        self.zone_damage: float = 0.0
        self.zone_phase: int = 0
        self.zone_active: bool = False
        self.done: bool = False
        self._next_entity_id: int = 0

        # 스폰 좌표 캐시 (map_info용)
        self.rare_clusters: list[tuple[float, float]] = []
        self.chest_clusters: list[tuple[float, float]] = []

    # ── 초기화 ──────────────────────────────────────────────────────────
    def reset(self, bots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """매치 시작.

        Args:
            bots: 각 봇 spec [{"id": str, "stat": dict | None, "is_boss": bool, "spawn": [x,y] | None}]
                  stat dict 가 None 이면 base. 곱셈 키: max_hp_mult/atk_mult/def_mult/speed_mult.
        Returns:
            per-bot state dict (encoder 형식).
        """
        self.tick = 0
        self.done = False
        self.bots = {}
        self.nodes = []
        self.chests = []
        self.items = []
        self.zone_active = False
        self.zone_radius = ZONE_INITIAL_RADIUS
        self.zone_center = (MAP_W * 0.5, MAP_H * 0.5)
        self.zone_damage = 0.0
        self.zone_phase = 0
        self._next_entity_id = 0

        self._spawn_clusters()
        self._spawn_nodes()
        self._spawn_chests()

        # 봇 생성
        for spec in bots:
            bid = str(spec["id"])
            stat = spec.get("stat") or {}
            is_boss = bool(spec.get("is_boss", False))
            max_hp = int(BASE_HP * float(stat.get("max_hp_mult", 1.0)))
            atk = int(BASE_ATK * float(stat.get("atk_mult", 1.0)))
            def_ = int(BASE_DEF * float(stat.get("def_mult", 1.0)))
            speed = BASE_SPEED * float(stat.get("speed_mult", 1.0))
            spawn = spec.get("spawn")
            if spawn is not None:
                px, py = _clip_to_map(float(spawn[0]), float(spawn[1]))
            else:
                px = self._rng.uniform(EDGE_MARGIN, MAP_W - EDGE_MARGIN)
                py = self._rng.uniform(EDGE_MARGIN, MAP_H - EDGE_MARGIN)
            self.bots[bid] = BR2BotState(
                bot_id=bid,
                pos=(px, py),
                hp=max_hp,
                max_hp=max_hp,
                atk=atk,
                def_=def_,
                speed=speed,
                is_boss=is_boss,
            )

        return {bid: self.state_for(bid) for bid in self.bots}

    def _spawn_clusters(self) -> None:
        """rare / chest 클러스터 중심 좌표 생성. choose_spawn 의 map_info 에 노출."""
        self.rare_clusters = []
        for _ in range(self._n_rare_clusters):
            x = self._rng.uniform(EDGE_MARGIN + CLUSTER_RADIUS, MAP_W - EDGE_MARGIN - CLUSTER_RADIUS)
            y = self._rng.uniform(EDGE_MARGIN + CLUSTER_RADIUS, MAP_H - EDGE_MARGIN - CLUSTER_RADIUS)
            self.rare_clusters.append((x, y))
        self.chest_clusters = []
        for _ in range(self._n_chest_clusters):
            x = self._rng.uniform(EDGE_MARGIN + CLUSTER_RADIUS, MAP_W - EDGE_MARGIN - CLUSTER_RADIUS)
            y = self._rng.uniform(EDGE_MARGIN + CLUSTER_RADIUS, MAP_H - EDGE_MARGIN - CLUSTER_RADIUS)
            self.chest_clusters.append((x, y))

    def _spawn_nodes(self) -> None:
        """코인 노드 분포. 일부는 rare 클러스터 주변."""
        n_rare = int(self._n_initial_nodes * RARE_FRACTION)
        n_normal = self._n_initial_nodes - n_rare
        # rare nodes — 클러스터 주변
        for _ in range(n_rare):
            cx, cy = self._rng.choice(self.rare_clusters) if self.rare_clusters else (MAP_W * 0.5, MAP_H * 0.5)
            x = cx + self._rng.uniform(-CLUSTER_RADIUS, CLUSTER_RADIUS)
            y = cy + self._rng.uniform(-CLUSTER_RADIUS, CLUSTER_RADIUS)
            x, y = _clip_to_map(x, y)
            self.nodes.append(_Node(id=self._next_id(), pos=(x, y), rare=True))
        # normal nodes — 균일
        for _ in range(n_normal):
            x = self._rng.uniform(EDGE_MARGIN, MAP_W - EDGE_MARGIN)
            y = self._rng.uniform(EDGE_MARGIN, MAP_H - EDGE_MARGIN)
            self.nodes.append(_Node(id=self._next_id(), pos=(x, y), rare=False))

    def _spawn_chests(self) -> None:
        for cx, cy in self.chest_clusters:
            for _ in range(3):   # 클러스터당 3 상자
                x = cx + self._rng.uniform(-CLUSTER_RADIUS * 0.5, CLUSTER_RADIUS * 0.5)
                y = cy + self._rng.uniform(-CLUSTER_RADIUS * 0.5, CLUSTER_RADIUS * 0.5)
                x, y = _clip_to_map(x, y)
                self.chests.append(_Chest(id=self._next_id(), pos=(x, y)))

    def _next_id(self) -> int:
        i = self._next_entity_id
        self._next_entity_id += 1
        return i

    # ── 매치 정보 (choose_spawn 용) ────────────────────────────────────
    def map_info(self) -> dict[str, Any]:
        return {
            "map_size": [MAP_W, MAP_H],
            "rare_clusters": [list(c) for c in self.rare_clusters],
            "chest_clusters": [list(c) for c in self.chest_clusters],
        }

    # ── state dict (encoder 형식) ──────────────────────────────────────
    def state_for(self, bot_id: str) -> dict[str, Any]:
        me = self.bots[bot_id]
        t = self.tick * TICK_DT
        guarding = t < me.guard_until
        return {
            "time": t,
            "self": {
                "id": bot_id,
                "bot_id": bot_id,
                "pos": list(me.pos),
                "vel": list(me.vel),
                "hp": me.hp,
                "max_hp": me.max_hp,
                "atk": me.atk,
                "def": me.def_,
                "speed": me.speed,
                "attack_cd": max(0.0, me.attack_cd),
                "guard_cd": max(0.0, me.guard_cd),
                "dash_cd": max(0.0, me.dash_cd),
                "has_potion": me.has_potion,
                "has_ranged": me.has_ranged,
                "chest_progress": me.chest_progress,
                "guarding": guarding,
            },
            "vision": {
                "enemies": [
                    {
                        "id": b.bot_id,
                        "pos": list(b.pos),
                        "hp": b.hp,
                        "guarding": t < b.guard_until,
                        "has_ranged": b.has_ranged,
                    }
                    for bid, b in self.bots.items()
                    if bid != bot_id and not b.is_dead
                ],
                "nodes": [
                    {"pos": list(n.pos), "rare": n.rare}
                    for n in self.nodes if n.alive
                ],
                "chests": [
                    {"pos": list(c.pos)} for c in self.chests if c.alive
                ],
                "items": [
                    {"pos": list(it.pos), "kind": it.kind} for it in self.items if it.alive
                ],
                "projectiles": [],   # 미니 sim 은 즉발 공격, 투사체 미사용
            },
            "zone": self._zone_payload(),
            "leaderboard": sorted(
                [{"id": b.bot_id, "score": b.score} for b in self.bots.values()],
                key=lambda r: -r["score"],
            ),
        }

    def _zone_payload(self) -> dict[str, Any]:
        if not self.zone_active:
            return {"active": False}
        return {
            "active": True,
            "center": list(self.zone_center),
            "radius": self.zone_radius,
            "damage": self.zone_damage,
            "phase": self.zone_phase,
            "target_center": list(self.zone_center),
            "target_radius": self.zone_radius,
            "target_eta": 0.0,
        }

    # ── 한 틱 진행 ──────────────────────────────────────────────────────
    def step(
        self, actions: dict[str, dict[str, Any]]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, float], bool, dict[str, Any]]:
        """모든 봇 액션을 받아 한 틱 진행 후 새 상태/리워드/종료 반환."""
        prev_score = {bid: b.score for bid, b in self.bots.items()}
        prev_hp = {bid: b.hp for bid, b in self.bots.items()}

        self._advance_cooldowns()
        self._apply_actions(actions)
        self._update_chests()
        self._collect_nodes()
        self._advance_zone()
        self._apply_zone_damage()
        self._update_alive()

        self.tick += 1

        # 종료: 보스 죽음 OR 보스 외 전부 죽음 OR 시간 초과
        boss_alive = any(b.is_boss and not b.is_dead for b in self.bots.values())
        non_boss_alive = any((not b.is_boss) and (not b.is_dead) for b in self.bots.values())
        time_up = self.tick >= self.max_ticks
        self.done = time_up or not boss_alive or not non_boss_alive

        if self.done:
            self._finalize_ranks()

        states = {bid: self.state_for(bid) for bid in self.bots}
        rewards = {
            bid: (b.score - prev_score[bid]) + 0.001 * (b.hp - prev_hp[bid])
            for bid, b in self.bots.items()
        }
        info = {"tick": self.tick, "done": self.done}
        return states, rewards, self.done, info

    # ── 동역학 ──────────────────────────────────────────────────────────
    def _advance_cooldowns(self) -> None:
        for b in self.bots.values():
            if b.is_dead:
                continue
            b.attack_cd = max(0.0, b.attack_cd - TICK_DT)
            b.guard_cd = max(0.0, b.guard_cd - TICK_DT)
            b.dash_cd = max(0.0, b.dash_cd - TICK_DT)

    def _apply_actions(self, actions: dict[str, dict[str, Any]]) -> None:
        t = self.tick * TICK_DT
        for bid, b in self.bots.items():
            if b.is_dead:
                continue
            act = actions.get(bid) or {}
            move = _norm2(tuple(act.get("move_dir", [0.0, 0.0])[:2]))
            aim = _norm2(tuple(act.get("aim_dir", [1.0, 0.0])[:2]))
            if aim == (0.0, 0.0):
                aim = b.last_move_dir or (1.0, 0.0)

            # use_potion
            if act.get("use_potion") and b.has_potion:
                b.hp = min(b.max_hp, b.hp + POTION_HEAL)
                b.has_potion = False

            # dash
            if act.get("dash") and b.dash_cd <= 0.0:
                b.dash_cd = DASH_CD_SEC
                b.dash_until = t + DASH_DURATION_SEC

            # guard
            if act.get("guard") and b.guard_cd <= 0.0:
                b.guard_cd = GUARD_CD_SEC
                b.guard_until = t + GUARD_DURATION_SEC

            # 이동 (dash 중이면 가속)
            speed_mult = DASH_SPEED_MULT if t < b.dash_until else 1.0
            dx = move[0] * b.speed * speed_mult * TICK_DT
            dy = move[1] * b.speed * speed_mult * TICK_DT
            nx, ny = _clip_to_map(b.pos[0] + dx, b.pos[1] + dy)
            b.vel = ((nx - b.pos[0]) / TICK_DT, (ny - b.pos[1]) / TICK_DT)
            b.pos = (nx, ny)
            if move != (0.0, 0.0):
                b.last_move_dir = move

            # 공격
            if act.get("attack") and b.attack_cd <= 0.0:
                b.attack_cd = ATTACK_CD_SEC
                self._resolve_attack(b, aim)

            # 상자 픽업 (이번 틱에 인접한 상자 진행)
            if act.get("pickup"):
                self._start_chest_pickup(b)

    def _resolve_attack(self, attacker: BR2BotState, aim: tuple[float, float]) -> None:
        rng_atk = RANGED_RANGE if attacker.has_ranged else MELEE_RANGE
        # aim 콘 ±45° 안 가장 가까운 적
        best: Optional[BR2BotState] = None
        best_d = float("inf")
        for b in self.bots.values():
            if b.bot_id == attacker.bot_id or b.is_dead:
                continue
            dx = b.pos[0] - attacker.pos[0]
            dy = b.pos[1] - attacker.pos[1]
            d = math.hypot(dx, dy)
            if d > rng_atk or d < 1e-6:
                continue
            ux, uy = dx / d, dy / d
            dot = ux * aim[0] + uy * aim[1]
            if dot < 0.7071:   # cos(45°)
                continue
            if d < best_d:
                best_d = d
                best = b
        if best is None:
            return
        # 데미지 계산
        t = self.tick * TICK_DT
        guarded = t < best.guard_until
        raw = max(1, attacker.atk - best.def_)
        damage = raw * (GUARD_DAMAGE_REDUCTION if guarded else 1.0)
        best.hp = max(0, int(best.hp - damage))
        attacker.damage_dealt += damage
        best.damage_taken += damage

    def _start_chest_pickup(self, b: BR2BotState) -> None:
        # 가장 가까운 살아있는 상자
        best: Optional[_Chest] = None
        best_d = float("inf")
        for c in self.chests:
            if not c.alive:
                continue
            d = _dist(b.pos, c.pos)
            if d <= CHEST_PICKUP_RANGE and d < best_d:
                best_d = d
                best = c
        if best is None:
            b.chest_progress = 0.0
            b.chest_target_id = None
            return
        # 같은 상자 계속 열기
        if b.chest_target_id != best.id:
            b.chest_target_id = best.id
            b.chest_progress = 0.0
        b.chest_progress = min(1.0, b.chest_progress + TICK_DT / CHEST_OPEN_DURATION_SEC)

    def _update_chests(self) -> None:
        # progress 1.0 도달 → 상자 오픈, 아이템 드롭, score 적립
        for b in self.bots.values():
            if b.chest_progress >= 1.0 and b.chest_target_id is not None:
                target = next((c for c in self.chests if c.id == b.chest_target_id and c.alive), None)
                if target is not None:
                    target.alive = False
                    b.score += CHEST_SCORE
                    # 50% 확률 포션, 50% 확률 ranged 업그레이드
                    drop_kind = "potion" if self._rng.random() < 0.5 else "ranged"
                    self.items.append(_Item(id=self._next_id(), pos=target.pos, kind=drop_kind))
                b.chest_progress = 0.0
                b.chest_target_id = None

    def _collect_nodes(self) -> None:
        # 코인 자동 채집 (위에 올라가면)
        for b in self.bots.values():
            if b.is_dead:
                continue
            for n in self.nodes:
                if not n.alive:
                    continue
                if _dist(b.pos, n.pos) <= NODE_PICKUP_RANGE:
                    n.alive = False
                    heal = NODE_HEAL_RARE if n.rare else NODE_HEAL_NORMAL
                    score = NODE_SCORE_RARE if n.rare else NODE_SCORE_NORMAL
                    b.hp = min(b.max_hp, b.hp + heal)
                    b.score += score
                    b.nodes_collected += 1
            # 아이템 픽업
            for it in self.items:
                if not it.alive:
                    continue
                if _dist(b.pos, it.pos) <= NODE_PICKUP_RANGE:
                    it.alive = False
                    if it.kind == "potion":
                        b.has_potion = True
                    elif it.kind == "ranged":
                        b.has_ranged = True

    # ── zone ────────────────────────────────────────────────────────────
    def _advance_zone(self) -> None:
        t = self.tick * TICK_DT
        if t < ZONE_PHASE0_END:
            self.zone_active = False
            self.zone_damage = 0.0
            return
        self.zone_active = True
        if t < ZONE_PHASE1_END:
            frac = (t - ZONE_PHASE0_END) / max(1e-6, ZONE_PHASE1_END - ZONE_PHASE0_END)
            self.zone_radius = ZONE_INITIAL_RADIUS + frac * (ZONE_PHASE1_END_RADIUS - ZONE_INITIAL_RADIUS)
            self.zone_damage = ZONE_DAMAGE_PHASE1
            self.zone_phase = 1
        elif t < ZONE_PHASE2_END:
            frac = (t - ZONE_PHASE1_END) / max(1e-6, ZONE_PHASE2_END - ZONE_PHASE1_END)
            self.zone_radius = ZONE_PHASE1_END_RADIUS + frac * (ZONE_PHASE2_END_RADIUS - ZONE_PHASE1_END_RADIUS)
            self.zone_damage = ZONE_DAMAGE_PHASE2
            self.zone_phase = 2
        else:
            frac = min(1.0, (t - ZONE_PHASE2_END) / max(1e-6, ZONE_PHASE3_END - ZONE_PHASE2_END))
            self.zone_radius = ZONE_PHASE2_END_RADIUS + frac * (ZONE_PHASE3_END_RADIUS - ZONE_PHASE2_END_RADIUS)
            self.zone_damage = ZONE_DAMAGE_PHASE3
            self.zone_phase = 3

    def _apply_zone_damage(self) -> None:
        if not self.zone_active or self.zone_damage <= 0.0:
            return
        cx, cy = self.zone_center
        for b in self.bots.values():
            if b.is_dead:
                continue
            d = _dist(b.pos, (cx, cy))
            if d > self.zone_radius:
                # tick 당 damage. zone_damage 는 초당 값이므로 ×TICK_DT
                dmg = self.zone_damage * TICK_DT
                # 자기장은 guard·def 무시 (BR2 룰)
                b.hp = max(0, int(b.hp - dmg))
                b.damage_taken += dmg

    # ── 사망/순위 ──────────────────────────────────────────────────────
    def _update_alive(self) -> None:
        for b in self.bots.values():
            if not b.is_dead and b.hp <= 0:
                b.is_dead = True
                # 사망 시점 - 순위 = 살아남은 수 + 죽은 시간 역순 (간단화)
                # _finalize_ranks 에서 일괄 처리

    def _finalize_ranks(self) -> None:
        """매치 종료 시 순위 결정.

        규칙(옛 BR2 보스전 운영 기준 단순화):
            1. 생존자 우선, 그 안에서 score 내림차순.
            2. 사망자는 score 내림차순 (사망 시점 무관 — 단순화).
        """
        survivors = [b for b in self.bots.values() if not b.is_dead]
        dead = [b for b in self.bots.values() if b.is_dead]
        survivors.sort(key=lambda x: -x.score)
        dead.sort(key=lambda x: -x.score)
        rank = 1
        for b in survivors + dead:
            b.rank = rank
            rank += 1

    # ── 결과 ────────────────────────────────────────────────────────────
    def episode_result(self) -> BR2EpisodeResult:
        return BR2EpisodeResult(
            ranks={bid: b.rank for bid, b in self.bots.items()},
            n_bots=len(self.bots),
            final_score={bid: b.score for bid, b in self.bots.items()},
            final_hp={bid: b.hp for bid, b in self.bots.items()},
            damage_dealt={bid: b.damage_dealt for bid, b in self.bots.items()},
            damage_taken={bid: b.damage_taken for bid, b in self.bots.items()},
            nodes_collected={bid: b.nodes_collected for bid, b in self.bots.items()},
            duration_ticks=self.tick,
        )


__all__ = ["BR2MiniEnv", "BR2BotState", "BR2EpisodeResult", "TICK_DT", "BOSS_DURATION_SEC"]

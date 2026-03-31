"""
AI Arena — 게임 설정 상수
모든 밸런스 수치를 이 파일 하나에서 관리한다.
수치 변경 시 이 파일만 수정하면 엔진 전체에 반영된다.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MapConfig:
    width: int = 100
    height: int = 100
    initial_mineral_count: int = 300
    center_zone_size: int = 30          # 중앙 고밀도 구역 한 변 길이
    center_density_multiplier: float = 2.0
    
    # 희귀 광물 군락 설정
    num_rare_mineral_clusters: int = 5    # 생성할 군락 수
    rare_cluster_radius: int = 6          # 군락의 반경
    rare_minerals_per_cluster: int = 10   # 군락당 희귀 광물 수

    mineral_regen_delay: int = 50       # 채굴 후 재생까지 필요한 틱
    mineral_regen_chance: float = 0.15  # 재생 확률


@dataclass(frozen=True)
class BotConfig:
    initial_energy: int = 100
    max_bots: int = 100
    vision_radius: int = 2              # 시야 반경 (5×5 = 중심 ± 2)
    low_energy_threshold: int = 20      # 낮은 에너지 보정 기준 (v1.1)
    low_energy_mine_bonus: int = 5      # 낮은 에너지 시 추가 채굴 보너스


@dataclass(frozen=True)
class ActionCost:
    stay: int = 1
    move: int = 2
    mine: int = 3
    attack: int = 5
    shield: int = 3


@dataclass(frozen=True)
class CombatConfig:
    attack_damage: int = 25
    shield_reduction: float = 0.5       # 실드 피해 감소율


@dataclass(frozen=True)
class MineConfig:
    normal_points: int = 15
    rare_points: int = 40
    contested_split: float = 0.5        # 경합 시 점수 분배 비율


@dataclass(frozen=True)
class ZoneConfig:
    # Phase 1: 0~299틱 — 자기장 없음
    phase1_end: int = 299
    # Phase 2: 300~449틱 — 20틱마다 1칸 수축, -3/틱
    phase2_end: int = 449
    phase2_shrink_interval: int = 20
    phase2_damage: int = 3
    # Phase 3: 450~500틱 — 10틱마다 1칸 수축 (가속), -3/틱
    phase3_shrink_interval: int = 10
    phase3_damage: int = 3


@dataclass(frozen=True)
class GameConfig:
    max_ticks: int = 500
    leaderboard_size: int = 3           # 공개 리더보드 상위 N명

    # 최종 점수 가중치
    score_per_mineral: float = 1.0      # 채굴 점수는 게임 중 실시간 반영
    score_per_survival_tick: float = 0.1
    score_per_kill: float = 10.0

    map: MapConfig = field(default_factory=MapConfig)
    bot: BotConfig = field(default_factory=BotConfig)
    action_cost: ActionCost = field(default_factory=ActionCost)
    combat: CombatConfig = field(default_factory=CombatConfig)
    mine: MineConfig = field(default_factory=MineConfig)
    zone: ZoneConfig = field(default_factory=ZoneConfig)


# 기본 설정 싱글턴
DEFAULT_CONFIG = GameConfig()

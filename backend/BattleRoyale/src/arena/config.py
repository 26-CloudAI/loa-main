"""
AI Arena — 게임 설정 상수
모든 밸런스 수치를 이 파일 하나에서 관리한다.
수치 변경 시 이 파일만 수정하면 엔진 전체에 반영된다.
"""

import dataclasses
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MapConfig:
    width: int = 100
    height: int = 100
    initial_mineral_count: int = 300
    center_zone_size: int = 30          # 중앙 고밀도 구역 한 변 길이
    center_density_multiplier: float = 2.0

    # 희귀 광물 군락 설정
    rare_zone_size: int = 6             # 희귀 광물 군락 반경
    num_rare_mineral_clusters: int = 5  # 생성할 군락 수
    rare_minerals_per_cluster: int = 10 # 군락당 희귀 광물 수

    mineral_regen_delay: int = 50       # 채굴 후 재생까지 필요한 틱
    mineral_regen_chance: float = 0.15  # 재생 확률


@dataclass(frozen=True)
class BotConfig:
    initial_energy: int = 250           # 상향: 스폰 운에 의존하지 않도록 넉넉한 초기 에너지 부여
    max_energy: int = 1000              # 후반을 위해 비축할 수 있는 최대 에너지
    max_bots: int = 100
    spawn_margin: int = 5               # 스폰 가능 영역의 맵 가장자리 여백
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
    shield_reduction: float = 1.0       # 실드 피해 감소율 (100% 완전 방어)


@dataclass(frozen=True)
class MineConfig:
    normal_points: int = 5              # 하향: 전투(킬 10점) 대비 일반 채굴 밸런스 조정
    rare_points: int = 20               # 하향: 희귀 채굴 점수 조정
    energy_gain_normal: int = 10        # 하향: 일반 광물 채굴 시 에너지 회복량
    energy_gain_rare: int = 25          # 하향: 희귀 광물 채굴 시 에너지 회복량
    contested_split: float = 0.5        # 경합 시 점수 분배 비율


@dataclass(frozen=True)
class ZoneConfig:
    # Phase 1: 0~75틱 — 자기장 없음
    phase1_end: int = 75
    # Phase 2: 76~150틱 — 4틱마다 1칸 수축
    phase2_end: int = 150
    phase2_shrink_interval: int = 4
    phase2_damage: int = 3
    # Phase 3: 151~200틱 — 2틱마다 1칸 수축 (가속)
    phase3_shrink_interval: int = 2
    phase3_damage: int = 3


@dataclass(frozen=True)
class GameConfig:
    max_ticks: int = 200
    leaderboard_size: int = 3           # 공개 리더보드 상위 N명

    # 최종 점수 가중치
    score_per_mineral: float = 1.0      # 채굴 점수는 게임 중 실시간 반영
    score_per_survival_tick: float = 0.1
    score_per_kill: float = 30.0        # 상향: 킬의 난이도와 리스크에 걸맞은 높은 보상
    score_per_guard: float = 10.0       # 가드 보너스: 상대 공격 방어 성공 시

    # 최종 생존 순위 보너스 (survival_ticks 기준 상위 3인)
    survival_rank_bonus: tuple = (100, 50, 25)

    map: MapConfig = field(default_factory=MapConfig)
    bot: BotConfig = field(default_factory=BotConfig)
    action_cost: ActionCost = field(default_factory=ActionCost)
    combat: CombatConfig = field(default_factory=CombatConfig)
    mine: MineConfig = field(default_factory=MineConfig)
    zone: ZoneConfig = field(default_factory=ZoneConfig)


# 기본 설정 싱글턴
DEFAULT_CONFIG = GameConfig()

# 보스전 유저봇 최대 수 — 여기만 바꾸면 app.py·BOSS_BOT.md 모두 반영
BOSS_MAX_USER_BOTS: int = 3


def boss_battle_config() -> GameConfig:
    """
    보스전 전용 게임 설정.
    배틀로얄 기본값(DEFAULT_CONFIG)을 보스전에 맞게 지역 오버라이드한다.
    전역 설정을 변경하지 않으므로 일반 배틀로얄에 영향 없음.

    주요 변경:
      max_ticks         200 → 400  (전략 깊이 확보, 채굴 비중 상향)
      광물              300 → 400  (봇 수 증가 대비 자원 확대)
      희귀 군락          5 → 6     (추가 전략 거점)
      zone.phase1_end   75 → 150  (자유 탐색 시간 2배)
      zone.phase2_end  150 → 320  (점진 수축 구간 170틱, 8틱마다)
      zone.phase3_interval 2 → 5  (엔드게임 수축 완화)
      → 총 수축 37회, 최종 안전구역 ≈ 27×27
    """
    return dataclasses.replace(
        DEFAULT_CONFIG,
        max_ticks=400,
        map=dataclasses.replace(
            DEFAULT_CONFIG.map,
            initial_mineral_count=400,
            num_rare_mineral_clusters=6,
        ),
        zone=dataclasses.replace(
            DEFAULT_CONFIG.zone,
            phase1_end=150,
            phase2_end=320,
            phase2_shrink_interval=8,
            phase3_shrink_interval=5,
        ),
    )

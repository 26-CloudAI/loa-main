"""RuleBossEasyBR2 — 옛 RuleBossEasyBot(하) BR2 포팅.

옛 임계값 (energy max 999):
    _EASY_ATTACK    = 60     # 인접 적 공격 최소 에너지
    _EASY_HUNT      = 120    # 적 추적 시작 에너지
    _EASY_EMERGENCY = 100    # 긴급 채굴 에너지
    _EASY_TIMEOUT   = 5      # 시야 이탈 후 추적 포기 틱
    _EASY_WANDER_INTERVAL = 30  # 탐색 갱신 주기

BR2 매핑 (hp max 200, tick scale ×9):
    ATTACK_HP    = 60       (절대값 유지 — 옛 "공격 가능한 여유")
    HUNT_HP      = 120      (")
    EMERGENCY_HP = 100      (")
    ENEMY_LOST_TICKS = 45   (5 × 9)
    WANDER_INTERVAL_TICKS = 270  (30 × 9)
    SPAWN_DIST_RANGE = (180, 380)  # 옛 randint(3,7) × 60px (BR2 cell ≈ 60px)
    AGGRO_HUNT = False  # 옛 트리: 시야 이탈 후 추적 포기

행동 패턴 (옛 그대로):
- 시야 밖 적은 추적 안 함 (last_enemy_pos 잊으면 끝)
- 자원 우선, 적극적 공격은 안 함 (자기 hp 여유가 있을 때만)
- 라스트힛(적 hp ≤ 50) 가능하면 무조건 공격
"""
from __future__ import annotations

from .base import _RuleBossBase


class RuleBossEasyBR2(_RuleBossBase):
    LOW_HP_POTION = 100
    GUARD_HP = 50
    FLEE_HP = 30
    ATTACK_HP = 60
    HUNT_HP = 120
    EMERGENCY_HP = 100
    ENEMY_LOST_TICKS = 45
    MINERAL_EXPIRE_TICKS = 720
    WANDER_INTERVAL_TICKS = 270
    SPAWN_DIST_RANGE = (180.0, 380.0)
    AGGRO_HUNT = False
    DISPLAY_NAME = "보스(하)"


__all__ = ["RuleBossEasyBR2"]

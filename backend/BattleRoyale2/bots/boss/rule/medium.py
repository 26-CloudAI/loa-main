"""RuleBossMediumBR2 — 옛 RuleBossMediumBot(중) BR2 포팅.

옛 임계값 (energy max 999):
    _MED_ATTACK    = 40     # 인접 적 공격 최소 에너지
    _MED_HUNT      = 70     # 적 추적 시작 에너지
    _MED_EMERGENCY = 40     # 긴급 채굴 에너지
    _MED_TIMEOUT   = 10     # 시야 이탈 후 추적 포기 틱

BR2 매핑 (hp max 200, tick scale ×9):
    ATTACK_HP    = 40
    HUNT_HP      = 70
    EMERGENCY_HP = 40
    ENEMY_LOST_TICKS = 90   (10 × 9)
    SPAWN_DIST_RANGE = (120, 300)  # 옛 randint(2,5) × 60px
    AGGRO_HUNT = True  # 옛 트리: 시야 이탈 적도 last_enemy_pos 로 추격

행동 패턴 (옛 그대로):
- 공격 최우선 — 적이 시야에 들어오면 적극 추격·교전
- 라스트힛 우선, 저HP 적 우선 타겟 (옛 _pick_chase_target 점수식)
- 인접 적이면 emergency mine 보다 attack/flee 먼저
- 자기장 예측 이동
"""
from __future__ import annotations

from .base import _RuleBossBase


class RuleBossMediumBR2(_RuleBossBase):
    LOW_HP_POTION = 130
    GUARD_HP = 70
    FLEE_HP = 35
    ATTACK_HP = 40
    HUNT_HP = 70
    EMERGENCY_HP = 40
    ENEMY_LOST_TICKS = 90
    MINERAL_EXPIRE_TICKS = 720
    WANDER_INTERVAL_TICKS = 270
    SPAWN_DIST_RANGE = (120.0, 300.0)
    AGGRO_HUNT = True
    DISPLAY_NAME = "보스(중)"


__all__ = ["RuleBossMediumBR2"]

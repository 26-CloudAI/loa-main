"""BR2 학습용 순수 Python 미니 시뮬레이션.

Godot 헤드리스 러너 없이 BR2 보스 RL 학습을 수행하기 위한 단순화 환경.
Godot 실제 매치와 sim2real gap 이 있으므로, 학습 후 운영 배포 전 e2e 검증 필수.

주요 단순화:
    - 충돌: 원형(반지름 25px)
    - 공격: 근접 60px / 원거리 400px, 데미지 = attacker.atk - target.def (guard 시 50% 감소)
    - 시야: 전체 정보 노출 (encoder 가 top-K 잘라냄)
    - 투사체: 즉발 (속도 무시, 사거리만 검사)
    - zone: 원형, 3 phase 시간 기반 shrink
    - tick: 100ms (10Hz), 보스 모드 매치 360s = 3600 ticks
"""
from .mini_env import (
    BR2MiniEnv,
    BR2BotState,
    BR2EpisodeResult,
    BOSS_DURATION_SEC,
    BASE_DURATION_SEC,
    TICK_DT,
)

__all__ = [
    "BR2MiniEnv",
    "BR2BotState",
    "BR2EpisodeResult",
    "BOSS_DURATION_SEC",
    "BASE_DURATION_SEC",
    "TICK_DT",
]

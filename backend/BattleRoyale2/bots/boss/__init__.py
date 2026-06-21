"""BattleRoyale2 — 보스전용 봇 패키지.

하위 모듈:
    rule/ : 룰베이스 보스 (하/중) — 옛 rule_boss_bot.py 의 우선순위 트리를 BR2
            연속 2D 인터페이스(Godot 좌표/단위벡터 move_dir·aim_dir)로 1:1 포팅.
    rl/   : 강화학습 보스 (상, Phase 4 예정) — 체크포인트 없으면 Medium 룰 폴백.

ws_server 가 사용하는 운영 진입점(한국어 난이도 키):
    BossEasyBot, BossMediumBot, BossHardBot, BOSS_BOT_BY_DIFFICULTY

내부 구현 클래스(WIP 6/2 작업 보존):
    RuleBossEasyBR2, RuleBossMediumBR2 — 룰 봇 본체
"""
from __future__ import annotations

import logging

from .rule import RuleBossEasyBR2, RuleBossMediumBR2

logger = logging.getLogger(__name__)


# ── 운영 인터페이스(한국어 난이도 키 "하/중/상") ────────────────────────
BossEasyBot = RuleBossEasyBR2     # 난이도 '하'
BossMediumBot = RuleBossMediumBR2  # 난이도 '중'


def _resolve_hard_boss():
    """난이도 '상' 보스 클래스 결정 — RL 체크포인트 있으면 RLBossBR2, 없으면 Medium 폴백.

    3단계(강화학습 재개) 완료 후 체크포인트가 배치되면 자동 활성.
    그 전엔 Medium 룰로 폴백해 '상' 매치도 깨지지 않고 진행되도록 한다.
    """
    try:
        from .rl import RLBossBR2, DEFAULT_CHECKPOINT_DIR
    except Exception as e:  # noqa: BLE001 — numpy 미설치 등
        logger.info(
            "[BR2 boss] RL 모듈 import 실패 (%s) — '상' 난이도는 Medium 룰로 폴백", e
        )
        return RuleBossMediumBR2
    if not DEFAULT_CHECKPOINT_DIR.exists() or not list(DEFAULT_CHECKPOINT_DIR.glob("gen_*.npz")):
        logger.info(
            "[BR2 boss] RL 체크포인트 없음 (%s) — '상' 난이도는 Medium 룰로 폴백",
            DEFAULT_CHECKPOINT_DIR,
        )
        return RuleBossMediumBR2
    return RLBossBR2


BossHardBot = _resolve_hard_boss()


BOSS_BOT_BY_DIFFICULTY: dict[str, type] = {
    "하": BossEasyBot,
    "중": BossMediumBot,
    "상": BossHardBot,
}


__all__ = [
    "RuleBossEasyBR2",
    "RuleBossMediumBR2",
    "BossEasyBot",
    "BossMediumBot",
    "BossHardBot",
    "BOSS_BOT_BY_DIFFICULTY",
]

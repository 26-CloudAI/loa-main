"""PastBossOpponentBR2 — league 체크포인트의 freeze wrapper.

옛 backend/battle_royale/bots/boss/past_boss_opponent.py 의 BR2 버전.
훈련 중 현재 학습 보스의 메타 풀(과거 자기 자신들) 로 사용.

차이점:
    - 옛: PyTorch 모델 + _learn no-op patch
    - BR2: 이미 inference-only (QNetwork 가 backward 없음) — patch 필요 없음.
      epsilon_override=0.0 (greedy) 만 강제하면 충분.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot

from .inference import RLBossBR2

logger = logging.getLogger(__name__)


class PastBossOpponentBR2(BattleRoyale2DBot):
    """과거 league 체크포인트를 freeze opponent 로 사용. RLBossBR2 위의 얇은 래퍼."""

    def __init__(
        self,
        bot_id: str,
        checkpoint_path: str | Path,
        seed: Optional[int] = None,
    ):
        self._bot_id = bot_id
        self._inner = RLBossBR2(
            bot_id=bot_id,
            seed=seed,
            checkpoint_path=checkpoint_path,
            epsilon=0.0,   # 학습 X — 결정론적 greedy
        )
        self._checkpoint_path = str(checkpoint_path)

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict[str, Any]) -> Optional[tuple[float, float]]:
        return self._inner.choose_spawn(map_info)

    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return self._inner.get_action(state)

    def on_episode_done(self, rank: int, n_bots: int, score: float) -> None:
        # past opponent 는 자기 통계 갱신 안 함 (옛 동일)
        logger.debug("[BR2 past_opponent=%s] episode_done rank=%d ckpt=%s",
                     self.bot_id, rank, self._checkpoint_path)


__all__ = ["PastBossOpponentBR2"]

"""보스전 결과 기록 핸들러.

게임이 보스 모드일 때 보스봇과 유저 봇의 최종 순위를 비교해
`games.boss_won` 컬럼을 갱신한다. 동점이면 draw로 보고 NULL 유지.
"""

from __future__ import annotations

import logging
from typing import Iterable

logger = logging.getLogger(__name__)


def record_boss_result(
    game_id: str,
    game_record,
    participants: Iterable,
    game_repo,
) -> None:
    """보스전 결과를 DB에 기록한다.

    Args:
        game_id: 게임 ID
        game_record: GameRepository.get_game()로 얻은 레코드.
            None이면 처리하지 않음.
        participants: 해당 게임의 participant 레코드 목록.
        game_repo: GameRepository 인스턴스 (update_game_boss_result 사용).
    """
    if not game_record or game_record.mode != "boss":
        return

    participants = list(participants)
    boss_participants = [p for p in participants if p.is_boss_bot and p.final_rank]
    user_ranked = [
        p
        for p in participants
        if not p.is_ai_filler and not p.is_boss_bot and p.final_rank
    ]
    if not (boss_participants and user_ranked):
        return

    boss_rank = boss_participants[0].final_rank
    best_user_rank = min(p.final_rank for p in user_ranked)
    if boss_rank == best_user_rank:
        # 동점(동일 rank)이면 draw — NULL 유지
        return

    try:
        game_repo.update_game_boss_result(
            game_id, boss_won=(boss_rank < best_user_rank)
        )
    except Exception:
        logger.exception("보스전 결과 기록 실패 game=%s", game_id)

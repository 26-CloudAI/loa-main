"""
AI Arena — 게임 조회 헬퍼

StateStore/결과 저장소에 있는 dict를
REST API 응답용 GameInfo로 복원한다.
"""

from __future__ import annotations

from typing import Optional

from ..db.game_repo import GameRecord, ParticipantRecord
from .schemas import GameInfo, GameStatus


def game_info_from_state(
    game_id: str,
    state_data: dict,
    name: Optional[str] = None,
    mode: str = "battle-royale",
) -> GameInfo:
    """StateStore에 저장된 상태로부터 GameInfo를 복원한다."""
    bots = state_data.get("bots", [])
    bot_ids = state_data.get("bot_ids") or [b["id"] for b in bots if "id" in b]
    alive_bots = state_data.get("alive_bots")
    if alive_bots is None:
        alive_bots = state_data.get("alive_count")
    if alive_bots is None:
        alive_bots = sum(1 for b in bots if b.get("alive"))

    status_raw = state_data.get("status", GameStatus.RUNNING.value)
    try:
        status = GameStatus(status_raw)
    except ValueError:
        status = GameStatus.RUNNING

    return GameInfo(
        game_id=game_id,
        status=status,
        current_tick=state_data.get("current_tick", state_data.get("tick", 0)),
        total_bots=state_data.get("total_bots", len(bot_ids)),
        alive_bots=alive_bots,
        bot_ids=bot_ids,
        name=name,
        mode=mode,
    )


def game_info_from_result(
    game_id: str,
    result: dict,
    state_data: Optional[dict] = None,
) -> GameInfo:
    """저장된 게임 결과로부터 종료 상태 GameInfo를 복원한다."""
    rankings = result.get("rankings", [])
    bot_ids = [entry["id"] for entry in rankings if "id" in entry]
    if not bot_ids and state_data:
        bot_ids = state_data.get("bot_ids") or [
            b["id"] for b in state_data.get("bots", []) if "id" in b
        ]

    return GameInfo(
        game_id=game_id,
        status=GameStatus.FINISHED,
        current_tick=result.get("final_tick", 0),
        total_bots=len(bot_ids),
        alive_bots=0,
        bot_ids=bot_ids,
        name=result.get("name"),
        mode=result.get("mode", "battle-royale"),
    )


def game_info_from_record(
    record: GameRecord,
    participants: list[ParticipantRecord],
) -> GameInfo:
    """DB games/game_participants 레코드로부터 GameInfo를 복원한다."""
    bot_ids = [participant.bot_name for participant in participants]
    try:
        status = GameStatus(record.status)
    except ValueError:
        status = GameStatus.ERROR

    alive_bots = 0 if status in (GameStatus.FINISHED, GameStatus.ERROR) else len(bot_ids)
    current_tick = record.final_tick or 0

    return GameInfo(
        game_id=record.id,
        status=status,
        current_tick=current_tick,
        total_bots=record.total_bots,
        alive_bots=alive_bots,
        bot_ids=bot_ids,
        name=record.name,
        mode=record.mode,
    )


def game_result_from_record(
    record: GameRecord,
    participants: list[ParticipantRecord],
) -> dict:
    """DB 기록으로부터 결과 응답 payload를 복원한다."""
    rankings = []
    for participant in participants:
        rankings.append({
            "rank": participant.final_rank,
            "id": participant.bot_name,
            "final_score": participant.final_score,
            "kills": participant.kills,
            "minerals_mined": participant.minerals_mined,
            "survival_ticks": participant.survival_ticks,
        })

    return {
        "game_id": record.id,
        "reason": record.end_reason or "unknown",
        "final_tick": record.final_tick or 0,
        "rankings": rankings,
    }

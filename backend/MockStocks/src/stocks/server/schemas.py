from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field


class GameStatus(str, Enum):
    WAITING  = "waiting"
    LOADING  = "loading"
    RUNNING  = "running"
    FINISHED = "finished"
    ERROR    = "error"


@dataclass
class GameInfo:
    game_id: str
    status: GameStatus
    current_tick: int
    total_bots: int
    bot_ids: list[str]

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "status": self.status.value,
            "current_tick": self.current_tick,
            "total_bots": self.total_bots,
            "bot_ids": self.bot_ids,
        }


def make_tick_message(game_id: str, data: dict) -> dict:
    return {"type": "tick", "game_id": game_id, "data": data}


def make_game_start_message(game_id: str, bot_ids: list[str]) -> dict:
    return {"type": "game_start", "game_id": game_id, "bot_ids": bot_ids}


def make_game_end_message(game_id: str, rankings: list[dict]) -> dict:
    return {"type": "game_end", "game_id": game_id, "rankings": rankings}

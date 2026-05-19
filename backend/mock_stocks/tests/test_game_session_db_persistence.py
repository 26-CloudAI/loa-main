from __future__ import annotations

import asyncio
from dataclasses import dataclass

from stocks.bot_interface import BotInterface
from stocks.config import DEFAULT_CONFIG
from stocks.db.game_repo import StockGameRepository
from stocks.db.schema import init_db
from stocks.server import settings
from stocks.server.game_session import GameSession
from stocks.server.schemas import GameStatus
from stocks.types import GameResult


class DummyBot(BotInterface):
    def get_action(self, state: dict) -> dict:
        return {"action": "HOLD"}


class RecordingSpectatorManager:
    def __init__(self):
        self.messages: list[dict] = []

    async def broadcast(self, game_id: str, message: dict) -> None:
        self.messages.append(message)


@dataclass
class FinishedEngine:
    game_result: GameResult
    tick: int = 200
    game_over: bool = True


def _make_repo(tmp_path, monkeypatch) -> StockGameRepository:
    monkeypatch.setattr(settings, "DB_TYPE", "sqlite")
    return StockGameRepository(init_db(tmp_path / "stocks.db"))


def _seed_running_game(repo: StockGameRepository, game_id: str, bot_id: str = "bot-a") -> None:
    repo.create_game(
        game_id=game_id,
        total_bots=1,
        seed=123,
        total_ticks=DEFAULT_CONFIG.game.total_ticks,
        tick_interval=DEFAULT_CONFIG.game.tick_interval,
        name=f"모의주식 1 · {game_id}",
    )
    repo.add_participant(game_id, bot_id=bot_id, bot_name=bot_id)
    repo.update_game_started(game_id)


def test_run_loop_persists_finished_game_and_participant_results(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path, monkeypatch)
    _seed_running_game(repo, "game-1")

    spectator_manager = RecordingSpectatorManager()
    session = GameSession("game-1", spectator_manager, repo=repo)
    session._bots = [DummyBot("bot-a")]
    session._engine = FinishedEngine(
        game_result=GameResult(
            final_tick=200,
            rankings=[
                {
                    "rank": 1,
                    "id": "bot-a",
                    "total_value": 110_000_000.0,
                    "credit_score": 1005,
                }
            ],
        )
    )

    asyncio.run(session._run_loop())

    game = repo.get_game("game-1")
    participant = repo.get_participants("game-1")[0]

    assert session.status == GameStatus.FINISHED
    assert game.status == "finished"
    assert game.final_tick == 200
    assert game.end_reason == "finished"
    assert participant.final_rank == 1
    assert participant.final_total_value == 110_000_000.0
    assert participant.profit_rate == 10.0
    assert participant.final_credit_score == 1005
    assert spectator_manager.messages[-1]["type"] == "game_end"


def test_stop_marks_running_game_as_cancelled(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path, monkeypatch)
    _seed_running_game(repo, "game-2")

    session = GameSession("game-2", RecordingSpectatorManager(), repo=repo)
    session.status = GameStatus.RUNNING
    session._engine = FinishedEngine(game_result=GameResult(final_tick=42, rankings=[]), tick=42)

    asyncio.run(session.stop())

    game = repo.get_game("game-2")
    assert session.status == GameStatus.FINISHED
    assert game.status == "finished"
    assert game.final_tick == 42
    assert game.end_reason == "cancelled"


def test_stop_does_not_overwrite_already_finished_game(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path, monkeypatch)
    _seed_running_game(repo, "game-3")
    repo.update_game_finished("game-3", final_tick=200, end_reason="finished")

    session = GameSession("game-3", RecordingSpectatorManager(), repo=repo)
    session.status = GameStatus.FINISHED
    session._engine = FinishedEngine(game_result=GameResult(final_tick=42, rankings=[]), tick=42)

    asyncio.run(session.stop())

    game = repo.get_game("game-3")
    assert game.final_tick == 200
    assert game.end_reason == "finished"


def test_game_session_info_includes_name():
    session = GameSession(
        "abc12345",
        RecordingSpectatorManager(),
        name="모의주식 1 · abc12345",
    )
    session._bots = [DummyBot("bot-a"), DummyBot("bot-b")]

    info = session.get_info().to_dict()

    assert info["name"] == "모의주식 1 · abc12345"

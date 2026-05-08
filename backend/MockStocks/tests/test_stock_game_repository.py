from __future__ import annotations

from stocks.db.game_repo import StockGameRepository
from stocks.db.schema import init_db
from stocks.server import settings


def test_repository_persists_game_and_participant_results(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_TYPE", "sqlite")
    conn = init_db(tmp_path / "stocks.db")
    repo = StockGameRepository(conn)

    repo.create_game(
        game_id="game-1",
        total_bots=2,
        seed=123,
        total_ticks=200,
        tick_interval=0.1,
    )
    participant_id = repo.add_participant(
        game_id="game-1",
        bot_id="bot-a",
        bot_name="Bot A",
        is_ai_filler=True,
    )
    repo.update_game_started("game-1")
    repo.update_game_finished("game-1", final_tick=200, end_reason="finished")
    repo.update_participant_result(
        game_id="game-1",
        bot_id="bot-a",
        final_rank=1,
        initial_cash=100_000_000.0,
        final_total_value=125_000_000.0,
        profit_rate=25.0,
        final_credit_score=1010,
    )

    game = repo.get_game("game-1")
    participants = repo.get_participants("game-1")

    assert game is not None
    assert game.status == "finished"
    assert game.total_bots == 2
    assert game.seed == 123
    assert game.final_tick == 200
    assert game.end_reason == "finished"

    assert len(participants) == 1
    participant = participants[0]
    assert participant.id == participant_id
    assert participant.bot_id == "bot-a"
    assert participant.bot_name == "Bot A"
    assert participant.is_ai_filler is True
    assert participant.final_rank == 1
    assert participant.initial_cash == 100_000_000.0
    assert participant.final_total_value == 125_000_000.0
    assert participant.profit_rate == 25.0
    assert participant.final_credit_score == 1010


def test_repository_marks_stale_games_as_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_TYPE", "sqlite")
    conn = init_db(tmp_path / "stocks.db")
    repo = StockGameRepository(conn)

    repo.create_game("waiting-game", total_bots=2)
    repo.create_game("finished-game", total_bots=2)
    repo.update_game_finished("finished-game", final_tick=200, end_reason="finished")

    updated_count = repo.cleanup_stale_games()

    assert updated_count == 1
    assert repo.get_game("waiting-game").status == "error"
    assert repo.get_game("waiting-game").end_reason == "server_restart"
    assert repo.get_game("finished-game").status == "finished"


def test_repository_lists_only_finished_games_for_history(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_TYPE", "sqlite")
    conn = init_db(tmp_path / "stocks.db")
    repo = StockGameRepository(conn)

    repo.create_game("waiting-game", total_bots=2)
    repo.create_game("running-game", total_bots=2)
    repo.update_game_started("running-game")
    repo.create_game("finished-game", total_bots=2)
    repo.update_game_finished("finished-game", final_tick=200, end_reason="finished")

    games = repo.get_finished_games()

    assert [game.id for game in games] == ["finished-game"]

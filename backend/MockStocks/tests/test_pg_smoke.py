"""
MockStocks — PostgreSQL 스모크 테스트

Cloud SQL / PostgreSQL 환경에서 DDL 생성 및 StockGameRepository CRUD가
실제로 동작하는지 검증한다.

실행 조건: DB_TYPE=postgresql AND DB_HOST 환경변수 설정
  DB_TYPE=postgresql DB_HOST=127.0.0.1 DB_PORT=5432 \\
  DB_NAME=ai_arena DB_USER=<user> DB_PASSWORD=<pw> \\
  python -m pytest tests/test_pg_smoke.py -v

조건 미충족 시 자동 스킵 — 일반 pytest -q 실행에 영향 없음.
"""

from __future__ import annotations

import os
import uuid

import pytest

_PG_AVAILABLE = (
    os.environ.get("DB_TYPE") == "postgresql"
    and bool(os.environ.get("DB_HOST"))
)

pytestmark = pytest.mark.skipif(
    not _PG_AVAILABLE,
    reason="DB_TYPE=postgresql 및 DB_HOST 환경변수 필요 — Cloud SQL Auth Proxy 실행 후 재시도",
)


@pytest.fixture(scope="module")
def pg_conn():
    """PostgreSQL 연결 픽스처. 모듈 범위로 한 번만 연결."""
    from stocks.db.schema import init_db

    conn = init_db()
    yield conn
    conn.close()


@pytest.fixture()
def pg_repo(pg_conn):
    from stocks.db.game_repo import StockGameRepository

    return StockGameRepository(pg_conn)


def _delete_game(pg_conn, game_id: str) -> None:
    """테스트 데이터 정리 — CASCADE로 participants도 함께 삭제."""
    with pg_conn.cursor() as cur:
        cur.execute("DELETE FROM stock_games WHERE id = %s", (game_id,))
    pg_conn.commit()


# ─────────────────────────────────────────────────────────────────────────────

def test_init_db_creates_tables(pg_conn):
    """init_db() 후 stock_games, stock_game_participants 테이블이 존재해야 한다."""
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename IN ('stock_games', 'stock_game_participants')
            """
        )
        tables = {row["tablename"] for row in cur.fetchall()}
    assert "stock_games" in tables, "stock_games 테이블 미생성"
    assert "stock_game_participants" in tables, "stock_game_participants 테이블 미생성"


def test_full_game_lifecycle(pg_repo, pg_conn):
    """create_game → add_participant → started → finished → get 전체 흐름."""
    game_id = f"pg_smoke_{uuid.uuid4().hex[:8]}"
    try:
        pg_repo.create_game(
            game_id=game_id,
            total_bots=2,
            seed=42,
            total_ticks=50,
            tick_interval=0.1,
        )
        game = pg_repo.get_game(game_id)
        assert game is not None
        assert game.status == "waiting"
        assert game.total_bots == 2
        assert game.seed == 42

        pid = pg_repo.add_participant(
            game_id=game_id,
            bot_id="pg_bot_0",
            bot_name="PG Bot 0",
            is_ai_filler=False,
        )
        assert isinstance(pid, int)

        pg_repo.update_game_started(game_id)
        assert pg_repo.get_game(game_id).status == "running"

        pg_repo.update_game_finished(game_id, final_tick=50, end_reason="normal")
        game = pg_repo.get_game(game_id)
        assert game.status == "finished"
        assert game.final_tick == 50
        assert game.end_reason == "normal"

        pg_repo.update_participant_result(
            game_id=game_id,
            bot_id="pg_bot_0",
            final_rank=1,
            initial_cash=100_000_000.0,
            final_total_value=115_000_000.0,
            profit_rate=15.0,
            final_credit_score=1005,
        )

        participants = pg_repo.get_participants(game_id)
        assert len(participants) == 1
        p = participants[0]
        assert p.id == pid
        assert p.bot_id == "pg_bot_0"
        assert p.is_ai_filler is False
        assert p.final_rank == 1
        assert abs(p.profit_rate - 15.0) < 0.001

    finally:
        _delete_game(pg_conn, game_id)


def test_get_finished_games_filters_correctly(pg_repo, pg_conn):
    """get_finished_games()가 finished 상태만 반환하는지 확인."""
    waiting_id = f"pg_smoke_w_{uuid.uuid4().hex[:6]}"
    finished_id = f"pg_smoke_f_{uuid.uuid4().hex[:6]}"
    try:
        pg_repo.create_game(waiting_id, total_bots=2)
        pg_repo.create_game(finished_id, total_bots=2)
        pg_repo.update_game_finished(finished_id, final_tick=10, end_reason="normal")

        games = pg_repo.get_finished_games(limit=50)
        ids = [g.id for g in games]
        assert finished_id in ids, "finished 게임이 목록에 없음"
        assert waiting_id not in ids, "waiting 게임이 목록에 포함됨"
    finally:
        _delete_game(pg_conn, waiting_id)
        _delete_game(pg_conn, finished_id)


def test_cleanup_stale_games(pg_repo, pg_conn):
    """cleanup_stale_games()가 waiting/running → error로 전환하는지 확인."""
    stale_id = f"pg_smoke_s_{uuid.uuid4().hex[:6]}"
    done_id = f"pg_smoke_d_{uuid.uuid4().hex[:6]}"
    try:
        pg_repo.create_game(stale_id, total_bots=2)
        pg_repo.create_game(done_id, total_bots=2)
        pg_repo.update_game_finished(done_id, final_tick=10, end_reason="normal")

        updated = pg_repo.cleanup_stale_games()
        assert updated >= 1

        assert pg_repo.get_game(stale_id).status == "error"
        assert pg_repo.get_game(done_id).status == "finished"
    finally:
        _delete_game(pg_conn, stale_id)
        _delete_game(pg_conn, done_id)

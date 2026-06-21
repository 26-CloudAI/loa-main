"""
MockStocks — 게임 리포지토리
모의주식 게임 세션 기록 CRUD 및 참가자 관리.

BattleRoyale GameRepository와 동일한 패턴:
  - _is_pg 플래그로 SQLite/PostgreSQL 분기
  - _execute() 헬퍼로 ? → %s 자동 치환
  - _now() 헬퍼로 datetime('now') / NOW() 분기
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass
class StockGameRecord:
    id: str
    status: str
    total_bots: int
    seed: Optional[int]
    total_ticks: Optional[int]
    tick_interval: Optional[float]
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    final_tick: Optional[int]
    end_reason: Optional[str]
    owner_uid: Optional[str] = None
    name: Optional[str] = None


@dataclass
class StockParticipantRecord:
    id: int
    game_id: str
    bot_id: str
    bot_name: str
    is_ai_filler: bool
    final_rank: Optional[int]
    initial_cash: Optional[float]
    final_total_value: Optional[float]
    profit_rate: Optional[float]
    final_credit_score: Optional[int]
    code: Optional[str] = None


class StockGameRepository:
    def __init__(self, conn):
        self.conn = conn
        self._is_pg = not isinstance(conn, sqlite3.Connection)

    def _execute(self, sql: str, params=()):
        """SQLite/psycopg2 공통 실행 헬퍼."""
        if self._is_pg:
            cur = self.conn.cursor()
            cur.execute(sql.replace("?", "%s"), params)
            return cur
        return self.conn.execute(sql, params)

    def _now(self) -> str:
        return "NOW()" if self._is_pg else "datetime('now')"

    # ── 게임 세션 ─────────────────────────────

    def create_game(
        self,
        game_id: str,
        total_bots: int,
        seed: Optional[int] = None,
        total_ticks: Optional[int] = None,
        tick_interval: Optional[float] = None,
        owner_uid: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO stock_games (id, owner_uid, name, total_bots, seed, total_ticks, tick_interval)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (game_id, owner_uid, name, total_bots, seed, total_ticks, tick_interval),
        )
        self.conn.commit()

    def get_game(self, game_id: str) -> Optional[StockGameRecord]:
        cursor = self._execute("SELECT * FROM stock_games WHERE id = ?", (game_id,))
        row = cursor.fetchone()
        return self._row_to_game(row) if row else None

    def update_game_started(self, game_id: str) -> None:
        self._execute(
            f"UPDATE stock_games SET status = 'running', started_at = {self._now()} WHERE id = ?",
            (game_id,),
        )
        self.conn.commit()

    def update_game_finished(
        self,
        game_id: str,
        final_tick: int,
        end_reason: str,
    ) -> None:
        self._execute(
            f"""
            UPDATE stock_games
            SET status = 'finished', finished_at = {self._now()},
                final_tick = ?, end_reason = ?
            WHERE id = ?
            """,
            (final_tick, end_reason, game_id),
        )
        self.conn.commit()

    def get_recent_games(self, limit: int = 20) -> list[StockGameRecord]:
        cursor = self._execute(
            "SELECT * FROM stock_games ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_game(row) for row in cursor.fetchall()]

    def count_games_by_owner(self, owner_uid: str) -> int:
        """해당 유저의 MockStocks 게임 수 반환 (기본 이름 번호 생성용)."""
        cursor = self._execute(
            "SELECT COUNT(*) AS cnt FROM stock_games WHERE owner_uid = ?",
            (owner_uid,),
        )
        row = cursor.fetchone()
        return row["cnt"] if row else 0

    def get_finished_games(self, limit: int = 20, owner_uid: Optional[str] = None) -> list[StockGameRecord]:
        if owner_uid is not None:
            cursor = self._execute(
                """
                SELECT * FROM stock_games
                WHERE status = 'finished' AND owner_uid = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (owner_uid, limit),
            )
        else:
            cursor = self._execute(
                """
                SELECT * FROM stock_games
                WHERE status = 'finished'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [self._row_to_game(row) for row in cursor.fetchall()]

    def get_user_stats(self, owner_uid: str) -> dict:
        """유저의 모의주식 게임 수 및 1위 횟수를 반환한다."""
        cursor = self._execute(
            "SELECT COUNT(*) as cnt FROM stock_games WHERE owner_uid = ? AND status = 'finished'",
            (owner_uid,),
        )
        row = cursor.fetchone()
        games_played = row["cnt"] if row else 0

        cursor = self._execute(
            """
            SELECT COUNT(*) as cnt
            FROM stock_games sg
            JOIN stock_game_participants sgp ON sg.id = sgp.game_id
            WHERE sg.owner_uid = ?
              AND sg.status = 'finished'
              AND NOT sgp.is_ai_filler
              AND sgp.final_rank = 1
            """,
            (owner_uid,),
        )
        row = cursor.fetchone()
        wins = row["cnt"] if row else 0

        return {"games_played": games_played, "wins": wins, "losses": games_played - wins}

    def cleanup_stale_games(self) -> int:
        """서버 재시작 시 미완료 게임을 error 상태로 변경. 변경된 수를 반환."""
        cursor = self._execute(
            """
            UPDATE stock_games SET status = 'error', end_reason = 'server_restart'
            WHERE status IN ('waiting', 'running')
            """,
        )
        self.conn.commit()
        return cursor.rowcount

    # ── 참가자 ────────────────────────────────

    def add_participant(
        self,
        game_id: str,
        bot_id: str,
        bot_name: str,
        is_ai_filler: bool = False,
        code: Optional[str] = None,
    ) -> int:
        """참가자 추가. 생성된 participant ID를 반환."""
        if self._is_pg:
            cursor = self._execute(
                """
                INSERT INTO stock_game_participants (game_id, bot_id, bot_name, is_ai_filler, code)
                VALUES (?, ?, ?, ?, ?)
                RETURNING id
                """,
                (game_id, bot_id, bot_name, is_ai_filler, code),
            )
            participant_id = cursor.fetchone()["id"]
        else:
            cursor = self._execute(
                """
                INSERT INTO stock_game_participants (game_id, bot_id, bot_name, is_ai_filler, code)
                VALUES (?, ?, ?, ?, ?)
                """,
                (game_id, bot_id, bot_name, int(is_ai_filler), code),
            )
            participant_id = cursor.lastrowid
        self.conn.commit()
        return participant_id

    def update_participant_result(
        self,
        game_id: str,
        bot_id: str,
        final_rank: int,
        initial_cash: float,
        final_total_value: float,
        profit_rate: float,
        final_credit_score: int,
    ) -> None:
        self._execute(
            """
            UPDATE stock_game_participants
            SET final_rank = ?, initial_cash = ?, final_total_value = ?,
                profit_rate = ?, final_credit_score = ?
            WHERE game_id = ? AND bot_id = ?
            """,
            (final_rank, initial_cash, final_total_value, profit_rate,
             final_credit_score, game_id, bot_id),
        )
        self.conn.commit()

    def get_participants(self, game_id: str) -> list[StockParticipantRecord]:
        cursor = self._execute(
            """
            SELECT * FROM stock_game_participants
            WHERE game_id = ?
            ORDER BY COALESCE(final_rank, 9999) ASC
            """,
            (game_id,),
        )
        return [self._row_to_participant(row) for row in cursor.fetchall()]

    # ── 변환 헬퍼 ────────────────────────────

    def _row_to_game(self, row) -> StockGameRecord:
        return StockGameRecord(
            id=row["id"],
            status=row["status"],
            total_bots=row["total_bots"],
            seed=row["seed"],
            total_ticks=row["total_ticks"],
            tick_interval=row["tick_interval"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            final_tick=row["final_tick"],
            end_reason=row["end_reason"],
            owner_uid=row["owner_uid"] if "owner_uid" in row.keys() else None,
            name=row["name"] if "name" in row.keys() else None,
        )

    def get_user_bots(self, owner_uid: str, limit: int = 50) -> list[dict]:
        """유저의 모의주식 봇 제출 이력을 반환한다 (코드가 저장된 항목만)."""
        cursor = self._execute(
            """
            SELECT
                sgp.id, sgp.bot_id, sgp.bot_name, sgp.code,
                sgp.final_rank, sgp.profit_rate,
                sg.id   AS game_id,
                sg.name AS game_name,
                sg.created_at
            FROM stock_games sg
            JOIN stock_game_participants sgp ON sg.id = sgp.game_id
            WHERE sg.owner_uid = ?
              AND NOT sgp.is_ai_filler
              AND sgp.code IS NOT NULL
            ORDER BY sg.created_at DESC
            LIMIT ?
            """,
            (owner_uid, limit),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _row_to_participant(self, row) -> StockParticipantRecord:
        keys = row.keys() if hasattr(row, "keys") else {}
        return StockParticipantRecord(
            id=row["id"],
            game_id=row["game_id"],
            bot_id=row["bot_id"],
            bot_name=row["bot_name"],
            is_ai_filler=bool(row["is_ai_filler"]),
            final_rank=row["final_rank"],
            initial_cash=row["initial_cash"],
            final_total_value=row["final_total_value"],
            profit_rate=row["profit_rate"],
            final_credit_score=row["final_credit_score"],
            code=row["code"] if "code" in keys else None,
        )

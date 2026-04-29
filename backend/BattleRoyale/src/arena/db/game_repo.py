"""
AI Arena — 게임 리포지토리
게임 세션 기록 CRUD 및 참가자 관리.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GameRecord:
    id: str
    owner_user_id: Optional[int]
    status: str
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    final_tick: Optional[int]
    end_reason: Optional[str]
    winner_bot_id: Optional[int]
    total_bots: int
    seed: Optional[int]


@dataclass
class ParticipantRecord:
    id: int
    game_id: str
    bot_id: Optional[int]
    bot_name: str
    is_ai_filler: bool
    final_rank: Optional[int]
    final_score: Optional[float]
    kills: int
    minerals_mined: int
    survival_ticks: int


class GameRepository:
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

    def create_game(
        self,
        game_id: str,
        owner_user_id: int,
        total_bots: int,
        seed: Optional[int] = None,
        config_json: Optional[str] = None,
    ) -> GameRecord:
        self._execute(
            """
            INSERT INTO games (id, owner_user_id, total_bots, seed, config_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (game_id, owner_user_id, total_bots, seed, config_json),
        )
        self.conn.commit()
        return self.get_game(game_id)

    def get_game(self, game_id: str) -> Optional[GameRecord]:
        cursor = self._execute("SELECT * FROM games WHERE id = ?", (game_id,))
        row = cursor.fetchone()
        return self._row_to_game(row) if row else None

    def get_game_by_owner(self, game_id: str, owner_user_id: int) -> Optional[GameRecord]:
        cursor = self._execute(
            "SELECT * FROM games WHERE id = ? AND owner_user_id = ?",
            (game_id, owner_user_id),
        )
        row = cursor.fetchone()
        return self._row_to_game(row) if row else None

    def update_game_started(self, game_id: str) -> None:
        self._execute(
            f"UPDATE games SET status = 'running', started_at = {self._now()} WHERE id = ?",
            (game_id,),
        )
        self.conn.commit()

    def update_game_finished(
        self,
        game_id: str,
        final_tick: int,
        end_reason: str,
        winner_bot_id: Optional[int] = None,
    ) -> None:
        self._execute(
            """
            UPDATE games
            SET status = 'finished', finished_at = """ + self._now() + """,
                final_tick = ?, end_reason = ?, winner_bot_id = ?
            WHERE id = ?
            """,
            (final_tick, end_reason, winner_bot_id, game_id),
        )
        self.conn.commit()

    def add_participant(
        self,
        game_id: str,
        bot_name: str,
        bot_id: Optional[int] = None,
        is_ai_filler: bool = False,
    ) -> int:
        """참가자 추가. 생성된 participant ID를 반환."""
        if self._is_pg:
            cursor = self._execute(
                """
                INSERT INTO game_participants (game_id, bot_id, bot_name, is_ai_filler)
                VALUES (?, ?, ?, ?)
                RETURNING id
                """,
                (game_id, bot_id, bot_name, is_ai_filler),
            )
            participant_id = cursor.fetchone()["id"]
        else:
            cursor = self._execute(
                """
                INSERT INTO game_participants (game_id, bot_id, bot_name, is_ai_filler)
                VALUES (?, ?, ?, ?)
                """,
                (game_id, bot_id, bot_name, int(is_ai_filler)),
            )
            participant_id = cursor.lastrowid
        self.conn.commit()
        return participant_id

    def update_participant_result(
        self,
        game_id: str,
        bot_name: str,
        final_rank: int,
        final_score: float,
        kills: int = 0,
        minerals_mined: int = 0,
        survival_ticks: int = 0,
    ) -> None:
        self._execute(
            """
            UPDATE game_participants
            SET final_rank = ?, final_score = ?,
                kills = ?, minerals_mined = ?, survival_ticks = ?
            WHERE game_id = ? AND bot_name = ?
            """,
            (final_rank, final_score, kills, minerals_mined,
             survival_ticks, game_id, bot_name),
        )
        self.conn.commit()

    def get_participants(self, game_id: str) -> list[ParticipantRecord]:
        cursor = self._execute(
            "SELECT * FROM game_participants WHERE game_id = ? ORDER BY COALESCE(final_rank, 9999) ASC",
            (game_id,),
        )
        return [self._row_to_participant(row) for row in cursor.fetchall()]

    def get_bot_game_history(
        self, bot_id: int, limit: int = 20
    ) -> list[dict]:
        """특정 봇의 최근 게임 기록."""
        cursor = self._execute(
            """
            SELECT gp.*, g.finished_at, g.end_reason
            FROM game_participants gp
            JOIN games g ON g.id = gp.game_id
            WHERE gp.bot_id = ? AND g.status = 'finished'
            ORDER BY g.finished_at DESC
            LIMIT ?
            """,
            (bot_id, limit),
        )
        results = []
        for row in cursor.fetchall():
            results.append({
                "game_id": row["game_id"],
                "bot_name": row["bot_name"],
                "final_rank": row["final_rank"],
                "final_score": row["final_score"],
                "kills": row["kills"],
                "minerals_mined": row["minerals_mined"],
                "survival_ticks": row["survival_ticks"],
                "finished_at": row["finished_at"],
                "end_reason": row["end_reason"],
            })
        return results

    def cleanup_stale_games(self) -> int:
        """서버 재시작 시 미완료 게임을 error 상태로 변경. 변경된 수를 반환."""
        cursor = self._execute(
            """
            UPDATE games SET status = 'error', end_reason = 'server_restart'
            WHERE status IN ('waiting', 'running')
            """,
        )
        self.conn.commit()
        return cursor.rowcount

    def get_recent_games(self, limit: int = 20) -> list[GameRecord]:
        cursor = self._execute(
            "SELECT * FROM games ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_game(row) for row in cursor.fetchall()]

    def list_games_by_owner(self, owner_user_id: int, limit: int = 50) -> list[GameRecord]:
        cursor = self._execute(
            """
            SELECT * FROM games
            WHERE owner_user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (owner_user_id, limit),
        )
        return [self._row_to_game(row) for row in cursor.fetchall()]

    def _row_to_game(self, row: sqlite3.Row) -> GameRecord:
        return GameRecord(
            id=row["id"],
            owner_user_id=row["owner_user_id"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            final_tick=row["final_tick"],
            end_reason=row["end_reason"],
            winner_bot_id=row["winner_bot_id"],
            total_bots=row["total_bots"],
            seed=row["seed"],
        )

    def _row_to_participant(self, row: sqlite3.Row) -> ParticipantRecord:
        return ParticipantRecord(
            id=row["id"],
            game_id=row["game_id"],
            bot_id=row["bot_id"],
            bot_name=row["bot_name"],
            is_ai_filler=bool(row["is_ai_filler"]),
            final_rank=row["final_rank"],
            final_score=row["final_score"],
            kills=row["kills"],
            minerals_mined=row["minerals_mined"],
            survival_ticks=row["survival_ticks"],
        )

"""
AI Arena — 봇 리포지토리
봇 코드 CRUD, 버전 관리, 전적 통계.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass
class BotRecord:
    id: int
    user_id: int
    name: str
    code: str
    description: str
    version: int
    is_active: bool
    created_at: str
    updated_at: str
    wins: int
    losses: int
    games_played: int

    @property
    def win_rate(self) -> float:
        if self.games_played == 0:
            return 0.0
        return self.wins / self.games_played


class BotRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(
        self,
        user_id: int,
        name: str,
        code: str,
        description: str = "",
    ) -> BotRecord:
        """봇을 생성하고 반환."""
        cursor = self.conn.execute(
            """
            INSERT INTO bots (user_id, name, code, description)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, name, code, description),
        )
        self.conn.commit()
        return self.get_by_id(cursor.lastrowid)

    def get_by_id(self, bot_id: int) -> Optional[BotRecord]:
        cursor = self.conn.execute("SELECT * FROM bots WHERE id = ?", (bot_id,))
        row = cursor.fetchone()
        return self._row_to_bot(row) if row else None

    def get_by_user(self, user_id: int, active_only: bool = True) -> list[BotRecord]:
        """유저의 봇 목록 (최신 순)."""
        if active_only:
            cursor = self.conn.execute(
                "SELECT * FROM bots WHERE user_id = ? AND is_active = 1 ORDER BY updated_at DESC",
                (user_id,),
            )
        else:
            cursor = self.conn.execute(
                "SELECT * FROM bots WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            )
        return [self._row_to_bot(row) for row in cursor.fetchall()]

    def get_by_user_and_name(self, user_id: int, name: str) -> Optional[BotRecord]:
        cursor = self.conn.execute(
            "SELECT * FROM bots WHERE user_id = ? AND name = ?",
            (user_id, name),
        )
        row = cursor.fetchone()
        return self._row_to_bot(row) if row else None

    def update_code(self, bot_id: int, code: str, description: str | None = None) -> BotRecord:
        """봇 코드를 업데이트하고 버전을 증가."""
        if description is not None:
            self.conn.execute(
                """
                UPDATE bots
                SET code = ?, description = ?, version = version + 1,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (code, description, bot_id),
            )
        else:
            self.conn.execute(
                """
                UPDATE bots
                SET code = ?, version = version + 1,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (code, bot_id),
            )
        self.conn.commit()
        return self.get_by_id(bot_id)

    def soft_delete(self, bot_id: int) -> None:
        """봇을 비활성화 (소프트 삭제)."""
        self.conn.execute(
            "UPDATE bots SET is_active = 0, updated_at = datetime('now') WHERE id = ?",
            (bot_id,),
        )
        self.conn.commit()

    def record_game_result(
        self, bot_id: int, won: bool
    ) -> None:
        """게임 결과를 전적에 반영."""
        if won:
            self.conn.execute(
                """
                UPDATE bots
                SET wins = wins + 1, games_played = games_played + 1,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (bot_id,),
            )
        else:
            self.conn.execute(
                """
                UPDATE bots
                SET losses = losses + 1, games_played = games_played + 1,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (bot_id,),
            )
        self.conn.commit()

    def get_leaderboard(self, limit: int = 20) -> list[BotRecord]:
        """승률 기준 상위 봇 목록."""
        cursor = self.conn.execute(
            """
            SELECT * FROM bots
            WHERE is_active = 1 AND games_played >= 3
            ORDER BY CAST(wins AS REAL) / MAX(games_played, 1) DESC,
                     wins DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_bot(row) for row in cursor.fetchall()]

    def validate_code(self, code: str) -> tuple[bool, str]:
        """
        봇 코드 기본 검증.
        - action 함수가 정의되어 있는지
        - 문법 오류가 없는지
        - 크기 제한 내인지
        """
        max_size = 50_000
        if len(code) > max_size:
            return False, f"코드 크기가 {max_size}바이트를 초과합니다."

        if not code.strip():
            return False, "코드가 비어 있습니다."

        # 문법 검사
        try:
            compile(code, "<bot>", "exec")
        except SyntaxError as e:
            return False, f"문법 오류: {e.msg} (줄 {e.lineno})"

        # action 함수 존재 확인
        if "def action(" not in code and "def action (" not in code:
            return False, "action(state) 함수가 정의되어 있지 않습니다."

        return True, ""

    def _row_to_bot(self, row: sqlite3.Row) -> BotRecord:
        return BotRecord(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            code=row["code"],
            description=row["description"],
            version=row["version"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            wins=row["wins"],
            losses=row["losses"],
            games_played=row["games_played"],
        )

"""
AI Arena — 유저 리포지토리
유저 계정 CRUD 및 조회.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    id: int
    firebase_uid: str
    username: str
    display_name: str
    email: Optional[str]
    email_verified: bool
    auth_provider: Optional[str]
    photo_url: Optional[str]
    role: str
    created_at: str
    updated_at: Optional[str]
    last_login_at: Optional[str]
    is_active: bool
    banned_reason: Optional[str]
    banned_at: Optional[str]
    elo: int = 1200
    wins: int = 0
    losses: int = 0
    games_played: int = 0


class UserRepository:
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

    def create(
        self,
        firebase_uid: str,
        username: str,
        display_name: str,
        email: Optional[str] = None,
        auth_provider: Optional[str] = None,
        photo_url: Optional[str] = None,
    ) -> User:
        """유저를 생성하고 반환."""
        if self._is_pg:
            cur = self._execute(
                "INSERT INTO users (firebase_uid, username, display_name, email, auth_provider, photo_url) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (firebase_uid, username, display_name, email, auth_provider, photo_url),
            )
            user_id = cur.fetchone()["id"]
        else:
            cur = self._execute(
                "INSERT INTO users (firebase_uid, username, display_name, email, auth_provider, photo_url) VALUES (?, ?, ?, ?, ?, ?)",
                (firebase_uid, username, display_name, email, auth_provider, photo_url),
            )
            user_id = cur.lastrowid
        self.conn.commit()
        return self.get_by_id(user_id)

    def get_by_id(self, user_id: int) -> Optional[User]:
        cursor = self._execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        )
        row = cursor.fetchone()
        return self._row_to_user(row) if row else None

    def get_by_username(self, username: str) -> Optional[User]:
        cursor = self._execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        row = cursor.fetchone()
        return self._row_to_user(row) if row else None

    def get_by_firebase_uid(self, firebase_uid: str) -> Optional[User]:
        cursor = self._execute(
            "SELECT * FROM users WHERE firebase_uid = ?", (firebase_uid,)
        )
        row = cursor.fetchone()
        return self._row_to_user(row) if row else None

    def update_last_login(self, user_id: int) -> None:
        self._execute(
            f"UPDATE users SET last_login_at = {self._now()} WHERE id = ?",
            (user_id,),
        )
        self.conn.commit()

    def update_display_name(self, user_id: int, display_name: str) -> None:
        self._execute(
            f"UPDATE users SET display_name = ?, updated_at = {self._now()} WHERE id = ?",
            (display_name, user_id),
        )
        self.conn.commit()

    def deactivate(self, user_id: int) -> None:
        self._execute(
            "UPDATE users SET is_active = 0 WHERE id = ?", (user_id,)
        )
        self.conn.commit()

    def username_exists(self, username: str) -> bool:
        cursor = self._execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        )
        return cursor.fetchone() is not None

    def update_elo(self, user_id: int, new_elo: int, won: bool) -> None:
        """ELO 점수와 전적을 갱신한다."""
        if won:
            self._execute(
                f"UPDATE users SET elo = ?, wins = wins + 1, games_played = games_played + 1, updated_at = {self._now()} WHERE id = ?",
                (new_elo, user_id),
            )
        else:
            self._execute(
                f"UPDATE users SET elo = ?, losses = losses + 1, games_played = games_played + 1, updated_at = {self._now()} WHERE id = ?",
                (new_elo, user_id),
            )
        self.conn.commit()

    def get_rankings(self, limit: int = 50) -> list[User]:
        """ELO 순으로 정렬된 유저 목록을 반환한다. 게임 기록이 없는 유저는 제외."""
        cursor = self._execute(
            "SELECT * FROM users WHERE is_active = ? AND games_played > 0 ORDER BY elo DESC, wins DESC LIMIT ?",
            (self._bool_true(), limit),
        )
        return [self._row_to_user(row) for row in cursor.fetchall()]

    def _bool_true(self):
        return True if self._is_pg else 1

    def _row_to_user(self, row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            firebase_uid=row["firebase_uid"],
            username=row["username"],
            display_name=row["display_name"],
            email=row["email"],
            email_verified=bool(row["email_verified"]),
            auth_provider=row["auth_provider"],
            photo_url=row["photo_url"],
            role=row["role"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login_at=row["last_login_at"],
            is_active=bool(row["is_active"]),
            banned_reason=row["banned_reason"],
            banned_at=row["banned_at"],
            elo=row["elo"] if "elo" in row.keys() else 1200,
            wins=row["wins"] if "wins" in row.keys() else 0,
            losses=row["losses"] if "losses" in row.keys() else 0,
            games_played=row["games_played"] if "games_played" in row.keys() else 0,
        )

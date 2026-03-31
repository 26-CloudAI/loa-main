"""
AI Arena — 유저 리포지토리
유저 계정 CRUD 및 조회.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    id: int
    username: str
    display_name: str
    password_hash: str
    salt: str
    created_at: str
    last_login_at: Optional[str]
    is_active: bool


class UserRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(
        self,
        username: str,
        display_name: str,
        password_hash: str,
        salt: str,
    ) -> User:
        """유저를 생성하고 반환."""
        cursor = self.conn.execute(
            """
            INSERT INTO users (username, display_name, password_hash, salt)
            VALUES (?, ?, ?, ?)
            """,
            (username, display_name, password_hash, salt),
        )
        self.conn.commit()
        return self.get_by_id(cursor.lastrowid)

    def get_by_id(self, user_id: int) -> Optional[User]:
        cursor = self.conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        )
        row = cursor.fetchone()
        return self._row_to_user(row) if row else None

    def get_by_username(self, username: str) -> Optional[User]:
        cursor = self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        row = cursor.fetchone()
        return self._row_to_user(row) if row else None

    def update_last_login(self, user_id: int) -> None:
        self.conn.execute(
            "UPDATE users SET last_login_at = datetime('now') WHERE id = ?",
            (user_id,),
        )
        self.conn.commit()

    def update_display_name(self, user_id: int, display_name: str) -> None:
        self.conn.execute(
            "UPDATE users SET display_name = ? WHERE id = ?",
            (display_name, user_id),
        )
        self.conn.commit()

    def deactivate(self, user_id: int) -> None:
        self.conn.execute(
            "UPDATE users SET is_active = 0 WHERE id = ?", (user_id,)
        )
        self.conn.commit()

    def username_exists(self, username: str) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        )
        return cursor.fetchone() is not None

    def _row_to_user(self, row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            password_hash=row["password_hash"],
            salt=row["salt"],
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
            is_active=bool(row["is_active"]),
        )

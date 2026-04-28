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
        )

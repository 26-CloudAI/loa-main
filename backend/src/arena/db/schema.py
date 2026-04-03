"""
AI Arena — 데이터베이스 스키마 및 마이그레이션

DB_TYPE 환경변수에 따라 SQLite 또는 PostgreSQL을 사용한다.

테이블:
  users              — 유저 계정
  bots               — 유저가 업로드한 봇 코드
  games              — 게임 세션 기록
  game_participants  — 게임 참가자 (봇 ↔ 게임 매핑)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

SCHEMA_VERSION = 1

# ── SQLite DDL ─────────────────────────────────
SCHEMA_SQL_SQLITE = """
-- 유저 계정
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    display_name    TEXT    NOT NULL,
    password_hash   TEXT    NOT NULL,
    salt            TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    last_login_at   TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- 유저가 업로드한 봇 코드
CREATE TABLE IF NOT EXISTS bots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    name            TEXT    NOT NULL,
    code            TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    version         INTEGER NOT NULL DEFAULT 1,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    wins            INTEGER NOT NULL DEFAULT 0,
    losses          INTEGER NOT NULL DEFAULT 0,
    games_played    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bots_user_id ON bots(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bots_user_name ON bots(user_id, name);

-- 게임 세션 기록
CREATE TABLE IF NOT EXISTS games (
    id              TEXT    PRIMARY KEY,
    status          TEXT    NOT NULL DEFAULT 'waiting',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at      TEXT,
    finished_at     TEXT,
    final_tick      INTEGER,
    end_reason      TEXT,
    winner_bot_id   INTEGER,
    total_bots      INTEGER NOT NULL DEFAULT 0,
    seed            INTEGER,
    config_json     TEXT,
    FOREIGN KEY (winner_bot_id) REFERENCES bots(id) ON DELETE SET NULL
);

-- 게임 참가자 (봇-게임 매핑 + 결과)
CREATE TABLE IF NOT EXISTS game_participants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         TEXT    NOT NULL,
    bot_id          INTEGER,
    bot_name        TEXT    NOT NULL,
    is_ai_filler    INTEGER NOT NULL DEFAULT 0,
    final_rank      INTEGER,
    final_score     REAL,
    kills           INTEGER NOT NULL DEFAULT 0,
    minerals_mined  INTEGER NOT NULL DEFAULT 0,
    survival_ticks  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
    FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_gp_game_id ON game_participants(game_id);
CREATE INDEX IF NOT EXISTS idx_gp_bot_id ON game_participants(bot_id);

-- 스키마 버전 관리
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""

# ── PostgreSQL DDL ──────────────────────────────
SCHEMA_SQL_POSTGRESQL = """
-- 유저 계정
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL       PRIMARY KEY,
    username        VARCHAR(50)  NOT NULL UNIQUE,
    display_name    VARCHAR(100) NOT NULL,
    password_hash   TEXT         NOT NULL,
    salt            TEXT         NOT NULL,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMP,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- 유저가 업로드한 봇 코드
CREATE TABLE IF NOT EXISTS bots (
    id              SERIAL    PRIMARY KEY,
    user_id         INTEGER   NOT NULL,
    name            TEXT      NOT NULL,
    code            TEXT      NOT NULL,
    description     TEXT      NOT NULL DEFAULT '',
    version         INTEGER   NOT NULL DEFAULT 1,
    is_active       BOOLEAN   NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    wins            INTEGER   NOT NULL DEFAULT 0,
    losses          INTEGER   NOT NULL DEFAULT 0,
    games_played    INTEGER   NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bots_user_id ON bots(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bots_user_name ON bots(user_id, name);

-- 게임 세션 기록
CREATE TABLE IF NOT EXISTS games (
    id              TEXT      PRIMARY KEY,
    status          TEXT      NOT NULL DEFAULT 'waiting',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    final_tick      INTEGER,
    end_reason      TEXT,
    winner_bot_id   INTEGER,
    total_bots      INTEGER   NOT NULL DEFAULT 0,
    seed            INTEGER,
    config_json     TEXT,
    FOREIGN KEY (winner_bot_id) REFERENCES bots(id) ON DELETE SET NULL
);

-- 게임 참가자 (봇-게임 매핑 + 결과)
CREATE TABLE IF NOT EXISTS game_participants (
    id              SERIAL    PRIMARY KEY,
    game_id         TEXT      NOT NULL,
    bot_id          INTEGER,
    bot_name        TEXT      NOT NULL,
    is_ai_filler    BOOLEAN   NOT NULL DEFAULT FALSE,
    final_rank      INTEGER,
    final_score     REAL,
    kills           INTEGER   NOT NULL DEFAULT 0,
    minerals_mined  INTEGER   NOT NULL DEFAULT 0,
    survival_ticks  INTEGER   NOT NULL DEFAULT 0,
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
    FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_gp_game_id ON game_participants(game_id);
CREATE INDEX IF NOT EXISTS idx_gp_bot_id ON game_participants(bot_id);

-- 스키마 버전 관리
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


def get_connection(db_path: str | Path = "ai_arena.db"):
    """
    DB_TYPE 환경변수에 따라 DB 연결을 반환하는 팩토리.

    DB_TYPE=sqlite (기본):  sqlite3.Connection 반환
    DB_TYPE=postgresql:     psycopg2.connection 반환
                            DB_HOST, DB_NAME, DB_USER, DB_PASSWORD 필요
    """
    from ..server import settings  # 지연 import (순환 의존 방지)

    if settings.DB_TYPE == "postgresql":
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError as e:
            raise ImportError(
                "psycopg2가 필요합니다: pip install psycopg2-binary"
            ) from e

        conn = psycopg2.connect(
            host=settings.DB_HOST,
            dbname=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
        )
        conn.autocommit = False
        return conn

    # 기본: SQLite
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | Path = "ai_arena.db"):
    """
    데이터베이스를 초기화하고 연결을 반환한다.
    DB_TYPE에 따라 SQLite 또는 PostgreSQL 스키마를 생성한다.
    """
    from ..server import settings  # 지연 import (순환 의존 방지)

    if settings.DB_TYPE == "postgresql":
        return _init_postgresql()
    return _init_sqlite(db_path)


def _init_sqlite(db_path: str | Path = "ai_arena.db") -> sqlite3.Connection:
    """SQLite DB 초기화."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")   # FK 제약 활성화

    conn.executescript(SCHEMA_SQL_SQLITE)

    cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
    if cursor.fetchone()[0] == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

    conn.commit()
    return conn


def _init_postgresql():
    """PostgreSQL DB 초기화. psycopg2 필요."""
    try:
        import psycopg2
    except ImportError as e:
        raise ImportError(
            "psycopg2가 필요합니다: pip install psycopg2-binary"
        ) from e

    from ..server import settings

    conn = psycopg2.connect(
        host=settings.DB_HOST,
        dbname=settings.DB_NAME,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
    )

    with conn.cursor() as cur:
        # PostgreSQL은 executescript 없으므로 구문별로 실행
        for statement in SCHEMA_SQL_POSTGRESQL.split(";"):
            stmt = statement.strip()
            if stmt:
                cur.execute(stmt)

        cur.execute("SELECT COUNT(*) FROM schema_version")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO schema_version (version) VALUES (%s)", (SCHEMA_VERSION,)
            )

    conn.commit()
    return conn


def get_schema_version(conn) -> int:
    """현재 스키마 버전을 반환."""
    from ..server import settings

    if settings.DB_TYPE == "postgresql":
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_version LIMIT 1")
            row = cur.fetchone()
            return row[0] if row else 0
    else:
        cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else 0

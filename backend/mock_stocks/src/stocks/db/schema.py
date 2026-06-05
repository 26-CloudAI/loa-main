"""
MockStocks — 데이터베이스 스키마 및 마이그레이션

DB_TYPE 환경변수에 따라 SQLite 또는 PostgreSQL을 사용한다.
BattleRoyale과 같은 ai_arena DB를 공유하며, 테이블은 stock_ prefix로 독립 운영.

테이블:
  stock_games               — 모의주식 게임 세션
  stock_game_participants   — 게임 참가자별 결과 (수익률, 최종 자산)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

# ── SQLite DDL ─────────────────────────────────
SCHEMA_SQL_SQLITE = """
-- 모의주식 게임 세션
CREATE TABLE IF NOT EXISTS stock_games (
    id              TEXT    PRIMARY KEY,
    owner_uid       TEXT,
    name            TEXT,
    status          TEXT    NOT NULL DEFAULT 'waiting',
    total_bots      INTEGER NOT NULL DEFAULT 0,
    seed            INTEGER,
    total_ticks     INTEGER,
    tick_interval   REAL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at      TEXT,
    finished_at     TEXT,
    final_tick      INTEGER,
    end_reason      TEXT
);

-- 게임 참가자별 결과
CREATE TABLE IF NOT EXISTS stock_game_participants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id             TEXT    NOT NULL,
    bot_id              TEXT    NOT NULL,
    bot_name            TEXT    NOT NULL,
    is_ai_filler        INTEGER NOT NULL DEFAULT 0,
    code                TEXT,
    final_rank          INTEGER,
    initial_cash        REAL,
    final_total_value   REAL,
    profit_rate         REAL,
    final_credit_score  INTEGER,
    FOREIGN KEY (game_id) REFERENCES stock_games(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sgp_game_id ON stock_game_participants(game_id);
CREATE INDEX IF NOT EXISTS idx_sgp_bot_id  ON stock_game_participants(bot_id);
"""

# ── PostgreSQL DDL ──────────────────────────────
SCHEMA_SQL_POSTGRESQL = """
-- 모의주식 게임 세션
CREATE TABLE IF NOT EXISTS stock_games (
    id              TEXT        PRIMARY KEY,
    owner_uid       TEXT,
    name            TEXT,
    status          TEXT        NOT NULL DEFAULT 'waiting',
    total_bots      INTEGER     NOT NULL DEFAULT 0,
    seed            INTEGER,
    total_ticks     INTEGER,
    tick_interval   DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    final_tick      INTEGER,
    end_reason      TEXT
);

-- 게임 참가자별 결과
CREATE TABLE IF NOT EXISTS stock_game_participants (
    id                  BIGSERIAL        PRIMARY KEY,
    game_id             TEXT             NOT NULL,
    bot_id              TEXT             NOT NULL,
    bot_name            TEXT             NOT NULL,
    is_ai_filler        BOOLEAN          NOT NULL DEFAULT FALSE,
    code                TEXT,
    final_rank          INTEGER,
    initial_cash        DOUBLE PRECISION,
    final_total_value   DOUBLE PRECISION,
    profit_rate         DOUBLE PRECISION,
    final_credit_score  INTEGER,
    FOREIGN KEY (game_id) REFERENCES stock_games(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sgp_game_id ON stock_game_participants(game_id);
CREATE INDEX IF NOT EXISTS idx_sgp_bot_id  ON stock_game_participants(bot_id);
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
            connect_timeout=settings.DB_CONNECT_TIMEOUT,
            options=(
                f"-c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS} "
                f"-c lock_timeout={settings.DB_LOCK_TIMEOUT_MS}"
            ),
        )
        conn.autocommit = False
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        return conn

    # 기본: SQLite
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | Path = "ai_arena.db"):
    """
    데이터베이스를 초기화하고 연결을 반환한다.
    DB_TYPE에 따라 SQLite 또는 PostgreSQL 스키마를 생성한다.
    """
    from ..server import settings

    if settings.DB_TYPE == "postgresql":
        return _init_postgresql()
    return _init_sqlite(db_path)


def _init_sqlite(db_path: str | Path = "ai_arena.db") -> sqlite3.Connection:
    """SQLite DB 초기화."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL_SQLITE)
    try:
        conn.execute("ALTER TABLE stock_games ADD COLUMN owner_uid TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE stock_games ADD COLUMN name TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE stock_game_participants ADD COLUMN code TEXT")
    except Exception:
        pass
    conn.commit()
    return conn


def _init_postgresql():
    """PostgreSQL DB 초기화. psycopg2 필요."""
    try:
        import psycopg2
        import psycopg2.extras
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
        connect_timeout=settings.DB_CONNECT_TIMEOUT,
        options=(
            f"-c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS} "
            f"-c lock_timeout={settings.DB_LOCK_TIMEOUT_MS}"
        ),
    )

    with conn.cursor() as cur:
        for statement in SCHEMA_SQL_POSTGRESQL.split(";"):
            stmt = statement.strip()
            if stmt:
                cur.execute(stmt)

    conn.commit()
    conn.autocommit = True          # SELECT 후 트랜잭션 누수 방지
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn

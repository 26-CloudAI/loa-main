"""
AI Arena — 데이터베이스 스키마 및 마이그레이션

sqlite3 표준 라이브러리 기반.
개발 단계에서는 SQLite, 프로덕션에서는 PostgreSQL로 마이그레이션 가능.

테이블:
  users              — 유저 계정
  bots               — 유저가 업로드한 봇 코드
  games              — 게임 세션 기록
  game_participants  — 게임 참가자 (봇 ↔ 게임 매핑)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA_SQL = """
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


def init_db(db_path: str | Path = "ai_arena.db") -> sqlite3.Connection:
    """
    데이터베이스를 초기화하고 연결을 반환한다.
    테이블이 없으면 생성, 이미 있으면 그대로 사용.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")     # 동시 읽기 성능 향상
    conn.execute("PRAGMA foreign_keys=ON")       # FK 제약 활성화

    conn.executescript(SCHEMA_SQL)

    # 스키마 버전 기록
    cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
    if cursor.fetchone()[0] == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

    conn.commit()
    return conn


def get_schema_version(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
    row = cursor.fetchone()
    return row[0] if row else 0

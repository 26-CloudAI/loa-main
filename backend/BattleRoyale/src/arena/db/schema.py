"""
AI Arena — 데이터베이스 스키마 및 마이그레이션

DB_TYPE 환경변수에 따라 SQLite 또는 PostgreSQL을 사용한다.

테이블:
  users              — 유저 계정 (Firebase Auth 기반)
  bots               — 유저가 업로드한 봇 코드
  games              — 게임 세션 기록
  game_participants  — 게임 참가자 (봇 ↔ 게임 매핑)
  seasons            — 시즌 관리
  bot_ratings        — 봇별 시즌 레이팅
  rating_history     — 게임별 레이팅 변동 기록
  schema_version     — 스키마 버전 관리
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 5

# ── SQLite DDL ─────────────────────────────────
SCHEMA_SQL_SQLITE = """
-- 유저 계정 (Firebase Auth 기반)
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    firebase_uid    TEXT    NOT NULL UNIQUE,
    username        TEXT    NOT NULL UNIQUE,
    display_name    TEXT    NOT NULL,
    email           TEXT,
    email_verified  INTEGER NOT NULL DEFAULT 0,
    auth_provider   TEXT,
    photo_url       TEXT,
    role            TEXT    NOT NULL DEFAULT 'user',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT,
    last_login_at   TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    banned_reason   TEXT,
    banned_at       TEXT,
    elo             INTEGER NOT NULL DEFAULT 1200,
    wins            INTEGER NOT NULL DEFAULT 0,
    losses          INTEGER NOT NULL DEFAULT 0,
    games_played    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users(firebase_uid);

-- 유저가 업로드한 봇 코드
CREATE TABLE IF NOT EXISTS bots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    name            TEXT    NOT NULL,
    code            TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    version         INTEGER NOT NULL DEFAULT 1,
    is_active       INTEGER NOT NULL DEFAULT 1,
    is_public       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    wins            INTEGER NOT NULL DEFAULT 0,
    losses          INTEGER NOT NULL DEFAULT 0,
    games_played    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bots_user_id ON bots(user_id);
CREATE INDEX IF NOT EXISTS idx_bots_user_name ON bots(user_id, name);

-- 게임 세션 기록
CREATE TABLE IF NOT EXISTS games (
    id              TEXT    PRIMARY KEY,
    owner_user_id   INTEGER,
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
    name            TEXT,
    mode            TEXT    NOT NULL DEFAULT 'battle-royale',
    FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (winner_bot_id) REFERENCES bots(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_games_owner_user_id ON games(owner_user_id);

-- 게임 참가자 (봇-게임 매핑 + 결과)
CREATE TABLE IF NOT EXISTS game_participants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id             TEXT    NOT NULL,
    bot_id              INTEGER,
    bot_name            TEXT    NOT NULL,
    is_ai_filler        INTEGER NOT NULL DEFAULT 0,
    final_rank          INTEGER,
    final_score         REAL,
    kills               INTEGER NOT NULL DEFAULT 0,
    minerals_mined      INTEGER NOT NULL DEFAULT 0,
    rare_minerals_mined INTEGER NOT NULL DEFAULT 0,
    survival_ticks      INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
    FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_gp_game_id ON game_participants(game_id);
CREATE INDEX IF NOT EXISTS idx_gp_bot_id ON game_participants(bot_id);

-- 시즌
CREATE TABLE IF NOT EXISTS seasons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    ended_at    TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_seasons_is_active ON seasons(is_active);

-- 봇 레이팅 (시즌별)
CREATE TABLE IF NOT EXISTS bot_ratings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id          INTEGER NOT NULL,
    season_id       INTEGER NOT NULL,
    rating          REAL    NOT NULL DEFAULT 1000.0,
    peak_rating     REAL    NOT NULL DEFAULT 1000.0,
    games_played    INTEGER NOT NULL DEFAULT 0,
    wins            INTEGER NOT NULL DEFAULT 0,
    top3_count      INTEGER NOT NULL DEFAULT 0,
    total_kills     INTEGER NOT NULL DEFAULT 0,
    total_minerals  INTEGER NOT NULL DEFAULT 0,
    avg_survival    REAL    NOT NULL DEFAULT 0.0,
    last_played_at  TEXT,
    FOREIGN KEY (bot_id)    REFERENCES bots(id)    ON DELETE CASCADE,
    FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE CASCADE,
    UNIQUE(bot_id, season_id)
);

CREATE INDEX IF NOT EXISTS idx_br_season ON bot_ratings(season_id);
CREATE INDEX IF NOT EXISTS idx_br_bot ON bot_ratings(bot_id);

-- 레이팅 변동 기록 (게임별)
CREATE TABLE IF NOT EXISTS rating_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id          INTEGER NOT NULL,
    season_id       INTEGER NOT NULL,
    game_id         TEXT    NOT NULL,
    rating_before   REAL    NOT NULL,
    rating_after    REAL    NOT NULL,
    rating_delta    REAL    NOT NULL,
    final_rank      INTEGER NOT NULL,
    recorded_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (bot_id)    REFERENCES bots(id)    ON DELETE CASCADE,
    FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE CASCADE,
    FOREIGN KEY (game_id)   REFERENCES games(id)   ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rh_bot ON rating_history(bot_id, season_id);
CREATE INDEX IF NOT EXISTS idx_rh_game ON rating_history(game_id);

-- 스키마 버전 관리
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

# ── PostgreSQL DDL ──────────────────────────────
SCHEMA_SQL_POSTGRESQL = """
-- 유저 계정 (Firebase Auth 기반)
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL       PRIMARY KEY,
    firebase_uid    TEXT         NOT NULL UNIQUE,
    username        VARCHAR(50)  NOT NULL UNIQUE,
    display_name    VARCHAR(100) NOT NULL,
    email           TEXT,
    email_verified  BOOLEAN      NOT NULL DEFAULT FALSE,
    auth_provider   TEXT,
    photo_url       TEXT,
    role            TEXT         NOT NULL DEFAULT 'user',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ,
    last_login_at   TIMESTAMPTZ,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    banned_reason   TEXT,
    banned_at       TIMESTAMPTZ,
    elo             INTEGER      NOT NULL DEFAULT 1200,
    wins            INTEGER      NOT NULL DEFAULT 0,
    losses          INTEGER      NOT NULL DEFAULT 0,
    games_played    INTEGER      NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users(firebase_uid);

-- 유저가 업로드한 봇 코드
CREATE TABLE IF NOT EXISTS bots (
    id              BIGSERIAL   PRIMARY KEY,
    user_id         INTEGER     NOT NULL,
    name            TEXT        NOT NULL,
    code            TEXT        NOT NULL,
    description     TEXT        NOT NULL DEFAULT '',
    version         INTEGER     NOT NULL DEFAULT 1,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    is_public       BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    wins            INTEGER     NOT NULL DEFAULT 0,
    losses          INTEGER     NOT NULL DEFAULT 0,
    games_played    INTEGER     NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bots_user_id ON bots(user_id);
CREATE INDEX IF NOT EXISTS idx_bots_user_name ON bots(user_id, name);

-- 게임 세션 기록
CREATE TABLE IF NOT EXISTS games (
    id              TEXT        PRIMARY KEY,
    owner_user_id   INTEGER,
    status          TEXT        NOT NULL DEFAULT 'waiting',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    final_tick      INTEGER,
    end_reason      TEXT,
    winner_bot_id   BIGINT,
    total_bots      INTEGER     NOT NULL DEFAULT 0,
    seed            INTEGER,
    config_json     JSONB,
    name            TEXT,
    mode            TEXT        NOT NULL DEFAULT 'battle-royale',
    FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (winner_bot_id) REFERENCES bots(id) ON DELETE SET NULL
);

-- 게임 참가자 (봇-게임 매핑 + 결과)
CREATE TABLE IF NOT EXISTS game_participants (
    id                  BIGSERIAL        PRIMARY KEY,
    game_id             TEXT             NOT NULL,
    bot_id              BIGINT,
    bot_name            TEXT             NOT NULL,
    is_ai_filler        BOOLEAN          NOT NULL DEFAULT FALSE,
    final_rank          INTEGER,
    final_score         DOUBLE PRECISION,
    kills               INTEGER          NOT NULL DEFAULT 0,
    minerals_mined      INTEGER          NOT NULL DEFAULT 0,
    rare_minerals_mined INTEGER          NOT NULL DEFAULT 0,
    survival_ticks      INTEGER          NOT NULL DEFAULT 0,
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
    FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_gp_game_id ON game_participants(game_id);
CREATE INDEX IF NOT EXISTS idx_gp_bot_id ON game_participants(bot_id);

-- 시즌
CREATE TABLE IF NOT EXISTS seasons (
    id          BIGSERIAL   PRIMARY KEY,
    name        TEXT        NOT NULL UNIQUE,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_seasons_is_active ON seasons(is_active);

-- 봇 레이팅 (시즌별)
CREATE TABLE IF NOT EXISTS bot_ratings (
    id              BIGSERIAL        PRIMARY KEY,
    bot_id          BIGINT           NOT NULL,
    season_id       BIGINT           NOT NULL,
    rating          DOUBLE PRECISION NOT NULL DEFAULT 1000.0,
    peak_rating     DOUBLE PRECISION NOT NULL DEFAULT 1000.0,
    games_played    INTEGER          NOT NULL DEFAULT 0,
    wins            INTEGER          NOT NULL DEFAULT 0,
    top3_count      INTEGER          NOT NULL DEFAULT 0,
    total_kills     INTEGER          NOT NULL DEFAULT 0,
    total_minerals  INTEGER          NOT NULL DEFAULT 0,
    avg_survival    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    last_played_at  TIMESTAMPTZ,
    FOREIGN KEY (bot_id)    REFERENCES bots(id)    ON DELETE CASCADE,
    FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE CASCADE,
    UNIQUE(bot_id, season_id)
);

CREATE INDEX IF NOT EXISTS idx_br_season ON bot_ratings(season_id);
CREATE INDEX IF NOT EXISTS idx_br_bot ON bot_ratings(bot_id);

-- 레이팅 변동 기록 (게임별)
CREATE TABLE IF NOT EXISTS rating_history (
    id              BIGSERIAL        PRIMARY KEY,
    bot_id          BIGINT           NOT NULL,
    season_id       BIGINT           NOT NULL,
    game_id         TEXT             NOT NULL,
    rating_before   DOUBLE PRECISION NOT NULL,
    rating_after    DOUBLE PRECISION NOT NULL,
    rating_delta    DOUBLE PRECISION NOT NULL,
    final_rank      INTEGER          NOT NULL,
    recorded_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    FOREIGN KEY (bot_id)    REFERENCES bots(id)    ON DELETE CASCADE,
    FOREIGN KEY (season_id) REFERENCES seasons(id) ON DELETE CASCADE,
    FOREIGN KEY (game_id)   REFERENCES games(id)   ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rh_bot ON rating_history(bot_id, season_id);
CREATE INDEX IF NOT EXISTS idx_rh_game ON rating_history(game_id);

-- 스키마 버전 관리
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER     NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
    from ..server import settings  # 지연 import (순환 의존 방지)

    if settings.DB_TYPE == "postgresql":
        return _init_postgresql()
    return _init_sqlite(db_path)


def _init_sqlite(db_path: str | Path = "ai_arena.db") -> sqlite3.Connection:
    """SQLite DB 초기화."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript(SCHEMA_SQL_SQLITE)
    _migrate_sqlite(conn)

    cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
    if cursor.fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
            (SCHEMA_VERSION,),
        )
    else:
        conn.execute(
            "UPDATE schema_version SET version = ?, applied_at = datetime('now')",
            (SCHEMA_VERSION,),
        )

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

        _migrate_postgresql(cur)

        cur.execute("SELECT COUNT(*) FROM schema_version")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO schema_version (version) VALUES (%s)",
                (SCHEMA_VERSION,),
            )
        else:
            cur.execute(
                "UPDATE schema_version SET version = %s, applied_at = NOW()",
                (SCHEMA_VERSION,),
            )

    conn.commit()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn


def _migrate_sqlite(conn: sqlite3.Connection) -> None:
    """SQLite 기존 DB에 필요한 컬럼/인덱스를 보강한다."""
    game_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(games)").fetchall()
    }
    if "owner_user_id" not in game_cols:
        conn.execute(
            "ALTER TABLE games ADD COLUMN owner_user_id INTEGER REFERENCES users(id)"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_games_owner_user_id ON games(owner_user_id)"
    )

    user_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    for col, definition in [
        ("elo", "INTEGER NOT NULL DEFAULT 1200"),
        ("wins", "INTEGER NOT NULL DEFAULT 0"),
        ("losses", "INTEGER NOT NULL DEFAULT 0"),
        ("games_played", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col not in user_cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")

    if "name" not in game_cols:
        conn.execute("ALTER TABLE games ADD COLUMN name TEXT")
    if "mode" not in game_cols:
        conn.execute("ALTER TABLE games ADD COLUMN mode TEXT NOT NULL DEFAULT 'battle-royale'")

    bot_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(bots)").fetchall()
    }
    if "is_public" not in bot_cols:
        conn.execute("ALTER TABLE bots ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0")

    # 유니크 인덱스 → 일반 인덱스로 변경 (같은 이름 봇 중복 허용)
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(bots)").fetchall()}
    if "idx_bots_user_name" in indexes:
        idx_info = conn.execute("PRAGMA index_info(idx_bots_user_name)").fetchall()
        is_unique = any(
            row[0] for row in conn.execute(
                "SELECT \"unique\" FROM pragma_index_list('bots') WHERE name='idx_bots_user_name'"
            ).fetchall()
        )
        if is_unique:
            conn.execute("DROP INDEX IF EXISTS idx_bots_user_name")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bots_user_name ON bots(user_id, name)")


def _migrate_postgresql(cur) -> None:
    """PostgreSQL 기존 DB에 필요한 컬럼/인덱스를 보강한다."""
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'games' AND column_name = 'owner_user_id'
        """
    )
    if cur.fetchone() is None:
        cur.execute(
            "ALTER TABLE games ADD COLUMN owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE"
        )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_games_owner_user_id ON games(owner_user_id)"
    )

    for col, definition in [
        ("elo", "INTEGER NOT NULL DEFAULT 1200"),
        ("wins", "INTEGER NOT NULL DEFAULT 0"),
        ("losses", "INTEGER NOT NULL DEFAULT 0"),
        ("games_played", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        cur.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name=%s",
            (col,),
        )
        if cur.fetchone() is None:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")

    for col, definition in [
        ("name", "TEXT"),
        ("mode", "TEXT NOT NULL DEFAULT 'battle-royale'"),
    ]:
        cur.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name='games' AND column_name=%s",
            (col,),
        )
        if cur.fetchone() is None:
            cur.execute(f"ALTER TABLE games ADD COLUMN {col} {definition}")

    cur.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name='bots' AND column_name='is_public'"
    )
    if cur.fetchone() is None:
        cur.execute("ALTER TABLE bots ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT FALSE")

    # 유니크 인덱스 → 일반 인덱스로 변경
    cur.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename='bots' AND indexname='idx_bots_user_name'"
    )
    if cur.fetchone():
        cur.execute(
            "SELECT indisunique FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE c.relname='idx_bots_user_name'"
        )
        row = cur.fetchone()
        if row and row[0]:
            cur.execute("DROP INDEX IF EXISTS idx_bots_user_name")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bots_user_name ON bots(user_id, name)")


def get_schema_version(conn) -> int:
    """현재 스키마 버전을 반환."""
    from ..server import settings

    if settings.DB_TYPE == "postgresql":
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_version LIMIT 1")
            row = cur.fetchone()
            return row["version"] if row else 0
    else:
        cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else 0

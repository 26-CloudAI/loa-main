# DB 설계 초안 — AI Arena (LOA Backend)

> 작성일: 2026-03-31
> 최종 수정: 2026-03-31 (피드백 반영)
> 현재 구현: SQLite (`src/arena/db/schema.py`, `src/arena/ranking/repository.py`)
> 대상 환경: 개발(SQLite) → 프로덕션(PostgreSQL 권장)

---

## 0. 피드백

### Findings

1. db_design.md (line 101) 의 bot_ratings 설계는 현재 랭킹 코드 요구사항을 충분히 반영하지 못합니다. 초안은 bot_id 기준 단일 레이팅 행만 가정하고 tier, games_for_k, peak_rating 정도만 두고 있는데, 실제 랭킹 구현은 seasons 테이블을 전제로 하고, bot_ratings도 (bot_id, season_id) 단위로 관리합니다. 또한 wins, top3_count, total_kills, total_minerals, avg_survival, last_played_at까지 저장합니다. 이 구조는 실제로 repository.py, repository.py, repository.py, repository.py 에 박혀 있고, 테스트도 시즌 기반을 전제로 합니다(test_ranking.py, test_ranking.py). 지금 문서대로 가면 랭킹 모듈이 기대하는 스키마와 바로 충돌합니다.

2. db_design.md (line 458) 에서 bot_rating_history를 "향후 선택"으로 분리해 둔 건 현재 코드 기준으로는 이미 늦었습니다. 실제 구현은 rating_history 테이블을 이미 핵심 데이터로 사용하고 있고(repository.py, repository.py, repository.py), 이름도 문서와 다릅니다. 즉 이건 "선택 확장"이 아니라 현재 랭킹 설계의 필수 구성입니다. 문서가 현재 상태를 따라가지 못한 부분입니다.

3. db_design.md (line 207) 의 game_participants.final_score 설명은 아직 불완전합니다. 문서도 희귀 광물 구분 필요성을 언급하긴 했지만(db_design.md), 이걸 선택 사항처럼 둔 건 약합니다. 현재 스키마에는 minerals_mined만 있고 희귀/일반 구분 컬럼이 없습니다(schema.py). 그런데 게임 규칙상 희귀 광물과 일반 광물의 점수는 다르므로, final_score를 재계산 가능한 설계라고 쓰면 안 됩니다. 지금 구조에서는 final_score를 권위 데이터로 저장한다고 못 박거나, 아니면 rare_minerals_mined 같은 분해 컬럼을 필수로 넣는 쪽이 맞습니다.

4. db_design.md (line 239) 의 schema_version 설계는 현재 실제 스키마와 다릅니다. 문서는 applied_at까지 둔 마이그레이션 테이블을 제안하지만, 현재 구현은 version 단일 컬럼 בלבד입니다(schema.py). 초안에서 "현재 구현 반영"을 표방한다면 이 차이를 단순 확장안이 아니라 "호환 안 되는 변경"으로 분리해야 합니다. 지금처럼 한 문서 안에서 현재형과 제안형이 섞이면 마이그레이션 기준이 흐려집니다.

5. db_design.md (line 216) 의 refresh_tokens는 방향성으로는 이해되지만, 현재 백엔드 코드 요구사항이라고 보기엔 과합니다. 실제 인증 코드는 access token 생성/검증까지만 있고 DB 기반 refresh token 저장은 사용하지 않습니다(auth_service.py, auth_service.py, auth_service.py). 이 항목은 "필요 테이블"이 아니라 "향후 인증 고도화 시 후보"로 더 뒤로 빼는 편이 정확합니다.

6. db_design.md (line 81) 에서 bots.wins / losses / games_played를 캐시라고 설명한 건 맞지만, 실제 프로젝트는 이미 시즌별 랭킹 통계까지 별도로 굴리고 있습니다. 즉 bots의 전역 통계와 bot_ratings의 시즌 통계는 의미가 다릅니다. 그런데 초안은 이 둘의 책임 구분이 약합니다. 실제로 bots는 전역 누적 승패를 업데이트하고(bot_repo.py), 랭킹 저장소는 시즌별 통계를 별도로 관리합니다(repository.py). 이걸 명확히 안 써두면 나중에 어느 숫자가 화면 기준인지 혼선이 생깁니다.

### 좋은 점

1. users, bots, games, game_participants의 큰 축은 현재 기본 스키마와 잘 맞습니다(schema.py, schema.py, schema.py, schema.py).
2. 코드 크기 제한 50KB를 문서에 반영한 점은 실제 서버/검증 로직과 일치합니다(db_design.md, config.py, bot_repo.py).
3. game_participants.bot_id를 nullable로 두고 AI filler를 bot_name으로 보존하는 방향은 실제 사용 패턴과 맞습니다(db_design.md, game_repo.py).

### 보완 제안

- seasons, bot_ratings, rating_history를 한 묶음의 "필수 랭킹 스키마"로 승격하세요.
- bot_ratings는 UNIQUE(bot_id, season_id) 기준으로 재정의하세요.
- bots 통계는 "전역 누적", bot_ratings 통계는 "시즌 누적"이라고 문서에 명시하세요.
- final_score를 권위 데이터로 볼지, 재계산 가능 데이터로 볼지 먼저 결정하세요.
- 재계산 가능하게 갈 거면 rare_minerals_mined 또는 점수 분해 컬럼을 필수로 넣으세요.
- schema_version은 "현재 구현형"과 "개선안"을 분리해서 적으세요.
- refresh_tokens는 현재 요구사항이 아니라 향후 확장안으로 한 단계 뒤로 내리세요.

- 한 줄 평으로 정리하면, db_design.md의 기본 축은 괜찮지만 "랭킹/시즌 설계"와 "점수 재구성 가능성"은 지금 상태로는 실제 코드 요구사항을 충분히 반영하지 못했습니다.

---

## 1. 개요

| 테이블 | 분류 | 설명 |
|---|---|---|
| `users` | 핵심 | 플랫폼 사용자 계정 |
| `bots` | 핵심 | 봇 코드 + **전역** 누적 통계 캐시 |
| `seasons` | 핵심 (랭킹) | 시즌 메타데이터 |
| `bot_ratings` | 핵심 (랭킹) | 봇별 **시즌** ELO 레이팅 및 통계 |
| `rating_history` | 핵심 (랭킹) | 대전별 레이팅 변화 이력 |
| `games` | 핵심 | 대전 메타데이터 |
| `game_participants` | 핵심 | 대전별 봇 참가 결과 |
| `schema_version` | 관리 | DB 마이그레이션 버전 추적 |

> `refresh_tokens`는 현재 코드에서 사용하지 않으므로 Section 7(향후 확장)으로 분류.

---

## 2. ERD (텍스트)

```
users    (1) ──< bots            (N)
seasons  (1) ──< bot_ratings     (N)
bots     (1) ──< bot_ratings     (N)   [UNIQUE(bot_id, season_id)]
bots     (1) ──< rating_history  (N)
seasons  (1) ──< rating_history  (N)
games    (1) ──< rating_history  (N)
bots     (1) ──< game_participants (N)
games    (1) ──< game_participants (N)
games    (N) >── bots            (1)   [winner_bot_id]
```

---

## 3. 테이블 상세

---

### 3.1 `users`

사용자 계정 정보 및 인증 자격증명을 저장한다.

```sql
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,        -- 로그인 ID (3~20자, 영숫자+_)
    display_name    TEXT    NOT NULL,               -- 화면 표시 이름
    password_hash   TEXT    NOT NULL,               -- PBKDF2-HMAC-SHA256 해시
    salt            TEXT    NOT NULL,               -- 32바이트 hex salt
    created_at      TEXT    NOT NULL,               -- ISO 8601
    last_login_at   TEXT,                           -- nullable
    is_active       INTEGER NOT NULL DEFAULT 1      -- 0: 비활성, 1: 활성
);

CREATE INDEX idx_users_username ON users(username);
```

**제약 조건**
- `username`: 정규식 `^[a-zA-Z0-9_]{3,20}$`
- `password`: 최소 6자 (서비스 레이어 검증)
- `salt`: `secrets.token_hex(32)` 생성 (32바이트 = 64 hex chars)

---

### 3.2 `bots`

봇 소스 코드와 **전역 누적** 통계를 저장한다.

> **통계 책임 구분**
> - `bots.wins / losses / games_played` — **전역 누적** (시즌에 무관한 통산 기록, 프로필/봇 카드 표시용)
> - `bot_ratings.wins / top3_count / ...` — **시즌 누적** (현재 시즌 기준 랭킹/리더보드 표시용)
>
> UI에서 "이번 시즌 승률"은 `bot_ratings`를 사용하고, "역대 통산 승패"는 `bots`를 사용한다.

```sql
CREATE TABLE bots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,               -- 봇 이름 (사용자 내 유일)
    code            TEXT    NOT NULL,               -- 파이썬 소스코드 (최대 50KB)
    description     TEXT    NOT NULL DEFAULT '',
    version         INTEGER NOT NULL DEFAULT 1,     -- 코드 수정 시 자동 증가
    is_active       INTEGER NOT NULL DEFAULT 1,     -- 0: 소프트 삭제
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    -- 전역 누적 통계 (game_participants 기반 캐시, 시즌 무관)
    wins            INTEGER NOT NULL DEFAULT 0,
    losses          INTEGER NOT NULL DEFAULT 0,
    games_played    INTEGER NOT NULL DEFAULT 0,

    UNIQUE(user_id, name)
);

CREATE INDEX idx_bots_user_id   ON bots(user_id);
CREATE INDEX idx_bots_user_name ON bots(user_id, name);
```

**비즈니스 규칙**
- 코드 크기 제한: 50,000 bytes (`APIConfig.max_bot_code_size`)
- 코드 업데이트 시: `version += 1`, `updated_at` 갱신
- 소프트 삭제: `is_active = 0` (물리 삭제 없음)

---

### 3.3 `seasons`

랭킹 시즌 메타데이터를 저장한다. `bot_ratings`와 `rating_history`는 모두 시즌 단위로 관리된다.

```sql
CREATE TABLE seasons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,            -- 예: "Season 1", "2026 Spring"
    started_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    ended_at    TEXT,                               -- NULL: 진행 중
    is_active   INTEGER NOT NULL DEFAULT 1          -- 활성 시즌은 1개만 허용
);
```

**비즈니스 규칙**
- 새 시즌 생성 시: 기존 활성 시즌의 `is_active = 0`, `ended_at` 기록 후 신규 삽입 (`SeasonRepository.create_season()`)
- 활성 시즌(`is_active = 1`)은 항상 최대 1개 유지

---

### 3.4 `bot_ratings`

봇의 **시즌별** ELO 레이팅과 시즌 누적 통계를 저장한다. 한 봇은 시즌마다 1개의 행을 가진다.

```sql
CREATE TABLE bot_ratings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id          INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    season_id       INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    rating          REAL    NOT NULL DEFAULT 1200.0,
    peak_rating     REAL    NOT NULL DEFAULT 1200.0,
    games_played    INTEGER NOT NULL DEFAULT 0,
    -- 시즌 누적 통계
    wins            INTEGER NOT NULL DEFAULT 0,     -- 1위 횟수
    top3_count      INTEGER NOT NULL DEFAULT 0,     -- 3위 이내 횟수
    total_kills     INTEGER NOT NULL DEFAULT 0,
    total_minerals  INTEGER NOT NULL DEFAULT 0,
    avg_survival    REAL    NOT NULL DEFAULT 0.0,   -- 평균 생존 틱 (누적 평균)
    last_played_at  TEXT,

    UNIQUE(bot_id, season_id)
);

CREATE INDEX idx_br_season ON bot_ratings(season_id);
CREATE INDEX idx_br_rating ON bot_ratings(season_id, rating DESC);
```

**파생 속성** (저장 없이 계산)
- `tier`: `get_tier(rating)` 함수로 런타임 계산 (`src/arena/ranking/elo.py`)
- `win_rate`: `wins / games_played`
- `top3_rate`: `top3_count / games_played`

**티어 기준** (`src/arena/ranking/elo.py`)

| 티어 | 레이팅 범위 |
|---|---|
| Grandmaster | 2000+ |
| Master | 1800 – 1999 |
| Diamond | 1600 – 1799 |
| Platinum | 1400 – 1599 |
| Gold | 1200 – 1399 |
| Silver | 1000 – 1199 |
| Bronze | 800 – 999 |
| Iron | < 800 |

**K-factor 기준** (`src/arena/ranking/elo.py`)

| 구간 | K-factor |
|---|---|
| 10경기 미만 | 40.0 |
| 10~29경기 | 24.0 |
| 30경기 이상 | 16.0 |

---

### 3.5 `rating_history`

대전별 레이팅 변화를 기록하는 **필수** 이력 테이블이다. 레이팅 차트, 최근 트렌드, 연승/연패 계산에 사용된다.

```sql
CREATE TABLE rating_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id          INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    season_id       INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    game_id         TEXT    NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    rating_before   REAL    NOT NULL,
    rating_after    REAL    NOT NULL,
    rating_delta    REAL    NOT NULL,               -- rating_after - rating_before
    final_rank      INTEGER NOT NULL,               -- 해당 대전에서의 순위
    recorded_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_rh_bot ON rating_history(bot_id, season_id);
```

**사용처** (`src/arena/ranking/repository.py`)
- `get_rating_history()` — 이력 목록 조회
- `get_rating_chart_data()` — 레이팅 변화 차트 데이터
- `get_bot_stats()` — 최근 5경기 트렌드, 현재 연승/연패 계산

---

### 3.6 `games`

개별 대전의 메타데이터 및 결과를 저장한다.

```sql
CREATE TABLE games (
    id              TEXT    PRIMARY KEY,             -- UUID v4
    status          TEXT    NOT NULL DEFAULT 'waiting',
                                                     -- waiting|running|finished|error
    created_at      TEXT    NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    final_tick      INTEGER,
    end_reason      TEXT,                            -- max_ticks|last_standing|all_minerals_depleted
    winner_bot_id   INTEGER REFERENCES bots(id) ON DELETE SET NULL,
    total_bots      INTEGER NOT NULL,
    seed            INTEGER,                         -- 맵 생성 시드 (재현용)
    config_json     TEXT                             -- 직렬화된 GameConfig JSON
);

CREATE INDEX idx_games_status     ON games(status);
CREATE INDEX idx_games_created_at ON games(created_at DESC);
```

**status 전이**
```
waiting → running → finished
                 ↘ error
```

**end_reason 값** (`src/arena/types.py:GameOverReason`)
- `max_ticks`: 최대 틱(500) 도달
- `last_standing`: 최후의 1봇 생존
- `all_minerals_depleted`: 모든 광물 채굴 완료

---

### 3.7 `game_participants`

각 대전에서 참가한 봇별 결과 및 통계를 저장한다.

```sql
CREATE TABLE game_participants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id             TEXT    NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    bot_id              INTEGER REFERENCES bots(id) ON DELETE SET NULL,
                                                         -- AI 필러봇은 NULL
    bot_name            TEXT    NOT NULL,               -- 대전 당시 봇 이름 스냅샷
    is_ai_filler        INTEGER NOT NULL DEFAULT 0,     -- 1: AI 채움봇
    -- 결과 (게임 종료 후 기록)
    final_rank          INTEGER,
    final_score         REAL,                           -- 권위 데이터 (재계산 불가, 아래 참고)
    kills               INTEGER NOT NULL DEFAULT 0,
    minerals_mined      INTEGER NOT NULL DEFAULT 0,     -- 일반 + 희귀 합산
    rare_minerals_mined INTEGER NOT NULL DEFAULT 0,     -- 희귀 광물만 별도 집계
    survival_ticks      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_gp_game_id ON game_participants(game_id);
CREATE INDEX idx_gp_bot_id  ON game_participants(bot_id);
```

**`final_score` 설계 원칙 — 권위 데이터**

`final_score`는 게임 엔진이 계산한 최종 점수를 그대로 저장하며, DB에서 재계산하지 않는다.

> 이유: `minerals_mined`만으로는 일반/희귀 비율을 알 수 없어 `final_score`를 역산할 수 없다.
> `rare_minerals_mined`를 추가하여 점수 분해 검증은 가능하게 하되, **화면 표시와 랭킹 기준은 `final_score`를 사용**한다.

**점수 공식** (엔진 내부, `src/arena/config.py`)
```
final_score = (일반 광물 수 × 15) + (희귀 광물 수 × 40)
            + (survival_ticks × 0.1)
            + (kills × 10)

검증:
일반 광물 수 = minerals_mined - rare_minerals_mined
희귀 광물 수 = rare_minerals_mined
```

---

### 3.8 `schema_version`

DB 마이그레이션 버전을 추적한다.

**현재 구현** (`src/arena/db/schema.py` 기준):
```sql
-- 컬럼이 version 하나뿐, PRIMARY KEY 없음
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
-- 초기화: INSERT INTO schema_version (version) VALUES (1)
```

**개선안** (호환 불가 변경 — 마이그레이션 필요):
```sql
-- applied_at 추가, PRIMARY KEY 지정
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT    NOT NULL
);
-- 초기화: INSERT OR IGNORE INTO schema_version VALUES (1, datetime('now'))
```

> 현재 구현에서 개선안으로 전환하려면 기존 테이블 DROP 후 재생성이 필요하다 (비파괴적 ALTER로 처리 불가).

---

## 4. 전체 DDL (초기화 스크립트)

현재 구현(`schema.py` + `repository.py`)을 통합한 전체 스키마.

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 1. users
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    salt          TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- 2. bots (전역 누적 통계 포함)
CREATE TABLE IF NOT EXISTS bots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    code         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    version      INTEGER NOT NULL DEFAULT 1,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    wins         INTEGER NOT NULL DEFAULT 0,
    losses       INTEGER NOT NULL DEFAULT 0,
    games_played INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_bots_user_id   ON bots(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bots_user_name ON bots(user_id, name);

-- 3. seasons
CREATE TABLE IF NOT EXISTS seasons (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    started_at TEXT    NOT NULL DEFAULT (datetime('now')),
    ended_at   TEXT,
    is_active  INTEGER NOT NULL DEFAULT 1
);

-- 4. bot_ratings (시즌 누적 통계 포함)
CREATE TABLE IF NOT EXISTS bot_ratings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id         INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    season_id      INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    rating         REAL    NOT NULL DEFAULT 1200.0,
    peak_rating    REAL    NOT NULL DEFAULT 1200.0,
    games_played   INTEGER NOT NULL DEFAULT 0,
    wins           INTEGER NOT NULL DEFAULT 0,
    top3_count     INTEGER NOT NULL DEFAULT 0,
    total_kills    INTEGER NOT NULL DEFAULT 0,
    total_minerals INTEGER NOT NULL DEFAULT 0,
    avg_survival   REAL    NOT NULL DEFAULT 0.0,
    last_played_at TEXT,
    UNIQUE(bot_id, season_id)
);
CREATE INDEX IF NOT EXISTS idx_br_season ON bot_ratings(season_id);
CREATE INDEX IF NOT EXISTS idx_br_rating ON bot_ratings(season_id, rating DESC);

-- 5. rating_history
CREATE TABLE IF NOT EXISTS rating_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id        INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    season_id     INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    game_id       TEXT    NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    rating_before REAL    NOT NULL,
    rating_after  REAL    NOT NULL,
    rating_delta  REAL    NOT NULL,
    final_rank    INTEGER NOT NULL,
    recorded_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rh_bot ON rating_history(bot_id, season_id);

-- 6. games
CREATE TABLE IF NOT EXISTS games (
    id            TEXT    PRIMARY KEY,
    status        TEXT    NOT NULL DEFAULT 'waiting',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at    TEXT,
    finished_at   TEXT,
    final_tick    INTEGER,
    end_reason    TEXT,
    winner_bot_id INTEGER REFERENCES bots(id) ON DELETE SET NULL,
    total_bots    INTEGER NOT NULL DEFAULT 0,
    seed          INTEGER,
    config_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_games_status     ON games(status);
CREATE INDEX IF NOT EXISTS idx_games_created_at ON games(created_at DESC);

-- 7. game_participants
CREATE TABLE IF NOT EXISTS game_participants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id             TEXT    NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    bot_id              INTEGER REFERENCES bots(id) ON DELETE SET NULL,
    bot_name            TEXT    NOT NULL,
    is_ai_filler        INTEGER NOT NULL DEFAULT 0,
    final_rank          INTEGER,
    final_score         REAL,
    kills               INTEGER NOT NULL DEFAULT 0,
    minerals_mined      INTEGER NOT NULL DEFAULT 0,
    rare_minerals_mined INTEGER NOT NULL DEFAULT 0,
    survival_ticks      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_gp_game_id ON game_participants(game_id);
CREATE INDEX IF NOT EXISTS idx_gp_bot_id  ON game_participants(bot_id);

-- 8. schema_version (현재 구현)
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
```

---

## 5. 주요 쿼리 패턴

### 5.1 시즌 리더보드 (ELO 기준)
```sql
SELECT br.bot_id, b.name AS bot_name, u.display_name AS owner,
       br.rating, br.peak_rating, br.games_played,
       br.wins, br.top3_count, br.total_kills, br.avg_survival,
       ROUND(CAST(br.wins AS REAL) / NULLIF(br.games_played, 0) * 100, 1) AS win_rate_pct
FROM bot_ratings br
JOIN bots  b ON b.id = br.bot_id
JOIN users u ON u.id = b.user_id
WHERE br.season_id = :season_id
  AND br.games_played >= 3
  AND b.is_active = 1
ORDER BY br.rating DESC
LIMIT 50;
```

### 5.2 봇 프로필 — 전역 통산 + 현재 시즌
```sql
-- 전역 통산 (bots)
SELECT b.id, b.name, b.wins, b.losses, b.games_played,
       ROUND(CAST(b.wins AS REAL) / NULLIF(b.games_played, 0) * 100, 1) AS career_win_rate
FROM bots b WHERE b.id = :bot_id;

-- 현재 시즌 (bot_ratings)
SELECT br.rating, br.peak_rating, br.wins, br.top3_count,
       br.total_kills, br.avg_survival, br.last_played_at
FROM bot_ratings br
JOIN seasons s ON s.id = br.season_id
WHERE br.bot_id = :bot_id AND s.is_active = 1;
```

### 5.3 레이팅 차트 데이터
```sql
SELECT rh.rating_after, rh.final_rank, rh.recorded_at
FROM rating_history rh
WHERE rh.bot_id = :bot_id AND rh.season_id = :season_id
ORDER BY rh.recorded_at ASC;
```

### 5.4 특정 봇의 최근 대전 이력
```sql
SELECT gp.final_rank, gp.final_score, gp.kills,
       gp.minerals_mined, gp.rare_minerals_mined, gp.survival_ticks,
       g.finished_at, g.end_reason, g.total_bots
FROM game_participants gp
JOIN games g ON g.id = gp.game_id
WHERE gp.bot_id = :bot_id
  AND g.status = 'finished'
ORDER BY g.finished_at DESC
LIMIT 20;
```

### 5.5 대전 결과 및 참가자 조회
```sql
SELECT gp.*, b.name AS bot_name_current, u.display_name
FROM game_participants gp
LEFT JOIN bots  b ON b.id = gp.bot_id
LEFT JOIN users u ON u.id = b.user_id
WHERE gp.game_id = :game_id
ORDER BY gp.final_rank ASC;
```

### 5.6 대전 종료 후 통계 업데이트
```sql
-- 1) 전역 누적 (bots)
UPDATE bots
SET wins         = wins + :win_delta,
    losses       = losses + :loss_delta,
    games_played = games_played + 1
WHERE id = :bot_id;

-- 2) 시즌 누적 (bot_ratings) — repository.py의 process_game_results() 참고
UPDATE bot_ratings
SET rating         = :new_rating,
    peak_rating    = MAX(peak_rating, :new_rating),
    games_played   = games_played + 1,
    wins           = wins + :win_delta,
    top3_count     = top3_count + :top3_delta,
    total_kills    = total_kills + :kills,
    total_minerals = total_minerals + :minerals_mined,
    avg_survival   = (avg_survival * games_played + :survival_ticks) / (games_played + 1),
    last_played_at = datetime('now')
WHERE bot_id = :bot_id AND season_id = :season_id;

-- 3) 레이팅 이력 (rating_history)
INSERT INTO rating_history
    (bot_id, season_id, game_id, rating_before, rating_after, rating_delta, final_rank)
VALUES
    (:bot_id, :season_id, :game_id, :rating_before, :rating_after, :delta, :rank);
```

---

## 6. 데이터 정합성 고려사항

### 6.1 봇 삭제 처리
- `bots.is_active = 0` 소프트 삭제 사용
- `game_participants.bot_id`는 `ON DELETE SET NULL` → 과거 대전 기록 보존
- `games.winner_bot_id`도 `ON DELETE SET NULL` 동일 처리

### 6.2 통계 이중화 일관성

| 통계 위치 | 범위 | 갱신 시점 | 표시 용도 |
|---|---|---|---|
| `bots.wins/losses/games_played` | 전역 통산 | 대전 완료 시 | 프로필, 봇 카드 |
| `bot_ratings.wins/top3_count/...` | 시즌 누적 | 대전 완료 시 | 리더보드, 시즌 통계 |

두 통계 모두 대전 완료 트랜잭션 내에서 함께 갱신해야 불일치 방지.

### 6.3 트랜잭션 범위 (대전 종료 시)
```
BEGIN TRANSACTION
  1. UPDATE games               SET status='finished', ...
  2. INSERT game_participants   (all bots, final_score 포함)
  3. UPDATE bots                SET wins/losses/games_played (전역, each bot)
  4. UPDATE bot_ratings         SET rating/wins/top3_count/... (시즌, each bot)
  5. INSERT rating_history      (each bot)
COMMIT
```

### 6.4 AI 필러봇 처리
- `game_participants.is_ai_filler = 1` + `bot_id = NULL`
- `bot_name`에 봇 이름 기록 (예: `AI_초식_00`)
- ELO 계산 시 AI 필러봇은 고정 레이팅(1200) 적용 (`src/arena/ranking/elo.py`)
- AI 필러봇은 `bot_ratings`, `rating_history`에 기록하지 않음

### 6.5 시즌 전환 처리
- 시즌 종료 시 `seasons.is_active = 0`, `ended_at` 기록
- 새 시즌 시작 시 신규 `seasons` 행 삽입; 봇들의 `bot_ratings`는 새 시즌 ID로 신규 생성 (이전 시즌 데이터 보존)
- `bots`의 전역 통계는 시즌 전환과 무관하게 계속 누적

---

## 7. 향후 확장 고려사항

### 7.1 refresh_tokens (인증 고도화 시)

현재 `auth_service.py`는 JWT 생성/검증만 구현하며 DB에 저장하지 않는다. 토큰 로그아웃(무효화)이나 다중 디바이스 세션 관리가 필요해지면 추가한다.

```sql
CREATE TABLE refresh_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT    NOT NULL UNIQUE,            -- SHA-256 해시
    issued_at   TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL,                   -- issued_at + 7일
    revoked     INTEGER NOT NULL DEFAULT 0          -- 0: 유효, 1: 취소됨
);
CREATE INDEX idx_rt_user_id    ON refresh_tokens(user_id);
CREATE INDEX idx_rt_token_hash ON refresh_tokens(token_hash);
```

### 7.2 리플레이 저장 (선택)

틱별 게임 상태를 저장하려면 (용량 주의 — 1게임당 최대 500틱):

```sql
CREATE TABLE game_replays (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id    TEXT    NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    tick       INTEGER NOT NULL,
    state_json TEXT    NOT NULL,                    -- TickBroadcast JSON
    UNIQUE(game_id, tick)
);
```

### 7.3 PostgreSQL 전환 시 주의사항

| SQLite | PostgreSQL |
|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` 또는 `BIGSERIAL` |
| `TEXT` (날짜) | `TIMESTAMPTZ` |
| `REAL` | `DOUBLE PRECISION` |
| `INTEGER` (bool) | `BOOLEAN` |
| `TEXT PRIMARY KEY` (UUID) | `UUID PRIMARY KEY DEFAULT gen_random_uuid()` |
| `PRAGMA journal_mode=WAL` | 불필요 (내장 MVCC) |
| `PRAGMA foreign_keys=ON` | 기본 활성화 |

---

## 8. 현재 구현 vs 설계 초안 차이점

| 항목 | 현재 구현 | 설계 초안 | 비고 |
|---|---|---|---|
| `seasons` 테이블 | `repository.py`에 구현됨 | 핵심 테이블로 명시 | 동일 |
| `bot_ratings` 구조 | `UNIQUE(bot_id, season_id)` + 시즌 통계 | 동일하게 반영 | 초안 v1에서 누락 → 수정 |
| `rating_history` | `repository.py`에 구현됨, 핵심 사용 | 핵심 테이블로 승격 | 초안 v1에서 선택 → 수정 |
| `game_participants.rare_minerals_mined` | `schema.py`에 없음 | 필수 추가 | 점수 검증 가능성 확보 |
| `game_participants.final_score` | 저장됨 | 권위 데이터로 명시 | 재계산 불가 명시 |
| `schema_version` 구조 | `version` 단일 컬럼 | 현재형/개선안 분리 표기 | 개선안은 호환 불가 변경 |
| `refresh_tokens` | 미구현 | Section 7(향후 확장)으로 이동 | 현재 요구사항 아님 |

---

*이 문서는 `src/arena/db/schema.py`, `src/arena/ranking/repository.py`, `src/arena/ranking/elo.py`, `src/arena/config.py`, `src/arena/server/schemas.py` 등을 기반으로 작성되었습니다.*

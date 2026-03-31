# DB 설계 초안 — AI Arena (LOA Backend)

> 작성일: 2026-03-31
> 최종 수정: 2026-03-31 (PostgreSQL 기반으로 전환)
> 현재 구현: SQLite (`src/arena/db/schema.py`, `src/arena/ranking/repository.py`) — 개발 단계
> **목표 환경: PostgreSQL 15+**
> **인증 방식: GCP Firebase Authentication**

---

## 0. 변경 이력

| 버전 | 주요 변경 |
|---|---|
| v1 (초안) | users/bots/games/game_participants 기본 축 작성 |
| v2 | bot_ratings를 `UNIQUE(bot_id, season_id)` 기반으로 재설계, seasons/rating_history 핵심 테이블로 승격, rare_minerals_mined 추가, final_score 권위 데이터 명시, schema_version 현재형/개선안 분리, refresh_tokens 제거 |
| v3 | **Firebase Auth 전환**: users에서 password_hash/salt 제거, firebase_uid 도입, 인증 플로우 재정의, refresh_tokens 완전 제거 |
| v4 | auth_provider 의미 정의(최초 가입 provider), role 권한 source of truth 명시(DB 기준), is_active 범위 선언(운영 정지 전용), username 설정 플로우 추가, Upsert 쿼리 last_login_at 누락 수정 |
| v5 (현재) | **PostgreSQL 전환**: 타입 체계 전면 교체 (BIGSERIAL/UUID/TIMESTAMPTZ/BOOLEAN/DOUBLE PRECISION/JSONB), SQLite PRAGMA 제거, `datetime('now')` → `NOW()`, `MAX()` → `GREATEST()` |

---

## 1. 인증 구조 개요 (Firebase Auth)

### 책임 분리 원칙

> **인증 정보는 Firebase가 관리하고, 우리 DB는 서비스용 사용자 프로필과 도메인 데이터만 관리한다.**

| 역할 | 담당 |
|---|---|
| 사용자 인증 (로그인, 비밀번호, OAuth) | Firebase Authentication |
| JWT 발급 및 refresh token 관리 | Firebase Authentication |
| 서비스 사용자 프로필 저장 | 우리 DB (`users` 테이블) |
| 봇, 대전, 랭킹 등 도메인 데이터 | 우리 DB (나머지 테이블) |

### 로그인 플로우 (Token Verify + User Sync)

```
1. 사용자가 Firebase Auth로 로그인 (이메일/Google/GitHub 등)
2. Firebase가 ID Token (JWT) 발급
3. 프론트엔드가 백엔드 API 요청 시 Authorization: Bearer <id_token> 헤더 포함
4. 백엔드가 Firebase Admin SDK로 ID Token 검증
5. 검증된 firebase_uid로 users 테이블 Upsert
   ├── 없으면: INSERT — auth_provider, last_login_at 포함 신규 생성
   └── 있으면: UPDATE — display_name, photo_url, email_verified, last_login_at 동기화
              (auth_provider는 최초 가입 값 보존, username은 이 단계에서 처리 안 함)
6. 이후 내부 요청은 users.id(정수 PK)로 처리
7. username 미설정 사용자는 별도 프로필 설정 API(PATCH /users/me)로 입력 유도
```

### 지원 인증 제공자 (`auth_provider` 값)

| 값 | 설명 |
|---|---|
| `password` | 이메일/비밀번호 |
| `google.com` | Google OAuth |
| `github.com` | GitHub OAuth |

---

## 2. 테이블 개요

| 테이블 | 분류 | 설명 |
|---|---|---|
| `users` | 핵심 | Firebase 계정과 연결된 서비스 사용자 프로필 |
| `bots` | 핵심 | 봇 코드 + **전역** 누적 통계 캐시 |
| `seasons` | 핵심 (랭킹) | 시즌 메타데이터 |
| `bot_ratings` | 핵심 (랭킹) | 봇별 **시즌** ELO 레이팅 및 통계 |
| `rating_history` | 핵심 (랭킹) | 대전별 레이팅 변화 이력 |
| `games` | 핵심 | 대전 메타데이터 |
| `game_participants` | 핵심 | 대전별 봇 참가 결과 |
| `schema_version` | 관리 | DB 마이그레이션 버전 추적 |

> `refresh_tokens`: Firebase Auth가 토큰 생명주기를 전담하므로 **완전히 제거**.

---

## 3. ERD (텍스트)

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

## 4. PostgreSQL 타입 선택 기준

| 용도 | PostgreSQL 타입 | 비고 |
|---|---|---|
| 자동 증가 PK | `BIGSERIAL` | 8바이트 정수, 대용량 대응 |
| FK 참조 정수 | `BIGINT` | BIGSERIAL PK와 타입 일치 |
| 게임 ID (UUID) | `UUID` | `gen_random_uuid()` 자동 생성 (PostgreSQL 13+) |
| 날짜/시각 | `TIMESTAMPTZ` | 타임존 포함, 기본값 `NOW()` |
| 불리언 | `BOOLEAN` | `TRUE/FALSE`, `DEFAULT TRUE/FALSE` |
| 소수점 수치 | `DOUBLE PRECISION` | ELO 레이팅, 점수 등 |
| 일반 정수 카운터 | `INTEGER` | 승패수, 킬수 등 |
| 짧은 문자열 | `TEXT` | PostgreSQL TEXT는 길이 제한 없음 |
| JSON 데이터 | `JSONB` | 인덱싱 가능, config_json/state_json |

---

## 5. 테이블 상세

---

### 5.1 `users`

Firebase Authentication과 연결된 **서비스 사용자 프로필** 테이블.
비밀번호·솔트 등 인증 자격증명은 저장하지 않는다. Firebase가 전담한다.

```sql
CREATE TABLE users (
    id             BIGSERIAL    PRIMARY KEY,
    firebase_uid   TEXT         NOT NULL UNIQUE,          -- Firebase Auth UID (인증 식별자)
    email          TEXT,                                   -- Firebase 계정 이메일 (동기화)
    email_verified BOOLEAN      NOT NULL DEFAULT FALSE,    -- Firebase 이메일 인증 여부
    username       TEXT         UNIQUE,                    -- 서비스 내 공개 별칭/슬러그 (선택)
    display_name   TEXT         NOT NULL,                  -- 화면 표시 이름 (Firebase displayName 동기화)
    photo_url      TEXT,                                   -- 프로필 이미지 URL (Firebase photoURL 동기화)
    auth_provider  TEXT,                                   -- 최초 가입 provider: password|google.com|github.com
    role           TEXT         NOT NULL DEFAULT 'user',   -- 서비스 권한: user|admin
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),    -- 프로필 마지막 동기화 시각
    last_login_at  TIMESTAMPTZ,                            -- 마지막 로그인 시각
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,     -- FALSE: 운영 정지 전용
    banned_reason  TEXT,                                   -- 정지 사유 (운영용)
    banned_at      TIMESTAMPTZ                             -- 정지 시각 (운영용)
);

CREATE INDEX idx_users_firebase_uid ON users(firebase_uid);
CREATE INDEX idx_users_username     ON users(username);
```

**컬럼별 역할**

| 컬럼 | 역할 |
|---|---|
| `firebase_uid` | Firebase Auth의 원본 식별자. 백엔드 토큰 검증 후 이 값으로 사용자를 찾는다 |
| `email` | Firebase 계정 이메일. 로그인 키가 아니라 표시/알림용 |
| `username` | 서비스 내 공개 별칭 (URL slug 등). 로그인 ID가 아님. 선택 입력 |
| `display_name` | 화면 표시 이름. Firebase `displayName`과 동기화 |
| `photo_url` | Firebase `photoURL`과 동기화 |
| `auth_provider` | **최초 가입 시** 사용한 Firebase 제공자. 이후 로그인에서 갱신하지 않는다 (가입 경로 추적 목적) |
| `role` | 서비스 내부 권한. **DB가 source of truth**. Firebase Custom Claims는 선택적 캐시로만 사용 |

> **`role` 권한 판단 원칙**: 권한 결정은 항상 `users.role` (DB) 기준으로 한다. Firebase Custom Claims에 role을 넣더라도 최종 판단 근거는 DB다. Claims와 DB가 엇갈릴 경우 DB 값을 우선한다.

> **`is_active` 범위 선언**: 현재 `is_active = FALSE`는 **운영 정지 전용**으로만 사용한다. 휴면·탈퇴·소프트 딜리트 등 다른 비활성 상태가 필요해지면 별도 컬럼(예: `status TEXT`)을 추가한다.

**비즈니스 규칙**
- 비밀번호·솔트는 저장하지 않는다. 인증은 Firebase에 위임.
- 최초 로그인 시: `firebase_uid` 기준 `INSERT`, `last_login_at`도 이 시점에 함께 기록
- 재방문 시: `last_login_at`, `display_name`, `photo_url`, `email_verified` `UPDATE` (동기화). `auth_provider`는 갱신하지 않음 (최초 가입 값 보존)
- `username`은 서비스 정책에 따라 선택. 최초 로그인 Upsert에는 포함되지 않으며, **별도 프로필 설정 API**에서 사용자가 직접 입력한다
- `email` 유니크는 강제하지 않음 (Firebase provider별 처리 방식 상이)

---

### 5.2 `bots`

봇 소스 코드와 **전역 누적** 통계를 저장한다.

> **통계 책임 구분**
> - `bots.wins / losses / games_played` — **전역 누적** (시즌에 무관한 통산 기록, 프로필/봇 카드 표시용)
> - `bot_ratings.wins / top3_count / ...` — **시즌 누적** (현재 시즌 기준 랭킹/리더보드 표시용)
>
> UI에서 "이번 시즌 승률"은 `bot_ratings`를 사용하고, "역대 통산 승패"는 `bots`를 사용한다.

```sql
CREATE TABLE bots (
    id           BIGSERIAL   PRIMARY KEY,
    user_id      BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT        NOT NULL,                   -- 봇 이름 (사용자 내 유일)
    code         TEXT        NOT NULL,                   -- 파이썬 소스코드 (최대 50KB)
    description  TEXT        NOT NULL DEFAULT '',
    version      INTEGER     NOT NULL DEFAULT 1,         -- 코드 수정 시 자동 증가
    is_active    BOOLEAN     NOT NULL DEFAULT TRUE,      -- FALSE: 소프트 삭제
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- 전역 누적 통계 (game_participants 기반 캐시, 시즌 무관)
    wins         INTEGER     NOT NULL DEFAULT 0,
    losses       INTEGER     NOT NULL DEFAULT 0,
    games_played INTEGER     NOT NULL DEFAULT 0,

    UNIQUE(user_id, name)
);

CREATE INDEX idx_bots_user_id        ON bots(user_id);
CREATE UNIQUE INDEX idx_bots_user_name ON bots(user_id, name);
```

**비즈니스 규칙**
- 코드 크기 제한: 50,000 bytes (`APIConfig.max_bot_code_size`)
- 코드 업데이트 시: `version += 1`, `updated_at` 갱신
- 소프트 삭제: `is_active = FALSE` (물리 삭제 없음)

---

### 5.3 `seasons`

랭킹 시즌 메타데이터를 저장한다. `bot_ratings`와 `rating_history`는 모두 시즌 단위로 관리된다.

```sql
CREATE TABLE seasons (
    id         BIGSERIAL   PRIMARY KEY,
    name       TEXT        NOT NULL UNIQUE,              -- 예: "Season 1", "2026 Spring"
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at   TIMESTAMPTZ,                              -- NULL: 진행 중
    is_active  BOOLEAN     NOT NULL DEFAULT TRUE         -- 활성 시즌은 1개만 허용
);
```

**비즈니스 규칙**
- 새 시즌 생성 시: 기존 활성 시즌의 `is_active = FALSE`, `ended_at` 기록 후 신규 삽입
- 활성 시즌(`is_active = TRUE`)은 항상 최대 1개 유지

---

### 5.4 `bot_ratings`

봇의 **시즌별** ELO 레이팅과 시즌 누적 통계를 저장한다. 한 봇은 시즌마다 1개의 행을 가진다.

```sql
CREATE TABLE bot_ratings (
    id             BIGSERIAL        PRIMARY KEY,
    bot_id         BIGINT           NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    season_id      BIGINT           NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    rating         DOUBLE PRECISION NOT NULL DEFAULT 1200.0,
    peak_rating    DOUBLE PRECISION NOT NULL DEFAULT 1200.0,
    games_played   INTEGER          NOT NULL DEFAULT 0,
    -- 시즌 누적 통계
    wins           INTEGER          NOT NULL DEFAULT 0,   -- 1위 횟수
    top3_count     INTEGER          NOT NULL DEFAULT 0,   -- 3위 이내 횟수
    total_kills    INTEGER          NOT NULL DEFAULT 0,
    total_minerals INTEGER          NOT NULL DEFAULT 0,
    avg_survival   DOUBLE PRECISION NOT NULL DEFAULT 0.0, -- 평균 생존 틱 (누적 평균)
    last_played_at TIMESTAMPTZ,

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

### 5.5 `rating_history`

대전별 레이팅 변화를 기록하는 **필수** 이력 테이블이다. 레이팅 차트, 최근 트렌드, 연승/연패 계산에 사용된다.

```sql
CREATE TABLE rating_history (
    id            BIGSERIAL        PRIMARY KEY,
    bot_id        BIGINT           NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    season_id     BIGINT           NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    game_id       UUID             NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    rating_before DOUBLE PRECISION NOT NULL,
    rating_after  DOUBLE PRECISION NOT NULL,
    rating_delta  DOUBLE PRECISION NOT NULL,              -- rating_after - rating_before
    final_rank    INTEGER          NOT NULL,
    recorded_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rh_bot ON rating_history(bot_id, season_id);
```

**사용처** (`src/arena/ranking/repository.py`)
- `get_rating_history()` — 이력 목록 조회
- `get_rating_chart_data()` — 레이팅 변화 차트 데이터
- `get_bot_stats()` — 최근 5경기 트렌드, 현재 연승/연패 계산

---

### 5.6 `games`

개별 대전의 메타데이터 및 결과를 저장한다.

```sql
CREATE TABLE games (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    status        TEXT        NOT NULL DEFAULT 'waiting', -- waiting|running|finished|error
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    final_tick    INTEGER,
    end_reason    TEXT,                                   -- max_ticks|last_standing|all_minerals_depleted
    winner_bot_id BIGINT      REFERENCES bots(id) ON DELETE SET NULL,
    total_bots    INTEGER     NOT NULL DEFAULT 0,
    seed          INTEGER,                                -- 맵 생성 시드 (재현용)
    config_json   JSONB                                   -- 직렬화된 GameConfig
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

### 5.7 `game_participants`

각 대전에서 참가한 봇별 결과 및 통계를 저장한다.

```sql
CREATE TABLE game_participants (
    id                  BIGSERIAL        PRIMARY KEY,
    game_id             UUID             NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    bot_id              BIGINT           REFERENCES bots(id) ON DELETE SET NULL,
                                                              -- AI 필러봇은 NULL
    bot_name            TEXT             NOT NULL,            -- 대전 당시 봇 이름 스냅샷
    is_ai_filler        BOOLEAN          NOT NULL DEFAULT FALSE,
    -- 결과 (게임 종료 후 기록)
    final_rank          INTEGER,
    final_score         DOUBLE PRECISION,                     -- 권위 데이터 (재계산 불가, 아래 참고)
    kills               INTEGER          NOT NULL DEFAULT 0,
    minerals_mined      INTEGER          NOT NULL DEFAULT 0,  -- 일반 + 희귀 합산
    rare_minerals_mined INTEGER          NOT NULL DEFAULT 0,  -- 희귀 광물만 별도 집계
    survival_ticks      INTEGER          NOT NULL DEFAULT 0
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

### 5.8 `schema_version`

DB 마이그레이션 버전을 추적한다.

```sql
CREATE TABLE schema_version (
    version    INTEGER     PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_version(version) VALUES (1) ON CONFLICT DO NOTHING;
```

---

## 6. 전체 DDL (초기화 스크립트)

```sql
-- gen_random_uuid() 사용을 위해 pgcrypto 또는 PostgreSQL 13+ 내장 함수 사용
-- PostgreSQL 13 미만이라면: CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. users (Firebase Auth 연동 프로필)
CREATE TABLE IF NOT EXISTS users (
    id             BIGSERIAL    PRIMARY KEY,
    firebase_uid   TEXT         NOT NULL UNIQUE,
    email          TEXT,
    email_verified BOOLEAN      NOT NULL DEFAULT FALSE,
    username       TEXT         UNIQUE,
    display_name   TEXT         NOT NULL,
    photo_url      TEXT,
    auth_provider  TEXT,
    role           TEXT         NOT NULL DEFAULT 'user',
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_login_at  TIMESTAMPTZ,
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    banned_reason  TEXT,
    banned_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users(firebase_uid);
CREATE INDEX IF NOT EXISTS idx_users_username     ON users(username);

-- 2. bots (전역 누적 통계 포함)
CREATE TABLE IF NOT EXISTS bots (
    id           BIGSERIAL   PRIMARY KEY,
    user_id      BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         TEXT        NOT NULL,
    code         TEXT        NOT NULL,
    description  TEXT        NOT NULL DEFAULT '',
    version      INTEGER     NOT NULL DEFAULT 1,
    is_active    BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    wins         INTEGER     NOT NULL DEFAULT 0,
    losses       INTEGER     NOT NULL DEFAULT 0,
    games_played INTEGER     NOT NULL DEFAULT 0,
    UNIQUE(user_id, name)
);
CREATE INDEX IF NOT EXISTS idx_bots_user_id        ON bots(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bots_user_name ON bots(user_id, name);

-- 3. seasons
CREATE TABLE IF NOT EXISTS seasons (
    id         BIGSERIAL   PRIMARY KEY,
    name       TEXT        NOT NULL UNIQUE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at   TIMESTAMPTZ,
    is_active  BOOLEAN     NOT NULL DEFAULT TRUE
);

-- 4. bot_ratings (시즌 누적 통계 포함)
CREATE TABLE IF NOT EXISTS bot_ratings (
    id             BIGSERIAL        PRIMARY KEY,
    bot_id         BIGINT           NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    season_id      BIGINT           NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    rating         DOUBLE PRECISION NOT NULL DEFAULT 1200.0,
    peak_rating    DOUBLE PRECISION NOT NULL DEFAULT 1200.0,
    games_played   INTEGER          NOT NULL DEFAULT 0,
    wins           INTEGER          NOT NULL DEFAULT 0,
    top3_count     INTEGER          NOT NULL DEFAULT 0,
    total_kills    INTEGER          NOT NULL DEFAULT 0,
    total_minerals INTEGER          NOT NULL DEFAULT 0,
    avg_survival   DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    last_played_at TIMESTAMPTZ,
    UNIQUE(bot_id, season_id)
);
CREATE INDEX IF NOT EXISTS idx_br_season ON bot_ratings(season_id);
CREATE INDEX IF NOT EXISTS idx_br_rating ON bot_ratings(season_id, rating DESC);

-- 5. rating_history
CREATE TABLE IF NOT EXISTS rating_history (
    id            BIGSERIAL        PRIMARY KEY,
    bot_id        BIGINT           NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    season_id     BIGINT           NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    game_id       UUID             NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    rating_before DOUBLE PRECISION NOT NULL,
    rating_after  DOUBLE PRECISION NOT NULL,
    rating_delta  DOUBLE PRECISION NOT NULL,
    final_rank    INTEGER          NOT NULL,
    recorded_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rh_bot ON rating_history(bot_id, season_id);

-- 6. games
CREATE TABLE IF NOT EXISTS games (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    status        TEXT        NOT NULL DEFAULT 'waiting',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    final_tick    INTEGER,
    end_reason    TEXT,
    winner_bot_id BIGINT      REFERENCES bots(id) ON DELETE SET NULL,
    total_bots    INTEGER     NOT NULL DEFAULT 0,
    seed          INTEGER,
    config_json   JSONB
);
CREATE INDEX IF NOT EXISTS idx_games_status     ON games(status);
CREATE INDEX IF NOT EXISTS idx_games_created_at ON games(created_at DESC);

-- 7. game_participants
CREATE TABLE IF NOT EXISTS game_participants (
    id                  BIGSERIAL        PRIMARY KEY,
    game_id             UUID             NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    bot_id              BIGINT           REFERENCES bots(id) ON DELETE SET NULL,
    bot_name            TEXT             NOT NULL,
    is_ai_filler        BOOLEAN          NOT NULL DEFAULT FALSE,
    final_rank          INTEGER,
    final_score         DOUBLE PRECISION,
    kills               INTEGER          NOT NULL DEFAULT 0,
    minerals_mined      INTEGER          NOT NULL DEFAULT 0,
    rare_minerals_mined INTEGER          NOT NULL DEFAULT 0,
    survival_ticks      INTEGER          NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_gp_game_id ON game_participants(game_id);
CREATE INDEX IF NOT EXISTS idx_gp_bot_id  ON game_participants(bot_id);

-- 8. schema_version
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER     PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO schema_version(version) VALUES (1) ON CONFLICT DO NOTHING;
```

---

## 7. 주요 쿼리 패턴

### 7.1 Firebase ID Token 검증 후 사용자 Upsert

```sql
-- 최초 가입(INSERT) + 재방문 동기화(UPDATE) 통합 처리
INSERT INTO users (
    firebase_uid, email, email_verified, display_name,
    photo_url, auth_provider, last_login_at, created_at, updated_at
)
VALUES (
    :uid, :email, :email_verified, :display_name,
    :photo_url, :provider, NOW(), NOW(), NOW()
)
ON CONFLICT(firebase_uid) DO UPDATE SET
    email          = EXCLUDED.email,
    email_verified = EXCLUDED.email_verified,
    display_name   = EXCLUDED.display_name,
    photo_url      = EXCLUDED.photo_url,
    last_login_at  = NOW(),
    updated_at     = NOW();
    -- auth_provider: 의도적으로 갱신하지 않음 (최초 가입 provider 보존)
    -- username:      Upsert 대상 아님 — 별도 프로필 설정 API에서 처리
```

> **정책 요약**
> - `last_login_at`: INSERT·UPDATE 모두 현재 시각으로 기록
> - `auth_provider`: INSERT 시에만 기록. 이후 로그인에서 변경하지 않음 (최초 가입 경로 보존)
> - `username`: 이 Upsert에 포함되지 않음. 최초 가입 후 별도 `PATCH /users/me` 요청으로 설정

### 7.2 firebase_uid로 내부 사용자 조회
```sql
SELECT id, username, display_name, role, is_active, banned_at
FROM users
WHERE firebase_uid = :firebase_uid;
```

### 7.3 시즌 리더보드 (ELO 기준)
```sql
SELECT br.bot_id, b.name AS bot_name, u.display_name AS owner,
       br.rating, br.peak_rating, br.games_played,
       br.wins, br.top3_count, br.total_kills, br.avg_survival,
       ROUND((br.wins::NUMERIC / NULLIF(br.games_played, 0)) * 100, 1) AS win_rate_pct
FROM bot_ratings br
JOIN bots  b ON b.id = br.bot_id
JOIN users u ON u.id = b.user_id
WHERE br.season_id = :season_id
  AND br.games_played >= 3
  AND b.is_active = TRUE
ORDER BY br.rating DESC
LIMIT 50;
```

### 7.4 봇 프로필 — 전역 통산 + 현재 시즌
```sql
-- 전역 통산 (bots)
SELECT b.id, b.name, b.wins, b.losses, b.games_played,
       ROUND((b.wins::NUMERIC / NULLIF(b.games_played, 0)) * 100, 1) AS career_win_rate
FROM bots b WHERE b.id = :bot_id;

-- 현재 시즌 (bot_ratings)
SELECT br.rating, br.peak_rating, br.wins, br.top3_count,
       br.total_kills, br.avg_survival, br.last_played_at
FROM bot_ratings br
JOIN seasons s ON s.id = br.season_id
WHERE br.bot_id = :bot_id AND s.is_active = TRUE;
```

### 7.5 레이팅 차트 데이터
```sql
SELECT rh.rating_after, rh.final_rank, rh.recorded_at
FROM rating_history rh
WHERE rh.bot_id = :bot_id AND rh.season_id = :season_id
ORDER BY rh.recorded_at ASC;
```

### 7.6 대전 종료 후 통계 업데이트
```sql
-- 1) 전역 누적 (bots)
UPDATE bots
SET wins         = wins + :win_delta,
    losses       = losses + :loss_delta,
    games_played = games_played + 1,
    updated_at   = NOW()
WHERE id = :bot_id;

-- 2) 시즌 누적 (bot_ratings)
UPDATE bot_ratings
SET rating         = :new_rating,
    peak_rating    = GREATEST(peak_rating, :new_rating),
    games_played   = games_played + 1,
    wins           = wins + :win_delta,
    top3_count     = top3_count + :top3_delta,
    total_kills    = total_kills + :kills,
    total_minerals = total_minerals + :minerals_mined,
    avg_survival   = (avg_survival * games_played + :survival_ticks) / (games_played + 1),
    last_played_at = NOW()
WHERE bot_id = :bot_id AND season_id = :season_id;

-- 3) 레이팅 이력
INSERT INTO rating_history
    (bot_id, season_id, game_id, rating_before, rating_after, rating_delta, final_rank)
VALUES
    (:bot_id, :season_id, :game_id, :rating_before, :rating_after, :delta, :rank);
```

---

## 8. 데이터 정합성 고려사항

### 8.1 봇 삭제 처리
- `bots.is_active = FALSE` 소프트 삭제 사용
- `game_participants.bot_id`는 `ON DELETE SET NULL` → 과거 대전 기록 보존
- `games.winner_bot_id`도 `ON DELETE SET NULL` 동일 처리

### 8.2 통계 이중화 일관성

| 통계 위치 | 범위 | 갱신 시점 | 표시 용도 |
|---|---|---|---|
| `bots.wins/losses/games_played` | 전역 통산 | 대전 완료 시 | 프로필, 봇 카드 |
| `bot_ratings.wins/top3_count/...` | 시즌 누적 | 대전 완료 시 | 리더보드, 시즌 통계 |

두 통계 모두 대전 완료 트랜잭션 내에서 함께 갱신해야 불일치 방지.

### 8.3 트랜잭션 범위 (대전 종료 시)
```
BEGIN;
  1. UPDATE games               SET status='finished', ...
  2. INSERT game_participants   (all bots, final_score 포함)
  3. UPDATE bots                SET wins/losses/games_played (전역, each bot)
  4. UPDATE bot_ratings         SET rating/wins/top3_count/... (시즌, each bot)
  5. INSERT rating_history      (each bot)
COMMIT;
```

### 8.4 AI 필러봇 처리
- `game_participants.is_ai_filler = TRUE` + `bot_id = NULL`
- `bot_name`에 봇 이름 기록 (예: `AI_초식_00`)
- ELO 계산 시 AI 필러봇은 고정 레이팅(1200) 적용
- AI 필러봇은 `bot_ratings`, `rating_history`에 기록하지 않음

### 8.5 사용자 계정 정지 처리
- `is_active = FALSE` + `banned_reason`, `banned_at` 기록
- 정지 사용자의 봇은 대전 참여 불가 (서비스 레이어에서 `users.is_active` 확인)
- 정지 해제 시: `is_active = TRUE`, `banned_reason/banned_at = NULL`

### 8.6 시즌 전환 처리
- 시즌 종료 시 `seasons.is_active = FALSE`, `ended_at = NOW()` 기록
- 새 시즌 시작 시 신규 `seasons` 행 삽입; 봇들의 `bot_ratings`는 새 시즌 ID로 신규 생성 (이전 시즌 데이터 보존)
- `bots`의 전역 통계는 시즌 전환과 무관하게 계속 누적

---

## 9. 향후 확장 고려사항

### 9.1 리플레이 저장 (선택)

틱별 게임 상태를 저장하려면 (용량 주의 — 1게임당 최대 500틱):

```sql
CREATE TABLE game_replays (
    id         BIGSERIAL PRIMARY KEY,
    game_id    UUID      NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    tick       INTEGER   NOT NULL,
    state_json JSONB     NOT NULL,
    UNIQUE(game_id, tick)
);
```

### 9.2 개발 환경(SQLite)과 프로덕션(PostgreSQL) 차이

개발 단계에서 SQLite를 사용할 경우 주의할 타입 매핑:

| PostgreSQL (목표) | SQLite (개발) | 비고 |
|---|---|---|
| `BIGSERIAL PRIMARY KEY` | `INTEGER PRIMARY KEY AUTOINCREMENT` | |
| `BIGINT` (FK) | `INTEGER` | |
| `UUID DEFAULT gen_random_uuid()` | `TEXT` (UUID 문자열 직접 생성) | |
| `TIMESTAMPTZ` | `TEXT` (ISO 8601) | |
| `BOOLEAN` | `INTEGER` (0/1) | |
| `DOUBLE PRECISION` | `REAL` | |
| `JSONB` | `TEXT` (JSON 문자열) | |
| `NOW()` | `datetime('now')` | |
| `GREATEST(a, b)` | `MAX(a, b)` (스칼라 불가, CASE 필요) | UPDATE SET 내 사용 주의 |
| `x::NUMERIC` | `CAST(x AS REAL)` | |

---

## 10. 현재 구현 vs 목표 설계 차이점

> **현재 구현**: 자체 JWT/PBKDF2 실험 코드 + SQLite (`src/arena/db/auth_service.py`, `schema.py`)
> **목표 설계**: Firebase Auth + PostgreSQL. 이 문서는 목표 설계 기준으로 작성됨.

| 항목 | 현재 구현 | 목표 설계 (이 문서) | 비고 |
|---|---|---|---|
| DB 엔진 | SQLite | **PostgreSQL 15+** | 전면 전환 |
| 인증 방식 | 자체 PBKDF2 + JWT | Firebase Authentication | 전면 전환 |
| `users.password_hash` | 있음 | **제거** | Firebase 위임 |
| `users.salt` | 있음 | **제거** | Firebase 위임 |
| `users.firebase_uid` | 없음 | **추가 (NOT NULL UNIQUE)** | 핵심 식별자 |
| `users.email` | 없음 | 추가 | Firebase 동기화 |
| `users.email_verified` | `INTEGER` 없음 | `BOOLEAN` 추가 | |
| `users.photo_url` | 없음 | 추가 | Firebase 동기화 |
| `users.auth_provider` | 없음 | 추가 | 최초 가입 경로 추적 |
| `users.role` | 없음 | 추가 | 서비스 권한 관리 |
| `users.is_active` | `INTEGER` | `BOOLEAN` | |
| `users.banned_*` | 없음 | 추가 | 운영 정지 관리 |
| `users.username` | 로그인 ID (필수) | 서비스 별칭 (선택) | 역할 변경 |
| `refresh_tokens` | 미구현 | **완전 제거** | Firebase가 대신 |
| `games.id` | `TEXT` (UUID 문자열) | `UUID` | |
| `games.config_json` | `TEXT` | `JSONB` | |
| `bots.is_active` | `INTEGER` | `BOOLEAN` | |
| `game_participants.is_ai_filler` | `INTEGER` | `BOOLEAN` | |
| `game_participants.final_score` | `REAL` | `DOUBLE PRECISION` | |
| `game_participants.rare_minerals_mined` | 없음 | **필수 추가** | 점수 검증 가능성 확보 |
| `rating_history` | `repository.py`에 구현, 핵심 사용 | 핵심 테이블로 승격 | 초안 v1에서 선택 → 수정 |
| `schema_version` | `version` 단일 컬럼 (SQLite) | `version PK + applied_at TIMESTAMPTZ` | |

---

*이 문서는 `src/arena/db/schema.py`, `src/arena/ranking/repository.py`, `src/arena/ranking/elo.py`, `src/arena/config.py`, `src/arena/server/schemas.py` 등을 기반으로 작성되었습니다.*
*목표 DB 환경: PostgreSQL 15+ / 인증: GCP Firebase Authentication*

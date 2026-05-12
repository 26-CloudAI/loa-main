# MockStocks Cloud Run DB Lock Issue

작성일: 2026-05-12

## 요약

Cloud Run 배포가 새로 진행될 때 MockStocks 게임 목록에서 이전 기록이 사라지고, 새로 생성되는 기본 게임 이름 번호가 계속 `1`로 표시되는 문제가 발생했다.

확인 결과 GCP/Cloud SQL 자체 장애가 아니라, MockStocks 서버의 PostgreSQL 초기화 과정이 `stock_games` 테이블 락을 얻지 못해 실패하고, 이후 앱이 DB 없이 기동하는 것이 직접 원인이다.

## 관찰된 증상

- 게임 목록 화면에서 `모의주식` 완료 기록이 보이지 않는다.
- 새 모의주식 게임 생성 시 자동 이름 번호가 증가하지 않고 계속 `1`로 시작한다.
- 배포 직후 또는 새 Cloud Run 리비전 기동 직후 증상이 반복된다.
- Cloud Run 서비스 자체는 Ready 상태이며 API 요청도 200 응답을 반환한다.

## Cloud Run 확인 결과

현재 Cloud Run 서비스 설정은 PostgreSQL 사용으로 잡혀 있다.

- 서비스: `ai-arena-server`
- 리전: `asia-northeast3`
- 최신 확인 리비전: `ai-arena-server-00076-5r5`
- `DB_TYPE=postgresql`
- `DB_HOST=10.114.0.3`
- Cloud SQL 연결: `knu-2026-sungjin0418:asia-northeast3:arena-db`

따라서 단순히 Cloud Run 환경변수에서 `DB_TYPE`이 빠져 SQLite로 뜬 문제는 아니다.

## 핵심 로그

최근 여러 리비전에서 같은 오류가 반복됐다.

```text
2026-05-12T02:20:16Z ERROR ai-arena-server-00076-5r5
MockStocks DB 초기화 실패, DB 없이 기동: canceling statement due to lock timeout
```

반복 확인된 리비전:

```text
ai-arena-server-00076-5r5  2026-05-12
ai-arena-server-00074-db2  2026-05-12
ai-arena-server-00072-lrt  2026-05-12
ai-arena-server-00070-5s9  2026-05-12
ai-arena-server-00068-r7j  2026-05-10
ai-arena-server-00067-7m9  2026-05-10
ai-arena-server-00063-x9d  2026-05-08
```

Traceback상 실패 위치는 MockStocks PostgreSQL schema 초기화 경로다.

```text
File "/app/src/stocks/server/app.py", line 147, in _init_repository
  db_conn = init_db()
File "/app/src/stocks/db/schema.py", line 145, in init_db
  return _init_postgresql()
File "/app/src/stocks/db/schema.py", line 196, in _init_postgresql
  cur.execute(...)
psycopg2.errors.LockNotAvailable: canceling statement due to lock timeout
```

해당 코드는 `CREATE TABLE/CREATE INDEX` 루프 이후 아래 migration DDL을 실행한다.

```sql
ALTER TABLE stock_games ADD COLUMN IF NOT EXISTS owner_uid TEXT;
ALTER TABLE stock_games ADD COLUMN IF NOT EXISTS name TEXT;
```

## 왜 게임 기록과 번호가 같이 깨지는가

MockStocks 앱은 startup에서 DB 초기화가 실패하면 예외를 로깅하고 서버는 계속 띄운다.

대상 코드:

- `backend/MockStocks/src/stocks/server/app.py`
- `lifespan()` 내부

현재 동작:

```python
except Exception as e:
    registry._repo = None
    logger.exception("MockStocks DB 초기화 실패, DB 없이 기동: %s", e)
```

이후 두 기능이 모두 `registry._repo`에 의존한다.

### 1. 기록 목록

`GET /stocks/api/games/history`는 repo가 없으면 빈 배열을 반환한다.

```python
repo = registry._repo
if repo is None:
    return []
```

따라서 프론트엔드는 DB 오류를 알 수 없고, 기록이 실제로 사라진 것처럼 보인다.

### 2. 자동 이름 번호

새 게임 생성 시 기본 이름 번호는 DB count로 계산한다.

```python
next_index = registry._repo.count_games_by_owner(uid) + 1 if registry._repo else 1
```

repo가 없으면 항상 `1`이 된다.

## 왜 DB 초기화가 실패하는가

직접 원인은 PostgreSQL lock timeout이다.

추정되는 발생 메커니즘:

1. 기존 Cloud Run 인스턴스가 `/stocks/api/games/history` 같은 조회 요청을 처리한다.
2. MockStocks PostgreSQL 연결은 `autocommit=False`로 생성된다.
3. `SELECT * FROM stock_games ...` 같은 조회가 실행된다.
4. 조회 후 `commit()` 또는 `rollback()`이 호출되지 않는다.
5. PostgreSQL 세션이 `idle in transaction` 상태로 남을 수 있다.
6. 이 트랜잭션이 `stock_games`에 대한 lock을 유지한다.
7. 새 Cloud Run 리비전이 startup 중 `ALTER TABLE stock_games ...`를 실행한다.
8. `ALTER TABLE`은 컬럼이 이미 존재해도 강한 테이블 lock을 잡으려 한다.
9. 기존 세션의 열린 트랜잭션 때문에 lock을 얻지 못한다.
10. `DB_LOCK_TIMEOUT_MS=5000` 설정 때문에 5초 후 실패한다.
11. MockStocks 서버는 DB 없이 기동한다.

즉 배포 중 구 리비전과 신 리비전이 겹쳐 떠 있는 상황에서, 운영 요청의 열린 read transaction과 startup migration DDL이 충돌하는 구조다.

## GCP 문제인가?

현재 근거 기준으로는 GCP 자체 장애로 보기 어렵다.

- Cloud Run 서비스는 정상 Ready 상태다.
- Cloud SQL private IP와 Cloud Run env 설정은 존재한다.
- 오류는 네트워크 연결 실패가 아니라 PostgreSQL의 `LockNotAvailable`이다.
- 같은 앱 코드 경로에서 여러 리비전마다 반복된다.

따라서 원인은 인프라보다 애플리케이션 DB 트랜잭션/마이그레이션 설계에 가깝다.

## 단기 해결 계획

### 1. PostgreSQL read transaction 누수 방지

MockStocks repository의 PostgreSQL 연결에서 read-only query 후 트랜잭션이 열린 채로 남지 않도록 한다.

선택지:

- PostgreSQL 연결을 `autocommit=True`로 변경한다.
- 또는 repository query helper에서 SELECT 이후 명시적으로 `commit()` 또는 `rollback()`을 수행한다.

현 구조에서는 repository가 장기 공유 연결 하나를 들고 있으므로, 운영 안정성 측면에서 `autocommit=True`가 가장 단순한 단기 대응이다.

#### autocommit 적용 위치

`schema.py`에는 두 개의 연결 생성 경로가 있다.

- `get_connection()` — `conn.autocommit = False`로 명시 설정 (line 126)
- `_init_postgresql()` — psycopg2 기본값(autocommit=False)으로 별도 연결 생성 후 반환 (line 179~205)

`app.py`의 `lifespan`은 `init_db()` → `_init_postgresql()`이 반환한 conn을 `StockGameRepository`에 직접 넘긴다. `get_connection()`은 repo가 사용하지 않으므로, **`get_connection()`만 수정해서는 문제가 해결되지 않는다.**

수정 위치: `backend/MockStocks/src/stocks/db/schema.py`의 `_init_postgresql()` 함수 끝, `conn.commit()` 이후에 `conn.autocommit = True`를 추가한다.

```python
    conn.commit()
    conn.autocommit = True          # SELECT 후 트랜잭션이 열린 채로 남는 것 방지
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn
```

#### SELECT 후 트랜잭션을 열린 채로 남기는 메서드

`autocommit=True`로 바꾸지 않을 경우 아래 `game_repo.py` 메서드들에 각각 `commit()`/`rollback()`이 필요하다.

- `get_game()` (line 86)
- `get_recent_games()` (line 115)
- `count_games_by_owner()` (line 122)
- `get_finished_games()` (line 131)
- `get_participants()` (line 219)

### 2. startup DDL 최소화

매 startup마다 아래 DDL을 실행하지 않도록 한다.

```sql
ALTER TABLE stock_games ADD COLUMN IF NOT EXISTS owner_uid TEXT;
ALTER TABLE stock_games ADD COLUMN IF NOT EXISTS name TEXT;
```

`SCHEMA_SQL_POSTGRESQL` DDL(`schema.py:60~74`)에 `owner_uid TEXT`와 `name TEXT`가 이미 포함되어 있다. 운영 DB 및 배포 대상 환경에서 두 컬럼이 이미 존재하는지 확인하거나 1회 migration을 먼저 수행한 뒤, `ALTER TABLE` 블록(`schema.py:196~201`)을 제거하는 것이 가장 빠른 방법이다.

운영 DB 컬럼 존재 여부 확인 쿼리:

```sql
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'public'
AND table_name = 'stock_games'
AND column_name IN ('owner_uid', 'name');
```

두 컬럼이 모두 조회되면 `ALTER TABLE` 두 줄을 제거한다. 이후 장기적으로는 아래 방향으로 전환한다.

- schema migration을 앱 startup이 아니라 별도 관리 작업으로 분리

### 3. DB 초기화 실패 시 조용히 빈 배열 반환하지 않기

`/stocks/api/games/history`에서 repo가 없을 때 `[]` 대신 `503 Service Unavailable`을 반환한다.

목표:

- 데이터가 사라진 것처럼 보이는 착시 제거
- 배포/운영 중 DB 장애를 프론트와 로그에서 명확히 감지

### 4. 새 게임 생성도 DB 없으면 실패시키기

현재는 repo가 없어도 인메모리 게임을 생성한다. 이 경우 배포/재시작 시 기록이 사라지고 번호도 틀어진다.

운영 환경에서는 MockStocks DB repo가 없으면 `POST /stocks/api/games`를 `503`으로 막는 것이 안전하다.

## 장기 해결 계획

### 1. 앱 startup migration 제거

운영 서버 startup에서 DDL을 실행하지 않는 구조로 바꾼다.

권장 방향:

- migration 스크립트 또는 Cloud Run Job으로 schema 변경을 별도 실행
- 앱 startup은 schema 검증 또는 연결 확인만 수행

### 2. 요청 단위 DB 연결 관리

현재 구조는 repo가 앱 lifespan 동안 단일 DB 연결을 공유한다.

장기적으로는 다음 중 하나로 전환한다.

- 요청/작업 단위 connection 생성 후 close
- connection pool 도입
- repository method 단위 transaction boundary 명확화

### 3. DB 상태 health check 추가

`/health`는 현재 앱 기동 여부만 확인한다. 별도 endpoint 또는 health payload에 DB 상태를 포함하면 배포 후 문제를 빠르게 감지할 수 있다.

예:

```json
{
  "status": "ok",
  "mockstocks_db": "connected"
}
```

단, Cloud Run startup probe 대상 health와 운영 진단용 health는 분리하는 것이 안전하다.

## 검증 계획

수정 후 아래를 확인한다.

1. 로컬 SQLite 테스트 통과
   - `backend/MockStocks/tests/test_stock_game_repository.py`
   - `backend/MockStocks/tests/test_game_session_db_persistence.py`
   - `backend/MockStocks/tests/test_startup_db_failure.py`

2. PostgreSQL smoke test
   - Cloud SQL Auth Proxy 또는 실제 PostgreSQL 연결 환경에서 `backend/MockStocks/tests/test_pg_smoke.py` 실행

3. Cloud Run 배포 후 로그 확인
   - `MockStocks DB 초기화 실패` 로그가 없어야 한다.
   - `canceling statement due to lock timeout` 로그가 없어야 한다.

4. E2E 확인
   - 모의주식 게임 생성
   - 게임 종료 후 목록에 기록 표시
   - 새 게임 생성 시 이름 번호 증가
   - 새 Cloud Run 리비전 배포 후에도 기록 유지
   - 배포 후 새 게임 번호가 기존 기록 기준으로 증가

## 임시 운영 대응

코드 수정 전 임시로는 새 리비전을 다시 배포하면 DB 초기화가 성공할 수도 있다. 하지만 기존 인스턴스의 열린 트랜잭션과 startup DDL이 다시 충돌할 수 있으므로 재발 가능성이 높다.

근본 대응은 PostgreSQL transaction boundary 정리와 startup migration 제거다.

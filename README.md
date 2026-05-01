# League of Agents (LOA)

> 부분 관측 기반 AI Agents 전략 게임 플랫폼

사용자가 직접 작성한 Python 봇 로직을 제출하고, 여러 봇이 상호작용하는 과정을 실시간으로 관전할 수 있는 온라인 AI Agent 학습 플랫폼.

---

## 제품 목표

- 사용자 봇 코드를 안전하게 실행할 수 있는 신뢰성 있는 환경
- 전략 다양성이 살아있는, 결정적이고 재현 가능한 시스템
- 개발자를 위한 로그 분석 및 피드백 기능
- 향후 확장 가능한 모듈형 아키텍처

---

## 빠른 시작


## 프로젝트 구조

```
loa-main/
├── backend/
│   ├── run_server.py              # FastAPI 서버 진입점
│   ├── run_simulation.py          # 콘솔 시뮬레이션 (의존성 0)
│   ├── run_simulation_log.py      # 로그 남기는 시뮬레이션
│   ├── run_sandbox_game.py        # Docker 통합 시뮬레이션
│   ├── bots/                      # 예시 봇 3종
│   │   ├── herbivore.py           # 초식동물 (채굴 중심)
│   │   ├── mad_dog.py             # 미친개 (전투 중심)
│   │   └── camper.py              # 존버 (생존/방어 중심)
│   ├── src/arena/
│   │   ├── config.py              # 모든 밸런스 수치 (단일 파일 관리)
│   │   ├── engine.py              # 게임 엔진 코어 (틱 루프)
│   │   ├── grid.py                # 100×100 맵, 광물 배치/재생
│   │   ├── zone.py                # 자기장 3단계 수축
│   │   ├── vision.py              # 5×5 시야 → state JSON
│   │   ├── types.py               # Action enum, Bot, Mineral 등
│   │   ├── bot_interface.py       # 봇 추상 인터페이스
│   │   ├── sandbox/               # Docker 격리 실행
│   │   ├── server/                # FastAPI + Redis + WebSocket
│   │   ├── db/                    # SQLite DB + Repository
│   │   ├── auth/                  # PBKDF2 + JWT 인증
│   │   └── ranking/               # 멀티플레이어 ELO 랭킹
│   └── tests/                     # 테스트 (164개)
└── frontend/                      # React + Canvas (개발 예정)
```

---

## 기술 스택

| 레이어 | 기술 | 외부 의존성 |
|--------|------|-------------|
| 게임 엔진 | Python 3.11+ (표준 라이브러리) | 없음 |
| 인증 | PBKDF2 + HMAC-SHA256 JWT | 없음 |
| DB | SQLite3 (WAL 모드) | 없음 |
| 랭킹 | 멀티플레이어 ELO | 없음 |
| API 서버 | FastAPI + Uvicorn | `pip install fastapi uvicorn` |
| 상태 동기화 | Redis Pub/Sub (인메모리 폴백 포함) | `pip install redis` (선택) |
| 샌드박스 | Docker (docker-py) | `pip install docker` + Docker 데몬 |
| 프론트엔드 | React + Canvas API | 별도 빌드 환경 (개발 예정) |

> 게임 엔진, DB, 인증, 랭킹은 Python 표준 라이브러리만으로 동작합니다.

---

## 게임 규칙

### 맵

- 크기: 100 × 100
- 초기 광물: 300개 (중앙 30×30 고밀도 구역)
- 희귀 광물: 군락(cluster) 방식 5개, 반경 6, 군락당 10개
- 광물 재생: 채굴 후 50틱 대기, 재생 확률 15%

### 봇

- 최대 봇 수: 100
- 초기 에너지: 250
- 시야: 5×5 (반경 2), 부분 관측

### 행동 & 비용

| 행동 | 에너지 비용 |
|------|------------|
| STAY | -1 |
| MOVE_* (4방향) | -2 |
| MINE | -3 |
| ATTACK_* (4방향) | -5 |
| SHIELD | -3 |

### 전투

- 공격 피해: 25
- 실드 피해 감소: 100% (완전 방어)

### 채굴 & 점수

- 일반 광물: +5점, +10 에너지
- 희귀 광물: +20점, +25 에너지
- 생존 보너스: tick당 +0.1
- 킬 보너스: +30
- 가드 보너스: +10 (실드로 상대 공격 방어 성공 시)

**최종 점수** = 광물 점수 + 생존 tick × 0.1 + 킬 수 × 30 + 방어 성공 × 10

### 자기장

| Phase | 틱 구간 | 수축 | 피해 |
|-------|---------|------|------|
| 1 | 0 ~ 75 | 없음 | - |
| 2 | 76 ~ 150 | 4틱마다 1칸 | 3 |
| 3 | 151 ~ 200 | 2틱마다 1칸 | 3 |

최대 틱: **200**

### 경기 종료 조건

- 생존 봇 1개 남았을 때 (섬멸 승리)
- 최대 틱(200) 도달 시 점수 승리

### Tick 처리 순서

1. 행동 수집 → 2. 이전 실드 제거 → 3. 실드 적용 → 4. 공격 해석
→ 5. 이동 해석 → 6. 채굴 해석 → 7. 대기 비용 적용 → 8. 자기장 피해
→ 9. 사망 처리 → 10. 생존 tick 갱신 → 11. 광물 재생 → 12. tick/자기장 갱신 → 13. 종료 확인

---

## 봇 작성 가이드

```python
def action(state: dict) -> str:
    tick          = state["tick"]
    my_bot        = state["my_bot"]        # id, position, energy, score, shield_active
    vision        = state["vision"]        # 5×5 grid (부분 관측)
    zone_boundary = state["zone_boundary"]
    leaderboard   = state["leaderboard"]   # 상위 3명

    # 반환값: STAY / MOVE_UP / MOVE_DOWN / MOVE_LEFT / MOVE_RIGHT
    #          MINE / ATTACK_UP / ATTACK_DOWN / ATTACK_LEFT / ATTACK_RIGHT / SHIELD
    return "STAY"
```

---

## 예시 봇 전략

| 봇 | 전략 |
|----|------|
| Herbivore | 시야와 기억을 활용한 채굴 중심, 적 최우선 도주 |
| Mad Dog | 시야 내 적 최우선 추적 및 공격, 중앙 장악과 기회주의적 파밍 |
| Camper | 외곽 시계 방향 순찰 파밍, 에너지 변화로 자기장/피격을 추론해 도주하는 생존 중심 |

---

## API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/games` | 게임 생성 + 봇 등록 + 시작 |
| GET | `/api/games` | 활성 게임 목록 |
| GET | `/api/games/{id}` | 게임 정보 |
| GET | `/api/games/{id}/result` | 게임 결과 |
| DELETE | `/api/games/{id}` | 게임 강제 종료 |
| WS | `/ws/games/{id}` | 실시간 관전 |
| GET | `/health` | 헬스체크 |

---

## 현재 구현 상태

| 영역 | 상태 |
|------|------|
| 게임 엔진 (틱루프, 전투, 채굴, 자기장) | ✅ 완료 |
| 예시 봇 3종 | ✅ 완료 |
| 로컬 시뮬레이션 실행기 | ✅ 완료 |
| FastAPI 서버 + WebSocket 관전 | ✅ 완료 |
| Docker 샌드박스 모듈 | ✅ 구조 완료 (서버와 미연결) |
| ELO 랭킹 엔진 | ✅ 구현 완료 (API 미연결) |
| DB 스키마 + Repository | ✅ 구현 완료 (API 미연결) |
| 인증 (PBKDF2 + JWT) | ✅ 구현 완료 (mock 사용 중) |
| 봇 CRUD API | ❌ 미구현 |
| DB ↔ API 연결 | ❌ 미연결 |
| 서버 → Sandbox 전환 | ❌ 현재 in-process 사용 중 |
| 경기 이력 영속화 | ❌ 미구현 |
| 프론트엔드 | ❌ 미구현 |

---

## 로드맵

### 단기 — 핵심 연결 작업

현재 각 레이어(엔진, DB, 인증, 샌드박스, 랭킹)는 개별적으로 구현되어 있지만 서로 연결되지 않은 상태다. 단기 목표는 이 레이어들을 실제로 연결해 동작하는 서비스를 완성하는 것이다.

#### 1. 봇 CRUD API 구현

**목표**: 사용자가 봇 코드를 등록·조회·수정·삭제할 수 있는 API 엔드포인트를 제공한다.

- `POST /api/bots` — 봇 코드 등록 (코드 크기 검증, `action(state)` 함수 존재 여부 확인)
- `GET /api/bots` — 내 봇 목록 조회
- `GET /api/bots/{id}` — 봇 상세 조회
- `PUT /api/bots/{id}` — 봇 코드 업데이트 (버전 자동 증가)
- `DELETE /api/bots/{id}` — 봇 삭제

관련 파일: `server/app.py` (엔드포인트 추가), `db/bot_repo.py` (이미 구현됨, 연결만 필요)

#### 2. 인증 정책 확정 및 실제 인증 연결

**목표**: 현재 개발용 mock 인증(`mock_auth/`)을 실제 인증 시스템으로 교체한다.

현재 상태: `mock_auth/router.py`가 임시 인메모리 사용자 스토어 기반으로 동작 중이며, Firebase 전환 포인트가 주석으로 명시되어 있음.

결정 필요 사항:
- **JWT 직접 운영**: 현재 `auth/auth_service.py`(PBKDF2 + HMAC-SHA256) 그대로 사용
- **Firebase Auth 연동**: `mock_auth/router.py`의 `verify_token` 의존성만 Firebase Admin SDK로 교체
- **OAuth 추가 여부**: GitHub/Google 소셜 로그인 포함 여부

관련 파일: `server/app.py` (mock_auth 라우터 교체), `auth/auth_service.py`, `db/user_repo.py`

#### 3. DB ↔ API 연결 (경기 이력 영속화)

**목표**: 게임 세션이 종료될 때 결과를 DB에 저장하여 경기 이력을 영속화한다.

현재 상태: `db/game_repo.py`, `db/bot_repo.py`가 완성되어 있지만 `server/game_session.py`의 게임 종료 흐름과 연결되지 않음.

구현 내용:
- 게임 종료 시 `games` 테이블에 결과(우승자, 최종 틱, 종료 사유) 기록
- `game_participants` 테이블에 각 봇의 최종 순위, 점수, 킬 수, 채굴량, 생존 틱 기록
- 봇의 `wins` / `losses` / `games_played` 카운터 갱신

관련 파일: `server/game_session.py` (종료 콜백 추가), `db/game_repo.py`, `db/bot_repo.py`

#### 4. 서버 실행 경로를 Sandbox로 전환

**목표**: API를 통해 제출된 사용자 봇 코드를 현재의 in-process `exec` 방식 대신 Docker 컨테이너에서 격리 실행한다.

현재 상태: `server/app.py`의 `InProcessBot`이 같은 프로세스에서 `exec(code)`로 봇을 실행 중. `sandbox/` 모듈은 완성되어 있지만 서버에서 사용하지 않음.

구현 내용:
- `server/app.py`의 `InProcessBot` → `sandbox/docker_adapter.py`의 `DockerBotAdapter`로 교체
- Docker 네트워크(`ai-arena-net`) 생성 및 컨테이너 풀 초기화를 서버 lifespan에 추가
- 컨테이너 리소스 제한 적용 (CPU 0.1코어, 메모리 50MB, PID 32, 읽기 전용 루트 fs, capabilities 전체 제거)
- 봇 응답 타임아웃 100ms, 실패 시 `STAY` fallback

관련 파일: `server/app.py`, `sandbox/docker_adapter.py`, `sandbox/pool.py`, `sandbox/container_manager.py`

---

### 중기 — 플랫폼 완성

단기 작업으로 기본 서비스가 동작하면, 중기에는 사용자가 실제로 활용할 수 있는 플랫폼으로 완성한다.

#### 5. ELO 랭킹 API 연결

**목표**: 게임이 종료될 때마다 자동으로 참가 봇들의 ELO 레이팅을 갱신하고, 리더보드를 조회할 수 있는 API를 제공한다.

현재 상태: `ranking/elo.py`(멀티플레이어 ELO 계산), `ranking/repository.py`(시즌/레이팅/히스토리 DB)가 완성되어 있지만 게임 종료 흐름과 미연결.

구현 내용:
- 게임 종료 시 참가자 최종 순위를 기반으로 `calculate_multiplayer_elo()` 호출
- `ranking/repository.py`에 레이팅 변경 기록 저장
- `GET /api/leaderboard` — 전체 랭킹 조회
- `GET /api/bots/{id}/rating` — 봇 레이팅 이력 조회
- 티어 시스템: Iron(~800) / Bronze / Silver / Gold(1200) / Platinum / Diamond / Master / Grandmaster(2000+)

관련 파일: `server/game_session.py`, `ranking/elo.py`, `ranking/repository.py`

#### 6. 프론트엔드 구현

**목표**: 실시간 경기 관전과 봇 코드 제출을 위한 웹 인터페이스를 제공한다.

현재 상태: `frontend/frontend.md`에 스펙만 존재. 실제 구현 없음.

구현 내용:
- **관전 뷰**: Canvas API 기반 100×100 맵 실시간 렌더링 (봇 위치, 광물, 자기장, 리더보드)
- **봇 에디터**: 코드 편집기 + 제출 UI
- **대시보드**: 내 봇 목록, 전적, ELO 레이팅, 경기 이력
- **리더보드**: 전체 랭킹, 티어별 필터

WebSocket(`/ws/games/{id}`)에서 받는 tick 브로드캐스트 데이터를 실시간으로 Canvas에 반영.

#### 7. 리플레이 도구

**목표**: 종료된 경기를 다시 돌려볼 수 있는 리플레이 기능을 제공한다.

현재 상태: `backend/log_replay.html`이 기본 구현으로 존재.

구현 내용:
- 경기 전체 틱 로그를 DB 또는 파일에 저장
- `GET /api/games/{id}/replay` — 틱 로그 조회 API
- `log_replay.html` 또는 프론트엔드 내 리플레이 플레이어 확장

#### 8. 운영 모니터링 강화

**목표**: 서버와 경기 상태를 안정적으로 관찰할 수 있는 기반을 마련한다.

구현 내용:
- 콘솔 출력 → 구조화 JSON 로깅 전환
- `/health` 엔드포인트 확장 (활성 게임 수, 컨테이너 풀 상태, Redis 연결 상태)
- 컨테이너 실행 실패, 타임아웃, 비정상 종료에 대한 알림 구조 설계

---

### 장기 — 확장 기능

플랫폼이 안정화된 후 게임성과 생태계를 확장한다.

#### 9. LLM 해설 연동

각 경기의 주요 이벤트(킬, 광물 경합, 자기장 피해)를 LLM이 실시간 또는 사후에 해설하는 기능. 관전 경험을 풍부하게 한다.

#### 10. PvE 보스 / RL 기반 봇

강화학습으로 훈련된 고성능 봇을 플랫폼에 도입한다. 사용자 봇의 도전 대상이 되는 보스 봇 모드(PvE)를 제공한다.

#### 11. 확장 게임 모드

- 팀전 모드: 다수 봇이 팀을 이뤄 협력
- 모의 주식 모드 / 하네스 모드: 새로운 승리 조건과 자원 시스템
- 자원 전달 행동, 고급 지형 시스템

---

## 미결정 사항

| 항목 | 선택지 |
|------|--------|
| API 경로 샌드박스 의무화 시점 | 단기 전환 vs 알파 출시 후 |
| 인증 모델 | JWT 직접 운영 / Firebase Auth / OAuth 추가 |
| 봇 코드 제출 방식 | 경기 단위 즉시 제출 vs 영구 자산으로 관리 후 참가 |
| Redis 의존성 | 배포 필수 요소 vs 인메모리 폴백으로 선택 유지 |
| 경기 이력 영속화 | v1.0 필수 / v1.1 마일스톤 |

---

## 브랜치 전략

```
main        ← 안정 버전 (테스트 전부 통과한 것만 머지)
├── develop ← 개발 통합 브랜치
    ├── feature/xxx  ← 기능 개발
    ├── fix/xxx      ← 버그 수정
    └── refactor/xxx ← 리팩토링
```

커밋 메시지 형식: `feat:` / `fix:` / `test:` / `refactor:`

PR 머지 전 `pytest tests/ -v` 전체 통과 필수.

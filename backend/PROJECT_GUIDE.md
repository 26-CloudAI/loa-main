# AI Arena — 프로젝트 유지보수 가이드

## 기술 스택 요약

| 레이어 | 기술 | 역할 | 외부 의존성 |
|--------|------|------|-------------|
| 게임 엔진 | Python 3.11+ (표준 라이브러리) | 틱 루프, 전투, 채굴, 자기장 | 없음 |
| 인증 | PBKDF2 + HMAC-SHA256 JWT | 비밀번호 해싱, 토큰 발급 | 없음 |
| DB | SQLite3 (WAL 모드) | 유저, 봇 코드, 게임 기록 | 없음 |
| 랭킹 | 멀티플레이어 ELO | 시즌별 레이팅, 리더보드 | 없음 |
| API 서버 | FastAPI + Uvicorn | REST + WebSocket | `pip install fastapi uvicorn` |
| 상태 동기화 | Redis Pub/Sub | 틱 브로드캐스팅, 인메모리 폴백 | `pip install redis` (선택) |
| 샌드박스 | Docker (docker-py) | 유저 봇 격리 실행 | `pip install docker` + Docker 데몬 |
| 프론트엔드 | React + Canvas API | 관전 대시보드, 코드 에디터 | 별도 빌드 환경 |

**핵심 설계 원칙**: 게임 엔진, DB, 인증, 랭킹은 Python 표준 라이브러리만으로 동작합니다. `pip install` 없이 `python run_simulation.py`로 즉시 실행 가능합니다.


## 폴더 구조

```
ai-arena/
├── pyproject.toml                # 프로젝트 설정 + 의존성 정의
├── run_simulation.py             # 콘솔 시뮬레이션 (의존성 0)
├── run_simulation_log.py         # 콘솔 시뮬레이션 (로그 남음)
├── run_sandbox_game.py           # Docker 통합 시뮬레이션
├── run_server.py                 # FastAPI 서버 시작
│
├── src/
│   └── arena/
│       ├── __init__.py
│       ├── config.py             # 모든 밸런스 수치 (한 파일에서 관리)
│       ├── types.py              # Action enum, Bot, Mineral, Position 등
│       ├── engine.py             # 게임 엔진 코어 (틱 루프)
│       ├── grid.py               # 100×100 맵, 광물 배치/재생
│       ├── zone.py               # 자기장 3단계 수축
│       ├── vision.py             # 5×5 시야 → state JSON
│       ├── bot_interface.py      # 봇 추상 인터페이스
│       │
│       ├── sandbox/              # Docker 격리 실행
│       │   ├── config.py         # CPU/메모리/네트워크 제한값
│       │   ├── wrapper_template.py  # 컨테이너 내부 HTTP 서버
│       │   ├── container_manager.py # 단일 컨테이너 라이프사이클
│       │   ├── docker_adapter.py    # BotInterface 구현 (HTTP 통신)
│       │   └── pool.py              # 게임 세션 전체 컨테이너 관리
│       │
│       ├── server/               # FastAPI + Redis + WebSocket
│       │   ├── config.py         # Redis, WS, API 설정
│       │   ├── schemas.py        # REST/WS 메시지 스키마
│       │   ├── redis_manager.py  # StateStore + PubSub (인메모리 폴백 포함)
│       │   ├── game_session.py   # 엔진 실행 + 브로드캐스팅 연결
│       │   ├── ws_manager.py     # 관전 클라이언트 연결 관리
│       │   └── app.py            # FastAPI 앱 (엔드포인트 정의)
│       │
│       ├── db/                   # SQLite 데이터베이스
│       │   ├── schema.py         # 테이블 정의 + 마이그레이션
│       │   ├── user_repo.py      # 유저 CRUD
│       │   ├── bot_repo.py       # 봇 코드 CRUD + 검증
│       │   └── game_repo.py      # 게임 기록 + 참가자
│       │
│       ├── auth/                 # 인증
│       │   └── auth_service.py   # PBKDF2 해싱 + JWT + AuthService
│       │
│       └── ranking/              # ELO 랭킹
│           ├── elo.py            # 멀티플레이어 ELO 계산
│           └── repository.py     # 시즌/레이팅/히스토리 DB
│
├── bots/                         # 콜드스타트 봇 3종
│   ├── herbivore.py              # 초식동물 (채굴 전용)
│   ├── mad_dog.py                # 미친개 (전투 전용)
│   └── camper.py                 # 존버 (회피 후 후반 진입)
│
└── tests/                        # 테스트 (164개)
    ├── conftest.py               # 공통 픽스처
    ├── test_engine_unittest.py   # 엔진 코어 (29개)
    ├── test_sandbox.py           # 샌드박스 (13개)
    ├── test_server.py            # 서버 (24개)
    ├── test_db_auth.py           # DB + 인증 (44개)
    ├── test_ranking.py           # 랭킹 (34개)
    └── test_edge_cases.py        # 엣지케이스 + 통합 (20개)
```


## 로컬 실행 가이드

### 1단계: 엔진만 테스트 (의존성 0)

```bash
# 클론
git clone https://github.com/<your-repo>/ai-arena.git
cd ai-arena

# 콘솔 시뮬레이션 (봇 5개로 한 판)
python run_simulation.py

# 봇 수, 시드 변경
python run_simulation.py --bots 12 --seed 99

# 전체 테스트 실행
python -m tests.test_engine_unittest
python -m tests.test_db_auth
python -m tests.test_ranking
python -m tests.test_edge_cases

# 한 번에 전체 테스트 (pytest 설치 시)
pip install pytest
pytest tests/ -v
```

### 2단계: API 서버 실행

```bash
pip install fastapi uvicorn

# 인메모리 모드 (Redis 불필요)
python run_server.py

# Redis 모드
pip install redis
python run_server.py --redis

# 다른 포트
python run_server.py --port 9000

# API 문서 확인
# 브라우저에서 http://localhost:8080/docs
```

### 3단계: Docker 샌드박스 테스트

```bash
# Docker 데몬이 실행 중이어야 함
pip install docker

# 봇 3개로 격리 실행
python run_sandbox_game.py --bots 3

# 악성 봇(무한루프) 포함 테스트
python run_sandbox_game.py --bots 3 --malicious

# 샌드박스 단위 테스트 (Docker 없이 동작)
python -m tests.test_sandbox
```


## Git 관리 가이드

### .gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/

# DB
*.db
*.sqlite3

# 환경
.env
.venv/
venv/

# IDE
.vscode/
.idea/
*.swp

# Docker
docker-compose.override.yml

# OS
.DS_Store
Thumbs.db
```

### 브랜치 전략

```
main              ← 안정 버전 (테스트 전부 통과한 것만 머지)
├── develop       ← 개발 통합 브랜치
│   ├── feature/frontend-phaser    ← 기능 개발
│   ├── feature/boss-ai-ppo        ← 기능 개발
│   ├── fix/attack-cost-death      ← 버그 수정
│   └── refactor/db-postgresql     ← 리팩토링
```

**규칙**:
- `main`에 직접 push 금지. 항상 PR로 머지.
- PR 머지 전 `pytest tests/ -v` 전체 통과 필수.
- 커밋 메시지 형식: `feat: 보스 AI PvE 모드 추가` / `fix: 공격 비용 사망 시 데미지 무효화` / `test: 동시 킬 엣지케이스 추가`

### 초기 셋업 (GitHub에 올리기)

```bash
cd ai-arena

git init
git add .
git commit -m "feat: AI Arena v1.0 — 엔진 + 샌드박스 + 서버 + DB + 랭킹"

git remote add origin https://github.com/<your-repo>/ai-arena.git
git branch -M main
git push -u origin main

# develop 브랜치 생성
git checkout -b develop
git push -u origin develop
```


## 수정이 잦을 파일들

| 상황 | 수정할 파일 |
|------|-------------|
| 밸런스 조정 (에너지, 데미지 등) | `src/arena/config.py` |
| 새 행동 추가 (예: TELEPORT) | `src/arena/types.py` → `engine.py` → `sandbox/wrapper_template.py` |
| DB 스키마 변경 | `src/arena/db/schema.py` |
| 새 API 엔드포인트 | `src/arena/server/app.py` |
| ELO 공식 튜닝 | `src/arena/ranking/elo.py` |
| 콜드스타트 봇 전략 수정 | `bots/herbivore.py`, `mad_dog.py`, `camper.py` |
| Docker 리소스 제한 변경 | `src/arena/sandbox/config.py` |


## 테스트 작성 규칙

```python
# tests/ 안에 test_*.py 파일 추가
# 파일 상단에 프로젝트 경로 추가
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# unittest.TestCase 상속
class TestNewFeature(unittest.TestCase):
    def test_something(self):
        # given
        engine = GameEngine([DummyBot("a"), DummyBot("b")], config=small_cfg(), seed=42)
        # when
        engine.process_tick()
        # then
        self.assertEqual(engine.tick, 1)
```

**새 기능 추가 시**: 해당 기능의 테스트를 먼저 작성하고, 테스트가 실패하는 것을 확인한 뒤, 구현합니다.


## 프로덕션 전환 시 변경 포인트

| 항목 | 현재 | 프로덕션 |
|------|------|----------|
| DB | SQLite (파일 1개) | PostgreSQL + SQLAlchemy |
| 비밀번호 해싱 | PBKDF2 (표준 라이브러리) | bcrypt (`pip install bcrypt`) |
| JWT | 자체 구현 (HMAC) | PyJWT (`pip install PyJWT`) |
| Redis | 인메모리 폴백 | Redis 서버 필수 |
| 프론트엔드 | JSX 아티팩트 | Vite + React 빌드 |
| 시크릿 키 | 서버 시작 시 랜덤 생성 | 환경 변수 (.env) |
| 로깅 | 콘솔 출력 | 구조화 로깅 (JSON) |

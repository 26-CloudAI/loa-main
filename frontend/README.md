# League of Agents (LOA) - 프론트엔드 PRD

> **버전**: 1.1  
> **작성일**: 2026-04-03  
> **최종 수정**: 2026-04-03 (포트·테스트 계정·인증 경계·MVP 관전 범위·엣지케이스 보완)  
> **대상 독자**: 프론트엔드 개발자  
> **백엔드 기준**: loa-backend MVP (FastAPI + WebSocket + SQLite)

---

## 1. 제품 개요

**League of Agents (LOA)**는 사용자가 Python 봇 코드를 제출하면, 해당 봇들이 100×100 격자 맵에서 자원 채굴·전투·생존을 겨루는 AI 배틀 아레나 플랫폼이다.

### 1.1 핵심 사용자 목표

| 사용자 유형 | 목표 |
|---|---|
| 봇 개발자 | Python 코드를 작성·제출하고 경기 결과를 확인한다 |
| 관전자 | 진행 중인 게임을 실시간으로 구경하고 리더보드를 추적한다 |

### 1.2 프론트엔드 범위 (MVP)

- 인증 (로그인/로그아웃/프로필)
- 게임 생성 (봇 코드 제출)
- 게임 목록 (활성 게임 조회)
- 실시간 관전 (Canvas 기반 게임 렌더링)
- 게임 결과 조회

---

## 2. 기술 스택 및 제약

| 항목 | 결정 사항 |
|---|---|
| 백엔드 API | `http://localhost:8080` (REST + WebSocket) |
| 인증 방식 | Bearer JWT (헤더: `Authorization: Bearer <token>`) |
| 실시간 통신 | WebSocket (`ws://localhost:8080/ws/games/{game_id}`) |
| 렌더링 | Canvas API (100×100 그리드) |

> **포트 참고**: `run_server.py` 의 기본 포트가 `8080` 이다 (`--port` 옵션으로 변경 가능). 환경변수(`VITE_API_BASE` 등)로 관리하면 배포 환경과 분리하기 쉽다.

---

## 3. 화면 및 기능 명세

---

### 3.1 인증 (Auth)

#### 3.1.1 로그인 화면

**경로**: `/login`

**기능 요건**

- 이메일·비밀번호 입력 필드
- 로그인 버튼 → `POST /auth/login` 호출
- 응답의 `access_token`을 로컬 스토리지(또는 메모리)에 저장
- 로그인 성공 시 `/games` 로 리다이렉트
- 실패 시 에러 메시지 표시

**API**

```
POST /auth/login
Body: { "email": string, "password": string }
Response: {
  "access_token": string,
  "token_type": "bearer",
  "expires_in": 3600,
  "user": { "id", "username", "display_name", "email", "role" }
}
```

**개발용 테스트 계정**

| 이메일 | 비밀번호 |
|---|---|
| alice@arena.dev | alice1234 |
| bob@arena.dev | bob1234 |
| carol@arena.dev | carol1234 |

---

#### 3.1.2 현재 인증 적용 범위 (백엔드 실제 기준)

> **중요**: 현재 백엔드는 `/auth/*` 라우터에만 토큰 검증이 적용된다.  
> `/api/games`, `/ws/games/{game_id}` 는 인증 의존성이 **없다**.

| 엔드포인트 | 인증 필요 여부 |
|---|---|
| `POST /auth/login` | 불필요 (로그인 자체) |
| `GET /auth/me` | **필요** (`Bearer` 헤더) |
| `POST /auth/logout` | **필요** (`Bearer` 헤더) |
| `POST /api/games` | 불필요 (현재 백엔드 기준) |
| `GET /api/games` | 불필요 |
| `GET /api/games/{id}` | 불필요 |
| `GET /api/games/{id}/result` | 불필요 |
| `WS /ws/games/{game_id}` | 불필요 |

**프론트엔드 구현 지침**: 로그인 여부와 무관하게 게임 목록·관전·결과 화면은 접근 가능하게 구현한다. 로그인 상태이면 헤더에 토큰을 포함해 보내도 무방하지만, 서버가 이를 강제하지 않으므로 401 처리 로직을 과도하게 구현할 필요가 없다.

---

#### 3.1.3 전역 헤더 (로그인 후)

**기능 요건**

- `GET /auth/me` 로 현재 사용자 정보 표시
- 사용자 이름 + 역할 뱃지 (`user` / `admin`) 표시
- 로그아웃 버튼 → `POST /auth/logout` 호출 후 토큰 삭제 및 `/login` 리다이렉트

---

### 3.2 게임 목록 화면

**경로**: `/games`

**기능 요건**

- `GET /api/games` 를 주기적으로 폴링(예: 3초)하여 활성 게임 목록 표시
- 각 게임 카드에 표시할 정보:
  - `game_id` (앞 8자리 축약)
  - `status` 상태 뱃지: `waiting` / `running` / `finished`
  - `current_tick` / 최대 200
  - `alive_bots` / `total_bots`
- **관전하기** 버튼 → `/games/{game_id}/watch` 로 이동
- **새 게임 만들기** 버튼 → `/games/new` 로 이동
- 게임 없을 때 빈 상태 메시지 표시

**API**

```
GET /api/games
Response: GameInfo[]
```

**GameInfo 구조**

```json
{
  "game_id": "uuid",
  "status": "waiting|running|finished|error",
  "current_tick": 45,
  "total_bots": 4,
  "alive_bots": 3,
  "bot_ids": ["user_bot1", "AI_초식_00", ...]
}
```

---

### 3.3 게임 생성 화면

**경로**: `/games/new`

**기능 요건**

1. **봇 코드 에디터**
   - Python 문법 하이라이팅 지원 (CodeMirror 또는 Monaco Editor 권장)
   - 최대 50KB 실시간 용량 표시 및 초과 시 경고
   - 기본 템플릿 제공 (아래 참조)

2. **봇 이름 입력** (게임 내 표시용 ID)

3. **게임 옵션 패널**

| 옵션 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| AI로 빈 슬롯 채우기 | Toggle | ON | `fill_with_ai: true` |
| 최소 봇 수 | Number (2~100) | 4 | `min_bots` |
| 틱 간격 (속도) | Slider (0.01~1.0초) | 0.05 | `tick_interval` |
| 시드 (재현용) | Number (선택) | null | `seed` |

4. **게임 시작 버튼**
   - `POST /api/games` 호출
   - **요청 중 버튼 비활성화** (중복 제출 방지 — 서버가 막아주지 않으므로 프론트에서 반드시 처리)
   - 성공 시 `/games/{game_id}/watch` 로 이동
   - 실패 시 버튼 재활성화 + 에러 메시지 표시

5. **유효성 검사**
   - 봇 코드 비어있으면 제출 불가
   - 50KB 초과 시 제출 불가

**기본 코드 템플릿**

```python
def action(state: dict) -> str:
    """
    state 구조:
      - state["tick"]: 현재 틱 (int)
      - state["my_bot"]["position"]: [x, y]
      - state["my_bot"]["energy"]: 현재 에너지
      - state["my_bot"]["score"]: 현재 점수
      - state["vision"]["grid"]: 5x5 시야 배열
        ("empty", "mineral", "mineral_rare", "bot_enemy", "ME", "wall", "zone")
      - state["zone_boundary"]: 생존 구역 경계
      - state["leaderboard"]: [{"rank", "id", "score"}, ...]
    
    반환값 (str):
      "STAY", "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT",
      "MINE", "ATTACK_UP", "ATTACK_DOWN", "ATTACK_LEFT", "ATTACK_RIGHT", "SHIELD"
    """
    return "STAY"
```

**API**

```
POST /api/games
Body: {
  "bots": [{ "bot_id": string, "code": string }],
  "tick_interval": number,
  "fill_with_ai": boolean,
  "min_bots": number,
  "seed": number | null
}
Response: GameInfo
```

---

### 3.4 실시간 관전 화면

**경로**: `/games/{game_id}/watch`

이 화면이 MVP의 핵심이다. WebSocket으로 실시간 상태를 수신하여 Canvas에 렌더링한다.

**진입 시 상태 처리**

| 진입 시 게임 상태 | 처리 방법 |
|---|---|
| `running` | 정상 WebSocket 연결 → 현재 틱부터 렌더링 |
| `finished` | WebSocket 연결 없이 바로 `GET /api/games/{id}/result` 호출 후 종료 모달 표시 |
| `waiting` | "게임 시작 대기 중..." 표시 후 WebSocket 대기 |
| `error` / 404 | "게임을 찾을 수 없습니다." 메시지 + 게임 목록 링크 |

---

#### 3.4.1 Canvas 렌더링

**맵 구조**: 100×100 그리드. 각 셀을 픽셀로 렌더링 (권장 셀 크기: 6~8px → 600~800px 캔버스)

**렌더링 레이어 (뒤→앞 순서)**

| 레이어 | 내용 |
|---|---|
| 배경 | 어두운 단색 그리드 |
| 존 경계 | 빨간 반투명 오버레이 (`zone_boundary` 범위 밖) |
| 광물 | 일반 광물: 노란색 점, 희귀 광물: 밝은 주황색 큰 점 |
| 봇 | 원으로 표시, 봇 ID 축약 라벨 |

**봇 표현**

- 색상: 봇 ID 기반 해시로 고유 색상 부여 (매 틱마다 동일 색상 유지)
- 에너지바: 봇 원 아래 작은 녹색 바 (`energy / 100`)
- 사망 시 (`alive: false`): 회색으로 변경 후 1틱 뒤 제거 (MVP — 페이드아웃 연출은 Phase 2)

**Zone (존) 시각화**

```
zone_boundary 값 = 맵 가장자리에서 얼마나 안쪽까지 위험한가
위험 구역 = x < zone_boundary || x >= (100 - zone_boundary)
           || y < zone_boundary || y >= (100 - zone_boundary)
```

- 위험 구역: 빨간 반투명 오버레이 (opacity 0.25)
- 존 경계선: 밝은 빨간색 테두리

---

#### 3.4.2 WebSocket 연결

```javascript
const ws = new WebSocket(`ws://localhost:8080/ws/games/${gameId}`);

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  switch (msg.type) {
    case "game_start":
      // msg.data.game_id, msg.data.bot_ids
      // 봇 목록 초기화, 색상 매핑
      break;
    case "tick":
      // msg.data.tick, msg.data.bots[], msg.data.minerals[]
      // msg.data.zone_boundary, msg.data.alive_count
      // msg.data.leaderboard[]
      // → Canvas 재렌더링
      break;
    case "event":
      // msg.data.event_type: "kill" | "mine_success" | "death" | "zone_damage"
      // msg.data.actor_id, msg.data.target_id, msg.data.detail
      // → 이벤트 로그에 추가
      break;
    case "game_end":
      // msg.data.reason, msg.data.rankings[]
      // → 결과 모달 표시
      break;
  }
};
```

**tick 데이터 구조**

```json
{
  "type": "tick",
  "data": {
    "tick": 45,
    "bots": [
      { "id": "bot_id", "x": 50, "y": 50, "energy": 75, "score": 123.4, "alive": true, "shield_active": false }
    ],
    "minerals": [
      { "x": 40, "y": 50, "rare": false },
      { "x": 41, "y": 51, "rare": true }
    ],
    "zone_boundary": 5,
    "alive_count": 3,
    "leaderboard": [
      { "rank": 1, "id": "bot_1", "score": 500.2 },
      { "rank": 2, "id": "bot_2", "score": 450.1 },
      { "rank": 3, "id": "bot_3", "score": 320.5 }
    ]
  }
}
```

---

#### 3.4.3 관전 화면 레이아웃

```
┌─────────────────────────────────────────────────────────────┐
│  [◀ 게임 목록]    LOA - 게임 관전    게임 ID: abcd1234     │
├──────────────────────────────────┬──────────────────────────┤
│                                  │  틱: 45 / 200            │
│                                  │  생존: 3 / 4             │
│         Canvas (게임 맵)         ├──────────────────────────┤
│         100×100 그리드           │  리더보드                 │
│                                  │  #1 bot_1  500.2pt       │
│                                  │  #2 bot_2  450.1pt       │
│                                  │  #3 bot_3  320.5pt       │
│                                  ├──────────────────────────┤
│                                  │  이벤트 로그              │
│                                  │  [틱45] bot_1 → bot_3 킬 │
│                                  │  [틱44] bot_2 광물 채굴   │
│                                  │  [틱43] bot_3 존 피해     │
├──────────────────────────────────┴──────────────────────────┤
│  연결 상태: RUNNING   WebSocket: 연결됨                      │
└─────────────────────────────────────────────────────────────┘
```

**컨트롤 패널 (Phase 1 MVP)**

| 요소 | 동작 |
|---|---|
| 연결 상태 뱃지 | `WAITING` / `RUNNING` / `FINISHED` / `DISCONNECTED` |
| WebSocket 상태 | 연결됨 / 재연결 중 / 연결 끊김 |

> **Phase 2 이후**: 재생/일시정지, 속도 선택(0.5x/1x/2x/4x)은 백엔드 WebSocket이 서버 측 속도(`tick_interval`)로 제어하므로, 클라이언트 렌더링 스킵 배율 구현은 MVP 이후로 미룬다.

**이벤트 로그 패널**

- 최근 50개 이벤트 표시 (오래된 것은 자동 제거)
- 이벤트 타입별 색상:

| 이벤트 | 색상 |
|---|---|
| `kill` | 빨간색 |
| `mine_success` | 노란색 |
| `death` | 회색 |
| `zone_damage` | 주황색 |

---

#### 3.4.4 게임 종료 모달

`game_end` 메시지 수신 시 Canvas 위에 오버레이로 표시

**표시 내용**

- 종료 사유 (`reason`):
  - `last_standing` → "최후의 1봇 생존!"
  - `max_ticks` → "최대 틱(200) 도달"
  - `all_minerals_depleted` → "모든 광물 소진"
- 최종 순위표 (`rankings` 배열)

```
순위 | 봇 이름       | 점수   | 킬 | 채굴 | 생존 틱
#1   | user_bot1    | 542.3  |  3 |  12 |  200
#2   | AI_초식_00   | 430.1  |  0 |  18 |  180
#3   | AI_미친개_01 | 310.5  |  2 |   5 |  150
#4   | AI_존버_02   | 100.2  |  0 |   2 |   80
```

- **닫기** 버튼 → 모달 닫고 결과 화면 계속 표시
- **게임 목록으로** 버튼 → `/games`

---

### 3.5 게임 결과 화면

**경로**: `/games/{game_id}/result`

게임 종료 후 별도로 접근 가능한 결과 페이지.

**기능 요건**

- `GET /api/games/{game_id}/result` 호출
- 게임이 아직 진행 중이면 "게임 진행 중입니다." 메시지 + 관전 링크
- 종료 시 순위표 전체 표시

**API**

```
GET /api/games/{game_id}/result
Response: {
  "game_id": string,
  "reason": "last_standing|max_ticks|all_minerals_depleted",
  "final_tick": number,
  "rankings": [
    {
      "rank": number,
      "id": string,
      "score": number,
      "kills": number,
      "minerals_mined": number,
      "survival_ticks": number,
      "is_ai_filler": boolean
    }
  ]
}
```

---

### 3.6 서버 상태 표시 (선택, 관리자용)

**경로**: `/health` (헤더에 상태 표시 또는 별도 페이지)

```
GET /health
Response: { "status": "ok", "active_games": 2, "total_spectators": 15 }
```

---

## 4. 게임 규칙 참고 (UI 설명용)

관전 화면 또는 튜토리얼 팝업에 게임 규칙을 표시할 때 사용한다.

### 4.1 봇 액션

| 액션 | 에너지 소모 | 설명 |
|---|---|---|
| `STAY` | 1 | 제자리 대기 |
| `MOVE_*` | 2 | 상하좌우 이동 |
| `MINE` | 3 | 현재 위치 광물 채굴 |
| `ATTACK_*` | 5 | 인접 방향 공격 (25 데미지) |
| `SHIELD` | 3 | 이번 틱 방어 (피해 50% 감소) |

### 4.2 점수 계산

| 항목 | 점수 |
|---|---|
| 일반 광물 채굴 | +15pt |
| 희귀 광물 채굴 | +40pt |
| 킬 | +10pt |
| 생존 보너스 | 틱당 +0.1pt |

### 4.3 Zone (링 오브 파이어)

| 구간 | 동작 |
|---|---|
| 틱 0~75 | 존 없음 (자유 탐색) |
| 틱 76~150 | 20틱마다 1칸씩 축소, 존 밖 -3 에너지/틱 |
| 틱 151~200 | 10틱마다 1칸씩 축소, 존 밖 -3 에너지/틱 |

---

## 5. 라우팅 구조

```
/login                      → 로그인 (이미 로그인 상태면 /games 로 리다이렉트)
/games                      → 게임 목록 (인증 불필요 — 공개)
/games/new                  → 게임 생성 (인증 불필요 — 공개)
/games/:game_id/watch       → 실시간 관전 (인증 불필요 — 공개)
/games/:game_id/result      → 게임 결과 (인증 불필요 — 공개)
```

> 현재 백엔드는 `/api/*`, `/ws/*` 에 인증을 강제하지 않는다.  
> 로그인 기능은 사용자 식별용으로 제공하되, 비로그인 상태에서도 모든 화면에 접근 가능하도록 구현한다.

---

## 6. 에러 처리

| 상황 | 처리 방법 |
|---|---|
| 토큰 만료 / `GET /auth/me` 401 | 로컬 토큰 삭제 후 로그인 상태 초기화 (다른 화면은 계속 사용 가능) |
| 이미 로그인 상태에서 `/login` 접근 | `/games` 로 즉시 리다이렉트 |
| WebSocket 연결 끊김 | 재연결 시도 (최대 3회, 지수 백오프), 실패 시 에러 배너 |
| 이미 종료된 게임으로 watch 진입 | `GET /api/games/{id}` 로 상태 확인 후 `finished` 이면 바로 결과 모달 표시 |
| 게임 없음 404 | "게임을 찾을 수 없습니다." 메시지 + 목록 링크 |
| 게임 생성 중 중복 제출 | 제출 버튼 비활성화로 방지 (3.3 항목 참고) |
| 코드 50KB 초과 | 제출 버튼 비활성화 + 인라인 경고 |
| 서버 오류 500 | 토스트 알림 표시 |

---

## 7. 우선순위 및 구현 순서

| 단계 | 기능 | 이유 |
|---|---|---|
| Phase 1 | 로그인, 전역 헤더, 라우팅 | 사용자 식별 기반 기능(내 봇 구분 등)의 출발점이며, 이후 Firebase 인증 전환 시 보호 라우트 추가가 용이 |
| Phase 2 | 게임 목록, 게임 생성 | 게임 생성 없이 관전 불가 |
| Phase 3 | 관전 화면 (Canvas + WebSocket) | 핵심 UX |
| Phase 4 | 게임 결과 화면, 이벤트 로그 | 경험 완성 |

---

## 8. 향후 확장 (MVP 이후)

### Phase 2 (관전 화면 고도화)

- **재생/일시정지**: WebSocket 수신은 유지, Canvas 렌더링 토글
- **속도 선택**: 0.5x / 1x / 2x / 4x 렌더링 스킵 배율
- **봇 사망 페이드아웃**: 회색 변경 후 애니메이션 제거
- **이벤트 로그 고급 필터**: 이벤트 타입별 토글

### Phase 3 (플랫폼 확장)

- **봇 관리**: 봇 목록 조회, 코드 버전 관리 (백엔드 Bot CRUD API 완성 후)
- **Firebase 인증**: Google/GitHub OAuth 로그인 (현재 Mock JWT)
- **인증 강제**: Firebase 전환 후 `/api/games` 등에 인증 의존성 추가 시 프론트 보호 라우트 적용
- **글로벌 리더보드**: ELO 기반 시즌 랭킹
- **게임 리플레이**: 틱별 재생 (녹화 데이터 저장 필요)
- **LLM 해설**: 경기 이벤트 자동 해설

# BR2 보안 강화 — 수정 파일 기록

Codex adversarial review(critical) 대응: BR2(`/battleroyale2`)가 유저 봇 코드를 game-server
Pod에서 직접 `exec`(in-process)하던 RCE 경로를, 기존 배틀로얄/모의주식과 동일하게 격리된
**bot-runner** 실행으로 전환. 인증/owner·WS 토큰은 main(`23eafff`, `4ccb09b`)이 이미 구현했고,
여기서는 **봇 실행 격리(critical RCE 차단)** 만 추가한다.

브랜치: `seongjin-kube` · 작업 시작 2026-05-27

---

## Phase 0 — origin/main 동기화 (2026-05-27)
- `git merge origin/main` (클린 머지, 충돌 0). main의 BR2 인증/owner + Godot WS 토큰 흡수.
  (이 단계는 본인 코드 수정 아님 — 머지 커밋 `061fa4b`.)

## Phase 1 — BR2 봇 실행 bot-runner 격리 (2026-05-27)

### 신규 파일
- `backend/BattleRoyale2/server/remote_bot.py`
  — `RemoteBattleRoyale2BotAdapter`. bot-runner `/run`(mode=battleroyale2)을 호출해 봇을 격리
    실행. get_action→action dict, choose_spawn(phase)→좌표, on_episode_done→no-op. 실패 시 ZERO 폴백.
- `backend/bot_runner/tests/test_battleroyale2_mode.py`
  — battleroyale2 모드 테스트 11종(정규화/ZERO 폴백/import 화이트리스트/policy 차단/choose_spawn/타임아웃).
- `backend/BattleRoyale2/tests/test_bot_runner_isolation.py`
  — `_make_user_bot`/`_assemble_bots`가 BOT_RUNNER_URL 시 원격 어댑터 사용, 프로덕션 in-process 거부 검증.
- `backend/BattleRoyale2/HARDENING_CHANGES.md` — 이 기록 파일.

### 수정 파일
- `backend/bot_runner/executor.py`
  — `battleroyale2` 모드 추가: BR2 builtins(`_BR2_BUILTINS`, 화이트리스트 `__import__`),
    베이스 클래스 주입(`_BR2BotBase`), 액션/스폰 검증(`_validate_br2_action`/`_validate_spawn`),
    `_child_entry`에 phase 분기(get_action/choose_spawn), `run()`에 `phase` 인자, `_default_for()`.
- `backend/bot_runner/schemas.py`
  — `RunRequest.phase: Optional[str]` 추가.
- `backend/bot_runner/main.py`
  — `_default_action`을 `executor._default_for`로 위임, `run()`에 `req.phase` 전달.
- `backend/BattleRoyale2/server/ws_server.py`
  — `_make_user_bot()` 헬퍼 추가(BOT_RUNNER_URL→격리 어댑터, 프로덕션 필수 시 in-process 거부),
    `_assemble_bots`가 `InProcessBot2` 대신 `_make_user_bot` 사용, `RemoteBattleRoyale2BotAdapter` import.

### 검증
- `bot_runner/tests` 100 passed, `BattleRoyale2/tests` 10 passed.
- 라이브 round-trip: 정상 봇 → 검증된 액션, 악성 봇(`open('/etc/passwd')`) → policy 차단 + ZERO 폴백(게임 지속).

---

## Phase 2 — BR2 WS owner 인증 (2026-05-27)

Phase 1 이후 WS `/match/{id}`는 유효한 토큰이면 아무 로그인 사용자나 연결 가능했다.
Phase 2는 게임 생성자(owner)만 자신의 매치 WS에 접속할 수 있도록 owner 일치 검사를 추가한다.

### 수정 파일
- `backend/BattleRoyale2/server/ws_server.py`
  — `match_ws` 인증 블록에 owner 일치 검사 추가:
    토큰 유효 후 `_resolve_owner_id(token) != game.owner_user_id`이면 4403으로 WS 거부.
    (4401 = 미인증, 4403 = owner 불일치)
- `backend/BattleRoyale2/tests/test_ws_owner_auth.py`
  — WS 인증 시나리오 4종(토큰없음→4401, 무효토큰, wrong owner→4403, owner 토큰 수락).

### 검증
- `BattleRoyale2/tests` 14 passed (+4 신규).

---

## Codex 리뷰 후속 — P1 3건 수정 (2026-05-27)

Phase 1/2 커밋(`f03d48c`, `ecb0bc2`) 후 Codex 리뷰가 production-impacting P1 3건 지적 → 모두 수정.

### P1-A: classic 모드(BR/Boss/MS) import 깨짐 회귀
유저 봇 템플릿이 `import random`/`import math`로 시작하는데, classic 모드는 `SAFE_BUILTINS`
(`__import__` 없음)로 실행돼 매 틱 STAY/HOLD 폴백되던 회귀. import 화이트리스트를 BR2 전용에서
**전 모드 공용**으로 일반화.
- `backend/bot_runner/executor.py`
  — `_BR2_ALLOWED_MODULES`/`_br2_safe_import`/`_BR2_BUILTINS` → `_ALLOWED_MODULES`/`_safe_import`로
    통합, `_build_safe_builtins()`가 `SAFE_BUILTINS`에 화이트리스트 `__import__` 주입. BR2 모드도
    공용 `SAFE_BUILTINS` 사용(베이스 클래스 주입만 차이). 허용 모듈: math/random/json/collections/heapq/itertools.
- `backend/bot_runner/tests/test_dos_hardening.py`
  — 회귀 테스트 4종(BR `import random` 동작 / stocks `import math` 동작 / `import os` 차단 /
    allowlist 밖 `import base64` 런타임 차단).

### P1-B: 프로덕션 BOT_RUNNER fail-closed (secure-by-default)
`BOT_RUNNER_REQUIRED` 기본값 `false`→`true`. 프로덕션에서 `BOT_RUNNER_URL` 미설정 시 InProcessBot
폴백(RCE) 대신 503/거부. Cloud Run은 bot-runner 없이 in-process 실행이 설계이므로
`BOT_RUNNER_REQUIRED=false`를 **명시적 opt-out**으로 설정.
- `backend/battle_royale/src/arena/server/settings.py` — 기본값 false→true + 주석.
- `backend/mock_stocks/src/stocks/server/app.py` — fail-closed 조건을 `ENV=="production" and REQUIRED`로
  BR과 일치(기존엔 ENV 무관 `REQUIRED`만 검사 → dev에서도 503 위험).
- `backend/BattleRoyale2/server/ws_server.py` — `_make_user_bot`의 `BOT_RUNNER_REQUIRED` 기본값 false→true.
- `cloudbuild.yaml` — Cloud Run env에 `BOT_RUNNER_REQUIRED=false` 추가(명시적 opt-out).
- `backend/BattleRoyale2/tests/test_bot_runner_isolation.py` — production+REQUIRED 미설정→RuntimeError 테스트 추가.
- `backend/BattleRoyale2/tests/test_db_flow.py` — `repo` fixture에 `ENV=development` 설정(로컬 테스트 dev 컨텍스트).

### P1-C: BR2 WS owner 해석 실패 시 fail-closed
`match_ws`에서 토큰은 유효하나 `_resolve_owner_id`가 `None`(user-service/DB 장애)이면 소유권 확인
불가 → 기존엔 통과 허용. `caller_id is None`도 불일치와 동일하게 4403 거부로 변경.
- `backend/BattleRoyale2/server/ws_server.py` — owner 검사를 `caller_id != owner`로 단순화(None 포함 거부).
- `backend/BattleRoyale2/tests/test_ws_owner_auth.py` — owner 해석 실패(`ghost` 토큰)→4403 테스트 추가.

### 검증
- `bot_runner/tests` 104 passed, `BattleRoyale2/tests` 16 passed,
  `battle_royale/tests` 276 passed/7 skipped, `mock_stocks/tests` 21 passed/4 skipped.
  (`test_startup_db_failure.py`는 .venv firebase_admin 미설치로 collection 제외 — 기존 환경 문제.)

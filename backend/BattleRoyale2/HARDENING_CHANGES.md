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

# BR2 헤드리스 러너 (C2 서버사이드 시뮬)

서버(Cloud Run)가 헤드리스 Godot 러너 프로세스로 게임을 직접 돌려, 생성 즉시 'running' 으로
시뮬레이션되고 관전/리플레이가 가능하게 한다. (브라우저 권위 클라이언트 불필요)

- `game.pck` — Godot 3.6 **Linux** export 팩(러너용). 웹용 `frontend/public/godot/index.pck` 와 별개.
- `godot_server` 바이너리는 이미지 빌드 시 다운로드(`backend/Dockerfile`).
- 러너 오케스트레이션: `BattleRoyale2/server/runner_manager.py`.

## 기본 비활성

이미지에 바이너리/팩이 들어가도 **`BR2_RUNNER_ENABLED` 미설정이면 러너는 안 켜진다**(`get_runner_manager()→None`).
즉 **배포만으로는 동작 변화 없음.** 아래 env 를 설정해야 켜진다.

## 켜는 법

러너 env·리소스·인스턴스 설정은 **`cloudbuild.yaml` 에 박혀 있어 배포 시 자동 적용**된다
(`--set-env-vars` 가 매 배포 시 env 를 교체하므로, 여기 없으면 수동 설정이 배포 때마다 지워짐).

**1회 설정 — Cloud Build 트리거 substitution:**
- 트리거 설정에서 `_BR2_RUNNER_SECRET` = (임의 문자열, 예 `loa-brrun-7f3a9b2c`) 추가.
  (repo 에 시크릿 커밋 금지 → 트리거에만 둔다. 빈 값이면 러너 WS 인증 실패)

이후 **main 에 머지 → Cloud Build 자동 배포** 시 러너가 켜진 상태로 배포됨.

### 임시 테스트(배포 없이 바로) — 다음 배포 때 cloudbuild 값으로 덮어써짐
```bash
gcloud run services update ai-arena-server --region asia-northeast3 \
  --min-instances 1 --max-instances 1 --cpu 2 --memory 1Gi --timeout 3600 \
  --update-env-vars \
'BR2_RUNNER_ENABLED=1,BR2_GODOT_BIN=/usr/local/bin/godot_server,BR2_GAME_PCK=/app/BattleRoyale2/runner/game.pck,BR2_RUNNER_WS=ws://127.0.0.1:8080/battleroyale2/match/,BR2_RUNNER_SECRET=loa-brrun-7f3a9b2c,BR2_MAX_CONCURRENT_GAMES=4,BR2_MATCH_TIMEOUT_SEC=240'
```

### env 의미
| 변수 | 설명 |
|---|---|
| `BR2_RUNNER_ENABLED` | "1" 이면 러너 활성 |
| `BR2_GODOT_BIN` | linux_server 바이너리 경로 |
| `BR2_GAME_PCK` | 이 디렉터리의 game.pck 경로 |
| `BR2_RUNNER_WS` | 러너가 접속할 내부 WS(자기 자신). `/battleroyale2/match/` 마운트 |
| `BR2_RUNNER_SECRET` | 러너 WS 인증 공유 시크릿(설정 시 WS 가 이 토큰을 러너로 허용) |
| `BR2_MAX_CONCURRENT_GAMES` | 동시 러너 상한(초과 시 거절) |
| `BR2_MATCH_TIMEOUT_SEC` | 러너 1판 최대 수명(초). 초과 시 kill |

러너가 **비정상 종료(crash) 또는 타임아웃 kill** 되면 reaper 가 `on_exit` 콜백으로 해당 게임을
DB 에서 종료 처리(`status='error'`, `end_reason='runner_crash'`/`'runner_timeout'`)한다. 정상
종료(MATCH_END 후 rc=0)는 콜백을 호출하지 않으며, 이미 `finished` 인 게임은 덮어쓰지 않는다.
→ 러너가 죽어도 게임이 '진행 중' 으로 박제되지 않음.

## ⚠️ 제약

- **단일 인스턴스 가정**: 러너·관전 릴레이·프레임 StateStore 가 프로세스 로컬. min=max=1 필수.
  멀티 인스턴스로 확장하려면 Redis Pub/Sub + Redis StateStore 로 교체(인프라 추상화 존재).
- WS 타임아웃을 매치 길이 이상으로(`--timeout`).

## game.pck 재생성 (게임 코드 변경 시)

웹 pck(`frontend/public/godot/index.pck`)와 **별도로** 갱신해야 함. 게임 레포 PoC 컨테이너가 Linux export 산출:
```bash
# (게임 레포 loa-battleroyale 에서)
docker build -f poc/headless_godot/Dockerfile -t loa-headless-poc .
cid=$(docker create loa-headless-poc)
docker cp "$cid:/out/game.pck" <loa-backend>/backend/BattleRoyale2/runner/game.pck
docker rm "$cid"
```

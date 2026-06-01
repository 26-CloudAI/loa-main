# BR2 헤드리스 러너 (C2 서버사이드 시뮬)

서버(Cloud Run)가 헤드리스 Godot 러너 프로세스로 게임을 직접 돌려, 생성 즉시 'running' 으로
시뮬레이션되고 관전/리플레이가 가능하게 한다. (브라우저 권위 클라이언트 불필요)

- `game.pck` — Godot 3.6 **Linux** export 팩(러너용). 웹용 `frontend/public/godot/index.pck` 와 별개.
- `godot_server` 바이너리는 이미지 빌드 시 다운로드(`backend/Dockerfile`).
- 러너 오케스트레이션: `BattleRoyale2/server/runner_manager.py`.

## 기본 비활성

이미지에 바이너리/팩이 들어가도 **`BR2_RUNNER_ENABLED` 미설정이면 러너는 안 켜진다**(`get_runner_manager()→None`).
즉 **배포만으로는 동작 변화 없음.** 아래 env 를 설정해야 켜진다.

## 켜는 법 (Cloud Run)

```bash
gcloud run services update ai-arena-server --region asia-northeast3 \
  --min-instances 1 --max-instances 1 \    # 인메모리 릴레이/StateStore → 단일 인스턴스 필수
  --cpu 2 --memory 1Gi \                    # 러너 1개 ≈ 0.4 vCPU/46MB + 서버. 동시성 따라 조정
  --timeout 3600 \                          # WS 매치(~3분) 동안 연결 유지
  --update-env-vars \
'BR2_RUNNER_ENABLED=1,BR2_GODOT_BIN=/usr/local/bin/godot_server,BR2_GAME_PCK=/app/BattleRoyale2/runner/game.pck,BR2_RUNNER_WS=ws://127.0.0.1:8080/battleroyale2/match/,BR2_MAX_CONCURRENT_GAMES=4,BR2_MATCH_TIMEOUT_SEC=240'
# BR2_RUNNER_SECRET 은 Secret Manager 로 (러너 WS 인증용 공유 시크릿):
#   gcloud run services update ... --set-secrets BR2_RUNNER_SECRET=br2-runner-secret:latest
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

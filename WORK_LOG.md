# WORK_LOG.md — seongjin
> Personal mode: in `.git/info/exclude`, never committed.

---

## 2026-05-26 — Claude Code — Phase 9 본검증 (main 머지 + GKE E2E Steps 0~5)

### 배경
Phase 8 + A1(readiness latch, fac686b) GKE 반영 완료 후, Phase 9 E2E 진행 전 main 최신화 작업 수행.

### main → seongjin-kube 머지 (ccc58c7)
- main이 46커밋 앞(BR2 Godot 업데이트, boss bot 개선, frontend UI 등). 겹치는 파일 0건 (drydrun 확인), 충돌 없음.
- 머지 후 테스트: BR 276 / MS 21(4skip) / healthz 5 / bot_runner 89 passed — 회귀 없음.
- `test_startup_db_failure` firebase_admin 미설치 문제는 머지 이전과 동일한 기존 결함.
- origin/seongjin-kube push 완료 (fac686b → ccc58c7).

### Step 0 — Cloud Run rollback 경로 확인
- `/battleroyale/health` · `/stocks/health` → 200 ✅
- `/healthz` → 404 (Cloud Run 구버전, A1 미배포 — 의도된 동작)

### Step 1~4 — GKE Ingress E2E (HTTP + Host 헤더, IP: 8.233.221.199)
인증: kubetest@arena.dev Firebase 토큰. arena-cert Provisioning(DNS 미설정)이라 HTTP+Host 헤더 방식.

| 게임 | game_id | 결과 |
|------|---------|------|
| BattleRoyale | 6cb14f43 | reason:max_ticks, final_tick:200, kube_t 4위(151틱) |
| Boss | 813f5947 | reason:last_standing, final_tick:250 |
| MockStocks | 18e78944 | final_tick:200 |

모두 `/result` HTTP 200 ✅. 유저 봇은 GKE RemoteBotAdapter→bot-runner 경로 실행 확인.

**비고** — `GET /api/games/{id}` 폴링이 `finished` 전환 안 하는 기존 버그: Redis state_store가 마지막 틱 "running" 상태를 TTL 1시간 유지 → `_resolve_owned_game_info`가 DB 전에 Redis 먼저 읽어 "running" 반환. `/result` 엔드포인트 직접 폴링으로 우회함. list 엔드포인트는 DB status 먼저 확인해 올바르게 동작.

### Step 5 — GKE WebSocket
- GKE Ingress 경유: curl에서 `101 Switching Protocols` 확인 ✅. Python websockets 16.0은 IP+additional_headers 조합에서 Host 헤더 중복으로 GFE 400 반환 → DNS 설정(ws://api.leagueofagents.net) 후 재확인 예정.
- port-forward 경유 (game-server, 비gVisor): 연결 성공, live tick 36~43 (alive=4) 8건 수신 ✅ (game_id:727ce631).

### 다음 작업
- Step 6: Cloud Run E2E (병행 운영 검증)
- Step 7: Cloud Build GKE 배포 step 추가 (팀 승인 필요)
- DNS 설정(api.leagueofagents.net A레코드) → arena-cert Active → HTTPS/WS E2E 재확인

---

## 2026-05-26 — Claude Code — origin/main → seongjin-kube merge (Phase 5 준비)

### 배경
Phase 5(이미지 빌드/배포) 전, seongjin-kube가 옛 main(`b009fd7`) 기준이라 팀의 최신 작업(BattleRoyale2 Godot 게임, 키 제거 PR #102 등 ~37커밋)이 빠진 상태. 이대로 이미지 빌드 시 stale backend가 됨. rebase 대신 **merge** 선택 (팀 정책=merge commit, force-push 불필요, 우리 7커밋 보존).

### 진행
- 안전 백업 브랜치 `backup/seongjin-kube-premerge-20260525` 생성 (로컬)
- 충돌 후보 사전 분석: merge-base `b009fd7` 기준 양쪽 동시 수정 파일은 `backend/run_server.py` 1개뿐
- `git merge origin/main --no-edit` → **충돌 0, ort 자동 병합 성공** (merge 커밋 `252082d`)
- `run_server.py` 자동 병합 의미 검증: 우리 `/healthz`,`/livez` + main `br2_app` 방어적 로드 + `/battleroyale2` mount 가 모두 올바르게 공존 (수동 확인 완료)
- `backend/Dockerfile`에 main의 `COPY BattleRoyale2/` 포함 확인 → 빌드 이미지가 최신 backend 반영

### 검증 (전부 통과)
- bot_runner 78 / healthz·livez 5 / BR remote adapter 11 / MS remote adapter 10 / battle_royale 258 / mock_stocks 19 passed(4 skip)
- 비통과 1건: `test_startup_db_failure.py` — `firebase_admin` 미설치(backend/.venv) 환경 문제. **merge 이전 백업본에도 동일 import 존재 → merge 회귀 아님.**
- 이전 open-question이던 `test_db_auth`/`test_edge_cases`/`test_ranking` import 실패는 main PR #101로 해소되어 이제 통과

### 결과
- `origin/seongjin-kube` = `252082d` (push 완료, force 아님). 이제 main의 최신 backend 위에 우리 k8s 작업이 얹힌 상태.
- 로컬 `backend/secrets/serviceAccountKey.json`(로테이션된 새 키)은 merge로 들어온 `.gitignore` `**/secrets/*`로 정상 무시됨

### 추후
- [ ] Phase 5: server/bot-runner 이미지 빌드 → Artifact Registry push → 수동 kubectl 배포
- [ ] seongjin-kube → main PR (이제 main 머지 완료라 rebase 불필요, 깔끔히 PR 가능)
- [ ] `backup/seongjin-kube-premerge-20260525` 브랜치 정리 (며칠 후 이상 없으면)

---

## 2026-05-25 — Claude Code — Firebase serviceAccountKey 유출 대응 + GCP 키 로테이션

### 배경
커밋 61f8df7 ("chore: MainPage UI 조정", 2026-05-21, blackwellSW)에서 실제 Firebase Admin SDK 서비스 계정 키 3개가 main에 커밋됨.
유출 파일: `backend/secrets/`, `backend/src/arena/server/secrets/`, `backend/BattleRoyale/src/arena/server/secrets/` 아래 `serviceAccountKey.json` (모두 동일 키, SA: `firebase-adminsdk-fbsvc@ai-arena-b2b4b.iam.gserviceaccount.com`, private_key_id: `3365cb0c...`)

### 완료 항목

**Git 측 (방법 1 — 히스토리 재작성 없이 현재 트리에서만 제거)**
- `~/capstone_design/loa-secret-cleanup`에 격리 클론 후 `fix-leaked-secret` 브랜치 분기 (origin/main `3b04b4d` 기준)
- 유출 키 파일 3개 `git rm` 제거
- `.gitignore`: `secrets/*` → `**/secrets/*` 로 수정 + 예외 `!**/secrets/*.example.{json,py}`
- 커밋 `cf26652` push → PR #102 생성 → 당일 머지 (현재 main: `5e09d44`)
- 격리 클론 디렉터리 삭제

**GCP 키 로테이션**
- 새 키 발급 (private_key_id: `1f9402…`) → `backend/secrets/serviceAccountKey.json` 교체
- 로컬 파일 검증: 유출키와 다름, 같은 SA/프로젝트 확인
- Secret Manager `firebase-service-account` (project: `knu-2026-sungjin0418`) 버전 2 추가
- Cloud Run `ai-arena-server` 새 리비전 배포: `ai-arena-server-00106-zn6` (트래픽 100%)
- 검증: `/docs` HTTP 200, 로그 Firebase 오류 없음
- Secret Manager 버전 1(유출키 `3365cb0c`) disable (사용자 직접)

### 주요 발견
- 유출키 `3365cb0c`는 IAM에 이미 없음 → Google 자동 leaked-credential 대응 삭제 추정
- IAM의 `5ede4f3f` (2026-04-03)는 Google system-managed 키 (`--managed-by=user` 필터 시 미표시) → 건드리지 않음
- Cloud Run은 Secret Manager를 통해 credential을 받으므로 레포 파일과 완전 독립 (Dockerfile에 `secrets/` COPY 없음, PR과 로테이션은 서로 영향 없음)
- Secret v1이 유출키를 담고 있었음 (private_key_id만 추출 검증, 본문 미노출)
- `.gitignore` `secrets/*` 패턴 한계가 이번 유출의 간접 원인 → PR #102로 수정 완료
- Firebase Admin SDK ID 토큰 검증은 Google 공개 인증서로 하므로, IAM 키가 죽어도 로그인은 동작 가능

### GCP 자원 (확인됨)
- Cloud Run/Secret Manager 프로젝트: `knu-2026-sungjin0418`
- Firebase SA 프로젝트: `ai-arena-b2b4b`
- Secret 이름: `firebase-service-account`, Cloud Run 서비스: `ai-arena-server`, 리전: `asia-northeast3`

### 추후 작업
- [ ] Secret Manager 버전 1 `destroy` (며칠간 이상 없으면 — `gcloud secrets versions destroy 1 --secret=firebase-service-account --project knu-2026-sungjin0418`)
- [ ] 실제 Firebase 로그인 E2E 테스트 (새 키 기반 token verification 확인)
- [ ] `5ede4f3f` 키 생성 경위 감사 (누가/언제/어디서 사용 중인지)

---

## 2026-05-25 — Claude Code — Phase 3 매니페스트 보안 강화 + Phase 4 GKE 클러스터 생성 준비

### Phase 3 잔여 매니페스트 수정 (검토 #5~10 후속)

5개 파일 수정:
- `k8s/base/network-policy.yaml` — `game-server-isolation` NetworkPolicy 추가 (검토 #5). Google LB IP 대역(`130.211.0.0/22`, `35.191.0.0/16`)을 `ipBlock`으로 8080 허용, 클러스터 내 횡방향 접근 차단. (※ 최초 커밋 56fb8af는 kube-system namespaceSelector였으나 Ingress 백엔드 차단 문제로 9d1d08d에서 ipBlock으로 수정 — 아래 Stop-hook 섹션 참조)
- `k8s/base/bot-runner-deployment.yaml` — container securityContext에 `seccompProfile.type: RuntimeDefault` 추가 (검토 #7). gVisor fallback 대비 syscall 필터.
- `k8s/base/namespace.yaml` — `pod-security.kubernetes.io/enforce: restricted` 라벨 추가 (검토 #8). bot-runner 매니페스트가 이미 restricted 조건 충족(runAsNonRoot/readOnlyRootFilesystem/capabilities.drop ALL).
- `k8s/base/service-account.yaml` — bot-runner SA에 `automountServiceAccountToken: false` 추가 (검토 #9). Pod 레벨에 더해 SA 레벨 belt-and-suspenders.
- `k8s/base/ingress.yaml` — `kubernetes.io/ingress.class: "gce"` annotation 제거, `spec.ingressClassName: gce` 신규 추가 (검토 #6). deprecated annotation 대체.

**CORS_ORIGINS 확장 근거 기록 (검토 #10)**: 계획서(plan.md)에는 CORS 출처 2개(`ai-arena-b2b4b.web.app`, `ai-arena-b2b4b.firebaseapp.com`)만 명시됐으나, 실제 `configmap.yaml`에는 4개(`leagueofagents.net`, `www.leagueofagents.net` 추가). 커스텀 도메인 `leagueofagents.net`이 프로덕션 도메인으로 확정되면서 계획 작성 시점 이후에 추가됨. 기능 문제 없음.

### Phase 4 실행 결과 (2026-05-25 완료)

**Pre-flight**:
- API 4개 (`container`/`artifactregistry`/`secretmanager`/`sqladmin`) 전부 활성화 확인
- VPC/subnet: `default` / `default` (10.178.0.0/20, asia-northeast3)
- static IP `loa-arena-ingress-ip` 예약 → `8.233.221.199` (Ingress 미연결 상태라 ~$7/월, Phase 5 연결 후 $0)

**클러스터 생성**: `gcloud container clusters create-auto loa-arena --region asia-northeast3 --release-channel regular --network default --subnetwork default`
- STATUS RUNNING, master 1.35.3-gke.1389000, master IP 34.64.252.138
- **gke-gcloud-auth-plugin 미설치 경고** → `gcloud components install gke-gcloud-auth-plugin` 으로 해결 후 `get-credentials` 성공
- `kubectl get nodes`: 노드 1개 `NotReady,SchedulingDisabled` — Autopilot은 워크로드 없으면 노드 최소 유지, 정상. Phase 5 Pod 배포 시 자동 프로비저닝.

**검증 결과** (전부 통과):
- `kubectl get runtimeclass` → `gvisor`, `confidential-linked-runner` 존재. bot-runner gVisor 사용 가능 ✅
- Workload Identity pool → `knu-2026-sungjin0418.svc.id.goog` ✅ (Phase 6 GCS 접근 설정 가능)
- net-test Pod → Cloud SQL `10.114.0.3:5432 open`, Redis `10.197.54.43:6379 open` ✅ (Private IP 직접 접근, Auth Proxy 불필요)
- Artifact Registry: repo-level IAM 비어있으나 노드 기본 SA `673184377961-compute@developer` 가 project-level `roles/editor` 보유 → image pull 가능 ✅

**비용 메모**: 클러스터 관리비 $0.10/시간 고정 + Pod requests 기준 과금 ≈ $120~170/월. 중지 개념 없음(삭제만). 작업 없을 때 `gcloud container clusters delete loa-arena --region asia-northeast3` 로 비용 0, 필요 시 재생성(5~10분). 명령어는 `k8s/README.md` + checklist Phase 4 에 기록.

**Phase 3 매니페스트 추가 보강 (Stop-hook 지적 2건)**:
1. namespace를 `enforce: restricted` 로 했더니 game-server(Dockerfile root 실행)가 admission 거부 위험. → `enforce: baseline` + `warn: restricted` 로 조정, game-server 에 securityContext(allowPrivilegeEscalation:false, capabilities.drop ALL, seccompProfile RuntimeDefault) 추가. runAsNonRoot 는 backend/Dockerfile non-root USER 추가 후 (커밋 0d8c504).
2. game-server NetworkPolicy 를 `namespaceSelector: kube-system` 로 했더니 GKE Ingress 백엔드 차단 위험. GKE 외부 HTTP(S) LB(GFE)+헬스체커는 Pod 이 아니라 Google LB IP 대역(`130.211.0.0/22`, `35.191.0.0/16`)에서 NEG 로 Pod IP 직접 호출. → `ipBlock` 두 대역 허용으로 수정 (커밋 9d1d08d). **Phase 8 에서 Ingress 실제 배포 후 health check 통과 + 횡방향 차단 양쪽 검증 필요 (지금은 클러스터에 미적용이라 검증 불가).**

### 이전 세션에서 적어둔 Phase 4 명령 참고 (실행 완료)

**Pre-flight 확인 (사용자가 실행)**:
```bash
! gcloud services list --enabled --filter="name:(container.googleapis.com OR artifactregistry.googleapis.com OR secretmanager.googleapis.com OR sqladmin.googleapis.com)" --format="value(name)"
! gcloud compute networks subnets list --filter="region:asia-northeast3 AND network:default" --format="table(name,network,ipCidrRange)"
! gcloud compute addresses list --global --filter="name:loa-arena-ingress-ip"
```

**Static IP 예약** (없으면):
```bash
! gcloud compute addresses create loa-arena-ingress-ip --global
```

**클러스터 생성** (비용 발생 — 사용자 승인 후):
```bash
! gcloud container clusters create-auto loa-arena \
    --region asia-northeast3 --release-channel regular \
    --network default --subnetwork default \
    --project knu-2026-sungjin0418
```

**Post-creation 검증**:
```bash
! gcloud container clusters get-credentials loa-arena --region asia-northeast3
! kubectl get nodes && kubectl get ns
! kubectl get runtimeclass  # gvisor 포함 확인
! gcloud container clusters describe loa-arena --region asia-northeast3 --format='value(workloadIdentityConfig.workloadPool)'
! kubectl run net-test --image=busybox:1.35 --restart=Never --rm -it -- sh -c "nc -zv 10.114.0.3 5432 && echo 'sql ok'; nc -zv 10.197.54.43 6379 && echo 'redis ok'"
```

---

## 2026-05-22 — Claude Code — k8s Phase 1-3 재시작 (옛 구조 → 새 main 위로 재커밋) + 정리 + 로컬 검증

### 배경: 왜 재시작이 필요했는가
지난 세션에서 git 손상 복구 후 작업트리 변경을 5개 Phase 커밋으로 분해 (59a8306 ~ f79503d). 푸시 직전에 발견: 이 커밋들이 옛 디렉토리 구조 (`BattleRoyale/`, `MockStocks/`, `BotRunner/`) 기반인데, origin/main 이 그동안 18커밋의 대규모 리팩터링으로 새 구조 (`battle_royale/`, `mock_stocks/`, `core/`, `server/boss/` 격리, `gcs_weights.py` 이동) 로 정리됨. seongjin-kube 는 그 변화를 한 번도 fetch/merge 한 적이 없어 그대로 머지 불가능. 안전 태그 `pre-main-merge` (= f79503d) 로 옛 5커밋 보존.

### 전략 결정 (옵션 A 채택)
- **옵션 A**: `git reset --hard origin/main` 후 새 경로로 cherry-pick + 수동 재작업 (선택)
- **옵션 B**: 5커밋을 main 위로 rebase/merge — BattleRoyale↔battle_royale rename 폭풍으로 git rename detection 실패 시 충돌 폭발 위험. 기각.
- **51b1330** (보스전 DB 컬럼 제거): 폐기 확정. main 의 `server/boss/result_handler.py` 가 `boss_won` 컬럼 사용 중이고 SCHEMA_VERSION 7 다운그레이드는 운영 DB 위험.
- **f79503d** (Frontend 정리/디자인 리프레시): 폐기 확정. main 의 5ca8439 가 추가한 MyPage 를 통째로 삭제하는 변경 — k8s 와 무관, 별도 작업으로 분리.
- **BotRunner 디렉토리명**: `backend/BotRunner/` → `backend/bot_runner/` (main 의 lowercase 컨벤션 일치).

### Step 1 — 기획 문서 3종 갱신 (재커밋 전 선행)
sed 일괄 치환 + 정밀 수정 + 의미 단위 추가.
- `for_kubernetes_migration_plan.md`: `BattleRoyale/` → `battle_royale/`, `MockStocks/` → `mock_stocks/`, `BotRunner/` → `bot_runner/` 일괄 치환. line 795/800-801/1614 의 잔존 path-style 잡음. **section 1.4 신규 추가** — main 리팩터링 컨텍스트 (`backend/core/bot_interface.py` 위치, `server/boss/` 격리, BotRunner 는 유저 봇에만 적용).
- `for_kubernetes_migration_explan.md`: `backend/BotRunner/` → `backend/bot_runner/` 1건.
- `for_kubernetes_checklist.md`: 일괄 치환 + **재시작 컨텍스트 노트** 추가 (Phase 0 `[x]` 유효, Phase 1/2 `[x]` 는 재작업 필요, BotRunner lowercase 결정 명시).
- 검증: `grep -E "backend/(BattleRoyale|MockStocks|BotRunner)"` 0 hit. 남은 capitalized 78개는 게임명/클래스명/prose (의도).

### Step 2 — git reset + 재시작 베이스 마련
- `git fetch origin` → `git reset --hard origin/main` (HEAD: f79503d → b009fd7).
- 옛 5커밋은 `pre-main-merge` 태그로만 도달 가능 (보존 확인).
- 기획 문서 3종은 `.git/info/exclude` 로 untracked → 리셋 영향 없음 (별도 커밋 불필요).
- 작업트리에 옛 디렉토리들 (BattleRoyale/, BotRunner/, MockStocks/ 등) 이 untracked 로 남음 → Step 6 에서 정리.

### Step 3 — Phase 1 bot_runner 재커밋 (524e22b)
- `git cat-file -p 59a8306:backend/BotRunner/<file>` 로 14개 파일 추출 → `backend/bot_runner/` 에 배치.
- Dockerfile / 내부 import 는 path-agnostic 이라 변경 불필요. conftest.py 의 comment 만 "BotRunner 루트" → "bot_runner 루트" 수정.
- `backend/pyproject.toml`: main 의 `[project.optional-dependencies].dev` 에 `cachetools>=5.0`, `httpx>=0.25` 추가 (fastapi/uvicorn 은 main 의 `server` optional 에 이미 존재). `[dependency-groups]` 블록은 main 컨벤션과 안 맞아 생략.
- `uv venv backend/bot_runner/.testvenv` → 의존성 설치 → `pytest tests/ -v` **78 passed**.
- 커밋: 15 files, +1056 / -1.

### Step 4 — Phase 2 RemoteBotAdapter + /healthz, /livez 재커밋 (e5de13f)
**Keep / Drop 분리**: 옛 08352fc 가 RemoteAdapter 도입 + 보스봇 리팩터링을 한 번에 묶었는데, **main 의 `server/boss/` 격리가 더 깔끔한 구조**이므로 보스봇 리팩터링 부분 (rl_boss_bot/rule_boss_bot/train_boss_parallel/gcs_weights 재구성, BOSS_MAX_USER_BOTS 제거, BOSS_BOT.md/boss_bot_ops.md 삭제, .gitignore 가중치 패턴 제거) 은 모두 폐기.

**파일 작업**:
- BR adapter: `backend/battle_royale/src/arena/sandbox/remote_adapter.py` — 추출 후 `from ..bot_interface import BotInterface` → `from core.bot_interface import BotInterface` 로 import 수정 (main 이 BR BotInterface 를 `backend/core/` 로 이동).
- MS adapter: `backend/mock_stocks/src/stocks/sandbox/{__init__,remote_adapter}.py` 신규. import 는 그대로 (`from ..bot_interface import BotInterface` — main 이 MS BotInterface 는 `mock_stocks/src/stocks/bot_interface.py` 에 유지).
- BR/MS settings.py: `BOT_RUNNER_URL`/`BOT_RUNNER_TIMEOUT_SEC`(0.5)/`BOT_RUNNER_REQUIRED` 5줄 append.
- BR app.py: line 354 middleware 다음에 `app.state.db_ok = lambda: state.get("db_conn") is not None` 추가. line 551 의 `bot = InProcessBot(...)` 블록을 `if _settings.BOT_RUNNER_URL: RemoteBattleRoyaleBotAdapter / elif production+REQUIRED: 503 / else: InProcessBot` 로 교체.
- MS app.py: import 에 `from . import settings as _settings` 추가 (main 에 없던 패턴). registry 정의 직후 `app.state.db_ok = lambda: registry._repo is not None` 추가. line 333 의 InProcessBot 블록을 동일 분기 (단 MS 는 ENV 조건 없음, BOT_RUNNER_REQUIRED 만) 로 교체.
- run_server.py: `app = FastAPI(...)` 와 `app.mount(...)` 사이에 `/healthz`, `/livez` 추가. `from fastapi.responses import JSONResponse` 도 inline import.
- 테스트 5개: BR/MS test_remote_bot_adapter (mock HTTP), BR/MS test_create_game_uses_remote_bot, backend/tests/test_healthz_livez (mock app).

**검증**:
- 신규 Phase 2 테스트: 26/26 통과 (BR adapter 8, MS adapter 7, BR create_game 3, MS create_game 3, healthz_livez 5).
- BR 전체 회귀: 202 passed, 2 failed (둘 다 사전 main 이슈 — `test_duplicate_name_per_user`, `test_valid_actions_complete` 의 8방향 Action enum 불일치). Phase 2 와 무관.
- 3 collection error: `generate_salt`/`hash_password` import 실패, `firebase_admin` 미설치 — 사전 main 이슈.

- 커밋: 14 files, +796 / -2.

### Step 5 — Phase 3 K8s 매니페스트 재커밋 (6a0f290)
- main 에 k8s/ 가 없으므로 c1f429c 만 보면 부족 (c1f429c 는 PDB + placeholder 만 추가). `pre-main-merge` 태그 (f79503d) 가 옛 작업의 최종 상태로 k8s/ 16개 파일을 모두 갖고 있음.
- `git checkout pre-main-merge -- k8s/` 로 16개 파일 일괄 가져옴 (이미 staged 상태로 들어옴).
- 검증:
  - configmap 의 `BOT_RUNNER_URL=http://bot-runner.arena.svc.cluster.local:8001` 이 bot-runner-service 의 port 8001 과 일치.
  - bot-runner-deployment containerPort 8001 = bot_runner/Dockerfile EXPOSE 8001 = main.py CMD `--port 8001`.
  - 이미지 태그 `:PLACEHOLDER` (game-server, bot-runner 둘 다).
- 커밋: 16 files, +441.

### Step 6 — Push (3단계 안전 절차)
1. `git push --dry-run --force-with-lease origin seongjin-kube` → `88ef1c5...6a0f290 (forced update)` 확인. 21 commits push, 2 commits 제거 (7fe0e30, 88ef1c5) — 두 커밋의 내용은 새 HEAD 에 보존됨.
2. **백업 브랜치** 생성: `git push origin pre-main-merge:refs/heads/seongjin-kube-backup` → `origin/seongjin-kube-backup = f79503d` (옛 작업 영구 보존).
3. 본 push: `git push --force-with-lease origin seongjin-kube` 성공.

### Step 7 — 로컬 secret 이동 + 잔재 정리 (156M+ 회수)
- secret: `backend/src/arena/server/secrets/serviceAccountKey.json` → `backend/secrets/serviceAccountKey.json` (firebase_handler.py 의 `parents[4]/secrets/serviceAccountKey.json` 기본 경로 매칭 확인).
- 삭제: `backend/BotRunner/` (11), `MockStocks/` (36), `bots/` (6), `path/to/venv/` (1029, 실수로 만들어진 venv), `src/` (44), `BattleRoyale/` (5506, 156M), `server.log`, `temp_bots/`.
- 보존: `backend/ai_arena.db` (활성 로컬 DB).

### 발견된 부가 이슈 — .gitignore `secrets/*` 패턴 한계
- `.gitignore` 의 `secrets/*` 는 루트 `secrets/` 만 매칭, `backend/secrets/` 안 보호.
- 즉시 우회: `.git/info/exclude` 에 `backend/secrets/serviceAccountKey.json`, `backend/secrets/gemini_key.py` 추가 (로컬 보호).
- 일반적 개선: `secrets/*` → `**/secrets/*` 로 .gitignore 패턴 수정. 팀 협의 후 별도 PR.

### Step 8 — 로컬 dev 서버 동작 검증
- `python run_server.py --port 8088` (.testvenv + firebase-admin 추가 설치).
- 부팅: Firebase 초기화 ✓, SQLite DB init ✓, 인메모리 Redis ✓, MockStocks 뉴스 풀 2/2 채움 ✓.
- 엔드포인트:
  - `/healthz` 200, `{"status":"ok","battleroyale":{"db":"ok"},"stocks":{"db":"ok"}}` — Phase 2 신규, db_ok lambda 정상 동작
  - `/livez` 200, `{"status":"alive"}` — Phase 2 신규
  - `/battleroyale/health`, `/stocks/health` 200 — main 기존 sub-app 회귀 없음

### 최종 상태
- 로컬 seongjin-kube = origin/seongjin-kube = **6a0f290** (싱크)
- `origin/seongjin-kube-backup = f79503d` (안전망)
- 3 Phase 커밋: 524e22b (Phase 1), e5de13f (Phase 2), 6a0f290 (Phase 3)
- backend/ 디렉토리 깨끗 (`battle_royale/`, `bot_runner/`, `core/`, `mock_stocks/`, `secrets/`, `tests/`, 표준 파일들)

### 다음 세션 시작점
- [ ] Phase 4: GKE Autopilot 클러스터 실제 생성 (인프라 작업, GCP 콘솔/`gcloud container clusters create`)
- [x] `.gitignore` 의 `secrets/*` → `**/secrets/*` 수정 완료 — PR #102 머지 (2026-05-25)
- [ ] seongjin-kube → main PR 생성 (사용자 결정 — origin/main 이 b009fd7 → 47e51b0 으로 1커밋 진행됨, rebase 또는 merge 필요)
- [ ] checklist.md 의 Phase 0/1/2 `[x]` 를 새 커밋 (524e22b, e5de13f) 기준으로 갱신

---

## 2026-05-17 — Claude Code — Kubernetes 전환 Phase 1: Bot Runner 보안 패치 + 검토

### 보안 패치 4건 (Codex stop-hook 검토 기반)

**1. getattr alias bypass 차단**
- `getattr/setattr/delattr/hasattr`를 `_FORBIDDEN_CALLS`에서 `_FORBIDDEN_NAMES`로 분리
- `ast.Name` 노드 레벨에서 차단 → `g = getattr` 같은 alias 할당도 거부
- executor.py `_BLOCKED_BUILTINS`에도 동일하게 추가 (defence-in-depth)

**2. str.format() 정적 문자열 dunder 차단**
- `_FORMAT_DUNDER_RE` 패턴으로 `ast.Constant` 문자열 내 `{...}` 블록에 `__` 포함 시 거부
- `"{0.__class__}".format([])` 같은 정적 탬플릿 차단

**3. str.format() 동적 조합 문자열 차단**
- `_FORBIDDEN_METHODS = frozenset(["format", "format_map"])` 추가
- `ast.Call` 레벨에서 `.format()` / `.format_map()` 메서드 호출 자체 차단
- 동적 조합 `s = "{0." + "__class__" + "}"; s.format([])` 패턴도 차단

**4. bound-method alias bypass 차단**
- `ast.Attribute` 브랜치에서도 `_FORBIDDEN_METHODS` 체크 추가
- `fmt = "".format` / `f = str.format` 같이 메서드 참조 자체를 막음

### 기타 조정

- `__build_class__` 차단 해제: 사용자 봇이 `class X:` 정의 가능. `__subclasses__/__bases__/__mro__` 등은 여전히 차단되므로 subclass enumeration escape 불가 — 별도 attack probe로 재확인.
- `requirements.txt` 분리: 프로덕션(fastapi/uvicorn/pydantic/cachetools) vs `requirements-dev.txt`(+ httpx/pytest). Docker 이미지 슬림화.

### 검증

- 알려진 21개 우회 벡터 전부 policy.check()에서 차단 확인 (직접 probe 실행)
- 정상 봇 코드 6패턴 통과 확인 (dict/math/f-string/%format/stocks/class-based)
- `pytest` 78/78 통과

### 다음 작업

- Phase 2: 게임 서버 RemoteBotAdapter 연결 + /healthz /livez 엔드포인트

---

## 2026-05-16 — Claude Code — Kubernetes 전환 Phase 0 사전 점검 완료

### 완료 항목

**GCP 리소스 확인**
- Project ID: `knu-2026-sungjin0418`
- Cloud Run URL: `https://ai-arena-server-6eb5desvgq-du.a.run.app`
- Cloud SQL private IP: `10.114.0.3` (계획서 DB_HOST 일치 확인)
- Memorystore Redis: `arena-redis`, `10.197.54.43:6379` (계획서 REDIS_HOST 일치 확인)
- VPC: `default` network, `asia-northeast3` subnet `10.178.0.0/20`
- VPC connector: `arena-connector`
- Secret Manager: `firebase-service-account`, `db-password`, `GEMINI_API_KEY`
- GCS boss weights: `gs://boss-weights/trained_weights.json` (manifest에는 미기재, Cloud Build substitution으로만 주입)
- Artifact Registry: `ai-arena` (DOCKER, asia-northeast3)

**운영 baseline 확인**
- `/battleroyale/health` → `{"status":"ok","active_games":0,"total_spectators":0}`
- `/stocks/health` → `{"status":"ok"}`
- BattleRoyale/MockStocks 게임 생성 → 관전 WebSocket → 종료 → 결과 E2E 정상

**비용 예산**
- 현재 Cloud Run 비용 및 GCP 크레딧 잔액 확인 → 전환 진행 가능

### 특이사항
- JWT_SECRET이 Cloud Run 환경변수에 없음 → Kubernetes Secret 생성 시 필요 여부 재확인 필요
- gVisor 사전 호환성 확인(Phase 0.4)은 Phase 4 클러스터 생성 후 진행

### 다음 작업
- Phase 1: Bot Runner 서비스 구현 (`backend/BotRunner/`)

---

## 2026-05-12 — Claude Code — MockStocks Cloud Run DB lock 충돌 수정

**배경**: Cloud Run rolling 배포 시 신·구 리비전 겹침 구간에서 `ALTER TABLE stock_games`(startup DDL)가 구 리비전의 idle-in-transaction SELECT와 lock 충돌 → `LockNotAvailable` → DB 없이 기동 → 기록 목록 공백, 새 게임 이름 번호 항상 1.

### 완료 항목
- `backend/MockStocks/src/stocks/db/schema.py`: `_init_postgresql()`에서 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS owner_uid/name` 두 줄 제거. 해당 컬럼은 `SCHEMA_SQL_POSTGRESQL`에 이미 포함. lock 충돌 직접 원인 제거.
- `backend/MockStocks/src/stocks/db/schema.py`: `conn.commit()` 이후 `conn.autocommit = True` 추가. SELECT 후 idle-in-transaction 트랜잭션 누수 방지. (`get_connection()` 아닌 `_init_postgresql()` 반환 conn이 repo 실제 연결.)
- `backend/MockStocks/src/stocks/server/app.py`: `GET /api/games/history` repo=None 시 `[]` → `503`.
- `backend/MockStocks/src/stocks/server/app.py`: `POST /api/games` repo=None 시 인메모리 게임 생성 → `503`.
- `docs/mockstocks_cloud_run_db_lock_issue.md`: 원인 분석·재현 경로·단기/장기 해결 계획 문서화.
- 커밋 `243aa96`, PR #83: https://github.com/26-CloudAI/loa-main/pull/83

### 검증
- `uv run pytest MockStocks/tests/test_stock_game_repository.py MockStocks/tests/test_game_session_db_persistence.py MockStocks/tests/test_startup_db_failure.py -v` → 9/9 passed
- FastAPI TestClient 통합 테스트 (Firebase mock, SQLite 정상 + init_db 실패 503 경로) → 전체 통과
- 로컬 서버 직접 기동 + 프론트엔드 E2E 확인 완료

### 다음 작업
- [ ] PR #83 팀 머지 후 Cloud Run 배포
- [ ] 배포 후 로그에서 `canceling statement due to lock timeout` 소멸 확인
- [ ] `test_pg_smoke.py` Cloud SQL Auth Proxy 환경에서 실행

---

## 2026-05-12 — Codex — 최우선: 유저 봇 코드 서버 인프로세스 실행 차단

### 현재 파악
- Cloud Run 운영 서버는 정상 응답 중 (`/battleroyale/health`, `/stocks/health`).
- BattleRoyale `/api/games` 생성 경로에서 유저 제출 코드를 `InProcessBot`으로 감싸고, `exec(code, {"__builtins__": __builtins__})`로 서버 프로세스 안에서 직접 로드한다.
- `sandbox/`에는 `ContainerPool`, `DockerBotAdapter`가 있지만 운영 `create_game()` 경로에 연결되어 있지 않다.
- `CreateGameRequest.use_sandbox` 필드는 스키마에만 있고 실제 API 구현에서는 읽지 않는다.
- Cloud Run 서버 이미지는 FastAPI 서버 실행용이며, 서버 컨테이너 안에서 Docker 샌드박스를 띄우는 구성은 없다.

### 문제점
- 신뢰할 수 없는 유저 코드가 DB/Firebase/Gemini 시크릿을 가진 운영 서버 프로세스 안에서 실행된다.
- 유저 코드가 파일/환경변수 접근, 네트워크 호출, import, CPU/메모리 과점유, 무한 루프를 시도할 수 있다.
- 한 유저 봇 문제가 같은 Cloud Run 인스턴스의 API 서버와 다른 게임 세션까지 영향을 줄 수 있다.
- 샌드박스 옵션이 있는 것처럼 보이지만 실제 운영에서는 격리가 적용되지 않는다.


## 2026-05-09 — Codex — 게임 이름 생성 방식 통합

### 완료 항목
- BattleRoyale/보스전 기본 게임 이름에서 `새` 제거. 자동 이름 형식을 `{모드명} {번호} · {짧은게임ID}`로 변경.
- MockStocks `stock_games`에 `name` 컬럼 추가. SQLite/PostgreSQL DDL 및 `ALTER TABLE ... ADD COLUMN` 마이그레이션 반영.
- `StockGameRepository`에 `name` 저장/조회와 `count_games_by_owner()` 추가.
- MockStocks 생성 API에 optional `name` 필드 추가. 미입력 시 `모의주식 N · {game_id}` 자동 생성 후 활성/이력 목록 응답에 포함.
- `MockStocksNewPage`에 게임 이름 입력칸 추가. 배틀로얄/보스전 placeholder와 VITE_MOCK 목록 데이터도 새 형식으로 정리.
- 커밋 `5105e10` 생성 및 `origin/seongjin` push 완료.
- Draft PR #68 생성: https://github.com/26-CloudAI/loa-main/pull/68

### 검증
- `backend/.venv/bin/pytest backend/MockStocks/tests -v` → 9 passed, 4 skipped
- `backend/.venv/bin/pytest backend/BattleRoyale/tests/test_startup_db_failure.py -v` → 2 passed
- `npx eslint src/dev/mock.ts src/pages/MockStocksNewPage.tsx src/pages/GameNewPage.tsx src/pages/BossBattlePage.tsx src/pages/GamesPage.tsx` → 0 errors, 1 existing warning (`GamesPage` hook dependency)
- `npm run build` → passed
- `npm run lint` 전체 실행은 기존 unrelated React rule 오류들(`AuthContext`, `MockStocksWatchPage`, `WatchPage`) 때문에 실패.

### 다음 작업
- [ ] PR #68 머지 후 배포
- [ ] 배포 후 신규 생성 게임이 `배틀로얄 N · id`, `보스전 N · id`, `모의주식 N · id`로 보이는지 실제 계정에서 확인
- [ ] 기존 MockStocks 과거 레코드(`name` NULL)는 fallback `게임 {shortId}`로 남는지 확인

## 2026-05-09 — Codex — Cloud Run startup DB 블로킹 방어

### 완료 항목
- Cloud Run 배포 실패 원인인 lifespan 내 동기 DB 초기화 블로킹을 완화.
- BattleRoyale/MockStocks PostgreSQL 연결에 `DB_CONNECT_TIMEOUT`, `DB_STATEMENT_TIMEOUT_MS`, `DB_LOCK_TIMEOUT_MS` 설정 추가.
- BattleRoyale/MockStocks lifespan에서 `init_db()` + `cleanup_stale_games()`를 executor + 35초 timeout으로 실행하도록 변경.
- DB 초기화 실패 시 서버는 기동을 계속하고, BattleRoyale DB 의존 API는 `503 DB를 사용할 수 없습니다.`를 반환하도록 방어.
- MockStocks startup migration에서 락 대기 위험이 큰 `DELETE FROM stock_games WHERE owner_uid IS NULL` 제거. 기존 owner 없는 레코드는 owner 필터에서 자연스럽게 제외되므로 startup에서 삭제하지 않음.
- DB startup 실패 회귀 테스트 추가:
  - `backend/BattleRoyale/tests/test_startup_db_failure.py`
  - `backend/MockStocks/tests/test_startup_db_failure.py`

### 검증
- `backend/.venv/bin/pytest BattleRoyale/tests/test_startup_db_failure.py -v` → 2 passed
- `backend/.venv/bin/pytest MockStocks/tests/test_startup_db_failure.py -v` → 1 passed
- `backend/.venv/bin/pytest MockStocks/tests/test_stock_game_repository.py MockStocks/tests/test_game_session_db_persistence.py -v` → 6 passed
- `backend/.venv/bin/pytest BattleRoyale/tests/test_server.py BattleRoyale/tests/test_startup_db_failure.py -v` → 26 passed
- `backend/.venv/bin/pytest BattleRoyale/tests/test_db_auth.py -v`는 기존 `AuthService` import 불일치로 collection 실패. 이번 변경과 무관.

### 추가 완료 (같은 세션)
- **`test_db_auth.py` 정리**: `AuthService`, `generate_salt`, `hash_password`, `verify_password` import 제거.
  `_create_test_user()`를 `firebase_uid` 기반 `UserRepository.create()`로 수정.
  `TestGameRepo`에 `create_game()` 신규 파라미터 `owner_user_id` 반영.
  `TestPasswordHashing`, `TestAuthService` 클래스 제거. → 31 passed.
- **PR #67 생성**: https://github.com/26-CloudAI/loa-main/pull/67

### 다음 작업
- [ ] PR #67 머지 후 Cloud Run 재배포 → startup probe 통과 확인
- [ ] `/battleroyale/health`, `/stocks/health` 응답 확인
- [ ] PostgreSQL/Cloud SQL Auth Proxy 환경에서 실제 startup 동작 검증

## 2026-05-08 — Claude Code — MockStocks 게임 목록 owner 필터링 구현

### 배경
GCP 배포 후 확인하니 게임 목록에 다른 계정이 만든 MockStocks 게임도 같이 표시되는 버그 발견.
BattleRoyale은 `owner_user_id` 기반 필터가 있었지만 MockStocks엔 없었음.

### 완료 항목
- **`schema.py`**: `stock_games` 테이블에 `owner_uid TEXT` 컬럼 추가. SQLite/PostgreSQL DDL 양쪽 수정. `ALTER TABLE ... ADD COLUMN` 마이그레이션 추가.
- **`game_repo.py`**: `StockGameRecord`에 `owner_uid` 필드 추가. `create_game()`에 `owner_uid` INSERT. `get_finished_games()`에 `owner_uid` 필터 추가. `_row_to_game()` safe key check 추가.
- **`game_session.py`**: `GameSession.__init__`에 `owner_uid` 파라미터 추가. `start()`에서 `repo.create_game(owner_uid=...)` 전달. `GameRegistry.create_game()`에 `owner_uid` 파라미터 추가. `list_games(owner_uid=None)` 필터 추가.
- **`app.py`**: `_get_uid()` 헬퍼 (Firebase 토큰 검증, 실패 시 None). `_require_uid()` 헬퍼 (None이면 HTTP 401). `POST /api/games`, `GET /api/games`, `GET /api/games/history` 세 엔드포인트에 `_require_uid()` 적용.
- **`MockStocksNewPage.tsx`**: 게임 생성 POST 요청에 `Authorization: Bearer` 헤더 추가.
- **`GamesPage.tsx`**: MockStocks 목록/히스토리 GET 요청에 `Authorization: Bearer` 헤더 추가.
- **NULL 레코드 정리**: 마이그레이션 시 기존 `owner_uid IS NULL` 행 DELETE (SQLite/PostgreSQL 양쪽).

### 코드 리뷰 지적 사항 반영
- 인증 실패(토큰 없음/만료) 시 `None` → 전체 목록 노출 문제 → `_require_uid()`로 401 반환으로 수정.

### 커밋
- `0fd9c99` — feat: MockStocks 게임 목록 owner UID 기준 필터링
- `619e681` — fix: 인증 실패 시 401 반환 (전체 목록 노출 방지)
- `46c946c` — fix: 서버 시작 시 owner_uid 없는 MockStocks 기록 삭제

### PR
- PR #66 머지 → Cloud Build 배포 진행 중

### 다음 액션
- [ ] 배포 완료 후 두 계정으로 게임 목록 격리 E2E 확인
- [ ] result/delete/ws 엔드포인트 owner 검증 (P1 미처리 항목)

---

## 2026-05-08 — Claude Code — BattleRoyale `count_games_by_mode` PostgreSQL 버그 수정

### 문제
Cloud Run 로그에서 게임 생성 시 `KeyError: 0` 발생.
원인: `count_games_by_mode()`에서 `SELECT COUNT(*)` 결과를 `row[0]`으로 접근하는데,
PostgreSQL `RealDictCursor`는 dict 반환 → 정수 인덱스 접근 불가.

### 수정
`SELECT COUNT(*) AS cnt`로 변경, `row["cnt"]`로 접근.
배틀로얄/보스전 모드 모두 게임 생성 불가 상태였음.

### 커밋 / PR
- 커밋 `2491459`, PR #65 머지 완료

---

## 2026-05-08 — Claude Code — seongjin 브랜치 병합 검증 완료

- 커밋 `96387e6` (main → seongjin 병합), `6997834` (종료 팝업 결과 보기 버튼) 최종 확인.
- 종료 팝업 버튼 4개 동작 확인: 결과 보기(`/games/{id}/mock-stocks/result`), 새 게임 만들기, 메인 홈, 관전 계속 보기.
- 라우팅 3개 정상 등록 (`App.tsx`): `/new`, `/watch`, `/result`.
- `GamesPage`: 활성 → watch, 종료 → result 분기 정상.
- 백엔드 엔드포인트 `GET /api/games/history`, `GET /api/games/{id}/result` 정상 등록.
- TypeScript 빌드 ✓ (131ms, 오류 없음), pytest 6 passed 4 skipped.
- **다음 액션**: push → PR (`seongjin` → `main`), 배포 후 E2E 확인.

---

## 2026-05-08 — Codex — main MockStocks 관전 UI 병합

- `main`의 팀원 MockStocks 관전 페이지 전면 개편 커밋을 `seongjin`에 merge 완료 (`96387e6`). 텍스트 충돌 없음.
- 팀원 작업 유지: `MockStocksNewPage.tsx` 새 게임 생성 후 `/watch?bot=...` 이동, `MockStocksWatchPage.tsx` 수익률 그래프/종목 현황/뉴스 배너/종료 팝업 UI.
- seongjin 작업 유지: `GamesPage.tsx` MockStocks 활성/이력 병합, 종료 게임 결과 페이지 이동, `App.tsx` 결과 라우트, DB 결과 API.
- 접점 보완: 종료 팝업에 `/games/{game_id}/mock-stocks/result`로 이동하는 “결과 보기” 버튼 추가.
- 검증: `npx tsc --noEmit`, `python3 -m compileall -q backend/MockStocks/src/stocks backend/MockStocks/tests`, `backend/.venv/bin/python -m pytest backend/MockStocks/tests -q` → 6 passed, 4 skipped.

### 다음 액션
- [ ] 종료 팝업 결과 보기 버튼 변경분 커밋 여부 결정
- [ ] push/PR 전 `git status`, `git diff main..HEAD --stat` 확인

---

## 2026-05-08 — Claude Code — MockStocks 결과 상세 페이지 + PG 스모크 테스트

### 완료 항목
- **`test_pg_smoke.py` 신규**: PostgreSQL 환경 스모크 테스트 (init_db, CRUD, get_finished_games, cleanup_stale_games). `DB_TYPE=postgresql` + `DB_HOST` 미설정 시 자동 스킵.
- **`GET /api/games/{id}/result` DB 폴백**: in-memory snapshot 없으면 `repo.get_game()` + `repo.get_participants()` 조회 → `{game_id, status, rankings}` 반환. 서버 재시작 후 종료 게임도 결과 조회 가능.
- **`MockStocksResultPage.tsx` 신규**: `/games/:id/mock-stocks/result` 라우트. 랭킹 테이블(순위/봇명/최종자산/수익률), AI 필러 봇 흐림 처리, 메타(final_tick, end_reason, finished_at) 표시.
- **`App.tsx` 수정**: `/games/:game_id/mock-stocks/result` 라우트 추가.
- **`GamesPage.tsx` 수정**: finished MockStocks "결과 보기" 버튼 활성화 → `/mock-stocks/result` 이동.

### 검증
- `python3 -m compileall -q backend/MockStocks/src/stocks backend/MockStocks/tests` 통과
- `backend/.venv/bin/python -m pytest backend/MockStocks/tests -q` → 6 passed, 4 skipped
- `npx tsc --noEmit` 통과
- 커밋: `7d2c485`

### 다음 세션 시작점
- [ ] push → PR → main 병합 후 배포 E2E 확인
- [ ] PostgreSQL 실제 연결 환경에서 `test_pg_smoke.py` 실행
- [ ] 해설 타임아웃 개선
- [ ] `google.generativeai` → `google.genai` 마이그레이션
- [ ] `mock_db` → `BotRepository` 전환

---

## 2026-05-08 — Claude Code — MockStocks DB 저장 로직 신규 구현

### 배경
MockStocks 게임 모드에는 DB 저장 로직이 전혀 없었음 (게임 결과 인메모리에만 존재). BattleRoyale의 DB 패턴을 그대로 따르되, stock_ prefix 독립 테이블로 같은 ai_arena DB에 공유하는 방식으로 설계.

### 완료 항목
- **`db/` 디렉터리 신설**: `__init__.py`, `schema.py`, `game_repo.py` 생성
- **`schema.py`**: `stock_games`, `stock_game_participants` 테이블 DDL (SQLite + PostgreSQL 양쪽). `init_db()`, `get_connection()` 팩토리 함수. BattleRoyale `schema.py`와 동일한 `DB_TYPE` 분기 패턴.
- **`game_repo.py`**: `StockGameRepository` 전체 구현 — `create_game`, `get_game`, `update_game_started`, `update_game_finished`, `add_participant`, `update_participant_result`, `get_participants`, `get_recent_games`, `cleanup_stale_games`. `_is_pg` 플래그 + `_execute()` / `_now()` 헬퍼로 SQLite/PostgreSQL 분기.
- **`settings.py` 수정**: DB 환경변수 5개 추가 (`DB_TYPE`, `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`). BattleRoyale와 동일한 env var명으로 같은 DB 연결.
- **`bot_interface.py` 수정**: `is_ai_filler: bool = False` 속성 추가. game_session에서 AI 필러 여부 판별 가능.
- **`game_session.py` 수정**: `GameSession` / `GameRegistry`에 `repo` 파라미터 연동. start() 시 `create_game` + `add_participant` × N + `update_game_started` 호출. `_run_loop()` 종료 시 `update_game_finished` + `update_participant_result` × N 호출. profit_rate = (final_value - initial_cash) / initial_cash × 100 자동 계산.
- **`app.py` 수정**: `asynccontextmanager` lifespan 추가 → `init_db()` + `StockGameRepository` 생성 + `cleanup_stale_games()`. filler 봇 생성 시 `is_ai_filler=True` 전달.

### 설계 결정
- BattleRoyale `bots` 테이블 FK 없음 — MockStocks는 봇 등록 시스템 없고 bot_id가 단순 문자열
- `is_ai_filler` 판별은 BotInterface 레벨에서 처리 (app.py에서 filler 생성 시 명시)
- repo가 None이면 DB 호출 조용히 스킵 → 기존 코드 경로 하위호환

### 리뷰 후 보완 (2026-05-08)
- **P1 — PostgreSQL 참가자 추가 커밋 누락 수정**: `StockGameRepository.add_participant()`의 PostgreSQL 분기에서 `RETURNING id` 직후 바로 return하지 않고, SQLite와 동일하게 `self.conn.commit()`을 거친 뒤 participant id를 반환하도록 수정.
- **P1 — 게임 종료 UX와 DB 저장 실패 분리**: `_run_loop()` 종료 시 `update_game_finished()` / `update_participant_result()`를 `try/except`로 감싸 DB 저장 실패가 발생해도 `game_end` WebSocket 브로드캐스트가 막히지 않도록 변경.
- **P2 — 수동 삭제/중단 DB 상태 기록**: `GameSession.stop()`에서 `waiting/loading/running` 상태의 세션을 중단하면 `end_reason='cancelled'`로 DB 종료 상태를 남김. 이미 `finished`인 세션은 `cancelled`로 덮어쓰지 않도록 보호.
- **SQLite 기준 테스트 추가**: `backend/MockStocks/tests/conftest.py`, `test_stock_game_repository.py`, `test_game_session_db_persistence.py` 추가. repository CRUD/cleanup, `_run_loop()` 정상 종료 저장, `stop()` cancelled 저장, 이미 finished인 게임 덮어쓰기 방지 검증.
- **MockStocks 게임 목록 연동 P1/P2 보완**: GamesPage MockStocks 관전 경로를 실제 라우트(`/games/{id}/mock-stocks/watch`)로 수정. `/api/games/history`는 `StockGameRepository.get_finished_games()`를 통해 finished 게임만 반환하도록 변경하고 테스트 추가.

### 검증
- `python3 -m compileall -q backend/MockStocks/src/stocks` 통과
- 간단한 인라인 확인: 진행 중 세션 `stop()` 시 `cancelled` 저장 호출, 이미 `FINISHED`인 세션 `stop()` 시 DB 갱신 생략 확인
- `backend/.venv/bin/python -m pytest backend/MockStocks/tests -q` → 6 passed
- `.venv/bin/python -m pytest backend/MockStocks/tests -q` → 6 passed
- `python3 -m compileall -q backend/MockStocks/src/stocks backend/MockStocks/tests` 통과
- `npx tsc --noEmit` 통과

### 다음 세션 시작점
- [ ] MockStocks 결과 상세 페이지/API 추가 (종료 게임의 “결과 보기” 활성화)
- [ ] PostgreSQL 실제 연결 환경에서 DDL/CRUD 스모크 테스트
- [ ] 해설 타임아웃 개선
- [ ] `mock_db` → `BotRepository` 전환

---

## 2026-04-27 — Claude Code — 멀티에이전트 협업 환경 초기화

- 팀 컨벤션 조사 완료 (README, pyproject.toml, git log, 브랜치 패턴)
- Personal mode(A)로 AGENTS.md, WORK_LOG.md 생성
- `.git/info/exclude`에 개인 파일 등록 (팀 .gitignore 미수정)
- GitHub main → 로컬 main fast-forward 동기화 (2커밋 업데이트)
- 워크트리 3개 경로를 loa-backend → loa-main으로 수정
- 워크트리 현황 파악: naughty-jang(Gemini 해설 미커밋), sad-cannon(RL봇+프론트, main 병합완료), upbeat-ishizaka(서버설정, 미병합)
- 기존 CLAUDE.md 확인 — 건드리지 않음, AGENTS.md에서 follow 명시

**다음 세션 주의사항**:
- `commentary_service.py`는 `.claude/worktrees/naughty-jang/backend/src/arena/server/`에 있음
- seongjin 브랜치에 반영하려면 해당 파일을 수동 복사 후 커밋 필요
- `claude/sad-cannon-745f79`의 변경사항을 seongjin에 merge할지 여부 결정 필요

---

## 2026-04-29 — Claude Code — 배포 인프라 안정화 + owner 기반 게임 기록

### 완료 항목
- Firebase Hosting GitHub Actions CI/CD 연동 (프론트 자동 배포)
- Firebase Auth SDK 로그인 버그 수정 (stale 세션 캐시 문제 확인)
- `games.owner_user_id` 컬럼 + 인덱스 추가 (`schema.py`)
- `GameRepository.list_games_by_owner()` / `get_game_by_owner()` 구현
- 전 API 엔드포인트 owner 검증 적용 (`app.py`)
- 프론트 4개 페이지 Bearer 토큰 / WS `?token=` 전달
- **Redis REDIS_HOST 버그 수정**: `run_server.py` `--redis-host` default `"localhost"` → `None` + `os.environ.get("REDIS_HOST", "localhost")`
- **좀비 게임 정리**: `cleanup_stale_games()` 구현, 서버 lifespan 시작 시 호출
- Cloud Run 크래시 원인: `schema.py` 인덱스 선언 순서 버그 → 수정
- `.gitignore`에 `.firebase/` 추가
- 워크트리 2개(`naughty-jang`, `upbeat-ishizaka`) 삭제 (이미 main에 반영됨)
- 로컬 main → origin/main 동기화 (`git reset --hard origin/main`)
- PR #41, #42 생성·병합, Cloud Run / Firebase Hosting 자동 배포 완료
- 전체 시스템 동작 확인: 로그인 → 게임 생성 → 진행 → 기록 저장

### 확인된 설계 한계 (문서화)
1. **WebSocket owner-only 관전**: 브라우저 WS는 Authorization 헤더 불가 → `?token=` query param. 현재는 owner만 관전 가능 (다른 사용자 관전 미지원)
2. **좀비 게임 정리 timing**: Cloud Run 인스턴스가 급사(SIGKILL)하면 cleanup 없이 종료됨. 다음 인스턴스 시작 시 `cleanup_stale_games()`가 DB 정리. 단, 다중 인스턴스 환경에서는 경쟁조건 가능.

### 트러블슈팅
| 문제 | 원인 | 해결 |
|------|------|------|
| 게임 생성 시 Redis `localhost:6379` 연결 실패 | `run_server.py` --redis-host default 하드코딩 | `None` + env var fallback |
| 서버 재시작 후 게임 목록에 좀비 레코드 | lifespan cleanup 없음 | `cleanup_stale_games()` 추가 |
| Cloud Run 크래시 (시작 직후) | schema.py 인덱스 컬럼 순서 오류 | 수정 |
| 로그인 후 재접속 시 인증 실패 | 브라우저 Firebase 세션 캐시 만료 | 시크릿 창 테스트 / IndexedDB 삭제 안내 |

### 다음 세션 시작점
- [ ] 해설 타임아웃 개선
- [ ] 해설 탭 UI/디자인 개선
- [ ] `google.generativeai` → `google.genai` 마이그레이션
- [ ] `mock_db` → `BotRepository` 전환

---

## 2026-04-29 — Claude Code — 멀티에이전트 킷 정비

**배경**: 에이전트가 세션 시작 시 `AGENTS.md`를 자동으로 읽지 않는 문제 발견 (CLAUDE.md 없음, AGENTS.md는 exclude에만 등록).

### 완료 항목
- **`.claude/CLAUDE.local.md` 생성** — Claude Code가 세션 시작 시 자동으로 읽는 파일. "AGENTS.md를 먼저 읽어라" 지시 포함. `.claude/`를 `.git/info/exclude`에 추가해 커밋 방지.
  - `CLAUDE.md`(팀 공유)가 아닌 `CLAUDE.local.md`를 선택한 이유: 팀 파일 무단 수정 금지 규칙 때문.
- **`GEMINI.md` 생성** — Gemini 에이전트용 동일 지시. `.git/info/exclude`에 추가.
- **exclude 패턴 정리** — `foranti.md` / `forgemini.md` / `forcopilot.md` 세 줄 → `for_*.md` 한 줄로 교체.
- **`AGENTS.md` 갱신** — `## After completing work` 섹션 추가 (작업 완료 후 에이전트 행동 규칙 명시), 2026-04-29 배포 작업 내용 반영.

### 다음 세션 시작점 (에이전트 킷)
- Copilot용 `COPILOT-INSTRUCTIONS.md` 또는 `.github/copilot-instructions.md` 필요 시 추가 (현재 미작성)

---

## 2026-04-27 — Claude Code — 워크트리 정리 및 seongjin 업데이트

- `sad-cannon-745f79` 워크트리: main을 seongjin에 merge 완료 (RL봇, 프론트-백 연결 등 반영)
- `sad-cannon-745f79` 워크트리 삭제 완료
- `upbeat-ishizaka` 워크트리: 충돌로 merge 보류, 내용 기록 후 새로 시작하기로 결정

**upbeat-ishizaka 미완료 작업 (새로 시작 필요)**:
- Phase 1: `settings.py` — 환경변수 기반 설정 중앙화 (USE_REDIS, JWT_SECRET, LOG_FORMAT, SERVER_PORT, CORS_ORIGINS, DB_*)
- Phase 2: `logging_config.py` — GCP Cloud Logging 호환 JSON 구조화 로깅, app.py에 레이트리밋(IP당 60초/3회), CORS_ORIGINS env var 적용, 5분 주기 세션 cleanup 태스크
- Phase 3: `schema.py` — SQLite/PostgreSQL DDL 분기 (DB_TYPE 환경변수), `get_connection()` 팩토리, `firebase.json` SPA 라우팅 rewrites
- **충돌 파일**: `schema.py`, `app.py`, `firebase.json` (팀 변경사항과 충돌 — 새로 작업 시 현재 파일 기준으로 재작성 필요)
- 참고 브랜치: `claude/upbeat-ishizaka` (커밋 `0101519`, 2026-04-03)

---

## 2026-05-19 — Claude Code — Kubernetes Phase 2 (RemoteBotAdapter + /healthz·/livez)

**브랜치**: `seongjin-kube` (`for_kubernetes_migration_plan.md` 기준 PR 2 범위)

### 완료 항목

#### 1. Bot Runner 설정 추가 (양 게임 모드)
- `BattleRoyale/src/arena/server/settings.py`, `MockStocks/src/stocks/server/settings.py`에 동일 env 추가:
  - `BOT_RUNNER_URL` (기본 `""` — 미설정 시 InProcess fallback)
  - `BOT_RUNNER_TIMEOUT_SEC` (기본 0.5 — HTTP 왕복 + spawn overhead 고려해 plan보다 여유)
  - `BOT_RUNNER_REQUIRED` (기본 false)

#### 2. RemoteBotAdapter 신규
- `BattleRoyale/src/arena/sandbox/remote_adapter.py` — `RemoteBattleRoyaleBotAdapter`
- `MockStocks/src/stocks/sandbox/remote_adapter.py` — `RemoteStockBotAdapter` (sandbox/ 디렉터리 자체 신규)
- `code_hash = "sha256:" + hashlib.sha256(code.encode()).hexdigest()`를 `__init__`에서 계산
- 매 tick `POST /run` 호출 (`mode`, `bot_id`, `code_hash`, `code`, `state` 전송)
- timeout/500/invalid JSON/connection refused → fallback (BR: `STAY`, MS: `{"action": "HOLD"}`)
- `urllib.request` 사용 (외부 의존성 추가 없음)

#### 3. create_game() 분기 로직
- 유저 봇만 `BOT_RUNNER_URL` 설정 시 Remote 사용, AI filler/boss는 in-process 유지
- BattleRoyale: `ENV == "production" and BOT_RUNNER_REQUIRED` → 503 (plan 일치)
- MockStocks: `BOT_RUNNER_REQUIRED` → 503 (plan 일치, MockStocks settings에 ENV 없음)

#### 4. /healthz · /livez 엔드포인트 (`run_server.py`)
- `/healthz` — readinessProbe용: 양 sub-app의 `app.state.db_ok()` 집계, 한 쪽이라도 실패 시 HTTP 503 + `{"status":"degraded", ...}`
- `/livez` — livenessProbe용: 항상 HTTP 200 + `{"status":"alive"}` (DB 체크 없음 — DB 장애로 Pod 재시작되면 메모리의 진행 중 게임이 날아감)
- 각 sub-app `create_app()`이 `app.state.db_ok = lambda: state.get("db_conn") is not None` 노출

### 테스트 (신규 26개, 모두 통과)
- BattleRoyale adapter 8개: 정상 응답, timeout, 500, invalid JSON, action 타입 검증, connection refused, code_hash payload 검증
- MockStocks adapter 7개: 동일 패턴
- create_game 분기 3개씩 × 2 모드 = 6개
- healthz/livez 5개: 정상/degraded(BR down)/degraded(MS down)/degraded(both down)/livez 200 고정

### Stop-hook이 잡아낸 critical bug
- **증상**: MockStocks remote 게임이 시작 직전 500
- **원인**: `RemoteStockBotAdapter.__init__`이 `super().__init__()` 미호출 → `is_ai_filler` 속성 부재 → `game_session.start()`의 `add_participant(is_ai_filler=bot.is_ai_filler)`에서 AttributeError
- **수정**: `super().__init__(bot_id, is_ai_filler=False)` 추가, 중복 `_bot_id`/`bot_id` property 제거
- BattleRoyale `BotInterface`는 `__init__`이 없어 해당 어댑터는 영향 없음
- 인터페이스 비대칭이 원인: BR은 `participant_specs` tuple로 ai_filler 관리, MS는 `bot.is_ai_filler` 직접 접근

### 검증
- 신규 테스트 26 passed
- BotRunner 78 passed (Phase 1 회귀 없음)
- BattleRoyale 203 passed (기존 결함 2개 제외 — `test_duplicate_name_per_user`, `test_valid_actions_complete`는 Phase 2 무관)
- MockStocks 19 passed, 4 skipped (PG smoke)

### 병행 운영 원칙 유지
- Cloud Run에서는 `BOT_RUNNER_URL` 미설정 → `InProcessBot` fallback 유지 (기존 동작 그대로)
- GKE에서만 `BOT_RUNNER_URL = http://bot-runner.arena.svc.cluster.local:8001` 설정 → Remote 활성화
- 프론트 API URL은 cutover(PR 7) 전까지 Cloud Run 유지

### Stop-hook이 잡아낸 무관 파일
- `backend/BattleRoyale/bots/trained_weights.json` (이전 로컬 RL 학습 결과물) → `git checkout HEAD --`로 되돌림. Phase 2 변경 set에서 제외.

### 다음 세션 시작점
- [ ] Phase 2 PR 2 생성 (브랜치 `seongjin-kube` → main)
- [ ] Phase 3: Kubernetes 매니페스트 작성 (`k8s/base/*.yaml`)

---

## 2026-05-26 — Claude Code — Phase 5: 이미지 빌드 + AR Push + 수동 GKE 배포 완료

### 배경
Phase 4에서 GKE 클러스터 `loa-arena` 생성/검증 완료. Phase 5 목표: 이미지 빌드 → AR push → Secret 생성 → kubectl apply → set image → rollout 확인 → health 검증.

### 이미지 빌드 + AR Push

| 이미지 | 태그 | 빌드 방식 | digest |
|--------|------|-----------|--------|
| server | `20260526-252082d` | `gcloud builds submit backend/` | `sha256:569d939a...` |
| bot-runner | `20260526-252082d` | `gcloud builds submit backend/bot_runner/` | `sha256:24f30dd7...` |

- 빌드 플랫폼: GCP Cloud Build (linux/amd64) — Apple Silicon Mac에서 로컬 빌드 시 exec format error 방지
- server: 최초 `/healthz`, `/livez` 포함 이미지 (Phase 2 seongjin-kube 엔드포인트 + BattleRoyale2 포함)
- bot-runner: **최초 빌드/push**

### 배포 순서

1. `kubectl apply -f k8s/base/namespace.yaml` → arena namespace 생성
2. `kubectl create secret generic arena-secrets -n arena ...` → Secret Manager 3개 + JWT 랜덤 생성
3. `kubectl apply -k k8s/base/` → 전체 리소스 생성 (Deployment는 `:PLACEHOLDER` → ImagePullBackOff 상태)
4. `kubectl -n arena patch configmap arena-config --patch='{"data": {"BOSS_WEIGHTS_GCS_URI": "gs://boss-weights/trained_weights.json"}}'`
5. `kubectl set image deployment/game-server game-server=.../server:20260526-252082d -n arena`
6. `kubectl set image deployment/bot-runner bot-runner=.../bot-runner:20260526-252082d -n arena`
7. `kubectl rollout status` 양쪽 성공

### 검증 결과

| 항목 | 결과 |
|------|------|
| `kubectl get pods -n arena` | game-server 1/1 Running, bot-runner 2/2 Running |
| `/healthz` | `{"status":"ok","battleroyale":{"db":"ok"},"stocks":{"db":"ok"}}` |
| `/livez` | `{"status":"alive"}` |
| `/battleroyale/health` | `{"status":"ok","active_games":0,"total_spectators":0}` |
| `/stocks/health` | `{"status":"ok"}` |
| bot-runner `/health` | `{"status":"ok"}` (pod 내부 exec로 확인) |
| bot-runner `/livez` | `{"status":"alive"}` (pod 내부 exec로 확인) |

### 특이사항

- **PodSecurity warn (game-server)**: `runAsNonRoot != true` — backend/Dockerfile에 USER 디렉티브 없음. 기존 설계 결정 유지 (checklist Phase 3 강화 항목). 기능 영향 없음.
- **bot-runner port-forward 실패**: gVisor(`runtimeClassName: gvisor`) 런타임에서 `kubectl port-forward`가 컨테이너 네트워크 namespace 직접 진입 실패. 이는 gVisor의 알려진 제약. Kubernetes health checker(`169.254.4.6`)의 probe 200 OK + `kubectl exec` 내부 curl로 정상 동작 확인.
- **Cloud Run**: 완전 독립. kubectl 명령은 GKE에만 영향. Cloud Run은 기존과 동일하게 정상 서빙 중.
- **BOSS_WEIGHTS_GCS_URI**: ConfigMap에 주입 완료. 단, Phase 6 WI 바인딩 전까지 GCS 실제 읽기는 실패 예상 (boss 게임에만 영향, 일반 BR/MS 게임 무관).

### 다음 단계
- Phase 7: gVisor Smoke Test (`kubectl exec` 기반으로 실행 — port-forward 대신)
- Phase 8: Ingress/LB가 올라온 후 E2E 검증
- Phase 6: Workload Identity 설정 (game-server → GCS boss weights 읽기)
- PR 4: seongjin-kube → main PR 생성 제안 (타이밍은 사용자 결정)

---

## 2026-05-26 — Claude Code — game-server non-root 전환 (보안 강화)

### 배경
Phase 5 배포 시 game-server에 PodSecurity 경고(`runAsNonRoot != true`)가 떴다. `backend/Dockerfile`에 `USER` 디렉티브가 없어 컨테이너가 root(uid 0)로 실행됐기 때문. bot-runner는 이미 `USER 10001`로 non-root였으나 game-server는 미적용 상태였음. 심층 방어 완성 + 경고 제거 목적으로 non-root 전환.

### 사전 안전성 검증 (코드 전수 조사)
non-root에서 깨질 런타임 쓰기 경로 확인:
- SQLite `ai_arena.db`: `init_db()`가 `DB_TYPE=="postgresql"`이면 `_init_postgresql()` 분기 (`schema.py:375`) → prod에서 sqlite 미생성
- GCS weights: `/tmp/boss_weights.json` (world-writable, non-root OK)
- `container_manager.py:149` `/app/temp_bots`: 옛 Docker 샌드박스, GKE 미사용 (`/app` chown으로 안전망)
- 그 외 파일 쓰기 없음 (로그 stdout/json)

### 변경
- `backend/Dockerfile`: `groupadd/useradd appuser(uid 10002)` + `chown -R /app` + `USER 10002` (bot-runner와 동일 패턴, uid만 구분)
- `k8s/base/game-server-deployment.yaml`: securityContext에 `runAsNonRoot: true` + `runAsUser: 10002` (deferral 주석 제거)
- 이미지: `server:20260526-252082d-nonroot` (`sha256:a21905c7...`)

### 검증
- `kubectl apply -k` 시 game-server PodSecurity 경고 **소멸**
- `kubectl exec -- id` → `uid=10002(appuser)` (이전 uid=0 → 전환 확인)
- health 전부 정상, RESTARTS 0, Permission denied 에러 없음
- 로그의 GCS WI 404 에러는 non-root 무관 (Phase 6 WI 미바인딩 사안, 기존부터 존재)

### 운영 gotcha 발견
`kubectl apply -k k8s/base/`는 **두 Deployment를 모두 `:PLACEHOLDER`로 되돌린다.** game-server만 업데이트하려 apply 했더니 bot-runner도 PLACEHOLDER로 리셋되어 새 ReplicaSet이 ImagePullBackOff 발생 (기존 pod은 롤링업데이트라 생존). → bot-runner `kubectl set image` 재실행으로 복구. **교훈: apply -k 후엔 game-server·bot-runner 양쪽 모두 set image 필요.** (또는 kustomize `images:` override 도입 검토 — 향후 PR 5 Cloud Build step에서 고려)

### Cloud Run 영향 (주의)
`backend/Dockerfile`은 Cloud Run과 공유. 이번엔 GKE에만 `kubectl set image` → Cloud Run 즉시 무관. 단 **다음 팀 Cloud Build 실행 시 Cloud Run도 non-root 이미지로 배포됨.** Cloud Run은 non-root 지원 + 동일 prod 경로라 안전하나 팀 공유 필요. 커밋은 안 함 (k8s 규칙: 제안만).

---

## 2026-05-26 — Claude Code — Phase 6 Workload Identity 설정 (game-server → GCS boss weights)

### 배경
game-server Pod이 `gs://boss-weights/trained_weights.json`을 ADC로 읽지 못하고 startup 시 `404 Gaia id not found`로 실패하던 문제. K8s SA `game-server`의 WI annotation은 이미 `game-server-sa@knu-2026-sungjin0418.iam.gserviceaccount.com`을 가리켰으나, 해당 **GCP SA가 존재하지 않아** 토큰 교환이 404 실패. Phase 6은 GCP SA 생성 + 권한·WI 바인딩으로 코드 변경 없이 GCS 읽기를 활성화.

### 사전 확인 (탐색)
- K8s SA `game-server` annotation 이미 적용됨(`last-applied-configuration` 포함) → **재apply 불필요** (apply 시 양쪽 Deployment PLACEHOLDER 리셋 gotcha 회피)
- K8s SA `bot-runner` `automountServiceAccountToken: false` 적용됨
- ConfigMap `arena-config`에 `BOSS_WEIGHTS_GCS_URI=gs://boss-weights/trained_weights.json` 설정됨
- 버킷/블롭 `gs://boss-weights/trained_weights.json` 존재
- `gcs_weights.py`는 `storage.Client()`(ADC) 사용 → 코드 변경 0

### 작업 (GCP IAM 3단계 + 재시작)
1. `gcloud iam service-accounts create game-server-sa --display-name "LOA game-server runtime"` (신규 생성, 기존 재사용 아님)
2. `gcloud projects add-iam-policy-binding ... --member=serviceAccount:game-server-sa@... --role=roles/storage.objectViewer --condition=None`
3. `gcloud iam service-accounts add-iam-policy-binding game-server-sa@... --role=roles/iam.workloadIdentityUser --member="serviceAccount:knu-2026-sungjin0418.svc.id.goog[arena/game-server]"`
4. `kubectl rollout restart deployment/game-server -n arena` (apply 안 함)

### 검증
- `kubectl exec deploy/game-server -- python3 -c "...storage.Client().bucket('boss-weights').blob('trained_weights.json').exists()"` → **`exists: True`**
- 새 Pod(`game-server-68fb5fc8d5-gmh7r`) 기동 로그: **`Weights downloaded: gs://boss-weights/trained_weights.json → /tmp/trained_weights.json`** (403/404 0건)
- bot-runner Pod env에 DB/Firebase/Gemini/JWT/SECRET/PASSWORD **없음**
- bot-runner Pod에 SA token mount **없음** (`/var/run/secrets/kubernetes.io/serviceaccount` 부재)

### 운영 gotcha 발견
GCP SA 신규 생성 직후 `iam.workloadIdentityUser` 바인딩 전파에 **30초~1분 지연**. 그 사이 기동한 첫 restart Pod의 startup GCS load가 `403 iam.serviceAccounts.getAccessToken denied`로 실패 → fallback. `gcs_weights.download()`는 예외를 삼키고 None을 반환하므로 직후 로그 `"보스봇 가중치 GCS에서 로드 완료"`는 **성공을 보장하지 않음**(무조건 출력). 전파 완료 확인(exec True) 후 **한 번 더 rollout restart**해야 startup에서 실제 다운로드 로그가 찍힘. → 첫 restart로 exec는 True지만 startup 로그가 403이었고, 두 번째 restart로 클린 startup 확보.

### 미커밋 / 후속
- 미커밋 파일: `backend/Dockerfile`, `k8s/base/game-server-deployment.yaml` (Phase 5 non-root분), `for_kubernetes_checklist.md`(Phase 6 [x] 갱신), `WORK_LOG.md`
- 커밋/PR은 직접 만들지 않음 (k8s 규칙: 제안만). 사용자 승인 시 `seongjin-kube` 브랜치로 커밋 제안 예정
- Cloud Run `ai-arena-server` 무관/생존 (cutover 전 rollback 대상, 삭제 금지)

---

## 2026-05-26 — Claude Code — Phase 7: gVisor Smoke Test (bot-runner Deployment Pod)

### 배경
Phase 6 완료(WI + GCS boss weights 읽기 성공) 후, 실제 bot-runner Deployment Pod에서
`executor.py`가 사용하는 syscall이 gVisor(runsc) 위에서 동작하는지 재확인.

### executor.py 분석
- `multiprocessing.get_context("spawn")` — fork 아닌 spawn (Python 인터프리터 새로 exec)
- child에서 `resource.setrlimit(RLIMIT_CPU/AS/FSIZE/NPROC)` 적용
- `signal.signal(SIGALRM) + signal.alarm()` timeout
- `/tmp` emptyDir(tmpfs) 쓰기

### 작업
1. `/tmp/smoke.py`를 bot-runner Pod에 생성 (스크립트 파일 방식 — spawn context는 `python -c` 방식에서 `__main__` pickle 실패함)
2. `kubectl exec deploy/bot-runner -n arena -- bash -c 'cat > /tmp/smoke.py ... && python /tmp/smoke.py'` 실행

### 검증 결과
```
mp ok
rlimit ok
signal ok
tmpfile ok
```
→ **4항목 전부 통과.** gVisor 위에서 spawn/setrlimit/SIGALRM/tmpfs 모두 정상 동작.

### 운영 gotcha 발견
`kubectl exec -- python -c '...'` + spawn context 조합은 실패함.
spawn context의 child process가 `__main__` 모듈에서 함수(예: `_w`)를 unpickle 시도하지만,
`python -c` 기반 `__main__`은 built-in 모듈이라 함수를 찾지 못해 `AttributeError` 발생.
→ smoke test는 반드시 스크립트 파일(`/tmp/smoke.py`) 방식으로 실행해야 함.

### 다음 단계
Phase 8 — Kubernetes Smoke / E2E 테스트 (Ingress URL 점검부터 시작)

---

## 2026-05-26 — Claude Code — Phase 8: Kubernetes Smoke / E2E 테스트 (완료)

### 핵심: Ingress LB가 6시간+ 미프로비저닝 → 근본원인 진단·복구
- 증상: `kubectl -n arena get ingress`의 ADDRESS가 6시간 넘게 비어 있음. NEG·backend service·URL map·forwarding rule 전부 미생성. SSL 인증서(ManagedCert)만 생성돼 있었음.
- **근본 원인**: Phase 3 검토 #6에서 `kubernetes.io/ingress.class: "gce"` annotation을 제거하고 `spec.ingressClassName: gce`만 남겼는데, **GKE 1.35 Autopilot GLBC가 spec.ingressClassName 단독으로는 NEG/LB 생성을 트리거하지 않음**. (deprecated 정리 의도가 역효과.)
- **복구**:
  1. `kubectl -n arena annotate ingress arena-ingress kubernetes.io/ingress.class=gce` → 즉시 NEG 생성 시작
  2. NEG → backend service 생성됐으나 backend에 NEG가 attach 안 됨 → `kubectl label ingress` touch로 재조정 강제 → NEG attach 완료
  3. URL map/target proxy(HTTP+HTTPS)/forwarding rule(80/443) 생성, IP `8.233.221.199` 할당
  4. 초기 Connection Reset(`ConnectionResetError`)은 **GFE 전파 지연** — 수 분 후 자체 해소, 헬스 4종 200
- **영속화**: `k8s/base/ingress.yaml`에 annotation 복원(spec 필드는 호환 위해 병기). 커밋 `0e1d0bf`.
- 교훈: 이 클러스터/버전에서는 GCE Ingress에 annotation+spec 둘 다 둘 것.

### bot-runner P1(RLIMIT_NPROC) 수정 → 커밋·재빌드·재배포·prod 검증
- 작업 트리에 있던 `executor.py` 미커밋 수정(`multiprocessing.Queue`→`SimpleQueue`, `get_nowait` try/except→`empty()`+`get()`)이 바로 P1 수정이었음.
- **버그 메커니즘**: `Queue`는 백그라운드 feeder thread로 파이프에 기록. child에 `RLIMIT_NPROC(0,0)`이 걸리면 feeder thread fork가 막혀 결과 유실 → game-server는 STAY/HOLD fallback 처리. `SimpleQueue`는 put 시 동기적으로 파이프에 직접 기록(feeder thread 없음)이라 RLIMIT 하에서도 정상.
- **prod 실증**: 기존 이미지(`252082d`) `POST /run`(MOVE_UP 봇) → `{"ok":false,"action":"STAY","error":"no result received from child process"}`. SimpleQueue 이미지(`20260526-0e1d0bf`) 재배포 후 → `{"ok":true,"action":"MOVE_UP"}`. stocks 모드(INQUIRY)도 정상.
- 절차: `pytest bot_runner/tests/` 78 passed → 커밋 `8eb3e68` → `gcloud builds submit`(`bot-runner:20260526-0e1d0bf`, digest `sha256:bc62439...`) → `kubectl set image`(apply 회피, PLACEHOLDER gotcha) → rollout 2/2 gvisor 유지.

### Smoke 결과 (전부 통과)
- pods/svc/ingress 상태, 헬스 4종(GKE Ingress) 200, Cloud Run 병행 헬스 200
- gVisor: bot-runner 2개 모두 `gvisor`
- NetworkPolicy: game-server↔bot-runner 통신 OK / bot-runner egress 차단(URLError) / 횡방향 차단(임시 Pod→game-server:80 timed out) / Ingress 헬스체크 backend HEALTHY + 방화벽 `k8s-fw-l7--...` 130.211.0.0/22·35.191.0.0/16→8080
- NetworkPolicy는 **Dataplane V2(ADVANCED_DATAPATH) eBPF로 실제 적용**됨 (레거시 `networkPolicyConfig` addon은 disabled지만 무관)

### E2E 결과 (Firebase 토큰, 전부 통과)
- 인증: ENV=production → mock auth 불가. Firebase REST `signInWithPassword`(공개 Web API key `AIza...g24`, 프로젝트 ai-arena-b2b4b)로 테스트 계정 `kubetest@arena.dev` ID 토큰 발급.
- 로그인(`/api/me` user 17), BattleRoyale(`23cffa85` 200틱), Boss(`a9e0323f` 84틱), MockStocks(`5e40c6aa` 200틱) 생성→종료→결과 전부 200. 유저 봇 실제 action 수행(STAY fallback 아님, 로그에 bot-runner 에러 없음).
- 목록/owner filtering OK(kubetest 소유만), os.environ 봇 `forbidden import: os` 차단, WebSocket `101 Switching Protocols`+tick 수신(BackendConfig timeoutSec 3600 적용).

### Codex adversarial review (needs-attention, 기존 코드)
`main..HEAD` 전체(bot_runner 서브시스템 포함) 대상. 내 4줄 수정이 아닌 **기존 코드** 3건:
- [high] executor.py 타임아웃 미준수 (child alarm 최소 1s > game-server 0.5s timeout, worker 백로그) — 기존 known DoS
- [high] stocks 출력 무검증 (공격자 dict 전체 반환, 거대 문자열/수량 DoS) — 기존 known DoS
- [medium] SAFE_BUILTINS 블랙리스트 허점 (license/help/credits site helper로 open 없이 파일 읽기 가능) — **신규**
→ 현재 인증+레이트리밋+egress 차단+시크릿 미마운트로 게이트. **Phase 10 cutover 전 수정 권장**. 별도 세션 예정.

### 미커밋 / 후속
- 커밋됨: `8eb3e68`(executor SimpleQueue), `0e1d0bf`(ingress class annotation)
- 미커밋: `for_kubernetes_checklist.md`(Phase 8 [x]), `WORK_LOG.md` — 커밋 제안만(k8s 규칙)
- bot-runner DoS/샌드박스 3건 별도 수정 세션
- Cloud Run `ai-arena-server` 생존(삭제 금지)
- 클러스터 비용: 작업 종료 시 삭제 검토

---

## 2026-05-26 — Claude Code — bot-runner DoS/샌드박스 3건 수정·배포 (커밋 6676e5a)

사용자 요청으로 Codex가 Phase 8에서 지적한 bot-runner 3건을 수정. 푸시도 완료(seongjin-kube: 8eb3e68/0e1d0bf/6676e5a).

### 수정 내용
1. **타임아웃 미준수**: `signal.alarm`(0.1s→1s 올림) → `signal.setitimer(ITIMER_REAL, sub-second)`. parent `process_timeout`을 `+5.0`→`+_PROCESS_GRACE_SEC`(env `BOT_PROCESS_GRACE_SEC`, 기본 1.0). `main.py`에 `BoundedSemaphore(workers)` 백프레셔(포화 시 즉시 폴백, `runner saturated`).
2. **stocks 출력 무검증**: `_validate` 고정 스키마 정규화(action/symbol≤64자/quantity bool아닌 int 0≤q≤1e9). **검증을 child 안으로 이동**이 핵심 — parent 검증은 오버사이즈 출력(>~64KB)이 SimpleQueue pipe 버퍼 초과로 **데드락**(테스트 중 직접 발견). child 정규화로 작은 결과만 IPC 통과.
3. **SAFE_BUILTINS allowlist 전환**: 블랙리스트→`_ALLOWED_BUILTINS`+`BaseException` 서브클래스만. site helper(license/help/credits/copyright/exit/quit)·open/exec/eval/getattr류 제외. **exec ns에 `__name__` 추가**(클래스 정의 `__module__` 해석 — 기존 블랙리스트는 `vars(builtins)`의 모듈 `__name__`을 우연히 포함).

### 검증
- 테스트 11건 추가(`test_dos_hardening.py`), 기존 78 회귀 없음 → **89 passed**. (타임아웃 테스트 3.66s→2.45s)
- 이미지 `bot-runner:20260526-6676e5a` 빌드/재배포(2/2 gvisor Running). prod 실증:
  - 무한루프 봇 **0.39초** 폴백(이전 5.1s), 정상 BR/stocks 봇 정상
  - 100KB symbol→HOLD, evil 키 스트립, `str(license)`→`name 'license' is not defined` 차단

### Codex 재리뷰 — 별개 신규 3건 (미수정, 더 광범위한 diff)
1. **[critical] BotRunner fail-open** (`mock_stocks/app.py:337-348`, BR 동일): `BOT_RUNNER_URL` 미설정+`BOT_RUNNER_REQUIRED=false`면 `InProcessBot` 폴백. **Cloud Run은 의도적 InProcessBot**(병행 설계), GKE는 fail-closed 정상. ENV=production 필수화 제안은 Cloud Run 설계와 충돌 → 팀 결정.
2. **[high] readiness 영구 latch** (`run_server.py:143-154`): DB startup 실패 시 `/healthz` 503 고정, `/livez` 200 → Pod 영구 NotReady, 재시작 안 됨. fatal 또는 백그라운드 재시도 필요.
3. **[high] BattleRoyale2 WS 무인증** (`BattleRoyale2/server/ws_server.py:181-205`): main 머지 Godot 게임 소켓이 토큰/Origin 없이 연결+봇 루프 → DoS. mount 게이트 또는 인증 추가 필요.
→ 3건 모두 별개 작업, Phase 10 cutover 전 결정 필요. [[project_botrunner_dos_findings]] 기록.

---

## 2026-05-26 — Claude Code — A1 readiness 영구 latch 수정 (Codex 재리뷰 #2)

Codex 재리뷰가 지적한 신규 3건 중 **A1만** 처리(A2 fail-open/A3 BR2 WS는 별개·팀 결정 대기). 미커밋(seongjin-kube).

### 문제
`run_server.py`의 `/healthz`(readiness)가 `br_app.state.db_ok()`/`ms_app.state.db_ok()` 종합. 2026-05-09 "startup DB 비차단" 설계로 DB init 실패해도 프로세스는 살지만(`/livez` 200), `db_ok`를 다시 채우는 경로가 없어 `/healthz`가 **영구 503** → Pod 영구 NotReady, k8s가 재시작도 안 함.

### 수정 (백그라운드 재시도 self-heal)
핵심 통찰: 두 `db_ok` 람다가 **live mutable state를 늦은 평가**로 읽음(BR `state["db_conn"]`, MS `registry._repo`). 따라서 lifespan이 실패 후 백그라운드로 state를 채우기만 하면 `/healthz`가 자동 200 flip → `/healthz`·`db_ok`·`run_server.py` **무변경**.
- BR/MS `app.py`: 첫 시도는 `DB_INIT_TIMEOUT_SEC`(기본 35s) 안에서만 기다리고(startup 비차단, shield로 executor 살려둠), 실패/타임아웃 시 `_db_retry_loop`가 `DB_RETRY_INTERVAL_SEC`(기본 10s)마다 `await _init_once()`로 **직렬** 재시도. 성공하면 종료. shutdown에서 retry/finalize/startup 태스크 cancel.
- MS는 늦게 생긴 conn도 닫도록 lifespan 로컬 `conn`을 `conn_holder`로 교체.
- `settings.py`(BR/MS): `DB_INIT_TIMEOUT_SEC`, `DB_RETRY_INTERVAL_SEC` 추가.

### Codex 적대적 리뷰 5회 반복 → 단순화 결정 (사용자)
리뷰가 점점 깊은 엣지케이스를 지적: ①timeout이 executor 스레드 미중단(누수/중첩) ②멈춘 future를 await하면 복구 막힘 ③상한 saturate 시 복구 불가 ④**cleanup이 늦은 시도에서도 돌아 라이브 게임 손상**. 사용자 지시로 **"중요한 것만 + 단순화"** 채택:
- **유지(중요)**: ④ 수정 — `cleanup_stale_games`(destructive, waiting/running→error)를 `_init_repositories`에서 **분리**. `_accept_winner`가 첫 성공 결과만 승자로 채택해 **승자 연결로 1회만**, readiness flip(=게임 생성 가능) **전에** 정리. 패자/늦게 끝난 시도는 conn만 닫고 정리 재실행 안 함 → 라이브 게임 보호.
- **되돌림(과한 방어)**: wedge→liveness(`/livez` 503 + `db_wedged` + `DB_WEDGE_DEADLINE_SEC`), `inflight` 동시상한 카운터 전부 제거. 재시도는 `await`로 자연 직렬화(중첩 ~2개 이하). **run_server.py·liveness 원복(Cloud Run 무영향).**

### 알려진 한계 (문서화, 미해결)
- **init 스레드가 *영원히* 멈추는** 극단 케이스는 self-heal 안 됨(파이썬 스레드 강제종료 불가). 현실에선 psycopg2 `connect_timeout=10`/`statement_timeout=30s`/`lock_timeout=5s`가 막아줌.
- **startup이 BR 35s + MS 35s 직렬 → 최대 ~70s간 `/livez`도 미응답**(Codex 5번째 지적). **기존 동작**(2026-05-09 비차단 설계의 35s timeout·직렬 lifespan), 이번 변경이 악화시키지 않음. k8s `startupProbe` 추가/조정으로 처리할 별건 — 코드 변경 아님.

### 검증
- 복구 테스트 BR/MS: init_db 첫 호출 실패→재시도 성공, `db_ok` False→True flip, BR `/api/rankings` 503→200.
- cleanup-1회 테스트 BR/MS: 첫 시도 멈춘 동안 재시도 승자(cleanup 1회), 멈춘 시도 뒤늦게 끝나도 cleanup 재실행 안 함(`GameRepository`/`StockGameRepository.cleanup_stale_games` 호출 카운트 == 1).
- 회귀: BR 202(boss 제외, root .venv) + boss 60(backend/.venv) / MS 21·4 skip / bot_runner 89 / backend/tests(healthz·livez) 5 — 전부 통과. 환경 분리(backend/.venv=numpy有 firebase無, root .venv=firebase有 numpy無)는 기존 제약.

### 다음
- 사용자 결정: 커밋/PR 시점. A2/A3 처리 여부. (선택) startup~70s/liveness 타이밍은 k8s startupProbe로 별도 처리.

### 배포 업데이트 (2026-05-26)
- `fac686b`를 `origin/seongjin-kube`에 push.
- Cloud Build `1812d477-7594-4d8d-872c-e656b2037f3a`로 server 이미지 `asia-northeast3-docker.pkg.dev/knu-2026-sungjin0418/ai-arena/server:20260526-fac686b` 빌드/푸시 성공(digest `sha256:cc8b8c5bbc29d5d002f3d0b23391f37f9e97a52566020bb4ca08f9aa973765db`).
- GKE `arena/deployment/game-server`만 새 이미지로 교체. Cloud Run `ai-arena-server`는 배포하지 않음.
- rollout 성공 후 `game-server-6f758cf768-z8cmb` 1/1 Running. GKE Ingress `8.233.221.199` 기준 `/healthz`, `/livez`, `/battleroyale/health`, `/stocks/health` 200 확인. rollout 직후 일시 502는 GFE/NEG 전파 지연으로 재시도 후 해소.

---

## 2026-05-27 — Claude Code — BR2 RCE 격리(Phase 1/2) + Codex 후속 P1 3건 수정 (seongjin-kube, push 완료)

Codex adversarial review가 지적한 BR2(`/battleroyale2`) critical RCE를 차단하고, 후속 리뷰 P1 3건까지 수정. 커밋 `f03d48c`/`ecb0bc2`/`fe6a963` 모두 `origin/seongjin-kube` push 완료. **단 GKE 배포는 미반영(신규 이미지 빌드 필요).**

### 배경
공개 ingress가 마운트된 BR2 앱까지 노출. BR2는 유저 봇 코드를 `InProcessBot2`로 game-server Pod 안에서 직접 `exec` → 인터넷 누구나 RCE/DoS 가능. 인증/owner·Godot WS 토큰은 main이 이미 구현(`23eafff`/`4ccb09b`)했으므로, 남은 **봇 실행 격리**와 후속 P1만 처리.

### Phase 1 — BR2 봇 실행 bot-runner 격리 (커밋 `f03d48c`)
- `bot_runner/executor.py`: `battleroyale2` 모드 신규(`_BR2BotBase` 주입, `get_action`/`choose_spawn` phase 분기, `_validate_br2_action`/`_validate_spawn` 경계 스키마, `_default_for`). BR2 봇은 호출마다 새 spawn 프로세스라 **틱 단위 무상태** 계약(`on_episode_done` no-op).
- `bot_runner/schemas.py`/`main.py`: `RunRequest.phase` 추가, `_default_action`→`executor._default_for` 위임.
- `BattleRoyale2/server/remote_bot.py`(신규): `RemoteBattleRoyale2BotAdapter` — `/run`(mode=battleroyale2) 호출, 실패 시 ZERO 폴백.
- `BattleRoyale2/server/ws_server.py`: `_make_user_bot()` 헬퍼(BOT_RUNNER_URL→격리 어댑터, 프로덕션 in-process 거부), `_assemble_bots`가 사용.

### Phase 2 — BR2 WS owner 인증 (커밋 `ecb0bc2`)
- `ws_server.py` `match_ws`: 토큰 유효성 검사(4401) 이후 `_resolve_owner_id(token) != game.owner_user_id`이면 4403 거부. 기존엔 유효 토큰이면 아무 로그인 유저나 접속 가능했음.

### Codex 후속 P1 3건 (커밋 `fe6a963`)
1. **P1-A classic import 회귀**: allowlist 전환(6676e5a) 후 `SAFE_BUILTINS`에 `__import__`가 없어, classic BR/Boss/MS 유저 봇 템플릿(`import random`/`import math`, 예: `BossBattlePage.tsx`)이 policy는 통과하나 exec에서 매 틱 STAY/HOLD 폴백되던 **프로덕션 회귀**. import 화이트리스트를 BR2 전용→**전 모드 공용**(`_ALLOWED_MODULES`/`_safe_import`: math/random/json/collections/heapq/itertools)으로 일반화, `_build_safe_builtins()`가 `SAFE_BUILTINS`에 `__import__` 주입. `_BR2_BUILTINS` 제거(공용 `SAFE_BUILTINS` 사용, 베이스 클래스 주입만 차이).
2. **P1-B 프로덕션 fail-open** (= 기존 A2): **사용자 결정 = 옵션2 secure-by-default + Cloud Run 명시적 opt-out**. `BOT_RUNNER_REQUIRED` 기본값 false→true(`settings.py` + BR2 `_make_user_bot`). 프로덕션 URL 미설정 시 InProcessBot(RCE) 폴백 대신 거부. Cloud Run은 bot-runner 사이드카 없는 in-process가 설계 → `cloudbuild.yaml`에 `BOT_RUNNER_REQUIRED=false` 명시적 opt-out(옵션1 엄격안은 Cloud Run 즉시 깨짐으로 기각). MS fail-closed 조건을 `ENV=="production" and REQUIRED`로 BR과 일치(기존 MS는 ENV 무관).
3. **P1-C BR2 WS owner 해석 실패** (= A3 잔여): `match_ws`에서 토큰은 유효하나 `_resolve_owner_id`가 None(user-service/DB 장애)이면 통과 허용하던 것 → `caller_id != owner`(None 포함) 4403 거부로 fail-closed.

### 보안 검토 메모
P1-A에서 `__import__`를 SAFE_BUILTINS에 추가해도 공격 표면 확대 없음: 동일 allowlist를 BR2가 이미 사용 중이었고, `__import__("os")` 직접 호출은 policy가 forbidden call로 차단, `__globals__`/frame 속성 traversal도 policy가 차단(`_FORBIDDEN_DUNDERS`/`_FORBIDDEN_FRAME_ATTRS`). `_safe_import`는 allowlist 밖 모듈(`base64` 등) 런타임 차단.

### 검증
- bot_runner 104 / BR2 16 / battle_royale 276·7skip / mock_stocks 21·4skip passed.
- `test_startup_db_failure.py`는 `.venv` firebase_admin 미설치로 collection 제외(기존 환경 문제, 회귀 아님).
- 신규/갱신 테스트: bot_runner `test_dos_hardening.py`(import 회귀 4종), BR2 `test_battleroyale2_mode.py`(11종)·`test_bot_runner_isolation.py`(격리 라우팅+fail-closed)·`test_ws_owner_auth.py`(owner 인증 5종)·`test_db_flow.py` fixture에 ENV=development.

### 미해결 / 다음
- **P2 [k8s] readiness latch cleanup-hang**(`app.py:275-282`, Codex 이번에도 재지적): `cleanup_stale_games()` hang 시 `winner_chosen` 먼저 set돼 `state["db_conn"]` 미설치로 `/healthz` 영구 503 가능. **PG statement/lock timeout이 실질적으로 방어**(30s 내 예외→복구)해 ship 블로커 아님 — 사용자 결정으로 **후속 처리**. 고치려면 cleanup executor 호출에 `asyncio.wait_for` timeout + timeout 시에도 state 설치(BR/MS 양쪽).
- **GKE 배포 미반영**: 위 3커밋이 아직 GKE 이미지에 안 올라감(현재 `server:20260526-fac686b`). BR2 RCE 차단을 라이브로 닫으려면 신규 이미지 빌드 + GKE 배포 + E2E 재확인 필요(Phase 9 마무리).
- Phase 9 잔여: Cloud Build 병행 배포 1회, Cloud Run URL E2E, 안정성 수일 관찰.

---

## 2026-05-27 — Codex — Phase 9 보안 이미지 GKE 배포 + BR2 RCE 라이브 차단 확인

직전 세션에서 코드 수정·push까지 끝난 `f03d48c`/`ecb0bc2`/`fe6a963`을 GKE에 실제 반영. Cloud Run은 배포하지 않고, GKE `arena` namespace의 두 Deployment만 `kubectl set image`로 교체했다.

### 빌드 / 배포
- preflight: `seongjin-kube`, HEAD `fe6a963`, 작업트리 clean. 기존 GKE 이미지는 `server:20260526-fac686b`, `bot-runner:20260526-6676e5a`.
- server 이미지: `asia-northeast3-docker.pkg.dev/knu-2026-sungjin0418/ai-arena/server:20260527-fe6a963`
  - Cloud Build `ab9897f4-0576-4ec0-804c-12ec5ee2c098`, digest `sha256:bc8d0ab75676518295786c4772fa379b6ed257487c2c79d0f989b7c0e00109ef`
- bot-runner 이미지: `asia-northeast3-docker.pkg.dev/knu-2026-sungjin0418/ai-arena/bot-runner:20260527-fe6a963`
  - Cloud Build `923c9af0-b467-4942-8899-0deefada7e58`, digest `sha256:595102ecfa6a6a22cc5d6875bef0aa01a6469d5b94a33b5e14553eda1f8c42d7`
- `kubectl -n arena set image deployment/game-server ...` / `deployment/bot-runner ...`만 사용. `kubectl apply -k k8s/base` 미사용(PLACEHOLDER 리셋 회피).
- rollout 결과: `game-server-745fd8dfc5-6vtz2` 1/1 Running, `bot-runner-84bffd99b5-{28q8z,w9bv4}` 2/2 Running, bot-runner 둘 다 `runtimeClassName: gvisor`.

### 검증
- GKE Ingress `8.233.221.199` + Host `api.leagueofagents.net`:
  - `/healthz`, `/livez`, `/battleroyale/health`, `/stocks/health` 전부 HTTP 200.
- bot-runner 내부 확인:
  - `kubectl exec deploy/bot-runner -- python3 -c ... /health` → `{"status":"ok"}`
  - `/livez` → `{"status":"alive"}`
- game-server → bot-runner 직접 BR2 `/run`:
  - 정상 BR2 봇: `ok=true`, action normalized.
  - 악성 `import os` 봇: `ok=false`, ZERO action, `error="forbidden import: os"`.
- 인증 BR2 E2E:
  - Firebase 계정 `kubetest@arena.dev` 토큰으로 GKE Ingress `POST /battleroyale2/api/games` 201.
  - game `8f28b71faf5048b485804846d5441b3b`.
  - WebSocket은 기존 Ingress Host 헤더 중복 gotcha를 피하려고 `kubectl port-forward deploy/game-server 18080:8080`로 연결. `HELLO` → `MATCH_CONFIG`/`MATCH_START`, `MATCH_INFO` → `SPAWN_CHOICES`, `STATE` → `ACTIONS` 확인.
  - 악성 유저 봇 action은 ZERO 폴백. `MATCH_END` 후 `/battleroyale2/api/games/{id}/result` 200, `status=finished`, `end_reason=phase9_smoke`, rankings 2.

### 메모 / 다음
- Cloud Run은 건드리지 않음. 이번 작업은 Artifact Registry 신규 태그 push + GKE Deployment 이미지 교체만 수행.
- game-server access log는 WS query token을 URL에 남긴다. 최종 보고/기록에는 토큰 값을 싣지 말 것. 장기적으로 WS 토큰 로그 마스킹 검토 필요.
- Phase 9 잔여: Cloud Run URL E2E, Cloud SQL/Redis/GCS 안정성 수일 관찰, 비용/로그/에러율 비교.

---

## 2026-05-27 — Claude Code — Cloud Build GKE 자동 배포 파이프라인 구축 (Phase 9 완료)

### 목표
seongjin-kube 브랜치 push 시 GKE game-server + bot-runner를 자동 배포하는 파이프라인 구축.
기존 cloudbuild.yaml(main→Cloud Run)은 무변경, 별도 `cloudbuild.gke.yaml` 파일로 분리.

### 사전 작업
- Cloud Build SA(`673184377961@cloudbuild.gserviceaccount.com`)에 `roles/container.developer` 부여
  - 기존: `roles/cloudbuild.builds.builder`, `roles/iam.serviceAccountUser`, `roles/run.admin`
  - 추가 후: `roles/container.developer` 포함 4개
- Cloud Build GitHub 트리거: CLI 생성 불가(GitHub App 연결 없음) → GCP Console에서 수동 생성
  - 이름: `gke-deploy-seongjin-kube`, 브랜치: `^seongjin-kube$`, config: `cloudbuild.gke.yaml`
  - 서비스 계정: `673184377961-compute@developer.gserviceaccount.com` (roles/editor 보유)

### 파이프라인 설계
- 이미지 태그: `YYYYMMDD-$SHORT_SHA` (기존 수동 배포 관례 일치)
- 배포 방식: `kubectl set image` 전용 (`kubectl apply -k` 금지 — PLACEHOLDER 리셋 방지)
- step 순서: 태그 계산 → server/bot-runner 빌드 → 푸시 → GKE 자격 취득 → set image × 2 → rollout status × 2
- 로깅: `CLOUD_LOGGING_ONLY` (Secret env 미참조, 로그 미노출)

### 커밋
- `572b3a7` `ci: Cloud Build GKE 자동 배포 파이프라인 추가 (cloudbuild.gke.yaml)`
- `d61f9a7` `fix(ci): $$TAG 이스케이프 — Cloud Build 치환 변수 충돌 수정`
  - 원인: Cloud Build이 bash 스크립트 내 `$TAG`를 자체 치환 변수로 파싱 → `$$TAG`로 이스케이프

### 빌드 결과
- 1차 시도(`80b84ca`): 빌드 시작 전 INVALID_ARGUMENT — `$TAG` 치환 오류
  - Cloud Build ID: `eb74fb31-bcee-4c3b-8224-e7b87422021e` FAILURE (asia-northeast3)
- 2차 시도(`d61f9a7`, `$$TAG` 수정 후): BUILD SUCCESS
  - Cloud Build ID: `7cc47bfc-c2a2-41bb-99f5-225b9229c8c8` SUCCESS (asia-northeast3, 2026-05-27T05:00:32Z)
  - server 이미지: `asia-northeast3-docker.pkg.dev/knu-2026-sungjin0418/ai-arena/server:20260527-d61f9a7`
  - bot-runner 이미지: `asia-northeast3-docker.pkg.dev/knu-2026-sungjin0418/ai-arena/bot-runner:20260527-d61f9a7`
  - rollout: game-server 1/1 Running, bot-runner 2/2 Running

### Phase 9 체크리스트 변경
- [x] Cloud Build SA `roles/container.developer` 부여
- [x] Cloud Build GKE 병행 배포 1회 이상 성공
- [x] 최종 완료 기준 "Cloud Build Cloud Run + GKE 병행 배포 수행 중" 체크

### 메모 / 다음
- Phase 9 잔여: Cloud Run URL E2E, Cloud SQL/Redis/GCS 안정성 수일 관찰, 비용/로그/에러율 비교.
- Cloud Build 트리거 재생성 시: GitHub App 연결 선행 필요, SA는 `673184377961-compute` 사용.

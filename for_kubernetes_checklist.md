# LOA Kubernetes 전환 체크리스트

> 상세 설계 근거: `for_kubernetes_migration_plan.md`
> 작업 브랜치: **`seongjin-kube`** (`seongjin` 브랜치와 분리, Kubernetes 전환 전용)
> Git 관리: `.git/info/exclude`의 `for_*.md` 패턴에 의해 로컬 전용

---

## ⚠️ 2026-05-21 재시작 컨텍스트

origin/main 이 5/19~5/20 사이 18커밋 대규모 리팩터링으로 디렉토리 lowercase 개명 + `server/boss/` 격리 + `backend/core/` 패키지 분리를 진행했다. 옛 seongjin-kube 의 Phase 1-3 작업 5개 커밋 (`pre-main-merge` 태그로 보존) 은 옛 구조 (`BattleRoyale/`, `MockStocks/`, `BotRunner/`) 기반이라 그대로 머지 불가능.

**재시작 방침**:
- `git reset --hard origin/main` 으로 seongjin-kube 를 새 main 위로 옮긴 뒤, 옛 작업 내용을 새 경로로 재커밋
- 51b1330 (보스전 DB 컬럼 제거) 와 f79503d (Frontend 정리) 는 폐기
- BotRunner 디렉토리는 `backend/bot_runner/` (lowercase)

**`[x]` 마크 의미 (재시작 후)**:
- Phase 0 `[x]`: 기존 GCP 리소스/baseline 확인 — **여전히 유효** (인프라 안 바뀜)
- Phase 1/2 `[x]`: 옛 구조에서 한 번 만들었던 작업 — **새 경로로 재작업 필요**. 코드 자체는 `pre-main-merge` 태그에서 참조하여 95% 재사용 가능, 디렉토리/import 만 lowercase 로.
- 재작업 완료 시점에 다시 `[x]` 유지 또는 갱신 일자 표시.

---

## 병행 운영 원칙 (전 Phase 공통)

- Cloud Run(`ai-arena-server`)은 **PR 7 Frontend cutover 전까지 절대 삭제하지 않는다.**
- Cloud Build에 GKE step을 추가한 뒤에도 `gcloud run deploy` step을 함께 유지한다. 매 배포마다 양쪽 모두 같은 이미지로 업데이트되지만, **Cloud Run은 `BOT_RUNNER_URL` 미설정으로 인해 기존 `InProcessBot` 방식으로 계속 동작**한다. GKE만 `BOT_RUNNER_URL`이 설정되어 `RemoteBotAdapter` 방식으로 동작한다.
- 프론트엔드(Firebase) API URL은 안정화 완료 전까지 **Cloud Run을 유지**한다. 실제 사용자 트래픽은 계속 Cloud Run으로 간다.
- GCP에서 확인이 필요한 시점마다 Cloud Run URL과 GKE Ingress URL **양쪽** 모두 응답을 검증한다.
- 문제 발생 시 프론트 환경변수 1개만 바꿔서 Cloud Run으로 즉시 복귀할 수 있는 상태를 항상 유지한다.

---

## Phase 0. 사전 점검

### GCP 리소스 확인
- [x] `gcloud config get-value project` 로 project id 확인 → `knu-2026-sungjin0418`
- [x] Cloud Run service `ai-arena-server` region, 환경변수 전체 목록 수집 → URL: `https://ai-arena-server-6eb5desvgq-du.a.run.app`
- [x] Cloud SQL instance `arena-db` private IP 확인 → `10.114.0.3` (DB_HOST 일치)
- [x] Memorystore Redis private IP 확인 → `10.197.54.43` (REDIS_HOST 일치), instance: `arena-redis`
- [x] VPC connector `arena-connector` 이름/VPC/subnet 확인 → network: `default`, subnet: `asia-northeast3 (10.178.0.0/20)`
- [x] Secret Manager secrets 목록 확인 → `firebase-service-account`, `db-password`, `GEMINI_API_KEY`
- [x] GCS boss weights 버킷명 확인 → `gs://boss-weights/trained_weights.json` (Cloud Run env 확인, manifest에는 미기재)
- [x] Artifact Registry repository `ai-arena` 존재 확인 → DOCKER format

### 운영 baseline 저장
- [x] `curl .../battleroyale/health` 응답 기록 → `{"status":"ok","active_games":0,"total_spectators":0}`
- [x] `curl .../stocks/health` 응답 기록 → `{"status":"ok"}`
- [x] BattleRoyale 게임 생성 → 관전 WebSocket → 종료 → 결과 E2E 확인 (수동) → 정상
- [x] MockStocks 게임 생성 → 관전 WebSocket → 종료 → 결과 E2E 확인 (수동) → 정상
- [x] WORK_LOG.md에 baseline 기록 (2026-05-19 항목)

### 비용 예산
- [x] Cloud Console에서 현재 Cloud Run 월 비용 확인 → 예산 내 정상
- [x] 남은 GCP 크레딧/예산 잔액 확인 → 충분
- [ ] GKE Autopilot 예상 비용 계산 (game-server 1 replica + bot-runner 2 replica + LB)
- [ ] `gcloud billing budgets create` 로 예산 알림 설정 (50%/90%/100%)
- [x] WORK_LOG.md에 비용 비교 기록

### gVisor 사전 호환성 확인 (Phase 4 클러스터 생성 직후 진행)
- [ ] gVisor 지원 클러스터에 임시 Pod 실행 (`runtimeClassName: gvisor`)
- [ ] `multiprocessing.Process` spawn 성공 확인 (`mp ok` 출력)
- [ ] `resource.setrlimit(RLIMIT_CPU, ...)` 성공 확인 (`rlimit ok` 출력)
- [ ] `signal.alarm(5); signal.alarm(0)` 성공 확인 (`signal ok` 출력)
- [ ] `tempfile.NamedTemporaryFile(dir='/tmp')` 성공 확인 (`tmpfile ok` 출력)
- [ ] WORK_LOG.md에 결과 기록
- [ ] 실패 시: gVisor 포기 결정 → 일반 Pod + NetworkPolicy/resource limit 강화 재설계 확정 후 Phase 1 진행

---

## Phase 1 (PR 1). Bot Runner 서비스 구현

### 디렉터리 및 파일 생성
- [x] `backend/bot_runner/` 디렉터리 생성
- [x] `main.py` — FastAPI 앱, `GET /health`, `POST /run` 엔드포인트
- [x] `schemas.py` — 요청/응답 Pydantic 모델
- [x] `cache.py` — `code_hash` 기반 LRU 캐시 (`cachetools.LRUCache`, source string 저장)
- [x] `executor.py` — multiprocessing spawn 기반 봇 실행, resource limit, signal timeout
- [x] `policy.py` — AST 정적 검사 (forbidden imports/builtins)
- [x] `requirements.txt`
- [x] `Dockerfile` (non-root user 10001, `WORKDIR /app`)

### API 구현
- [x] `POST /run` 요청: `mode`, `bot_id`, `code_hash`, `code`(optional), `state`
- [x] `code_hash` cache hit 시 policy 재검사 생략 (source string 캐시)
- [x] cache miss 시 policy check + compile 검증 후 LRUCache 저장
- [x] BattleRoyale 응답: `{"ok": true, "action": "MOVE_UP_LEFT"}`
- [x] MockStocks 응답: `{"ok": true, "action": {"action": "BUY", "symbol": "...", "quantity": ...}}`
- [x] 에러/timeout 응답: HTTP 200 + `{"ok": false, "error": "...", "action": <fallback>}`

### 보안 정책
- [x] AST 검사: `os`, `socket`, `subprocess`, `pathlib`, `builtins` import 차단
- [x] AST 검사: `open`, `exec`, `eval`, `compile`, `__import__`, `globals`, `locals`, `vars`, `dir` 차단
- [x] AST 검사: `getattr`, `setattr`, `delattr`, `hasattr` 이름 참조/호출 모두 차단 (alias bypass 방지)
- [x] `__base__`, `__getattr__`, `__getattribute__`, `__setattr__`, `__delattr__`, `__get__`, `__set__`, `__delete__`, `__new__` dunder 차단
- [x] `str.format()` / `str.format_map()` 차단: 정적·동적 조합 탬플릿·bound-method alias 3가지 경로 모두 차단
- [x] 코드 크기 제한 50KB
- [x] multiprocessing spawn 기반 프로세스 격리 (thread 실행 금지)
- [x] child process `os.environ.clear()`
- [x] `resource.setrlimit` CPU time / AS / file size / process count 적용
- [x] `signal.alarm` 기반 timeout

### 테스트
- [x] 정상 BattleRoyale action 반환 (19개 action 전체 parametrize)
- [x] 정상 MockStocks action 반환
- [x] syntax error → fallback action 반환
- [x] action 함수 없음 → fallback
- [x] timeout → fallback (infinite loop, cpu hog)
- [x] forbidden import → fallback
- [x] invalid action → fallback
- [x] code size 초과 → fallback

### PR 1 전 검증
- [x] `pytest tests/` 전체 통과 (78개: policy 32 + run 14 + mode_contracts 27 + timeout 2 + 기타 3)
- [x] 알려진 21개 우회 벡터 probe 스크립트로 전부 차단 확인
- [x] 정상 봇 코드 6패턴 (class-based 포함) 통과 확인
- [x] `docker build -f backend/bot_runner/Dockerfile backend/bot_runner` 성공
- [x] `uvicorn main:app --port 8001` 실행 후 `GET /health` 응답 확인 → `{"status":"ok"}`
- [x] `POST /run` 수동 테스트 → BattleRoyale `MOVE_UP` 정상, MockStocks `{"action":"HOLD"}` 정상

---

## Phase 2 (PR 2). RemoteBotAdapter + /healthz + /livez

### BattleRoyale 변경
- [x] `backend/battle_royale/src/arena/sandbox/remote_adapter.py` 생성
- [x] `backend/battle_royale/src/arena/server/settings.py` — `BOT_RUNNER_URL`, `BOT_RUNNER_TIMEOUT_SEC`, `BOT_RUNNER_REQUIRED` 추가
- [x] `create_game()` — user bot에 `RemoteBattleRoyaleBotAdapter` 사용, AI filler/boss는 in-process 유지
- [x] adapter `__init__`에서 `code_hash = "sha256:" + hashlib.sha256(code.encode()).hexdigest()` 계산
- [x] 매 tick `POST /run` 호출 시 `code_hash + code + state` 전송
- [x] `BOT_RUNNER_REQUIRED=true` + URL 없을 때 503 반환

### MockStocks 변경
- [x] `backend/mock_stocks/src/stocks/sandbox/remote_adapter.py` 생성
- [x] `backend/mock_stocks/src/stocks/server/settings.py` — 동일 설정 추가
- [x] `create_game()` — 동일 패턴 적용
- [x] fallback action: `{"action": "HOLD"}`

### 통합 health 엔드포인트
- [x] `GET /healthz` 추가 — BattleRoyale + MockStocks DB 상태 종합, 한 쪽 실패 시 HTTP 503
- [x] `GET /livez` 추가 — 프로세스 생존만 확인, 항상 HTTP 200, DB 체크 없음
- [x] `/healthz` 정상 응답: `{"status": "ok", "battleroyale": {"db": "ok"}, "stocks": {"db": "ok"}}`
- [x] `/healthz` 장애 응답: `{"status": "degraded", ...}` + HTTP 503
- [x] `/livez` 응답: `{"status": "alive"}` + HTTP 200 고정

### 테스트
- [x] Bot Runner mock HTTP 서버 기반 adapter 테스트 (BattleRoyale 8개, MockStocks 7개)
- [x] BattleRoyale create_game → user bot만 remote adapter 확인
- [x] MockStocks create_game → user bot만 remote adapter 확인
- [x] Bot Runner timeout → `STAY` / `{"action": "HOLD"}` fallback
- [x] Bot Runner 500 → fallback
- [x] `BOT_RUNNER_URL` 없을 때 InProcess fallback (개발 모드)
- [x] `/healthz` 정상/degraded 두 경로 모두 테스트 (5개 테스트)
- [x] 기존 backend pytest 전체 통과 (200+16 passed, 기존 결함 2개 제외)

---

## Phase 3 (PR 3). Kubernetes 매니페스트

### 디렉터리 구조 생성
- [x] `k8s/base/namespace.yaml`
- [x] `k8s/base/configmap.yaml` (BOSS_WEIGHTS_GCS_URI 미포함, DB_HOST/REDIS_HOST는 Phase 0.1 확인값 사용)
- [x] `k8s/base/game-server-deployment.yaml`
- [x] `k8s/base/game-server-service.yaml`
- [x] `k8s/base/bot-runner-deployment.yaml`
- [x] `k8s/base/bot-runner-service.yaml`
- [x] `k8s/base/backend-config.yaml` (WebSocket timeout 3600s)
- [x] `k8s/base/network-policy.yaml`
- [x] `k8s/base/ingress.yaml`
- [x] `k8s/base/managed-certificate.yaml` (api.leagueofagents.net)
- [x] `k8s/base/hpa.yaml`
- [x] `k8s/base/service-account.yaml`
- [x] `k8s/base/kustomization.yaml` (Skaffold용 Kustomize 리소스 목록)
- [x] `k8s/secret.example.yaml`
- [x] `k8s/README.md`

### game-server Deployment 체크
- [x] `replicas: 1` (세션 외부화 전까지 1 유지)
- [x] `readinessProbe` → `/healthz`
- [x] `livenessProbe` → `/livez`
- [x] `envFrom: configMapRef + secretRef` 명시
- [x] `serviceAccountName: game-server` 명시
- [x] resources requests/limits 명시

### bot-runner Deployment 체크
- [x] `runtimeClassName: gvisor`
- [x] `automountServiceAccountToken: false`
- [x] `securityContext.readOnlyRootFilesystem: true`
- [x] `securityContext.runAsNonRoot: true`, `runAsUser: 10001`
- [x] `capabilities.drop: ["ALL"]`
- [x] `/tmp` emptyDir `medium: Memory`, `sizeLimit: 64Mi` 마운트
- [x] `envFrom: secretRef` 없음 확인

### Service / BackendConfig 체크
- [x] game-server Service에 `cloud.google.com/backend-config` annotation 추가
- [x] BackendConfig `timeoutSec: 3600`, `healthCheck.requestPath: /healthz`

### NetworkPolicy 체크
- [x] bot-runner ingress: game-server Pod만 허용
- [x] bot-runner egress: `[]` (완전 차단)

### ServiceAccount / Workload Identity 체크
- [x] game-server ServiceAccount manifest에 `iam.gke.io/gcp-service-account` annotation 추가

### Ingress 체크
- [x] static IP 예약: `gcloud compute addresses create loa-arena-ingress-ip --global` → `8.233.221.199` (2026-05-25)
- [x] Ingress에 static IP annotation 연결 (`loa-arena-ingress-ip`)
- [x] ManagedCertificate 도메인 설정 (`api.leagueofagents.net`)

### PR 3 전 검증
- [x] `kubectl apply --dry-run=client -k k8s/base` — 표준 K8s 리소스 11개 통과. BackendConfig/ManagedCertificate는 GKE 전용 CRD라 로컬 에러 예상됨
- [ ] kubeconform 또는 kubeval 스키마 검사 (가능하면)
- [x] bot-runner manifest에 `runtimeClassName: gvisor` 확인
- [x] bot-runner manifest에 `envFrom: secretRef` 없음 확인
- [x] NetworkPolicy egress deny 확인
- [x] YAML 파일에 Secret 값 없음 확인

### Phase 3 리뷰 후 강화 (2026-05-19)

> Phase 3 매니페스트 리뷰 결과 운영 안정성·심층 방어 관점에서 보강한 항목. 상세 근거는 `AGENTS.md`의 *Phase 3 매니페스트 검토 사항* 섹션 참조.

- [x] **ConfigMap에 `BOT_RUNNER_TIMEOUT_SEC: "0.5"` 명시** (검토 #2) — 튜닝 포인트를 코드 기본값에서 매니페스트로 노출
- [x] **bot-runner `/livez` 엔드포인트 추가** (`backend/bot_runner/main.py`, 검토 #3) — readiness `/health`와 분리
- [x] **bot-runner liveness probe 분리** (검토 #3) — `path: /livez`, `periodSeconds: 20`, `failureThreshold: 6`. 일시 부하로 인한 readiness 실패가 Pod 재시작으로 이어지지 않게
- [x] **Deployment image 태그 `:latest` → `:PLACEHOLDER`** (검토 #1) — `kubectl apply` 단독 실행 시 의도적 ImagePullBackOff. 실제 배포는 Cloud Build / `kubectl set image`로 구체 태그/digest 주입 필수
- [x] **`k8s/README.md`에 PLACEHOLDER 운영 원칙 명시** (검토 #1)
- [x] **`k8s/base/game-server-pdb.yaml` 추가** (검토 #4) — `minAvailable: 1`. Autopilot 노드 자동 업그레이드/drain 시 voluntary disruption 차단. Redis 세션 외부화 + replica 2+ 전환 시 재조정 필요
- [x] **kustomization.yaml에 PDB 리소스 등록** (검토 #4)
- [x] **game-server NetworkPolicy 추가** (검토 #5) — `game-server-isolation` 추가. Google LB IP 대역(`130.211.0.0/22`, `35.191.0.0/16`)을 `ipBlock`으로 8080 허용 (GKE 외부 LB+헬스체커는 Pod 아닌 이 대역에서 NEG로 Pod IP 직접 호출). 그 외 클러스터 내 Pod 횡방향 접근 차단. Phase 8에서 Ingress 배포 후 검증 필요 (2026-05-25, 커밋 9d1d08d)
- [x] **bot-runner `seccompProfile.type: RuntimeDefault` 추가** (검토 #7) — container securityContext에 추가 (2026-05-25)
- [x] **namespace `arena`에 PodSecurity 라벨 추가** (검토 #8) — `enforce: baseline` + `warn: restricted`. game-server Dockerfile이 root 실행이므로 restricted 전면 적용 불가. baseline이 권한 에스컬레이션/privileged 차단, restricted warn이 나머지 위반 알림. runAsNonRoot는 Dockerfile 수정 후 (2026-05-25)
- [x] **bot-runner SA에 `automountServiceAccountToken: false` 명시** (검토 #9) — SA 레벨 추가 (2026-05-25)
- [x] **Ingress `kubernetes.io/ingress.class` annotation → `spec.ingressClassName` 전환** (검토 #6) — annotation 제거, spec 필드로 교체 (2026-05-25)
- [x] **WORK_LOG.md에 CORS_ORIGINS 확장 근거 기록** (검토 #10) — 2026-05-25 섹션에 기록 완료

---

## Phase 4. GKE 클러스터 생성

### 클러스터 생성 / 삭제 명령어 (반복 사용)

```bash
# 생성
gcloud container clusters create-auto loa-arena \
    --region asia-northeast3 \
    --release-channel regular \
    --network default \
    --subnetwork default \
    --project knu-2026-sungjin0418

# kubectl context 등록 (생성 직후)
gcloud container clusters get-credentials loa-arena \
    --region asia-northeast3 --project knu-2026-sungjin0418

# 삭제 (작업 없을 때 비용 절감)
gcloud container clusters delete loa-arena --region asia-northeast3
```

### 사전 확인
- [x] Cloud SQL private IP와 동일 VPC에 GKE 생성 가능한지 확인 → net-test Pod로 `10.114.0.3:5432 open` (2026-05-25)
- [x] Memorystore Redis와 동일 VPC 접근 가능한지 확인 → net-test Pod로 `10.197.54.43:6379 open` (2026-05-25)
- [x] Kubernetes Engine API 활성화 → `container.googleapis.com` 확인
- [x] Artifact Registry API 활성화 → `artifactregistry.googleapis.com` 확인
- [x] Secret Manager API 활성화 → `secretmanager.googleapis.com` 확인
- [x] Cloud SQL Admin API 활성화 → `sqladmin.googleapis.com` 확인

### 클러스터 생성
- [x] VPC/subnet 이름 확인 후 `create-auto loa-arena ...` 실행 → network/subnet 모두 `default`, STATUS RUNNING (2026-05-25)
- [x] `gcloud container clusters get-credentials loa-arena --region asia-northeast3` → 완료 (`gke-gcloud-auth-plugin` 설치 필요했음)
- [x] `kubectl get nodes` 정상 확인 → 노드 1개 `NotReady,SchedulingDisabled` (Autopilot 워크로드 없을 때 정상, Phase 5 배포 시 자동 프로비저닝)
- [x] `kubectl get ns` 확인 → 기본 + gke-managed-* 네임스페이스 정상, arena 는 Phase 5에서 생성

### gVisor 확인
- [x] `kubectl get runtimeclass` 출력에 `gvisor` 포함 확인 → `gvisor` + `confidential-linked-runner` 존재 (2026-05-25)

### Workload Identity 확인
- [x] `gcloud container clusters describe loa-arena ... --format='value(workloadIdentityConfig.workloadPool)'`
- [x] 출력값: `knu-2026-sungjin0418.svc.id.goog` (2026-05-25)

### 네트워크 확인
- [x] GKE Pod에서 Cloud SQL private IP (`10.114.0.3`) 접근 확인 → `open`
- [x] GKE Pod에서 Memorystore Redis (`10.197.54.43`) 접근 확인 → `open`
- [x] Artifact Registry image pull 권한 확인 → 노드 기본 SA `673184377961-compute@developer` 가 `roles/editor` 보유 (artifactregistry read 포함) → pull 가능

---

## Phase 5 (PR 4/5). 이미지 빌드와 배포 파이프라인

### Artifact Registry 이미지 빌드/푸시 (수동)
- [x] `gcloud builds submit` server 이미지 성공 → `server:20260526-252082d` (2026-05-26)
- [x] `gcloud builds submit` bot-runner 이미지 성공 → `bot-runner:20260526-252082d` (최초 빌드, 2026-05-26)
- [x] AR push server 이미지 성공 → `sha256:569d939a0318bb0f4a28265cc3b6b21d069e723f22d07dbe5f1f3cab7438d7e1`
- [x] AR push bot-runner 이미지 성공 → `sha256:24f30dd71a7d5865d0f2c59df1076320f34376b88ed038cba0f788176fdd1154`

> 빌드 방식: `gcloud builds submit` (Apple Silicon arm64 → GCP 인프라에서 linux/amd64 빌드)
> 이미지 태그 형식: `YYYYMMDD-shortsha` (`:latest` 금지)

### 수동 GKE 배포 (PR 4)
- [x] Secret 수동 생성: `kubectl create secret generic arena-secrets --namespace arena ...` (Secret Manager에서 직접 pull, 2026-05-26)
- [x] ConfigMap 적용 (`kubectl apply -k k8s/base/`) + `kubectl -n arena patch configmap arena-config --patch='{"data": {"BOSS_WEIGHTS_GCS_URI": "..."}}'` 로 주입 (2026-05-26)
- [x] `kubectl apply -k k8s/base/` 성공 (namespace/SA/ConfigMap/Service/Deployment/PDB/HPA/BackendConfig/ManagedCert/Ingress/NetworkPolicy 전부 생성, 2026-05-26)
- [x] `kubectl set image deployment/game-server ...` → `server:20260526-252082d`
- [x] `kubectl set image deployment/bot-runner ...` → `bot-runner:20260526-252082d`
- [x] `kubectl rollout status deployment/game-server` 성공 (game-server 1/1 Running)
- [x] `kubectl rollout status deployment/bot-runner` 성공 (bot-runner 2/2 Running)

### game-server non-root 전환 (2026-05-26)
- [x] `backend/Dockerfile`에 non-root user(`appuser` uid 10002) + `chown -R /app` + `USER 10002` 추가
- [x] `game-server-deployment.yaml` securityContext에 `runAsNonRoot: true` + `runAsUser: 10002` 추가 (deferral 주석 제거)
- [x] server 이미지 재빌드 → `server:20260526-252082d-nonroot` (`sha256:a21905c7...`)
- [x] `kubectl apply -k k8s/base/` → game-server PodSecurity 경고 **사라짐** 확인
- [x] `kubectl exec deploy/game-server -- id` → `uid=10002(appuser)` (root 아님) 확인
- [x] health 전부 정상 (`/healthz`, `/livez`, BR/MS health), RESTARTS 0
- [x] non-root 기인 Permission denied 에러 없음 (GCS WI 404는 Phase 6 사안, 무관)

> **운영 gotcha**: `kubectl apply -k k8s/base/`는 두 Deployment를 모두 `:PLACEHOLDER`로 되돌린다.
> apply 후엔 game-server·bot-runner **양쪽 모두** `kubectl set image`로 실제 태그를 다시 지정해야 함
> (이번에 bot-runner가 PLACEHOLDER ImagePullBackOff 났다가 재set으로 복구).

### Cloud Build SA 권한 부여 (PR 5 전)
- [x] `roles/container.developer` Cloud Build SA에 부여 (2026-05-27)
- [x] Artifact Registry push 권한 확인 (2026-05-27, 빌드 성공으로 확인)

### cloudbuild.gke.yaml 별도 파일 추가 (PR 5 — 전략 변경)
> 기존 cloudbuild.yaml(main→Cloud Run) 수정 대신 별도 파일로 분리.
> seongjin-kube push → cloudbuild.gke.yaml → GKE 전용 트리거로 연결.
- [x] bot-runner 이미지 빌드/푸시 step 추가 (2026-05-27)
- [ ] ConfigMap Cloud Build step 추가 (`BOSS_WEIGHTS_GCS_URI` substitution 주입) — 미구현(수동 유지)
- [ ] `kubectl apply -f k8s/base` step — 의도적 미구현(PLACEHOLDER 리셋 방지, kubectl set image만 사용)
- [x] `kubectl set image` + `rollout status` step 추가 (2026-05-27)
- [x] 기존 `gcloud run deploy` step 유지 확인 (cloudbuild.yaml 무변경)
- [x] `kubectl rollout status` 실패 시 build 실패 처리 확인 (--timeout=180s, 실패 시 step 비zero exit)
- [x] Secret 값이 Cloud Build 로그에 출력되지 않는지 확인 (CLOUD_LOGGING_ONLY, Secret env 미참조)

### Skaffold 로컬 개발 환경 설정 (선택 — PR 4에 포함 가능)
> Skaffold는 무료 오픈소스 도구. 팀원 전원 필수 아님. 인프라 담당자 또는 매니페스트 자주 수정하는 팀원에게 권장.
> 로컬 overlay는 패치 파일을 포함하므로 raw kubectl이 아닌 **Kustomize** 방식으로 배포한다.
- [ ] `brew install skaffold` 설치 확인
- [ ] `k8s/base/kustomization.yaml` 작성 (base 리소스 목록 — production Kustomize 배포용)
- [ ] `skaffold.yaml` 작성 (repo 루트): local/production 프로파일 분리
  - local 프로파일: `deploy.kustomize.paths: k8s/overlays/local`, `push: false`
  - production 프로파일: `deploy.kustomize.paths: k8s/base`
- [ ] `k8s/overlays/local/kustomization.yaml` 작성
  - `resources: ../../base`
  - `patches: bot-runner-patch-local.yaml` (target: Deployment/bot-runner)
  - `configMapGenerator: behavior: merge` (`USE_REDIS=false`, `DB_TYPE=sqlite`)
- [ ] `k8s/overlays/local/bot-runner-patch-local.yaml` 작성 (Kustomize strategic merge patch, `runtimeClassName: null`)
- [ ] `minikube start` 로컬 클러스터 기동 확인
- [ ] 로컬용 더미 Secret 생성: `kubectl create secret generic arena-secrets --namespace arena --from-literal=DB_PASSWORD=local`
- [ ] `skaffold dev --profile=local` 실행 → game-server, bot-runner 파드 정상 기동 확인
- [ ] bot-runner 파드에 `runtimeClassName` 없음 확인 (`kubectl get pod -o yaml`)
- [ ] `skaffold run --profile=production` 실행 → GKE 배포 정상 확인

---

## Phase 6. Secret과 권한

### Kubernetes ServiceAccount
- [x] game-server ServiceAccount 생성
- [x] bot-runner ServiceAccount 생성 (`automountServiceAccountToken: false`)

### Workload Identity 설정
- [x] GCP SA `game-server-sa` 생성 (또는 기존 재사용) — 신규 생성 (2026-05-26)
- [x] `roles/storage.objectViewer` → `game-server-sa` 부여
- [x] `roles/iam.workloadIdentityUser` 바인딩 (`PROJECT_ID.svc.id.goog[arena/game-server]`)
- [x] Kubernetes SA `game-server`에 `iam.gke.io/gcp-service-account` annotation 추가

### 검증
- [x] game-server Pod에서 GCS boss weights 읽기 성공 — `exists: True`, 새 Pod 기동 로그 `Weights downloaded: gs://boss-weights/trained_weights.json` (403/404 없음)
- [x] bot-runner Pod에 DB/Firebase/Gemini/JWT Secret env 없음 확인
- [x] bot-runner Pod에 service account token 자동 mount 없음 확인

> **운영 gotcha (Phase 6)**: GCP SA 신규 생성 직후 `iam.workloadIdentityUser` 바인딩 전파에
> 30초~1분 지연이 있다. 그 사이 기동한 Pod은 startup GCS load가 `403 iam.serviceAccounts.getAccessToken denied`로
> 실패하고 fallback한다 (`gcs_weights.download()`는 실패를 삼키고 None 반환 → "GCS에서 로드 완료" 로그는
> 성공을 보장하지 않음). 전파 완료 후 **한 번 더 rollout restart** 해야 startup에서 실제 GCS 다운로드가 찍힌다.

---

## Phase 7. gVisor Smoke Test (PR 4 단계 필수)

> Phase 0.4에서 임시 Pod 기준 사전 통과를 확인한 이후, 실제 bot-runner Deployment Pod에서 재확인하는 단계.

- [x] `kubectl -n arena exec deploy/bot-runner -- python /tmp/smoke.py` 실행 (2026-05-26)
- [x] `multiprocessing.Process` spawn 성공 (`mp ok` 출력)
- [x] `resource.setrlimit(RLIMIT_CPU, ...)` 성공 (`rlimit ok` 출력)
- [x] `signal.alarm(5); signal.alarm(0)` 성공 (`signal ok` 출력)
- [x] `tempfile.NamedTemporaryFile(dir='/tmp')` 성공 (`tmpfile ok` 출력)
- [x] 4항목 전부 통과 → Phase 7 완료 (gVisor 대체 방안 전환 불필요)

---

## Phase 8. Kubernetes Smoke / E2E 테스트

### 기본 상태 확인
- [x] `kubectl -n arena get pods` — game-server 1/1, bot-runner 2/2 Running (2026-05-26)
- [x] `kubectl -n arena get svc` 확인 — game-server(80→8080), bot-runner(8001) ClusterIP
- [x] `kubectl -n arena get ingress` — IP 할당 확인 → `8.233.221.199` (Ingress class annotation 복원 후, 아래 gotcha 참조)
- [x] `kubectl -n arena logs deploy/game-server` — 에러 없음 (healthz/livez 200 반복)
- [x] `kubectl -n arena logs deploy/bot-runner` — 에러 없음 (health/livez 200 반복)

> **Phase 8 gotcha (Ingress LB 미프로비저닝)**: Phase 3 검토 #6에서 `kubernetes.io/ingress.class` annotation을
> 제거하고 `spec.ingressClassName: gce`만 남겼는데, **GKE 1.35 Autopilot GLBC가 spec 필드 단독으로는
> NEG/LB 생성을 트리거하지 않음** (SSL 인증서만 생성, 6시간+ ADDRESS 미할당). annotation 복원 →
> 즉시 NEG/backend service/URL map/forwarding rule 생성, IP 할당. `k8s/base/ingress.yaml`에 annotation 영속화 (커밋 0e1d0bf).

### Health 확인 (GKE)
- [x] `curl <GKE_INGRESS_URL>/healthz` → `{"status":"ok","battleroyale":{"db":"ok"},"stocks":{"db":"ok"}}` (HTTP 200)
- [x] `curl <GKE_INGRESS_URL>/livez` → `{"status":"alive"}` (HTTP 200)
- [x] `curl <GKE_INGRESS_URL>/battleroyale/health` 정상 → `{"status":"ok","active_games":0,...}`
- [x] `curl <GKE_INGRESS_URL>/stocks/health` 정상 → `{"status":"ok"}`

> 호출 형식: `http://8.233.221.199<path>` + `-H "Host: api.leagueofagents.net"`.
> HTTPS는 ManagedCert가 DNS 미설정(`FailedNotVisible`)이라 미가용 — HTTP+IP만. 초기 Connection Reset은 GFE 전파 지연으로 수 분 후 자체 해소.

### Health 확인 (Cloud Run — 병행 운영 검증)
- [x] `curl <CLOUD_RUN_URL>/battleroyale/health` 정상 → `{"status":"ok",...}` (GKE 배포 후에도 Cloud Run 유지)
- [x] `curl <CLOUD_RUN_URL>/stocks/health` 정상 → `{"status":"ok"}`

### gVisor 런타임 확인
- [x] `kubectl -n arena get pods -l app=bot-runner -o jsonpath=...` → 2개 모두 `gvisor` 확인 (2026-05-26)

### NetworkPolicy 확인
- [x] game-server → bot-runner `/run` 호출 성공 — `http://bot-runner:8001/health` 200, `/run` MOVE_UP 정상
- [x] bot-runner → 외부 인터넷 호출 실패 확인 — 외부 IP urlopen `URLError`(차단)
- [x] **game-server Ingress health check 통과** — backend service `asia-northeast3-c` HEALTHY, 방화벽 `k8s-fw-l7--...`이 130.211.0.0/22·35.191.0.0/16 → tcp:8080 허용. NetworkPolicy는 Dataplane V2(ADVANCED_DATAPATH) eBPF로 실제 적용 (2026-05-26 검증)
- [x] game-server 횡방향 차단 — arena 내 임시 Pod → `game-server:80` `timed out`(차단 확인)

### E2E 확인 (2026-05-26, GKE Ingress `8.233.221.199` + Firebase 토큰)

> 인증: ENV=production이라 mock auth 불가. Firebase REST `signInWithPassword`(공개 Web API key)로
> 테스트 계정 `kubetest@arena.dev` ID 토큰 발급 → `Authorization: Bearer` 로 호출.
> 유저 봇은 GKE에서 `BOT_RUNNER_URL` 설정으로 `RemoteBotAdapter`→bot-runner Pod 실행.

- [x] 로그인 정상 — `GET /battleroyale/api/me` 200, user id 17 (kubetest) 토큰 검증 성공
- [x] BattleRoyale 게임 생성 → 관전 WebSocket → 종료 → 결과 — game `23cffa85` max_ticks(200) 종료, 결과 200, 유저 봇 실제 이동(98틱 생존)
- [x] Boss 게임 생성 → 관전 → 종료 → 결과 — game `a9e0323f` last_standing(84틱), AI_보스 승, 결과 200
- [x] MockStocks 게임 생성 → 관전 → 종료 → 결과 — game `5e40c6aa` finished(200틱), 3봇 참여, 결과 200
- [x] GamesPage active/history 목록 정상 — BR active 2건, MS history 1건 응답
- [x] 계정별 owner filtering 정상 — kubetest 소유 게임만 목록에 노출
- [x] 유저 봇 `os.environ` 접근 시 서버 Secret 미노출 — `import os` 봇이 `forbidden import: os`로 차단(fallback STAY). child `os.environ.clear()` + bot-runner Secret 미마운트 이중 방어
- [x] BackendConfig WebSocket timeout — `/battleroyale/ws/games/{id}` 핸드셰이크 `101 Switching Protocols` + tick 데이터 수신 확인. 백엔드 `timeoutSec: 3600` 적용 확인 (1시간 장기 보유는 미측정)

> **bot-runner P1(RLIMIT_NPROC) 수정 prod 검증**: 기존 이미지 `252082d`는 `POST /run`에서
> `{"ok":false,"action":"STAY","error":"no result received from child process"}` (Queue feeder thread가
> RLIMIT_NPROC(0,0) 하 fork 못해 결과 유실). SimpleQueue 전환 이미지 `20260526-0e1d0bf` 재배포 후
> `{"ok":true,"action":"MOVE_UP"}` 정상. battleroyale/stocks 양쪽 remote 실행 확인.

---

## Phase 9 (PR 6). GKE 안정화 관찰

- [x] Cloud Build가 **Cloud Run + GKE 병행 배포** 1회 이상 성공 (2026-05-27, cloudbuild.gke.yaml 트리거 `7cc47bfc`, seongjin-kube `d61f9a7`, server+bot-runner 빌드/푸시/rollout SUCCESS. Cloud Run은 기존 cloudbuild.yaml 트리거로 병행 운영 중)
- [x] GKE Ingress URL 기준 BattleRoyale/Boss/MockStocks E2E 통과 (2026-05-26, kubetest@arena.dev, BR:6cb14f43 max_ticks/200틱, Boss:813f5947 last_standing/250틱, MS:18e78944 200틱, 모두 result 200)
- [x] BR2 보안 이미지 GKE 배포 + live RCE 차단 확인 (2026-05-27, `server:20260527-fe6a963`, `bot-runner:20260527-fe6a963`, BR2 game `8f28b71faf5048b485804846d5441b3b` finished/phase9_smoke, 악성 `import os` 봇 ZERO 폴백)
- [ ] Cloud Run URL 기준 동일 E2E 통과 확인 (병행 운영 유지 검증)
- [x] WebSocket 관전 연결 확인 (2026-05-26, game:727ce631, port-forward→localhost:8080, tick=36~43 live 8건 수신. 비고: GKE Ingress 경유 WS는 Python websockets IP+Host 헤더 중복 문제로 400 — curl에서는 101 확인됨, DNS 설정 후 ws://api.leagueofagents.net 경로로 재확인 예정)
- [ ] Cloud SQL/Redis/GCS 접근 안정성 확인 (수일 관찰)
- [ ] GKE 비용 모니터링 — 예산 알림 미발생 확인
- [ ] 로그량/에러율 Cloud Run과 비교
- [x] Cloud Run rollback 경로 유효성 재확인 (2026-05-26, /battleroyale/health·/stocks/health 200 확인. /healthz는 Cloud Run 구버전이라 404 — 정상 기대 동작)

### Codex 재리뷰 신규 3건 (Phase 10 cutover 전 결정)
- [x] **A1 [high] readiness 영구 latch** — BR/MS lifespan에 DB init 실패 시 백그라운드 직렬 재시도(`DB_RETRY_INTERVAL_SEC` 기본 10s, 첫 시도 `DB_INIT_TIMEOUT_SEC` 기본 35s 비차단) 추가. 복구되면 `state["db_conn"]`/`registry._repo`가 채워지고 late-bound `db_ok()`가 자동 200 flip. + 미완료 게임 정리(`cleanup_stale_games`)를 init에서 분리해 **승자 연결로 1회만, readiness flip 전에** 실행 → 늦게 끝난 시도가 라이브 게임을 error로 망가뜨리지 않음. liveness/`run_server.py` 무변경(Cloud Run 무영향). 복구+cleanup-1회 테스트 BR/MS 추가, 전 스위트 회귀 없음. **알려진 한계**(미해결): init 스레드 영구 hang 시 self-heal 불가(드라이버 timeout이 현실적으로 차단), startup BR+MS 직렬 ~70s간 `/livez` 미응답(기존 동작 — k8s startupProbe로 별도 처리). (2026-05-26)
- [x] **A1 GKE game-server 반영** — `fac686b`를 `origin/seongjin-kube`에 push 후 server 이미지 `asia-northeast3-docker.pkg.dev/knu-2026-sungjin0418/ai-arena/server:20260526-fac686b` 빌드/푸시(Cloud Build `1812d477-7594-4d8d-872c-e656b2037f3a`, digest `sha256:cc8b8c5bbc29d5d002f3d0b23391f37f9e97a52566020bb4ca08f9aa973765db`). GKE `deployment/game-server`만 `kubectl set image`로 교체, Cloud Run은 미변경. rollout 성공, Pod `game-server-6f758cf768-z8cmb` 1/1 Running, GKE Ingress `/healthz`·`/livez`·`/battleroyale/health`·`/stocks/health` 200 확인. rollout 직후 502는 GFE/NEG 전파 지연으로 재시도 후 해소. (2026-05-26)
- [x] **A2 [critical] BotRunner fail-open** — 결정: **옵션2 secure-by-default + Cloud Run 명시적 opt-out**. `BOT_RUNNER_REQUIRED` 기본값 false→true(`settings.py` + BR2 `_make_user_bot`), 프로덕션에서 URL 미설정 시 InProcessBot 폴백 대신 거부. Cloud Run은 bot-runner 사이드카가 없어 in-process가 설계 → `cloudbuild.yaml`에 `BOT_RUNNER_REQUIRED=false` 명시적 opt-out 추가(옵션1 엄격안은 Cloud Run 즉시 깨짐으로 기각). MS fail-closed 조건도 `ENV=="production" and REQUIRED`로 BR과 일치. (커밋 `fe6a963`, 2026-05-27) — GKE `server:20260527-fe6a963`/`bot-runner:20260527-fe6a963` 배포 완료
- [x] **A3 [high] BattleRoyale2 WS 무인증 + BR2 RCE** — ① 봇 실행을 InProcessBot2(game-server in-process exec) → bot-runner 격리(`RemoteBattleRoyale2BotAdapter` + executor `battleroyale2` 모드)로 전환(critical RCE 차단, 커밋 `f03d48c`). ② WS `/match/{id}` owner 일치 검사 추가(4403, `ecb0bc2`) + owner 해석 실패(None) fail-closed(`fe6a963`). 인증/owner·Godot WS 토큰은 main이 선구현(`23eafff`/`4ccb09b`). 기록: `backend/BattleRoyale2/HARDENING_CHANGES.md`. (2026-05-27) — GKE 배포 및 BR2 E2E 확인 완료
- [x] **(Codex 후속 P1-A) classic 모드 import 회귀** — bot-runner allowlist 전환(6676e5a) 후 `SAFE_BUILTINS`에 `__import__`가 없어 classic BR/Boss/MS 유저 봇 템플릿(`import random`/`import math`)이 매 틱 STAY/HOLD 폴백되던 프로덕션 회귀. import 화이트리스트를 전 모드 공용(`_safe_import`: math/random/json/collections/heapq/itertools)으로 일반화. (커밋 `fe6a963`, 2026-05-27) — GKE `bot-runner:20260527-fe6a963` 배포 완료

---

## Phase 10 (PR 7). Frontend/API cutover

- [ ] 팀 승인 획득
- [ ] cutover 시간대 합의
- [ ] Firebase/Vite env에서 API base URL을 GKE Ingress IP/도메인으로 변경
- [ ] GKE URL 기준 E2E 재확인
- [ ] WebSocket 관전 연결 확인
- [ ] Cloud Run rollback 절차 문서화 (URL 되돌리기 방법)
- [ ] Cloud Run service 삭제하지 않음 (rollback 대상 유지)

---

## 최종 완료 기준

- [ ] GKE game-server Pod 정상 (replica 1, 세션 외부화 전)
- [ ] GKE bot-runner Pod 2개 이상 정상
- [ ] bot-runner runtimeClassName: gvisor 확인
- [ ] gVisor + Python smoke test 전 항목 통과
- [ ] bot-runner Secret 미주입 확인
- [ ] bot-runner readOnlyRootFilesystem + tmpfs /tmp 적용
- [ ] NetworkPolicy egress deny 적용
- [ ] /healthz (readiness), /livez (liveness) 분리 적용
- [ ] GKE Ingress static IP 예약 및 도메인 매핑
- [ ] BackendConfig WebSocket timeout 3600s 적용
- [ ] Workload Identity game-server → GCS 읽기 성공
- [ ] GCP 예산 알림 설정 완료
- [x] Cloud Build Cloud Run + GKE 병행 배포 수행 중 (2026-05-27, cloudbuild.gke.yaml 트리거 1회 성공, Cloud Run은 InProcessBot 동작 유지)
- [ ] GKE Ingress URL E2E 안정화 확인
- [ ] Cloud Run URL E2E 동시 통과 확인 (cutover 전까지 병행 운영 유지)
- [ ] 팀 승인 후 frontend/API cutover 완료
- [ ] Cloud Run rollback 경로 유지 확인 (cutover 후에도 즉시 되돌릴 수 있는 상태)

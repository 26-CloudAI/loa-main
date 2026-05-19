# LOA Kubernetes 전환 체크리스트

> 상세 설계 근거: `for_kubernetes_migration_plan.md`
> 작업 브랜치: **`seongjin-kube`** (`seongjin` 브랜치와 분리, Kubernetes 전환 전용)
> Git 관리: `.git/info/exclude`의 `for_*.md` 패턴에 의해 로컬 전용

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
- [x] `backend/BotRunner/` 디렉터리 생성
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
- [x] `docker build -f backend/BotRunner/Dockerfile backend/BotRunner` 성공
- [x] `uvicorn main:app --port 8001` 실행 후 `GET /health` 응답 확인 → `{"status":"ok"}`
- [x] `POST /run` 수동 테스트 → BattleRoyale `MOVE_UP` 정상, MockStocks `{"action":"HOLD"}` 정상

---

## Phase 2 (PR 2). RemoteBotAdapter + /healthz + /livez

### BattleRoyale 변경
- [x] `backend/BattleRoyale/src/arena/sandbox/remote_adapter.py` 생성
- [x] `backend/BattleRoyale/src/arena/server/settings.py` — `BOT_RUNNER_URL`, `BOT_RUNNER_TIMEOUT_SEC`, `BOT_RUNNER_REQUIRED` 추가
- [x] `create_game()` — user bot에 `RemoteBattleRoyaleBotAdapter` 사용, AI filler/boss는 in-process 유지
- [x] adapter `__init__`에서 `code_hash = "sha256:" + hashlib.sha256(code.encode()).hexdigest()` 계산
- [x] 매 tick `POST /run` 호출 시 `code_hash + code + state` 전송
- [x] `BOT_RUNNER_REQUIRED=true` + URL 없을 때 503 반환

### MockStocks 변경
- [x] `backend/MockStocks/src/stocks/sandbox/remote_adapter.py` 생성
- [x] `backend/MockStocks/src/stocks/server/settings.py` — 동일 설정 추가
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
- [ ] static IP 예약: `gcloud compute addresses create loa-arena-ingress-ip --global` (Phase 4)
- [x] Ingress에 static IP annotation 연결 (`loa-arena-ingress-ip`)
- [x] ManagedCertificate 도메인 설정 (`api.leagueofagents.net`)

### PR 3 전 검증
- [x] `kubectl apply --dry-run=client -k k8s/base` — 표준 K8s 리소스 11개 통과. BackendConfig/ManagedCertificate는 GKE 전용 CRD라 로컬 에러 예상됨
- [ ] kubeconform 또는 kubeval 스키마 검사 (가능하면)
- [x] bot-runner manifest에 `runtimeClassName: gvisor` 확인
- [x] bot-runner manifest에 `envFrom: secretRef` 없음 확인
- [x] NetworkPolicy egress deny 확인
- [x] YAML 파일에 Secret 값 없음 확인

---

## Phase 4. GKE 클러스터 생성

### 사전 확인
- [ ] Cloud SQL private IP와 동일 VPC에 GKE 생성 가능한지 확인
- [ ] Memorystore Redis와 동일 VPC 접근 가능한지 확인
- [ ] Kubernetes Engine API 활성화
- [ ] Artifact Registry API 활성화
- [ ] Secret Manager API 활성화
- [ ] Cloud SQL Admin API 활성화

### 클러스터 생성
- [ ] VPC/subnet 이름 확인 후 `gcloud container clusters create-auto loa-arena ...` 실행
- [ ] `gcloud container clusters get-credentials loa-arena --region asia-northeast3`
- [ ] `kubectl get nodes` 정상 확인
- [ ] `kubectl get ns` 확인

### gVisor 확인
- [ ] `kubectl get runtimeclass` 출력에 `gvisor` 포함 확인

### Workload Identity 확인
- [ ] `gcloud container clusters describe loa-arena ... --format='value(workloadIdentityConfig.workloadPool)'`
- [ ] 출력값: `PROJECT_ID.svc.id.goog`

### 네트워크 확인
- [ ] GKE Pod에서 Cloud SQL private IP (`10.114.0.3`) 접근 확인
- [ ] GKE Pod에서 Memorystore Redis (`10.197.54.43`) 접근 확인
- [ ] Artifact Registry image pull 권한 확인

---

## Phase 5 (PR 4/5). 이미지 빌드와 배포 파이프라인

### Artifact Registry 이미지 빌드/푸시 (수동)
- [ ] `docker build` server 이미지 성공
- [ ] `docker build` bot-runner 이미지 성공
- [ ] `docker push` server 이미지 성공
- [ ] `docker push` bot-runner 이미지 성공

### 수동 GKE 배포 (PR 4)
- [ ] Secret 수동 생성: `kubectl create secret generic arena-secrets --namespace arena ...`
- [ ] ConfigMap 적용 (BOSS_WEIGHTS_GCS_URI 포함하여 Cloud Build step 방식으로)
- [ ] `kubectl apply -f k8s/base` (configmap 제외)
- [ ] `kubectl set image deployment/game-server ...`
- [ ] `kubectl set image deployment/bot-runner ...`
- [ ] `kubectl rollout status deployment/game-server` 성공
- [ ] `kubectl rollout status deployment/bot-runner` 성공

### Cloud Build SA 권한 부여 (PR 5 전)
- [ ] `roles/container.developer` Cloud Build SA에 부여
- [ ] Artifact Registry push 권한 확인

### cloudbuild.yaml GKE 병행 배포 추가 (PR 5)
- [ ] 팀 승인 획득
- [ ] bot-runner 이미지 빌드/푸시 step 추가
- [ ] ConfigMap Cloud Build step 추가 (`BOSS_WEIGHTS_GCS_URI` substitution 주입)
- [ ] `kubectl apply -f k8s/base` step 추가 (configmap 미포함 또는 Cloud Build step 이후 실행)
- [ ] `kubectl set image` + `rollout status` step 추가
- [ ] 기존 `gcloud run deploy` step 유지 확인
- [ ] `kubectl rollout status` 실패 시 build 실패 처리 확인
- [ ] Secret 값이 Cloud Build 로그에 출력되지 않는지 확인

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
- [ ] game-server ServiceAccount 생성
- [ ] bot-runner ServiceAccount 생성 (`automountServiceAccountToken: false`)

### Workload Identity 설정
- [ ] GCP SA `game-server-sa` 생성 (또는 기존 재사용)
- [ ] `roles/storage.objectViewer` → `game-server-sa` 부여
- [ ] `roles/iam.workloadIdentityUser` 바인딩 (`PROJECT_ID.svc.id.goog[arena/game-server]`)
- [ ] Kubernetes SA `game-server`에 `iam.gke.io/gcp-service-account` annotation 추가

### 검증
- [ ] game-server Pod에서 GCS boss weights 읽기 성공
- [ ] bot-runner Pod에 DB/Firebase/Gemini/JWT Secret env 없음 확인
- [ ] bot-runner Pod에 service account token 자동 mount 없음 확인

---

## Phase 7. gVisor Smoke Test (PR 4 단계 필수)

> Phase 0.4에서 임시 Pod 기준 사전 통과를 확인한 이후, 실제 bot-runner Deployment Pod에서 재확인하는 단계.

- [ ] `kubectl -n arena exec deploy/bot-runner -- python -c "import multiprocessing...` 실행
- [ ] `multiprocessing.Process` spawn 성공 (`mp ok` 출력)
- [ ] `resource.setrlimit(RLIMIT_CPU, ...)` 성공 (`rlimit ok` 출력)
- [ ] `signal.alarm(5); signal.alarm(0)` 성공 (`signal ok` 출력)
- [ ] `tempfile.NamedTemporaryFile(dir='/tmp')` 성공 (`tmpfile ok` 출력)
- [ ] 실패 시: Phase 0.4에서 이미 결정된 대체 격리 방안으로 전환 (일반 Pod + NetworkPolicy/resource limit 강화)

---

## Phase 8. Kubernetes Smoke / E2E 테스트

### 기본 상태 확인
- [ ] `kubectl -n arena get pods` — game-server, bot-runner 모두 Running
- [ ] `kubectl -n arena get svc` 확인
- [ ] `kubectl -n arena get ingress` — IP 할당 확인
- [ ] `kubectl -n arena logs deploy/game-server` — 에러 없음
- [ ] `kubectl -n arena logs deploy/bot-runner` — 에러 없음

### Health 확인 (GKE)
- [ ] `curl <GKE_INGRESS_URL>/healthz` → `{"status": "ok", ...}`
- [ ] `curl <GKE_INGRESS_URL>/livez` → `{"status": "alive"}`
- [ ] `curl <GKE_INGRESS_URL>/battleroyale/health` 정상
- [ ] `curl <GKE_INGRESS_URL>/stocks/health` 정상

### Health 확인 (Cloud Run — 병행 운영 검증)
- [ ] `curl <CLOUD_RUN_URL>/battleroyale/health` 정상 (GKE 배포 후에도 Cloud Run 유지 확인)
- [ ] `curl <CLOUD_RUN_URL>/stocks/health` 정상

### gVisor 런타임 확인
- [ ] `kubectl -n arena get pods -l app=bot-runner -o jsonpath=...` → `gvisor` 확인

### NetworkPolicy 확인
- [ ] game-server → bot-runner `/run` 호출 성공
- [ ] bot-runner → 외부 인터넷 호출 실패 확인

### E2E 확인
- [ ] 로그인 정상
- [ ] BattleRoyale 게임 생성 → 관전 WebSocket 연결 → 종료 → 결과 페이지
- [ ] Boss 게임 생성 → 관전 → 종료 → 결과
- [ ] MockStocks 게임 생성 → 관전 → 종료 → 결과
- [ ] GamesPage active/history 목록 정상
- [ ] 계정별 owner filtering 정상
- [ ] 유저 봇 코드에서 `os.environ` 접근 시 서버 Secret 미노출 확인
- [ ] BackendConfig WebSocket timeout: 장시간 관전 중 연결 유지 확인

---

## Phase 9 (PR 6). GKE 안정화 관찰

- [ ] Cloud Build가 **Cloud Run + GKE 병행 배포** 1회 이상 성공 (같은 이미지, 다른 환경변수로 각자 동작)
- [ ] GKE Ingress URL 기준 BattleRoyale/Boss/MockStocks E2E 통과
- [ ] Cloud Run URL 기준 동일 E2E 통과 확인 (병행 운영 유지 검증)
- [ ] WebSocket 장시간 관전 연결 유지 확인 (GKE 기준)
- [ ] Cloud SQL/Redis/GCS 접근 안정성 확인 (수일 관찰)
- [ ] GKE 비용 모니터링 — 예산 알림 미발생 확인
- [ ] 로그량/에러율 Cloud Run과 비교
- [ ] Cloud Run rollback 경로 유효성 재확인 (Cloud Run URL이 여전히 정상 응답하는지)

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
- [ ] Cloud Build Cloud Run + GKE 병행 배포 수행 중 (같은 이미지, Cloud Run은 InProcessBot 동작 유지)
- [ ] GKE Ingress URL E2E 안정화 확인
- [ ] Cloud Run URL E2E 동시 통과 확인 (cutover 전까지 병행 운영 유지)
- [ ] 팀 승인 후 frontend/API cutover 완료
- [ ] Cloud Run rollback 경로 유지 확인 (cutover 후에도 즉시 되돌릴 수 있는 상태)

# LOA Kubernetes 전환 계획서

> 작성일: 2026-05-12  
> 작업 브랜치: **`seongjin-kube`** (Kubernetes 전환 전용, `seongjin` 브랜치와 분리)  
> 파일 위치: 레포 루트 (`WORK_LOG.md`와 동일 경로)  
> Git 관리: `.git/info/exclude`의 `for_*.md` 패턴에 의해 로컬 전용으로 유지

---

## 브랜치 전략

| 브랜치 | 용도 |
| --- | --- |
| `main` | 운영 기준 브랜치. PR 대상. |
| `seongjin` | 기존 기능 작업 전용. Kubernetes 관련 변경 없음. |
| `seongjin-kube` | Kubernetes 전환 작업 전용. 이 계획서의 모든 PR은 이 브랜치에서 진행. |

- `seongjin-kube`는 `seongjin`에서 분기한다.
- Kubernetes 코드(BotRunner, RemoteBotAdapter, k8s/, cloudbuild.yaml GKE step)는 모두 `seongjin-kube`에만 커밋한다.
- `seongjin-kube`의 PR은 `main`으로 머지한다.
- 기존 `seongjin` 작업이 먼저 머지되면 `seongjin-kube`를 rebase한다.

---

## 0. 결론

현재 레포 상태에서 Kubernetes로 바로 전환하려면 단순히 Cloud Run 배포 명령을 `kubectl apply`로 바꾸는 수준이 아니다. 실제 전환 범위는 아래 네 가지를 함께 포함한다.

1. **게임 서버 런타임 이전**
   - 기존 Cloud Run `ai-arena-server`를 GKE `game-server` Deployment로 이전
   - `/battleroyale`, `/stocks` 통합 FastAPI 서버는 그대로 유지

2. **유저 봇 실행 격리**
   - 현재 `InProcessBot`의 서버 프로세스 내 `exec()` 제거
   - 별도 `bot-runner` Deployment에서 유저 코드 실행
   - `bot-runner` Pod에만 `runtimeClassName: gvisor` 적용

3. **GCP 관리형 리소스 연결**
   - Cloud SQL PostgreSQL 연결
   - Memorystore Redis 연결
   - Secret Manager / Kubernetes Secret 연동
   - GCS boss weight 읽기

4. **배포 파이프라인 병행화 후 정식 전환**
   - 처음에는 `cloudbuild.yaml`에 GKE deploy 경로를 추가하고, 기존 Cloud Run deploy는 유지
   - GKE 안정화가 끝난 뒤 프론트/API 트래픽을 GKE로 정식 전환
   - trainer는 1차로 Cloud Run Job 유지, 안정화 후 Kubernetes CronJob 이전 여부 결정

권장 순서는 **GKE 기반 게임 서버 이전과 Bot Runner 분리를 한 프로젝트로 보되, PR/작업 단위는 6~8개로 쪼개는 것**이다. 한 번에 다 바꾸면 장애 원인 분리가 어렵다. 특히 Cloud Run은 안정화가 끝날 때까지 rollback 대상으로 남겨둔다.

---

## 0-A. 병행 운영 전략 (핵심 원칙)

**Cloud Run과 GKE는 동시에 살아 있는 상태로 전환을 진행한다.**

### 목표 상태 (안정화 기간 중)

```text
[현재 운영]                        [새로운 GKE 시스템]
Cloud Run ai-arena-server   +      GKE game-server
  ↑                                  ↑
  Firebase frontend (운영)           직접 URL 또는 별도 환경으로 검증
  (트래픽 계속 여기로)               (트래픽 없음, 내부 검증 전용)
```

### 원칙

1. **Cloud Run은 PR 7(Frontend cutover) 전까지 절대 삭제하지 않는다.**
   - Cloud Build에 GKE 배포 step을 추가한 뒤에도 기존 `gcloud run deploy` step을 함께 유지한다.
   - 매 배포마다 Cloud Run과 GKE 양쪽 모두 같은 이미지로 업데이트된다.
   - **단, Cloud Run과 GKE는 환경변수 설정이 다르기 때문에 동작 방식이 다르다.**
     - Cloud Run: `BOT_RUNNER_URL` 미설정 → `InProcessBot` fallback 유지 (기존 동작 그대로)
     - GKE: `BOT_RUNNER_URL = http://bot-runner...` 설정 → `RemoteBotAdapter` 사용
   - 즉 Cloud Run은 코드만 업데이트될 뿐, 실행 방식은 변경 전과 동일하다.

2. **프론트엔드(Firebase)의 API base URL은 안정화 완료 전까지 Cloud Run을 가리킨다.**
   - 실제 사용자 트래픽은 계속 Cloud Run으로 간다.
   - GKE는 내부 검증(개발자 직접 URL 접근, curl, E2E 스크립트)으로만 확인한다.

3. **GCP에서 확인이 필요한 시점마다 양쪽 시스템이 모두 응답하는지 검증한다.**
   - Cloud Run URL: `https://ai-arena-server-6eb5desvgq-du.a.run.app`
   - GKE Ingress URL: `https://<GKE_INGRESS_IP>` (발급 후 확인)
   - 두 URL 모두 `/healthz`, E2E가 통과해야 다음 Phase로 넘어간다.

4. **Cloud Run rollback 절차는 항상 유효하게 유지한다.**
   - `gcloud run deploy`로 언제든 이전 이미지로 되돌릴 수 있다.
   - GKE 전환 후 문제가 생기면 프론트 환경변수 1개만 바꿔서 Cloud Run으로 즉시 복귀한다.

### 병행 운영 기간 비용 고려

- Cloud Run + GKE 동시 운영 기간에는 두 시스템 비용이 동시에 발생한다.
- GKE Autopilot은 idle Pod도 요금이 나온다.
- Phase 0.3에서 예산 한도를 확인하고 Phase 9 안정화 기간을 너무 길게 잡지 않는다.

---

## 1. 현재 레포 상태 요약

### 1.1 배포 구조

현재 운영 배포는 `cloudbuild.yaml` 기준으로 다음 구조다.

```text
Cloud Build
├─ backend/Dockerfile 빌드
│  └─ Artifact Registry: server 이미지
├─ backend/Dockerfile.trainer 빌드
│  └─ Artifact Registry: trainer 이미지
├─ Cloud Run service deploy: ai-arena-server
└─ Cloud Run job deploy: boss-trainer
```

`backend/Dockerfile`은 BattleRoyale와 MockStocks를 하나의 `/app/src` 패키지 아래에 병합한다.

```text
/app
├─ run_server.py
├─ src/arena/   # BattleRoyale
├─ src/stocks/  # MockStocks
└─ bots/        # BattleRoyale + MockStocks bots 병합
```

운영 API 경로는 통합 FastAPI 앱의 mount 구조다.

```text
/battleroyale/*
/stocks/*
```

### 1.2 현재 보안 취약 지점

BattleRoyale:

```text
backend/BattleRoyale/src/arena/server/app.py
└─ create_game()
   └─ InProcessBot(...)
      └─ exec(code, local_ns)
```

MockStocks:

```text
backend/MockStocks/src/stocks/server/app.py
└─ create_game()
   └─ InProcessBot(...)
      └─ exec(code, ns)
```

즉, 유저 제출 Python 코드가 DB/Firebase/Gemini 시크릿을 가진 게임 서버 프로세스 안에서 실행된다.

### 1.3 이미 존재하지만 운영에 연결되지 않은 자산

BattleRoyale에는 Docker 샌드박스 관련 코드가 있다.

```text
backend/BattleRoyale/src/arena/sandbox/
├─ config.py
├─ container_manager.py
├─ docker_adapter.py
├─ pool.py
└─ wrapper_template.py
```

하지만 운영 `create_game()` 경로는 이 코드를 쓰지 않는다. 또한 Cloud Run 서버 컨테이너 안에서 Docker를 실행하는 구성도 아니다.

MockStocks에는 동일한 sandbox 패키지가 없다. 따라서 Kubernetes 전환 시에는 BattleRoyale 전용 `DockerBotAdapter`를 그대로 재사용하기보다, 두 게임 모드가 공유할 **HTTP 기반 RemoteBotAdapter + Bot Runner API**를 새로 잡는 편이 맞다.

---

## 2. 목표 아키텍처

### 2.1 1차 목표 아키텍처

```text
Firebase Hosting
└─ React frontend
   └─ HTTPS
      └─ GKE Ingress / Google Cloud Load Balancer
         └─ game-server Service
            └─ game-server Deployment
               ├─ /battleroyale/*
               ├─ /stocks/*
               ├─ Cloud SQL PostgreSQL
               ├─ Memorystore Redis
               ├─ Secret Manager / Kubernetes Secret
               └─ HTTP
                  └─ bot-runner Service
                     └─ bot-runner Deployment
                        ├─ runtimeClassName: gvisor
                        ├─ no DB/Firebase/Gemini secrets
                        ├─ NetworkPolicy ingress: game-server only
                        └─ NetworkPolicy egress: deny by default
```

### 2.2 유지할 것

- React frontend는 Firebase Hosting 유지
- BattleRoyale/MockStocks 통합 서버 구조 유지
- Cloud SQL PostgreSQL 유지
- Memorystore Redis 유지
- GCS boss weights 유지
- 기존 REST/WS URL path 유지: `/battleroyale`, `/stocks`

### 2.3 바꿀 것

- Cloud Run service -> GKE Deployment/Service/Ingress
- Cloud Run secret/env 설정 -> Kubernetes Secret/ConfigMap
- Cloud Run VPC connector -> GKE VPC-native 네트워크
- 유저 봇 `InProcessBot` -> `RemoteBotAdapter`
- 유저 코드 실행 위치 -> `bot-runner` Pod
- Bot Runner Pod -> GKE Sandbox(gVisor)

### 2.4 나중으로 미룰 수 있는 것

- `boss-trainer` Cloud Run Job을 Kubernetes CronJob으로 이전
- Prometheus/Grafana 고급 대시보드
- External Secrets Operator 도입
- GitOps/Cloud Deploy 도입

---

## 3. 핵심 설계 결정

### 결정 1. GKE 모드는 Autopilot으로 시작

이유:

- 노드 관리, 업그레이드, 스케일링 부담을 줄인다.
- GKE Sandbox(gVisor)를 Pod 단위로 적용할 수 있다.
- 캡스톤 팀이 직접 노드풀 운영까지 맡지 않아도 된다.

주의:

- Autopilot도 Kubernetes 리소스와 네트워크 디버깅은 필요하다.
- Cloud Run처럼 완전히 단순한 배포 경험은 아니다.
- region은 현재 Cloud Run/Cloud SQL과 같은 `asia-northeast3` 기준으로 맞춘다.

### 결정 2. Bot Runner만 gVisor 적용

`game-server`는 일반 Pod로 둔다. `bot-runner`에만 다음을 적용한다.

```yaml
runtimeClassName: gvisor
```

이유:

- 유저 코드 실행 Pod에만 sandbox overhead를 부담시킨다.
- DB/Firebase/Gemini/GCS 접근이 필요한 game-server는 일반 런타임으로 안정성을 우선한다.
- 공격 표면이 가장 큰 부분은 유저 코드 실행 경로다.

### 결정 3. Bot Runner는 Secret을 받지 않는다

`bot-runner` Deployment에는 다음을 주입하지 않는다.

- `DB_PASSWORD`
- `FIREBASE_CREDENTIALS_JSON`
- `GEMINI_API_KEY`
- `JWT_SECRET`
- `BOSS_WEIGHTS_GCS_URI`
- GCP service account 권한

Bot Runner가 알아야 하는 것은 실행 대상 코드와 game state뿐이다.

### 결정 4. 게임 서버와 Bot Runner는 HTTP API로만 통신

게임 서버 내부에는 게임 모드별 `BotInterface`를 만족하는 어댑터를 둔다.

```text
BattleRoyale BotInterface.get_action(state) -> str
MockStocks   BotInterface.get_action(state) -> dict
```

외부 호출은 공통 RemoteBotAdapter가 담당한다.

```text
RemoteBotAdapter
├─ POST /run (code_hash + code + state)
├─ timeout/error handling
└─ default action fallback
```

### 결정 5. Cloud SQL은 1차에서 Private IP 직접 연결을 우선 검토

현재 Cloud Run은 `DB_HOST=10.114.0.3` 형태의 Private IP로 보인다. GKE 클러스터를 같은 VPC/region에 만들면 Private IP 직접 연결 구조를 유지할 수 있다.

대안은 Cloud SQL Auth Proxy sidecar다.

| 방식 | 장점 | 단점 |
| --- | --- | --- |
| Private IP 직접 연결 | 단순, 현재 설정과 유사 | VPC/subnet/방화벽 조건 확인 필요 |
| Cloud SQL Auth Proxy sidecar | IAM 기반 연결, Cloud SQL 표준 패턴 | sidecar, Workload Identity, 포트 설정 추가 |

1차 전환은 **Private IP 직접 연결**을 기준으로 계획한다. 연결 실패 또는 보안 요구가 커지면 Auth Proxy로 전환한다.

### 결정 6. Redis는 기존 Memorystore 유지

GKE 안에 Redis Pod를 띄우지 않는다.

이유:

- 기존 `REDIS_HOST=10.197.54.43` 구조가 있다.
- Redis를 클러스터 안으로 옮기면 persistence/backup/HA를 새로 떠안는다.
- 현재 목적은 서버 런타임과 봇 실행 격리 이전이다.

---

## 4. 작업 단계

## Phase 0. 사전 점검

목표: GKE 작업 전에 현재 Cloud Run 운영 설정을 정확히 수집한다.

### 0.1 현재 GCP 리소스 확인

확인 항목:

- project id
- region: `asia-northeast3`
- Artifact Registry repository: `ai-arena`
- Cloud Run service: `ai-arena-server`
- Cloud Run job: `boss-trainer`
- Cloud SQL instance: `arena-db`
- Cloud SQL private IP: 현재 `DB_HOST=10.114.0.3`와 일치하는지
- Memorystore Redis private IP: 현재 `_REDIS_HOST=10.197.54.43`와 일치하는지
- VPC connector: `arena-connector`
- VPC/subnet 이름
- Secret Manager secrets:
  - `firebase-service-account`
  - `db-password`
  - `GEMINI_API_KEY`
- GCS bucket: `BOSS_WEIGHTS_GCS_URI` 값으로 확인
  - 최신 `cloudbuild.yaml`은 실제 버킷 URI를 하드코딩하지 않고 Cloud Build trigger substitution으로 주입하는 방향이다.
  - 계획서/PR에는 실제 버킷명을 쓰지 않는다.

예상 명령:

```bash
gcloud config get-value project
gcloud run services describe ai-arena-server --region asia-northeast3
gcloud sql instances describe arena-db
gcloud redis instances list --region asia-northeast3
gcloud secrets list
gcloud artifacts repositories list --location asia-northeast3
```

### 0.2 현재 API/health 기준선 저장

Kubernetes 전환 후 비교할 기준선을 남긴다.

확인:

- `/battleroyale/health`
- `/stocks/health`
- 로그인 후 게임 생성
- BattleRoyale 관전 WebSocket
- MockStocks 관전 WebSocket
- 게임 종료 후 결과 조회
- GamesPage 활성/이력 목록

산출물:

- `WORK_LOG.md`에 현재 운영 baseline 요약
- 필요 시 스크린샷 또는 Obsidian 세션 로그

### 0.3 비용 예산 확인

GKE Autopilot은 Cloud Run과 달리 Pod가 idle이어도 비용이 계속 발생한다. 캡스톤 기간 동안 GCP 크레딧이 떨어지지 않게 사전 확인이 필요하다.

확인 항목:

- 현재 Cloud Run 월 비용 baseline (Cloud Console > 청구 > 보고서)
- 남은 GCP 크레딧/예산 잔액
- GKE Autopilot 예상 비용
  - game-server 2 replica × (0.5 vCPU + 512Mi) 상시 운영
  - bot-runner 2 replica × (0.5 vCPU + 256Mi) 상시 운영
  - Ingress, Load Balancer 시간당 요금
  - Autopilot Pod overhead 요금
- 예산 알림 설정

예산 알림 명령 예시:

```bash
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="loa-arena-gke-budget" \
  --budget-amount=100USD \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100
```

산출물:

- `WORK_LOG.md`에 baseline Cloud Run 비용과 GKE 전환 예상 비용 비교 메모
- 예산 알림 설정 완료 여부

### 0.4 gVisor 사전 호환성 확인

Bot Runner의 핵심 격리 수단인 `multiprocessing.Process` spawn이 gVisor에서 동작하는지 **Phase 0 단계에서 미리 확인한다.**

이것을 PR 4(GKE staging 배포) 이후로 미루면, Phase 1-3 전체를 재설계해야 하는 상황이 PR 4에서 발생할 수 있다.

사전 확인 방법:

1. 임시 gVisor Pod를 기존 또는 신규 클러스터에 띄운다 (클러스터가 없으면 Phase 4 완료 후 즉시 진행).
2. 아래 명령으로 smoke test를 실행한다.

```bash
kubectl run gvisor-probe --image=python:3.11-slim \
  --overrides='{"spec":{"runtimeClassName":"gvisor"}}' \
  --restart=Never --rm -it -- python -c "
import multiprocessing, resource, signal, tempfile
def f(): pass
p = multiprocessing.Process(target=f); p.start(); p.join()
print('mp ok')
resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
print('rlimit ok')
signal.alarm(5); signal.alarm(0)
print('signal ok')
with tempfile.NamedTemporaryFile(dir='/tmp') as t:
    t.write(b'hello')
print('tmpfile ok')
"
```

결과 판단:

- **전 항목 통과**: Bot Runner multiprocessing 격리 방식 유지, Phase 1 코드 그대로 진행.
- **실패 항목 있음**: gVisor 포기. bot-runner를 일반 Pod(`runtimeClassName` 제거)로 전환하고, NetworkPolicy egress deny + resource limit + readOnlyRootFilesystem + AST 검사 조합으로 격리를 대체 설계한다. **thread executor 대체는 절대 불가** — 같은 프로세스 내 실행이므로 메모리/CPU 격리가 불가능하다.

산출물:

- `WORK_LOG.md`에 결과 기록 (통과/실패 항목 명시)
- 실패 시 Phase 1 시작 전 대체 설계 확정

### Phase 0 PR 분리 시점

이 Phase는 **PR을 만들지 않는다.**

이유:

- 대부분 GCP 리소스 조사, 운영 baseline 기록, 로컬 개인 문서 업데이트다.
- Secret/프로젝트 설정/운영 URL 등 민감 정보가 섞일 수 있다.
- 산출물은 `WORK_LOG.md`, Obsidian, Notion 같은 개인/운영 기록에 남기는 것이 맞다.

다음 Phase로 넘어가기 전에 필요한 조건:

- Cloud SQL/Redis private IP와 VPC 정보 확인
- 현재 Cloud Run health/E2E baseline 확인
- GKE 전환 중 rollback 대상이 될 기존 Cloud Run 서비스가 정상임을 확인

---

## Phase 1. Bot Runner API와 실행 모델 설계

목표: Kubernetes에서 실행될 유저 코드 실행 서비스를 먼저 코드 레벨로 정의한다.

### 1.1 신규 디렉터리

```text
backend/BotRunner/
├─ Dockerfile
├─ requirements.txt
├─ main.py
├─ schemas.py
├─ cache.py
├─ executor.py
├─ policy.py
└─ tests/
   ├─ test_run.py
   ├─ test_timeout.py
   ├─ test_forbidden_imports.py
   └─ test_mode_contracts.py
```

### 1.2 API 스키마

API는 stateless `/run` 단일 엔드포인트로 구성한다. registry 없이 매 tick 요청에 코드와 상태를 함께 보낸다. 코드 컴파일 비용은 `code_hash` 기반 in-process cache로 흡수한다.

```http
GET /health
```

```json
{"status": "ok"}
```

```http
POST /run
```

```json
{
  "mode": "battleroyale",
  "bot_id": "user-bot-1",
  "code_hash": "sha256:abc123",
  "code": "def action(state): return 'STAY'",
  "state": {}
}
```

`code_hash`는 `SHA-256(code)` 값이며 **게임 서버 adapter(RemoteBotAdapter)** 가 봇 초기화 시 계산한다. Bot Runner는 직접 계산하지 않고 요청에서 받은 값을 캐시 키로만 사용한다.

`code_hash`가 cache에 있으면 `code`는 optional. cache miss 시 `code`로 컴파일 후 cache에 저장. cache는 in-process LRU (예: `cachetools.LRUCache(maxsize=512)`).

BattleRoyale 응답:

```json
{
  "ok": true,
  "action": "MOVE_UP_LEFT"
}
```

최신 BattleRoyale는 8방향 이동/공격을 포함한 19개 action을 사용한다. Bot Runner의 BattleRoyale allowlist는 기존 `wrapper_template.py`의 하드코딩된 `VALID_ACTIONS`를 복사하지 말고, 최신 `src.arena.types.Action`과 동일하게 맞춘다.

```text
STAY
MOVE_UP, MOVE_DOWN, MOVE_LEFT, MOVE_RIGHT
MOVE_UP_LEFT, MOVE_UP_RIGHT, MOVE_DOWN_LEFT, MOVE_DOWN_RIGHT
MINE
ATTACK_UP, ATTACK_DOWN, ATTACK_LEFT, ATTACK_RIGHT
ATTACK_UP_LEFT, ATTACK_UP_RIGHT, ATTACK_DOWN_LEFT, ATTACK_DOWN_RIGHT
SHIELD
```

MockStocks 응답:

```json
{
  "ok": true,
  "action": {
    "action": "BUY",
    "symbol": "APEX",
    "quantity": 10
  }
}
```

에러 응답은 항상 HTTP 200 + fallback action으로 통일한다.

```json
{
  "ok": false,
  "error": "timeout",
  "action": "STAY"
}
```

또는 MockStocks:

```json
{
  "ok": false,
  "error": "timeout",
  "action": {"action": "HOLD"}
}
```

이유:

- 게임 루프가 HTTP 500 때문에 중단되면 안 된다.
- Bot Runner 내부 오류는 봇의 기본 액션으로 흡수한다.
- 게임 서버는 timeout/error counter만 기록한다.

### 1.3 stateless /run 방식 선택 이유

Bot Runner는 단일 `/run` 엔드포인트만 가진 stateless 서비스로 구현한다.

선택 이유:

- **수평 확장 안전**: replica가 몇 개든 어느 Pod에 요청이 가도 동작함. registry 기반이면 "등록한 Pod"에 요청이 가야 하는 session affinity 문제 발생.
- **Pod 재시작 무결함**: registry가 없으니 Pod이 죽어도 진행 중인 게임이 터지지 않음.
- **구현 단순**: register/action 두 엔드포인트 + in-memory registry 대신 cache 하나로 끝남.

컴파일 비용 대응:

```text
요청에 code_hash 포함
→ cache hit: 컴파일 생략, action 함수 재사용
→ cache miss: code 컴파일 후 LRUCache에 저장
```

payload 크기 우려: 코드가 수 KB 수준이고 클러스터 내부 통신이므로 무시 가능. correctness > 최적화 순서.

Bot Runner 내부 cache:

```text
key   = code_hash (SHA-256)
value = compiled action function + mode metadata
```

### 1.4 executor 보안 정책

최소 정책:

- 코드 크기 제한: 50KB 유지
- AST 정적 검사
  - `import os`, `import socket`, `import subprocess`, `import pathlib`, `import builtins` 차단
  - `open`, `exec`, `eval`, `compile`, `__import__`, `globals`, `locals`, `vars`, `dir` 차단
  - dunder attribute 접근 제한
- 실행 timeout
  - BattleRoyale: 100ms 기준
  - MockStocks: 100ms 또는 별도 env `BOT_ACTION_TIMEOUT_SEC`
- 프로세스 격리
  - Bot Runner API 프로세스와 user action 실행 프로세스를 분리
  - `multiprocessing` 또는 worker process pool 사용
  - gVisor 환경에서 `multiprocessing.Process` spawn이 실패하면 **프로덕션 배포를 중단(fail closed)** 한다. thread executor는 untrusted code에 절대 사용 불가 — 같은 프로세스에서 실행되므로 메모리/CPU 격리가 불가능하고 악성 봇이 다른 봇 데이터에 접근할 수 있다. 대안: 일반 Pod + NetworkPolicy/resource limit/readOnlyRootFilesystem/AST 검사 강화 (Phase 8.4 smoke test 참고)
- resource limit
  - CPU time
  - address space / memory
  - file size 0
  - process count 제한
- 환경변수 제거
  - child process에서 `os.environ.clear()`
- 파일시스템 쓰기 금지
  - 컨테이너 readOnlyRootFilesystem
  - writable tmpfs가 필요하면 sizeLimit 적용

주의:

- AST 검사는 보조 수단이다. 최종 격리는 Pod/gVisor/NetworkPolicy/resource limit이 담당한다.
- Python sandbox는 완전하지 않다. 같은 프로세스 내 제한에 기대면 안 된다.

### Phase 1 PR 분리 시점

이 Phase가 끝나면 **PR 1: Bot Runner 코드 추가**로 끊는다.

포함할 파일:

```text
backend/BotRunner/
```

포함하지 않을 파일:

```text
backend/BattleRoyale/src/arena/server/app.py
backend/MockStocks/src/stocks/server/app.py
k8s/
cloudbuild.yaml
frontend/
```

PR 목적:

- Bot Runner를 독립 서비스로 실행할 수 있는지 검증
- BattleRoyale/MockStocks action contract를 Bot Runner 레벨에서 고정
- timeout/fallback/금지 패턴 정책을 게임 서버 변경 없이 먼저 리뷰 가능하게 함

PR 전 검증:

- Bot Runner unit test 통과
- `backend/BotRunner/Dockerfile` build 통과
- 로컬 `uvicorn main:app --port 8001` 실행 후 `/health`, action API 수동 확인

이 PR은 아직 운영 경로를 바꾸지 않으므로 배포 리스크가 낮다.

---

## Phase 2. 게임 서버 RemoteBotAdapter 도입

목표: 유저 봇 실행 경로를 Bot Runner HTTP 호출로 바꾼다.

### 2.1 BattleRoyale 변경 파일

예상 변경:

```text
backend/BattleRoyale/src/arena/sandbox/remote_adapter.py
backend/BattleRoyale/src/arena/server/settings.py
backend/BattleRoyale/src/arena/server/app.py
backend/BattleRoyale/tests/test_remote_bot_adapter.py
backend/BattleRoyale/tests/test_create_game_uses_remote_bot.py
```

`settings.py` 추가:

```python
BOT_RUNNER_URL = os.environ.get("BOT_RUNNER_URL", "")
BOT_RUNNER_TIMEOUT_SEC = float(os.environ.get("BOT_RUNNER_TIMEOUT_SEC", "0.1"))
BOT_RUNNER_REQUIRED = os.environ.get("BOT_RUNNER_REQUIRED", "false").lower() in ("true", "1", "yes")
```

`create_game()` 정책:

```text
if user bot:
  if BOT_RUNNER_URL:
    RemoteBattleRoyaleBotAdapter(...)
  elif ENV == "production" and BOT_RUNNER_REQUIRED:
    503
  else:
    InProcessBot fallback

if AI filler/boss:
  existing in-process bot
```

Kubernetes production에서는 `BOT_RUNNER_REQUIRED=true`로 둔다.

### 2.2 MockStocks 변경 파일

예상 변경:

```text
backend/MockStocks/src/stocks/sandbox/remote_adapter.py
backend/MockStocks/src/stocks/server/settings.py
backend/MockStocks/src/stocks/server/app.py
backend/MockStocks/tests/test_remote_bot_adapter.py
backend/MockStocks/tests/test_create_game_uses_remote_bot.py
```

MockStocks는 반환 타입이 `dict`다.

Fallback:

```python
{"action": "HOLD"}
```

### 2.3 통합 /healthz + /livez 엔드포인트 추가

현재 health 엔드포인트는 sub-app 단위로 존재한다.

```text
/battleroyale/health
/stocks/health
```

문제:

- `/battleroyale/health`만 readiness probe로 쓰면 MockStocks DB 초기화 실패를 감지하지 못한다.
- readiness와 liveness를 같은 엔드포인트로 쓰면 DB 장애 시 정상 Pod이 재시작된다 — 메모리에 있던 진행 중 게임이 날아간다.

추가할 엔드포인트:

```text
GET /healthz   → readiness probe용 (DB/의존성 포함)
GET /livez     → liveness probe용 (프로세스 생존만 확인)
```

`/healthz` 응답 (정상):

```json
{
  "status": "ok",
  "battleroyale": {"db": "ok"},
  "stocks": {"db": "ok"}
}
```

`/healthz` 응답 (DB 실패) — HTTP 503:

```json
{
  "status": "degraded",
  "battleroyale": {"db": "error"},
  "stocks": {"db": "ok"}
}
```

`/livez` 응답 — HTTP 200 고정, DB/Redis/GCS 체크 없음:

```json
{"status": "alive"}
```

프로브 역할 분리:

- **readinessProbe** → `/healthz`: DB가 죽으면 Pod을 서비스에서 제외. 재시작하지 않음.
- **livenessProbe** → `/livez`: 프로세스가 완전히 멈췄을 때만 재시작.

변경 파일:

```text
backend/run_server.py
backend/BattleRoyale/src/arena/server/app.py (또는 lifespan 상태 노출)
backend/MockStocks/src/stocks/server/app.py (또는 lifespan 상태 노출)
```

이 작업은 PR 2에 포함하거나, Phase 3 manifest 작성 전에 별도 작은 PR로 분리한다. Phase 3 PR에서 probe path를 지정하려면 이 작업이 선행되어야 한다.

### 2.4 공통화 여부

이상적으로는 공통 패키지를 둔다.

```text
backend/shared/bot_runner_client.py
```

하지만 현재 Dockerfile은 `BattleRoyale/src`와 `MockStocks/src/stocks`만 복사한다. 공통 패키지를 추가하려면 Dockerfile과 로컬 import path 설계도 같이 바꿔야 한다.

초기에는 중복이 조금 있어도 아래처럼 각 게임 모드에 얇은 adapter를 두는 편이 리스크가 낮다.

```text
BattleRoyale/src/arena/sandbox/remote_adapter.py
MockStocks/src/stocks/sandbox/remote_adapter.py
```

중복되는 HTTP client 로직은 나중에 정리한다.

### Phase 2 PR 분리 시점

이 Phase가 끝나면 **PR 2: 게임 서버 RemoteBotAdapter 연결**로 끊는다.

포함할 파일:

```text
backend/BattleRoyale/src/arena/sandbox/remote_adapter.py
backend/BattleRoyale/src/arena/server/settings.py
backend/BattleRoyale/src/arena/server/app.py
backend/BattleRoyale/tests/
backend/MockStocks/src/stocks/sandbox/remote_adapter.py
backend/MockStocks/src/stocks/server/settings.py
backend/MockStocks/src/stocks/server/app.py
backend/MockStocks/tests/
```

포함하지 않을 파일:

```text
k8s/
cloudbuild.yaml
frontend/
```

PR 목적:

- 유저 봇 실행 경로를 `RemoteBotAdapter`로 전환할 수 있게 함
- AI filler/boss 봇은 기존 in-process 경로 유지
- `BOT_RUNNER_URL`이 없을 때 로컬 개발 fallback을 유지
- Kubernetes production에서는 `BOT_RUNNER_REQUIRED=true`로 보안을 강제할 수 있게 함

PR 전 검증:

- Bot Runner mock HTTP 서버 기반 adapter test 통과
- BattleRoyale create_game에서 유저 봇만 remote adapter를 쓰는지 확인
- MockStocks create_game에서 유저 봇만 remote adapter를 쓰는지 확인
- 기존 backend tests 중 영향 범위 통과

이 PR까지 머지되면, 아직 Kubernetes가 없어도 로컬 또는 별도 프로세스 Bot Runner와 통합 테스트가 가능하다.

---

## Phase 3. Kubernetes 매니페스트 작성

목표: GKE에 필요한 리소스를 파일로 명시한다.

### 3.1 디렉터리 구조

```text
k8s/
├─ base/
│  ├─ namespace.yaml
│  ├─ configmap.yaml
│  ├─ game-server-deployment.yaml
│  ├─ game-server-service.yaml
│  ├─ bot-runner-deployment.yaml
│  ├─ bot-runner-service.yaml
│  ├─ backend-config.yaml
│  ├─ network-policy.yaml
│  ├─ ingress.yaml
│  ├─ managed-certificate.yaml
│  ├─ hpa.yaml
│  └─ service-account.yaml
└─ README.md
```

주의:

- Secret 값이 들어간 YAML은 커밋하지 않는다.
- `k8s/secret.example.yaml`만 예시로 둘 수 있다.
- 실제 Secret 생성은 수동 명령 또는 Cloud Build substitution/Secret Manager 연동으로 처리한다.

### 3.2 Namespace

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: arena
```

### 3.3 ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: arena-config
  namespace: arena
data:
  USE_REDIS: "true"
  REDIS_HOST: "10.197.54.43"
  LOG_FORMAT: "json"
  CORS_ORIGINS: "https://ai-arena-b2b4b.web.app,https://ai-arena-b2b4b.firebaseapp.com"
  DB_TYPE: "postgresql"
  DB_HOST: "10.114.0.3"
  DB_NAME: "ai_arena"
  DB_USER: "arena_user"
  ENV: "production"
  BOT_RUNNER_URL: "http://bot-runner.arena.svc.cluster.local:8001"
  BOT_RUNNER_REQUIRED: "true"
```

주의:

- `BOSS_WEIGHTS_GCS_URI`는 이 파일에 포함하지 않는다. `kubectl apply -f k8s/base`가 이 ConfigMap을 적용하면 Cloud Build에서 주입된 실제 값이 placeholder로 덮어써진다. 이 값은 Phase 5.3의 Cloud Build step에서만 주입한다.
- `REDIS_HOST`(10.197.54.43)와 `DB_HOST`(10.114.0.3) 값은 **Phase 0.1 GCP 리소스 확인 후 실제 값과 일치하는지 검증한 뒤** 이 파일에 쓴다. IP가 다르면 서버 startup DB 연결이 실패하므로 추측으로 하드코딩하지 않는다.

### 3.4 Secret

Kubernetes Secret 이름:

```text
arena-secrets
```

키:

```text
DB_PASSWORD
FIREBASE_CREDENTIALS_JSON
GEMINI_API_KEY
JWT_SECRET
```

수동 생성 예시:

```bash
kubectl create secret generic arena-secrets \
  --namespace arena \
  --from-literal=DB_PASSWORD="$(gcloud secrets versions access latest --secret=db-password)" \
  --from-literal=FIREBASE_CREDENTIALS_JSON="$(gcloud secrets versions access latest --secret=firebase-service-account)" \
  --from-literal=GEMINI_API_KEY="$(gcloud secrets versions access latest --secret=GEMINI_API_KEY)" \
  --from-literal=JWT_SECRET="$(openssl rand -hex 32)"
```

주의:

- 위 명령을 문서에만 두고 출력값을 저장하지 않는다.
- Cloud Build 로그에 secret 값이 찍히지 않게 자동화 시 별도 주의가 필요하다.

### 3.5 game-server Deployment

핵심 설정:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: game-server
  namespace: arena
spec:
  replicas: 1
  selector:
    matchLabels:
      app: game-server
  template:
    metadata:
      labels:
        app: game-server
    spec:
      serviceAccountName: game-server
      containers:
        - name: game-server
          image: asia-northeast3-docker.pkg.dev/PROJECT_ID/ai-arena/server:IMAGE_TAG
          ports:
            - containerPort: 8080
          envFrom:
            - configMapRef:
                name: arena-config
            - secretRef:
                name: arena-secrets
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "1"
              memory: "1Gi"
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 6
          livenessProbe:
            httpGet:
              path: /livez
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 20
            timeoutSeconds: 3
            failureThreshold: 3
```

주의:

- **replicas: 1 필수**: BattleRoyale/MockStocks 모두 진행 중인 게임 세션을 프로세스 메모리에 보관한다. replica 2+로 시작하면 create 요청이 Pod A로, watch/get/delete 요청이 Pod B로 가서 게임이 중간에 끊긴다. Redis 기반 세션 외부화가 완료된 후에 replica를 늘린다.
- **readinessProbe → `/healthz`**: DB 장애 시 Pod을 서비스에서 제외한다. 재시작하지 않는다.
- **livenessProbe → `/livez`**: 프로세스 생존만 확인. DB/Redis 상태와 무관하게 동작한다. DB 장애에 재시작이 발생하면 메모리의 진행 중 게임이 날아간다.
- `/battleroyale/health`만 readiness로 쓰면 MockStocks DB 초기화 실패를 감지하지 못하므로 사용하지 않는다.

### 3.6 bot-runner Deployment

핵심 설정:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bot-runner
  namespace: arena
spec:
  replicas: 2
  selector:
    matchLabels:
      app: bot-runner
  template:
    metadata:
      labels:
        app: bot-runner
    spec:
      runtimeClassName: gvisor
      automountServiceAccountToken: false
      containers:
        - name: bot-runner
          image: asia-northeast3-docker.pkg.dev/PROJECT_ID/ai-arena/bot-runner:IMAGE_TAG
          ports:
            - containerPort: 8001
          env:
            - name: BOT_ACTION_TIMEOUT_SEC
              value: "0.1"
            - name: BOT_MAX_CODE_BYTES
              value: "51200"
          resources:
            requests:
              cpu: "500m"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "512Mi"
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            runAsUser: 10001
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: tmp
              mountPath: /tmp
          readinessProbe:
            httpGet:
              path: /health
              port: 8001
            initialDelaySeconds: 5
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8001
            initialDelaySeconds: 15
            periodSeconds: 10
      volumes:
        - name: tmp
          emptyDir:
            sizeLimit: 64Mi
            medium: Memory
```

주의:

- `readOnlyRootFilesystem: true` + `runAsNonRoot: true`로 권한을 최소화한다.
- `/tmp`는 `emptyDir` + `medium: Memory`로 tmpfs를 마운트해 Python/uvicorn이 임시 파일을 쓸 수 있게 한다.
- `sizeLimit: 64Mi`로 디스크 가득 채우기 공격을 방지한다.
- Bot Runner Dockerfile에서 non-root user를 생성하고 `WORKDIR /app` 소유권을 부여해야 한다 (`USER 10001` 또는 `USER bot-runner`).
- gVisor 환경에서 `multiprocessing.Process` spawn이 동작하는지 사전 확인이 필요하다. 일부 syscall이 제한되어 fork 기반 동작이 실패할 수 있다 (Phase 8 smoke test 참고).

### 3.7 Services

game-server:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: game-server
  namespace: arena
  annotations:
    cloud.google.com/backend-config: '{"default": "game-server-backend-config"}'
spec:
  type: ClusterIP
  selector:
    app: game-server
  ports:
    - port: 80
      targetPort: 8080
```

`backend-config` annotation은 3.9.1에서 정의한 BackendConfig를 가리킨다.

bot-runner:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: bot-runner
  namespace: arena
spec:
  type: ClusterIP
  selector:
    app: bot-runner
  ports:
    - port: 8001
      targetPort: 8001
```

### 3.8 NetworkPolicy

Bot Runner 기본 정책:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: bot-runner-isolation
  namespace: arena
spec:
  podSelector:
    matchLabels:
      app: bot-runner
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: game-server
      ports:
        - protocol: TCP
          port: 8001
  egress: []
```

의도:

- game-server Pod에서 오는 요청만 허용
- bot-runner 외부 네트워크 호출 차단

검증 필요:

- Autopilot/GKE Dataplane V2에서 적용 상태 확인
- DNS가 필요한 구조인지 확인. bot-runner는 외부 DNS가 필요 없어야 한다.

### 3.9 Ingress + SSL

선택지:

1. 기존 Cloud Run URL에서 새 도메인/GKE Ingress URL로 프론트 API base 변경
2. 커스텀 도메인을 GKE Ingress로 연결

캡스톤 안정성을 생각하면 처음에는 GKE Ingress가 발급하는 IP/도메인으로 스테이징 확인 후, 프론트 환경변수를 바꾼다.

필요 리소스:

```text
k8s/base/managed-certificate.yaml
k8s/base/ingress.yaml
```

주의:

- WebSocket이 `/battleroyale/ws/...`, `/stocks/ws/...`에서 정상 동작하는지 반드시 확인한다.
- GKE Ingress timeout이 게임 관전 WS에 충분한지 확인한다.
- Ingress IP는 반드시 static IP로 예약한다. Ingress 재생성 시 IP가 바뀌면 프론트엔드 환경변수까지 함께 수정해야 한다.

```bash
gcloud compute addresses create loa-arena-ingress-ip --global
```

### 3.9.1 BackendConfig (WebSocket timeout)

GKE Ingress의 기본 백엔드 timeout은 30초다. BattleRoyale max_ticks 200 × tick_interval 0.05~0.2 = 10~40초인 게임 자체는 짧지만, 관전 WebSocket은 일시정지/속도조절/대기 등으로 더 길게 유지된다. BackendConfig를 만들지 않으면 관전 중간에 연결이 끊긴다.

```yaml
apiVersion: cloud.google.com/v1
kind: BackendConfig
metadata:
  name: game-server-backend-config
  namespace: arena
spec:
  timeoutSec: 3600
  connectionDraining:
    drainingTimeoutSec: 60
  healthCheck:
    type: HTTP
    requestPath: /healthz
    port: 8080
```

Service에 annotation 연결:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: game-server
  namespace: arena
  annotations:
    cloud.google.com/backend-config: '{"default": "game-server-backend-config"}'
spec:
  type: ClusterIP
  selector:
    app: game-server
  ports:
    - port: 80
      targetPort: 8080
```

주의:

- `timeoutSec: 3600`은 1시간으로 넉넉히 잡았다. 실제 관전 최대 시간이 더 짧다면 줄여도 된다.
- `healthCheck.requestPath`는 Phase 2에서 추가한 통합 `/healthz`를 가리킨다.
- Service annotation은 `k8s/base/game-server-service.yaml`에 반영한다.

### 3.10 HPA

초기:

```text
game-server replicas: 2 고정
bot-runner replicas: 2 고정
```

검증 후:

```text
bot-runner HPA min 2, max 10, CPU 70%
```

Bot Runner는 stateless `/run` 방식으로 구현되므로 HPA는 처음부터 안전하게 적용할 수 있다.

- registry가 없으므로 "어느 replica에 요청이 가도" 동작함.
- Pod 재시작 시 in-process LRU cache만 초기화되고, 다음 요청에서 code 재컴파일 후 자동 복구.

초기 배포 시에도 `minReplicas: 2` 그대로 사용한다. session affinity, Redis registry, Pod endpoint 직접 지정 등의 우회책은 불필요하다.

### Phase 3 PR 분리 시점

이 Phase가 끝나면 **PR 3: Kubernetes 매니페스트 추가**로 끊는다.

포함할 파일:

```text
k8s/base/namespace.yaml
k8s/base/configmap.yaml
k8s/base/game-server-deployment.yaml
k8s/base/game-server-service.yaml
k8s/base/bot-runner-deployment.yaml
k8s/base/bot-runner-service.yaml
k8s/base/backend-config.yaml
k8s/base/network-policy.yaml
k8s/base/ingress.yaml
k8s/base/managed-certificate.yaml
k8s/base/hpa.yaml
k8s/base/service-account.yaml
k8s/secret.example.yaml
k8s/README.md
```

포함하지 않을 파일:

```text
cloudbuild.yaml
실제 Secret 값이 들어간 YAML
frontend API URL 변경
```

PR 목적:

- GKE 리소스 정의를 코드 리뷰 가능하게 만듦
- Secret 미포함 원칙, Bot Runner gVisor, NetworkPolicy, resource limit을 리뷰
- 실제 배포 자동화 전 수동 적용 가능한 manifest를 준비

PR 전 검증:

- `kubectl apply --dry-run=client -f k8s/base` 통과
- 가능하면 `kubeconform` 또는 `kubectl diff`로 schema 확인
- `bot-runner` Deployment에 `runtimeClassName: gvisor` 명시 확인
- `bot-runner`에 `envFrom: secretRef`가 없는지 확인
- `NetworkPolicy` egress deny 확인

이 PR은 인프라 정의만 추가하고 운영 트래픽을 바꾸지 않는다.

---

## Phase 4. GKE 클러스터 생성

목표: 운영과 같은 region/VPC에 Autopilot 클러스터를 만든다.

### 4.1 클러스터 생성 전 확인

확인:

- Cloud SQL private IP와 같은 VPC에 GKE를 만들 수 있는지
- Memorystore Redis와 같은 VPC에 접근 가능한지
- 필요한 API 활성화 여부
  - Kubernetes Engine API
  - Artifact Registry API
  - Secret Manager API
  - Cloud SQL Admin API

### 4.2 클러스터 생성 예시

정확한 VPC/subnet 이름 확인 후 실행한다.

```bash
gcloud container clusters create-auto loa-arena \
  --region asia-northeast3 \
  --release-channel regular \
  --network DEFAULT_OR_EXISTING_VPC \
  --subnetwork DEFAULT_OR_EXISTING_SUBNET
```

주의:

- 실제 VPC/subnet 이름을 확인하기 전까지 명령을 실행하지 않는다.
- Cloud SQL/Redis private IP 접근이 안 되면 이 단계에서 네트워크 설계를 다시 잡아야 한다.

### 4.3 kubectl context 확인

```bash
gcloud container clusters get-credentials loa-arena --region asia-northeast3
kubectl get nodes
kubectl get ns
```

### 4.4 gVisor RuntimeClass 사용 가능 여부 확인

GKE Autopilot은 `runtimeClassName: gvisor`를 표준 지원하지만, 클러스터에 실제로 RuntimeClass가 등록되어 있는지 확인이 필요하다.

```bash
kubectl get runtimeclass
```

기대 출력에 `gvisor`가 포함되어야 한다.

bot-runner Pod 배포 후 실제 gVisor 런타임으로 떠 있는지 확인:

```bash
kubectl -n arena get pods -l app=bot-runner \
  -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.runtimeClassName}{"\n"}{end}'
```

기대:

```text
bot-runner-xxxxx: gvisor
```

### 4.5 Workload Identity 사전 확인

GKE Autopilot은 기본적으로 Workload Identity가 활성화되어 있다. 다음을 확인한다.

```bash
gcloud container clusters describe loa-arena \
  --region asia-northeast3 \
  --format='value(workloadIdentityConfig.workloadPool)'
```

기대 출력: `PROJECT_ID.svc.id.goog`

이 값이 비어 있으면 Workload Identity가 비활성화된 상태이므로 GCS 접근을 위한 Phase 6 설정이 실패한다.

### Phase 4 PR 분리 시점

이 Phase는 **일반 코드 PR로 만들지 않는다.**

이유:

- 클러스터 생성은 GCP 프로젝트 상태를 바꾸는 운영 작업이다.
- 산출물은 Git diff보다 실행 로그, 설정값, 검증 결과가 중요하다.
- VPC/subnet/Cloud SQL/Redis 확인값은 민감하거나 환경 의존적일 수 있다.

대신 남길 기록:

- `WORK_LOG.md`: 생성한 클러스터 이름, region, VPC/subnet, 검증 결과
- Notion/Obsidian: 명령과 결정 이유
- 필요하면 `k8s/README.md`에 민감 정보 없는 절차만 반영하고 별도 PR로 업데이트

다음 Phase로 넘어가기 전에 필요한 조건:

- `kubectl get nodes` 정상
- `arena` namespace 적용 가능
- Artifact Registry image pull 권한 확인
- GKE에서 Cloud SQL/Redis private IP에 접근 가능한 네트워크 조건 확인

---

## Phase 5. 이미지 빌드와 배포 파이프라인

목표: server, bot-runner, trainer 이미지와 Kubernetes apply 흐름을 정한다.

### 5.1 이미지

필요 이미지:

```text
server
bot-runner
trainer
```

`server`는 기존 `backend/Dockerfile` 유지.

`bot-runner`는 신규:

```text
backend/BotRunner/Dockerfile
```

예상 Dockerfile:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py schemas.py cache.py executor.py policy.py ./

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
```

### 5.2 Cloud Build 변경 방향

현재:

```text
docker build server
docker build trainer
docker push server
docker push trainer
gcloud run deploy ai-arena-server
gcloud run jobs deploy boss-trainer
```

1차 GKE 안정화 전:

```text
docker build server
docker build bot-runner
docker build trainer
docker push server
docker push bot-runner
docker push trainer
gcloud run deploy ai-arena-server        # 기존 운영 경로 유지
gcloud run jobs deploy boss-trainer      # 기존 trainer 유지
kubectl apply -f k8s/base                # GKE 병행 배포
kubectl set image deployment/game-server ...
kubectl set image deployment/bot-runner ...
kubectl rollout status deployment/game-server
kubectl rollout status deployment/bot-runner
```

정식 cutover 후:

```text
docker build server
docker build bot-runner
docker build trainer
docker push server
docker push bot-runner
docker push trainer
kubectl apply -f k8s/base
kubectl set image deployment/game-server ...
kubectl set image deployment/bot-runner ...
kubectl rollout status deployment/game-server
kubectl rollout status deployment/bot-runner
```

정식 cutover 전까지는 **Cloud Run deploy를 제거하지 않는다.** Cloud Build에 GKE 경로를 추가하더라도 기본 운영 트래픽은 Cloud Run을 계속 바라보게 둔다.

### 5.3 BOSS_WEIGHTS_GCS_URI 주입 방법

Cloud Run은 substitution을 `--set-env-vars`로 직접 주입했지만, GKE는 ConfigMap을 거친다. ConfigMap을 manifest에 하드코딩하면 버킷명이 git에 노출된다.

권장 방식:

1. ConfigMap의 `BOSS_WEIGHTS_GCS_URI`는 placeholder로 두지 않는다.
2. Cloud Build step에서 `kubectl create configmap` 또는 `kubectl patch configmap`으로 substitution 값을 주입한다.

Cloud Build step 예시:

```yaml
- name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
  entrypoint: 'bash'
  args:
    - '-c'
    - |
      gcloud container clusters get-credentials loa-arena \
        --region ${_REGION} --project $PROJECT_ID
      kubectl -n arena create configmap arena-config \
        --from-literal=USE_REDIS=true \
        --from-literal=REDIS_HOST=${_REDIS_HOST} \
        --from-literal=DB_HOST=${_DB_HOST} \
        --from-literal=DB_NAME=${_DB_NAME} \
        --from-literal=DB_USER=${_DB_USER} \
        --from-literal=DB_TYPE=postgresql \
        --from-literal=ENV=production \
        --from-literal=CORS_ORIGINS=${_CORS_ORIGINS} \
        --from-literal=BOSS_WEIGHTS_GCS_URI=${_BOSS_WEIGHTS_GCS_URI} \
        --from-literal=BOT_RUNNER_URL=http://bot-runner.arena.svc.cluster.local:8001 \
        --from-literal=BOT_RUNNER_REQUIRED=true \
        --dry-run=client -o yaml | kubectl apply -f -
```

`kubectl apply -f k8s/base`는 ConfigMap을 포함하지 않거나, 위 step 이후에 실행한다. 어느 쪽이든 manifest 파일에는 실제 버킷명을 쓰지 않는다.

### 5.4 Cloud Build Service Account 권한

Cloud Build가 GKE에 배포하려면 다음 role이 필요하다.

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
CLOUD_BUILD_SA=${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${CLOUD_BUILD_SA}" \
  --role="roles/container.developer"
```

`roles/container.developer`는 GKE Deployment/Service/ConfigMap을 적용하는 데 충분하다. 클러스터를 생성/삭제할 필요는 없으므로 `roles/container.admin`은 부여하지 않는다.

Artifact Registry push 권한은 기본으로 부여되어 있지만 누락된 경우:

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${CLOUD_BUILD_SA}" \
  --role="roles/artifactregistry.writer"
```

### 5.5 cloudbuild.yaml 수정 리스크

`cloudbuild.yaml`은 protected shared file이다. 수정 전 팀 승인 필요.

권장 작업 순서:

1. `k8s/`와 Bot Runner 코드 먼저 PR
2. 수동 `kubectl apply`로 staging 검증
3. 팀 승인 후 `cloudbuild.yaml`에 GKE 병행 배포 경로 추가
4. GKE 안정화 기간 동안 Cloud Run과 GKE를 동시에 배포
5. 안정화 기준 충족 후 별도 cutover PR에서 프론트/API 트래픽을 GKE로 전환

### 5.6 Skaffold 로컬 개발 환경 (선택)

Skaffold는 로컬 Kubernetes(minikube/Docker Desktop)와 GKE를 프로파일로 분리하여,
동일한 매니페스트를 두 환경에서 사용할 수 있게 해주는 Google 공식 오픈소스 도구다.
Skaffold 자체는 무료이며, 비용은 배포 대상 인프라(GKE 등)에서만 발생한다.

#### 배경 및 필요성

Cloud Run은 `gcloud run deploy` 한 명령으로 배포가 끝났지만, GKE는 이미지 빌드 →
push → `kubectl apply` → `kubectl set image` → `kubectl rollout status` 순서를
매번 수동으로 실행해야 한다. Skaffold는 이 반복을 자동화하고, 로컬↔GKE 전환을
프로파일 하나로 처리한다.

팀원 전원이 로컬 k8s를 쓸 필요는 없다. 기능 개발은 기존과 동일하게
`python run_server.py`로 충분하다. Skaffold는 인프라 담당자 또는 Kubernetes 매니페스트를
자주 수정하는 팀원에게 유용하다.

#### 설치

```bash
# Mac
brew install skaffold

# 버전 확인
skaffold version
```

#### skaffold.yaml 구조

로컬 overlay는 패치 파일을 포함하므로 raw kubectl이 아닌 **Kustomize** 방식으로 배포한다.
Kustomize는 kubectl에 내장되어 있고(`kubectl apply -k`), 패치를 base에 덮어쓰는 방식으로
gVisor 제거 같은 환경별 차이를 깔끔하게 처리한다.

```yaml
apiVersion: skaffold/v4beta11
kind: Config
metadata:
  name: loa-arena

build:
  artifacts:
    - image: asia-northeast3-docker.pkg.dev/knu-2026-sungjin0418/ai-arena/server
      docker:
        dockerfile: Dockerfile
        context: backend
    - image: asia-northeast3-docker.pkg.dev/knu-2026-sungjin0418/ai-arena/bot-runner
      docker:
        dockerfile: BotRunner/Dockerfile
        context: backend

profiles:
  - name: local
    activation:
      - kubeContext: minikube
      - kubeContext: docker-desktop
    build:
      local:
        push: false           # 레지스트리 push 없이 로컬 Docker에 직접 로드
    deploy:
      kustomize:
        paths:
          - k8s/overlays/local  # kustomization.yaml이 base를 참조하고 패치를 적용

  - name: production
    activation:
      - kubeContext: gke_knu-2026-sungjin0418_asia-northeast3_arena-cluster
    deploy:
      kustomize:
        paths:
          - k8s/base            # base kustomization.yaml을 그대로 사용
```

#### k8s/ 디렉터리 전체 구조 (Skaffold 포함)

```text
k8s/
├── base/
│   ├── kustomization.yaml            # base 리소스 목록 (Skaffold용)
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── game-server-deployment.yaml
│   ├── game-server-service.yaml
│   ├── bot-runner-deployment.yaml
│   ├── bot-runner-service.yaml
│   ├── backend-config.yaml
│   ├── network-policy.yaml
│   ├── ingress.yaml
│   ├── managed-certificate.yaml
│   ├── hpa.yaml
│   └── service-account.yaml
├── overlays/
│   └── local/
│       ├── kustomization.yaml        # base 참조 + 패치 + configMapGenerator
│       └── bot-runner-patch-local.yaml  # runtimeClassName 제거 패치
├── secret.example.yaml
└── README.md
```

`k8s/base/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: arena
resources:
  - namespace.yaml
  - configmap.yaml
  - service-account.yaml
  - game-server-deployment.yaml
  - game-server-service.yaml
  - bot-runner-deployment.yaml
  - bot-runner-service.yaml
  - backend-config.yaml
  - network-policy.yaml
  - ingress.yaml
  - managed-certificate.yaml
  - hpa.yaml
```

`k8s/overlays/local/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: arena
resources:
  - ../../base
patches:
  - path: bot-runner-patch-local.yaml
    target:
      kind: Deployment
      name: bot-runner
configMapGenerator:
  - name: arena-config
    namespace: arena
    behavior: merge
    literals:
      - USE_REDIS=false
      - DB_TYPE=sqlite
      - ENV=development
      - CORS_ORIGINS=http://localhost:5173
```

`bot-runner-patch-local.yaml` (Kustomize strategic merge patch):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bot-runner
  namespace: arena
spec:
  template:
    spec:
      runtimeClassName: null    # gVisor는 로컬 k8s에서 지원 안 됨
```

`runtimeClassName: null`은 Kustomize strategic merge patch에서 base의 해당 필드를 제거한다.
raw `kubectl apply`로는 이 동작이 보장되지 않으므로 반드시 Kustomize를 통해야 한다.

#### 워크플로우 명령어

```bash
# 로컬 클러스터 시작 (minikube)
minikube start

# 로컬 개발 모드: 파일 변경 감지 → 자동 재빌드/재배포
skaffold dev --profile=local

# 로컬 한 번 배포
skaffold run --profile=local

# GKE에 배포 (컨텍스트가 GKE면 자동 activation, 또는 명시)
skaffold run --profile=production

# 특정 컨텍스트 강제 지정
skaffold run --profile=local --kube-context=minikube
```

`skaffold dev`는 Ctrl+C로 종료 시 배포된 리소스를 자동으로 정리한다.

#### Phase 5 PR에서의 위치

`skaffold.yaml`과 `k8s/overlays/local/`은 PR 4에 포함할 수 있다.
Cloud Build 자동화(PR 5)와는 독립적이다.

```text
PR 4 포함 가능:
  skaffold.yaml
  k8s/overlays/local/configmap-local.yaml
  k8s/overlays/local/bot-runner-patch-local.yaml
```

#### 주의사항

- 로컬 프로파일은 Secret이 없으므로 `kubectl create secret generic arena-secrets --namespace arena --from-literal=DB_PASSWORD=local` 등 최소한의 더미 Secret을 수동 생성해야 한다.
- `skaffold dev`는 이미지 재빌드를 포함하므로 Python 파일 수정 시 수 초 내에 파드가 재시작된다.
- `k8s/overlays/local/`에는 Secret 값이 들어가지 않도록 주의한다.

---

### Phase 5 PR 분리 시점

이 Phase는 두 번으로 나눈다.

**PR 4: 수동 배포 검증 기록/보완**

포함 가능:

```text
k8s/README.md
k8s/base/* 보완
backend/BotRunner/Dockerfile 보완
```

포함하지 않음:

```text
cloudbuild.yaml
frontend API URL 변경
```

목적:

- 수동 `docker build/push`, `kubectl apply`, `kubectl rollout status`를 통해 GKE staging 배포가 되는지 확인
- manifest의 실제 Autopilot 호환 문제를 반영
- Cloud Build 자동화 전에 배포 단위를 안정화

**PR 5: cloudbuild.yaml에 GKE 병행 배포 경로 추가**

포함:

```text
cloudbuild.yaml
필요 시 scripts/deploy-gke.sh
```

조건:

- 팀 승인 필수
- GKE 수동 배포와 smoke test 완료
- 기존 Cloud Run rollback 경로 확인
- 기존 Cloud Run deploy step을 제거하지 않음
- 기본 운영 트래픽은 아직 Cloud Run 유지

PR 전 검증:

- Cloud Build service account에 필요한 GKE 권한 확인
- `kubectl rollout status` 실패 시 build 실패하도록 구성
- Secret 값이 build log에 출력되지 않는지 확인
- GKE deploy 실패 시 Cloud Run 기존 서비스가 계속 운영되는지 확인

PR 5 merge 후 상태:

```text
Cloud Run: 계속 운영
GKE: 병행 배포 및 검증 대상
Frontend/API traffic: Cloud Run 유지
Rollback: 프론트 변경 없이 Cloud Run을 계속 사용
```

정식 전환은 PR 5가 아니라 별도 cutover Phase에서 수행한다.

---

## Phase 6. Secret과 권한

목표: game-server만 필요한 권한을 갖고, bot-runner는 권한을 갖지 않게 한다.

### 6.1 Kubernetes ServiceAccount

```text
game-server
bot-runner
```

`bot-runner`:

```yaml
automountServiceAccountToken: false
```

`game-server`:

- GCS boss weights 읽기 권한 필요
- Secret은 Kubernetes Secret으로 주입하면 런타임 Secret Manager 권한은 필수 아님
- 나중에 Secret Manager CSI를 쓰면 Workload Identity 필요

### 6.2 GCS 권한 (Workload Identity 연결)

현재 Cloud Run service account에 `roles/storage.objectViewer`가 부여되어 있다. GKE에서는 game-server Kubernetes ServiceAccount와 GCP ServiceAccount를 Workload Identity로 연결한다.

설정 단계:

1. GCP service account 생성 (또는 기존 재사용)

```bash
gcloud iam service-accounts create game-server-sa \
  --display-name "LOA game-server runtime"
```

2. GCS 객체 읽기 권한 부여

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:game-server-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

3. Kubernetes SA와 GCP SA 바인딩

```bash
gcloud iam service-accounts add-iam-policy-binding \
  game-server-sa@${PROJECT_ID}.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[arena/game-server]"
```

4. Kubernetes SA에 annotation 추가

```bash
kubectl annotate serviceaccount game-server \
  --namespace arena \
  iam.gke.io/gcp-service-account=game-server-sa@${PROJECT_ID}.iam.gserviceaccount.com
```

또는 manifest에 직접 포함:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: game-server
  namespace: arena
  annotations:
    iam.gke.io/gcp-service-account: game-server-sa@PROJECT_ID.iam.gserviceaccount.com
```

5. Pod spec에 `serviceAccountName: game-server` 명시

이미 3.5 game-server Deployment에 `serviceAccountName: game-server`가 명시되어 있다. 빠지지 않게 확인한다.

확인할 파일 (코드가 ADC를 쓰는지 검증):

```text
backend/BattleRoyale/gcs_weights.py
backend/BattleRoyale/src/arena/server/app.py
```

대안 (GCS 사용 없이 전환 난이도를 낮추는 경우):

- boss 가중치를 컨테이너 이미지에 포함하거나 ConfigMap으로 마운트
- 운영 안정화 후 GCS로 다시 전환

### 6.3 Firebase credentials

현재는 `FIREBASE_CREDENTIALS_JSON` Secret을 환경변수로 주입한다. GKE에서도 game-server Secret에만 주입한다.

Bot Runner에는 절대 주입하지 않는다.

### Phase 6 PR 분리 시점

이 Phase는 **Secret 값 자체는 PR에 포함하지 않고**, 필요한 경우 **PR 4 또는 PR 5에 문서/manifest 보완으로 포함**한다.

PR에 포함 가능한 것:

```text
k8s/base/service-account.yaml
k8s/secret.example.yaml
k8s/README.md
```

`k8s/base/rbac.yaml`은 **이 프로젝트에서 불필요**하다.

- `bot-runner` ServiceAccount는 K8s API 접근이 없으므로 RBAC가 필요 없다.
- `game-server` ServiceAccount는 GCS 읽기 권한을 Workload Identity(GCP IAM)로 처리한다. K8s RBAC Role/RoleBinding이 아니다.
- External Secrets Operator 등 추가 구성요소 도입 시에만 RBAC이 필요해진다.

PR에 포함 금지:

```text
실제 DB_PASSWORD
실제 FIREBASE_CREDENTIALS_JSON
실제 GEMINI_API_KEY
실제 JWT_SECRET
서비스 계정 키 JSON 파일
```

작업 기록 위치:

- 실제 Secret 생성 명령 결과는 `WORK_LOG.md`에도 값을 쓰지 않는다.
- 어떤 Secret name/key를 만들었는지만 기록한다.
- 권한 부여는 IAM 변경이므로 명령과 대상 service account만 기록한다.

다음 Phase로 넘어가기 전에 필요한 조건:

- game-server Pod에서 필요한 env가 존재함
- bot-runner Pod에는 Secret env가 없음
- game-server만 GCS boss weights를 읽을 수 있음
- bot-runner는 service account token 자동 mount가 꺼져 있음

---

## Phase 7. 코드 변경 상세

### 7.1 BattleRoyale create_game 변경

현재:

```python
for b in bots_data:
    bot = InProcessBot(b["bot_id"], b["code"])
```

변경:

```python
import hashlib

for b in bots_data:
    if settings.BOT_RUNNER_URL:
        code_hash = "sha256:" + hashlib.sha256(b["code"].encode()).hexdigest()
        bot = RemoteBattleRoyaleBotAdapter(
            bot_id=b["bot_id"],
            code=b["code"],
            code_hash=code_hash,  # 매 tick /run 호출 시 함께 전송
            runner_url=settings.BOT_RUNNER_URL,
            timeout=settings.BOT_RUNNER_TIMEOUT_SEC,
        )
    elif settings.ENV == "production" and settings.BOT_RUNNER_REQUIRED:
        raise HTTPException(503, "Bot Runner를 사용할 수 없습니다.")
    else:
        bot = InProcessBot(b["bot_id"], b["code"])
```

### 7.2 MockStocks create_game 변경

현재:

```python
bot = InProcessBot(b.bot_id, b.code)
```

변경:

```python
if settings.BOT_RUNNER_URL:
    bot = RemoteStockBotAdapter(...)
elif settings.BOT_RUNNER_REQUIRED:
    raise HTTPException(503, "Bot Runner를 사용할 수 없습니다.")
else:
    bot = InProcessBot(...)
```

### 7.3 기본 액션

BattleRoyale:

```text
STAY
```

MockStocks:

```json
{"action": "HOLD"}
```

### 7.4 timeout 기준

현재 `SandboxConfig.action_timeout_sec = 0.1`이다. HTTP 호출, JSON encode/decode, Bot Runner 내부 실행까지 포함하면 100ms는 빡빡할 수 있다.

권장:

- 초기 Kubernetes 검증: 500ms (HTTP 왕복 + multiprocessing spawn overhead + 실행 시간 합산 시 300ms는 정상 봇도 fallback될 수 있음)
- 실측 p95 latency 확인 후 단계적으로 낮추기 (300ms → 200ms → 100ms)
- 설정값으로 분리

```text
BOT_RUNNER_TIMEOUT_SEC=0.5
BOT_ACTION_TIMEOUT_SEC=0.1
```

게임 서버 HTTP timeout과 Bot Runner 내부 action timeout을 분리한다.

### Phase 7 PR 분리 시점

이 Phase의 코드 변경은 **새 PR로 따로 만들지 않고 Phase 2의 PR 2에 포함**한다.

이유:

- Phase 7은 독립 작업이라기보다 Phase 2 구현의 상세 설계다.
- `RemoteBotAdapter` 파일만 추가하고 `create_game()`을 연결하지 않으면 운영 경로가 바뀌지 않아 검증 가치가 낮다.
- 반대로 `create_game()` 연결만 있고 adapter test가 없으면 회귀 위험이 크다.

PR 2 안에서 반드시 같이 리뷰할 묶음:

```text
settings.py env 추가
remote_adapter.py 추가
app.py create_game 연결
fallback 정책
timeout 정책
tests
```

PR 2 merge 조건:

- `BOT_RUNNER_URL` 미설정 시 기존 로컬 개발 흐름 유지
- `BOT_RUNNER_REQUIRED=true`에서 Bot Runner 미설정이면 503
- 유저 봇만 remote 경로 사용
- AI filler/boss는 기존 경로 유지
- BattleRoyale와 MockStocks의 기본 액션이 각각 `STAY`, `{"action": "HOLD"}`로 유지

---

## Phase 8. 테스트 계획

### 8.1 Bot Runner 단위 테스트

필수:

- 정상 BattleRoyale action 반환
- 정상 MockStocks action 반환
- syntax error -> fallback
- action 함수 없음 -> fallback
- timeout -> fallback
- forbidden import -> fallback
- invalid action -> fallback
- code size 초과 -> 400 또는 fallback 정책 확인

### 8.2 게임 서버 adapter 테스트

BattleRoyale:

- Bot Runner 정상 응답 -> 해당 action 반환
- Bot Runner timeout -> `STAY`
- Bot Runner 500 -> `STAY`
- invalid JSON -> `STAY`

MockStocks:

- Bot Runner 정상 응답 -> dict action 반환
- Bot Runner timeout -> `{"action": "HOLD"}`
- invalid schema -> `{"action": "HOLD"}`

### 8.3 API 통합 테스트

- `BOT_RUNNER_URL` 설정 시 유저 봇이 Remote adapter로 생성되는지
- AI filler/boss bot은 InProcess 유지되는지
- Bot Runner 미설정 + development는 InProcess fallback
- Bot Runner 미설정 + production + required는 503

### 8.4 Kubernetes smoke test

배포 후:

```bash
kubectl -n arena get pods
kubectl -n arena get svc
kubectl -n arena get ingress
kubectl -n arena logs deploy/game-server
kubectl -n arena logs deploy/bot-runner
```

Health:

```bash
curl https://GKE_INGRESS_HOST/healthz
curl https://GKE_INGRESS_HOST/battleroyale/health
curl https://GKE_INGRESS_HOST/stocks/health
```

`/healthz`는 통합 readiness/liveness 용이며 BattleRoyale + MockStocks DB 초기화 상태를 모두 반영해야 한다.

NetworkPolicy:

- game-server -> bot-runner 호출 성공
- bot-runner -> 외부 인터넷 호출 실패
- bot-runner -> game-server 직접 호출 실패가 이상적이나, NetworkPolicy 방향상 egress deny로 막혀야 함

gVisor 확인:

```bash
kubectl -n arena get pods -l app=bot-runner -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.runtimeClassName}{"\n"}{end}'
```

기대:

```text
bot-runner-xxxxx: gvisor
```

gVisor + Python 호환성 smoke (반드시 PR 4 단계에서 1회 검증):

- `multiprocessing.Process(target=...).start()` 동작 확인. gVisor는 일부 syscall을 제한해 fork 기반 spawn이 실패할 수 있다.
- `resource.setrlimit(RLIMIT_CPU, ...)`, `resource.setrlimit(RLIMIT_AS, ...)` 동작 확인. executor의 resource limit이 gVisor에서 정상 적용되어야 한다.
- `signal.alarm(...)` 기반 timeout이 동작하는지 확인.
- `tmpfs` `/tmp` 쓰기 동작 확인. readOnlyRootFilesystem 환경에서 Python `tempfile`이 정상인지 검증.

확인 명령 예시:

```bash
kubectl -n arena exec deploy/bot-runner -- python -c "
import multiprocessing, resource, tempfile, signal
def f(): pass
p = multiprocessing.Process(target=f); p.start(); p.join()
print('mp ok')
resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
print('rlimit ok')
signal.alarm(5); signal.alarm(0)
print('signal ok')
with tempfile.NamedTemporaryFile() as t:
    t.write(b'hello')
print('tmpfile ok')
print('all checks passed')
"
```

여기서 실패하면 **thread executor로 대체하지 않는다** — thread는 같은 프로세스에서 실행되므로 untrusted code 격리 목적에 위배된다. 대안: gVisor를 포기하고 일반 Pod + NetworkPolicy + resource limit + readOnlyRootFilesystem + AST 검사 조합으로 격리 수단을 재설계한다.

### 8.5 E2E 확인

- 로그인
- BattleRoyale 게임 생성
- Boss 게임 생성
- MockStocks 게임 생성
- 관전 WebSocket 정상 연결
- 종료 팝업 정상
- 결과 페이지 정상
- GamesPage active/history 정상
- 다른 계정 목록 격리 정상
- 유저 봇 코드에서 `os.environ` 접근 시 서버 Secret이 보이지 않는지 확인

### Phase 8 PR 분리 시점

이 Phase는 **하나의 PR로 따로 만들지 않고, 각 PR의 merge gate로 분산 적용**한다.

PR별 필수 테스트:

```text
PR 1 Bot Runner:
- Bot Runner unit tests
- Docker build
- local health/action smoke

PR 2 RemoteBotAdapter:
- BattleRoyale adapter tests
- MockStocks adapter tests
- create_game remote/fallback tests
- 영향 범위 backend pytest

PR 3 Kubernetes manifests:
- kubectl apply --dry-run=client
- manifest lint/schema check
- Secret 값 미포함 확인

PR 4 GKE 수동 배포 보완:
- kubectl rollout status
- health smoke
- NetworkPolicy smoke
- gVisor runtimeClass 확인

PR 5 Cloud Build 병행 배포:
- Cloud Build dry-run에 준하는 수동 command 검증
- 실제 trigger 1회 검증
- 실패 시 rollout 중단 확인
- Cloud Run deploy step 유지 확인

PR 6 GKE 안정화:
- 일정 기간 GKE shadow/staging 운영
- 운영 Cloud Run과 health/E2E 결과 비교
- GKE 장애/비용/로그 확인

PR 7 Frontend/API cutover:
- production-like API URL로 E2E
- WebSocket 관전 확인
- rollback URL 확인
```

별도 테스트 전용 PR이 필요한 경우:

- 기존 테스트 구조가 너무 깨져서 구현 PR 안에서 정리하기 어려울 때
- GKE smoke/E2E 자동화 스크립트를 별도 `scripts/`로 만들 때
- CI가 없으므로 팀이 수동 검증 스크립트를 공유하기로 합의했을 때

---

## 9. 롤백 계획

### 9.1 GKE 배포 실패 시

Cloud Run 기존 서비스는 바로 삭제하지 않는다.

병행 배포 기간:

```text
Cloud Run ai-arena-server 유지
GKE game-server 신규 배포
Firebase frontend API URL은 Cloud Run 유지
```

문제 발생 시:

- PR 5 이전/직후라면 프론트가 아직 Cloud Run을 보므로 사용자 영향 없음
- GKE deploy만 중단하고 Cloud Run 운영 유지
- GKE 리소스는 유지한 채 로그 분석

### 9.2 정식 cutover 후 문제 발생 시

cutover 이후에는 프론트 API URL 또는 DNS가 GKE를 본다. 이때 문제가 생기면 아래 순서로 되돌린다.

1. 프론트 API base URL을 기존 Cloud Run URL로 되돌림
2. DNS를 바꿨다면 DNS를 Cloud Run 쪽으로 되돌림
3. `BOT_RUNNER_REQUIRED` 등 GKE 전용 설정은 그대로 두고, 트래픽만 Cloud Run으로 되돌림
4. GKE 리소스는 삭제하지 않고 원인 분석

Cloud Run 서비스를 삭제하는 것은 cutover 직후가 아니라 안정화 관찰 기간이 끝난 뒤 별도 결정으로 처리한다.

### 9.3 Bot Runner 실패 시

Kubernetes production에서는 `BOT_RUNNER_REQUIRED=true`가 맞지만, 초기 staging에서는 false로 두고 fallback을 확인할 수 있다.

운영 전환 후에는 fallback을 켜면 보안 목적이 깨지므로 권장하지 않는다.

### 9.4 Cloud Build 실패 시

수동 배포 명령을 문서화한다.

```bash
docker build -t asia-northeast3-docker.pkg.dev/PROJECT_ID/ai-arena/server:manual backend
docker push asia-northeast3-docker.pkg.dev/PROJECT_ID/ai-arena/server:manual
kubectl -n arena set image deployment/game-server game-server=asia-northeast3-docker.pkg.dev/PROJECT_ID/ai-arena/server:manual
kubectl -n arena rollout status deployment/game-server
```

---

## 10. 예상 리스크와 대응

| 리스크 | 영향 | 대응 |
| --- | --- | --- |
| Bot Runner replica 간 registry 불일치 | action 요청 실패 | stateless `/run` + code_hash cache 방식으로 구현 — registry 자체 없음 |
| game-server 멀티 replica 세션 불일치 | create/watch/get가 다른 Pod로 가면 게임 404 | game-server는 replicas: 1로 시작, Redis 세션 외부화 후 확장 |
| liveness probe가 DB 장애에 재시작 유발 | 진행 중 게임 메모리 유실 | readiness → `/healthz` (DB 포함), liveness → `/livez` (프로세스만) 분리 |
| 100ms timeout 과도 | 정상 봇도 STAY/HOLD 처리 | HTTP timeout과 action timeout 분리, 초기 500ms — 실측 후 단계적으로 낮춤 |
| GKE -> Cloud SQL private IP 연결 실패 | 서버 startup DB 실패 | VPC/subnet 확인, 필요 시 Cloud SQL Auth Proxy sidecar |
| GKE -> Memorystore 연결 실패 | Redis Pub/Sub 비활성/오류 | 같은 VPC 확인, 방화벽/authorized network 확인 |
| Ingress WebSocket timeout | 관전 끊김 | GKE Ingress WebSocket 검증, 필요 시 BackendConfig timeout 조정 |
| Secret 값 YAML 커밋 | 심각한 보안 사고 | Secret manifest 금지, `.gitignore`/review 체크 |
| bot-runner에 Secret 주입 | 격리 목적 훼손 | 별도 Deployment/envFrom 금지, 테스트로 env key absence 확인 |
| Cloud Build 권한 부족 | 배포 실패 | Cloud Build SA에 GKE deploy 권한 최소 부여 |
| `cloudbuild.yaml` shared file 수정 | 팀 충돌 | 팀 승인 후 별도 PR |
| Autopilot resource 제한/수정 | Pod 배포 실패 | requests/limits를 Autopilot 권장 범위로 조정 |
| gVisor + Python multiprocessing 미지원 | bot-runner executor 격리 실패 | PR 4 단계에서 사전 smoke, 실패 시 gVisor 포기 + 일반 Pod + NetworkPolicy/resource limit 강화로 재설계 (thread executor 불가) |
| `/battleroyale/health`만으로 readiness 판정 | MockStocks DB 실패 미감지 | Phase 2에서 통합 `/healthz` 추가 후 probe로 사용 |
| Ingress static IP 미예약 | Ingress 재생성 시 IP 변경, 프론트 환경변수 동시 수정 필요 | `gcloud compute addresses create` 사전 예약 |
| Workload Identity 미설정 | GCS boss weights 읽기 실패로 보스 게임 startup 실패 | Phase 6에서 GCP SA + K8s SA 바인딩 + Pod annotation 명시 |
| GKE Autopilot 상시 비용 | 캡스톤 GCP 크레딧 빠른 소진 | Phase 0에서 비용 baseline 확인 및 예산 알림 설정 |

---

## 11. PR 분리 제안

### PR 1. Bot Runner 코드 추가

범위:

- `backend/BotRunner/*`
- Bot Runner tests

검증:

- Bot Runner pytest
- Docker build
- local uvicorn health/action

### PR 2. RemoteBotAdapter 도입 + 통합 /healthz

범위:

- BattleRoyale remote adapter
- MockStocks remote adapter
- settings 추가
- create_game 연결
- 통합 `/healthz` 엔드포인트 추가 (BattleRoyale + MockStocks DB 상태 종합)
- tests

검증:

- 기존 backend tests
- Bot Runner mock HTTP tests
- `/healthz` 응답이 정상/degraded 두 경로 모두 테스트

참고:

- 통합 `/healthz`는 Phase 3 manifest의 readiness/liveness probe path가 된다. PR 2 merge 전에 PR 3을 시작하지 않는다.

### PR 3. Kubernetes manifests 추가

범위:

- `k8s/base/*` (Deployment, Service, ConfigMap, ServiceAccount, NetworkPolicy, Ingress, BackendConfig, HPA)
- `k8s/base/backend-config.yaml` (WebSocket timeout 3600s)
- `k8s/secret.example.yaml`
- `k8s/README.md`

검증:

- `kubectl apply --dry-run=client`
- kubeconform/kubeval 가능하면 사용
- bot-runner manifest에 `runtimeClassName: gvisor`, `readOnlyRootFilesystem: true`, `/tmp` tmpfs emptyDir 명시 확인
- bot-runner manifest에 `envFrom: secretRef` 없음 확인
- game-server Service에 `cloud.google.com/backend-config` annotation 확인
- NetworkPolicy egress deny 확인
- ServiceAccount manifest에 Workload Identity annotation 확인

### PR 4. GKE staging 수동 배포 검증

범위:

- 코드 변경 최소
- WORK_LOG/Notion/Obsidian 기록

검증:

- GKE smoke/E2E
- Cloud Run rollback 가능 상태 유지

### PR 5. cloudbuild.yaml에 GKE 병행 배포 경로 추가

범위:

- `cloudbuild.yaml`
- 필요 시 deploy script

조건:

- 팀 승인 필요
- staging GKE 검증 완료 후
- 기존 Cloud Run deploy 제거 금지
- 프론트/API 트래픽은 아직 Cloud Run 유지

검증:

- Cloud Run deploy step 정상
- GKE deploy step 정상
- GKE deploy 실패 시 기존 Cloud Run 서비스 영향 없음

### PR 6. GKE 안정화 관찰 및 보완

범위:

- `k8s/base/*` 보완
- `k8s/README.md` 운영 절차 보완
- 필요 시 BackendConfig, readiness/liveness, resource limit 조정

조건:

- Cloud Build가 Cloud Run과 GKE를 병행 배포 중
- 사용자는 아직 Cloud Run을 사용
- GKE Ingress URL로 별도 E2E 검증 가능

검증:

- 최소 1회 이상 실제 Cloud Build 병행 배포 성공
- GKE Ingress URL 기준 BattleRoyale/Boss/MockStocks E2E 통과
- WebSocket 장시간 관전 확인
- Cloud SQL/Redis/GCS 접근 안정성 확인
- Bot Runner gVisor/NetworkPolicy 확인
- 비용과 로그량 확인

### PR 7. frontend/API 정식 cutover

범위:

- Firebase/Vite env 또는 배포 설정
- 코드에 URL 하드코딩이 있으면 정리
- 필요 시 DNS/도메인 설정 문서 갱신

검증:

- 실제 배포 URL로 E2E
- GKE URL 기준 WebSocket 관전 확인
- Cloud Run URL rollback 절차 확인

조건:

- PR 6 안정화 기준 충족
- 팀 승인
- cutover 시간대 합의
- Cloud Run 서비스를 삭제하지 않고 rollback 대상으로 유지

### PR 8. Cloud Run 정리 여부 결정

이 PR은 필수가 아니다. 캡스톤 기간에는 Cloud Run을 rollback 대상으로 계속 유지해도 된다.

정리 조건:

- GKE cutover 후 일정 기간 장애 없음
- Cloud Build/GKE 배포가 안정적
- 비용 이슈로 Cloud Run 유지가 부담됨
- 팀이 rollback 대상을 GKE 이전 revision 또는 별도 backup으로 대체하기로 합의

범위:

- `cloudbuild.yaml`에서 Cloud Run deploy 제거 여부
- Cloud Run service 삭제 여부는 코드 PR만으로 처리하지 않고 별도 운영 승인 필요

검증:

- Cloud Run 제거 전 최종 백업/rollback 계획 문서화
- Firebase/frontend가 GKE만 바라보는지 확인

---

## 12. 완료 기준

Kubernetes 전환을 완료로 볼 조건:

- [ ] GKE `game-server` Pod 2개 이상 정상
- [ ] GKE `bot-runner` Pod 2개 이상 정상
- [ ] `bot-runner` Pod runtimeClassName이 `gvisor`
- [ ] `bot-runner` Pod에서 gVisor + Python multiprocessing/resource/tmpfs smoke 통과
- [ ] `bot-runner`에 DB/Firebase/Gemini/JWT/GCS Secret 미주입
- [ ] `bot-runner` Pod readOnlyRootFilesystem + tmpfs `/tmp` 적용
- [ ] NetworkPolicy로 `bot-runner` egress deny 적용
- [ ] `/healthz` 통합 endpoint 정상 (BattleRoyale + MockStocks DB 모두 반영)
- [ ] `/battleroyale/health` 정상
- [ ] `/stocks/health` 정상
- [ ] GKE Ingress static IP 예약 및 도메인/프론트 base URL 매핑
- [ ] BackendConfig WebSocket timeout 3600s 적용 확인
- [ ] Workload Identity로 game-server SA가 GCS boss weights 읽기 성공
- [ ] GCP 예산 알림 설정 및 baseline 비용 기록
- [ ] BattleRoyale 게임 생성/관전/종료/결과 정상
- [ ] Boss 게임 생성/관전/종료/결과 정상
- [ ] MockStocks 게임 생성/관전/종료/결과 정상
- [ ] GamesPage active/history 정상
- [ ] 계정별 owner filtering 정상
- [ ] 유저 봇 악성 코드 smoke test에서 서버 Secret 노출 없음
- [ ] Cloud Run rollback 경로 문서화
- [ ] Cloud Build가 Cloud Run + GKE 병행 배포 수행
- [ ] 병행 배포 기간 동안 GKE Ingress URL 기준 E2E 안정화 확인
- [ ] 팀 승인 후 frontend/API 트래픽을 GKE로 cutover
- [ ] cutover 후에도 Cloud Run rollback 경로 유지

Cloud Run 정리는 완료 기준에 포함하지 않는다. 안정화 후 비용/운영 판단에 따라 별도 PR 또는 운영 작업으로 결정한다.

---

## 13. 현재 기준 첫 작업 추천

바로 시작한다면 첫 커밋은 Kubernetes YAML이 아니라 **Bot Runner API와 adapter 경계**가 좋다.

이유:

- 현재 가장 큰 코드 리스크는 인프라가 아니라 `InProcessBot` 제거다.
- Bot Runner API가 안정되지 않으면 GKE Deployment를 만들어도 실행할 서비스가 없다.
- BattleRoyale와 MockStocks의 action contract가 다르므로 이 부분을 먼저 고정해야 한다.

첫 작업 체크리스트:

- [ ] `backend/BotRunner` 생성
- [ ] BattleRoyale/MockStocks action schema 지원
- [ ] timeout/fallback 정책 구현
- [ ] `RemoteBattleRoyaleBotAdapter` 구현
- [ ] `RemoteStockBotAdapter` 구현
- [ ] `BOT_RUNNER_URL`, `BOT_RUNNER_REQUIRED`, `BOT_RUNNER_TIMEOUT_SEC` 설정 추가
- [ ] 유저 봇만 remote, AI filler/boss는 in-process 유지
- [ ] pytest로 fallback/timeout 검증

---

## 14. 참고 공식 문서

- GKE Sandbox: https://cloud.google.com/kubernetes-engine/docs/concepts/sandbox-pods
- GKE Sandbox 사용: https://cloud.google.com/kubernetes-engine/docs/how-to/sandbox-pods
- GKE Autopilot overview: https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview
- GKE Network Policy: https://cloud.google.com/kubernetes-engine/docs/how-to/network-policy
- GKE pricing: https://cloud.google.com/kubernetes-engine/pricing

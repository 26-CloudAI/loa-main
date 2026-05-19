# k8s/ — Kubernetes 매니페스트

League of Agents GKE 배포 설계도. Phase 3에서 작성, Phase 4~5에서 실제 적용.

---

## 디렉터리 구조

```
k8s/
├── base/                          # GKE 운영 매니페스트
│   ├── kustomization.yaml         # Kustomize 리소스 목록 (Skaffold용)
│   ├── namespace.yaml             # arena namespace
│   ├── configmap.yaml             # 비밀 아닌 설정값
│   ├── service-account.yaml       # game-server / bot-runner KSA
│   ├── game-server-deployment.yaml
│   ├── game-server-service.yaml
│   ├── bot-runner-deployment.yaml
│   ├── bot-runner-service.yaml
│   ├── backend-config.yaml        # WebSocket timeout 3600s
│   ├── network-policy.yaml        # bot-runner 인터넷 완전 차단
│   ├── ingress.yaml               # GKE Ingress (api.leagueofagents.net)
│   ├── managed-certificate.yaml   # Google 관리 SSL 인증서
│   └── hpa.yaml                   # bot-runner HPA (min2/max10)
├── overlays/
│   └── local/                     # 로컬 Kubernetes(minikube) 오버라이드
│       ├── kustomization.yaml
│       └── bot-runner-patch-local.yaml
├── secret.example.yaml            # Secret 형식 예시 (실제 값 없음)
└── README.md
```

---

## 핵심 설계 원칙

| 원칙 | 내용 |
|------|------|
| game-server replicas: 1 고정 | 세션이 프로세스 메모리에 있음. Redis 외부화 전까지 증설 불가 |
| bot-runner Secret 없음 | 유저 봇 코드가 훔칠 비밀 정보가 없어야 함 |
| bot-runner egress 차단 | NetworkPolicy로 외부 인터넷 호출 완전 차단 |
| gVisor 격리 | bot-runner에만 적용. 봇 코드의 syscall을 제한 |
| BOSS_WEIGHTS_GCS_URI 미포함 | Phase 5 Cloud Build step에서 kubectl patch로 주입 |

---

## 적용 방법

### 수동 적용 (Phase 4 이후)

```bash
# 1. GKE 클러스터 인증
gcloud container clusters get-credentials arena-cluster \
  --region asia-northeast3 --project knu-2026-sungjin0418

# 2. Secret 먼저 생성 (한 번만)
kubectl create secret generic arena-secrets \
  --namespace arena \
  --from-literal=DB_PASSWORD="$(gcloud secrets versions access latest --secret=db-password)" \
  --from-literal=FIREBASE_CREDENTIALS_JSON="$(gcloud secrets versions access latest --secret=firebase-service-account)" \
  --from-literal=GEMINI_API_KEY="$(gcloud secrets versions access latest --secret=GEMINI_API_KEY)" \
  --from-literal=JWT_SECRET="$(openssl rand -hex 32)"

# 3. 매니페스트 적용 (Kustomize 모드) — 초기 설정 및 네임스페이스/서비스 적용
kubectl apply -k k8s/base/

# 4. 실제 이미지 태그로 교체 (latest 또는 빌드한 특정 태그)
IMAGE_TAG=latest   # 특정 태그를 쓰려면 여기를 변경
kubectl set image deployment/game-server \
  game-server=asia-northeast3-docker.pkg.dev/knu-2026-sungjin0418/ai-arena/server:${IMAGE_TAG} \
  -n arena
kubectl set image deployment/bot-runner \
  bot-runner=asia-northeast3-docker.pkg.dev/knu-2026-sungjin0418/ai-arena/bot-runner:${IMAGE_TAG} \
  -n arena

# 5. 롤아웃 완료 확인
kubectl rollout status deployment/game-server -n arena
kubectl rollout status deployment/bot-runner -n arena
```

### dry-run 검증 (클러스터 없이)

```bash
kubectl apply --dry-run=client -k k8s/base/
# BackendConfig, ManagedCertificate 에러는 GKE 전용 CRD라 로컬에서 정상. 실제 GKE에서는 통과.
```

### Skaffold 로컬 개발 (선택)

```bash
minikube start
skaffold dev --profile=local
```

---

## 도메인 구성

| 도메인 | 대상 |
|--------|------|
| `leagueofagents.net` | Firebase Hosting (React 프론트엔드) |
| `www.leagueofagents.net` | Firebase Hosting (리다이렉트) |
| `api.leagueofagents.net` | GKE Ingress (FastAPI 백엔드) |

> `api.leagueofagents.net` A레코드는 Phase 4에서 GKE static IP 예약 후 Cloud DNS에 추가한다.
> `gcloud compute addresses create loa-arena-ingress-ip --global`

---

## Secret 주의사항

- `secret.example.yaml`은 형식 예시만 있고 실제 값이 없다. git에 커밋해도 안전.
- 실제 Secret은 `kubectl create secret` 명령으로 수동 생성한다.
- Secret 값이 들어간 YAML 파일은 절대 git에 커밋하지 않는다.

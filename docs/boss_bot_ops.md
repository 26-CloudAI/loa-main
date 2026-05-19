# 보스 봇 운영 가이드

서비스/학습 인프라를 SSH만으로 운영하기 위한 실용 매뉴얼.
복붙 후 바로 실행 가능하도록 실제 값(프로젝트 ID, VM명, IP, 버킷명) 그대로 기입.

---

## 1. 시스템 개요

### 아키텍처

```
                 ┌──────────────────────────────────────────────────┐
                 │              GCS: knu-2026-boss-weights          │
                 │  boss_weights.pt        (RL 학습 가중치, PyTorch)│
                 │  quality_bots.json      (학습 대상 봇 목록)      │
                 │  training_meta.json     (마지막 학습 메타)       │
                 │  trained_bot_history.json (최근 학습 봇 이력)    │
                 └──────────────────────────────────────────────────┘
                       ▲                              ▲       │
              (1) 매일 1회                    (3) 학습 후     │ (4) 10분마다
              quality_bots.json 업로드        boss_weights.pt │  가중치 generation 변화 감지
                       │                       업로드          │  → 싱글톤 무효화
                       │                              │       ▼
┌────────────────────────────────┐   ┌────────────────────────────────┐
│ 서빙 VM                        │   │ 학습 VM                        │
│ instance-20260512-001211       │   │ boss-training-vm               │
│ us-central1-a / 104.197.230.135│   │ asia-northeast3-a / 34.64.42.5 │
│                                │   │                                │
│ - FastAPI (보스전 서비스)      │   │ (2) Cloud Scheduler            │
│ - InProcessBot (유저코드)      │   │     boss-training-daily        │
│ - RLBossBot(Torch) 싱글톤      │   │     매일 02:00 KST → VM start  │
│ - cron: 01:00 KST              │   │ - startup-script가 학습 자동   │
│   export_quality_bots.py       │   │ - 학습 후 self-stop            │
└────────────────────────────────┘   └────────────────────────────────┘
```

### 구성요소

| 구성요소 | 역할 | 코드/파일 |
|---|---|---|
| 서빙 VM | 보스전 게임 실행, 유저 봇 vs 보스봇 | `src/arena/server/app.py` |
| RLBossBot (numpy) | 폴백용 보스봇 (PyTorch 미설치 환경) | `bots/rl_boss_bot.py` |
| RLBossBotTorch | 운영용 보스봇 (학습 가중치 사용) | `bots/rl_boss_bot_torch.py` |
| RuleBossEasy/Medium | 룰베이스 보스봇 (난이도 하/중) | `bots/rule_boss_bot.py` |
| 학습 스크립트 | 병렬 DQN 학습 | `train_boss_parallel.py` |
| 품질 봇 추출 | DB → GCS `quality_bots.json` | `scripts/export_quality_bots.py` |
| GCS 유틸 | 가중치 / JSON 업·다운로드 | `gcs_weights.py` |
| Startup Script | 학습 VM 부팅 시 자동 학습 | `/tmp/boss-startup.sh` (참고용) |

---

## 2. GCP 인프라

### 프로젝트
```
프로젝트 ID: knu-2026-hangloss0331
리전        : asia-northeast3 (서울) — 학습
              us-central1     (아이오와) — 서빙
GitHub 저장소: git@github.com:26-CloudAI/loa-main.git (브랜치: yoontaek)
```

### VM

| VM | Zone | 외부 IP | 스펙 | 용도 |
|---|---|---|---|---|
| `instance-20260512-001211` | us-central1-a | 104.197.230.135 | e2-medium | 서빙 (FastAPI) |
| `boss-training-vm` | asia-northeast3-a | 34.64.42.5 | n2-standard-4 (Spot) | 학습 |

### GCS 버킷

```
gs://knu-2026-boss-weights/
  ├─ boss_weights.pt              # RL 학습 가중치 (PyTorch state_dict)
  ├─ quality_bots.json            # 학습 대상 봇 목록 (서빙 VM이 매일 업로드)
  ├─ training_meta.json           # 마지막 학습 세션 메타
  └─ trained_bot_history.json     # 최근 학습 세션별 봇 ID (중복 방지용)
```

### Cloud Scheduler
```
이름      : boss-training-daily
스케줄    : 0 17 * * *  (UTC) = 02:00 KST
대상      : VM start (boss-training-vm, asia-northeast3-a)
실행 원리 : VM startup-script가 자동 학습 → self-stop
```

### Secret / Metadata
- **학습 VM**: VM Instance Metadata에 `github-token` 키로 PAT 저장
  - 메타데이터 서버를 통해서만 접근 가능 (`Metadata-Flavor: Google` 헤더)
- **서빙 VM**: `/etc/environment`에 평문 (다른 OS 유저 접근 불가)
  - `BOSS_WEIGHTS_GCS_URI=gs://knu-2026-boss-weights/boss_weights.pt`
  - `JWT_SECRET=...`

### Service Account
- 학습 VM SA: `632937281491-compute@developer.gserviceaccount.com` (roles/editor)

---

## 3. 일상 운영

### 3.1 학습 VM 로그 실시간 확인

```bash
# SSH 접속 (외부 IP 사용)
gcloud compute ssh boss-training-vm \
  --zone=asia-northeast3-a --project=knu-2026-hangloss0331

# 또는 직접 SSH (방화벽에 22 허용 필요)
ssh -i ~/.ssh/google_compute_engine hangloss0331@34.64.42.5

# 학습 로그 실시간 follow (startup-script가 tee로 기록 중)
sudo tail -F /var/log/boss-train.log

# 학습 프로세스 상태
sudo systemctl status google-startup-scripts
ps -ef | grep -E 'train_boss_parallel|python' | grep -v grep

# 현재 학습 중 worker 로그만
sudo grep -E '\[W[0-9]+ ep' /var/log/boss-train.log | tail -50
```

### 3.2 서빙 VM 로그 실시간 확인

```bash
gcloud compute ssh instance-20260512-001211 \
  --zone=us-central1-a --project=knu-2026-hangloss0331

# FastAPI 로그 (운영 환경에서 systemd 사용 가정)
sudo journalctl -u battle-royale -f
# 또는 직접 실행 중이라면
tail -F /var/log/battle-royale.log

# export_quality_bots.py cron 로그
crontab -l                              # 등록된 cron 확인
ls -la /var/log/export_bots.log 2>/dev/null
tail -100 /var/log/export_bots.log
```

### 3.3 수동 학습 트리거

```bash
# (방법 1) Cloud Scheduler 강제 실행
gcloud scheduler jobs run boss-training-daily \
  --location=asia-northeast3 \
  --project=knu-2026-hangloss0331

# (방법 2) gcloud로 VM 직접 start (Scheduler와 동일 효과)
gcloud compute instances start boss-training-vm \
  --zone=asia-northeast3-a --project=knu-2026-hangloss0331

# (방법 3) SSH에서 학습 강제 실행 (조건 무시)
# 학습 VM 안에서:
cd /opt/loa-main/backend/BattleRoyale
BOSS_WEIGHTS_GCS_URI=gs://knu-2026-boss-weights/boss_weights.pt \
  /opt/boss-venv/bin/python train_boss_parallel.py \
  --device cpu --workers 3 --force
```

### 3.4 export_quality_bots.py 수동 실행 (서빙 VM)

```bash
# SSH 접속 후
cd /home/hangloss0331/loa-main/backend/BattleRoyale
# (정확한 경로는 운영 환경에 맞게 조정)
python3 scripts/export_quality_bots.py

# 환경변수가 필요한 경우
BOSS_WEIGHTS_GCS_URI=gs://knu-2026-boss-weights/boss_weights.pt \
  python3 scripts/export_quality_bots.py

# 결과 확인 (GCS)
gsutil cat gs://knu-2026-boss-weights/quality_bots.json | jq '.count, .exported_at'
```

### 3.5 학습 결과 모니터링

```bash
# 가중치 generation, 메타 정보 한눈에
gsutil cat gs://knu-2026-boss-weights/training_meta.json | jq

# 가중치 파일 정보
gsutil ls -l gs://knu-2026-boss-weights/boss_weights.pt
gsutil stat gs://knu-2026-boss-weights/boss_weights.pt

# 최근 학습 봇 ID
gsutil cat gs://knu-2026-boss-weights/trained_bot_history.json | jq
```

---

## 4. 장애 대응

### 4.1 학습 VM이 멈추거나 비정상 종료된 경우

**증상**: Cloud Scheduler 시간 지나도 학습 안 됨, training_meta.json 갱신 없음.

```bash
# 1. VM 상태 확인
gcloud compute instances describe boss-training-vm \
  --zone=asia-northeast3-a --project=knu-2026-hangloss0331 \
  --format='value(status,lastStartTimestamp,lastStopTimestamp)'

# 2. VM 강제 reset (실행 중이면 reboot, 멈춰있으면 start)
gcloud compute instances reset boss-training-vm \
  --zone=asia-northeast3-a --project=knu-2026-hangloss0331

# 3. 그래도 안 되면 start
gcloud compute instances start boss-training-vm \
  --zone=asia-northeast3-a --project=knu-2026-hangloss0331

# 4. SSH 들어가서 학습 락 잔존 여부 확인
gcloud compute ssh boss-training-vm --zone=asia-northeast3-a --command='
  ls -la /var/run/boss-training.lock 2>/dev/null
  cat /var/run/boss-training.lock 2>/dev/null
  sudo rm -f /var/run/boss-training.lock
'
```

### 4.2 가중치 손상 (학습 결과가 이상한 경우)

```bash
# 1. 현재 가중치 백업 (timestamp suffix)
TS=$(date +%Y%m%d_%H%M%S)
gsutil cp gs://knu-2026-boss-weights/boss_weights.pt \
          gs://knu-2026-boss-weights/backup/boss_weights.${TS}.pt

# 2. 이전 generation 목록 확인 (객체 버저닝이 켜져 있을 때만)
gsutil ls -a gs://knu-2026-boss-weights/boss_weights.pt

# 3. 특정 generation으로 롤백 (버저닝 활성화 시)
gsutil cp gs://knu-2026-boss-weights/boss_weights.pt#<GENERATION_NUMBER> \
          gs://knu-2026-boss-weights/boss_weights.pt

# 4. 백업으로 롤백 (가장 단순)
gsutil cp gs://knu-2026-boss-weights/backup/boss_weights.20260510_120000.pt \
          gs://knu-2026-boss-weights/boss_weights.pt

# 5. 처음부터 학습 (이전 가중치 완전 폐기)
gsutil rm gs://knu-2026-boss-weights/boss_weights.pt
gsutil rm -f gs://knu-2026-boss-weights/trained_bot_history.json
# 다음 Cloud Scheduler 실행 시 신규 학습
```

> **주의**: 버저닝이 비활성화돼 있으면 generation 롤백이 불가합니다. 평소에 백업본을
> `backup/` 디렉토리에 따로 보관해두세요. (학습 후 자동 백업 설정은 7장 참고)

### 4.3 서빙 VM 재시작 후 환경변수 적용 확인

```bash
# 1. 환경변수 정상 로드 확인
ssh ... 104.197.230.135
sudo cat /etc/environment
# 출력 예:
# BOSS_WEIGHTS_GCS_URI=gs://knu-2026-boss-weights/boss_weights.pt
# JWT_SECRET=...

# 2. FastAPI 프로세스가 환경변수 적용했는지 확인
ps -ef | grep uvicorn | head -3
PID=$(pgrep -f 'uvicorn.*battle' | head -1)
sudo cat /proc/${PID}/environ | tr '\0' '\n' | grep -E 'BOSS_|JWT_'

# 3. 서비스로 관리 중이라면 (systemd)
sudo systemctl restart battle-royale
sudo systemctl status battle-royale

# 4. 환경변수가 systemd unit에서 떨어진 경우
# /etc/systemd/system/battle-royale.service 에 EnvironmentFile=/etc/environment 추가
```

### 4.4 보스봇 가중치 강제 갱신 (서빙 VM)

```bash
# 1. 캐시 파일 삭제 → 다음 보스전 생성 시 GCS에서 재다운로드
sudo rm -f /tmp/boss_weights.pt /tmp/boss_weights.json

# 2. 또는 서버 재시작 (lifespan에서 download 호출)
sudo systemctl restart battle-royale

# 3. 그래도 메모리상 싱글톤이 남아있으면 GCS의 가중치 generation을 변경 (재업로드)
gsutil cp /tmp/boss_weights.pt gs://knu-2026-boss-weights/boss_weights.pt
# → 10분 내 hot-reload 태스크가 감지하고 싱글톤 무효화

# 4. 즉시 적용하려면 서버 재시작이 가장 확실
```

### 4.5 게임 세션이 꼬여서 멈춰있는 경우

```bash
# DB에서 미완료 게임 강제 종료
sudo systemctl restart battle-royale
# → 시작 시 cleanup_stale_games()가 waiting/running 게임을 error 처리
```

---

## 5. SSH 치트시트

### 5.1 학습 VM (boss-training-vm)

```bash
# 접속
gcloud compute ssh boss-training-vm \
  --zone=asia-northeast3-a --project=knu-2026-hangloss0331

# 직접 SSH (key 등록 후)
ssh -i ~/.ssh/google_compute_engine hangloss0331@34.64.42.5

# === SSH 내부에서 ===
# 학습 로그 실시간
sudo tail -F /var/log/boss-train.log

# venv 활성화
source /opt/boss-venv/bin/activate
cd /opt/loa-main/backend/BattleRoyale

# 강제 학습 (스케줄 무시)
BOSS_WEIGHTS_GCS_URI=gs://knu-2026-boss-weights/boss_weights.pt \
  python train_boss_parallel.py --device cpu --workers 3 --force

# 로컬 디버그 학습 (GCS 업로드 안 함, VM 종료 안 함)
python train_boss_parallel.py --no-gcs --no-self-stop --force \
  --workers 2 --episodes-per-worker 10

# 학습 락 해제
sudo rm -f /var/run/boss-training.lock

# 가중치 파일 직접 확인
ls -la /opt/loa-main/backend/BattleRoyale/bots/trained_weights_torch.pt
python -c "
import torch
ck = torch.load('/opt/loa-main/backend/BattleRoyale/bots/trained_weights_torch.pt', weights_only=True)
print('version:', ck.get('version'))
print('episodes:', ck.get('episode_count'))
print('steps:', ck.get('step_count'))
print('epsilon:', ck.get('epsilon'))
"

# VM 수동 종료 (학습 중 외 비용 절약)
sudo shutdown -h now
# 또는 외부에서
gcloud compute instances stop boss-training-vm --zone=asia-northeast3-a
```

### 5.2 서빙 VM (instance-20260512-001211)

```bash
# 접속
gcloud compute ssh instance-20260512-001211 \
  --zone=us-central1-a --project=knu-2026-hangloss0331

ssh -i ~/.ssh/google_compute_engine hangloss0331@104.197.230.135

# === SSH 내부에서 ===
# FastAPI 로그
sudo journalctl -u battle-royale -f

# 환경변수 확인
sudo cat /etc/environment
env | grep -E 'BOSS_|JWT_'

# 서버 재시작
sudo systemctl restart battle-royale

# DB 백업
cp /home/hangloss0331/loa-main/backend/BattleRoyale/ai_arena.db \
   /home/hangloss0331/backup/ai_arena.$(date +%Y%m%d).db

# cron 확인 / 편집
crontab -l
crontab -e
# 예시: 0 16 * * *  cd /home/hangloss0331/loa-main/backend/BattleRoyale && python3 scripts/export_quality_bots.py >> /var/log/export_bots.log 2>&1

# 수동 quality_bots.json 갱신
cd /home/hangloss0331/loa-main/backend/BattleRoyale
BOSS_WEIGHTS_GCS_URI=gs://knu-2026-boss-weights/boss_weights.pt \
  python3 scripts/export_quality_bots.py

# 캐시 가중치 강제 갱신
sudo rm -f /tmp/boss_weights.pt /tmp/boss_weights.json
sudo systemctl restart battle-royale
```

### 5.3 로컬에서 GCS 직접 조작

```bash
# 인증 확인
gcloud auth list
gcloud config set project knu-2026-hangloss0331

# 객체 목록
gsutil ls -l gs://knu-2026-boss-weights/

# 메타 확인
gsutil cat gs://knu-2026-boss-weights/training_meta.json | jq
gsutil cat gs://knu-2026-boss-weights/quality_bots.json   | jq '.count, .exported_at, .bots[0:3]'

# 가중치 백업
gsutil cp gs://knu-2026-boss-weights/boss_weights.pt \
          gs://knu-2026-boss-weights/backup/boss_weights.$(date +%Y%m%d_%H%M%S).pt

# 로컬로 다운로드
gsutil cp gs://knu-2026-boss-weights/boss_weights.pt /tmp/
gsutil cp gs://knu-2026-boss-weights/quality_bots.json /tmp/
```

---

## 6. 환경변수 목록

### 서빙 VM `/etc/environment`

| 변수 | 값 | 용도 |
|---|---|---|
| `BOSS_WEIGHTS_GCS_URI` | `gs://knu-2026-boss-weights/boss_weights.pt` | 가중치 다운로드·업로드 대상 |
| `JWT_SECRET` | (64자 hex) | 개발 환경 토큰 서명 키 |
| `ENV` (선택) | `production` | 운영 모드 (mock_auth 비활성화) |
| `DB_TYPE` (선택) | `sqlite` (기본) / `postgresql` | DB 종류 |
| `CORS_ORIGINS` (선택) | 콤마 구분 도메인 | CORS 허용 출처 |

### 학습 VM (startup-script가 일회성으로 export)

| 변수 | 값 | 용도 |
|---|---|---|
| `BOSS_WEIGHTS_GCS_URI` | `gs://knu-2026-boss-weights/boss_weights.pt` | 학습 후 가중치 업로드 대상 |
| `GIT_ASKPASS` | 임시 파일 | GitHub PAT 일회성 전달 (clone 후 즉시 삭제) |
| `GIT_TERMINAL_PROMPT` | `0` | git 대화형 프롬프트 차단 |

학습 봇 자체에는 추가 환경변수 불필요.

### 기타 GCP 메타데이터 (VM Instance Metadata)

| Key | VM | 용도 |
|---|---|---|
| `github-token` | boss-training-vm | private repo clone 용 PAT |
| `startup-script` | boss-training-vm | `/tmp/boss-startup.sh` 내용 |

---

## 7. Docker 격리 추가 시 체크리스트

현재 유저 봇 코드는 `_RESTRICTED_BUILTINS`로 builtins 일부만 제한된 in-process exec입니다.
이는 우발적 공격은 막지만 전문 공격자에게는 부족합니다. Docker/seccomp 격리로 전환할 때
체크해야 할 항목:

### 7.1 격리해야 할 코드 경로
- [ ] `src/arena/server/app.py:InProcessBot` — 서빙 측 유저 봇 실행
- [ ] `train_boss_parallel.py:_InProcessUserBot` — 학습 시 유저 봇 실행
- [ ] 두 곳 모두 동일한 격리 정책 적용 (현재는 `_FORBIDDEN_BUILTINS` 동기화로만 처리)

### 7.2 컨테이너 보안 옵션
- [ ] `--network=none` — 네트워크 차단
- [ ] `--read-only` + `--tmpfs /tmp` — 파일시스템 read-only
- [ ] `--cap-drop=ALL` — capability 제거
- [ ] `--security-opt=no-new-privileges` — 권한 상승 차단
- [ ] `--security-opt=seccomp=profile.json` — syscall 화이트리스트
- [ ] `--pids-limit=32`, `--memory=128m`, `--cpus=0.5` — 리소스 제한
- [ ] `--user nobody` 또는 unprivileged user — non-root 실행

### 7.3 인터페이스 변경 사항
- [ ] state(dict) → JSON 직렬화 후 stdin 전달
- [ ] action(str) → stdout으로 한 줄 출력
- [ ] 한 게임당 컨테이너 재사용 vs 매 틱마다 새 컨테이너 — 성능 트레이드오프 평가
- [ ] 추천: 게임 1회당 컨테이너 1개, stdin/stdout 라인 기반 RPC

### 7.4 타임아웃
- [ ] 봇 응답 타임아웃 (현재는 engine 측에서 예외 잡고 STAY)
- [ ] 컨테이너 단위 타임아웃 (최대 게임 시간 +α)
- [ ] 시작 지연 측정 (warm container 풀 필요 여부)

### 7.5 로그/감사
- [ ] 컨테이너 stderr 수집 (디버깅용)
- [ ] 비정상 종료 코드 알림 (악성 코드 감지)
- [ ] 리소스 한도 도달 이벤트 로깅

### 7.6 인프라
- [ ] 서빙 VM에 Docker 설치 + cgroup v2 확인
- [ ] 컨테이너 이미지 빌드/푸시 파이프라인 (Artifact Registry)
- [ ] 베이스 이미지: `python:3.11-slim-bullseye` 권장
- [ ] 학습 VM에는 별도 환경 (PyTorch 포함 이미지 필요)

### 7.7 점진적 도입
- [ ] Phase 1: 서빙 측만 Docker 적용 (학습은 그대로)
- [ ] Phase 2: 학습 측도 Docker 적용 (PyTorch 포함 이미지)
- [ ] Phase 3: `_RESTRICTED_BUILTINS` 코드 제거 (격리가 보장하므로 불필요)

---

## 8. 참고: 코드/설정 위치

```
loa-main/
├─ backend/BattleRoyale/
│   ├─ bots/
│   │   ├─ rl_boss_bot.py            # numpy DQN 보스봇 (폴백)
│   │   ├─ rl_boss_bot_torch.py      # PyTorch DQN 보스봇 (운영)
│   │   ├─ rule_boss_bot.py          # 룰베이스 보스봇 (하/중 난이도)
│   │   ├─ trained_weights.json      # numpy 가중치 캐시 (로컬)
│   │   ├─ trained_weights_torch.pt  # PyTorch 가중치 캐시 (로컬)
│   │   ├─ quality_bots.json         # 로컬 폴백용
│   │   └─ trained_bot_history.json  # 로컬 폴백용
│   ├─ scripts/
│   │   └─ export_quality_bots.py    # DB → GCS 품질봇 추출
│   ├─ src/arena/
│   │   ├─ server/app.py             # FastAPI, RL 봇 싱글톤 관리
│   │   ├─ engine.py                 # 게임 엔진
│   │   ├─ config.py                 # 게임 상수, boss_battle_config()
│   │   └─ db/schema.py              # SQLite/Postgres 스키마
│   ├─ gcs_weights.py                # GCS 가중치/JSON 유틸
│   ├─ train_boss_parallel.py        # 병렬 학습 메인
│   └─ ai_arena.db                   # SQLite (서빙)
└─ docs/
    └─ boss_bot_ops.md               # 이 문서

학습 VM:
  /opt/loa-main/                     # git clone된 코드 (startup-script가 sync)
  /opt/boss-venv/                    # Python venv
  /var/log/boss-train.log            # 학습 로그
  /var/run/boss-training.lock        # 학습 중복 방지 락
  메타데이터: github-token, startup-script

서빙 VM:
  /home/hangloss0331/loa-main/       # 코드 (수동 git pull)
  /tmp/boss_weights.pt               # GCS 캐시 (lifespan에서 다운로드)
  /etc/environment                   # BOSS_WEIGHTS_GCS_URI, JWT_SECRET
  crontab: 01:00 KST export_quality_bots.py
```

---

## 9. 자주 묻는 운영 시나리오

### Q. 학습이 한 번 실패한 후 다음 날에도 안 됨
A. `trained_bot_history.json`이 비정상 갱신됐을 가능성. GCS에서 확인 후 필요 시 초기화:
```bash
gsutil rm gs://knu-2026-boss-weights/trained_bot_history.json
```

### Q. 서빙 VM에 PyTorch 설치 안 돼있는데 학습 가중치가 반영되나?
A. **반영되지 않습니다**. `app.py`는 PyTorch가 있으면 `RLBossBotTorch`, 없으면 numpy `RLBossBot`을 사용합니다. numpy 버전은 `.pt` 파일을 로드할 수 없습니다.
**조치**: 서빙 VM에 PyTorch CPU 버전 설치
```bash
pip install --index-url https://download.pytorch.org/whl/cpu torch
sudo systemctl restart battle-royale
```

### Q. 학습 VM이 매일 켜졌다가 바로 꺼짐 (학습 안 함)
A. 정상 동작입니다. `train_boss_parallel.py`가 `MIN_NEW_BOTS=3` 미만의 신규 봇이면서 마지막 학습 후 7일 미경과면 self-stop합니다. 강제 학습은 `--force` 플래그 사용.

### Q. Cloud Scheduler 시간 바꾸려면?
```bash
gcloud scheduler jobs update http boss-training-daily \
  --location=asia-northeast3 \
  --schedule="0 18 * * *"   # UTC 18:00 = KST 03:00
```

### Q. 가중치 자동 백업 설정
서빙 또는 별도 cron에 추가:
```bash
# 매일 자정 백업 (UTC 15:00 = KST 00:00)
0 15 * * *  gsutil -q cp gs://knu-2026-boss-weights/boss_weights.pt gs://knu-2026-boss-weights/backup/boss_weights.$(date +\%Y\%m\%d).pt
```

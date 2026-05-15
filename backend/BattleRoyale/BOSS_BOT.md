# 보스봇 설계 문서

> AI Arena 보스전 시스템의 전체 설계, 구현 세부사항, 운영 가이드를 담는 문서다.  
> 최종 수정: 2026-05-15

---

## 목차

1. [개요](#1-개요)
2. [보스봇 종류 (난이도별)](#2-보스봇-종류-난이도별)
3. [룰베이스 봇 (하/중 난이도)](#3-룰베이스-봇-하중-난이도)
4. [RL 봇 (상 난이도)](#4-rl-봇-상-난이도)
5. [학습 인프라 (GCP + GCS)](#5-학습-인프라-gcp--gcs)
6. [품질 봇 필터링](#6-품질-봇-필터링)
7. [비용 계획](#7-비용-계획)
8. [운영 가이드](#8-운영-가이드)

---

## 1. 개요

보스전은 유저 봇이 AI 보스와 1:4 배틀을 벌이는 특수 게임 모드다. 보스는 세 가지 난이도(하/중/상)로 운영되며, **상 난이도 보스는 유저들이 올린 봇 코드를 학습 데이터로 삼아 점점 강해진다.**

### 핵심 설계 원칙

- **하/중**: 룰베이스 — 즉시 배포, 코드로 동작 제어
- **상**: RL(DQN) — GCS에 저장된 가중치로 동작, 별도 학습 VM에서 주기 학습
- **학습 → 서빙 분리**: 서빙 VM(e2-medium)은 추론만 담당, 학습은 별도 VM에서

---

## 2. 보스봇 종류 (난이도별)

| 난이도 | 클래스 | 파일 | 전략 |
|--------|--------|------|------|
| 하 | `RuleBossEasyBot` | `bots/rule_boss_bot.py` | 채굴 중심, 에너지 확보 후 추적 |
| 중 | `RuleBossMediumBot` | `bots/rule_boss_bot.py` | 공격 최우선, 저에너지 적 타겟 |
| 상 | `RLBossBot` (numpy) | `bots/rl_boss_bot.py` | DQN, GCS 가중치 |
| 상 (학습용) | `RLBossBotTorch` | `bots/rl_boss_bot_torch.py` | PyTorch DQN, GPU 지원 |

---

## 3. 룰베이스 봇 (하/중 난이도)

### 게임 설정 기준값

```python
initial_energy = 250   max_energy = 1000
attack_damage  = 25    shield: damage // 2 (12)  # config.shield_reduction=1.0은 미사용(버그)
attack_cost    = 5     kill → 공격자가 피해자 잔여 에너지 흡수 + kills×30점(최종)
mine_normal    = +5점 +10에너지    mine_rare = +20점 +25에너지
guard_bonus    = +10점 (실드 중 피격 시)
```

### 하 난이도 우선순위

```
자기장 탈출/예측
→ 시야 내 적 위치 갱신
→ 인접 적: 라스트힛(HP≤25) → 에너지≥60이면 공격 → flee
→ 긴급 채굴 (에너지 < 50)
→ 적 추적 (에너지 ≥ 100, zone 내 목적지)
→ 광물 채굴 (발밑 → 시야 → 기억)
→ zone 중앙 탐색
```

### 중 난이도 우선순위

```
자기장 탈출/예측
→ 인접 적: 라스트힛 → 에너지≥40이면 저에너지 적 우선 공격 → flee
→ 긴급 채굴 (에너지 < 40)
→ 시야 내 저에너지 적 추적 (에너지 ≥ 70, zone 검증)
→ 광물 채굴
→ 기억 속 적 추적 (에너지 ≥ 70, lost×20 패널티)
→ zone 중앙 확보
```

### 주요 개선 사항 (2026-05-15)

| 이전 | 개선 |
|------|------|
| 에너지 부족 시 SHIELD 고정 (데드락) | `flee()` 로 교체, zone 탈출 위험 시 중앙 방향 |
| 라스트힛 로직 없음 | 인접 적 HP ≤ 25이면 에너지 임계값 무관 공격 |
| zone 하드코딩 (50,50) | `zone_bounds` 중앙값 동적 계산 |
| grid 5×5 5회 중복 순회 | `_scan_grid()` 1회 통합 |
| stale 광물 기억 | 80틱 초과분 자동 만료 |
| zone 밖 적 추적 | zone 검증 후 무시 |
| raw string 비교 | `CellType`/`Action` enum 상수 사용 |
| Medium: emergency mine이 인접 전투 차단 | 인접 전투 판단 우선화 |

### 공통 유틸 함수

```python
_scan_grid()          # 5×5 1회 순회 → (발밑, 인접적, 시야적, 최적광물)
_needs_zone_retreat() # zone 탈출 + 예측 이동 (Phase2+ 경계 2칸 버퍼)
_safe_flee()          # zone 안으로 이탈, 불가 시 중앙 방향
_try_lastbit()        # 인접 적 HP ≤ 25이면 공격 인덱스 반환
_pick_attack()        # 인접 적 중 저에너지 우선 공격
_update_mineral_mem() # 광물 기억 + 80틱 stale 만료
_emergency_mine()     # 에너지 위기 시 최단 광물 이동, 없으면 STAY
```

---

## 4. RL 봇 (상 난이도)

### 아키텍처

```
상태 벡터 (N_FEATURES = 43)
  시야 25개: 5×5 grid CELL_ENCODING
  스칼라 18개:
    energy/1000, score/500, tick/200
    zone 4방향 거리 (left/right/top/bottom_margin / 50)  ← v2 추가
    dist_zone_center/100
    enemy_in_adj, enemy_in_vision
    nearest_enemy_energy/250   ← v2 추가
    mineral_in_adj, mineral_rare_in_adj, mineral_in_vision
    danger_zone, rank_norm
    kills_norm                 ← v2 추가
    bias (1.0)

네트워크 (numpy, 서빙용): 43 → 64 → 19
네트워크 (PyTorch, 학습용): 43 → 256 → 128 → 19

알고리즘: Double DQN
optimizer: Adam (lr=0.0005)
gamma: 0.95, batch: 128 (Torch) / 64 (numpy)
```

### 보상 설계

| 이벤트 | 보상 |
|--------|------|
| 킬 (kill_delta) | +50 × delta |
| 채굴 (score_delta) | +0.3 / 점 |
| 에너지 회복 | +0.02 / 단위 |
| 에너지 위험 (≤40) | -3.0 |
| 에너지 낮음 (≤80) | -1.0 |
| zone 밖 | -4.0 |
| 유효 이동 (zone 내) | +0.1 |
| STAY | -0.4 |
| 헛 SHIELD (적 미인접) | -0.5 |
| 에피소드 종료 1위 | +50 |
| 에피소드 종료 2위 | +15 |
| 에피소드 종료 3위 | -5 |
| 에피소드 종료 4위+ | -20 × (rank-3) |

### 하드코딩 규칙 (최소화)

```python
# 1. 자기장 탈출 (phase2+ 경계 2칸 버퍼 포함)
if in_danger or near_boundary:
    → zone 중앙으로 이동

# 2. 에너지 극위기 (≤30) — SHIELD 대신
if adj_enemy:
    → 라스트힛 시도 → 불가 시 flee
else:
    → 가장 가까운 광물로 이동 → 없으면 STAY

# 3. 발밑 광물
→ 라스트힛 기회 없으면 MINE

# 4. 나머지 → DQN (epsilon-greedy)
```

### 주요 개선 사항 (v2, 2026-05-15)

| 이전 | 개선 |
|------|------|
| N_FEATURES=38, zone_margin 1개 | N_FEATURES=43, zone 4방향+적에너지+kills |
| energy≤30 → 무조건 SHIELD | 라스트힛/flee 로직 |
| guided_action zone 밖 광물 추적 | zone 검증 추가 |
| stale 광물 기억 | 80틱 만료 |
| kill +20 | kill +50 |
| 헛 SHIELD 패널티 없음 | -0.5 |
| 종료 학습 4회 | 2회 (분산 감소) |
| 체크포인트 version=2 | version=3 (자동 초기화) |

---

## 5. 학습 인프라 (GCP + GCS)

### 전체 데이터 흐름

```
[서빙 VM - e2-medium]           [GCS 버킷]
  유저 봇 업로드 → SQLite DB
  새벽 2시 cron                   quality_bots.json  ←── export_quality_bots.py
  export_quality_bots.py ────────────────────────────────┘
  30초 폴링 ──────────────────── trained_weights.pt / .json
                                  training_meta.json
                                  trained_bot_history.json

[GCP Cloud Scheduler]
  매일 새벽 2시 → Training VM 시작

[Training VM - c2-std-8 Spot]
  startup script
    → quality_bots.json 다운로드
    → 신규 봇 < 3개 AND < 7일? → self-stop (비용 0)
    → train_boss_parallel.py 실행
    → weights + meta → GCS push
    → self-stop
```

### 파일 구조 (GCS 버킷 내)

```
gs://your-bucket/boss/
  trained_weights.json      # numpy RLBossBot 가중치 (서빙용)
  trained_weights_torch.pt  # PyTorch RLBossBotTorch 가중치 (학습용)
  training_meta.json        # 학습 통계 (generation, win_rate 등)
  quality_bots.json         # 품질 봇 목록 (daily export)
  trained_bot_history.json  # 최근 3세션 학습 봇 ID 이력
```

### 환경변수

```bash
BOSS_WEIGHTS_GCS_URI=gs://your-bucket/boss/trained_weights.json
```

이 URI의 디렉토리(`gs://your-bucket/boss/`)가 나머지 파일들의 기준 경로가 된다.

### 서빙 VM 핫리로드

GCS generation 번호 변경을 30초 폴링으로 감지 → `RLBossBot` 싱글톤 재로드.  
게임 요청 경로에 끼지 않으므로 유저 체감 지연 없음.

---

## 6. 품질 봇 필터링

### 기준

```python
len(code.strip()) >= 300    # trivial/덤핑 봇 제거
games_played >= 10          # 충분한 검증 (5봇 게임 랜덤 승률=20% 기준선)
win_rate >= 35%             # 랜덤 기준선보다 유의미하게 높음
  OR top3_rate >= 50%       # 상위권 진입률 기준

rating DESC 정렬 → 상위 20개 선택
```

### 왜 20%가 아닌 35%인가

5봇 게임에서 완전 랜덤 봇의 기대 승률은 1/5 = 20%.  
20% 기준은 랜덤과 구분이 불가능하므로 35%로 설정.  
3판 플레이 후 1승(33%)만으로는 기준에 미달 → `games_played >= 10` 이 추가 방어선.

### 비용 폭주 방지 (3중 상한)

```python
MAX_BOTS_PER_SESSION = 20   # 품질 봇이 100개여도 rating 상위 20개만 학습
MAX_EPISODES_TOTAL  = 600   # 세션 총 에피소드 상한
MAX_RUNTIME_HOURS   = 7     # 초과 시 worker 강제 종료
```

악의적 봇 덤핑 → 품질 필터 탈락 or 상위 20개 안에 못 들어감 → 비용 피해 없음.

### 중복 학습 방지

최근 3 세션 학습 봇 ID를 `trained_bot_history.json`에 기록.  
이미 학습한 봇은 다음 세션에서 제외 → 봇 다양성 확보.

---

## 7. 비용 계획

### 환경변수 기준 (1 USD ≈ 1,380원, Spot 인스턴스)

| 구성 | 사양 | 시간당 | 4주 (항상 ON) |
|------|------|--------|--------------|
| 서빙 VM | e2-medium (2vCPU) | $0.034 | ~3.2만원 |
| 학습 VM 1~2주 | c2-std-4 Spot (4코어) | $0.042 | 필요시만 |
| 학습 VM 3~4주 | c2-std-8 Spot (8코어) | $0.084 | 필요시만 |

### 스마트 스케줄링 효과

VM은 학습 조건 충족 시에만 시작, 학습 완료 후 즉시 self-stop.

| 시나리오 | 예상 학습 빈도 | VM 운영 시간/4주 | 비용 |
|----------|---------------|----------------|------|
| 활성 유저 많음 | 주 4~5회 | ~30h | ~0.9만원 (c2-std-4) |
| 활성 유저 보통 | 주 2~3회 | ~18h | ~0.5만원 |
| 신규 봇 거의 없음 | 7일마다 강제 | ~4h | ~0.1만원 |

**4주 총 예상 비용**: 서빙 3.2만원 + 학습 0.5~1만원 = **약 4~5만원 (예산 70만원의 7%)**

---

## 8. 운영 가이드

### 서빙 VM cron 설정

```bash
# crontab -e
0 2 * * * cd /path/to/BattleRoyale && python3 scripts/export_quality_bots.py >> /var/log/export_bots.log 2>&1
```

### GCP Cloud Scheduler 설정

```bash
gcloud scheduler jobs create http boss-train-trigger \
  --schedule="0 2 * * *" \
  --uri="https://compute.googleapis.com/compute/v1/projects/PROJECT/zones/ZONE/instances/INSTANCE/start" \
  --message-body="" \
  --oauth-service-account-email=SA@PROJECT.iam.gserviceaccount.com \
  --location=asia-northeast3
```

### 학습 VM 초기 생성 (1~2주차)

```bash
gcloud compute instances create boss-trainer-v1 \
  --zone=asia-northeast3-a \
  --machine-type=c2-standard-4 \
  --provisioning-model=SPOT \
  --maintenance-policy=TERMINATE \
  --boot-disk-size=30GB \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --metadata=startup-script='#!/bin/bash
    cd /home/user/loa-main/backend/BattleRoyale
    python3 train_boss_parallel.py --workers 3 --episodes-per-worker 100
  '
```

### 학습 VM 업그레이드 (3~4주차)

```bash
# 기존 VM 중지 후 타입 변경
gcloud compute instances stop boss-trainer-v1 --zone=asia-northeast3-a
gcloud compute instances set-machine-type boss-trainer-v1 \
  --zone=asia-northeast3-a --machine-type=c2-standard-8
gcloud compute instances start boss-trainer-v1 --zone=asia-northeast3-a
```

### 수동 학습 실행 (디버그)

```bash
# 신규 봇 조건 무시하고 강제 실행
python3 train_boss_parallel.py --workers 3 --episodes-per-worker 50 \
  --force --no-self-stop --no-gcs

# GCS 연동 + VM 자동 종료 포함 실제 실행
python3 train_boss_parallel.py --workers 6 --episodes-per-worker 100
```

### 품질 봇 수동 내보내기

```bash
python3 scripts/export_quality_bots.py
```

### 학습 상태 확인

```bash
# GCS에서 메타 확인
gsutil cat gs://your-bucket/boss/training_meta.json | python3 -m json.tool

# 예시 출력
{
  "updated_at": "2026-05-15T03:42:00+00:00",
  "generation": 1250,
  "total_episodes": 1250,
  "epsilon": 0.312,
  "win_rate": 0.58,
  "avg_rank": 1.9,
  "trained_bots": 12
}
```

### 서빙 VM 핫리로드 확인

서버 로그에서 아래 메시지 확인:
```
INFO gcs_weights: Weights downloaded: gs://... → /tmp/boss_weights.json
INFO game_session: RLBossBot 싱글톤 재로드 (generation 변경)
```

---

## 파일 목록

```
BattleRoyale/
├── bots/
│   ├── rule_boss_bot.py          # 하/중 룰베이스 봇
│   ├── rl_boss_bot.py            # 상 RL봇 (numpy, 서빙용)
│   └── rl_boss_bot_torch.py      # 상 RL봇 (PyTorch, 학습용)
├── scripts/
│   └── export_quality_bots.py    # 품질 봇 GCS 내보내기 (서빙 VM cron)
├── train_boss_bot.py             # 단일 프로세스 학습 (레거시)
├── train_boss_parallel.py        # 병렬 학습 + 비용 제어 + self-stop
├── gcs_weights.py                # GCS 업/다운로드 유틸
└── BOSS_BOT.md                   # 이 문서
```

# 보스봇 설계 문서

> AI Arena 보스전 시스템의 전체 설계, 구현 세부사항, 운영 가이드.  
> 최종 수정: 2026-05-15

---

## 목차

1. [개요](#1-개요)
2. [보스전 게임 구성](#2-보스전-게임-구성)
3. [보스봇 종류 (난이도별)](#3-보스봇-종류-난이도별)
4. [룰베이스 봇 (하/중 난이도)](#4-룰베이스-봇-하중-난이도)
5. [RL 봇 (상 난이도)](#5-rl-봇-상-난이도)
6. [학습 인프라 (GCP + GCS)](#6-학습-인프라-gcp--gcs)
7. [품질 봇 필터링](#7-품질-봇-필터링)
8. [비용 계획](#8-비용-계획)
9. [운영 가이드](#9-운영-가이드)
10. [파일 목록](#10-파일-목록)

---

## 1. 개요

보스전은 **유저 봇 1~3개가 AI 보스 1개에 도전하는 특수 게임 모드**다.  
보스는 세 가지 난이도(하/중/상)로 운영된다.

**핵심 목표**: 상 난이도 보스는 유저들이 올린 봇 코드를 학습해 점점 강해진다.  
유저는 혼자 도전하거나 봇 여러 개로 팀을 꾸려 강한 보스를 전략으로 이기는 것이 목표다.

### 설계 원칙

| 원칙 | 내용 |
|------|------|
| 보스 너프 금지 | 보스는 항상 강하게. 유저가 전략으로 극복 |
| 학습·서빙 분리 | 서빙 VM은 추론만, 학습은 별도 GCP VM |
| 전역 설정 불변 | 보스전 config는 지역 오버라이드 (`boss_battle_config()`) |
| 비용 통제 | 학습 VM은 조건 충족 시에만 가동, 자동 종료 |

---

## 2. 보스전 게임 구성

### 배틀로얄 vs 보스전 비교

| 항목 | 배틀로얄 | 보스전 |
|------|---------|--------|
| 봇 수 | 4~100 | 유저봇 1~3 + 보스 1 |
| max_ticks | 200 | **400** |
| 광물 수 | 300 | **400** |
| 희귀 광물 군락 | 5 | **6** |
| 자유 탐색 구간 | 0~75틱 | **0~150틱** |
| Zone 수축 시작 | 76틱 (4틱/칸) | **151틱 (8틱/칸)** |
| Zone 가속 수축 | 151틱 (2틱/칸) | **321틱 (5틱/칸)** |
| 최종 안전구역 | ≈ 15×15 | **≈ 27×27** |

> 보스전은 배틀로얄보다 게임 시간이 길고 자원이 풍부해 채굴·전략 플레이 비중이 높다.  
> 보스는 별도 핸디캡 없이 동일 조건으로 참가한다.

### 승리 조건

- 게임 종료 시 **어느 유저봇이라도 보스보다 높은 최종 점수**이면 유저 승리
- 보스를 처치하면 즉시 카운트 (킬 + 에너지 흡수 + kills×30점 최종 반영)

### API 요청 형식

```json
// 봇 1개로 단독 도전
{
  "mode": "boss",
  "difficulty": "상",
  "bots": [
    { "bot_id": "my_bot", "code": "def action(state): ..." }
  ]
}

// 봇 3개로 팀 도전 (최대)
{
  "mode": "boss",
  "difficulty": "상",
  "bots": [
    { "bot_id": "bot_attack",  "code": "..." },
    { "bot_id": "bot_miner",   "code": "..." },
    { "bot_id": "bot_support", "code": "..." }
  ]
}
```

### `boss_battle_config()` 상세

`src/arena/config.py`에 정의된 함수로, `DEFAULT_CONFIG`를 `dataclasses.replace()`로 오버라이드한다.  
전역 설정(`DEFAULT_CONFIG`)은 변경되지 않으므로 배틀로얄에 영향 없음.

```python
# config.py
def boss_battle_config() -> GameConfig:
    return dataclasses.replace(
        DEFAULT_CONFIG,
        max_ticks=400,
        map=dataclasses.replace(
            DEFAULT_CONFIG.map,
            initial_mineral_count=400,   # 300 → 400
            num_rare_mineral_clusters=6, # 5 → 6
        ),
        zone=dataclasses.replace(
            DEFAULT_CONFIG.zone,
            phase1_end=150,              # 75 → 150 (자유 탐색 2배)
            phase2_end=320,              # 150 → 320 (느린 수축 구간)
            phase2_shrink_interval=8,    # 4 → 8
            phase3_shrink_interval=5,    # 2 → 5
        ),
    )
```

Zone 수축 계산:
- Phase 2 수축 횟수: (320-150) ÷ 8 = **21회**
- Phase 3 수축 횟수: (400-320) ÷ 5 = **16회**
- 총 37회 수축 → 최종 안전구역 반경 **13타일 (27×27)**

---

## 3. 보스봇 종류 (난이도별)

| 난이도 | 클래스 | 파일 | 특성 |
|--------|--------|------|------|
| 하 | `RuleBossEasyBot` | `bots/rule_boss_bot.py` | 채굴 중심, 에너지 확보 후 추적 |
| 중 | `RuleBossMediumBot` | `bots/rule_boss_bot.py` | 공격 최우선, 저에너지 적 우선 타겟 |
| 상 (서빙) | `RLBossBot` | `bots/rl_boss_bot.py` | numpy DQN, GCS 가중치 실시간 반영 |
| 상 (학습) | `RLBossBotTorch` | `bots/rl_boss_bot_torch.py` | PyTorch DQN, GPU 지원, 병렬 학습 |

---

## 4. 룰베이스 봇 (하/중 난이도)

### 게임 수치 기준

```
초기 에너지: 250   최대 에너지: 1000
공격 데미지: 25    실드: damage//2 (12) — config.shield_reduction=1.0 미사용(불일치 버그)
공격 비용: 5       킬 → 공격자 피해자 잔여 에너지 흡수 + kills×30점 (최종)
채굴(일반): +5점 +10에너지    채굴(희귀): +20점 +25에너지
가드 보너스: +10점 (실드 중 피격)
```

### 하 난이도 의사결정 순서

```
1. 자기장 탈출 / 예측 이동 (Phase2+ 경계 2칸 버퍼)
2. 시야 내 적 위치 갱신
3. 인접 적 처리: 라스트힛(HP≤25) → 에너지≥60 공격 → flee
4. 긴급 채굴 (에너지 < 50)
5. 적 추적 (에너지 ≥ 100, zone 내 목적지 검증)
6. 광물 채굴: 발밑 → 시야 → 기억(80틱 만료)
7. zone 중앙 탐색
```

### 중 난이도 의사결정 순서

```
1. 자기장 탈출 / 예측 이동
2. 인접 적 처리: 라스트힛 → 에너지≥40 저에너지 적 우선 공격 → flee
3. 긴급 채굴 (에너지 < 40)
4. 시야 내 저에너지 적 추적 (에너지 ≥ 70, zone 검증)
5. 발밑 광물 채굴
6. 기억 속 적 추적 (lost×20 패널티로 오래된 위치 신뢰도 감소)
7. zone 중앙 확보
```

### 주요 개선 사항 (2026-05-15)

| 이전 문제 | 수정 내용 |
|-----------|-----------|
| 에너지 부족 + 인접 적 → SHIELD 반복 (데드락) | `flee()` 로 교체, zone 탈출 위험 시 중앙 방향 |
| 라스트힛 로직 없음 | 인접 적 HP ≤ 25이면 에너지 임계값 무관 즉시 공격 |
| zone 중앙 하드코딩 (50, 50) | `zone_bounds` 기반 동적 중앙 계산 |
| grid 5×5를 5회 중복 순회 | `_scan_grid()` 1회 통합 |
| stale 광물 기억 (만료 없음) | 80틱 초과분 자동 만료 |
| zone 밖 적 추적 | zone 검증 후 무시 |
| raw string 직접 비교 | `CellType` / `Action` enum 상수 사용 |
| Medium: emergency mine이 인접 전투 차단 | 인접 전투 판단(라스트힛/flee)을 emergency보다 우선화 |
| 허수아비 SHIELD (적 없을 때도 실드) | 인접 적 없는 SHIELD 차단, 마지막 수단만 허용 |

### 공통 유틸 (`bots/rule_boss_bot.py` 모듈 레벨)

```python
_scan_grid()          # 5×5 1회 순회 → (발밑셀, 인접적, 시야적, 최적광물 상대좌표)
_needs_zone_retreat() # zone 밖 OR Phase2+ 경계 2칸 이내 → True
_safe_flee()          # 적 반대 방향 이동, zone 탈출 위험 시 중앙 방향으로 대체
_try_lastbit()        # 인접 적 HP ≤ 25 + 내 에너지 ≥ 5 → 공격 action 반환
_pick_attack()        # 인접 적 중 저에너지 우선 (other_bots 에너지 정보 활용)
_update_mineral_mem() # 시야 내 광물 갱신 + 80틱 stale 만료
_emergency_mine()     # 에너지 위기: 최단 광물 방향 이동, 없으면 STAY
_ADJ_MAP              # 모듈 레벨 캐시 (매 틱 dict 생성 방지)
```

---

## 5. RL 봇 (상 난이도)

### 상태 벡터 (N_FEATURES = 43)

```
시야 25개: 5×5 grid 각 셀을 CELL_ENCODING으로 연속값 변환
  empty=0.0, mineral=0.5, mineral_rare=1.0, ME=0.2, bot_enemy=-1.0

스칼라 18개:
  energy / 1000.0          에너지 (최대치 기준 정규화)
  score / 500.0            현재 점수
  tick / 200               경과 틱 비율
  left_margin / 50         zone 좌측까지 거리   ← v2 추가 (방향별 4개)
  right_margin / 50        zone 우측까지 거리
  top_margin / 50          zone 상단까지 거리
  bottom_margin / 50       zone 하단까지 거리
  dist_zone_center / 100   zone 중앙까지 거리
  enemy_in_adj             인접 8칸 내 적 여부 (0/1)
  enemy_in_vision          시야 내 적 여부 (0/1)
  nearest_enemy_energy/250 가장 가까운 적 에너지  ← v2 추가
  mineral_in_adj           인접 광물 여부 (0/1)
  mineral_rare_in_adj      인접 희귀광물 여부 (0/1)
  mineral_in_vision        시야 내 광물 여부 (0/1)
  danger_zone              zone 밖이면 1.0
  rank_norm                리더보드 순위 정규화
  kills_norm               킬 수 정규화 (kills/5)  ← v2 추가
  1.0                      bias
```

### 네트워크 구조

```
서빙용 (numpy, rl_boss_bot.py):  43 → 64 → 19
학습용 (PyTorch, rl_boss_bot_torch.py): 43 → 256 → 128 → 19
```

| 설정 | 값 |
|------|-----|
| 알고리즘 | Double DQN |
| 옵티마이저 | Adam (lr=0.0005) |
| 감쇠율 (γ) | 0.95 |
| 배치 크기 | 128 (Torch) / 64 (numpy) |
| 리플레이 버퍼 | 50,000 (Torch) / 10,000 (numpy) |
| Target 업데이트 | 200 스텝마다 |
| ε 시작/최솟값 | 1.0 → 0.05 (에피소드당 ×0.992) |

### 보상 설계

| 이벤트 | 보상 | 이유 |
|--------|------|------|
| 킬 | **+50** × kill_delta | 킬이 가장 중요한 전략적 행동 |
| 채굴 점수 | +0.3 / 점 | 채굴 전략 장려 |
| 에너지 회복 | +0.02 / 단위 | 생존 유지 인센티브 |
| 에너지 위험 (≤40) | -3.0 | 위기 회피 학습 |
| 에너지 낮음 (≤80) | -1.0 | 선제 채굴 유도 |
| zone 밖 | -4.0 | 자기장 회피 강제 |
| 유효 이동 (zone 내) | +0.1 | 탐색 장려 |
| STAY | -0.4 | 정체 억제 |
| 헛 SHIELD (적 미인접) | **-0.5** | ← v2 추가: SHIELD 남용 방지 |
| 에피소드 1위 | +50 |  |
| 에피소드 2위 | +15 |  |
| 에피소드 3위 | -5 |  |
| 에피소드 4위+ | -20 × (rank-3) |  |

### 하드코딩 규칙 (최소한만)

```python
# 1. 자기장 탈출 / 예측 이동 (Phase2+ 경계 2칸 버퍼)
if outside_zone or near_boundary_in_phase2:
    → zone 중앙으로 이동

# 2. 에너지 극위기 (≤ 30) — SHIELD 대신 전투·채굴 우선
if adj_enemy_exists:
    → 라스트힛 가능하면 공격
    → 불가 시 flee (zone 안으로)
else:
    → 가장 가까운 광물로 이동, 없으면 STAY

# 3. 발밑 광물 + 라스트힛 기회 없으면 → MINE

# 4. 나머지 모든 행동 → DQN (epsilon-greedy + guided exploration)
```

### 주요 개선 사항 (v2, 2026-05-15)

| 이전 | 개선 |
|------|------|
| N_FEATURES=38, zone_margin 1개 스칼라 | N_FEATURES=43, zone 4방향 거리 + 적 에너지 + kills |
| energy≤30 → 무조건 SHIELD | 라스트힛/flee 우선, SHIELD는 최후 수단 |
| emergency mine이 인접 전투 차단 (순서 버그) | 인접 전투 판단을 emergency보다 먼저 |
| guided_action이 zone 밖 광물·적 추적 | zone 검증 추가 |
| stale 광물 기억 (무한 지속) | 80틱 만료 |
| kill 보상 +20 | **+50** |
| 헛 SHIELD 패널티 없음 | **-0.5** 추가 |
| 에피소드 종료 학습 4회 반복 | 2회 (과적합·분산 감소) |
| 체크포인트 version=2 | version=3 (N_FEATURES 변경으로 구버전 자동 초기화) |

---

## 6. 학습 인프라 (GCP + GCS)

### 전체 데이터 흐름

```
[서빙 VM - e2-medium]
  유저 봇 업로드 → SQLite DB (bots, bot_ratings 테이블)
  새벽 2시 cron → export_quality_bots.py 실행
      └─ 품질 봇 필터링 → GCS: quality_bots.json

  GCS 30초 폴링 → 새 generation 감지 → RLBossBot 싱글톤 핫리로드

[GCP Cloud Scheduler - 무료]
  매일 새벽 2시 → Training VM 시작 명령

[Training VM - c2-std-4/8 Spot]
  startup script:
    1. quality_bots.json 다운로드
    2. 신규 봇 수 확인
       - 신규 봇 < 3개 AND 마지막 학습 < 7일 → 즉시 self-stop (비용 ≈ 0)
       - 조건 충족 → 학습 시작
    3. N workers 병렬 에피소드 실행
    4. trained_weights_torch.pt + training_meta.json → GCS push
    5. trained_bot_history.json 갱신
    6. VM self-stop
```

### GCS 버킷 파일 구조

```
gs://your-bucket/boss/
  trained_weights.json       서빙용 numpy 가중치
  trained_weights_torch.pt   학습용 PyTorch 가중치
  training_meta.json         학습 통계 (generation, win_rate, epsilon 등)
  quality_bots.json          품질 봇 목록 (서빙 VM이 매일 갱신)
  trained_bot_history.json   최근 3세션 학습 봇 ID 이력
```

### 환경변수

```bash
BOSS_WEIGHTS_GCS_URI=gs://your-bucket/boss/trained_weights.json
# 이 URI 기준 같은 디렉토리에 위 파일들이 함께 저장됨
```

### training_meta.json 예시

```json
{
  "updated_at": "2026-05-15T03:42:00+00:00",
  "generation": 1250,
  "total_episodes": 1250,
  "total_steps": 85000,
  "epsilon": 0.312,
  "win_rate": 0.58,
  "avg_rank": 1.9,
  "avg_score": 412.3,
  "trained_bots": 12,
  "session_episodes": 150,
  "runtime_hours": 5.2
}
```

---

## 7. 품질 봇 필터링

### 필터 기준 (`scripts/export_quality_bots.py`)

```python
# 통과 조건
len(code.strip()) >= 300     # trivial/덤핑 봇 제거
games_played >= 10           # 충분한 검증 (랜덤 기대 승률 20% 극복하려면 최소 10판)
win_rate >= 35%              # 랜덤(20%) 대비 유의미하게 높음
  OR top3_rate >= 50%        # 또는 상위권 진입률 50% 이상

# 선택
rating DESC 정렬 → 상위 20개만 추출
```

### 왜 35% / 10판인가

5봇 게임에서 완전 랜덤봇의 기대 승률은 1/5 = **20%**. 3판만 하면 1승(33%)으로 20%를 넘기므로 `games_played >= 10`이 필수 방어선이다. 35%는 5봇 기준 "평균 이상" 봇을 선별하는 실용적 임계값이다.

### 비용 폭주 방지 (3중 상한)

| 상한 | 값 | 효과 |
|------|-----|------|
| `MAX_BOTS_PER_SESSION` | 20 | 품질 봇 100개여도 rating 상위 20개만 선택 |
| `MAX_EPISODES_TOTAL` | 600 | 세션 총 에피소드 상한 |
| `MAX_RUNTIME_HOURS` | 7 | 초과 시 worker 강제 종료 후 저장 |

악의적 봇 다수 업로드(덤핑) → 품질 필터 탈락 or 상위 20개 안에 못 들어감 → 학습량·비용 변화 없음.

### 중복 학습 방지

`trained_bot_history.json`에 최근 3 세션 봇 ID를 기록한다.  
이미 학습한 봇은 다음 세션에서 제외되어 봇 다양성을 확보한다.

---

## 8. 비용 계획

### VM 단가 (Spot 인스턴스, 1 USD ≈ 1,380원)

| VM | 사양 | 시간당 |
|----|------|--------|
| 서빙 VM | e2-medium (2vCPU, 4GB) | $0.034 |
| 학습 VM 1~2주 | c2-standard-4 Spot (4코어) | $0.042 |
| 학습 VM 3~4주 | c2-standard-8 Spot (8코어) | $0.084 |

### 스마트 스케줄링 효과 (4주 기준)

| 시나리오 | 빈도 | VM 운영 시간 | 학습 비용 |
|----------|------|------------|---------|
| 활성 유저 많음 | 주 4~5회 | ~30h | ~0.9만원 |
| 활성 유저 보통 | 주 2~3회 | ~18h | ~0.5만원 |
| 신규 봇 거의 없음 | 7일마다 강제 | ~4h | ~0.1만원 |

**4주 총 예상 비용**: 서빙 3.2만원 + 학습 0.5~1만원 = **약 4~5만원 (예산 70만원의 7%)**

> 신규 봇이 없는 날 VM이 1분 만에 self-stop하는 비용 ≈ $0.00014 (사실상 0)

---

## 9. 운영 가이드

### 서빙 VM cron 등록

```bash
# 품질 봇 매일 새벽 2시 자동 내보내기
crontab -e
# 추가:
0 2 * * * cd /path/to/BattleRoyale && python3 scripts/export_quality_bots.py >> /var/log/export_bots.log 2>&1
```

### GCP Cloud Scheduler 설정

```bash
gcloud scheduler jobs create http boss-train-trigger \
  --schedule="0 2 * * *" \
  --time-zone="Asia/Seoul" \
  --uri="https://compute.googleapis.com/compute/v1/projects/PROJECT/zones/ZONE/instances/INSTANCE/start" \
  --message-body="" \
  --oauth-service-account-email=SA@PROJECT.iam.gserviceaccount.com \
  --location=asia-northeast3
```

### 학습 VM 생성 (1~2주차, c2-std-4 Spot)

```bash
gcloud compute instances create boss-trainer \
  --zone=asia-northeast3-a \
  --machine-type=c2-standard-4 \
  --provisioning-model=SPOT \
  --maintenance-policy=TERMINATE \
  --boot-disk-size=30GB \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --service-account=SA@PROJECT.iam.gserviceaccount.com \
  --metadata=startup-script='#!/bin/bash
    cd /home/user/loa-main/backend/BattleRoyale
    export BOSS_WEIGHTS_GCS_URI=gs://your-bucket/boss/trained_weights.json
    python3 train_boss_parallel.py --workers 3 --episodes-per-worker 100
  '
```

### 학습 VM 업그레이드 (3~4주차, c2-std-8 Spot)

```bash
gcloud compute instances stop boss-trainer --zone=asia-northeast3-a
gcloud compute instances set-machine-type boss-trainer \
  --zone=asia-northeast3-a --machine-type=c2-standard-8
gcloud compute instances start boss-trainer --zone=asia-northeast3-a
```

### 학습 CLI 옵션

```bash
# 기본 실행 (신규 봇 없으면 자동 종료)
python3 train_boss_parallel.py --workers 6 --episodes-per-worker 100

# 강제 학습 (디버그/수동)
python3 train_boss_parallel.py --workers 3 --episodes-per-worker 50 \
  --force --no-self-stop --no-gcs

# CPU 지정
python3 train_boss_parallel.py --device cpu --workers 4
```

### 품질 봇 수동 내보내기

```bash
python3 scripts/export_quality_bots.py
```

### 학습 상태 확인

```bash
# GCS 메타 확인
gsutil cat gs://your-bucket/boss/training_meta.json | python3 -m json.tool

# 서빙 VM 핫리로드 로그 확인
journalctl -u your-service --grep "RLBossBot" -f
```

### 보스전 동작 확인 (로컬 시뮬레이션)

```bash
python3 -c "
from src.arena.config import boss_battle_config
from src.arena.engine import GameEngine
from bots.herbivore import HerbivoreBot
from bots.rule_boss_bot import RuleBossMediumBot

cfg = boss_battle_config()
print(f'max_ticks={cfg.max_ticks}, 광물={cfg.map.initial_mineral_count}')

bots = [HerbivoreBot('user_1'), HerbivoreBot('user_2'), RuleBossMediumBot('boss')]
engine = GameEngine(bots, config=cfg, seed=42)
result = engine.run_full_game()
for r in result.rankings:
    print(f'{r[\"rank\"]}위: {r[\"id\"]} → {r[\"final_score\"]}점')
"
```

---

## 10. 파일 목록

```
BattleRoyale/
├── src/arena/
│   ├── config.py                     게임 설정 (DEFAULT_CONFIG + boss_battle_config())
│   ├── engine.py                     게임 엔진 (config 파라미터 수용)
│   └── server/
│       └── app.py                    API 서버 (보스전 config 주입, 유저봇 1~3개)
│
├── bots/
│   ├── rule_boss_bot.py              하/중 룰베이스 봇 (RuleBossEasyBot, RuleBossMediumBot)
│   ├── rl_boss_bot.py                상 RL봇 numpy (N_FEATURES=43, 서빙용)
│   └── rl_boss_bot_torch.py          상 RL봇 PyTorch (43→256→128→19, GPU 학습용)
│
├── scripts/
│   └── export_quality_bots.py        서빙 VM cron: 품질 봇 → GCS 내보내기
│
├── train_boss_bot.py                 단일 프로세스 학습 스크립트 (레거시)
├── train_boss_parallel.py            병렬 학습 (비용 상한 + 스마트 스케줄링 + self-stop)
├── gcs_weights.py                    GCS 업/다운로드 유틸 (upload_json, download_json 포함)
└── BOSS_BOT.md                       이 문서
```

### 주요 설정값 요약

| 파라미터 | 위치 | 값 |
|---------|------|-----|
| N_FEATURES | `rl_boss_bot.py` | 43 |
| 보스전 max_ticks | `config.py:boss_battle_config` | 400 |
| 보스전 최종 zone | `config.py:boss_battle_config` | ≈ 27×27 |
| 유저봇 최대 수 | `app.py:_BOSS_MAX_USER_BOTS` | 3 |
| 품질봇 최소 게임 수 | `scripts/export_quality_bots.py` | 10 |
| 품질봇 최소 승률 | `scripts/export_quality_bots.py` | 35% |
| 세션 최대 봇 수 | `train_boss_parallel.py` | 20 |
| 세션 최대 에피소드 | `train_boss_parallel.py` | 600 |
| 세션 최대 런타임 | `train_boss_parallel.py` | 7시간 |
| 광물 기억 만료 | `rl_boss_bot.py`, `rule_boss_bot.py` | 80틱 |

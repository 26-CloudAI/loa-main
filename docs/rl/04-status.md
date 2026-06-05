# 04. 현 상태 — gen_00011 학습 결과·한계·다음 단계

> [README](README.md) · [01-design](01-design.md) · [02-serving](02-serving.md) · [03-infrastructure](03-infrastructure.md) · **04-status**

본 문서는 *2026-06-05 현재 사실 그대로* 의 RL 학습 상태와 정직한 한계 평가, 그리고 다음 단계 후보를 정리한다.

---

## 1. 한눈에

| 항목 | 상태 |
|---|---|
| **인프라 (코드)** | ✅ 완성 — encoder/decoder/network/inference/league/past_opponent |
| **학습 환경** | ✅ 완성 — `BR2MiniEnv` 순수 Python sim |
| **학습 스크립트** | ✅ 완성 — `train_boss_br2.py` (DQN, 500 epi 실행 가능) |
| **초기 학습 (gen_00011)** | ✅ 완료 — 500 epi, GCS 업로드 OK |
| **학습 품질** | ⚠️ 부족 — win_rate20 = 0.00, avg_rank20 = 3.25 |
| **운영 wire (백엔드 통합)** | ✅ 검증 — RLBossBR2 단위 추론 통과 |
| **Godot e2e 검증** | 🚧 진행 중 — 사용자 집 PC 에서 진행 예정 |
| **Cloud Scheduler 자동화** | ❌ 미완성 — startup script 미작성, 현재 PAUSE |

---

## 2. gen_00011 학습 결과

### 2.1 학습 설정 (실측)

| 항목 | 값 |
|---|---|
| 에피소드 수 | 500 |
| device | CPU (단일 코어) |
| 시드 | 42 |
| 시나리오 mix | pfsp 70% / trio 25% / solo 5% |
| 보상 | RANK1=+150, RANK2(n≥3)=+30, RANK3+=-10, SOLO_LOSS=-20 |
| 총 학습 시간 | ≈ 40분 |
| 출력 | `gen_00011.npz` (223KB) — GCS + 로컬 동시 보관 |

### 2.2 정량 결과 (학습 종료 시점)

| 지표 | 값 | 해석 |
|---|---|---|
| `win_rate20` | **0.00** | 최근 20 에피소드 1위 0회 |
| `avg_rank20` | **3.25 / 4** | 평균 거의 꼴등 |
| `episode_reward` (마지막 ep) | ≈ -10 ~ -20 | 패율 90%+ 보스 |
| replay buffer size | 30k 가득 참 | 데이터 부족은 아님 |

### 2.3 정성 평가

- **wire 검증 목적은 달성** — 가중치 로드 → encode → forward → decode 체인 정상.
- **실력 면에선 룰 중급 폴백과 비슷하거나 약함** — 이 가중치를 운영에 배포하면 사용자는 "상" 매치에서 룰 중급과 비슷한 보스를 만나게 됨.
- 학습 곡선이 평탄 — 500 ep 로는 DQN 이 보상 sparse 환경에서 수렴 못 함.

### 2.4 진단 (가설)

1. **에피소드 수 부족** — DQN 은 보통 수천~수만 ep 필요. 500은 워밍업 수준.
2. **dense reward 부족** — `mini_env` score delta 만으론 보스의 *공격적 행동* 인센티브 약함.
3. **상대 풀 단순** — `Herbivore/MadDog/Camper` 위주, league 자체 봇 (past_opponent) 미적용.
4. **보상 음수 누적** — 패율 90%+ × (-10 ~ -20) 이 양의 시그널(+150 × ~0회) 압도.
5. **sim2real 갭** — sim 학습이 잘 됐어도 Godot 에서 약할 수 있는 별개 이슈.

---

## 3. 알려진 한계

### 3.1 학습 자체

| 한계 | 영향 | 우회 |
|---|---|---|
| sim2real 갭 | sim 강한 정책이 Godot 에서 약할 수 있음 | 운영 전 반드시 e2e 검증 |
| past_opponent (league) 미연동 | 자기복제 학습 불가 | TODO — `train_boss_br2.py` 의 `_build_opponents` 에 league 풀 추가 |
| solo 보상 -20 이 여전히 음 | n=2 시나리오의 학습 시그널 음수 누적 | 시나리오 비중 5% 로 제한 (현재 적용) |
| 학습 곡선 모니터링 자동 종료 없음 | 학습이 발산해도 끝까지 돔 | 향후: `early_stop_on_win_rate` 추가 |

### 3.2 인프라 자동화

| 한계 | 영향 | 우회 |
|---|---|---|
| Cloud Scheduler startup script 없음 | 학습 자동 트리거 불가 | 수동 SSH + 명령 실행 |
| 운영 백엔드 가중치 자동 동기화 없음 | 학습 후 가중치 수동 동기화 필요 | 수동 `gsutil cp` |
| 백엔드 hot-swap 없음 | 가중치 교체 시 재시작 필수 | 수동 재시작 (active_games=0 확인) |
| 학습 VM idle 비용 모니터링 없음 | Scheduler 가 VM 만 켜고 학습 안 함 발견 늦음 | GCP 청구 알림 설정 권장 |

### 3.3 운영 정책

| 한계 | 영향 |
|---|---|
| 가중치 파일 손상 시 랜덤 weight 로 폴백 (Medium 폴백 아님) | 사용자에게 명백히 약한 봇 노출 가능 |
| 학습 generation 번호 vs 운영 배포 버전 매핑 없음 | "운영은 지금 어느 학습 산출물?" 추적 어려움 |
| RL 보스가 실제로 룰 중급보다 강한지 자동 측정 없음 | 학습 결과를 정량 비교할 bench 미흡 |

---

## 4. 다음 단계 후보

영향 큰 순:

### 4.1 단기 (이번 주)

1. **e2e Godot 검증** (집 PC SSH 포트포워딩) — RL 추론이 실제 매치에서 끊김 없이 돌고 보스가 움직이는지.
2. **현 가중치를 메인 운영에 배포 여부 결정** — 약하더라도 "RL wire 가동" 의 신호로서 배포할지, 룰 폴백 유지할지.

### 4.2 중기 (1~2주)

3. **보상/시나리오 재튜닝 후 재학습 2000ep** — [01-design.md §9](01-design.md#9-향후-튜닝-후보) 의 1+2 동시 적용.
4. **bench 스크립트 추가** — RLBossBR2 vs RuleBossMediumBR2 N=50 매치 시뮬, win_rate/avg_rank 비교.
5. **past_opponent (league) 풀 학습 연동** — `train_boss_br2.py` 에서 league 체크포인트를 상대로 샘플.

### 4.3 장기 (1개월+)

6. **Cloud Scheduler 자동화 완성** — startup script + 운영 백엔드 부팅 hook.
7. **GPU 학습 노드 전환 (선택)** — 학습 시간 단축, batch ↑.
8. **PPO/A2C 등 알고리즘 비교** — DQN 한계 시 액터-크리틱 시도.

---

## 5. 메모리 인용

이 가이드는 다음 메모리 항목을 근거로 한다:

| 메모리 | 적용 부분 |
|---|---|
| `[[project-boss-bot]]` | 보스봇 전체 아키텍처, 난이도 정책 |
| `[[project-br2-boss-integration]]` | 본 세션 작업 진행, BR2 통합 결정 |
| `[[feedback-boss-claude-direct]]` | solo (2v1) 직접 학습 금지 → 시나리오 5% 제한 |
| `[[feedback-no-false-agreement]]` | 본 문서가 학습 약함을 솔직히 명시한 이유 |
| `[[feedback-model-usage]]` | RL 작업 = Opus, 본 문서 작성도 Opus 채택 |
| `[[feedback-git-push]]` | 본 문서 푸시는 사용자 명시 요청 후에만 |

---

## 6. 변경 이력

- **2026-06-05** — 초안. gen_00011 학습 직후 상태 기록.

추후 학습/배포 시 본 문서의 §2(결과) 와 §3.1(한계) 갱신 권장.

---

← [README](README.md)

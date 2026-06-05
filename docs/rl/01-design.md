# 01. 학습 설계 — 보상·시나리오·인코딩·하이퍼파라미터

> [README](README.md) · **01-design** · [02-serving](02-serving.md) · [03-infrastructure](03-infrastructure.md) · [04-status](04-status.md)

이 문서는 *RL 정책을 수정·재학습* 하려는 사람을 위한 설계 근거 정리다. 코드는 `backend/BattleRoyale2/scripts/train/train_boss_br2.py` 와 `backend/BattleRoyale2/sim/mini_env.py`.

---

## 1. 알고리즘 한눈에

| 항목 | 선택 | 이유 |
|---|---|---|
| 알고리즘 | **DQN** (Huber loss, target net) | 옛 BR1 보스 학습과 동일 구조 유지 → 코드 재사용 + 이전 노하우 흡수 |
| 네트워크 | MLP 80→256→128→20 (ReLU) | 입력 80차, 액션 20개. 깊은 conv 불필요 (이미지 아님) |
| 옵티마이저 | Adam (lr=5e-4) | DQN 권장 범위, BR1 운영 검증값 |
| Replay | deque (capacity=30k) uniform | PER 미적용 (구현 부담 vs gain trade-off) |
| Target sync | step % 1000 == 0 (hard copy) | soft τ 갱신 대비 안정 |
| ε-greedy | 1.0 → 0.05, 10k steps linear decay | 충분한 탐험 후 점진적 활용 |
| 학습 주기 | step % 4 == 0 (after warmup 2k) | 인터랙션 ≫ 학습 → 안정 |
| Batch | 128 | GPU 미사용 가정한 CPU 적정값 |
| γ | 0.99 | 매치 길이 360s, 보스 행동의 장기 효과 보존 |

> 위 값은 `scripts/train/train_boss_br2.py` 상수로 정의 — 수정은 한 곳만 바꾸면 전체 학습에 반영.

---

## 2. 상태 인코딩 (encode_state)

게임 상태 dict → **(80,) float32 벡터** 변환. 좌표는 보스 기준 상대(ego-centric), 거리는 `MAP_DIAG≈4243` 으로 정규화.

### 80차 레이아웃

| offset | 크기 | 의미 | 정규화 |
|---|---|---|---|
| 0..9   | 10 | self_core: hp_ratio, vel(2), atk/def/speed, 3 cd, potion+ranged 압축 | hp/MAX_HP, vel/MAX_SPEED |
| 10..12 | 3  | self_meta: pos_x/W, pos_y/H, time/duration | 0~1 |
| 13..30 | 18 | enemy_top3 × (dx, dy, dist_n, hp_ratio, guarding, has_ranged) | 거리 정렬 후 가까운 3 |
| 31..42 | 12 | node_top3 × (dx, dy, dist_n, rare) | 광물 자원 |
| 43..48 | 6  | chest_top2 × (dx, dy, dist_n) | 상자 |
| 49..54 | 6  | item_top2 × (dx, dy, dist_n) | 드롭 아이템 |
| 55..64 | 10 | projectile_top2 × (dx, dy, dist_n, vel_dx, vel_dy) | 투사체 |
| 65..73 | 9  | zone: active, rel_center(2), radius_n, dmg, phase, target(2), eta_n | zone 압박 |
| 74     | 1  | leaderboard_self = my_score / top_score | 0~1 |
| 75     | 1  | bias = 1.0 | 상수 |
| 76..79 | 4  | padding (확장 여지) | zeros |

### 왜 ego-centric polar 인가

- BR1 은 **43차 grid** 인코딩 — 맵 그리드를 격자로 자름 → 격자 크기에 정책이 종속.
- BR2 는 **연속 2D** 라 격자가 부자연스러움. 보스 기준 상대 좌표 + 정규화된 거리/방향이 자연스러움.
- 거리(`dist_n`) 와 방향(`dx, dy` 단위벡터화)을 **분리** 해서 학습 효율 ↑.

```
   적 위치 (절대)              보스 시점 (인코딩)
   ┌─────────┐                  ┌─────────┐
   │   E1    │                  │         │
   │       B │  ───►            │   B─►E1 │  dx=-0.7, dy=-0.5
   │  E2     │                  │       ⤡ │  dist_n=0.3
   └─────────┘                  └─────────┘
```

---

## 3. 보상 설계

> ⚠️ **핵심**: 옛 BR1 학습에서 검증된 메모리 1+2 조건을 BR2 에 1:1 매핑. 임의로 풀지 말 것.

### 3.1 Per-episode terminal reward (보스 시점)

```python
def _episode_terminal_reward(rank: int, n: int) -> float:
    if rank == 1:
        return +150.0            # 1위
    if n == 2:
        return -20.0             # solo (보스 vs 1상대) 패배 — 메모리 2 완화값
    if rank == 2:
        return +30.0             # 다대일 2위 (n>=3)
    return -10.0                 # 다대일 3위 이하
```

| 시나리오 | rank | reward | 비고 |
|---|---|---|---|
| 어디서든 1위 | 1 | **+150** | 강한 시그널 |
| n=2 (solo) 비-1위 | ≥2 | **−20** | 옛 -50 → -20 완화 (메모리 2) |
| n≥3 (PFSP/trio) 2위 | 2 | **+30** | "아깝게 짐" 보너스 |
| n≥3 비-2위 | ≥3 | **−10** | 약한 패널티 |

### 3.2 Per-tick dense reward

- `mini_env` 의 score delta (광물 채굴, 적 처치) × `REWARD_DENSE_WEIGHT=1.0`
- `REWARD_MINING_PER_TICK=0.15` 는 보조 (현 학습 루프에선 직접 적용 안 됨, 향후 raw_score 와 분리할 때 사용 예정)

### 3.3 왜 이 값인가 — 메모리 근거

옛 BR1 보스 학습 데이터:

| 시도 | 설정 | 결과 |
|---|---|---|
| baseline | solo 패배 -50, solo 비중 30% | **패율 93% × -50 = 폭주**. forgetting (이전 학습 시그널 덮어쓰임) |
| 완화 v1 | solo 패배 -20, solo 비중 30% | 약간 회복하지만 여전히 비대한 음의 시그널 |
| **완화 v2 (채택)** | solo 패배 -20, solo 비중 5% | 안정. 다대일에 집중하여 학습 |

→ BR2 에서 같은 패턴이 재발하는 것을 막기 위해 위 두 줄을 **시작점 고정값** 으로 둠.

---

## 4. 시나리오 mix

학습 매 에피소드 시작 시 다음 분포로 환경 구성:

| 시나리오 | 비중 | n (보스 포함 봇 수) | 설명 |
|---|---|---|---|
| **pfsp** | 70% | 4 | 운영 기본형 (보스 1 + 상대 3) |
| **trio** | 25% | 4 | pfsp 와 같은 인원, 상대 구성만 다양 |
| **solo** | 5% | 2 | 보스 vs 단일 상대 (메모리 1번 제약, ≤5%) |

> 상대 구성(opponents)은 현재 단순화: 5% 룰 보스 + 95% 일반 봇(`HerbivoreBot`/`MadDogBot`/`CamperBot`). League 자체 봇 풀(`past_opponent`)은 추후 통합 예정.

---

## 5. 학습 루프 (의사 코드)

```python
for ep in range(1, episodes + 1):
    scenario = weighted_choice(["pfsp", "trio", "solo"], [0.70, 0.25, 0.05])
    env = BR2MiniEnv(seed=..., duration_sec=360)
    opponents = build_opponents(n=SCENARIO_NS[scenario], ...)
    epsilon = linear_decay(step, 1.0 → 0.05, 10_000)

    transitions, info = run_episode(env, qnet, opponents, scenario, epsilon)

    for tr in transitions:
        replay.push(tr)
        step += 1
        if len(replay) >= 2000 and step % 4 == 0:
            dqn_update(qnet, target, optimizer, replay)
            if step % 1000 == 0:
                target.load_state_dict(qnet.state_dict())

    if ep % 50 == 0:
        save_checkpoint(qnet, gen=NN, meta={"win_rate20": ..., "avg_rank20": ...})
        prune_old_checkpoints(keep=12)

# 종료 시
final_torch_pt → convert to .npz (numpy, in-out transpose)
copy to bots/boss/rl/checkpoints/gen_NNNNN.npz
gsutil cp gen_NNNNN.npz gs://knu-2026-boss-weights/br2/{gen_NNNNN.npz, latest.npz}
if self_stop: shutdown
```

---

## 6. mini_env — 학습용 단순화 환경

`backend/BattleRoyale2/sim/mini_env.py` 의 `BR2MiniEnv`. **Godot 헤드리스 러너 없이 학습**하기 위한 순수 Python 단순화.

### 채택 이유 — 옵션 비교

| 옵션 | 장점 | 단점 |
|---|---|---|
| A. Godot 헤드리스 러너 병렬 | 룰 100% 일치 | 360s/매치 → 학습 1k epi = 100+ 시간. 매치당 비용 ↑ |
| **B. 경량 Py 시뮬 (채택)** | 초고속 (~5s/매치 cpu), 단일 프로세스 600+ epi/day | sim2real 갭 — 운영 배포 전 e2e 검증 필수 |
| C. 하이브리드 | 정확도 + 속도 절충 | 구축 비용 가장 큼 |

→ BR2 보스 RL 의 *정성적 차별화* 가 목적이므로 B 채택. 절대 ranking ladder 운영이 목적이면 A 로 전환.

### 단순화 정책

| 항목 | 단순화 |
|---|---|
| 충돌 | 원형(반지름 25px) |
| 공격 | 근접 60px / 원거리 400px, 데미지 = `atk - target.def` (가드 시 50%↓) |
| 시야 | 전체 정보 노출 (encoder 가 top-K 잘라냄) |
| 투사체 | 즉발 (속도 무시, 사거리만 검사) |
| zone | 원형, 3 phase 시간 기반 shrink |
| tick | 100ms (10Hz). 보스 모드 매치 360s = 3600 ticks |

### Godot 과의 갭이 영향을 줄 수 있는 부분

1. **이동 정확도** — Godot 은 Navigation2D 기반, sim 은 단순 벡터 적분
2. **투사체 회피** — sim 은 즉발이라 위치만 맞으면 OK, Godot 은 비행 중 회피 가능
3. **충돌 경계** — Godot 콜리전 셰이프 ≠ sim 원형
4. **frame skip / 입력 지연** — sim 은 모든 tick 즉시 반영, Godot 은 네트워크/렌더 지연

→ 학습된 정책이 sim 에서 강해도 Godot 에서 약할 수 있다. 운영 전 e2e 검증 필수.

---

## 7. 액션 공간 (decoder)

| idx | 의미 | 채워지는 키 |
|---|---|---|
| 0 | STAY | (모두 0) |
| 1..8 | MOVE 8방향 | `move_dir`, `aim_dir` |
| 9..16 | ATTACK 8방향 | `aim_dir`, `attack=True` |
| 17 | GUARD | `guard=True` |
| 18 | DASH | `move_dir(last_move)`, `dash=True` |
| 19 | PICKUP | `pickup=True` |

8방향 단위벡터:
```
0=RIGHT  (+1,0)    1=DOWN_R(+.7,+.7)   2=DOWN(0,+1)    3=DOWN_L(-.7,+.7)
4=LEFT   (-1,0)    5=UP_L (-.7,-.7)   6=UP  (0,-1)    7=UP_R (+.7,-.7)
```

> **use_potion** 은 학습 액션 공간에서 제외 — 디코더가 룰로 처리: `has_potion AND hp <= 100`. 학습 부담↓.

---

## 8. 재학습 방법

VM SSH 후:

```bash
cd ~/loa-main/backend
source venv/bin/activate            # PyTorch 설치된 venv (학습 VM 전용)
python -m BattleRoyale2.scripts.train.train_boss_br2 \
  --episodes 500 \
  --device cpu \
  --upload-gcs \
  --self-stop \
  --seed 42
```

주요 플래그:

| 플래그 | 기본 | 의미 |
|---|---|---|
| `--episodes` | 100 | 학습 에피소드 수. 500≈40분 (CPU) |
| `--device` | cpu | cuda 사용 시 GPU 노드 필요 |
| `--output-dir` | `/tmp/br2_boss_train` | 중간 체크포인트 저장소 |
| `--upload-gcs` | off | 최종 `.npz` 를 `gs://knu-2026-boss-weights/br2/` 에 업로드 |
| `--self-stop` | off | 학습 종료 후 GCP VM 자동 shutdown (metadata 확인) |
| `--gen-start` | 0 | 이어 학습 시 마지막 generation+1 지정 |

학습 중 로그 모니터링 (10ep 마다 출력):

```
ep=120/500 sc=pfsp rank=2/4 score=33.5 reward=12.5 eps=0.512 buf=2300 avg_rank20=2.85 win20=0.10 elapsed=600s
                          ^^^^^^^^^^^^                                                  ^^^^^^^^^^^
                          이번 에피소드 성과                                            최근 20ep 추세
```

`avg_rank20 ↓ 2.0` 으로 내려가거나 `win20 ↑ 0.20+` 이면 학습 효과 가시화.

---

## 9. 향후 튜닝 후보

학습이 잘 안 될 때 시도 순서 (영향 ↑ → 영향 ↓):

1. **시나리오 비중 재조정** — pfsp 50% / trio 40% / solo 10%
2. **보상 음수 완화** — `REWARD_RANK3_PLUS=-10 → -3`, 패율 곱셈 효과 ↓
3. **dense reward 강화** — score delta 비중 ↑ (mining bonus 추가)
4. **상대 풀 다양화** — past_opponent (league) 자체 봇 mix 추가
5. **에피소드 수** — 500 → 2000~5000 (CPU 로는 시간 부담 큼)
6. **GPU 학습** — VM 을 GPU 타입으로 변경 후 batch 늘리기

→ 현 상황(win20=0.00) 에서 가장 효과 클 후보는 **1+2 동시 적용** 후 2000ep 재학습.

---

[다음 — 02. 서빙](02-serving.md) →

# BR2 RL 보스 설계 (Phase 4 인프라)

작성일: 2026-06-02 · 버전: 1 (인프라 단계, 학습 환경 미결)

## 1. 목적

옛 `backend/battle_royale/bots/boss/rl_boss_bot.py` (DQN, 43-D 그리드 인코딩, 19 액션)
의 BR2 (연속 2D) 버전 인프라. **학습 환경 구축은 후속 세션**, 본 문서는 인코더·디코더·
네트워크·league·past_opponent contract 만 확정한다.

## 2. 폴더

```
backend/BattleRoyale2/bots/boss/rl/
├── __init__.py
├── encoder.py        # state → (80,) float32
├── decoder.py        # int(0..19) → 7키 action dict
├── network.py        # numpy MLP (FEATURE_DIM=80 → 256 → 128 → 20)
├── inference.py      # RLBossBR2 (BattleRoyale2DBot 구현)
├── league.py         # 체크포인트 풀 (recency_bias=0.6, top 12)
├── past_opponent.py  # PastBossOpponentBR2 freeze wrapper
└── checkpoints/      # gen_NNNNN.npz + league_index.json
```

## 3. 인코더 (encoder.py)

### Feature 80차 레이아웃

| offset | size | 의미 |
|---|---|---|
| 0..9 | 10 | self_core: hp_ratio, vel(2), atk·def·speed norm, 3 cd, potion+ranged 압축 |
| 10..12 | 3 | self_meta: pos_x/W, pos_y/H, time/duration |
| 13..30 | 18 | enemy_top3 × (rel_dx, rel_dy, dist_n, hp_ratio, guarding, has_ranged) |
| 31..42 | 12 | node_top3 × (rel_dx, rel_dy, dist_n, rare) |
| 43..48 | 6 | chest_top2 × (rel_dx, rel_dy, dist_n) |
| 49..54 | 6 | item_top2 × (rel_dx, rel_dy, dist_n) |
| 55..64 | 10 | projectile_top2 × (rel_dx, rel_dy, dist_n, vel_dx, vel_dy) |
| 65..73 | 9 | zone: active, rel_to_center(2), radius_n, damage, phase, target_rel(2), target_eta_n |
| 74 | 1 | leaderboard_self: my_score / top_score |
| 75 | 1 | bias unit (상수 1.0) |
| 76..79 | 4 | padding (zeros, 확장 여지) |

### 정규화 상수

- 맵: `MAP_W=MAP_H=3000`, `MAP_DIAG≈4243`
- HP: `MAX_HP=200`
- 속도: `MAX_SPEED=300`
- 쿨다운: `MAX_CD=3.0s`
- zone damage: `ZONE_DAMAGE_NORM=5.0`
- projectile vel: `PROJECTILE_VEL_NORM=500`
- 매치 길이: 기본 360s (보스 모드). encoder 호출 시 `duration_sec` override.

### ego-centric 정규화

거리 큰 적/자원도 `dist_n = dist / MAP_DIAG ∈ [0, 1]` 로 압축. 방향은 단위벡터 `(dx/d, dy/d)`
로 분리해서 거리·방향 학습이 독립적.

## 4. 액션 디코더 (decoder.py)

### 20 디스크리트 액션

| idx | 의미 | 채워지는 키 |
|---|---|---|
| 0 | STAY | (모두 0) |
| 1..8 | MOVE 8방향 | move_dir, aim_dir |
| 9..16 | ATTACK 8방향 | aim_dir, attack=True |
| 17 | GUARD | guard=True |
| 18 | DASH | move_dir(last_move), dash=True |
| 19 | PICKUP | pickup=True |

### 8방향 인덱스 (BR2 좌표계: x=오른쪽+, y=아래+)

```
0=RIGHT   (+1, 0)
1=DOWN_R  (+.7, +.7)
2=DOWN    ( 0, +1)
3=DOWN_L  (-.7, +.7)
4=LEFT    (-1, 0)
5=UP_L    (-.7, -.7)
6=UP      ( 0, -1)
7=UP_R    (+.7, -.7)
```

### use_potion 룰 기반

학습 부담을 줄이기 위해 `use_potion` 은 학습 액션 공간에서 제외하고, 디코더가 룰로 추가:
`has_potion AND hp <= 100 → use_potion=True`. 옛 룰 보스의 LOW_HP_POTION 임계값과 일치.

## 5. 네트워크 (network.py)

옛 RLBossBot 과 동일 구조 (3-layer MLP, ReLU):

```
입력 (80,)
  → Linear (80, 256) + ReLU
  → Linear (256, 128) + ReLU
  → Linear (128, 20)   # raw Q-values
```

- He init (학습 안 한 weight 도 안전한 분산)
- inference-only (backward 없음). 학습은 별도 PyTorch 스크립트가 담당, 산출물을 `.npz`
  로 변환.
- `QNetwork.load / save` 가 체크포인트 입출력.

## 6. League (league.py)

옛 운영 정책 유지:

- 최대 풀 크기: **12**
- 보존 전략: 최근 **8** + 승률 quartile **4**
- 샘플링 `recency_bias = 0.6` (60% 최근, 40% top 승률)
- 인덱스: `league_index.json` (entries: generation, filename, win_rate, epsilon, step_count, ...)

학습 스크립트가 새 generation 마다 `LeagueIndex.add(entry)` → 자동 prune + 파일 삭제.

## 7. Past Opponent (past_opponent.py)

`PastBossOpponentBR2` — `RLBossBR2` 의 epsilon=0.0 freeze wrapper. 학습 중 opponent
풀 멤버로 사용. 옛처럼 `_learn` no-op patch 필요 없음 (BR2 QNetwork 가 inference-only).

## 8. ws_server 통합

`_BOSS_CLASS_BY_DIFFICULTY` 에 `"hard"` 키는 **부팅 시 체크포인트 발견되어야** 등록.

```python
def _try_enable_hard_boss():
    if any(DEFAULT_CHECKPOINT_DIR.glob("gen_*.npz")):
        _BOSS_CLASS_BY_DIFFICULTY["hard"] = RLBossBR2
```

POST `/api/games` 의 `boss_difficulty="hard"` 요청:
- 체크포인트 있음 → hard 보스로 매치 진행
- 체크포인트 없음 → **자동 medium 폴백** + warning 로그 (game.config_json 에는 medium 저장)

## 9. 학습 환경 (Phase 4 후속 결정)

본 인프라는 학습 환경 비독립적 — 어떤 환경을 골라도 같은 인코더/디코더/네트워크 사용.

### 후속 결정 옵션

| 옵션 | 설명 | 장단 |
|---|---|---|
| A 런너 기반 | Godot 헤드리스 러너 다수 병렬 (`runner_manager.try_spawn`) | 룰 100% 일치, 속도 느림 (360s/매치) |
| B 경량 Py 시뮬 | BR2 게임 룰(이동/zone/HP/공격/아이템/상자) Python 재구축 | 초고속, 600+ ep/일, sim2real 갭 |
| C 하이브리드 | B 로 사전학습 → A 로 파인튜닝 | 타협안, 구축 비용 가장 큼 |

### 권장 (작성자 의견)

- 보스 정책의 *정성적 차별화*가 목적이면 **B 경량 Py 시뮬** 권장. 옛 학습 인프라
  (`train_boss_parallel.py`) 의 멀티프로세스 패턴 그대로 옮길 수 있고, 600 에피소드를
  수 시간 내 돌릴 수 있음. sim2real 갭은 보상 함수 정성 평가로 흡수 가능.
- 정량 ranking ladder 운영이 목적이면 **A 런너 기반** 또는 C.

## 10. 변환·학습 스크립트 (후속)

후속 세션에서 추가할 파일:

```
backend/BattleRoyale2/scripts/train/train_boss_br2.py
backend/BattleRoyale2/scripts/tools/convert_torch_to_numpy_br2.py
backend/BattleRoyale2/scripts/sim/bench_boss_br2.py
backend/BattleRoyale2/sim/      # (옵션 B 채택 시) Python 게임 시뮬
```

## 11. 변경 이력

- 2026-06-02 v1 — 초안. 인코더/디코더/네트워크/league/past_opponent contract 확정.
  학습 환경은 미결 (사용자 선택 옵션 D).

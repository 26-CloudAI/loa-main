# BR2 보스 모드 프로토콜 (백엔드 ↔ Godot)

작성일: 2026-06-02 · 대상 버전: BR2 v0.1 · contract version: **v2**

이 문서는 BattleRoyale2 (BR2) 백엔드가 보스 모드 매치 시 Godot 클라이언트에게
전달하는 추가 메타데이터 contract 를 정의한다. Godot 측(별도 리포 `loa-battleroyale-game`)
이 이 contract 를 구현하면 보스 모드 매치 환경이 옛 `boss_battle_config()` 의 의미를
보존하면서 BR2 다대일 균형이 잡힌다.

## 1. 개요

- BR2 base 매치 (일반 배틀로얄) 와 보스 모드는 **봇 의사결정 인터페이스가 동일**하다 (`BattleRoyale2DBot`).
- 보스 모드의 차이:
  1. **매치 환경**: 길이, 자원 양, 자기장 phase 타이밍, 봇 슬롯 정원
  2. **보스 stat 강화**: 다대일(평균 3 vs 1) 균형을 위한 hp/atk/def/speed 배수
     — 옛 1대1 보스전엔 없던 개념이지만 BR2 다대일에선 필수.
- 보스다움 = stat 강화 × 알고리즘 강도 (룰베이스 Phase 1 / RL Phase 4).

## 2. POST `/battleroyale2/api/games`

기존 필드에 더해 보스 모드용 필드 1개:

```jsonc
{
  "bots": [...],
  "bot_count": 4,              // 보스 모드 기본 4, 최대 8
  "seed": 12345,
  "name": "보스전 1",
  "boss_difficulty": "easy"    // "easy" | "medium" | (향후) "hard"
}
```

서버 검증:
- `boss_difficulty` 가 미지원 값(`"hard"` 포함 — Phase 4 까지 비활성)이면 무시(일반 매치).
- 보스 모드인 경우 `bots.length ≤ BOSS_MAX_USER_BOTS (=3)`. 초과 시 400.
- `boss_difficulty` 가 설정되면 `games.config_json` 에 영속 저장 (다중 인스턴스 복원).

응답:
```jsonc
{ "game_id": "abc...", "persisted": true, "running": false }
```

## 3. WS `MATCH_CONFIG` 페이로드

기존:
```jsonc
{
  "type": "MATCH_CONFIG",
  "data": {
    "match_id": "abc...",
    "seed": 0,
    "duration": 180,
    "bots": [{"id":"bot_a","display_name":"초식봇"}, ...]
  }
}
```

**보스 모드 추가 필드 `boss_rules`** (없으면 일반 매치, Godot 은 자기 base 룰 유지):

```jsonc
{
  "type": "MATCH_CONFIG",
  "data": {
    "match_id": "abc...",
    "seed": 0,
    "duration": 360,             // 보스 모드 기본 ×2
    "bots": [
      {"id":"boss","display_name":"보스(하)"},
      {"id":"challenger","display_name":"도전자 1"},
      {"id":"ai_0","display_name":"초식봇 1"},
      {"id":"ai_1","display_name":"존버봇 1"}
    ],
    "boss_rules": {
      "version": 2,
      "duration_sec": 360,
      "map": {
        "rare_clusters": 6,
        "chest_clusters": 6,
        "initial_node_count_hint": 400
      },
      "zone": {
        "phase1_end_sec": 135.0,        // 자유 탐색 구간 (옛 비율 0.375 × 360)
        "phase2_end_sec": 288.0,        // 점진 수축 종료 (옛 비율 0.80 × 360)
        "phase2_shrink_interval_sec": 0.8,
        "phase3_shrink_interval_sec": 0.5
      },
      "slots": {
        "boss_count": 1,
        "user_max": 3,
        "ai_fillers_enabled": true,
        "target_bot_count": 4
      },
      "boss_stat_overrides": {           // 다대일 균형 — Godot 가 bot_id=="boss" 에 곱셈 적용
        "max_hp_mult": 2.0,              // base 200 → 400 (Easy)
        "atk_mult": 1.2,
        "def_mult": 1.2,
        "speed_mult": 1.0,
        "attack_cd_mult": 1.0
      },
      "difficulty": "easy"
    }
  }
}
```

### Godot 적용 가이드
- `boss_rules` 가 있으면 `boss_rules.duration_sec` 가 권위. 없으면 `data.duration` 또는 base.
- `boss_rules.map.*` : 매치 초기 자원 스폰 시 적용. 없으면 base 유지.
- `boss_rules.zone.*` : 자기장 phase 전환 타이밍을 절대 초 단위로 강제. 없으면 base 유지.
- `boss_rules.slots.boss_count` : 보스 봇 ID = `"boss"` 로 고정 (서버가 보장). Godot 가
  보스 봇에게 시각적 마킹(테두리/이름표 색) 적용 권장.
- `boss_rules.boss_stat_overrides` : 보스 봇(`bot_id=="boss"`) 의 base stat 에 **곱셈 적용**:
  - `max_hp_mult` : base max_hp 에 곱함. 현재 hp 도 비례 스케일.
  - `atk_mult`/`def_mult`/`speed_mult` : 각각 base 값에 곱함.
  - `attack_cd_mult` : base 공격 쿨다운에 곱함 (<1.0 이면 공격 더 자주).
  - null 이면 강화 안 함 (일반 매치 동일).

## 4. 옛 boss_battle_config 와의 매핑

| 옛 (`backend/battle_royale/.../boss/config.py`) | BR2 (`backend/BattleRoyale2/rules/boss_mode.py`) |
|---|---|
| `max_ticks = 400` (옛 base 200 ×2) | `duration_sec = 360` (BR2 base 180 ×2) |
| `initial_mineral_count = 400` | `map.initial_node_count_hint = 400` |
| `num_rare_mineral_clusters = 6` | `map.rare_clusters = 6` |
| `zone.phase1_end = 150` (옛 / 400 = 0.375) | `zone.phase1_end_sec = 135.0` (BR2 / 360 = 0.375) |
| `zone.phase2_end = 320` (옛 / 400 = 0.80) | `zone.phase2_end_sec = 288.0` (BR2 / 360 = 0.80) |
| `zone.phase2_shrink_interval = 8` (틱 × 0.1s) | `phase2_shrink_interval_sec = 0.8` |
| `zone.phase3_shrink_interval = 5` (틱 × 0.1s) | `phase3_shrink_interval_sec = 0.5` |
| `BOSS_MAX_USER_BOTS = 3` | `slots.user_max = 3` |
| (옛은 stat 강화 없음 — 1대1) | `boss_stat_overrides.*` (BR2 신규, 다대일 균형) |

## 5. 다대일 균형 — boss_stat_overrides

옛 1대1 보스전과 달리 BR2 보스전은 평균 3 vs 1 (유저 ≤3 + AI 채움 vs 보스). 알고리즘
강도만으로 균형 잡히지 않아 stat 강화 도입.

### 난이도별 배수 (BR2 base hp=200, atk=10 기준)

| 난이도 | max_hp× | atk× | def× | speed× | attack_cd× | 결과 (예: hp) |
|---|---|---|---|---|---|---|
| 하 | 2.0 | 1.2 | 1.2 | 1.0 | 1.0 | 200 → 400 |
| 중 | 2.5 | 1.4 | 1.3 | 1.05 | 0.95 | 200 → 500 |
| 상 | 3.0 | 1.6 | 1.4 | 1.1 | 0.9 | 200 → 600 |

### 룰 봇 임계값 비율 보존

`backend/BattleRoyale2/bots/boss/rule/base.py` 의 임계값은 *옛 base max_hp=200 기준
절대값* 으로 정의되어 있고, runtime 에 `state["self"]["max_hp"]` 에 비례 자동 스케일된다.

예: Medium 보스 (max_hp=500) 의 `ATTACK_HP=40` 임계값 → 실제 적용 `40 × (500/200) = 100`.
옛 의사결정 의미 (HP 20% 이하면 공격 자제) 가 보존된다.

## 6. 미지원 / 향후 변경

- **`difficulty: "hard"`** : 체크포인트 (`backend/BattleRoyale2/bots/boss/rl/checkpoints/gen_*.npz`)
  배치 후 자동 활성. 없으면 ws_server 가 medium 폴백.
- **봇 슬롯 시각 마킹** : Godot 측에서 `bot_id === "boss"` 의 캐릭터에 보스 테두리/이펙트
  적용 권장 (네임 표시는 `display_name = "보스(하|중|상)"` 사용).
- **boss_stat_overrides 적용** : Godot 측에서 받아 base stat 에 곱셈 오버라이드 PR 필요.
  Godot 코드 미수정 시 contract 무시되어 보스 stat = 일반 봇 stat 으로 동작 (다대일 불균형).

## 7. 변경 이력

- 2026-06-02 v2 — `boss_stat_overrides` 활성 (다대일 균형). `slots.target_bot_count` 추가.
  룰 봇 임계값 max_hp 비율 자동 스케일.
- 2026-06-02 v1 — 초안. 옛 boss_battle_config BR2 매핑, MATCH_CONFIG.boss_rules contract 정의.

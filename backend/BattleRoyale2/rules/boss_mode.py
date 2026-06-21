"""보스 모드 게임 룰 — BR2 다대일 환경에 맞춘 밸런스.

배경:
    옛 backend/battle_royale 보스전은 1대1 (유저 1 vs 보스 1) 이라 보스 stat 강화
    없이도 알고리즘 강도만으로 균형이 맞았다. BR2 보스전은 다대일 (보스 1 + 유저 최대 3
    + AI 채움 = 평균 4명) 이라 stat 강화 없이는 보스가 즉시 cornered 된다.

    따라서 BR2 보스전은 *옛 의사결정 트리·임계값은 보존* 하면서 (rule/base.py),
    *환경 룰 + 보스 stat 강화* 를 추가한다. 임계값은 비율 기반이므로 max_hp 가
    강화돼도 의미 보존된다 (옛 60/200 ≈ 30% → 강화된 400 hp 에서도 30% = 120).

옛 boss_battle_config 1:1 매핑 (환경 룰):
    max_ticks         200 → 400  → BR2 duration_sec 360 (BR2 base 180 × 2)
    minerals          300 → 400  → initial_node_count_hint 400
    rare clusters       5 → 6    → map.rare_clusters 6
    zone phase1_end    75 → 150  → 비율 0.375 → phase1_end_sec 135
    zone phase2_end   150 → 320  → 비율 0.80  → phase2_end_sec 288
    zone phase2 interval  8 (그대로 0.8s)
    zone phase3 interval  5 (옛 2→5 완화 보존, 0.5s)

BR2 보스전 신규 (다대일 균형):
    유저 최대 3 + AI 채움 → 평균 3마리가 보스와 동시 교전.
    보스가 일반 봇 ~3배 전투력을 가져야 균형. 단 너무 강하면 도전 좌절.
    난이도별 boss_stat_overrides 로 hp/atk/def/speed 배수 제공.

밸런스 표 (BR2 base hp≈200, atk≈10 가정):

    난이도 | hp×   | atk×  | def×  | spd×  | 체감
    -------|-------|-------|-------|-------|-----------------------
    하     | 2.0   | 1.2   | 1.2   | 1.0   | 초보도 도전 가능
    중     | 2.5   | 1.4   | 1.3   | 1.05  | 팀워크·라스트힛 필요
    상     | 3.0   | 1.6   | 1.4   | 1.1   | RL 정책 + 풀 강화

이 dict 는 MATCH_CONFIG.boss_rules 필드로 노출된다. Godot 측이 받으면 보스 봇
(`bot_id="boss"`) 의 stat 를 곱셈 오버라이드, 필드 누락이면 base 유지.
"""
from __future__ import annotations

from typing import Any, Optional


# 옛 BOSS_MAX_USER_BOTS=3 동일 — 보스 1마리 + 유저봇 최대 3 + AI 채움
BOSS_MAX_USER_BOTS: int = 3

# 보스 모드 매치 기본 봇 수 (보스 + 유저봇 + AI 채움). 옛 보스전 운영 경험상 4가 균형.
BOSS_MODE_DEFAULT_BOT_COUNT: int = 4

# BR2 base 매치 길이 (ws_server.py 와 동기). 옛 보스전 × 2 비율로 360s 가 보스 모드.
BR2_BASE_DURATION_SEC: int = 180
BOSS_MODE_DURATION_SEC: int = 360

# zone phase 비율 — 옛 (phase1_end / max_ticks, phase2_end / max_ticks)
#   옛: 150/400=0.375, 320/400=0.8
_PHASE1_FRAC: float = 0.375
_PHASE2_FRAC: float = 0.80

# ── 난이도별 보스 stat 강화 배수 ────────────────────────────────────────
# 다대일(평균 3 vs 1) 균형 보존을 위한 배수. base = BR2 일반 봇 stat.
# Godot 측이 bot_id == "boss" 캐릭터에 multiplicative override 적용.
# 난이도 키는 운영 컨벤션과 동일하게 한국어("하/중/상") 사용.
BOSS_STAT_MULTIPLIERS: dict[str, dict[str, float]] = {
    "하": {
        "max_hp_mult": 2.0,    # 200 → 400
        "atk_mult": 1.2,       # 10  → 12
        "def_mult": 1.2,       # 5   → 6
        "speed_mult": 1.0,     # 100 → 100 (하: 속도 강화 없음 — 도주 가능 시간 확보)
        "attack_cd_mult": 1.0,
    },
    "중": {
        "max_hp_mult": 2.5,    # 200 → 500
        "atk_mult": 1.4,       # 10  → 14
        "def_mult": 1.3,       # 5   → 6.5
        "speed_mult": 1.05,    # 100 → 105
        "attack_cd_mult": 0.95,  # 공격 cd 5% 감소 (살짝 더 자주)
    },
    "상": {
        "max_hp_mult": 3.0,    # 200 → 600
        "atk_mult": 1.6,       # 10  → 16
        "def_mult": 1.4,       # 5   → 7
        "speed_mult": 1.1,     # 100 → 110
        "attack_cd_mult": 0.9,
    },
}


def boss_mode_rules(difficulty: Optional[str] = None) -> dict[str, Any]:
    """MATCH_CONFIG.boss_rules 페이로드.

    Args:
        difficulty: "하" | "중" | "상". 환경 룰은 난이도 무관 동일,
                    boss_stat_overrides 만 난이도별로 다름.

    Returns:
        Godot 클라이언트가 자기 base 룰 위에 오버레이로 적용할 dict.
    """
    stat_overrides = BOSS_STAT_MULTIPLIERS.get(difficulty) if difficulty else None
    return {
        "version": 2,   # v2: boss_stat_overrides 도입 (v1 → 강화 없음)
        "duration_sec": BOSS_MODE_DURATION_SEC,
        "map": {
            "rare_clusters": 6,
            "chest_clusters": 6,
            "initial_node_count_hint": 400,    # 옛 minerals 300→400
        },
        "zone": {
            # 옛 phase 비율 보존 — 절대 초 단위로 환산
            "phase1_end_sec": round(BOSS_MODE_DURATION_SEC * _PHASE1_FRAC, 1),  # 135.0
            "phase2_end_sec": round(BOSS_MODE_DURATION_SEC * _PHASE2_FRAC, 1),  # 288.0
            # 옛 8tick(=0.8s) / 5tick(=0.5s) 그대로
            "phase2_shrink_interval_sec": 0.8,
            "phase3_shrink_interval_sec": 0.5,
        },
        "slots": {
            "boss_count": 1,
            "user_max": BOSS_MAX_USER_BOTS,
            "ai_fillers_enabled": True,
            "target_bot_count": BOSS_MODE_DEFAULT_BOT_COUNT,
        },
        # 다대일 균형 보정 — Godot 측이 bot_id=="boss" 에 multiplicative 적용.
        # 옛 1대1 보스전엔 없던 개념이지만 BR2 다대일에선 필수.
        "boss_stat_overrides": stat_overrides,
        "difficulty": difficulty,
    }


def boss_max_hp(difficulty: Optional[str], base_max_hp: int = 200) -> int:
    """Godot 적용 후 보스의 max_hp 예측값. 룰 봇이 자기 임계값 스케일에 사용 가능."""
    if difficulty and difficulty in BOSS_STAT_MULTIPLIERS:
        return int(base_max_hp * BOSS_STAT_MULTIPLIERS[difficulty]["max_hp_mult"])
    return base_max_hp


def is_boss_mode(boss_difficulty: Optional[str]) -> bool:
    return bool(boss_difficulty)


__all__ = [
    "BOSS_MAX_USER_BOTS",
    "BOSS_MODE_DEFAULT_BOT_COUNT",
    "BOSS_MODE_DURATION_SEC",
    "BR2_BASE_DURATION_SEC",
    "BOSS_STAT_MULTIPLIERS",
    "boss_mode_rules",
    "boss_max_hp",
    "is_boss_mode",
]

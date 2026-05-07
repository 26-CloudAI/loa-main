"""
보스봇 학습 파라미터 자동 조정기 (Claude API 불필요)
=====================================================

PostgreSQL에서 최근 보스전 결과를 읽어 다음 학습 설정을 추천한다.
train_boss_bot.py 실행 전에 호출하면 적절한 --episodes, 상대 조합 등을 결정할 수 있다.

사용법:
    python analyze_boss_stats.py                  # 추천 설정 출력
    python analyze_boss_stats.py --json           # JSON으로 출력 (스크립트 연동용)
    python analyze_boss_stats.py --apply          # 출력 + training_config.json 저장
    eval $(python analyze_boss_stats.py --export-env)  # 환경변수로 export

환경변수:
    DB_HOST, DB_NAME, DB_USER, DB_PASSWORD  — PostgreSQL 접속 정보
    BOSS_BOT_NAME                           — 보스봇 bot_name (기본: AI_보스)
    STATS_WINDOW                            — 분석 대상 최근 게임 수 (기본: 100)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

BOSS_BOT_NAME = os.environ.get("BOSS_BOT_NAME", "AI_보스")
STATS_WINDOW = int(os.environ.get("STATS_WINDOW", "100"))
CONFIG_PATH = Path(__file__).parent / "training_config.json"

# ---------------------------------------------------------------------------
# 기본 학습 설정 (변경 없을 때 사용)
# ---------------------------------------------------------------------------

@dataclass
class TrainingConfig:
    episodes: int = 500
    bots: int = 5
    train_epsilon: float = 0.30
    note: str = ""

    # 상대 조합 가중치 (herbivore : mad_dog : camper)
    # train_boss_bot.py 는 아직 이 값을 읽지 않음 — 향후 확장용
    opponent_weights: dict = None  # type: ignore

    def __post_init__(self):
        if self.opponent_weights is None:
            self.opponent_weights = {"herbivore": 1, "mad_dog": 1, "camper": 1}


# ---------------------------------------------------------------------------
# DB 조회
# ---------------------------------------------------------------------------

def _get_db_conn():
    host = os.environ.get("DB_HOST", "localhost")
    dbname = os.environ.get("DB_NAME", "ai_arena")
    user = os.environ.get("DB_USER", "arena_user")
    password = os.environ.get("DB_PASSWORD", "")
    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(
        host=host, dbname=dbname, user=user, password=password,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _fetch_boss_stats(limit: int = STATS_WINDOW) -> list[dict]:
    """최근 보스전 결과를 가져온다."""
    try:
        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    gp.final_rank,
                    gp.final_score,
                    gp.kills,
                    gp.survival_ticks,
                    g.total_bots,
                    g.finished_at
                FROM game_participants gp
                JOIN games g ON g.id = gp.game_id
                WHERE gp.bot_name = %s
                  AND g.status = 'finished'
                  AND gp.final_rank IS NOT NULL
                ORDER BY g.finished_at DESC
                LIMIT %s
                """,
                (BOSS_BOT_NAME, limit),
            )
            rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("DB 조회 실패: %s", exc)
        return []


# ---------------------------------------------------------------------------
# 통계 계산
# ---------------------------------------------------------------------------

@dataclass
class BossStats:
    n_games: int
    win_rate: float        # 1등 비율
    top2_rate: float       # 1~2등 비율
    avg_rank: float
    avg_rank_norm: float   # avg_rank / total_bots
    avg_kills: float
    avg_survival: float
    trend: str             # "improving" | "stable" | "declining"


def _compute_stats(rows: list[dict]) -> BossStats | None:
    if not rows:
        return None

    n = len(rows)
    total_bots_list = [r["total_bots"] or 5 for r in rows]
    ranks = [r["final_rank"] for r in rows]
    kills = [r["kills"] or 0 for r in rows]
    survivals = [r["survival_ticks"] or 0 for r in rows]

    win_rate = sum(1 for r in ranks if r == 1) / n
    top2_rate = sum(1 for r in ranks if r <= 2) / n
    avg_rank = sum(ranks) / n
    avg_rank_norm = sum(r / b for r, b in zip(ranks, total_bots_list)) / n

    # 트렌드: 앞 절반 vs 뒷 절반 평균 순위 비교 (rows는 최신순 정렬)
    half = max(n // 2, 1)
    recent_avg = sum(ranks[:half]) / half
    older_avg = sum(ranks[half:]) / max(n - half, 1)
    if recent_avg < older_avg - 0.3:
        trend = "improving"
    elif recent_avg > older_avg + 0.3:
        trend = "declining"
    else:
        trend = "stable"

    return BossStats(
        n_games=n,
        win_rate=win_rate,
        top2_rate=top2_rate,
        avg_rank=avg_rank,
        avg_rank_norm=avg_rank_norm,
        avg_kills=sum(kills) / n,
        avg_survival=sum(survivals) / n,
        trend=trend,
    )


# ---------------------------------------------------------------------------
# 규칙 기반 파라미터 조정
# ---------------------------------------------------------------------------

def _recommend(stats: BossStats | None) -> TrainingConfig:
    """
    통계에 따라 다음 학습 설정을 결정한다.

    규칙 (우선순위 순):
      1. 데이터 없음         → 기본값
      2. 보스가 너무 강함 (win_rate > 0.6)
                            → 적 강화 (mad_dog 위주), 에피소드 줄이기
      3. 보스가 너무 약함 (avg_rank_norm > 0.6)
                            → 탐색률 높이기, 에피소드 늘리기
      4. 하락 추세           → 탐색률 높이기 (local optima 탈출)
      5. 안정/개선           → 기본값 유지
    """
    if stats is None or stats.n_games < 10:
        return TrainingConfig(note="데이터 부족 — 기본값 사용")

    cfg = TrainingConfig()

    if stats.win_rate > 0.6:
        cfg.episodes = 300
        cfg.opponent_weights = {"herbivore": 1, "mad_dog": 3, "camper": 2}
        cfg.note = f"보스 승률 과다 ({stats.win_rate:.0%}) — 난이도 상향"

    elif stats.avg_rank_norm > 0.6:
        cfg.episodes = 700
        cfg.train_epsilon = 0.40
        cfg.note = f"보스 평균 순위 낮음 ({stats.avg_rank:.2f}) — 탐색 강화 + 에피소드 증가"

    elif stats.trend == "declining":
        cfg.train_epsilon = 0.35
        cfg.note = "하락 추세 감지 — 탐색률 소폭 상향"

    elif stats.win_rate >= 0.4 and stats.trend == "improving":
        cfg.episodes = 400
        cfg.note = f"개선 추세, 승률 양호 ({stats.win_rate:.0%}) — 에피소드 줄여 빠른 배포"

    else:
        cfg.note = (
            f"안정 (승률 {stats.win_rate:.0%}, 평균순위 {stats.avg_rank:.2f}, "
            f"추세 {stats.trend}) — 기본값 유지"
        )

    return cfg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="보스봇 학습 파라미터 자동 조정기")
    p.add_argument("--json",       action="store_true", help="JSON으로 출력")
    p.add_argument("--apply",      action="store_true", help=f"{CONFIG_PATH} 에 저장")
    p.add_argument("--export-env", action="store_true", help="shell export 문 출력")
    p.add_argument("--window",     type=int, default=STATS_WINDOW, help="분석 게임 수")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    rows = _fetch_boss_stats(args.window)
    stats = _compute_stats(rows)
    cfg = _recommend(stats)

    if args.export_env:
        print(f"export TRAIN_EPISODES={cfg.episodes}")
        print(f"export TRAIN_EPSILON={cfg.train_epsilon}")
        return

    if args.json:
        output = asdict(cfg)
        if stats:
            output["_stats"] = asdict(stats)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        if args.apply:
            CONFIG_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # 사람이 읽는 출력
    print("=" * 60)
    print("  보스봇 학습 파라미터 추천")
    print("=" * 60)
    if stats:
        print(f"  분석 게임 수   : {stats.n_games}")
        print(f"  승률 (1등)     : {stats.win_rate:.1%}")
        print(f"  TOP2 비율      : {stats.top2_rate:.1%}")
        print(f"  평균 순위      : {stats.avg_rank:.2f}")
        print(f"  평균 킬        : {stats.avg_kills:.1f}")
        print(f"  트렌드         : {stats.trend}")
    else:
        print("  (게임 기록 없음)")
    print()
    print(f"  → 추천 에피소드  : {cfg.episodes}")
    print(f"  → 탐색률 epsilon : {cfg.train_epsilon}")
    print(f"  → 노트           : {cfg.note}")
    print("=" * 60)

    if args.apply:
        CONFIG_PATH.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2))
        print(f"  설정 저장됨: {CONFIG_PATH}")


if __name__ == "__main__":
    main()

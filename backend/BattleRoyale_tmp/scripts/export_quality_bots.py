"""
품질 봇 GCS 내보내기 스크립트
==============================

서빙 VM에서 하루 1회 cron으로 실행한다.
bot_ratings 기준으로 품질 봇을 필터링해 GCS에 quality_bots.json으로 저장.
학습 VM은 이 파일을 읽어 학습 대상을 결정한다.

품질 기준:
  - games_played >= 10         최소 10판 플레이
  - win_rate >= 35%            OR
  - top3_rate >= 50%           5봇 게임 기준 절반 이상 상위권
  - len(code) >= 300           trivial/덤핑 봇 제외
  rating DESC 정렬 후 상위 MAX_BOTS_EXPORT개만 저장

crontab 설정 예시 (서빙 VM):
  0 2 * * * cd /path/to/BattleRoyale && python3 scripts/export_quality_bots.py >> /var/log/export_bots.log 2>&1

환경변수:
  BOSS_WEIGHTS_GCS_URI  — gcs_weights.py와 동일
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.arena import gcs_weights
from src.arena.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [export_quality_bots] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

MIN_GAMES_PLAYED    = 10     # 최소 플레이 수
MIN_WIN_RATE        = 0.35   # 최소 승률 (5봇 랜덤 기준선 20%보다 높게)
MIN_TOP3_RATE       = 0.50   # 또는 top3 진입률 50% 이상
MIN_CODE_LENGTH     = 300    # trivial 봇 필터 (문자 수)
MAX_BOTS_EXPORT     = 20     # GCS에 저장할 최대 봇 수 (rating 상위)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def export() -> int:
    """품질 봇을 DB에서 조회해 GCS에 업로드. 반환: 내보낸 봇 수."""
    if not gcs_weights.enabled():
        logger.warning("BOSS_WEIGHTS_GCS_URI 미설정 — 로컬 파일로 폴백")

    conn = None
    try:
        conn = init_db()

        # bot_ratings JOIN bots로 품질 봇 조회
        rows = conn.execute("""
            SELECT
                b.id,
                b.name,
                b.code,
                COALESCE(r.games_played, b.games_played, 0)  AS gp,
                COALESCE(r.wins,         b.wins,         0)  AS wins,
                COALESCE(r.top3_count,   0)                  AS top3,
                COALESCE(r.rating,       0.0)                AS rating
            FROM bots b
            LEFT JOIN bot_ratings r ON r.bot_id = b.id
            WHERE b.is_active = 1
              AND b.is_public  = 1
        """).fetchall()

    except Exception as exc:
        logger.error("DB 조회 실패: %s", exc)
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    # ── 품질 필터 ───────────────────────────────────────────────────────
    quality_bots = []
    for r in rows:
        bot_id, name, code, gp, wins, top3, rating = (
            r["id"], r["name"], r["code"] or "",
            int(r["gp"]), int(r["wins"]), int(r["top3"]), float(r["rating"]),
        )

        # 코드 길이
        if len(code.strip()) < MIN_CODE_LENGTH:
            continue

        # 최소 게임 수
        if gp < MIN_GAMES_PLAYED:
            continue

        win_rate  = wins / gp
        top3_rate = top3 / gp

        if win_rate < MIN_WIN_RATE and top3_rate < MIN_TOP3_RATE:
            continue

        quality_bots.append({
            "id":       bot_id,
            "name":     name,
            "code":     code,
            "rating":   rating,
            "games":    gp,
            "win_rate": round(win_rate, 3),
            "top3_rate": round(top3_rate, 3),
        })

    # rating 내림차순 정렬 → 상위 MAX_BOTS_EXPORT개
    quality_bots.sort(key=lambda x: x["rating"], reverse=True)
    n_passed = len(quality_bots)
    quality_bots = quality_bots[:MAX_BOTS_EXPORT]

    logger.info(
        "품질 봇 필터링 완료: 전체 %d개 중 %d개 통과 → 상위 %d개 내보내기",
        len(rows), n_passed, len(quality_bots),
    )

    if not quality_bots:
        logger.info("품질 봇 없음 — GCS 업로드 건너뜀")
        return 0

    # ── GCS 업로드 ───────────────────────────────────────────────────────
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count":       len(quality_bots),
        "criteria": {
            "min_games_played": MIN_GAMES_PLAYED,
            "min_win_rate":     MIN_WIN_RATE,
            "min_top3_rate":    MIN_TOP3_RATE,
            "min_code_length":  MIN_CODE_LENGTH,
            "max_exported":     MAX_BOTS_EXPORT,
        },
        "bots": quality_bots,
    }

    if gcs_weights.enabled():
        ok = gcs_weights.upload_json(payload, "quality_bots.json")
        if ok:
            logger.info("GCS 업로드 완료: quality_bots.json (%d개)", len(quality_bots))
        else:
            logger.error("GCS 업로드 실패")
    else:
        # 로컬 저장 (GCS 미설정 시 개발 환경용)
        local_path = _PROJECT_ROOT / "bots" / "quality_bots.json"
        local_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        logger.info("로컬 저장: %s (%d개)", local_path, len(quality_bots))

    return len(quality_bots)


if __name__ == "__main__":
    n = export()
    sys.exit(0 if n >= 0 else 1)

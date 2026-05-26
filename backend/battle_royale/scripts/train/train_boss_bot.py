"""
RLBossBot 오프라인 강화학습 스크립트
=====================================

DB에 등록된 유저 공개 봇을 상대로 RLBossBot의 Q-가중치를 누적 학습한다.
프로덕션 보스전과 동일한 분포의 상대(유저가 실제로 짠 봇)를 사용하므로
온라인 게임에서의 성능이 직접 향상된다.

동작 흐름:
  1. (옵션) GCS에서 기존 가중치 다운로드 → 이어서 학습
  2. DB(`ai_arena.db`)에서 활성·공개 유저 봇 코드 최대 N개 로드
     - 부족하면 콜드스타트 봇(herbivore/mad_dog/camper)으로 채움
  3. RLBossBot 인스턴스 1개 생성 (싱글톤)
  4. N 에피소드 반복:
       - 매 에피소드마다 reset_for_episode() 호출
       - 보스 + 상대봇 4명을 GameEngine에 넣고 run_full_game()
       - 종료 후 on_episode_done(rank, n_bots)로 학습 + 로컬 저장
       - 진행 상황 로그(순위, epsilon, step, buffer)
  5. 완료 후 GCS에 최종 업로드

사용법:
    python train_boss_bot.py                       # 50 에피소드, GCS 자동
    python train_boss_bot.py --episodes 200
    python train_boss_bot.py --max-user-bots 6
    python train_boss_bot.py --no-gcs              # 로컬 파일만 사용
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

# battle_royale 루트(src/, bots/) + backend 루트(core/) 모두 sys.path에 추가
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT.parent))

from src.arena import gcs_weights  # noqa: E402

from core.bot_interface import BotInterface  # noqa: E402
from core.engine import GameEngine  # noqa: E402
from src.arena.server.boss.config import boss_battle_config  # noqa: E402

from bots.battle_royale.camper import CamperBot  # noqa: E402
from bots.battle_royale.herbivore import HerbivoreBot  # noqa: E402
from bots.battle_royale.mad_dog import MadDogBot  # noqa: E402
from bots.boss.rl_boss_bot import RLBossBot  # noqa: E402

logger = logging.getLogger("train_boss_bot")

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

BOSS_BOT_ID = "AI_보스"
N_BOTS_PER_EPISODE = 5  # 보스 1 + 상대 4 (프로덕션 min_bots와 동일한 규모)

COLDSTART_FACTORIES = [
    (HerbivoreBot, "초식"),
    (MadDogBot,    "미친개"),
    (CamperBot,    "존버"),
]

# 샘플 유저봇 — DB 봇이 없을 때 콜드스타트보다 우선 사용
try:
    from bots.battle_royale.sample_user_bots import SAMPLE_USER_BOTS
except ImportError:
    SAMPLE_USER_BOTS = []

WEIGHTS_PATH = _PROJECT_ROOT / "bots" / "boss" / "trained_weights.json"

# ---------------------------------------------------------------------------
# 유저 봇 어댑터 — app.py 의 InProcessBot 와 동일한 패턴
# ---------------------------------------------------------------------------

class _InProcessUserBot(BotInterface):
    """
    DB에 저장된 유저 코드를 같은 프로세스에서 실행하는 어댑터.
    `action(state)` 함수가 정의되어 있어야 하며,
    실행 중 예외가 발생하면 안전하게 STAY로 폴백한다.
    """

    def __init__(self, bot_id: str, code: str):
        self._bot_id = bot_id
        self._action_fn = None
        try:
            local_ns: dict = {"__builtins__": __builtins__}
            exec(code, local_ns)
            fn = local_ns.get("action")
            if fn is None or not callable(fn):
                raise ValueError("action(state) 함수를 찾을 수 없습니다.")
            self._action_fn = fn
        except Exception as exc:
            logger.warning("유저 봇 %s 코드 로드 실패: %s", bot_id, exc)

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def get_action(self, state: dict) -> str:
        if self._action_fn is None:
            return "STAY"
        try:
            result = self._action_fn(state)
            return str(result) if result else "STAY"
        except Exception:
            return "STAY"


# ---------------------------------------------------------------------------
# 상대 봇 풀 구성
# ---------------------------------------------------------------------------

def _load_user_bot_records(max_user_bots: int) -> list[tuple[str, str]]:
    """
    DB에서 활성 유저 봇 코드를 최대 max_user_bots 개 가져온다.
    반환: [(bot_id_label, code), ...]
    DB 접근 실패 시 빈 리스트 반환 (콜드스타트로 폴백).
    """
    if max_user_bots <= 0:
        return []

    try:
        from src.arena.db import init_db
    except Exception as exc:
        logger.warning("DB 모듈 import 실패: %s — 콜드스타트만 사용", exc)
        return []

    conn = None
    try:
        conn = init_db()
        # bot_repo에 모든 활성 봇을 불러오는 공용 메서드가 없으므로 직접 SELECT.
        cur = conn.execute(
            "SELECT id, name, code FROM bots "
            "WHERE is_active = 1 "
            "ORDER BY updated_at DESC LIMIT ?",
            (max_user_bots,),
        )
        rows = cur.fetchall()
        records: list[tuple[str, str]] = []
        for r in rows:
            label = f"USR_{r['id']:04d}_{r['name'][:12]}"
            code = r["code"] or ""
            if not code.strip():
                continue
            records.append((label, code))
        logger.info("DB에서 유저 봇 %d개 로드", len(records))
        return records
    except Exception as exc:
        logger.warning("DB에서 유저 봇 로드 실패: %s — 콜드스타트만 사용", exc)
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _build_opponents(
    user_bot_records: list[tuple[str, str]],
    n_opponents: int,
    seed: int,
    rng: random.Random,
) -> list[BotInterface]:
    """
    상대 봇 n_opponents 개를 만든다.
      - 가능한 한 유저 봇을 우선 사용 (라운드로빈으로 셔플)
      - 부족분은 콜드스타트 봇으로 채움
    """
    opponents: list[BotInterface] = []
    # 유저 봇 — 셔플해서 사용
    pool = list(user_bot_records)
    rng.shuffle(pool)

    used = 0
    for label, code in pool:
        if used >= n_opponents:
            break
        bot_id = f"{label}_{used:02d}"
        opponents.append(_InProcessUserBot(bot_id=bot_id, code=code))
        used += 1

    # 부족분은 샘플 유저봇 → 콜드스타트 순으로 채움
    sample_pool = list(SAMPLE_USER_BOTS)
    rng.shuffle(sample_pool)
    sample_idx = 0
    while len(opponents) < n_opponents:
        idx = len(opponents)
        if sample_idx < len(sample_pool):
            cls, label = sample_pool[sample_idx % len(sample_pool)]
            sample_idx += 1
        else:
            cls, label = rng.choice(COLDSTART_FACTORIES)
        opponents.append(cls(bot_id=f"{label}_{idx:02d}", seed=seed + idx))

    return opponents


# ---------------------------------------------------------------------------
# 결과 파싱
# ---------------------------------------------------------------------------

def _find_boss_rank(rankings: list[dict], n_bots: int) -> tuple[int, float, int]:
    for entry in rankings:
        if entry.get("id") == BOSS_BOT_ID:
            return (
                entry.get("rank", n_bots),
                float(entry.get("final_score", 0.0)),
                int(entry.get("survival_ticks", 0)),
            )
    return n_bots, 0.0, 0


# ---------------------------------------------------------------------------
# 메인 학습 루프
# ---------------------------------------------------------------------------

def train(
    n_episodes: int,
    max_user_bots: int,
    use_gcs: bool,
    base_seed: int = 42,
) -> None:
    rng = random.Random(base_seed)

    # 1) 가중치 다운로드 (GCS 활성 시)
    weights_path: Optional[Path] = WEIGHTS_PATH if WEIGHTS_PATH.exists() else None
    if use_gcs and gcs_weights.enabled():
        downloaded = gcs_weights.download()
        if downloaded:
            weights_path = downloaded
            logger.info("GCS에서 가중치 로드: %s", downloaded)
        else:
            logger.info("GCS 가중치 없음 — 로컬 파일/콜드스타트 사용")

    # 2) DB에서 유저 봇 로드
    user_bot_records = _load_user_bot_records(max_user_bots)
    if not user_bot_records:
        logger.info("유저 봇 0개 — 모든 상대를 콜드스타트 봇으로 구성")

    # 3) RLBossBot 싱글톤 생성
    boss = RLBossBot(
        bot_id=BOSS_BOT_ID,
        seed=rng.randint(0, 10_000),
        weights_path=weights_path,
    )

    print("=" * 70)
    print(f"  RLBossBot 오프라인 학습 시작")
    print(f"  에피소드: {n_episodes} | 봇/판: {N_BOTS_PER_EPISODE} | "
          f"유저봇: {len(user_bot_records)} | GCS: {use_gcs and gcs_weights.enabled()}")
    print(f"  시작 epsilon: {boss._epsilon:.3f} | "
          f"누적 에피소드: {boss._episode_count} | "
          f"누적 step: {boss._step_count}")
    print(f"  저장 경로: {WEIGHTS_PATH}")
    print("=" * 70)

    rank_history: list[int] = []
    score_history: list[float] = []
    t_start = time.time()

    n_opponents = N_BOTS_PER_EPISODE - 1

    for ep in range(1, n_episodes + 1):
        ep_seed = rng.randint(0, 1_000_000)

        # 틱 상태 초기화 — 가중치/버퍼/epsilon은 유지
        boss.reset_for_episode()

        opponents = _build_opponents(
            user_bot_records, n_opponents, ep_seed, rng,
        )
        all_bots: list[BotInterface] = [boss] + opponents

        try:
            engine = GameEngine(all_bots, config=boss_battle_config(), seed=ep_seed)
            result = engine.run_full_game()
        except Exception:
            logger.error(
                "에피소드 %d 실행 중 예외:\n%s", ep, traceback.format_exc(),
            )
            continue

        rank, score, survival = _find_boss_rank(
            result.rankings, N_BOTS_PER_EPISODE,
        )
        rank_history.append(rank)
        score_history.append(score)

        # 종료 보상 푸시 + 학습 + 로컬 저장 (+ GCS 업로드 N판마다)
        boss.on_episode_done(rank, N_BOTS_PER_EPISODE)

        elapsed = time.time() - t_start
        print(
            f"  [ep {ep:4d}/{n_episodes}] "
            f"rank={rank}/{N_BOTS_PER_EPISODE}  "
            f"score={score:7.1f}  surv={survival:3d}  "
            f"eps={boss._epsilon:.3f}  "
            f"step={boss._step_count:6d}  "
            f"buf={len(boss._buffer):5d}  "
            f"reason={result.reason.value}  "
            f"({elapsed:6.1f}s)"
        )

    # 4) 학습 종료 — 최종 저장 (버퍼 포함) + GCS 업로드
    print()
    print("=" * 70)
    print("  학습 완료")

    boss.save_weights(WEIGHTS_PATH, save_buffer=True)
    print(f"  로컬 저장 (버퍼 포함): {WEIGHTS_PATH}")

    if rank_history:
        avg_rank = sum(rank_history) / len(rank_history)
        avg_score = sum(score_history) / len(score_history)
        print(f"  평균 순위: {avg_rank:.2f} / {N_BOTS_PER_EPISODE}")
        print(f"  평균 점수: {avg_score:.1f}")
    print(f"  최종 epsilon: {boss._epsilon:.3f}")
    print(f"  최종 step:    {boss._step_count}")
    print(f"  버퍼 크기:    {len(boss._buffer)}")
    print(f"  총 소요:      {time.time() - t_start:.1f}s")

    if use_gcs and gcs_weights.enabled():
        ok = gcs_weights.upload(WEIGHTS_PATH)
        if ok:
            print(f"  GCS 최종 업로드 완료")
        else:
            print(f"  GCS 업로드 실패 — 로컬 파일은 보존됨", file=sys.stderr)
    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="RLBossBot 오프라인 학습 (유저 공개 봇 vs 보스)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--episodes", type=int, default=50,
        help="총 학습 에피소드 수",
    )
    p.add_argument(
        "--max-user-bots", type=int, default=10,
        help="DB에서 불러올 유저 봇 최대 개수 (부족분은 콜드스타트로 보충)",
    )
    p.add_argument(
        "--no-gcs", action="store_true",
        help="GCS 다운/업로드 건너뛰고 로컬 파일만 사용",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="랜덤 시드",
    )
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()

    if args.episodes <= 0:
        print("오류: --episodes 는 1 이상이어야 합니다.", file=sys.stderr)
        return 1

    train(
        n_episodes=args.episodes,
        max_user_bots=args.max_user_bots,
        use_gcs=not args.no_gcs,
        base_seed=args.seed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

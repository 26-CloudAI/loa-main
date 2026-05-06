"""
RLBossBot 강화학습 훈련 스크립트
=================================

여러 에피소드(게임)를 반복 실행하면서 RLBossBot의 Q-가중치를 누적 학습한다.

동작 원리:
  1. 매 에피소드마다 RLBossBot 1개 + 상대 봇 N-1개(herbivore/mad_dog/camper 랜덤 조합)
  2. GameEngine.run_full_game() 으로 한 판 완주 — 봇 내부에서 온라인 TD 업데이트 수행
  3. 에피소드 종료 후 boss bot 인스턴스에서 현재 가중치를 꺼내 다음 에피소드에 전달
  4. 100 에피소드마다 평균 순위 / 평균 점수 출력
  5. 학습 완료 후 저장 (GCS 또는 로컬)

사용법:
    python train_boss_bot.py                           # 500 에피소드, 로컬 저장
    python train_boss_bot.py --episodes 50             # 빠른 테스트
    python train_boss_bot.py --gcs-uri gs://bucket/trained_weights.json
    python train_boss_bot.py --episodes 1000 --bots 6 --seed 0

GCS 모드 (Cloud Run Job):
  --gcs-uri 를 주거나 BOSS_WEIGHTS_GCS_URI 환경변수 설정 시:
    1. GCS에서 기존 가중치 다운로드 (이어서 학습)
    2. 훈련 완료 후 GCS에 atomic 업로드
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent))

import gcs_weights

from src.arena.config import DEFAULT_CONFIG
from src.arena.engine import GameEngine
from bots.herbivore import HerbivoreBot
from bots.mad_dog import MadDogBot
from bots.camper import CamperBot
from bots.rl_boss_bot import RLBossBot

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

BOSS_BOT_ID = "boss_rl"
OPPONENTS = [
    (HerbivoreBot, "초식"),
    (MadDogBot,    "미친개"),
    (CamperBot,    "존버"),
]

# 학습 중 탐색 엡실론 (온라인 업데이트를 유도하기 위해 기본값보다 높게)
TRAIN_EPSILON = 0.30   # 학습 중 탐색률
EVAL_EPSILON = 0.05    # 평가/저장 시 착취 위주

WEIGHTS_PATH = Path(__file__).parent / "bots" / "trained_weights.json"

# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def _create_opponent_bots(
    n: int,
    base_seed: int,
    rng: random.Random,
) -> list:
    """n개의 상대 봇을 랜덤하게 생성한다."""
    bots = []
    for i in range(n):
        cls, label = rng.choice(OPPONENTS)
        bots.append(cls(bot_id=f"{label}_{i:02d}", seed=base_seed + i))
    return bots


def _find_boss_rank(rankings: list[dict]) -> tuple[int, float, int]:
    """
    rankings 에서 boss bot 항목을 찾아 (순위, 최종점수, 생존틱)를 반환.
    못 찾으면 (총 봇 수, 0.0, 0) 반환.
    """
    n = len(rankings)
    for entry in rankings:
        if entry.get("id") == BOSS_BOT_ID:
            return entry["rank"], entry["final_score"], entry["survival_ticks"]
    return n, 0.0, 0


# ---------------------------------------------------------------------------
# 메인 훈련 루프
# ---------------------------------------------------------------------------

def train(
    n_episodes: int = 500,
    n_bots: int = 5,
    base_seed: int = 42,
    verbose: bool = False,
    gcs_uri: str = "",
) -> None:
    rng = random.Random(base_seed)

    # GCS에서 기존 가중치 가져오기 (이어서 학습)
    local_weights = WEIGHTS_PATH
    if gcs_uri or gcs_weights.enabled():
        downloaded = gcs_weights.download(gcs_uri)
        if downloaded:
            local_weights = downloaded
            print(f"  GCS에서 가중치 로드: {gcs_uri or gcs_weights._GCS_URI}")
        else:
            print("  GCS 가중치 없음 — 처음부터 학습")

    print("=" * 65)
    print(f"  RLBossBot 훈련 시작")
    print(f"  에피소드: {n_episodes} | 총 봇 수: {n_bots} | 기본 시드: {base_seed}")
    print(f"  탐색 엡실론: {TRAIN_EPSILON} | 저장 경로: {local_weights}")
    print("=" * 65)

    # 첫 에피소드용 boss bot — 기존 가중치 있으면 자동 로드
    boss_bot = RLBossBot(
        bot_id=BOSS_BOT_ID,
        seed=rng.randint(0, 10_000),
        epsilon_override=TRAIN_EPSILON,
        weights_path=local_weights,
    )

    # 누적 통계
    rank_history: list[int] = []
    score_history: list[float] = []
    survival_history: list[int] = []

    best_avg_rank = float("inf")
    best_weights: list[list[float]] | None = None

    t_start = time.time()

    for ep in range(1, n_episodes + 1):
        ep_seed = rng.randint(0, 1_000_000)
        n_opponents = n_bots - 1

        # 틱 상태만 초기화 — 버퍼·가중치는 에피소드 간 유지
        boss_bot.reset_for_episode()

        opponent_bots = _create_opponent_bots(n_opponents, ep_seed, rng)
        all_bots = [boss_bot] + opponent_bots

        engine = GameEngine(all_bots, config=DEFAULT_CONFIG, seed=ep_seed)
        result = engine.run_full_game()

        rank, score, survival = _find_boss_rank(result.rankings)
        rank_history.append(rank)
        score_history.append(score)
        survival_history.append(survival)

        if verbose:
            print(
                f"  [ep {ep:4d}] 순위: {rank}/{n_bots} | "
                f"점수: {score:7.1f} | 생존틱: {survival:3d} | "
                f"버퍼: {len(boss_bot._buffer):5d} | "
                f"종료: {result.reason.value}"
            )

        # 종료 보상 push + 추가 학습(×4) + 가중치 저장(버퍼 제외)
        boss_bot.on_episode_done(rank, n_bots)

        # ------------------------------------------------------------------
        # 100 에피소드마다 진행 상황 출력
        # ------------------------------------------------------------------
        if ep % 100 == 0 or ep == n_episodes:
            window = min(100, ep)
            avg_rank = sum(rank_history[-window:]) / window
            avg_score = sum(score_history[-window:]) / window
            avg_survival = sum(survival_history[-window:]) / window
            elapsed = time.time() - t_start

            print(
                f"[ep {ep:4d}/{n_episodes}] "
                f"최근{window}ep 평균 순위: {avg_rank:.2f}/{n_bots} | "
                f"평균 점수: {avg_score:8.1f} | "
                f"평균 생존틱: {avg_survival:.1f} | "
                f"버퍼: {len(boss_bot._buffer):5d} | "
                f"경과: {elapsed:.1f}s"
            )

            # 평균 순위가 개선되면 베스트 가중치 갱신
            if avg_rank < best_avg_rank:
                best_avg_rank = avg_rank
                best_weights = boss_bot.get_weights()
                print(f"  -> 베스트 가중치 갱신 (평균 순위 {avg_rank:.2f})")

    # ------------------------------------------------------------------
    # 훈련 완료 — 베스트 가중치 + 누적 버퍼 최종 저장
    # ------------------------------------------------------------------
    print()
    print("=" * 65)
    print("  훈련 완료!")

    # 저장할 가중치 결정: 베스트가 있으면 베스트, 없으면 마지막
    save_weights = best_weights if best_weights is not None else boss_bot.get_weights()
    boss_bot.set_weights(save_weights)
    # 최종 저장은 버퍼 포함 — 다음 훈련 시 ep1부터 즉시 학습 가능
    boss_bot.save_weights(local_weights, save_buffer=True)

    total_avg_rank = sum(rank_history) / len(rank_history)
    total_avg_score = sum(score_history) / len(score_history)
    elapsed_total = time.time() - t_start

    print(f"  전체 평균 순위 : {total_avg_rank:.2f} / {n_bots}")
    print(f"  전체 평균 점수 : {total_avg_score:.1f}")
    print(f"  총 소요 시간   : {elapsed_total:.1f}s")
    print(f"  가중치 저장 위치: {local_weights}")
    print("=" * 65)

    # GCS에 업로드
    if gcs_uri or gcs_weights.enabled():
        ok = gcs_weights.upload(local_weights, gcs_uri)
        if ok:
            print(f"  GCS 업로드 완료: {gcs_uri or gcs_weights._GCS_URI}")
        else:
            print("  GCS 업로드 실패 — 로컬 파일은 보존됨", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI 진입점
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RLBossBot 강화학습 훈련 스크립트",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--episodes", "-e",
        type=int,
        default=500,
        help="총 훈련 에피소드 수",
    )
    parser.add_argument(
        "--bots", "-b",
        type=int,
        default=5,
        help="에피소드당 총 봇 수 (boss 포함, 최소 2)",
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=42,
        help="랜덤 시드",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="매 에피소드 결과 출력",
    )
    parser.add_argument(
        "--gcs-uri",
        type=str,
        default="",
        help="GCS 가중치 경로 (예: gs://bucket/trained_weights.json). "
             "BOSS_WEIGHTS_GCS_URI 환경변수로도 설정 가능",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.bots < 2:
        print("오류: --bots 는 최소 2 이상이어야 합니다.", file=sys.stderr)
        sys.exit(1)

    train(
        n_episodes=args.episodes,
        n_bots=args.bots,
        base_seed=args.seed,
        verbose=args.verbose,
        gcs_uri=args.gcs_uri,
    )

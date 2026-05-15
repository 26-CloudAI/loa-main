"""
RLBossBotTorch 병렬 강화학습 스크립트
=======================================

N개의 worker 프로세스가 동시에 게임 에피소드를 실행하고,
SYNC_EVERY 에피소드마다 가중치를 공유 체크포인트로 동기화한다.

아키텍처:
  worker_0 ──┐
  worker_1 ──┤── 체크포인트(trained_weights_torch.pt) ──┐
  ...        ┘                                          └── GCS 업로드
  worker_N-1─┘

각 worker:
  1. 독립 RLBossBotTorch 인스턴스 + GameEngine 실행
  2. 에피소드마다 on_episode_done() 호출 → 로컬 학습
  3. SYNC_EVERY 에피소드마다 공유 체크포인트에서 최신 가중치 로드
  4. 로컬 가중치를 공유 체크포인트에 저장 (파일 잠금)

비용 예상 (GCP Spot g2-standard-4, L4 GPU):
  - $0.21/hr × 24hr × 14일 ≈ $71 (약 10만원)
  - 2주 학습 후 충분한 수렴 기대

사용법:
  # 기본 (8 workers, 1000 에피소드/worker)
  python train_boss_parallel.py

  # 커스텀
  python train_boss_parallel.py --workers 4 --episodes 500 --no-gcs

  # CPU 강제 (GPU 없는 환경)
  python train_boss_parallel.py --device cpu

  # 단일 프로세스 디버그
  python train_boss_parallel.py --workers 1 --episodes 10
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import random
import sys
import time
import traceback
from multiprocessing import Process, Queue, current_process
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.arena.bot_interface import BotInterface
from src.arena.config import DEFAULT_CONFIG
from src.arena.engine import GameEngine

from bots.camper import CamperBot
from bots.herbivore import HerbivoreBot
from bots.mad_dog import MadDogBot

logger = logging.getLogger("train_parallel")

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

BOSS_BOT_ID    = "AI_보스"
N_BOTS_PER_EP  = 5        # 보스 1 + 상대 4
SYNC_EVERY     = 5        # 이 에피소드마다 체크포인트 동기화
LOCK_FILE      = _PROJECT_ROOT / "bots" / ".train_lock"
WEIGHTS_PATH   = _PROJECT_ROOT / "bots" / "trained_weights_torch.pt"

COLDSTART_FACTORIES = [
    (HerbivoreBot, "초식"),
    (MadDogBot,    "미친개"),
    (CamperBot,    "존버"),
]

try:
    from bots.sample_user_bots import SAMPLE_USER_BOTS
except ImportError:
    SAMPLE_USER_BOTS = []


# ---------------------------------------------------------------------------
# 유저봇 어댑터
# ---------------------------------------------------------------------------

class _InProcessUserBot(BotInterface):
    def __init__(self, bot_id: str, code: str):
        self._bot_id = bot_id
        self._action_fn = None
        try:
            ns: dict = {"__builtins__": __builtins__}
            exec(code, ns)
            fn = ns.get("action")
            if callable(fn):
                self._action_fn = fn
        except Exception:
            pass

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


def _load_user_bots(max_n: int) -> list[tuple[str, str]]:
    if max_n <= 0:
        return []
    try:
        from src.arena.db import init_db
        conn = init_db()
        cur = conn.execute(
            "SELECT id, name, code FROM bots WHERE is_active=1 "
            "ORDER BY updated_at DESC LIMIT ?", (max_n,)
        )
        rows = cur.fetchall()
        conn.close()
        return [(f"USR_{r['id']:04d}_{r['name'][:12]}", r["code"] or "")
                for r in rows if (r["code"] or "").strip()]
    except Exception:
        return []


def _build_opponents(user_records, n, seed, rng) -> list[BotInterface]:
    pool = list(user_records)
    rng.shuffle(pool)
    opponents = []
    for label, code in pool[:n]:
        opponents.append(_InProcessUserBot(f"{label}_{len(opponents):02d}", code))

    sample_pool = list(SAMPLE_USER_BOTS)
    rng.shuffle(sample_pool)
    si = 0
    while len(opponents) < n:
        idx = len(opponents)
        if si < len(sample_pool):
            cls, label = sample_pool[si % len(sample_pool)]
            si += 1
        else:
            cls, label = rng.choice(COLDSTART_FACTORIES)
        opponents.append(cls(bot_id=f"{label}_{idx:02d}", seed=seed + idx))
    return opponents


def _find_boss_rank(rankings, n_bots):
    for e in rankings:
        if e.get("id") == BOSS_BOT_ID:
            return e.get("rank", n_bots), float(e.get("final_score", 0.0))
    return n_bots, 0.0


# ---------------------------------------------------------------------------
# 파일 잠금 유틸
# ---------------------------------------------------------------------------

class FileLock:
    """Unix 파일 잠금 (멀티프로세스 동기화)."""

    def __init__(self, path: Path):
        self._path = path
        self._fd   = None

    def __enter__(self):
        self._fd = open(self._path, "w")
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_):
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        self._fd.close()


# ---------------------------------------------------------------------------
# Worker 프로세스
# ---------------------------------------------------------------------------

def _worker(
    worker_id: int,
    n_episodes: int,
    user_records: list,
    device: str,
    max_user_bots: int,
    result_queue: Queue,
    base_seed: int,
) -> None:
    """
    단일 worker 프로세스 메인 루프.
    독립적으로 에피소드를 실행하고 SYNC_EVERY마다 체크포인트 동기화.
    """
    logging.basicConfig(
        level=logging.WARNING,
        format=f"%(asctime)s [W{worker_id}] %(message)s",
    )

    # worker마다 시드 분기
    rng   = random.Random(base_seed + worker_id * 1000)
    seed  = rng.randint(0, 999_999)

    try:
        from bots.rl_boss_bot_torch import RLBossBotTorch
        boss = RLBossBotTorch(
            bot_id=BOSS_BOT_ID,
            seed=seed,
            weights_path=WEIGHTS_PATH if WEIGHTS_PATH.exists() else None,
            device=device,
        )
    except Exception as exc:
        result_queue.put({"worker_id": worker_id, "error": str(exc)})
        return

    rank_hist, score_hist = [], []
    t_start = time.time()

    for ep in range(1, n_episodes + 1):
        ep_seed = rng.randint(0, 1_000_000)
        boss.reset_for_episode()

        opponents = _build_opponents(user_records, N_BOTS_PER_EP - 1, ep_seed, rng)
        all_bots: list[BotInterface] = [boss] + opponents

        try:
            engine = GameEngine(all_bots, config=DEFAULT_CONFIG, seed=ep_seed)
            result = engine.run_full_game()
        except Exception:
            logger.debug("W%d ep%d 예외: %s", worker_id, ep, traceback.format_exc())
            continue

        rank, score = _find_boss_rank(result.rankings, N_BOTS_PER_EP)
        rank_hist.append(rank)
        score_hist.append(score)

        boss.on_episode_done(rank, N_BOTS_PER_EP)

        # ── 체크포인트 동기화 ──────────────────────────────────────────
        if ep % SYNC_EVERY == 0:
            try:
                with FileLock(LOCK_FILE):
                    # 최신 checkpoint 로드 (다른 worker가 더 많이 학습했을 수 있음)
                    if WEIGHTS_PATH.exists():
                        import torch
                        ckpt = torch.load(WEIGHTS_PATH, map_location=boss._device, weights_only=True)
                        if ckpt.get("step_count", 0) > boss._step_count:
                            boss.set_weights_state_dict({
                                "online": ckpt["online"],
                                "target": ckpt["target"],
                                "step_count": ckpt["step_count"],
                                "episode_count": ckpt["episode_count"],
                                "epsilon": ckpt.get("epsilon", boss._epsilon),
                            })
                    # 현재 가중치 저장
                    boss.save_weights()
            except Exception as exc:
                logger.debug("W%d sync 실패: %s", worker_id, exc)

        elapsed = time.time() - t_start
        print(
            f"  [W{worker_id} ep{ep:4d}/{n_episodes}] "
            f"rank={rank}/{N_BOTS_PER_EP}  score={score:7.1f}  "
            f"eps={boss._epsilon:.3f}  step={boss._step_count:6d}  "
            f"buf={len(boss._buffer):5d}  ({elapsed:6.1f}s)"
        )

    # 최종 결과 리포트
    result_queue.put({
        "worker_id":   worker_id,
        "episodes":    len(rank_hist),
        "avg_rank":    sum(rank_hist) / len(rank_hist) if rank_hist else 0,
        "avg_score":   sum(score_hist) / len(score_hist) if score_hist else 0,
        "epsilon":     boss._epsilon,
        "step_count":  boss._step_count,
        "buffer_size": len(boss._buffer),
    })


# ---------------------------------------------------------------------------
# 메인 학습 루프
# ---------------------------------------------------------------------------

def train(
    n_workers:    int,
    n_episodes:   int,
    max_user_bots: int,
    device:       str,
    use_gcs:      bool,
    base_seed:    int,
) -> None:
    # 잠금 파일 초기화
    LOCK_FILE.touch(exist_ok=True)

    # 유저봇 로드 (메인 프로세스에서 한 번만)
    user_records = _load_user_bots(max_user_bots)
    print(f"유저봇 {len(user_records)}개 로드")

    # GCS 초기 다운로드
    if use_gcs:
        try:
            import gcs_weights
            if gcs_weights.enabled():
                downloaded = gcs_weights.download()
                if downloaded:
                    print(f"GCS에서 가중치 로드: {downloaded}")
        except Exception:
            pass

    print("=" * 70)
    print(f"  병렬 학습 시작")
    print(f"  workers={n_workers}  episodes/worker={n_episodes}  device={device}")
    print(f"  총 에피소드: {n_workers * n_episodes}")
    print(f"  체크포인트: {WEIGHTS_PATH}")
    print("=" * 70)

    result_queue: Queue = Queue()
    processes = []

    for wid in range(n_workers):
        p = Process(
            target=_worker,
            args=(wid, n_episodes, user_records, device,
                  max_user_bots, result_queue, base_seed),
            daemon=True,
        )
        p.start()
        processes.append(p)
        # worker 시작 간격 (GIL 충돌 방지)
        time.sleep(0.5)

    # 모든 worker 완료 대기
    for p in processes:
        p.join()

    # 결과 수집
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())

    # 최종 요약
    print()
    print("=" * 70)
    print("  학습 완료")
    for r in sorted(results, key=lambda x: x.get("worker_id", 0)):
        if "error" in r:
            print(f"  W{r['worker_id']}: 오류 — {r['error']}")
        else:
            print(
                f"  W{r['worker_id']}: ep={r['episodes']}  "
                f"avg_rank={r['avg_rank']:.2f}  avg_score={r['avg_score']:.1f}  "
                f"eps={r['epsilon']:.3f}  step={r['step_count']}"
            )

    # GCS 최종 업로드
    if use_gcs and WEIGHTS_PATH.exists():
        try:
            import gcs_weights
            if gcs_weights.enabled():
                ok = gcs_weights.upload(WEIGHTS_PATH)
                print(f"  GCS 최종 업로드: {'성공' if ok else '실패'}")
        except Exception:
            pass
    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="RLBossBotTorch 병렬 학습 (PyTorch + GPU)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--workers",        type=int,   default=8,
                   help="병렬 worker 수 (코어 수와 맞추기 권장)")
    p.add_argument("--episodes",       type=int,   default=500,
                   help="worker당 에피소드 수")
    p.add_argument("--max-user-bots",  type=int,   default=10,
                   help="DB에서 불러올 유저봇 최대 수")
    p.add_argument("--device",         type=str,   default="auto",
                   help="학습 device: auto / cuda / cpu")
    p.add_argument("--no-gcs",         action="store_true",
                   help="GCS 업/다운로드 건너뜀")
    p.add_argument("--seed",           type=int,   default=42)
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = _parse()

    # device 자동 감지
    device = args.device
    if device == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                print(f"GPU 감지: {torch.cuda.get_device_name(0)}")
            else:
                device = "cpu"
                print("GPU 없음 — CPU 사용")
        except ImportError:
            print("PyTorch 없음 — 설치 필요: pip install torch")
            return 1

    train(
        n_workers     = args.workers,
        n_episodes    = args.episodes,
        max_user_bots = args.max_user_bots,
        device        = device,
        use_gcs       = not args.no_gcs,
        base_seed     = args.seed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

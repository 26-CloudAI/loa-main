"""
RLBossBotTorch 병렬 강화학습 스크립트
=======================================

GCS의 quality_bots.json에서 품질 봇을 읽어 병렬 학습한다.
비용 상한선 적용으로 악의적 덤핑 등 예외 상황에서도 비용이 통제된다.

비용 안전장치 (3중):
  MAX_BOTS_PER_SESSION  세션당 학습 봇 최대 수 (rating 상위 선택)
  MAX_EPISODES_TOTAL    세션당 총 에피소드 상한
  MAX_RUNTIME_HOURS     이 시간 초과 시 worker 강제 종료 후 self-stop

스마트 스케줄링:
  MIN_NEW_BOTS          신규 봇 이 수 미만 AND 마지막 학습 7일 미경과 → 즉시 self-stop
  학습 후 GCS에 training_meta.json + trained_bot_history.json 갱신
  VM self-stop (GCP metadata API 사용)

사용법:
  python train_boss_parallel.py                     # 기본값
  python train_boss_parallel.py --workers 6 --episodes-per-worker 100
  python train_boss_parallel.py --device cpu --no-gcs   # 로컬 디버그

GCP Cloud Scheduler 설정 (권장):
  대상: VM startup (또는 gcloud compute instances start)
  스케줄: 0 2 * * *  (매일 새벽 2시)
  VM startup-script에서 이 스크립트를 실행하면 자동 판단 후 self-stop.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import platform
import random
import signal
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from multiprocessing import Process, Queue
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.arena.bot_interface import BotInterface
from src.arena.config import DEFAULT_CONFIG
from src.arena.engine import GameEngine

from bots.battle_royale.camper import CamperBot
from bots.battle_royale.herbivore import HerbivoreBot
from bots.battle_royale.mad_dog import MadDogBot
import gcs_weights

logger = logging.getLogger("train_parallel")

# ---------------------------------------------------------------------------
# 비용 안전장치 상수
# ---------------------------------------------------------------------------

MAX_BOTS_PER_SESSION   = 20    # 세션당 최대 학습 봇 수 (rating 상위 선택)
MAX_EPISODES_TOTAL     = 600   # 세션 전체 최대 에피소드 (worker 합산)
MAX_RUNTIME_HOURS      = 7     # 이 시간 초과 시 강제 종료
MAX_TRAINING_PER_DAY   = 1     # 하루 최대 학습 세션 (중복 방지)

# 스케줄링
MIN_NEW_BOTS           = 3     # 신규 봇 이 수 이상이어야 학습 시작
FORCE_RETRAIN_DAYS     = 7     # 신규 봇 없어도 N일 경과 시 재학습
BOT_HISTORY_SESSIONS   = 3     # 최근 N 세션 봇은 중복 학습 제외

# 게임 구성
BOSS_BOT_ID            = "AI_보스"
N_BOTS_PER_EP          = 5

COLDSTART_FACTORIES = [
    (HerbivoreBot, "초식"),
    (MadDogBot,    "미친개"),
    (CamperBot,    "존버"),
]

try:
    from bots.battle_royale.sample_user_bots import SAMPLE_USER_BOTS
except ImportError:
    SAMPLE_USER_BOTS = []

WEIGHTS_PATH     = _PROJECT_ROOT / "bots" / "trained_weights_torch.pt"
LOCK_FILE        = _PROJECT_ROOT / "bots" / ".train_lock"
META_FILENAME    = "training_meta.json"
HISTORY_FILENAME = "trained_bot_history.json"


# ---------------------------------------------------------------------------
# GCP self-stop
# ---------------------------------------------------------------------------

def _gcp_self_stop() -> None:
    """GCP 메타데이터 API로 현재 VM 인스턴스를 종료한다."""
    try:
        import urllib.request
        meta = "http://metadata.google.internal/computeMetadata/v1/instance"
        headers = {"Metadata-Flavor": "Google"}

        def _get(path: str) -> str:
            req = urllib.request.Request(f"{meta}/{path}", headers=headers)
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.read().decode()

        name = _get("name")
        zone = _get("zone").split("/")[-1]
        logger.info("VM 자동 종료: %s (zone=%s)", name, zone)
        import subprocess
        subprocess.run(
            ["gcloud", "compute", "instances", "stop", name, "--zone", zone, "--quiet"],
            check=False,
        )
    except Exception as exc:
        logger.warning("self-stop 실패 (로컬 환경이거나 권한 없음): %s", exc)


# ---------------------------------------------------------------------------
# 품질 봇 로딩 및 필터
# ---------------------------------------------------------------------------

def _load_quality_bots() -> list[dict]:
    """GCS 또는 로컬에서 quality_bots.json을 로드한다."""
    data = None
    if gcs_weights.enabled():
        data = gcs_weights.download_json("quality_bots.json")

    if data is None:
        local = _PROJECT_ROOT / "bots" / "quality_bots.json"
        if local.exists():
            data = json.loads(local.read_text())
            logger.info("로컬 quality_bots.json 로드")

    if data is None:
        logger.warning("quality_bots.json 없음 — 학습 봇 없이 진행")
        return []

    bots = data.get("bots", [])
    logger.info("품질 봇 로드: %d개 (내보낸 시각: %s)", len(bots), data.get("exported_at", "?"))
    return bots


def _load_bot_history() -> list[dict]:
    """이미 학습한 봇 이력 로드. {session, bot_ids} 리스트 (최신순)."""
    data = None
    if gcs_weights.enabled():
        data = gcs_weights.download_json(HISTORY_FILENAME)
    if data is None:
        local = _PROJECT_ROOT / "bots" / HISTORY_FILENAME
        if local.exists():
            data = json.loads(local.read_text())
    return data if isinstance(data, list) else []


def _save_bot_history(history: list[dict], new_bot_ids: list[int]) -> None:
    """이번 세션 학습 봇 ID를 이력에 추가하고 저장 (최근 BOT_HISTORY_SESSIONS 유지)."""
    entry = {
        "session":  datetime.now(timezone.utc).isoformat(),
        "bot_ids":  new_bot_ids,
    }
    history = [entry] + history
    history = history[:BOT_HISTORY_SESSIONS]

    if gcs_weights.enabled():
        gcs_weights.upload_json(history, HISTORY_FILENAME)
    else:
        local = _PROJECT_ROOT / "bots" / HISTORY_FILENAME
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(json.dumps(history, ensure_ascii=False, indent=2))


def _select_training_bots(
    quality_bots: list[dict], history: list[dict]
) -> tuple[list[dict], list[int]]:
    """
    이미 학습한 봇을 제외하고 rating 상위 MAX_BOTS_PER_SESSION개 선택.
    반환: (선택된 봇 목록, 선택된 봇 ID 목록).
    id/code 누락 항목은 안전하게 건너뛴다.
    """
    trained_ids: set[int] = set()
    for session in history:
        trained_ids.update(session.get("bot_ids", []))

    def _valid(b: dict) -> bool:
        return (
            isinstance(b, dict)
            and isinstance(b.get("id"), int)
            and isinstance(b.get("code"), str)
            and b["code"].strip()
            and b["id"] not in trained_ids
        )

    new_bots = [b for b in quality_bots if _valid(b)]
    new_bots.sort(key=lambda x: x.get("rating", 0), reverse=True)
    selected = new_bots[:MAX_BOTS_PER_SESSION]
    return selected, [b["id"] for b in selected]


def _check_last_training_time(history: list[dict]) -> datetime | None:
    """마지막 학습 세션 시각 반환. 없으면 None."""
    if not history:
        return None
    try:
        return datetime.fromisoformat(history[0]["session"])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 유저봇 어댑터
# ---------------------------------------------------------------------------

# 학습 VM에서 유저 코드를 실행하므로 가능한 한 능력을 제한한다.
# 완전한 샌드박스는 아니지만 (실제 격리는 컨테이너/seccomp가 필요),
# 우발적·평이한 악성 코드의 직접적인 자격증명 접근/파일 IO/네트워크를 차단한다.
_FORBIDDEN_BUILTINS = frozenset({
    "open", "exec", "eval", "compile", "__import__",
    "input", "breakpoint", "memoryview",
    "globals", "vars",
})


def _restricted_builtins() -> dict:
    import builtins as _b
    safe = {}
    for name in dir(_b):
        if name.startswith("_"):
            continue
        if name in _FORBIDDEN_BUILTINS:
            continue
        safe[name] = getattr(_b, name)
    # 학습 봇이 필요로 할 수 있는 최소 객체만 노출
    return safe


_RESTRICTED_BUILTINS = _restricted_builtins()


class _InProcessUserBot(BotInterface):
    def __init__(self, bot_id: str, code: str):
        self._bot_id = bot_id
        self._action_fn = None
        try:
            ns: dict = {"__builtins__": _RESTRICTED_BUILTINS}
            exec(code, ns)
            fn = ns.get("action")
            if callable(fn):
                self._action_fn = fn
        except Exception:
            # 악성/문법오류 코드는 STAY만 반환하도록 비활성 처리
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


def _build_opponents(user_bots: list[dict], n: int, seed: int, rng: random.Random) -> list[BotInterface]:
    pool = list(user_bots)
    rng.shuffle(pool)
    opponents: list[BotInterface] = []
    for b in pool[:n]:
        opponents.append(_InProcessUserBot(f"USR_{b['id']}", b["code"]))

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


def _find_boss_rank(rankings, n_bots) -> tuple[int, float, int]:
    for e in rankings:
        if e.get("id") == BOSS_BOT_ID:
            return e.get("rank", n_bots), float(e.get("final_score", 0.0)), int(e.get("survival_ticks", 0))
    return n_bots, 0.0, 0


# ---------------------------------------------------------------------------
# 파일 잠금
# ---------------------------------------------------------------------------

class FileLock:
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
    training_bots: list[dict],
    device: str,
    result_queue: Queue,
    base_seed: int,
    t_start_unix: float,
) -> None:
    logging.basicConfig(level=logging.WARNING,
                        format=f"%(asctime)s [W{worker_id}] %(message)s")

    rng  = random.Random(base_seed + worker_id * 1000)
    seed = rng.randint(0, 999_999)

    try:
        from bots.boss.rl_boss_bot_torch import RLBossBotTorch
        boss = RLBossBotTorch(
            bot_id=BOSS_BOT_ID,
            seed=seed,
            weights_path=WEIGHTS_PATH if WEIGHTS_PATH.exists() else None,
            device=device,
        )
    except Exception as exc:
        result_queue.put({"worker_id": worker_id, "error": str(exc)})
        return

    rank_hist, score_hist, kill_hist = [], [], []
    t_local = time.time()
    deadline = t_start_unix + MAX_RUNTIME_HOURS * 3600

    for ep in range(1, n_episodes + 1):
        # 런타임 상한 체크
        if time.time() > deadline:
            logger.warning("W%d: 런타임 상한(%dh) 초과 — 종료", worker_id, MAX_RUNTIME_HOURS)
            break

        ep_seed = rng.randint(0, 1_000_000)
        boss.reset_for_episode()

        opponents = _build_opponents(training_bots, N_BOTS_PER_EP - 1, ep_seed, rng)
        all_bots: list[BotInterface] = [boss] + opponents

        try:
            engine = GameEngine(all_bots, config=DEFAULT_CONFIG, seed=ep_seed)
            result = engine.run_full_game()
        except Exception:
            logger.debug("W%d ep%d 예외: %s", worker_id, ep, traceback.format_exc())
            continue

        rank, score, surv = _find_boss_rank(result.rankings, N_BOTS_PER_EP)
        rank_hist.append(rank)
        score_hist.append(score)

        boss.on_episode_done(rank, N_BOTS_PER_EP)

        # 주기적 체크포인트 동기화
        if ep % 10 == 0:
            try:
                with FileLock(LOCK_FILE):
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
                    boss.save_weights()
            except Exception as exc:
                logger.debug("W%d sync 실패: %s", worker_id, exc)

        elapsed = time.time() - t_local
        wins = sum(1 for r in rank_hist if r == 1)
        print(
            f"  [W{worker_id} ep{ep:4d}/{n_episodes}] "
            f"rank={rank}/{N_BOTS_PER_EP}  score={score:7.1f}  "
            f"win_rate={wins/len(rank_hist)*100:.0f}%  "
            f"eps={boss._epsilon:.3f}  step={boss._step_count:6d}  "
            f"({elapsed:.0f}s)"
        )

    wins = sum(1 for r in rank_hist if r == 1)
    result_queue.put({
        "worker_id":    worker_id,
        "episodes":     len(rank_hist),
        "avg_rank":     sum(rank_hist) / len(rank_hist) if rank_hist else 0,
        "avg_score":    sum(score_hist) / len(score_hist) if score_hist else 0,
        "win_rate":     wins / len(rank_hist) if rank_hist else 0,
        "epsilon":      boss._epsilon,
        "step_count":   boss._step_count,
        "buffer_size":  len(boss._buffer),
        "total_episodes": boss._episode_count,
    })


# ---------------------------------------------------------------------------
# 메인 학습 루프
# ---------------------------------------------------------------------------

def train(
    n_workers:       int,
    episodes_per_worker: int,
    device:          str,
    use_gcs:         bool,
    base_seed:       int,
    force:           bool,
    self_stop:       bool,
) -> None:
    LOCK_FILE.touch(exist_ok=True)
    t_start = time.time()

    # ── 품질 봇 로드 및 선택 ──────────────────────────────────────────────
    quality_bots = _load_quality_bots()
    history      = _load_bot_history()
    selected_bots, selected_ids = _select_training_bots(quality_bots, history)
    last_training = _check_last_training_time(history)

    n_new = len(selected_bots)
    days_since = (
        (datetime.now(timezone.utc) - last_training).days
        if last_training else 999
    )

    print("=" * 70)
    print(f"  RLBossBotTorch 병렬 학습")
    print(f"  품질 봇: 전체 {len(quality_bots)}개 → 신규 {n_new}개 선정")
    print(f"  마지막 학습: {days_since}일 전")
    print(f"  비용 상한: 봇 {MAX_BOTS_PER_SESSION}개 / 총 {MAX_EPISODES_TOTAL}ep / {MAX_RUNTIME_HOURS}h")
    print("=" * 70)

    # ── 스마트 스케줄링: 조건 미충족 시 종료 ─────────────────────────────
    should_train = (
        force
        or n_new >= MIN_NEW_BOTS
        or days_since >= FORCE_RETRAIN_DAYS
    )
    if not should_train:
        print(f"  신규 봇 {n_new}개 < {MIN_NEW_BOTS}개 AND {days_since}일 < {FORCE_RETRAIN_DAYS}일")
        print("  → 학습 조건 미충족. VM 종료.")
        if self_stop:
            _gcp_self_stop()
        return

    if not selected_bots:
        print("  선택된 품질 봇 없음 — 콜드스타트 봇으로만 학습")

    # ── 에피소드 수 결정 (비용 상한 적용) ───────────────────────────────
    max_ep_per_worker = max(1, MAX_EPISODES_TOTAL // n_workers)
    ep_per_worker = min(episodes_per_worker, max_ep_per_worker)
    total_episodes = ep_per_worker * n_workers

    print(f"  workers={n_workers}  ep/worker={ep_per_worker}  총={total_episodes}ep")
    print(f"  device={device}")
    print("=" * 70)

    # ── worker 실행 ──────────────────────────────────────────────────────
    result_queue: Queue = Queue()
    processes = []

    for wid in range(n_workers):
        p = Process(
            target=_worker,
            args=(wid, ep_per_worker, selected_bots, device,
                  result_queue, base_seed, t_start),
            daemon=True,
        )
        p.start()
        processes.append(p)
        time.sleep(0.5)

    # 런타임 상한으로 join timeout 설정
    deadline_seconds = MAX_RUNTIME_HOURS * 3600
    for p in processes:
        remain = max(1, deadline_seconds - (time.time() - t_start))
        p.join(timeout=remain)
        if p.is_alive():
            logger.warning("런타임 상한 초과 — worker %d SIGTERM", p.pid)
            p.terminate()
            p.join(timeout=10)
            if p.is_alive():
                # SIGTERM 후에도 살아있으면 SIGKILL. (atomic save 적용된
                # checkpoint는 SIGKILL에도 손상되지 않는다.)
                logger.warning("worker %d SIGKILL", p.pid)
                try:
                    p.kill()
                except Exception:
                    pass
                p.join(timeout=5)

    # ── 결과 수집 ────────────────────────────────────────────────────────
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())

    total_ep   = sum(r.get("episodes", 0) for r in results if "error" not in r)
    avg_rank   = (sum(r.get("avg_rank", 0) * r.get("episodes", 0)
                     for r in results if "error" not in r) / total_ep) if total_ep else 0
    avg_score  = (sum(r.get("avg_score", 0) * r.get("episodes", 0)
                     for r in results if "error" not in r) / total_ep) if total_ep else 0
    win_rate   = (sum(r.get("win_rate", 0) * r.get("episodes", 0)
                     for r in results if "error" not in r) / total_ep) if total_ep else 0
    max_step   = max((r.get("step_count", 0) for r in results if "error" not in r), default=0)
    max_ep_cnt = max((r.get("total_episodes", 0) for r in results if "error" not in r), default=0)
    last_eps   = min((r.get("epsilon", 1.0) for r in results if "error" not in r), default=1.0)
    elapsed    = time.time() - t_start

    print()
    print("=" * 70)
    print(f"  학습 완료 | 총 {total_ep}ep | {elapsed/3600:.2f}h")
    for r in sorted(results, key=lambda x: x.get("worker_id", 0)):
        if "error" in r:
            print(f"  W{r['worker_id']}: 오류 — {r['error']}")
        else:
            print(
                f"  W{r['worker_id']}: {r['episodes']}ep  "
                f"avg_rank={r['avg_rank']:.2f}  win={r['win_rate']*100:.0f}%  "
                f"eps={r['epsilon']:.3f}"
            )

    # ── 이력 업데이트 ─────────────────────────────────────────────────────
    if selected_ids:
        _save_bot_history(history, selected_ids)
        logger.info("학습 이력 저장: 봇 %d개", len(selected_ids))

    # ── training_meta.json GCS 업로드 ────────────────────────────────────
    meta = {
        "updated_at":     datetime.now(timezone.utc).isoformat(),
        "generation":     max_ep_cnt,
        "total_episodes": max_ep_cnt,
        "total_steps":    max_step,
        "epsilon":        round(last_eps, 4),
        "win_rate":       round(win_rate, 3),
        "avg_rank":       round(avg_rank, 2),
        "avg_score":      round(avg_score, 1),
        "trained_bots":   len(selected_bots),
        "session_episodes": total_ep,
        "runtime_hours":  round(elapsed / 3600, 2),
    }
    if use_gcs and gcs_weights.enabled():
        gcs_weights.upload_json(meta, META_FILENAME)
        print(f"  training_meta.json → GCS")

    print("=" * 70)

    # ── GCS 최종 가중치 업로드 ───────────────────────────────────────────
    if use_gcs and gcs_weights.enabled() and WEIGHTS_PATH.exists():
        ok = gcs_weights.upload(WEIGHTS_PATH)
        print(f"  가중치 GCS 업로드: {'성공' if ok else '실패'}")

    # ── VM 자동 종료 ──────────────────────────────────────────────────────
    if self_stop:
        print("  VM 자동 종료 중...")
        _gcp_self_stop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="RLBossBotTorch 병렬 학습 (비용 상한 + 스마트 스케줄링)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--workers",              type=int,   default=6,
                   help="병렬 worker 수")
    p.add_argument("--episodes-per-worker",  type=int,   default=100,
                   help=f"worker당 에피소드 수 (총 상한 {MAX_EPISODES_TOTAL}에 의해 자동 조정)")
    p.add_argument("--device",               type=str,   default="auto")
    p.add_argument("--no-gcs",               action="store_true")
    p.add_argument("--seed",                 type=int,   default=42)
    p.add_argument("--force",                action="store_true",
                   help="신규 봇 부족해도 강제 학습 (디버그/수동 실행용)")
    p.add_argument("--no-self-stop",         action="store_true",
                   help="학습 후 VM 자동 종료 비활성화 (로컬 디버그용)")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = _parse()

    device = args.device
    if device == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
                print(f"GPU: {torch.cuda.get_device_name(0)}")
            else:
                device = "cpu"
                print("GPU 없음 → CPU")
        except ImportError:
            print("PyTorch 없음: pip install torch")
            return 1

    train(
        n_workers            = args.workers,
        episodes_per_worker  = args.episodes_per_worker,
        device               = device,
        use_gcs              = not args.no_gcs,
        base_seed            = args.seed,
        force                = args.force,
        self_stop            = not args.no_self_stop,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

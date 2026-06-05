"""BR2 보스 RL 학습 (DQN + Replay + Target + PFSP-lite league).

구조:
    - sim: BattleRoyale2.sim.BR2MiniEnv (순수 Python 단순화 환경)
    - 모델: PyTorch MLP (FEATURE_DIM=80 → 256 → 128 → ACTION_DIM=20)
    - 학습: DQN (Huber loss + target sync)
    - 상대: PFSP-lite — league (past_boss) + 룰 보스 + 일반 봇 mix
    - 보상 (BR2 RewardCalculator):
        per-tick: sim 자체 (score delta + hp delta)
        per-episode (보스 시점):
            rank==1: +150
            n>=3 일 때 rank==2: +30, rank>=3: -10
            n==2 (보스 vs 1상대) 일 때 비-1위: -20   ← 메모리 1+2 조건 완화값
    - 시나리오 mix:
        PFSP (3v1) 70% / trio (4v1) 25% / solo (2v1) 5%   ← solo 비중 ≤5% (메모리 1번)
    - 출력: torch.pt + numpy.npz (network 호환 포맷) + GCS br2/ 업로드 (옵션)

학습 종료 시:
    1) 최신 torch.pt 를 numpy.npz 로 변환 (gen_NNNNN.npz)
    2) GCS gs://knu-2026-boss-weights/br2/ 로 업로드 (옵션, --upload-gcs)
    3) checkpoints 디렉토리(BR2 bots/boss/rl/checkpoints/) 에 복사 → 백엔드 RLBossBR2 자동 활성
    4) (옵션) GCP self-stop

사용:
    python -m BattleRoyale2.scripts.train.train_boss_br2 \\
        --episodes 100 --workers 1 --device cpu --upload-gcs

메모리 [[project-boss-bot]] 의 5/31 1+2 조건을 BR2 환경에 1:1 매핑한 시작점.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

# torch 는 학습 환경에서만 import — 인퍼런스 노드 보호.
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False

# 프로젝트 상대 import (script 직접 실행 시 sys.path 보정)
_BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from BattleRoyale2.bots import HerbivoreBot, MadDogBot, CamperBot
from BattleRoyale2.bots.boss import RuleBossEasyBR2, RuleBossMediumBR2
from BattleRoyale2.bots.boss.rl.encoder import encode_state, FEATURE_DIM, DEFAULT_MATCH_DURATION
from BattleRoyale2.bots.boss.rl.decoder import ACTION_DIM, decode_action
from BattleRoyale2.rules.boss_mode import BOSS_STAT_MULTIPLIERS
from BattleRoyale2.sim import BR2MiniEnv, BOSS_DURATION_SEC, TICK_DT

logger = logging.getLogger(__name__)

# ── 하이퍼파라미터 (메모리 5/31 baseline) ─────────────────────────────────
H1: int = 256
H2: int = 128
REPLAY_CAPACITY: int = 30_000
BATCH_SIZE: int = 128
GAMMA: float = 0.99
LR: float = 5e-4
TARGET_SYNC_STEPS: int = 1_000
EPSILON_START: float = 1.0
EPSILON_END: float = 0.05
EPSILON_DECAY_STEPS: int = 10_000
LEARN_INTERVAL_STEPS: int = 4
WARMUP_TRANSITIONS: int = 2_000

# 시나리오 mix (메모리 1+2 조건 적용 — solo ≤ 5%)
SCENARIO_WEIGHTS: dict[str, float] = {"pfsp": 0.70, "trio": 0.25, "solo": 0.05}
SCENARIO_NS: dict[str, int] = {"pfsp": 4, "trio": 4, "solo": 2}   # 보스 포함 봇 수

# 보상 (BR2 RewardCalculator v0 — 메모리 1+2 조건 적용)
REWARD_RANK1: float = 150.0
REWARD_RANK2_TRIO_PLUS: float = 30.0   # n >= 3 일 때 2위
REWARD_RANK3_PLUS: float = -10.0       # n >= 3 일 때 3위 이하
REWARD_LOSS_SOLO: float = -20.0        # n == 2 일 때 비-1위 (메모리 2번 완화값: -50 → -20)
REWARD_MINING_PER_TICK: float = 0.15   # mini_env 의 score delta 와 별개 보조
REWARD_DENSE_WEIGHT: float = 1.0

# league
LEAGUE_SNAPSHOT_INTERVAL: int = 50
LEAGUE_MAX_ENTRIES: int = 12

# 체크포인트
BR2_BOSS_BUCKET: str = "gs://knu-2026-boss-weights/br2"
LOCAL_CHECKPOINT_DIR: Path = _BACKEND_DIR / "BattleRoyale2" / "bots" / "boss" / "rl" / "checkpoints"

BOSS_ID: str = "boss"


# ── 모델 ────────────────────────────────────────────────────────────────
def build_qnet() -> "nn.Module":
    if not _TORCH_OK:
        raise RuntimeError("PyTorch 미설치 — pip install torch (CPU) 또는 venv 활성화 필요.")
    return nn.Sequential(
        nn.Linear(FEATURE_DIM, H1), nn.ReLU(),
        nn.Linear(H1, H2),         nn.ReLU(),
        nn.Linear(H2, ACTION_DIM),
    )


def soft_update_target(target: "nn.Module", online: "nn.Module") -> None:
    target.load_state_dict(online.state_dict())


# ── Replay buffer ───────────────────────────────────────────────────────
@dataclass
class Transition:
    s: np.ndarray
    a: int
    r: float
    s_next: np.ndarray
    done: bool


class ReplayBuffer:
    def __init__(self, capacity: int = REPLAY_CAPACITY):
        self.buf: deque[Transition] = deque(maxlen=capacity)

    def __len__(self) -> int:
        return len(self.buf)

    def push(self, *args) -> None:
        self.buf.append(Transition(*args))

    def sample(self, batch_size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        idx = np.random.randint(0, len(self.buf), size=batch_size)
        s = np.stack([self.buf[i].s for i in idx])
        a = np.array([self.buf[i].a for i in idx], dtype=np.int64)
        r = np.array([self.buf[i].r for i in idx], dtype=np.float32)
        s_next = np.stack([self.buf[i].s_next for i in idx])
        done = np.array([self.buf[i].done for i in idx], dtype=np.float32)
        return s, a, r, s_next, done


# ── 상대 풀 (PFSP-lite + 룰 + 일반봇) ───────────────────────────────────
_RULE_BOSS_FACTORIES = [
    (RuleBossEasyBR2, "RuleBossEasy"),
    (RuleBossMediumBR2, "RuleBossMed"),
]
_SAMPLE_BOTS = [
    (HerbivoreBot, "초식봇"),
    (MadDogBot, "미친개봇"),
    (CamperBot, "존버봇"),
]


def _build_opponents(n: int, seed: int, rng: random.Random) -> list:
    """보스 외 (n-1) 상대 구성. league(past) 비중은 향후 확장."""
    opponents = []
    n_others = n - 1
    # 단순 비율: rule 5% / sample 95%
    n_rule = max(0, int(round(n_others * 0.05)))
    n_sample = n_others - n_rule
    for i in range(n_rule):
        cls, label = rng.choice(_RULE_BOSS_FACTORIES)
        opponents.append(cls(bot_id=f"{label}_{i:02d}", seed=seed + i))
    for i in range(n_sample):
        cls, label = rng.choice(_SAMPLE_BOTS)
        opponents.append(cls(bot_id=f"{label}_{i:02d}", seed=seed + 100 + i))
    rng.shuffle(opponents)
    return opponents


# ── 에피소드 ────────────────────────────────────────────────────────────
def _select_action(qnet: "nn.Module", feat: np.ndarray, epsilon: float,
                   rng: random.Random, device: str) -> int:
    if rng.random() < epsilon:
        return rng.randrange(ACTION_DIM)
    with torch.no_grad():
        t = torch.from_numpy(feat).float().unsqueeze(0).to(device)
        q = qnet(t)
        return int(q.argmax(dim=1).item())


def _run_episode(
    env: BR2MiniEnv,
    qnet: "nn.Module",
    opponents: list,
    scenario: str,
    epsilon: float,
    rng: random.Random,
    device: str,
    duration_sec: float,
    difficulty: str = "상",
) -> tuple[list[Transition], dict[str, Any]]:
    """한 매치 진행. 보스 시점 transitions 와 결과 dict 반환."""
    n = SCENARIO_NS[scenario]
    # 봇 spec
    bot_specs = [{"id": BOSS_ID, "stat": BOSS_STAT_MULTIPLIERS[difficulty], "is_boss": True}]
    for i, op in enumerate(opponents):
        bot_specs.append({"id": op.bot_id, "stat": None, "is_boss": False})
    states = env.reset(bots=bot_specs)
    map_info = env.map_info()
    # opponent.choose_spawn — 첫 reset 후 spawn 위치 보정 가능 (미구현, 단순화)

    transitions: list[Transition] = []
    last_move: tuple[float, float] = (1.0, 0.0)
    prev_feat: Optional[np.ndarray] = None
    prev_action: Optional[int] = None
    prev_score: float = 0.0
    accumulated_reward: float = 0.0

    while not env.done:
        actions: dict[str, dict[str, Any]] = {}
        # 보스: Q-net 정책
        boss_state = states[BOSS_ID]
        boss_feat = encode_state(boss_state, duration_sec=duration_sec)
        boss_action_idx = _select_action(qnet, boss_feat, epsilon, rng, device)
        boss_action = decode_action(boss_action_idx, boss_state, last_move=last_move)
        mv = boss_action.get("move_dir", [0.0, 0.0])
        if abs(mv[0]) > 1e-6 or abs(mv[1]) > 1e-6:
            last_move = (float(mv[0]), float(mv[1]))
        actions[BOSS_ID] = boss_action

        # 상대: 각 봇.get_action
        for op in opponents:
            try:
                actions[op.bot_id] = op.get_action(states[op.bot_id]) or {}
            except Exception:
                actions[op.bot_id] = {}

        # transition 기록 (보스 시점)
        if prev_feat is not None and prev_action is not None:
            # 직전 step 의 보상 = score delta + 작은 mining 보너스
            cur_score = env.bots[BOSS_ID].score
            r_dense = REWARD_DENSE_WEIGHT * (cur_score - prev_score)
            transitions.append(Transition(prev_feat, prev_action, r_dense, boss_feat, False))
            accumulated_reward += r_dense
            prev_score = cur_score

        prev_feat = boss_feat
        prev_action = boss_action_idx

        states, _step_r, done, _info = env.step(actions)

    # 종료 시 마지막 transition 추가 + per-episode reward
    if prev_feat is not None and prev_action is not None:
        final_feat = encode_state(states[BOSS_ID], duration_sec=duration_sec)
        result = env.episode_result()
        boss_rank = result.ranks[BOSS_ID]
        terminal_r = _episode_terminal_reward(boss_rank, result.n_bots)
        # 마지막 transition reward = score delta + terminal
        cur_score = env.bots[BOSS_ID].score
        r_dense_last = REWARD_DENSE_WEIGHT * (cur_score - prev_score)
        transitions.append(Transition(prev_feat, prev_action,
                                      r_dense_last + terminal_r, final_feat, True))
        accumulated_reward += r_dense_last + terminal_r

    info = {
        "scenario": scenario,
        "boss_rank": env.bots[BOSS_ID].rank,
        "boss_score": env.bots[BOSS_ID].score,
        "boss_hp": env.bots[BOSS_ID].hp,
        "n_bots": n,
        "episode_reward": accumulated_reward,
        "ticks": env.tick,
    }
    return transitions, info


def _episode_terminal_reward(rank: int, n: int) -> float:
    """보스 시점 episode 종료 reward (BR2 v0)."""
    if rank == 1:
        return REWARD_RANK1
    if n == 2:
        return REWARD_LOSS_SOLO        # 메모리 2번 완화값
    if rank == 2:
        return REWARD_RANK2_TRIO_PLUS
    return REWARD_RANK3_PLUS


# ── 학습 ────────────────────────────────────────────────────────────────
def _dqn_update(qnet: "nn.Module", target: "nn.Module", optimizer: "optim.Optimizer",
                buf: ReplayBuffer, device: str) -> float:
    s, a, r, s_next, done = buf.sample(BATCH_SIZE)
    s_t = torch.from_numpy(s).float().to(device)
    a_t = torch.from_numpy(a).long().to(device)
    r_t = torch.from_numpy(r).float().to(device)
    s_n = torch.from_numpy(s_next).float().to(device)
    d_t = torch.from_numpy(done).float().to(device)

    q = qnet(s_t).gather(1, a_t.unsqueeze(1)).squeeze(1)
    with torch.no_grad():
        q_next = target(s_n).max(dim=1)[0]
        target_q = r_t + (1.0 - d_t) * GAMMA * q_next
    loss = torch.nn.functional.smooth_l1_loss(q, target_q)
    optimizer.zero_grad()
    loss.backward()
    torch.nn.utils.clip_grad_norm_(qnet.parameters(), 5.0)
    optimizer.step()
    return float(loss.item())


def _save_torch_checkpoint(qnet: "nn.Module", path: Path, meta: dict[str, Any]) -> None:
    torch.save({"state_dict": qnet.state_dict(), "meta": meta}, str(path))


def _convert_torch_to_npz(torch_path: Path, npz_path: Path, meta: dict[str, Any]) -> None:
    """net.{0,2,4}.{weight,bias} (out,in) → numpy 가중치 (in,out) transpose."""
    cp = torch.load(str(torch_path), map_location="cpu")
    sd = cp["state_dict"] if isinstance(cp, dict) and "state_dict" in cp else cp
    # nn.Sequential 의 모듈 인덱스: 0=Linear1, 2=Linear2, 4=Linear3
    arr = {}
    arr["W1"] = sd["0.weight"].cpu().numpy().T.astype(np.float32)
    arr["b1"] = sd["0.bias"].cpu().numpy().astype(np.float32)
    arr["W2"] = sd["2.weight"].cpu().numpy().T.astype(np.float32)
    arr["b2"] = sd["2.bias"].cpu().numpy().astype(np.float32)
    arr["W3"] = sd["4.weight"].cpu().numpy().T.astype(np.float32)
    arr["b3"] = sd["4.bias"].cpu().numpy().astype(np.float32)
    # meta — 키 prefix 'meta_'
    for k, v in meta.items():
        arr[f"meta_{k}"] = np.array([v]) if not isinstance(v, (list, np.ndarray)) else np.asarray(v)
    np.savez(str(npz_path), **arr)


def _upload_gcs(local_path: Path, gcs_path: str) -> bool:
    try:
        subprocess.run(["gsutil", "cp", str(local_path), gcs_path], check=True,
                       capture_output=True, text=True)
        logger.info("GCS 업로드 OK: %s → %s", local_path, gcs_path)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("GCS 업로드 실패 (%s): %s", e, getattr(e, "stderr", ""))
        return False


def _maybe_gcp_self_stop() -> None:
    """학습 VM 자동 종료. metadata server 가 응답해야 GCP VM 으로 판정."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/name",
            headers={"Metadata-Flavor": "Google"},
        )
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        return
    try:
        subprocess.run(["sudo", "shutdown", "-h", "now"], check=False, timeout=5)
    except Exception:  # noqa: BLE001
        pass


# ── 메인 학습 함수 ─────────────────────────────────────────────────────
def train(
    episodes: int,
    device: str,
    output_dir: Path,
    upload_gcs: bool,
    seed: int,
    self_stop: bool,
    gen_start: int,
) -> int:
    if not _TORCH_OK:
        logger.error("PyTorch 미설치. 학습 불가.")
        return 1

    rng = random.Random(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    qnet = build_qnet().to(device)
    target_net = build_qnet().to(device)
    soft_update_target(target_net, qnet)
    optimizer = optim.Adam(qnet.parameters(), lr=LR)
    buf = ReplayBuffer()

    step_count: int = 0
    generation: int = gen_start
    t0 = time.time()

    rank_history: list[int] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for ep in range(1, episodes + 1):
        scenario = rng.choices(
            list(SCENARIO_WEIGHTS.keys()), weights=list(SCENARIO_WEIGHTS.values()), k=1
        )[0]
        n = SCENARIO_NS[scenario]
        ep_seed = rng.randrange(10**9)
        env = BR2MiniEnv(seed=ep_seed, duration_sec=BOSS_DURATION_SEC)
        opponents = _build_opponents(n=n, seed=ep_seed, rng=rng)
        epsilon = max(
            EPSILON_END,
            EPSILON_START - (EPSILON_START - EPSILON_END) * (step_count / EPSILON_DECAY_STEPS),
        )
        transitions, info = _run_episode(
            env, qnet, opponents, scenario, epsilon, rng, device,
            duration_sec=BOSS_DURATION_SEC,
        )
        for tr in transitions:
            buf.push(tr.s, tr.a, tr.r, tr.s_next, tr.done)
            step_count += 1
            if len(buf) >= WARMUP_TRANSITIONS and step_count % LEARN_INTERVAL_STEPS == 0:
                _dqn_update(qnet, target_net, optimizer, buf, device)
                if step_count % TARGET_SYNC_STEPS == 0:
                    soft_update_target(target_net, qnet)

        rank_history.append(info["boss_rank"])
        avg_rank = sum(rank_history[-20:]) / max(1, min(20, len(rank_history)))
        win_rate = sum(1 for r in rank_history[-20:] if r == 1) / max(1, min(20, len(rank_history)))

        if ep % 10 == 0 or ep == 1:
            elapsed = time.time() - t0
            logger.info(
                "ep=%d/%d sc=%s rank=%d/%d score=%.1f reward=%.1f eps=%.3f buf=%d "
                "avg_rank20=%.2f win20=%.2f elapsed=%.0fs",
                ep, episodes, info["scenario"], info["boss_rank"], info["n_bots"],
                info["boss_score"], info["episode_reward"], epsilon, len(buf),
                avg_rank, win_rate, elapsed,
            )

        if ep % LEAGUE_SNAPSHOT_INTERVAL == 0:
            generation += 1
            ckpt = output_dir / f"gen_{generation:05d}.pt"
            _save_torch_checkpoint(qnet, ckpt, {
                "generation": generation, "episodes": ep, "win_rate": win_rate,
                "avg_rank": avg_rank,
            })
            logger.info("league snapshot saved: %s (win=%.2f)", ckpt, win_rate)
            # 오래된 ckpt 정리
            ckpts = sorted(output_dir.glob("gen_*.pt"))
            for old in ckpts[:-LEAGUE_MAX_ENTRIES]:
                old.unlink()

    # 최종 산출물 — npz 변환 + 백엔드 checkpoints 디렉토리 복사
    generation += 1
    final_torch = output_dir / f"gen_{generation:05d}.pt"
    final_npz = output_dir / f"gen_{generation:05d}.npz"
    meta = {
        "generation": generation,
        "episodes": episodes,
        "feature_dim": FEATURE_DIM,
        "action_dim": ACTION_DIM,
        "h1": H1, "h2": H2,
        "trained_at": int(time.time()),
        "avg_rank20": avg_rank if rank_history else 0.0,
        "win_rate20": win_rate if rank_history else 0.0,
    }
    _save_torch_checkpoint(qnet, final_torch, meta)
    _convert_torch_to_npz(final_torch, final_npz, meta)
    logger.info("final ckpt: torch=%s npz=%s", final_torch, final_npz)

    LOCAL_CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(final_npz), str(LOCAL_CHECKPOINT_DIR / final_npz.name))
    logger.info("백엔드 checkpoints 디렉토리에 배치: %s", LOCAL_CHECKPOINT_DIR / final_npz.name)

    if upload_gcs:
        _upload_gcs(final_npz, f"{BR2_BOSS_BUCKET}/{final_npz.name}")
        _upload_gcs(final_npz, f"{BR2_BOSS_BUCKET}/latest.npz")

    if self_stop:
        logger.info("self-stop 활성 — VM 종료")
        _maybe_gcp_self_stop()

    return 0


# ── argparse + main ─────────────────────────────────────────────────────
def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BR2 보스 RL 학습")
    p.add_argument("--episodes", type=int, default=100)
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    p.add_argument("--output-dir", type=Path,
                   default=Path("/tmp/br2_boss_train"))
    p.add_argument("--upload-gcs", action="store_true",
                   help="최종 가중치를 gs://knu-2026-boss-weights/br2/ 에 업로드")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--self-stop", action="store_true",
                   help="학습 종료 후 GCP VM 종료 (metadata server 확인)")
    p.add_argument("--gen-start", type=int, default=0,
                   help="generation 시작 번호 (이어 학습 시 last+1)")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main() -> int:
    args = _parse()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger.info("BR2 보스 RL 학습 시작 — episodes=%d device=%s output=%s",
                args.episodes, args.device, args.output_dir)
    return train(
        episodes=args.episodes,
        device=args.device,
        output_dir=args.output_dir,
        upload_gcs=args.upload_gcs,
        seed=args.seed,
        self_stop=args.self_stop,
        gen_start=args.gen_start,
    )


if __name__ == "__main__":
    sys.exit(main())

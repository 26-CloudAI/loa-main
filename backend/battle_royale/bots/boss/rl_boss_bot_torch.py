"""
RLBossBotTorch — PyTorch DQN 기반 보스 봇 (GPU 학습용)
=========================================================

numpy 버전(rl_boss_bot.py) 대비 변경점:
  - PyTorch DQN: 43 → 256 → 128 → 19 (3층, 더 표현력 높은 네트워크)
  - GPU 자동 감지: CUDA/MPS/CPU 우선순위로 선택
  - Adam optimizer: 자동 학습률 적응
  - 동일 StateEncoder/RewardCalculator/BotInterface 재사용
  - 체크포인트: version=4 (numpy 버전과 분리)

병렬 학습 시:
  train_boss_parallel.py 의 worker 프로세스가 이 클래스를 사용.
  각 worker가 독립적으로 episode를 실행하고,
  N episode마다 shared checkpoint에서 최신 가중치를 받아온다.
"""

from __future__ import annotations

import json
import random
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torch.optim as optim
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

from core.bot_interface import BotInterface
from core.types import Action

# numpy 버전에서 공통 상수/유틸 임포트
from bots.boss.rl_boss_bot import (
    ACTIONS, N_ACTIONS,
    IDX_STAY, IDX_MINE, IDX_SHIELD,
    IDX_MOVE_UP, IDX_MOVE_DOWN, IDX_MOVE_LEFT, IDX_MOVE_RIGHT,
    IDX_MOVE_UP_LEFT, IDX_MOVE_UP_RIGHT, IDX_MOVE_DOWN_LEFT, IDX_MOVE_DOWN_RIGHT,
    _ADJ_DIRS, _CX, _CY, _ADJ_CELL_COORDS, _MOVE_TO_DELTA,
    _move_idx_toward,
    MAX_TICKS, ENERGY_CRITICAL, _ATTACK_COST, _ATTACK_DAMAGE, _LASTBIT_HP,
    _ZONE_P2_START, _ZONE_BUFFER, _MIN_EXPIRE_TICKS,
    EPSILON_START, EPSILON_MIN, EPSILON_DECAY, EXPLOIT_GUIDE_PROB,
    GCS_UPLOAD_INTERVAL,
    StateEncoder, RewardCalculator,
)

_DEFAULT_WEIGHTS_PATH = Path(__file__).parent / "trained_weights_torch.pt"

# ---------------------------------------------------------------------------
# 하이퍼파라미터 (PyTorch 버전)
# ---------------------------------------------------------------------------

N_FEATURES   = 43
N_HIDDEN1    = 256
N_HIDDEN2    = 128
LR           = 0.0005       # Adam 학습률
GAMMA        = 0.95
BATCH_SIZE   = 128          # GPU 활용을 위해 배치 크기 증가
BUFFER_SIZE  = 30000        # B 트랙: 50k→30k 축소 (상대 분포 변화에 대응, forgetting 가속)
TARGET_UPDATE_FREQ = 200    # target network 동기화 주기
MIN_BUFFER_LEARN   = 1000   # 학습 시작 최소 버퍼 크기
WEIGHT_SYNC_FREQ   = 10     # 병렬 학습 시 weight sync 주기 (episode 단위)


def _get_device() -> "torch.device":
    """CUDA → MPS → CPU 순으로 가용 device 선택."""
    if not _TORCH_AVAILABLE:
        raise RuntimeError("PyTorch가 설치되지 않았습니다: pip install torch")
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# PyTorch DQN 네트워크 — 3층 MLP
# ---------------------------------------------------------------------------

class DQNetworkTorch(nn.Module):
    """
    43 → 256 → 128 → 19 (3층 MLP, ReLU 활성화).
    numpy 버전(64 hidden 1층) 대비 표현력 대폭 향상.
    """

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(N_FEATURES, N_HIDDEN1),
            nn.ReLU(),
            nn.Linear(N_HIDDEN1, N_HIDDEN2),
            nn.ReLU(),
            nn.Linear(N_HIDDEN2, N_ACTIONS),
        )

    def forward(self, x: "torch.Tensor") -> "torch.Tensor":
        return self.net(x)


# ---------------------------------------------------------------------------
# Replay Buffer (numpy 기반, PyTorch tensor 변환은 학습 시에만)
# ---------------------------------------------------------------------------

class ReplayBufferTorch:
    def __init__(self, maxlen: int = BUFFER_SIZE):
        self._buf: deque[tuple] = deque(maxlen=maxlen)

    def push(self, phi, action, reward, phi_next, done):
        self._buf.append((
            np.array(phi, dtype=np.float32),
            int(action),
            float(reward),
            np.array(phi_next, dtype=np.float32),
            bool(done),
        ))

    def sample(self, n: int, device: "torch.device"):
        batch = random.sample(self._buf, min(n, len(self._buf)))
        phis      = torch.tensor(np.array([e[0] for e in batch]), device=device)
        actions   = torch.tensor([e[1] for e in batch], dtype=torch.long, device=device)
        rewards   = torch.tensor([e[2] for e in batch], dtype=torch.float32, device=device)
        phis_next = torch.tensor(np.array([e[3] for e in batch]), device=device)
        dones     = torch.tensor([e[4] for e in batch], dtype=torch.float32, device=device)
        return phis, actions, rewards, phis_next, dones

    def __len__(self) -> int:
        return len(self._buf)


# ---------------------------------------------------------------------------
# RLBossBotTorch
# ---------------------------------------------------------------------------

class RLBossBotTorch(BotInterface):
    """
    PyTorch DQN 기반 보스 봇.
    BotInterface 준수, 학습 로직 포함.
    병렬 학습 환경(train_boss_parallel.py)에서 사용.
    """

    def __init__(
        self,
        bot_id: str,
        seed: Optional[int] = None,
        weights_path=None,
        epsilon_override: Optional[float] = None,
        device: Optional[str] = None,
    ):
        if not _TORCH_AVAILABLE:
            raise RuntimeError("PyTorch가 설치되지 않았습니다: pip install torch")

        self._bot_id = bot_id
        self._rng    = random.Random(seed)
        self._encoder = StateEncoder()
        self._reward_calc = RewardCalculator()

        self._device = torch.device(device) if device else _get_device()

        if seed is not None:
            torch.manual_seed(seed)

        self._online = DQNetworkTorch().to(self._device)
        self._target = DQNetworkTorch().to(self._device)
        self._target.load_state_dict(self._online.state_dict())
        self._target.eval()

        self._optimizer = optim.Adam(self._online.parameters(), lr=LR)
        self._buffer    = ReplayBufferTorch(BUFFER_SIZE)

        self._step_count    = 0
        self._episode_count = 0

        self._epsilon = epsilon_override if epsilon_override is not None \
                        else EPSILON_START
        self._epsilon_override = epsilon_override

        self._prev_phi:        Optional[np.ndarray] = None
        self._prev_action_idx: Optional[int]        = None
        self._prev_state:      Optional[dict]       = None
        self._on_mineral:      bool                 = False

        # {(x, y): (cell_type, last_seen_tick)}
        self._mineral_memory: dict[tuple[int, int], tuple[str, int]] = {}

        load_path = Path(weights_path) if weights_path is not None \
                    else _DEFAULT_WEIGHTS_PATH
        if load_path.exists():
            self._load_checkpoint(load_path)

        print(f"[RLBossBotTorch] device={self._device}, "
              f"ep={self._episode_count}, step={self._step_count}, "
              f"eps={self._epsilon:.3f}")

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict) -> Optional[tuple[int, int]]:
        w = map_info.get("width", 100)
        h = map_info.get("height", 100)
        minerals = map_info.get("minerals", [])

        for m in minerals:
            cell_type = "mineral_rare" if m["rare"] else "mineral"
            self._mineral_memory[(m["x"], m["y"])] = (cell_type, 0)

        rare = [(m["x"], m["y"]) for m in minerals if m["rare"]]
        if rare:
            tx, ty = self._rng.choice(rare)
            offsets = [(1, 0), (-1, 0), (0, 1), (0, -1)]
            self._rng.shuffle(offsets)
            for dx, dy in offsets:
                nx, ny = tx + dx, ty + dy
                if 0 <= nx < w and 0 <= ny < h:
                    return (nx, ny)
            return (tx, ty)

        return (
            self._rng.randint(w // 2 - 15, w // 2 + 15),
            self._rng.randint(h // 2 - 15, h // 2 + 15),
        )

    def get_action(self, state: dict) -> str:
        my     = state["my_bot"]
        pos_x, pos_y = my["position"]
        grid   = state["vision"]["grid"]
        energy = my["energy"]
        tick   = state.get("tick", 0)
        other_bots = state.get("other_bots", [])
        safe_min_x, safe_min_y, safe_max_x, safe_max_y = state["zone_bounds"]

        # ── 광물 메모리 갱신 ──────────────────────────────────────────────
        for gy in range(5):
            for gx in range(5):
                mx   = pos_x + (gx - _CX)
                my_y = pos_y + (gy - _CY)
                cell = grid[gy][gx]
                if cell in ("mineral", "mineral_rare"):
                    self._mineral_memory[(mx, my_y)] = (cell, tick)
                elif cell == "empty":
                    self._mineral_memory.pop((mx, my_y), None)
        self._mineral_memory = {
            k: v for k, v in self._mineral_memory.items()
            if tick - v[1] <= _MIN_EXPIRE_TICKS
        }

        phi = self._encoder.encode(state)

        # ── TD 업데이트 ──────────────────────────────────────────────────
        if self._prev_state is not None and self._prev_phi is not None:
            reward = self._reward_calc.compute_tick(
                self._prev_state, state, self._prev_action_idx or IDX_STAY
            )
            self._buffer.push(
                self._prev_phi,
                self._prev_action_idx or IDX_STAY,
                reward, phi, False,
            )
            self._learn()

        # ── 하드코딩 규칙 ────────────────────────────────────────────────

        # 1. 자기장 탈출 / 예측 이동
        in_danger = (
            pos_x < safe_min_x or pos_x > safe_max_x
            or pos_y < safe_min_y or pos_y > safe_max_y
        )
        if not in_danger and tick >= _ZONE_P2_START:
            buf = _ZONE_BUFFER
            if (pos_x - safe_min_x < buf or safe_max_x - pos_x < buf or
                    pos_y - safe_min_y < buf or safe_max_y - pos_y < buf):
                in_danger = True

        if in_danger:
            cx = (safe_min_x + safe_max_x) // 2
            cy = (safe_min_y + safe_max_y) // 2
            action_idx = _move_idx_toward(cx - pos_x, cy - pos_y)

        # 2. 에너지 극위기 → 라스트힛 or flee
        elif energy <= ENERGY_CRITICAL:
            lastbit = self._lastbit_idx(grid, pos_x, pos_y, energy, other_bots)
            if lastbit is not None:
                action_idx = lastbit
            elif self._adj_enemy_exists(grid):
                action_idx = self._flee_idx(
                    grid, pos_x, pos_y,
                    safe_min_x, safe_max_x, safe_min_y, safe_max_y
                )
            else:
                action_idx = self._emergency_mine_idx(grid, pos_x, pos_y)

        # 3. 발밑 광물 (라스트힛 없을 때)
        elif self._on_mineral:
            lastbit = self._lastbit_idx(grid, pos_x, pos_y, energy, other_bots)
            action_idx = lastbit if lastbit is not None else IDX_MINE

        # 4. DQN
        else:
            action_idx = self._select_dqn(
                phi, grid, pos_x, pos_y,
                safe_min_x, safe_max_x, safe_min_y, safe_max_y,
            )

        if action_idx in _MOVE_TO_DELTA:
            dx, dy = _MOVE_TO_DELTA[action_idx]
            self._on_mineral = grid[_CY + dy][_CX + dx] in ("mineral", "mineral_rare")
        else:
            self._on_mineral = False

        self._prev_state      = state
        self._prev_phi        = phi
        self._prev_action_idx = action_idx

        return ACTIONS[action_idx]

    # -----------------------------------------------------------------------
    # 전투 헬퍼 (numpy 버전과 동일)
    # -----------------------------------------------------------------------

    def _adj_enemy_exists(self, grid: list) -> bool:
        return any(
            grid[_CY + dy][_CX + dx] == "bot_enemy"
            for dx, dy, _, _ in _ADJ_DIRS
        )

    def _lastbit_idx(self, grid, pos_x, pos_y, energy, other_bots) -> Optional[int]:
        # engine은 ATTACK_COST 차감 후 energy<=0이면 사망 처리하면서 공격을
        # 취소한다. 공격이 실제로 적중하려면 energy > ATTACK_COST가 필요.
        if energy <= _ATTACK_COST:
            return None
        pos_to_e = {(b["position"][0], b["position"][1]): b["energy"] for b in other_bots}
        for dx, dy, _, atk_idx in _ADJ_DIRS:
            if grid[_CY + dy][_CX + dx] == "bot_enemy":
                if pos_to_e.get((pos_x + dx, pos_y + dy), 999) <= _LASTBIT_HP:
                    return atk_idx
        return None

    def _flee_idx(self, grid, pos_x, pos_y, min_x, max_x, min_y, max_y) -> int:
        for dx, dy, move_idx, _ in _ADJ_DIRS:
            if grid[_CY + dy][_CX + dx] == "bot_enemy":
                nx, ny = pos_x - dx, pos_y - dy
                if min_x <= nx <= max_x and min_y <= ny <= max_y:
                    return _move_idx_toward(-dx, -dy)
                cx, cy = (min_x + max_x) // 2, (min_y + max_y) // 2
                return _move_idx_toward(cx - pos_x, cy - pos_y)
        return IDX_STAY

    def _emergency_mine_idx(self, grid, pos_x, pos_y) -> int:
        if grid[_CY][_CX] in ("mineral", "mineral_rare"):
            return IDX_MINE
        for dx, dy, move_idx, _ in _ADJ_DIRS:
            if grid[_CY + dy][_CX + dx] in ("mineral", "mineral_rare"):
                return move_idx
        best_dist, best_idx = 999, IDX_STAY
        for gy in range(5):
            for gx in range(5):
                if grid[gy][gx] in ("mineral", "mineral_rare"):
                    d = abs(gx - _CX) + abs(gy - _CY)
                    if d < best_dist:
                        best_dist, best_idx = d, _move_idx_toward(gx - _CX, gy - _CY)
        return best_idx

    # -----------------------------------------------------------------------
    # DQN 행동 선택
    # -----------------------------------------------------------------------

    def _select_dqn(self, phi, grid, pos_x, pos_y, min_x, max_x, min_y, max_y) -> int:
        if random.random() < self._epsilon:
            if random.random() < 0.70:
                guided = self._guided_action(grid, pos_x, pos_y, min_x, max_x, min_y, max_y)
                if guided is not None:
                    return guided
            return self._rng.choice(self._valid_actions(grid))

        if random.random() < EXPLOIT_GUIDE_PROB:
            guided = self._guided_action(grid, pos_x, pos_y, min_x, max_x, min_y, max_y)
            if guided is not None:
                return guided

        self._online.eval()
        with torch.no_grad():
            phi_t = torch.tensor(phi, device=self._device).unsqueeze(0)
            q = self._online(phi_t).squeeze(0).cpu().numpy()

        for dx, dy, _, attack_idx in _ADJ_DIRS:
            if grid[_CY + dy][_CX + dx] != "bot_enemy":
                q[attack_idx] -= 1e6
        if not self._on_mineral:
            q[IDX_MINE] -= 1e6

        return int(np.argmax(q))

    def _guided_action(self, grid, pos_x, pos_y, min_x, max_x, min_y, max_y) -> Optional[int]:
        adj = [(dx, dy, mi, ai, grid[_CY + dy][_CX + dx]) for dx, dy, mi, ai in _ADJ_DIRS]

        for dx, dy, move_idx, _, cell in adj:
            if cell == "mineral_rare":
                return move_idx

        if random.random() < 0.5:
            for dx, dy, _, attack_idx, cell in adj:
                if cell == "bot_enemy":
                    return attack_idx

        best, best_score = None, float("inf")
        for gy in range(5):
            for gx in range(5):
                cell = grid[gy][gx]
                if cell not in ("mineral", "mineral_rare"):
                    continue
                ddx, ddy = gx - _CX, gy - _CY
                dist = abs(ddx) + abs(ddy)
                if dist == 0:
                    continue
                prio = dist - (2 if cell == "mineral_rare" else 0)
                if prio < best_score:
                    best_score = prio
                    best = (ddx, ddy)
        if best is not None:
            return _move_idx_toward(*best)

        if self._mineral_memory:
            mem_best, mem_score = None, float("inf")
            for (mx, my_c), (cell_type, _) in self._mineral_memory.items():
                if not (min_x <= mx <= max_x and min_y <= my_c <= max_y):
                    continue
                dist = abs(mx - pos_x) + abs(my_c - pos_y)
                if dist == 0:
                    continue
                prio = dist - (3 if cell_type == "mineral_rare" else 0)
                if prio < mem_score:
                    mem_score = prio
                    mem_best = (mx - pos_x, my_c - pos_y)
            if mem_best is not None:
                return _move_idx_toward(*mem_best)

        return None

    def _valid_actions(self, grid) -> list[int]:
        valid = [
            IDX_STAY,
            IDX_MOVE_UP, IDX_MOVE_DOWN, IDX_MOVE_LEFT, IDX_MOVE_RIGHT,
            IDX_MOVE_UP_LEFT, IDX_MOVE_UP_RIGHT,
            IDX_MOVE_DOWN_LEFT, IDX_MOVE_DOWN_RIGHT,
            IDX_SHIELD,
        ]
        for dx, dy, _, attack_idx in _ADJ_DIRS:
            if grid[_CY + dy][_CX + dx] == "bot_enemy":
                valid.append(attack_idx)
        if self._on_mineral:
            valid.append(IDX_MINE)
        return valid

    # -----------------------------------------------------------------------
    # PyTorch 학습
    # -----------------------------------------------------------------------

    def _learn(self) -> None:
        if len(self._buffer) < MIN_BUFFER_LEARN:
            return

        self._online.train()
        phis, actions, rewards, phis_next, dones = self._buffer.sample(
            BATCH_SIZE, self._device
        )

        # Double DQN target
        with torch.no_grad():
            best_actions = self._online(phis_next).argmax(dim=1)
            q_tgt = self._target(phis_next)
            td_targets = rewards + (1.0 - dones) * GAMMA * q_tgt.gather(1, best_actions.unsqueeze(1)).squeeze(1)

        q_pred = self._online(phis).gather(1, actions.unsqueeze(1)).squeeze(1)
        loss = F.mse_loss(q_pred, td_targets)

        self._optimizer.zero_grad()
        loss.backward()
        # Gradient clipping (안정적 학습)
        nn.utils.clip_grad_norm_(self._online.parameters(), max_norm=10.0)
        self._optimizer.step()

        self._step_count += 1

        if self._step_count % TARGET_UPDATE_FREQ == 0:
            self._target.load_state_dict(self._online.state_dict())

    # -----------------------------------------------------------------------
    # 에피소드 관리
    # -----------------------------------------------------------------------

    def reset_for_episode(self) -> None:
        self._prev_phi        = None
        self._prev_action_idx = None
        self._prev_state      = None
        self._on_mineral      = False
        self._mineral_memory  = {}

    def on_episode_done(self, rank: int, n_bots: int) -> None:
        if self._prev_phi is not None:
            final_reward = RewardCalculator.compute_episode_end(rank, n_bots)
            dummy_phi = np.zeros(N_FEATURES, dtype=np.float32)
            self._buffer.push(
                self._prev_phi,
                self._prev_action_idx or IDX_STAY,
                final_reward, dummy_phi, True,
            )
            for _ in range(2):
                self._learn()

        self._episode_count += 1

        if self._epsilon_override is None:
            self._epsilon = max(EPSILON_MIN, self._epsilon * EPSILON_DECAY)

        self.save_weights()

        if self._episode_count % GCS_UPLOAD_INTERVAL == 0:
            try:
                from src.arena import gcs_weights
                if gcs_weights.enabled():
                    gcs_weights.upload(_DEFAULT_WEIGHTS_PATH)
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # 체크포인트
    # -----------------------------------------------------------------------

    def save_weights(self, path=None) -> None:
        save_path = Path(path) if path is not None else _DEFAULT_WEIGHTS_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version":       4,
            "n_features":    N_FEATURES,
            "n_hidden1":     N_HIDDEN1,
            "n_hidden2":     N_HIDDEN2,
            "n_actions":     N_ACTIONS,
            "step_count":    self._step_count,
            "episode_count": self._episode_count,
            "epsilon":       self._epsilon,
            "online":        self._online.state_dict(),
            "target":        self._target.state_dict(),
            "optimizer":     self._optimizer.state_dict(),
        }
        # Atomic write: tmp 파일에 torch.save 후 os.replace.
        # 다중 worker 환경에서 부분 쓰기로 인한 체크포인트 손상을 방지한다.
        import os, tempfile
        fd, tmp_path = tempfile.mkstemp(
            prefix=save_path.name + ".",
            suffix=".tmp",
            dir=str(save_path.parent),
        )
        os.close(fd)
        try:
            torch.save(payload, tmp_path)
            os.replace(tmp_path, save_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_checkpoint(self, path: Path) -> None:
        try:
            ckpt = torch.load(path, map_location=self._device, weights_only=True)
            if ckpt.get("version") != 4:
                return
            if (ckpt.get("n_features") != N_FEATURES
                    or ckpt.get("n_actions") != N_ACTIONS):
                return
            self._online.load_state_dict(ckpt["online"])
            self._target.load_state_dict(ckpt["target"])
            self._optimizer.load_state_dict(ckpt["optimizer"])
            self._step_count    = ckpt.get("step_count", 0)
            self._episode_count = ckpt.get("episode_count", 0)
            if self._epsilon_override is None:
                self._epsilon = ckpt.get("epsilon", EPSILON_START)
        except Exception:
            pass

    def get_weights_state_dict(self) -> dict:
        """병렬 학습 시 가중치 공유용."""
        return {
            "online":    {k: v.cpu() for k, v in self._online.state_dict().items()},
            "target":    {k: v.cpu() for k, v in self._target.state_dict().items()},
            "optimizer": self._optimizer.state_dict(),
            "step_count":    self._step_count,
            "episode_count": self._episode_count,
            "epsilon":       self._epsilon,
        }

    def set_weights_state_dict(self, d: dict) -> None:
        """병렬 학습 시 worker가 최신 가중치를 받아올 때 사용."""
        self._online.load_state_dict({k: v.to(self._device) for k, v in d["online"].items()})
        self._target.load_state_dict({k: v.to(self._device) for k, v in d["target"].items()})
        if "optimizer" in d:
            self._optimizer.load_state_dict(d["optimizer"])
        else:
            # 다른 worker 가중치를 덮어쓸 때 기존 모멘트는 새 파라미터와 불일치 —
            # 리셋해서 불안정 학습 방지
            self._optimizer = optim.Adam(self._online.parameters(), lr=LR)
        self._step_count    = d.get("step_count", self._step_count)
        self._episode_count = d.get("episode_count", self._episode_count)
        if self._epsilon_override is None:
            self._epsilon = d.get("epsilon", self._epsilon)

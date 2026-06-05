"""RLBossBR2 — 강화학습 보스 봇 (난이도 '상', BattleRoyale2DBot 구현).

옛 RLBossBot 의 BR2 버전:
- encoder.encode_state → QNetwork.forward → decoder.decode_action 체인
- 체크포인트(.npz) 로드. 파일 없으면 랜덤 weight 폴백(성능 보장 X) — ws_server 가 "hard"
  요청을 medium 으로 강등하도록 fallback 정책 적용 (factory 헬퍼 참조).
- ε-greedy 옵션 (학습 시): epsilon=0.0 (greedy) 기본. inference 시 epsilon_override 로 조정 가능.

학습 환경(Phase 4 후속)에서:
- league.py 가 체크포인트들을 GCS·로컬에 관리
- past_opponent.py 의 PastBossOpponentBR2 가 이 클래스의 freeze wrapper.
- train_boss_br2.py (별도 세션) 가 PyTorch 로 학습 → convert_torch_to_numpy_br2.py 로 .npz 변환.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any, Optional

import numpy as np

from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot

from .decoder import ACTION_DIM, decode_action
from .encoder import encode_state, DEFAULT_MATCH_DURATION
from .network import QNetwork

logger = logging.getLogger(__name__)


# 기본 체크포인트 디렉토리 (학습 산출물 보관).
DEFAULT_CHECKPOINT_DIR: Path = Path(__file__).resolve().parent / "checkpoints"


class RLBossBR2(BattleRoyale2DBot):
    """난이도 '상' 보스 — QNetwork 기반 추론.

    매치 시작 시 1회 체크포인트 로드, 매 틱마다 encode → forward → decode.
    학습(가중치 갱신)은 이 클래스가 직접 하지 않고 별도 학습 스크립트가 담당
    (옛 RLBossBot.numpy_training_enabled=False 와 동일 원칙).
    """

    DISPLAY_NAME: str = "보스(상)"

    def __init__(
        self,
        bot_id: str,
        seed: Optional[int] = None,
        checkpoint_path: Optional[str | Path] = None,
        epsilon: float = 0.0,
        match_duration_sec: float = DEFAULT_MATCH_DURATION,
    ):
        self._bot_id = bot_id
        self._rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed)
        self._epsilon = float(epsilon)
        self._duration = float(match_duration_sec)
        self._last_move: tuple[float, float] = (1.0, 0.0)
        self._network = self._load_network(checkpoint_path)

    @staticmethod
    def _load_network(checkpoint_path: Optional[str | Path]) -> QNetwork:
        if checkpoint_path is None:
            # 디폴트: checkpoints/ 안 가장 최신 generation
            latest = RLBossBR2._find_latest_checkpoint(DEFAULT_CHECKPOINT_DIR)
            if latest is None:
                logger.warning(
                    "[BR2 RL] 체크포인트 없음 — 랜덤 weight 으로 동작 (성능 보장 X). "
                    "학습 산출물 .npz 를 %s 에 배치하세요.", DEFAULT_CHECKPOINT_DIR
                )
                return QNetwork()
            checkpoint_path = latest
        try:
            net = QNetwork.load(checkpoint_path)
            logger.info("[BR2 RL] 체크포인트 로드: %s meta=%s", checkpoint_path, net.meta)
            return net
        except Exception as e:  # noqa: BLE001
            logger.exception("[BR2 RL] 체크포인트 로드 실패 (%s) — 랜덤 폴백", e)
            return QNetwork()

    @staticmethod
    def _find_latest_checkpoint(directory: Path) -> Optional[Path]:
        """디렉토리 안 가장 큰 generation 번호의 .npz 파일. 옛 league.py 와 동일 규칙
        (gen_NNNNN.npz). 없으면 None."""
        if not directory.exists():
            return None
        candidates = sorted(directory.glob("gen_*.npz"))
        return candidates[-1] if candidates else None

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict[str, Any]) -> Optional[tuple[float, float]]:
        # 보스는 맵 중앙 근처 — 룰 보스와 동일 컨셉
        ms = map_info.get("map_size", [3000.0, 3000.0])
        w, h = float(ms[0]), float(ms[1])
        rc = map_info.get("rare_clusters", []) or []
        if not rc:
            return (w * 0.5 + self._rng.uniform(-100, 100),
                    h * 0.5 + self._rng.uniform(-100, 100))
        cx, cy = float(rc[0][0]), float(rc[0][1])
        return (cx + self._rng.uniform(-80, 80), cy + self._rng.uniform(-80, 80))

    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        feat = encode_state(state, duration_sec=self._duration)
        # ε-greedy (보통 inference 시 epsilon=0). 학습 중 explore 필요 시 override.
        if self._epsilon > 0.0 and self._rng.random() < self._epsilon:
            action_idx = self._rng.randrange(ACTION_DIM)
        else:
            action_idx = self._network.argmax(feat)
        action = decode_action(action_idx, state, last_move=self._last_move)
        # last_move 캐시 — DASH 시 사용
        mv = action.get("move_dir", [0.0, 0.0])
        if abs(mv[0]) > 1e-6 or abs(mv[1]) > 1e-6:
            self._last_move = (float(mv[0]), float(mv[1]))
        return action

    def on_episode_done(self, rank: int, n_bots: int, score: float) -> None:  # noqa: ARG002
        # 학습은 외부 트레이너 담당. 여기선 통계 로깅만.
        if self._network.meta:
            logger.debug("[BR2 RL boss=%s] episode_done rank=%d/%d score=%.1f gen=%s",
                         self.bot_id, rank, n_bots, score,
                         self._network.meta.get("generation"))


__all__ = ["RLBossBR2", "DEFAULT_CHECKPOINT_DIR"]

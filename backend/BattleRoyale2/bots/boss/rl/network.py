"""numpy MLP — inference 전용. 옛 RLBossBot 의 구조와 동일 (3-layer DQN).

학습 자체는 PyTorch (별도 세션) 으로 진행하고, 체크포인트를 numpy weights 로 변환해서
이 인퍼런스 네트워크에 로드한다. 학습 환경(Phase 4 후속) 가 정해진 뒤 변환 스크립트
(convert_torch_to_numpy_br2.py — 옛 convert_torch_to_numpy.py 의 BR2 버전) 를 작성한다.

체크포인트 포맷 (.npz):
    W1 : (FEATURE_DIM, H1) float32
    b1 : (H1,)             float32
    W2 : (H1, H2)          float32
    b2 : (H2,)             float32
    W3 : (H2, ACTION_DIM)  float32
    b3 : (ACTION_DIM,)     float32
    meta (선택):
        generation : int
        win_rate   : float
        step_count : int

레이어:
    in (FEATURE_DIM=80) → H1=256 → H2=128 → out (ACTION_DIM=20)
    활성: ReLU (옛과 동일)
    출력: raw Q-values (argmax for greedy, softmax for sample)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .encoder import FEATURE_DIM
from .decoder import ACTION_DIM

logger = logging.getLogger(__name__)

H1: int = 256
H2: int = 128


def _xavier_init(shape: tuple[int, int], rng: np.random.Generator) -> np.ndarray:
    fan_in, fan_out = shape
    std = float(np.sqrt(2.0 / fan_in))   # He init for ReLU
    return rng.normal(0.0, std, size=shape).astype(np.float32)


class QNetwork:
    """3-layer numpy MLP. inference-only — backward 없음."""

    def __init__(self,
                 W1: Optional[np.ndarray] = None,
                 b1: Optional[np.ndarray] = None,
                 W2: Optional[np.ndarray] = None,
                 b2: Optional[np.ndarray] = None,
                 W3: Optional[np.ndarray] = None,
                 b3: Optional[np.ndarray] = None,
                 meta: Optional[dict[str, Any]] = None):
        if W1 is None:
            # 랜덤 초기화 — 학습 안 한 weight 으로도 동작 가능 (성능 보장 X).
            # 학습 후속 세션에서 체크포인트 로드 권장.
            rng = np.random.default_rng(seed=0)
            W1 = _xavier_init((FEATURE_DIM, H1), rng)
            b1 = np.zeros(H1, dtype=np.float32)
            W2 = _xavier_init((H1, H2), rng)
            b2 = np.zeros(H2, dtype=np.float32)
            W3 = _xavier_init((H2, ACTION_DIM), rng)
            b3 = np.zeros(ACTION_DIM, dtype=np.float32)
            logger.info("[BR2 RL] QNetwork 랜덤 초기화 — 학습된 체크포인트 권장")
        self.W1 = W1
        self.b1 = b1 if b1 is not None else np.zeros(H1, dtype=np.float32)
        self.W2 = W2
        self.b2 = b2 if b2 is not None else np.zeros(H2, dtype=np.float32)
        self.W3 = W3
        self.b3 = b3 if b3 is not None else np.zeros(ACTION_DIM, dtype=np.float32)
        self.meta = meta or {}
        self._validate_shapes()

    def _validate_shapes(self) -> None:
        assert self.W1.shape == (FEATURE_DIM, H1), f"W1 shape {self.W1.shape}"
        assert self.b1.shape == (H1,), f"b1 shape {self.b1.shape}"
        assert self.W2.shape == (H1, H2), f"W2 shape {self.W2.shape}"
        assert self.b2.shape == (H2,), f"b2 shape {self.b2.shape}"
        assert self.W3.shape == (H2, ACTION_DIM), f"W3 shape {self.W3.shape}"
        assert self.b3.shape == (ACTION_DIM,), f"b3 shape {self.b3.shape}"

    def forward(self, x: np.ndarray) -> np.ndarray:
        """x: (FEATURE_DIM,) or (batch, FEATURE_DIM) → Q-values."""
        if x.ndim == 1:
            x = x[np.newaxis, :]
            squeeze = True
        else:
            squeeze = False
        h1 = np.maximum(0.0, x @ self.W1 + self.b1)  # ReLU
        h2 = np.maximum(0.0, h1 @ self.W2 + self.b2)
        out = h2 @ self.W3 + self.b3
        return out[0] if squeeze else out

    def argmax(self, x: np.ndarray) -> int:
        q = self.forward(x)
        return int(np.argmax(q))

    @classmethod
    def load(cls, path: str | Path) -> "QNetwork":
        """.npz 체크포인트 로드. 파일이 없거나 손상이면 예외."""
        path = Path(path)
        data = np.load(path, allow_pickle=False)
        try:
            meta_raw = data["meta"].item() if "meta" in data.files else {}
        except Exception:  # noqa: BLE001
            meta_raw = {}
        return cls(
            W1=data["W1"].astype(np.float32),
            b1=data["b1"].astype(np.float32),
            W2=data["W2"].astype(np.float32),
            b2=data["b2"].astype(np.float32),
            W3=data["W3"].astype(np.float32),
            b3=data["b3"].astype(np.float32),
            meta=meta_raw if isinstance(meta_raw, dict) else {},
        )

    def save(self, path: str | Path) -> None:
        """체크포인트 저장. 메타데이터는 pickle 없이 dict → object array 로."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            W1=self.W1, b1=self.b1,
            W2=self.W2, b2=self.b2,
            W3=self.W3, b3=self.b3,
            meta=np.array(self.meta, dtype=object),
        )


__all__ = ["QNetwork", "FEATURE_DIM", "ACTION_DIM", "H1", "H2"]

"""scripts.tools.convert_torch_to_numpy 단위테스트.

torch 미설치 환경: shape 매핑 / validation 로직만 검증.
torch 설치 환경: 실제 변환 + numpy 봇 forward 패스 round-trip.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

# 변환 스크립트 직접 import 가능하게 sys.path 보강
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "tools"
sys.path.insert(0, str(_TOOLS_DIR))

import convert_torch_to_numpy as conv  # noqa: E402

try:
    import torch  # noqa: F401
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

requires_torch = pytest.mark.skipif(not HAS_TORCH, reason="torch not installed")


# ---------------------------------------------------------------------------
# torch 없이 검증 가능한 부분 (shape/validation 로직)
# ---------------------------------------------------------------------------

def test_validate_shapes_rejects_wrong_shape():
    bad = {
        "W1": np.zeros((43, 64)).tolist(),   # 64 (wrong, expected 256)
        "b1": np.zeros(64).tolist(),
        "W2": np.zeros((64, 128)).tolist(),
        "b2": np.zeros(128).tolist(),
        "W3": np.zeros((128, 19)).tolist(),
        "b3": np.zeros(19).tolist(),
    }
    with pytest.raises(ValueError, match="shape"):
        conv._validate_shapes(bad, "online")


def test_validate_shapes_accepts_correct_shape():
    good = {
        "W1": np.zeros((43, 256)).tolist(),
        "b1": np.zeros(256).tolist(),
        "W2": np.zeros((256, 128)).tolist(),
        "b2": np.zeros(128).tolist(),
        "W3": np.zeros((128, 19)).tolist(),
        "b3": np.zeros(19).tolist(),
    }
    conv._validate_shapes(good, "online")  # 예외 없이 통과


def test_torch_layer_keys_complete():
    """3 hidden layer = 3 weight/bias pairs."""
    assert len(conv.TORCH_LAYER_KEYS) == 3
    np_keys = []
    for _w, _b, np_w, np_b in conv.TORCH_LAYER_KEYS:
        np_keys.extend([np_w, np_b])
    assert sorted(np_keys) == ["W1", "W2", "W3", "b1", "b2", "b3"]


# ---------------------------------------------------------------------------
# torch 환경에서 실제 변환 검증
# ---------------------------------------------------------------------------

@requires_torch
def test_convert_roundtrip(tmp_path):
    """torch checkpoint → numpy.json → 같은 입력에 같은 출력 확인."""
    import torch as _torch
    # 가짜 torch checkpoint 생성 (학습된 봇 mimic)
    sd_online = {
        "net.0.weight": _torch.randn(256, 43),
        "net.0.bias":   _torch.randn(256),
        "net.2.weight": _torch.randn(128, 256),
        "net.2.bias":   _torch.randn(128),
        "net.4.weight": _torch.randn(19, 128),
        "net.4.bias":   _torch.randn(19),
    }
    sd_target = {k: v.clone() for k, v in sd_online.items()}

    torch_ckpt_path = tmp_path / "fake.pt"
    _torch.save({
        "version":       4,
        "n_features":    43,
        "n_hidden1":     256,
        "n_hidden2":     128,
        "n_actions":     19,
        "step_count":    12345,
        "episode_count": 678,
        "epsilon":       0.123,
        "online":        sd_online,
        "target":        sd_target,
    }, torch_ckpt_path)

    numpy_path = tmp_path / "out.json"
    result = conv.convert(torch_ckpt_path, numpy_path)

    # 메타 보존
    assert result["version"]       == 4
    assert result["step_count"]    == 12345
    assert result["episode_count"] == 678
    assert abs(result["epsilon"] - 0.123) < 1e-5

    # 파일에 저장됐는지
    assert numpy_path.exists()
    saved = json.loads(numpy_path.read_text())
    assert saved["version"] == 4

    # transpose 정확성: torch (out,in) → numpy (in,out)
    assert np.asarray(saved["online"]["W1"]).shape == (43, 256)
    assert np.asarray(saved["online"]["W2"]).shape == (256, 128)
    assert np.asarray(saved["online"]["W3"]).shape == (128, 19)

    # 값 일치 (transpose 후 원본과 일치)
    w1_np = np.asarray(saved["online"]["W1"])
    w1_torch_T = sd_online["net.0.weight"].numpy().T
    np.testing.assert_allclose(w1_np, w1_torch_T, atol=1e-5)


@requires_torch
def test_convert_forward_equivalence(tmp_path):
    """torch 모델 forward 와 numpy 모델 forward 가 같은 출력 내는지 (핵심 검증)."""
    import torch as _torch
    import torch.nn as nn

    # 1) torch 모델 생성
    class TinyDQN(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(43, 256),
                nn.ReLU(),
                nn.Linear(256, 128),
                nn.ReLU(),
                nn.Linear(128, 19),
            )
        def forward(self, x):
            return self.net(x)

    torch_model = TinyDQN()
    torch_model.eval()

    # 2) checkpoint 저장
    torch_ckpt_path = tmp_path / "model.pt"
    _torch.save({
        "version":       4,
        "n_features":    43,
        "n_hidden1":     256,
        "n_hidden2":     128,
        "n_actions":     19,
        "step_count":    0,
        "episode_count": 0,
        "epsilon":       0.0,
        "online":        torch_model.state_dict(),
        "target":        torch_model.state_dict(),
    }, torch_ckpt_path)

    # 3) 변환
    numpy_path = tmp_path / "out.json"
    conv.convert(torch_ckpt_path, numpy_path)

    # 4) numpy DQNetwork 로 로드
    # rl_boss_bot 모듈 직접 import 시 게임 엔진 dependency 회피 위해 헬퍼만 사용
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from bots.boss.rl_boss_bot import DQNetwork

    saved = json.loads(numpy_path.read_text())
    np_net = DQNetwork()
    np_net.from_dict(saved["online"])
    assert np_net.shape_ok()

    # 5) 같은 input 으로 forward 결과 비교
    rng = np.random.default_rng(42)
    phi = rng.standard_normal(43).astype(np.float32)

    torch_out = torch_model(_torch.from_numpy(phi)).detach().numpy()
    np_out    = np_net.forward(phi)

    np.testing.assert_allclose(np_out, torch_out, atol=1e-4)


@requires_torch
def test_convert_rejects_wrong_version(tmp_path):
    import torch as _torch
    bad = tmp_path / "v3.pt"
    _torch.save({"version": 3}, bad)
    with pytest.raises(ValueError, match="version"):
        conv.convert(bad, tmp_path / "out.json")


@requires_torch
def test_convert_rejects_wrong_hidden_size(tmp_path):
    import torch as _torch
    bad = tmp_path / "wrong.pt"
    _torch.save({
        "version":   4,
        "n_features": 43,
        "n_hidden1":  64,   # ← wrong
        "n_hidden2": 128,
        "n_actions":  19,
        "online":    {}, "target": {},
    }, bad)
    with pytest.raises(ValueError, match="hyperparams"):
        conv.convert(bad, tmp_path / "out.json")

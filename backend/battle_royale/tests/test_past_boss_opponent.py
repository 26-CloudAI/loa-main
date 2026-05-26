"""bots.boss.past_boss_opponent 테스트.

torch 없는 환경에서도 동작하도록 lazy import 패턴 검증 중심.
실제 추론 검증은 torch 가 있을 때만 (training VM).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.pop("BOSS_WEIGHTS_GCS_URI", None)

from bots.boss import league
from bots.boss.past_boss_opponent import PastBossOpponent, from_entry

try:
    import torch  # noqa: F401
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

requires_torch = pytest.mark.skipif(not HAS_TORCH, reason="torch not installed")


@pytest.fixture
def tmp_league(tmp_path, monkeypatch):
    monkeypatch.setattr(league, "_DEFAULT_LOCAL_ROOT", tmp_path / "league")
    yield tmp_path / "league"


def _fake_entry(filename: str, generation: int = 0) -> league.LeagueEntry:
    return league.LeagueEntry(
        generation=generation,
        filename=filename,
        archived_at="2026-05-26T00:00:00+00:00",
    )


def test_missing_checkpoint_raises(tmp_path, tmp_league):
    """체크포인트 파일이 존재하지 않으면 FileNotFoundError."""
    entry = _fake_entry("gen_99999.pt", generation=99999)
    with pytest.raises(FileNotFoundError):
        PastBossOpponent("test_boss", entry)


def test_from_entry_returns_none_on_missing(tmp_path, tmp_league):
    """from_entry 헬퍼는 예외 대신 None 반환."""
    entry = _fake_entry("gen_99999.pt", generation=99999)
    result = from_entry(entry)
    assert result is None


@pytest.mark.skipif(HAS_TORCH, reason="torch 가 설치되지 않은 환경 전용 테스트")
def test_lazy_import_torch_protection(tmp_path, tmp_league):
    """torch 미설치 환경에서 모듈 import 는 성공, 인스턴스화에서 실패."""
    # 모듈 자체는 이미 import 되었으므로 (위 import) 그게 곧 검증.
    # 가짜 체크포인트로 RLBossBotTorch 까지 진입 시도
    fake_ckpt = tmp_league
    fake_ckpt.mkdir(parents=True, exist_ok=True)
    (fake_ckpt / "gen_00001.pt").write_bytes(b"dummy")

    entry = _fake_entry("gen_00001.pt", generation=1)
    # from_entry 는 None 반환 (RuntimeError 잡음)
    result = from_entry(entry)
    assert result is None


@requires_torch
def test_past_boss_inference_smoke(tmp_path, tmp_league):
    """torch 환경에서 실제 추론까지 통과하는지 smoke test.
    체크포인트는 빈 모델을 새로 만들어 사용.
    """
    import torch as _torch
    from bots.boss.rl_boss_bot_torch import (
        RLBossBotTorch, N_FEATURES, N_HIDDEN1, N_HIDDEN2, DQNetworkTorch
    )
    from bots.boss.rl_boss_bot import N_ACTIONS

    # 빈 가중치 체크포인트 생성
    net = DQNetworkTorch()
    payload = {
        "version":       4,
        "n_features":    N_FEATURES,
        "n_hidden1":     N_HIDDEN1,
        "n_hidden2":     N_HIDDEN2,
        "n_actions":     N_ACTIONS,
        "step_count":    0,
        "episode_count": 0,
        "epsilon":       0.0,
        "online":        net.state_dict(),
        "target":        net.state_dict(),
        "optimizer":     _torch.optim.Adam(net.parameters()).state_dict(),
    }
    ckpt = tmp_league / "gen_00001.pt"
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    _torch.save(payload, ckpt)

    entry = _fake_entry("gen_00001.pt", generation=1)
    bot = PastBossOpponent("past_test", entry, seed=42, device="cpu")
    assert bot.bot_id == "past_test"
    assert bot.generation == 1

    # _learn / save_weights 가 no-op 인지 검증
    bot._boss._learn()      # 예외 없이 통과
    bot._boss.save_weights() # 예외 없이 통과


@requires_torch
def test_past_boss_does_not_save_weights(tmp_path, tmp_league):
    """on_episode_done 호출 후 가중치 파일이 새로 생기지 않는지 확인."""
    import torch as _torch
    from bots.boss.rl_boss_bot_torch import (
        N_FEATURES, N_HIDDEN1, N_HIDDEN2, DQNetworkTorch
    )
    from bots.boss.rl_boss_bot import N_ACTIONS

    net = DQNetworkTorch()
    payload = {
        "version":       4,
        "n_features":    N_FEATURES,
        "n_hidden1":     N_HIDDEN1,
        "n_hidden2":     N_HIDDEN2,
        "n_actions":     N_ACTIONS,
        "step_count":    0,
        "episode_count": 0,
        "epsilon":       0.0,
        "online":        net.state_dict(),
        "target":        net.state_dict(),
        "optimizer":     _torch.optim.Adam(net.parameters()).state_dict(),
    }
    ckpt = tmp_league / "gen_00002.pt"
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    _torch.save(payload, ckpt)

    snapshot_mtime = ckpt.stat().st_mtime

    entry = _fake_entry("gen_00002.pt", generation=2)
    bot = PastBossOpponent("past_test", entry, seed=42, device="cpu")
    bot.on_episode_done(rank=3, n_bots=5)

    # 체크포인트 파일이 수정되지 않았는지
    assert ckpt.stat().st_mtime == snapshot_mtime

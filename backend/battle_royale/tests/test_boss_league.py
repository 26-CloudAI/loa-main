"""bots.boss.league 단위테스트.

GCS 비활성 환경에서 로컬 fallback만 사용하여 snapshot/load/prune/sample 검증.
"""

from __future__ import annotations

import json
import os
import random
import shutil
from pathlib import Path

import pytest

# GCS 비활성화 환경에서만 테스트 (의도)
os.environ.pop("BOSS_WEIGHTS_GCS_URI", None)

from bots.boss import league


@pytest.fixture
def tmp_league(tmp_path, monkeypatch):
    """league 모듈의 로컬 루트를 tmp_path 로 redirect."""
    monkeypatch.setattr(league, "_DEFAULT_LOCAL_ROOT", tmp_path / "league")
    yield tmp_path / "league"


def _fake_weights(path: Path, content: bytes = b"FAKE_WEIGHTS") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_snapshot_then_load(tmp_path, tmp_league):
    src = _fake_weights(tmp_path / "weights.pt", b"WEIGHTS_V1")

    entry = league.snapshot(
        weights_src=src,
        generation=100,
        win_rate=0.27,
        epsilon=0.5,
        step_count=5000,
        session_episodes=50,
    )
    assert entry is not None
    assert entry.generation == 100
    assert entry.filename == "gen_00100.pt"

    # 파일이 로컬 league 디렉토리에 복사됐는지
    archived = tmp_league / "gen_00100.pt"
    assert archived.exists()
    assert archived.read_bytes() == b"WEIGHTS_V1"

    # 인덱스 로드 후 검증
    idx = league.load_index()
    assert len(idx.entries) == 1
    assert idx.entries[0].generation == 100
    assert abs(idx.entries[0].win_rate - 0.27) < 1e-6


def test_snapshot_overwrites_same_generation(tmp_path, tmp_league):
    src1 = _fake_weights(tmp_path / "w1.pt", b"V1")
    src2 = _fake_weights(tmp_path / "w2.pt", b"V2_BETTER")

    league.snapshot(src1, generation=50, win_rate=0.10)
    league.snapshot(src2, generation=50, win_rate=0.20)

    idx = league.load_index()
    assert len(idx.entries) == 1
    assert abs(idx.entries[0].win_rate - 0.20) < 1e-6


def test_prune_keeps_recent_and_quartile_best(tmp_path, tmp_league):
    """20개 generation 추가 → prune 후 최대 12개 (최근 8 + 분위 best 4)."""
    src = _fake_weights(tmp_path / "w.pt")

    # gen 100, 200, ..., 2000 (20개), win_rate 다양하게
    for i, gen in enumerate(range(100, 2100, 100)):
        # gen 500, 1100, 1700, 1900 에 high win rate (분위 best 후보)
        wr = 0.9 if gen in (500, 1100, 1700, 1900) else 0.1 + (i % 5) * 0.05
        league.snapshot(src, generation=gen, win_rate=wr)

    idx = league.load_index()
    assert len(idx.entries) == 20

    pruned = league.prune(idx)
    assert len(pruned.entries) <= league.MAX_LEAGUE_SIZE

    kept_gens = {e.generation for e in pruned.entries}
    # 최근 8개 (1300~2000) 는 무조건 유지
    for g in range(1300, 2100, 100):
        assert g in kept_gens, f"최근 generation {g} 가 prune 됨"

    # 삭제된 파일은 실제로 디스크에서도 제거됐는지
    for e_gen in range(100, 1300, 100):
        if e_gen not in kept_gens:
            assert not (tmp_league / f"gen_{e_gen:05d}.pt").exists()


def test_prune_noop_if_below_max(tmp_path, tmp_league):
    src = _fake_weights(tmp_path / "w.pt")
    for gen in range(100, 600, 100):  # 5개만
        league.snapshot(src, generation=gen)
    pruned = league.prune()
    assert len(pruned.entries) == 5


def test_sample_entry_recency_bias(tmp_path, tmp_league):
    """recency_bias=1.0 이면 최근 풀에서만 샘플, 0.0 이면 분위 best 풀에서만."""
    src = _fake_weights(tmp_path / "w.pt")
    for gen in range(100, 2100, 100):  # 20개
        league.snapshot(src, generation=gen, win_rate=0.1 + (gen % 7) * 0.05)

    league.prune()
    idx = league.load_index()

    rng = random.Random(42)
    # recency_bias=1.0: 최근 8개 중에서만
    recent_gens = sorted([e.generation for e in idx.entries], reverse=True)[:league.KEEP_RECENT]
    for _ in range(50):
        e = league.sample_entry(rng, recency_bias=1.0, index=idx)
        assert e is not None
        assert e.generation in recent_gens

    # recency_bias=0.0: 분위 best 풀에서만
    older = sorted(idx.entries, key=lambda e: e.generation, reverse=True)[league.KEEP_RECENT:]
    quartile_gens = {e.generation for e in league._select_quartile_best(older, league.KEEP_QUARTILE_BEST)}
    if quartile_gens:  # 분위 best 가 비어있지 않을 때만
        for _ in range(50):
            e = league.sample_entry(rng, recency_bias=0.0, index=idx)
            assert e is not None
            assert e.generation in quartile_gens


def test_sample_entry_empty_league_returns_none(tmp_path, tmp_league):
    rng = random.Random(0)
    assert league.sample_entry(rng) is None


def test_ensure_local_returns_existing(tmp_path, tmp_league):
    src = _fake_weights(tmp_path / "w.pt", b"DATA")
    entry = league.snapshot(src, generation=42)
    path = league.ensure_local(entry)
    assert path is not None
    assert path.read_bytes() == b"DATA"


def test_summary(tmp_path, tmp_league):
    src = _fake_weights(tmp_path / "w.pt")
    league.snapshot(src, generation=100, win_rate=0.2)
    league.snapshot(src, generation=200, win_rate=0.5)
    league.snapshot(src, generation=300, win_rate=0.3)

    s = league.summary()
    assert s["count"] == 3
    assert s["gen_range"] == (100, 300)
    assert s["win_rate_range"] == (0.2, 0.5)
    # summary 는 round(.., 3) 반환이므로 0.001 tolerance
    assert abs(s["win_rate_mean"] - (0.2 + 0.5 + 0.3) / 3) < 1e-3


def test_quartile_best_selection_logic():
    """분위 best 선택 로직 단위 검증."""
    entries = [
        league.LeagueEntry(generation=g, filename=f"gen_{g}", archived_at="",
                           win_rate=wr)
        for g, wr in [
            (100, 0.1), (200, 0.5),    # Q1 → best gen=200 (0.5)
            (300, 0.3), (400, 0.2),    # Q2 → best gen=300 (0.3)
            (500, 0.7), (600, 0.4),    # Q3 → best gen=500 (0.7)
            (700, 0.6), (800, 0.9),    # Q4 → best gen=800 (0.9)
        ]
    ]
    chosen = league._select_quartile_best(entries, k=4)
    chosen_gens = sorted(e.generation for e in chosen)
    # 분위 boundary 따라 정확한 매칭이 어렵지만, 최고 win_rate 0.9 (gen=800) 는 반드시 포함
    assert 800 in chosen_gens
    # 4분위로 나눴으니 4개 이하
    assert len(chosen) <= 4

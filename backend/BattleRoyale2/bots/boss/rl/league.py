"""league_br2 — BR2 보스 자기대전 체크포인트 풀.

옛 backend/battle_royale/bots/boss/league.py 의 BR2 버전. 동일한 운영 정책 유지:
    - 풀 크기: 최대 12
    - 보존 전략: 최근 8 + 승률 상위 quartile 4
    - 샘플링: recency_bias=0.6 (60% 최근 / 40% 상위 승률)
    - 파일 포맷: gen_NNNNN.npz (옛 .pt 와 다름 — numpy 포맷)
    - 메타 인덱스: league_index.json (옛 동일 스키마)

옛은 PyTorch state_dict 였지만 BR2 는 inference-only 라 .npz 로 보관. 학습 스크립트
(별도 세션) 가 PyTorch → npz 변환 시 같은 generation 번호로 league 에 등록.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 옛 league.py 와 동일 정책 (메모리에 등록된 운영 경험 보존)
MAX_POOL_SIZE: int = 12
RECENT_KEEP: int = 8
QUARTILE_KEEP: int = 4
RECENCY_BIAS: float = 0.6

DEFAULT_LEAGUE_DIR: Path = Path(__file__).resolve().parent / "checkpoints"
INDEX_FILENAME: str = "league_index.json"


@dataclass
class LeagueEntry:
    """체크포인트 메타. 옛 LeagueEntry 와 동일 스키마."""
    generation: int
    filename: str
    win_rate: float
    epsilon: float
    step_count: int
    session_episodes: int = 0
    timestamp: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class LeagueIndex:
    """체크포인트 풀 인덱스. 메모리 + 파일(league_index.json) 동기화."""

    def __init__(self, directory: Path = DEFAULT_LEAGUE_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.entries: list[LeagueEntry] = []
        self._load()

    @property
    def index_path(self) -> Path:
        return self.directory / INDEX_FILENAME

    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            self.entries = [LeagueEntry(**e) for e in raw.get("entries", [])]
            logger.info("[BR2 league] %d entries loaded from %s",
                        len(self.entries), self.index_path)
        except Exception:  # noqa: BLE001
            logger.exception("[BR2 league] index 로드 실패 — 빈 풀로 시작")
            self.entries = []

    def save(self) -> None:
        payload = {"entries": [asdict(e) for e in self.entries]}
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, entry: LeagueEntry) -> None:
        """새 체크포인트 등록 + 풀 크기 prune. 파일은 별도 관리 — 여기서 삭제만 한다."""
        self.entries.append(entry)
        self._prune()
        self.save()

    def _prune(self) -> None:
        """MAX_POOL_SIZE 초과분 제거. 보존 = (최근 RECENT_KEEP) ∪ (승률 quartile QUARTILE_KEEP)."""
        if len(self.entries) <= MAX_POOL_SIZE:
            return
        by_gen = sorted(self.entries, key=lambda e: e.generation)
        by_wr = sorted(self.entries, key=lambda e: e.win_rate, reverse=True)
        keep_ids = set()
        for e in by_gen[-RECENT_KEEP:]:
            keep_ids.add(e.generation)
        for e in by_wr[:QUARTILE_KEEP]:
            keep_ids.add(e.generation)
        new_entries = [e for e in self.entries if e.generation in keep_ids]
        removed = [e for e in self.entries if e.generation not in keep_ids]
        for e in removed:
            try:
                f = self.directory / e.filename
                if f.exists():
                    f.unlink()
            except Exception:  # noqa: BLE001
                logger.exception("[BR2 league] 파일 삭제 실패: %s", e.filename)
        self.entries = new_entries

    def sample(self, rng: Optional[random.Random] = None) -> Optional[LeagueEntry]:
        """recency_bias 적용해 한 체크포인트 샘플.
        recency_bias 확률로 최근 8개 풀에서, 나머지 확률로 승률 quartile 4개 풀에서 선택."""
        if not self.entries:
            return None
        rng = rng or random.Random()
        if rng.random() < RECENCY_BIAS:
            pool = sorted(self.entries, key=lambda e: e.generation)[-RECENT_KEEP:]
        else:
            pool = sorted(self.entries, key=lambda e: e.win_rate, reverse=True)[:QUARTILE_KEEP]
        return rng.choice(pool) if pool else None

    def latest(self) -> Optional[LeagueEntry]:
        if not self.entries:
            return None
        return max(self.entries, key=lambda e: e.generation)

    def filepath(self, entry: LeagueEntry) -> Path:
        return self.directory / entry.filename

    def __len__(self) -> int:
        return len(self.entries)


__all__ = [
    "LeagueEntry", "LeagueIndex",
    "DEFAULT_LEAGUE_DIR", "INDEX_FILENAME",
    "MAX_POOL_SIZE", "RECENT_KEEP", "QUARTILE_KEEP", "RECENCY_BIAS",
]

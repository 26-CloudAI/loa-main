"""
bots/boss/league.py — Self-play league 관리

보스의 과거 체크포인트를 풀로 보관하여 multi-agent autocurriculum 메커니즘을
구현한다. 학습 중 보스는 (현재 메타 봇 + 다양성 봇 + League 과거 보스) 혼합 풀을
상대로 학습하며, 자신의 과거 버전을 상대로 약점을 발견한다.

GCS 구조 (BOSS_WEIGHTS_GCS_URI 와 같은 디렉토리 sibling):
  league/
    league_index.json       메타데이터 인덱스 (선언 출처)
    gen_00050.pt            세대별 PyTorch 체크포인트 (rl_boss_bot_torch 형식)
    gen_00100.pt
    ...

로컬 fallback:
  GCS 비활성화 시 `bots/boss/league/` 하위에 동일 구조로 보관.

Pruning 정책 ("최근 8 + 분기별 best 4 = 최대 12개"):
  - 최근:        generation 상위 8개 (메타 적응)
  - 분기별 best: 전체 generation 범위를 4분위로 나누고 각 분위
                 win_rate 최고 1개 (다양성·archaeological 보존)
  - Union 후 중복 제거

Sampling (학습 시):
  recency_bias (기본 0.6): 최근 풀에서 60%, 분기별 best 풀에서 40%

torch 의존성 없음 — 체크포인트는 opaque 파일로 처리. 로딩은 PastBossOpponent 담당.
"""

from __future__ import annotations

import json
import logging
import random
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.arena import gcs_weights

logger = logging.getLogger("league")

LEAGUE_DIR_NAME      = "league"
INDEX_FILENAME       = "league/league_index.json"
CKPT_FILENAME_FMT    = "gen_{generation:05d}.pt"

# Pruning 파라미터
KEEP_RECENT          = 8
KEEP_QUARTILE_BEST   = 4   # 4분위 × 1 = 4개
MAX_LEAGUE_SIZE      = KEEP_RECENT + KEEP_QUARTILE_BEST   # 최대 12

# 로컬 fallback 디렉토리 (GCS 비활성화 시)
_DEFAULT_LOCAL_ROOT  = Path(__file__).parent / LEAGUE_DIR_NAME


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------

@dataclass
class LeagueEntry:
    generation:   int                 # boss._episode_count 누적 (snapshot 시점)
    filename:     str                 # league/ 하위 파일명 (예: gen_00050.pt)
    archived_at:  str                 # ISO8601 UTC
    win_rate:     float = 0.0         # 스냅샷 시점 직전 세션 승률 (회귀 측정용)
    epsilon:      float = 0.0
    step_count:   int   = 0
    session_episodes: int = 0         # 그 세션에서 학습한 에피소드 수
    notes:        str   = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LeagueEntry":
        # 모르는 필드는 무시, 누락된 필드는 default 사용
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class LeagueIndex:
    version:    int = 1
    updated_at: str = ""
    entries:    list[LeagueEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version":    self.version,
            "updated_at": self.updated_at,
            "entries":    [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LeagueIndex":
        entries = [LeagueEntry.from_dict(e) for e in d.get("entries", [])]
        return cls(
            version    = int(d.get("version", 1)),
            updated_at = d.get("updated_at", ""),
            entries    = entries,
        )

    @classmethod
    def empty(cls) -> "LeagueIndex":
        return cls(updated_at=_now_iso())


# ---------------------------------------------------------------------------
# 시간/경로 헬퍼
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ckpt_filename(generation: int) -> str:
    return CKPT_FILENAME_FMT.format(generation=generation)


def _local_root() -> Path:
    return _DEFAULT_LOCAL_ROOT


# ---------------------------------------------------------------------------
# GCS / 로컬 IO (체크포인트 파일)
# ---------------------------------------------------------------------------

def _gcs_sibling_uri(filename: str) -> Optional[str]:
    """gcs_weights 의 _GCS_URI 와 같은 디렉토리의 자식 파일 URI 계산."""
    base = gcs_weights._GCS_URI
    if not base:
        return None
    parent = base.rsplit("/", 1)[0]
    return f"{parent}/{filename}"


def _upload_ckpt_to_gcs(src: Path, filename: str) -> bool:
    """체크포인트 파일을 GCS 의 league/ 하위에 업로드."""
    uri = _gcs_sibling_uri(f"{LEAGUE_DIR_NAME}/{filename}")
    if not uri:
        return False
    return gcs_weights.upload(src, gcs_uri=uri)


def _download_ckpt_from_gcs(filename: str, dest: Path) -> Optional[Path]:
    """GCS 의 league/<filename> 을 dest 로 다운로드."""
    uri = _gcs_sibling_uri(f"{LEAGUE_DIR_NAME}/{filename}")
    if not uri:
        return None
    return gcs_weights.download(gcs_uri=uri, dest=dest)


def _delete_ckpt_from_gcs(filename: str) -> bool:
    """GCS 의 league/<filename> 삭제. 인덱스에서 빠진 파일 정리용."""
    uri = _gcs_sibling_uri(f"{LEAGUE_DIR_NAME}/{filename}")
    if not uri:
        return False
    try:
        from google.cloud import storage  # type: ignore
        bucket_name, blob_name = gcs_weights._parse_uri(uri)
        blob = storage.Client().bucket(bucket_name).blob(blob_name)
        if blob.exists():
            blob.delete()
            logger.info("league: GCS 삭제 %s", uri)
        return True
    except Exception as exc:
        logger.warning("league: GCS 삭제 실패 %s — %s", filename, exc)
        return False


# ---------------------------------------------------------------------------
# 인덱스 IO
# ---------------------------------------------------------------------------

def load_index() -> LeagueIndex:
    """League 인덱스 로드. GCS 우선, 실패 시 로컬, 그것도 없으면 empty."""
    if gcs_weights.enabled():
        data = gcs_weights.download_json(INDEX_FILENAME)
        if data is not None:
            try:
                return LeagueIndex.from_dict(data)
            except Exception as exc:
                logger.warning("league: GCS 인덱스 파싱 실패, 빈 인덱스로 시작 — %s", exc)
                return LeagueIndex.empty()

    local = _local_root() / "league_index.json"
    if local.exists():
        try:
            return LeagueIndex.from_dict(json.loads(local.read_text()))
        except Exception as exc:
            logger.warning("league: 로컬 인덱스 파싱 실패 — %s", exc)
    return LeagueIndex.empty()


def save_index(index: LeagueIndex) -> bool:
    """인덱스 저장. GCS + 로컬 동시 (둘 다 best-effort)."""
    index.updated_at = _now_iso()
    data = index.to_dict()
    ok_gcs = True
    if gcs_weights.enabled():
        ok_gcs = gcs_weights.upload_json(data, INDEX_FILENAME)

    try:
        local = _local_root() / "league_index.json"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as exc:
        logger.warning("league: 로컬 인덱스 저장 실패 — %s", exc)
    return ok_gcs


# ---------------------------------------------------------------------------
# Snapshot — 학습 중 보스를 League 에 추가
# ---------------------------------------------------------------------------

def snapshot(
    weights_src: Path,
    generation: int,
    win_rate:   float = 0.0,
    epsilon:    float = 0.0,
    step_count: int   = 0,
    session_episodes: int = 0,
    notes:      str   = "",
) -> Optional[LeagueEntry]:
    """
    현재 학습 보스의 가중치 파일을 League 에 추가한다.

    Args:
      weights_src   : 원본 가중치 파일 경로 (예: trained_weights_torch.pt)
      generation    : 학습 누적 에피소드 (boss._episode_count)
      win_rate~step_count : 메타데이터 (회귀 모니터링용)

    Returns:
      추가된 LeagueEntry (실패 시 None).
    """
    if not weights_src.exists():
        logger.error("league.snapshot: weights_src 없음 — %s", weights_src)
        return None

    filename = _ckpt_filename(generation)
    entry = LeagueEntry(
        generation       = generation,
        filename         = filename,
        archived_at      = _now_iso(),
        win_rate         = float(win_rate),
        epsilon          = float(epsilon),
        step_count       = int(step_count),
        session_episodes = int(session_episodes),
        notes            = notes,
    )

    # 1) 로컬 복사 (먼저 보장)
    local_root = _local_root()
    local_root.mkdir(parents=True, exist_ok=True)
    local_dest = local_root / filename
    try:
        shutil.copyfile(weights_src, local_dest)
    except Exception as exc:
        logger.error("league.snapshot: 로컬 복사 실패 — %s", exc)
        return None

    # 2) GCS 업로드 (best-effort)
    if gcs_weights.enabled():
        ok = _upload_ckpt_to_gcs(local_dest, filename)
        if not ok:
            logger.warning("league.snapshot: GCS 업로드 실패 (로컬은 보존됨) — %s", filename)

    # 3) 인덱스 갱신
    index = load_index()
    # 같은 generation 이 이미 있으면 덮어쓰기 (드물지만 안전)
    index.entries = [e for e in index.entries if e.generation != generation]
    index.entries.append(entry)
    index.entries.sort(key=lambda e: e.generation)
    save_index(index)

    logger.info("league.snapshot: gen=%d win_rate=%.3f → %s (총 %d개)",
                generation, win_rate, filename, len(index.entries))
    return entry


# ---------------------------------------------------------------------------
# Prune — 최근 8 + 분기별 best 4 = 최대 12 유지
# ---------------------------------------------------------------------------

def _select_quartile_best(entries: list[LeagueEntry], k: int) -> list[LeagueEntry]:
    """전체 generation 범위를 k 분위로 나누고 각 분위 win_rate 최고 1개 반환."""
    if not entries or k <= 0:
        return []
    if len(entries) <= k:
        return list(entries)

    sorted_by_gen = sorted(entries, key=lambda e: e.generation)
    gen_min = sorted_by_gen[0].generation
    gen_max = sorted_by_gen[-1].generation
    span = max(1, gen_max - gen_min)

    bins: list[list[LeagueEntry]] = [[] for _ in range(k)]
    for e in sorted_by_gen:
        # [0, k-1] 범위로 클램프
        idx = min(k - 1, int((e.generation - gen_min) / span * k))
        bins[idx].append(e)

    chosen: list[LeagueEntry] = []
    for b in bins:
        if b:
            chosen.append(max(b, key=lambda e: e.win_rate))
    return chosen


def prune(index: Optional[LeagueIndex] = None, delete_files: bool = True) -> LeagueIndex:
    """
    League 인덱스를 정책에 따라 prune 한다.

    유지: (최근 KEEP_RECENT) ∪ (분기별 best KEEP_QUARTILE_BEST), 중복 제거.
    삭제된 항목의 체크포인트 파일도 GCS/로컬에서 best-effort 삭제.
    """
    if index is None:
        index = load_index()

    if len(index.entries) <= MAX_LEAGUE_SIZE:
        return index

    by_gen   = sorted(index.entries, key=lambda e: e.generation, reverse=True)
    recent   = by_gen[:KEEP_RECENT]
    older    = by_gen[KEEP_RECENT:]
    quartile = _select_quartile_best(older, KEEP_QUARTILE_BEST)

    keep_keys = {e.generation for e in recent} | {e.generation for e in quartile}
    keep_entries = [e for e in index.entries if e.generation in keep_keys]
    drop_entries = [e for e in index.entries if e.generation not in keep_keys]

    keep_entries.sort(key=lambda e: e.generation)
    index.entries = keep_entries
    save_index(index)

    if delete_files:
        for e in drop_entries:
            try:
                local = _local_root() / e.filename
                if local.exists():
                    local.unlink()
            except Exception as exc:
                logger.warning("league.prune: 로컬 삭제 실패 %s — %s", e.filename, exc)
            if gcs_weights.enabled():
                _delete_ckpt_from_gcs(e.filename)

    logger.info("league.prune: %d개 유지, %d개 삭제",
                len(keep_entries), len(drop_entries))
    return index


# ---------------------------------------------------------------------------
# Sampling — 학습 시 PastBossOpponent 가 사용할 체크포인트 선택
# ---------------------------------------------------------------------------

def sample_entry(
    rng: random.Random,
    recency_bias: float = 0.6,
    index: Optional[LeagueIndex] = None,
) -> Optional[LeagueEntry]:
    """
    League 에서 학습용 상대 체크포인트 1개를 선택한다.

    정책:
      recency_bias 확률로 "최근 KEEP_RECENT" 풀에서 균등 샘플,
      (1 - recency_bias) 확률로 "분기별 best KEEP_QUARTILE_BEST" 풀에서 균등 샘플.

    한쪽 풀이 비어있으면 다른 쪽에서 fallback. 둘 다 없으면 None.
    """
    if index is None:
        index = load_index()
    if not index.entries:
        return None

    by_gen   = sorted(index.entries, key=lambda e: e.generation, reverse=True)
    recent   = by_gen[:KEEP_RECENT]
    older    = by_gen[KEEP_RECENT:]
    quartile = _select_quartile_best(older, KEEP_QUARTILE_BEST)

    use_recent = rng.random() < recency_bias
    pool = recent if use_recent else quartile
    if not pool:
        pool = quartile if use_recent else recent
    if not pool:
        return None
    return rng.choice(pool)


# ---------------------------------------------------------------------------
# 체크포인트 파일 확보 — 로컬에 없으면 GCS에서 다운로드
# ---------------------------------------------------------------------------

def ensure_local(entry: LeagueEntry) -> Optional[Path]:
    """
    LeagueEntry 의 체크포인트 파일이 로컬에 있는지 확인하고,
    없으면 GCS 에서 다운로드한다. 최종 경로 반환 (실패 시 None).
    """
    local = _local_root() / entry.filename
    if local.exists():
        return local
    if gcs_weights.enabled():
        local.parent.mkdir(parents=True, exist_ok=True)
        return _download_ckpt_from_gcs(entry.filename, local)
    logger.warning("league.ensure_local: 파일 없음 + GCS 비활성 — %s", entry.filename)
    return None


# ---------------------------------------------------------------------------
# 디버그/통계
# ---------------------------------------------------------------------------

def summary(index: Optional[LeagueIndex] = None) -> dict:
    """현재 League 상태 요약."""
    if index is None:
        index = load_index()
    n = len(index.entries)
    if n == 0:
        return {"count": 0, "gen_range": None, "win_rate_range": None}
    gens = [e.generation for e in index.entries]
    wrs  = [e.win_rate for e in index.entries]
    return {
        "count": n,
        "gen_range":      (min(gens), max(gens)),
        "win_rate_range": (round(min(wrs), 3), round(max(wrs), 3)),
        "win_rate_mean":  round(sum(wrs) / n, 3),
        "updated_at":     index.updated_at,
    }

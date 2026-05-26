"""
bots/boss/past_boss_opponent.py — League 체크포인트 frozen wrapper

학습 보스의 과거 체크포인트(LeagueEntry)를 로드해 BotInterface 로 노출한다.
학습 중인 메인 보스는 이 wrapper 를 통해 자기 자신의 과거 버전들과 대전하며
autocurriculum 을 형성한다.

설계:
  - epsilon_override=0.0   : deterministic greedy (탐험 없음)
  - _learn no-op            : 매 tick TD 업데이트 비활성화 (인스턴스 레벨 패치)
  - save_weights no-op      : 가중치 누설 방지
  - on_episode_done pass    : 에피소드 종료 시점 학습/저장 비활성화

torch 의존성: RLBossBotTorch 를 lazy import 하므로 모듈 import 자체는 torch 없이도
안전. PastBossOpponent 인스턴스화 시점에 torch 필요 (training VM 에서만 사용).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.bot_interface import BotInterface

from bots.boss.league import LeagueEntry, ensure_local

logger = logging.getLogger("past_boss")


class PastBossOpponent(BotInterface):
    """League 체크포인트를 frozen 추론 모드로 wrapping 한 보스 상대."""

    def __init__(
        self,
        bot_id: str,
        league_entry: LeagueEntry,
        seed: Optional[int] = None,
        device: Optional[str] = None,
    ):
        self._bot_id = bot_id
        self._entry  = league_entry

        # 1) 로컬에 체크포인트 확보 (필요 시 GCS 다운로드)
        ckpt_path = ensure_local(league_entry)
        if ckpt_path is None or not ckpt_path.exists():
            raise FileNotFoundError(
                f"League 체크포인트 확보 실패: {league_entry.filename}"
            )

        # 2) RLBossBotTorch lazy import (torch 미설치 환경 보호)
        from bots.boss.rl_boss_bot_torch import RLBossBotTorch

        self._boss = RLBossBotTorch(
            bot_id=bot_id,
            seed=seed,
            weights_path=ckpt_path,
            epsilon_override=0.0,   # deterministic greedy
            device=device,
        )

        # 3) 학습/저장 메서드를 인스턴스 레벨에서 no-op 처리.
        #    클래스 레벨 패치는 같은 클래스의 학습 보스 인스턴스에도 영향을 주므로
        #    반드시 인스턴스 attribute 로만 덮어쓴다.
        self._boss._learn        = lambda: None
        self._boss.save_weights  = lambda path=None: None

        # 4) torch eval 모드 (Dropout/BatchNorm 비활성 — 우리 모델엔 없지만 안전)
        try:
            self._boss._online.eval()
            self._boss._target.eval()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 메타데이터
    # ------------------------------------------------------------------ #

    @property
    def bot_id(self) -> str:
        return self._bot_id

    @property
    def generation(self) -> int:
        return self._entry.generation

    @property
    def entry(self) -> LeagueEntry:
        return self._entry

    # ------------------------------------------------------------------ #
    # BotInterface 위임
    # ------------------------------------------------------------------ #

    def choose_spawn(self, map_info: dict):
        return self._boss.choose_spawn(map_info)

    def get_action(self, state: dict) -> str:
        # 내부 _learn 은 no-op 라 buffer push 만 발생.
        # buffer 누수 방지를 위해 prev_state 초기화하여 push 자체를 건너뛴다.
        self._boss._prev_phi   = None
        self._boss._prev_state = None
        return self._boss.get_action(state)

    def reset_for_episode(self) -> None:
        self._boss.reset_for_episode()

    def on_episode_done(self, rank: int, n_bots: int) -> None:
        """학습·저장 모두 비활성 — episode_count 도 증가시키지 않는다."""
        # 의도적으로 self._boss.on_episode_done 호출하지 않음
        return


# ---------------------------------------------------------------------------
# 편의 함수
# ---------------------------------------------------------------------------

def from_entry(
    entry: LeagueEntry,
    bot_id: Optional[str] = None,
    seed: Optional[int] = None,
    device: Optional[str] = None,
) -> Optional[PastBossOpponent]:
    """LeagueEntry → PastBossOpponent 변환. 실패 시 None (로그만 남김)."""
    try:
        bid = bot_id or f"보스_g{entry.generation}"
        return PastBossOpponent(bid, entry, seed=seed, device=device)
    except FileNotFoundError as exc:
        logger.warning("past_boss.from_entry: %s", exc)
        return None
    except RuntimeError as exc:
        # torch 미설치 등
        logger.warning("past_boss.from_entry: 로드 실패 — %s", exc)
        return None
    except Exception as exc:
        logger.error("past_boss.from_entry: 예외 — %s", exc)
        return None

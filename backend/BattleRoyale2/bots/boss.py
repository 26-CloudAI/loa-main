"""보스전 보스 봇 — 난이도별(하/중/상).

★ 운영 보스 로직은 여기에 작성하세요. ★
- 각 난이도 클래스의 `get_action(state)` 안에 보스 행동을 채우면 됩니다.
- `state`(봇 시점 게임 상태)·반환 `action` dict 형식은 유저 봇과 100% 동일:
  - 형식/예시: `BattleRoyale2/bots/user_template.py`, `bots/mad_dog.py`
  - 필드 설명: GAME_RULES.md §9.1 / PROTOCOL.md §3.4
- 허용 동작: move_dir/aim_dir(단위벡터), attack/guard/dash/pickup/use_potion(bool).
- 빈 dict({}) 반환 시 엔진이 STAY(가만히)로 처리.
- 난이도별 stat 강화(HP/공격 등)는 서버가 boss_rules 로 클라에 적용하므로 여기선 '행동'만 작성.

현재는 임시로 세 난이도 모두 가만히 있음(STAY). 운영 코드로 get_action 을 교체하세요.
ws_server 가 게임 생성 시 난이도에 맞는 클래스를 골라 bot_id="boss" 로 소환합니다.
"""
from __future__ import annotations

from typing import Any

from BattleRoyale2.src.arena.bot_interface import BattleRoyale2DBot


class _BossBase(BattleRoyale2DBot):
    """보스 봇 공통 베이스 — bot_id 고정('boss'). 난이도 클래스가 get_action 을 오버라이드."""

    def __init__(self, bot_id: str = "boss", seed: int | None = None):
        self._bot_id = bot_id
        self._seed = seed

    @property
    def bot_id(self) -> str:
        return self._bot_id

    def choose_spawn(self, map_info: dict[str, Any]):
        # 필요하면 보스 스폰 위치 지정. None 이면 엔진 랜덤.
        return None

    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {}   # STAY (임시)


class BossEasyBot(_BossBase):
    """난이도 하 보스."""
    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO(운영): 난이도 '하' 보스 로직 작성
        return {}


class BossMediumBot(_BossBase):
    """난이도 중 보스."""
    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO(운영): 난이도 '중' 보스 로직 작성
        return {}


class BossHardBot(_BossBase):
    """난이도 상 보스."""
    def get_action(self, state: dict[str, Any]) -> dict[str, Any]:
        # TODO(운영): 난이도 '상' 보스 로직 작성 (예: 학습 가중치 로드 등)
        return {}


# 난이도 라벨 → 보스 봇 클래스. ws_server 가 이 매핑으로 보스를 소환.
BOSS_BOT_BY_DIFFICULTY: dict[str, type[BattleRoyale2DBot]] = {
    "하": BossEasyBot,
    "중": BossMediumBot,
    "상": BossHardBot,
}

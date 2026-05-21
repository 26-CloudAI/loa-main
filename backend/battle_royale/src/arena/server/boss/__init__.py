"""AI Arena — 보스전 전용 서버 로직.

app.py에서 보스전 관련 기능을 격리한 패키지.
  - config: 보스전 GameConfig 및 상수 (BOSS_MAX_USER_BOTS)
  - bot_factory: 난이도별 보스봇 생성 + RL 싱글톤/락 관리
  - result_handler: 보스전 결과(boss_won) DB 기록
"""

from .bot_factory import BOSS_BOT_LOCK, create_boss_bot
from .config import BOSS_MAX_USER_BOTS, boss_battle_config
from .result_handler import record_boss_result

__all__ = [
    "BOSS_BOT_LOCK",
    "BOSS_MAX_USER_BOTS",
    "boss_battle_config",
    "create_boss_bot",
    "record_boss_result",
]

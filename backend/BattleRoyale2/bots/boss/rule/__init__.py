"""BattleRoyale2 룰베이스 보스 봇 (난이도별).

옛 backend/battle_royale/bots/boss/rule_boss_bot.py 의 의사결정 트리·임계값을
BR2 연속 2D 인터페이스로 1:1 포팅한 버전.
"""

from .easy import RuleBossEasyBR2
from .medium import RuleBossMediumBR2

__all__ = ["RuleBossEasyBR2", "RuleBossMediumBR2"]

"""BattleRoyale2 — 콜드스타트 샘플 봇."""

from .herbivore import HerbivoreBot
from .mad_dog import MadDogBot
from .camper import CamperBot
from .boss import BossEasyBot, BossMediumBot, BossHardBot, BOSS_BOT_BY_DIFFICULTY

__all__ = [
    "HerbivoreBot", "MadDogBot", "CamperBot",
    "BossEasyBot", "BossMediumBot", "BossHardBot", "BOSS_BOT_BY_DIFFICULTY",
]
